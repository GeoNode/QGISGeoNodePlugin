"""Async transport primitive built on top of QGIS' network access manager.

Phase 1 of the networking refactor. The classes here coexist with the legacy
``qgis_geonode.network`` / ``qgis_geonode.tasks.network_task`` modules; call
sites are migrated in later phases.

Design points worth noting (these are bugs in the legacy code that we must
not reintroduce):

* We connect to the per-reply ``finished`` signal, never to the global NAM
  ``finished`` signal. The legacy ``NetworkRequestTask`` connected to the
  singleton signal and never disconnected, leaking slots on every request.
* We set the timeout per-request via ``QNetworkRequest.setTransferTimeout``
  (available since Qt 5.15, which matches our ``qgisMinimumVersion = 3.34``).
  We never call ``QgsNetworkAccessManager.setTimeout`` because that mutates
  the global QGIS state.
* The ``QNetworkReply`` is ``deleteLater()``'d once and ownership is
  explicit; ``finished`` is emitted exactly once even if ``cancel()`` is
  called after completion.
"""

import dataclasses
import enum
import json
import typing

import qgis.core
from qgis.PyQt import (
    QtCore,
    QtNetwork,
)

from .errors import ErrorKind, NetworkError


class HttpMethod(enum.Enum):
    """HTTP verbs supported by :class:`Request`."""

    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    PATCH = "PATCH"
    DELETE = "DELETE"


# ``payload`` is intentionally typed loosely — POST/PUT accept bytes, str
# (utf-8 encoded), dict (JSON-encoded), or QHttpMultiPart (POST only).
PayloadType = typing.Union[
    bytes, str, typing.Dict[str, typing.Any], QtNetwork.QHttpMultiPart, None
]


@dataclasses.dataclass()
class RequestToPerform:
    """Description of an HTTP request to be sent."""

    url: QtCore.QUrl
    method: HttpMethod = HttpMethod.GET
    payload: PayloadType = None
    content_type: typing.Optional[str] = None
    extra_headers: typing.Optional[typing.Dict[str, str]] = None


@dataclasses.dataclass()
class NetworkResponse:
    """Result delivered through :attr:`Request.finished`.

    Either ``error`` is ``None`` (success path) or it carries a populated
    :class:`NetworkError`. ``http_status`` may still be set on the error
    path when the server returned a response (typically 4xx/5xx).
    """

    request: RequestToPerform
    http_status: typing.Optional[int] = None
    http_reason: typing.Optional[str] = None
    body: bytes = b""
    error: typing.Optional[NetworkError] = None

    @property
    def ok(self) -> bool:
        return self.error is None


def _build_qt_error_map() -> typing.Dict["QtNetwork.QNetworkReply.NetworkError", str]:
    """Map ``QNetworkReply.NetworkError`` enum values to their symbolic names.

    Adapted from the legacy ``network.py`` so error reporting can stay
    self-describing without hard-coding numeric enum values.
    """

    result = {}
    for property_name in dir(QtNetwork.QNetworkReply):
        value = getattr(QtNetwork.QNetworkReply, property_name)
        if isinstance(value, QtNetwork.QNetworkReply.NetworkError):
            result[value] = property_name
    return result


_QT_ERROR_MAP: typing.Dict[
    "QtNetwork.QNetworkReply.NetworkError", str
] = _build_qt_error_map()


def _coerce_payload(
    payload: PayloadType,
    content_type: typing.Optional[str],
    allow_multipart: bool,
) -> typing.Tuple[typing.Union[bytes, QtNetwork.QHttpMultiPart], typing.Optional[str],]:
    """Coerce the user-supplied payload into something the NAM can send.

    Returns the coerced payload and an optional content-type override (used
    when we JSON-encode a dict and the caller did not supply one).
    """

    if payload is None:
        return b"", content_type
    if isinstance(payload, QtNetwork.QHttpMultiPart):
        if not allow_multipart:
            raise TypeError(
                "QHttpMultiPart payloads are only supported for POST requests"
            )
        return payload, content_type
    if isinstance(payload, bytes):
        return payload, content_type
    if isinstance(payload, str):
        return payload.encode("utf-8"), content_type
    if isinstance(payload, dict):
        encoded = json.dumps(payload).encode("utf-8")
        if content_type is None:
            content_type = "application/json"
        return encoded, content_type
    raise TypeError(f"Unsupported payload type: {type(payload).__name__}")


