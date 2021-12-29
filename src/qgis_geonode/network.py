import dataclasses
import enum
import json
import tempfile
import shutil
import typing
from contextlib import contextmanager
from functools import partial
from pathlib import Path

import qgis.core
from PyQt5 import QtNetwork
from qgis.PyQt import (
    QtCore,
    QtNetwork,
)

from .utils import log

UNSUPPORTED_REMOTE = "unsupported"


class HttpMethod(enum.Enum):
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    PATCH = "PATCH"


@dataclasses.dataclass()
class ParsedNetworkReply:
    http_status_code: int
    http_status_reason: str
    qt_error: typing.Optional[str]
    response_body: QtCore.QByteArray


@dataclasses.dataclass()
class RequestToPerform:
    url: QtCore.QUrl
    method: typing.Optional[HttpMethod] = HttpMethod.GET
    payload: typing.Optional[str] = None
    content_type: typing.Optional[str] = None


@dataclasses.dataclass()
class EventLoopResult:
    result: typing.Optional[bool]


def _get_qt_network_reply_error_mapping() -> typing.Dict:
    """Workaround for accessing unsubscriptable enum types of QNetworkReply.NetworkError

    adapted from https://stackoverflow.com/a/39677321

    """

    result = {}
    for property_name in dir(QtNetwork.QNetworkReply):
        value = getattr(QtNetwork.QNetworkReply, property_name)
        if isinstance(value, QtNetwork.QNetworkReply.NetworkError):
            result[value] = property_name
    return result


_Q_NETWORK_REPLY_ERROR_MAP: typing.Final[
    typing.Dict[QtNetwork.QNetworkReply.NetworkError, str]
] = _get_qt_network_reply_error_mapping()


@contextmanager
def wait_for_signal(
    signal, timeout: int = 10000
) -> typing.ContextManager[EventLoopResult]:
    """Fire up a custom event loop and wait for the input signal to be emitted

    This function allows running QT async code in a blocking fashion. It works by
    spawning a Qt event loop. This custom loop has its `quit()` slot bound to the
    input `signal`. The event loop is `exec_`'ed, thus blocking the current
    thread until the the input `signal` is emitted.

    The main purpose for this context manager is to allow using Qt network requests
    inside a QgsTask. Since QgsTask is already running in the background, we simplify
    the handling of network requests and responses in order to make the code easier to
    grasp.

    """

    loop = QtCore.QEventLoop()
    signal.connect(loop.quit)
    loop_result = EventLoopResult(result=None)
    yield loop_result
    QtCore.QTimer.singleShot(timeout, partial(_forcibly_terminate_loop, loop))
    loop_result.result = not bool(loop.exec_())


def _forcibly_terminate_loop(loop: QtCore.QEventLoop):
    log("Forcibly ending event loop...")
    loop.exit(1)