class Request(QtCore.QObject):
    """Single-request async wrapper around ``QgsNetworkAccessManager``.

    Lifecycle:

    1. Create the object (cheap — no NAM lookup yet).
    2. ``send(request, authcfg, timeout_ms)`` — fires the request and returns
       immediately.
    3. The ``finished`` signal is emitted exactly once with a
       :class:`NetworkResponse`.

    ``cancel()`` aborts an in-flight reply. The pending ``finished`` will
    still fire, with ``error.kind == ErrorKind.CANCELLED``.
    """

    finished = QtCore.pyqtSignal(object)  # NetworkResponse

    def __init__(self, parent: typing.Optional[QtCore.QObject] = None) -> None:
        super().__init__(parent)
        self._reply: typing.Optional[QtNetwork.QNetworkReply] = None
        self._request: typing.Optional[RequestToPerform] = None
        self._completed: bool = False
        self._cancelled_by_user: bool = False

    # ------------------------------------------------------------------ public

    def send(
        self,
        request: RequestToPerform,
        authcfg: typing.Optional[str] = None,
        timeout_ms: int = 10000,
    ) -> None:
        if self._reply is not None or self._completed:
            raise RuntimeError(
                "Request instances are single-shot; create a new one "
                "for each request"
            )
        self._request = request

        qnetwork_request = QtNetwork.QNetworkRequest(request.url)
        if request.content_type is not None:
            qnetwork_request.setHeader(
                QtNetwork.QNetworkRequest.ContentTypeHeader,
                request.content_type,
            )
        if request.extra_headers:
            for header_name, header_value in request.extra_headers.items():
                qnetwork_request.setRawHeader(
                    header_name.encode("utf-8"),
                    header_value.encode("utf-8"),
                )
        # Per-request timeout — does NOT mutate the NAM's global state, unlike
        # the legacy code's ``nam.setTimeout(...)``.
        qnetwork_request.setTransferTimeout(int(timeout_ms))

        if authcfg:
            auth_manager = qgis.core.QgsApplication.authManager()
            auth_added, _ = auth_manager.updateNetworkRequest(qnetwork_request, authcfg)
            if not auth_added:
                error = NetworkError(
                    kind=ErrorKind.AUTH,
                    url=request.url.toString(),
                    message=(f"QGIS auth manager rejected auth config " f"{authcfg!r}"),
                )
                response = NetworkResponse(request=request, error=error)
                # Make the failure asynchronous so callers see the same
                # signal-then-emit ordering as the success path.
                QtCore.QTimer.singleShot(0, lambda r=response: self._emit_async(r))
                return

        nam = qgis.core.QgsNetworkAccessManager.instance()
        try:
            self._reply = self._dispatch(nam, qnetwork_request, request)
        except Exception as exc:  # pragma: no cover - defensive
            error = NetworkError(
                kind=ErrorKind.TRANSPORT,
                url=request.url.toString(),
                message=f"Failed to dispatch request: {exc!r}",
            )
            response = NetworkResponse(request=request, error=error)
            QtCore.QTimer.singleShot(0, lambda r=response: self._emit_async(r))
            return

        # IMPORTANT: connect to the reply's own ``finished`` signal, not the
        # NAM's global ``finished`` signal. See the legacy bug in
        # ``tasks/network_task.py:39-44``.
        self._reply.finished.connect(self._on_reply_finished)

    def cancel(self) -> None:
        if self._completed:
            return
        self._cancelled_by_user = True
        if self._reply is not None and self._reply.isRunning():
            self._reply.abort()

    # ------------------------------------------------------------ dispatch

    def _dispatch(
        self,
        nam: "qgis.core.QgsNetworkAccessManager",
        qnetwork_request: QtNetwork.QNetworkRequest,
        request: RequestToPerform,
    ) -> QtNetwork.QNetworkReply:
        method = request.method
        if method == HttpMethod.GET:
            return nam.get(qnetwork_request)

        if method == HttpMethod.DELETE:
            return nam.deleteResource(qnetwork_request)

        # Methods that carry a body.
        allow_multipart = method == HttpMethod.POST
        payload, ct_override = _coerce_payload(
            request.payload,
            request.content_type,
            allow_multipart=allow_multipart,
        )
        if ct_override is not None and request.content_type is None:
            qnetwork_request.setHeader(
                QtNetwork.QNetworkRequest.ContentTypeHeader, ct_override
            )

        if method == HttpMethod.POST:
            if isinstance(payload, QtNetwork.QHttpMultiPart):
                reply = nam.post(qnetwork_request, payload)
                # The NAM does not take ownership of the multipart in all Qt
                # builds; tie its lifetime to the reply.
                payload.setParent(reply)
                return reply
            return nam.post(qnetwork_request, payload)

        if method == HttpMethod.PUT:
            return nam.put(qnetwork_request, payload)

        if method == HttpMethod.PATCH:
            verb = QtCore.QByteArray(b"PATCH")
            return nam.sendCustomRequest(qnetwork_request, verb, payload)

        raise NotImplementedError(f"Unsupported HTTP method: {method}")

    # ------------------------------------------------------------ completion

    def _on_reply_finished(self) -> None:
        if self._completed:
            return
        reply = self._reply
        request = self._request
        assert reply is not None and request is not None  # for type checkers

        http_status = reply.attribute(QtNetwork.QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        http_reason = reply.attribute(
            QtNetwork.QNetworkRequest.Attribute.HttpReasonPhraseAttribute
        )
        body_bytes = bytes(reply.readAll().data())

        qt_error_value = reply.error()
        qt_error_name: typing.Optional[str] = None
        error: typing.Optional[NetworkError] = None

        if qt_error_value != QtNetwork.QNetworkReply.NetworkError.NoError:
            qt_error_name = _QT_ERROR_MAP.get(qt_error_value, str(qt_error_value))

        # Classify the error.
        if qt_error_value == QtNetwork.QNetworkReply.NetworkError.NoError:
            # The reply succeeded at the transport layer. The HTTP status may
            # still be a 4xx/5xx — surface that as an HTTP error.
            if isinstance(http_status, int) and http_status >= 400:
                error = NetworkError(
                    kind=ErrorKind.HTTP,
                    url=request.url.toString(),
                    message=(
                        f"HTTP {http_status}"
                        f"{' ' + http_reason if http_reason else ''}"
                    ),
                    http_status=http_status,
                    body=body_bytes,
                )
        elif qt_error_value == QtNetwork.QNetworkReply.NetworkError.OperationCanceledError:
            # The reply was aborted. This happens both on explicit
            # ``cancel()`` and on transfer timeout (Qt 5.15 fires the same
            # error code in both cases).
            if self._cancelled_by_user:
                error = NetworkError(
                    kind=ErrorKind.CANCELLED,
                    url=request.url.toString(),
                    message="Request was cancelled by the caller",
                    qt_error=qt_error_name,
                    http_status=(http_status if isinstance(http_status, int) else None),
                    body=body_bytes or None,
                )
            else:
                error = NetworkError(
                    kind=ErrorKind.TIMEOUT,
                    url=request.url.toString(),
                    message="Request timed out",
                    qt_error=qt_error_name,
                    http_status=(http_status if isinstance(http_status, int) else None),
                    body=body_bytes or None,
                )
        elif qt_error_value in (
            QtNetwork.QNetworkReply.NetworkError.TimeoutError,
            QtNetwork.QNetworkReply.NetworkError.ProxyTimeoutError,
        ):
            error = NetworkError(
                kind=ErrorKind.TIMEOUT,
                url=request.url.toString(),
                message="Request timed out",
                qt_error=qt_error_name,
                http_status=(http_status if isinstance(http_status, int) else None),
                body=body_bytes or None,
            )
        else:
            # If the server still produced an HTTP status (4xx/5xx) treat it
            # as HTTP; otherwise it's a transport-level failure.
            if isinstance(http_status, int) and http_status >= 400:
                error = NetworkError(
                    kind=ErrorKind.HTTP,
                    url=request.url.toString(),
                    message=(
                        f"HTTP {http_status}"
                        f"{' ' + http_reason if http_reason else ''}"
                    ),
                    http_status=http_status,
                    qt_error=qt_error_name,
                    body=body_bytes,
                )
            else:
                error = NetworkError(
                    kind=ErrorKind.TRANSPORT,
                    url=request.url.toString(),
                    message=reply.errorString() or "Network transport error",
                    qt_error=qt_error_name,
                    http_status=(http_status if isinstance(http_status, int) else None),
                    body=body_bytes or None,
                )

        response = NetworkResponse(
            request=request,
            http_status=(http_status if isinstance(http_status, int) else None),
            http_reason=(http_reason if isinstance(http_reason, str) else None),
            body=body_bytes,
            error=error,
        )

        # Tear down before emitting so listeners can synchronously start a
        # new request without tripping over our state.
        self._teardown_reply()
        self._completed = True
        self.finished.emit(response)

    def _teardown_reply(self) -> None:
        reply = self._reply
        if reply is None:
            return
        try:
            reply.finished.disconnect(self._on_reply_finished)
        except (TypeError, RuntimeError):
            # Already disconnected or reply being torn down.
            pass
        reply.deleteLater()
        self._reply = None

    def _emit_async(self, response: NetworkResponse) -> None:
        if self._completed:
            return
        self._completed = True
        self.finished.emit(response)


class RequestBatch(QtCore.QObject):
    """Coordinator that fans out N parallel :class:`Request` calls.

    The ``finished`` signal carries a list of :class:`NetworkResponse` in the
    same order as the input list. Cancellation aborts every in-flight child;
    each cancelled child contributes a ``CANCELLED`` response.
    """

    finished = QtCore.pyqtSignal(list)

    def __init__(self, parent: typing.Optional[QtCore.QObject] = None) -> None:
        super().__init__(parent)
        self._children: typing.List[Request] = []
        self._responses: typing.List[typing.Optional[NetworkResponse]] = []
        self._done: int = 0
        self._completed: bool = False
        self._dispatched: bool = False

    def send(
        self,
        requests: typing.List[RequestToPerform],
        authcfg: typing.Optional[str] = None,
        timeout_ms: int = 10000,
    ) -> None:
        if self._dispatched:
            raise RuntimeError(
                "RequestBatch instances are single-shot; create a "
                "new one for each fan-out"
            )
        self._dispatched = True

        if not requests:
            QtCore.QTimer.singleShot(0, self._emit_empty)
            return

        self._responses = [None] * len(requests)
        for index, request in enumerate(requests):
            child = Request(parent=self)
            self._children.append(child)
            child.finished.connect(
                lambda response, i=index: self._on_child_finished(i, response)
            )
            child.send(request, authcfg=authcfg, timeout_ms=timeout_ms)

    def cancel(self) -> None:
        for child in self._children:
            child.cancel()

    # ------------------------------------------------------------ internals

    def _on_child_finished(self, index: int, response: NetworkResponse) -> None:
        if self._completed:
            return
        self._responses[index] = response
        self._done += 1
        if self._done >= len(self._responses):
            self._completed = True
            # Cast away the Optional now that every slot is filled.
            final: typing.List[NetworkResponse] = [
                r for r in self._responses if r is not None
            ]
            self.finished.emit(final)

    def _emit_empty(self) -> None:
        if self._completed:
            return
        self._completed = True
        self.finished.emit([])