class NetworkRequestTask(qgis.core.QgsTask):
    authcfg: typing.Optional[str]
    network_task_timeout: int
    network_access_manager: qgis.core.QgsNetworkAccessManager
    requests_to_perform: typing.List[RequestToPerform]
    response_contents: typing.List[typing.Optional[ParsedNetworkReply]]
    _num_finished: int
    _pending_replies: typing.Dict[int, typing.Tuple[int, QtNetwork.QNetworkReply]]

    _all_requests_finished = QtCore.pyqtSignal()
    task_done = QtCore.pyqtSignal(bool)

    def __init__(
        self,
        requests_to_perform: typing.List[RequestToPerform],
        network_task_timeout: int,
        authcfg: typing.Optional[str] = None,
        description: typing.Optional[str] = "AnotherNetworkRequestTask",
    ):
        """A QGIS task to run multiple network requests in parallel."""
        super().__init__(description)
        self.authcfg = authcfg
        self.network_task_timeout = network_task_timeout
        self.requests_to_perform = requests_to_perform[:]
        self.response_contents = [None] * len(requests_to_perform)
        self._num_finished = 0
        self._pending_replies = {}
        self.network_access_manager = qgis.core.QgsNetworkAccessManager.instance()
        self.network_access_manager.requestTimedOut.connect(
            self._handle_request_timed_out
        )
        self.network_access_manager.finished.connect(self._handle_request_finished)
        self.network_access_manager.authBrowserAborted.connect(
            self._handle_auth_browser_aborted
        )

    def run(self) -> bool:
        """Run the QGIS task

        This method is called by the QGIS task manager.

        Implementation uses a custom Qt event loop that waits until
        all of the HTTP requests have been performed. This is done by waiting on the
        `self._all_requests_finished` signal to be emitted.

        """

        if len(self.requests_to_perform) == 0:  # there is nothing to do
            result = False
        else:
            with wait_for_signal(
                self._all_requests_finished,
                timeout=self.network_task_timeout * len(self.requests_to_perform),
            ) as event_loop_result:
                for index, request_params in enumerate(self.requests_to_perform):
                    request = create_request(
                        request_params.url, request_params.content_type
                    )
                    if self.authcfg:
                        auth_manager = qgis.core.QgsApplication.authManager()
                        auth_added, _ = auth_manager.updateNetworkRequest(
                            request, self.authcfg
                        )
                    else:
                        auth_added = True
                    if auth_added:
                        qt_reply = self._dispatch_request(
                            request, request_params.method, request_params.payload
                        )
                        # QGIS adds a custom `requestId` property to all requests made by
                        # its network access manager - this can be used to keep track of
                        # replies
                        request_id = qt_reply.property("requestId")
                        self._pending_replies[request_id] = (index, qt_reply)
                    else:
                        self._all_requests_finished.emit()
            loop_forcibly_ended = not bool(event_loop_result.result)
            if loop_forcibly_ended:
                result = False
            else:
                result = self._num_finished >= len(self.requests_to_perform)
        return result

    def finished(self, result: bool) -> None:
        """This method is called by the QGIS task manager when this task is finished"""
        # This class emits the `task_done` signal in order to have a unified way to
        # deal with the various types of errors that can arise. The alternative would
        # have been to rely on the base class' `taskCompleted` and `taskTerminated`
        # signals
        if result:
            for index, response in enumerate(self.response_contents):
                if response is None:
                    final_result = False
                    break
                elif response.qt_error is not None:
                    final_result = False
                    break
            else:
                final_result = result
        else:
            final_result = result
        # for _, qt_reply in self._pending_replies.values():
        #     qt_reply.deleteLater()
        self.task_done.emit(final_result)

    def _dispatch_request(
        self,
        request: QtNetwork.QNetworkRequest,
        method: HttpMethod,
        payload: typing.Optional[typing.Union[str, QtNetwork.QHttpMultiPart]],
    ) -> QtNetwork.QNetworkReply:
        if method == HttpMethod.GET:
            reply = self.network_access_manager.get(request)
        elif method == HttpMethod.POST:
            reply = self.network_access_manager.post(request, payload)
        elif method == HttpMethod.PUT:
            data_ = QtCore.QByteArray(payload.encode())
            reply = self.network_access_manager.put(request, data_)
        elif method == HttpMethod.PATCH:
            data_ = QtCore.QByteArray(payload.encode())
            # QNetworkAccess manager does not have a patch() method
            reply = self.network_access_manager.sendCustomRequest(
                request, QtCore.QByteArray(HttpMethod.PATCH.value.encode()), data_
            )
        else:
            raise NotImplementedError
        return reply

    def _handle_request_finished(self, qgis_reply: qgis.core.QgsNetworkReplyContent):
        """Handle the finishing of a network request

        This slot is triggered when the network access manager emits the ``finished``
        signal. The custom QGIS network access manager provides an instance of
        ``QgsNetworkContentReply`` as an argument to this method. Note that this is not
        the same as the vanilla QNetworkReply - notoriously it seems to not be possible
        to retrieve the HTTP response body from this type of instance. Therefore, this
        method retrieves the original QNetworkReply (by comparing the reply's id) and
        then uses that to gain access to the response body.

        """

        try:
            index, qt_reply = self._pending_replies[qgis_reply.requestId()]
        except KeyError:
            pass  # we are not managing this request, ignore
        else:
            parsed = parse_qt_network_reply(qt_reply)
            self.response_contents[index] = parsed
            self._num_finished += 1
            if self._num_finished >= len(self.requests_to_perform):
                self._all_requests_finished.emit()

    def _handle_request_timed_out(
        self, request_params: qgis.core.QgsNetworkRequestParameters
    ) -> None:
        log(f"Request with id: {request_params.requestId()} has timed out")
        try:
            index, qt_reply = self._pending_replies[request_params.requestId()]
        except KeyError:
            pass  # we are not managing this request, ignore
        else:
            self.response_contents[index] = None
            self._num_finished += 1
            if self._num_finished >= len(self.requests_to_perform):
                self._all_requests_finished.emit()

    def _handle_auth_browser_aborted(self):
        log("inside _handle_auth_browser_aborted")


def deserialize_json_response(
    contents: QtCore.QByteArray,
) -> typing.Optional[typing.Union[typing.List, typing.Dict]]:
    decoded_contents: str = contents.data().decode()
    try:
        contents = json.loads(decoded_contents)
    except json.JSONDecodeError as exc:
        log(f"JSON decode error - decoded_contents: {decoded_contents}")
        log(exc, debug=False)
        contents = None
    return contents


def parse_qt_network_reply(reply: QtNetwork.QNetworkReply) -> ParsedNetworkReply:
    http_status_code = reply.attribute(
        QtNetwork.QNetworkRequest.HttpStatusCodeAttribute
    )
    http_status_reason = reply.attribute(
        QtNetwork.QNetworkRequest.HttpReasonPhraseAttribute
    )
    error = reply.error()
    if error == QtNetwork.QNetworkReply.NoError:
        qt_error = None
    else:
        qt_error = _Q_NETWORK_REPLY_ERROR_MAP[error]
    body = reply.readAll()
    return ParsedNetworkReply(
        http_status_code=http_status_code,
        http_status_reason=http_status_reason,
        qt_error=qt_error,
        response_body=body,
    )


def parse_network_reply(reply: qgis.core.QgsNetworkReplyContent) -> ParsedNetworkReply:
    http_status_code = reply.attribute(
        QtNetwork.QNetworkRequest.HttpStatusCodeAttribute
    )
    http_status_reason = reply.attribute(
        QtNetwork.QNetworkRequest.HttpReasonPhraseAttribute
    )
    error = reply.error()
    if error == QtNetwork.QNetworkReply.NoError:
        qt_error = None
    else:
        qt_error = _Q_NETWORK_REPLY_ERROR_MAP[error]
    body = reply.content()
    return ParsedNetworkReply(
        http_status_code=http_status_code,
        http_status_reason=http_status_reason,
        qt_error=qt_error,
        response_body=body,
    )


class ApiClientDiscovererTask(qgis.core.QgsTask):
    discovery_result: typing.Optional[str]

    discovery_finished = QtCore.pyqtSignal(str)

    def __init__(
        self, base_url: str, description: typing.Optional[str] = "MyApiDiscovererTask"
    ):
        """A task to autodetect the best API client to use for the provided base_url."""
        super().__init__(description)
        self.base_url = base_url
        self.discovery_result = None

    def run(self) -> bool:
        network_manager = qgis.core.QgsNetworkAccessManager()
        # DO NOT CHANGE THE ORDER OF THE LIST BELOW! Otherwise detection will not work OK
        urls_to_try = [
            (
                f"{self.base_url}/api/v2/datasets/",
                "qgis_geonode.apiclient.version_postv2.GeonodePostV2ApiClient",
            ),
            # TODO: Implement the other api clients
            (f"{self.base_url}/api/v2/", "qgis_geonode.apiclient.apiv2"),
            (
                f"{self.base_url}/api/",
                "qgis_geonode.apiclient.version_legacy.GeonodeLegacyApiClient",
            ),
        ]
        for url, client_class_path in urls_to_try:
            log(f"Performing request for {url!r}...")
            request = QtNetwork.QNetworkRequest(QtCore.QUrl(url))
            reply_content = network_manager.blockingGet(request)
            parsed_reply = parse_network_reply(reply_content)
            if parsed_reply.http_status_code == 200:
                self.discovery_result = client_class_path
                result = True
                break
        else:
            self.discovery_result = UNSUPPORTED_REMOTE
            result = False
        return result

    def finished(self, result: bool):
        self.discovery_finished.emit(self.discovery_result)


def create_request(
    url: QtCore.QUrl, content_type: typing.Optional[str] = None
) -> QtNetwork.QNetworkRequest:
    request = QtNetwork.QNetworkRequest(url)
    if content_type is not None:
        request.setHeader(QtNetwork.QNetworkRequest.ContentTypeHeader, content_type)
    return request


def sanitize_layer_name(name: str) -> str:
    chars_to_replace = [
        ">",
        "<",
        "|",
        " ",
    ]
    return "".join(c if c not in chars_to_replace else "_" for c in name)
