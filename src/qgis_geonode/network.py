import dataclasses
import json
import typing
from contextlib import contextmanager
from functools import partial

import qgis.core
from PyQt5 import QtNetwork
from qgis.PyQt import (
    QtCore,
    QtNetwork,
)

from .utils import log


@dataclasses.dataclass()
class ParsedNetworkReply:
    http_status_code: int
    http_status_reason: str
    qt_error: str
    response_body: str


@dataclasses.dataclass()
class RequestToPerform:
    url: QtCore.QUrl
    payload: typing.Optional[str] = None


class MultipleNetworkFetcherTask(qgis.core.QgsTask):

    response_contents: typing.List[ParsedNetworkReply]
    _exceptions_raised: typing.List[str]

    all_finished = QtCore.pyqtSignal(bool)

    def __init__(
        self,
        requests_to_perform: typing.List[RequestToPerform],
        authcfg: typing.Optional[str],
        description: typing.Optional[str] = "MyMultipleNetworkfetcherTask",
    ):
        """QGIS Task that is able to perform network requests

        Implementation uses QgsNetworkAccessManager's blocking GET and POST in order
        to perform blocking requests inside the task's run() method.

        """

        super().__init__(description)
        self.requests_to_perform = requests_to_perform
        self.authcfg = authcfg
        self.response_contents = []
        self._exceptions_raised = []

    def run(self) -> bool:
        result = True
        network_manager = qgis.core.QgsNetworkAccessManager()
        for request_params in self.requests_to_perform:
            log(f"Performing request for {request_params.url}...")
            request = QtNetwork.QNetworkRequest(request_params.url)
            if request_params.payload is None:
                reply_content = network_manager.blockingGet(request, self.authcfg)
            else:
                reply_content = network_manager.blockingPost(
                    request, request_params.payload, self.authcfg
                )
            try:
                parsed_reply = parse_network_reply(reply_content)
            except AttributeError as exc:
                result = False
                self._exceptions_raised.append(str(exc))
            else:
                if parsed_reply.qt_error is not None:
                    result = False
                self.response_contents.append(parsed_reply)
        return result

    def finished(self, result: bool):
        for index, exception_text in enumerate(self._exceptions_raised):
            log(
                f"There was a problem running request "
                f"{self.requests_to_perform[index]!r}: {exception_text}"
            )
        self.all_finished.emit(result)


@dataclasses.dataclass()
class EventLoopResult:
    result: typing.Optional[bool]


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
    log(f"About to start custom event loop...")
    loop_result.result = not bool(loop.exec_())
    log(f"Custom event loop ended, resuming...")


def _forcibly_terminate_loop(loop: QtCore.QEventLoop):
    log("Forcibly ending event loop...")
    loop.exit(1)


class SimplerNetworkFetcherTask(qgis.core.QgsTask):
    def __init__(
        self,
        request: QtNetwork.QNetworkRequest,
        request_payload: typing.Optional[str] = None,
    ):
        """
        Custom QgsTask that performs network requests

        This class is able to perform both GET and POST HTTP requests.

        It is needed because:

        - QgsNetworkContentFetcherTask only performs GET requests
        - QgsNetworkAcessManager.blockingPost() does not seem to handle redirects
          correctly

        Implementation is based on QgsNetworkContentFetcher. The run() method performs
        a normal async request using QtNetworkAccessManager's get() or post() methods.
        The resulting QNetworkReply instance has its `finished` signal be connected to
        a custom handler. The request is executed in scope of a custom Qt event loop,
        which blocks the current thread while the request is being processed.

        """

        super().__init__("QgisGeonodeNetworkFetcherTask")
        self.request = request
        self.request_payload = request_payload
        self.reply_content = None
        self.parsed_reply = None
        self.network_access_manager = qgis.core.QgsNetworkAccessManager.instance()
        # self.network_access_manager.setRedirectPolicy(
        #     QtNetwork.QNetworkRequest.NoLessSafeRedirectPolicy)
        self.network_access_manager.finished.connect(self._request_done)
        self._reply = None

    def run(self):
        with wait_for_signal(self.request_parsed) as loop_result:
            if self.request_payload is None:
                self._reply = self.network_access_manager.get(self.request)
            else:
                self._reply = self.network_access_manager.post(
                    self.request,
                    QtCore.QByteArray(self.request_payload.encode("utf-8")),
                )
        try:
            if loop_result.result:
                result = self.parsed_reply.qt_error is None
            else:
                result = False
            self._reply.deleteLater()
            self._reply = None
        except AttributeError:
            result = False
        return result

    def finished(self, result: bool):
        self.network_access_manager.finished.disconnect(self._request_done)
        log(f"Inside finished. Result: {result}")
        self.request_finished.emit()
        if not result:
            if self.parsed_reply is not None:
                self.api_client.error_received[str, int, str].emit(
                    self.parsed_reply.qt_error,
                    self.parsed_reply.http_status_code,
                    self.parsed_reply.http_status_reason,
                )
            else:
                self.api_client.error_received.emit("Problem parsing network reply")

    def _request_done(self, qgis_reply: qgis.core.QgsNetworkReplyContent):
        log(f"requested_url: {qgis_reply.request().url().toString()}")
        if self._reply is None:
            log(
                "Some other request was completed, probably authentication, "
                "ignoring..."
            )
        elif reply_matches(qgis_reply, self._reply):
            self.reply_content = self._reply.readAll()
            self.parsed_reply = parse_network_reply(qgis_reply)
            log(f"http_status_code: {self.parsed_reply.http_status_code}")
            log(f"qt_error: {self.parsed_reply.qt_error}")
            self.request_parsed.emit()
        else:
            log(f"qgis_reply did not match the original reply id, ignoring...")


def deserialize_json_response(
    contents: QtCore.QByteArray,
) -> typing.Optional[typing.Union[typing.List, typing.Dict]]:
    decoded_contents: str = contents.data().decode()
    try:
        contents = json.loads(decoded_contents)
    except json.JSONDecodeError as exc:
        log(f"decoded_contents: {decoded_contents}")
        log(exc, debug=False)
        contents = None
    return contents


class NetworkFetcherTask(qgis.core.QgsTask):
    api_client: "BaseGeonodeClient"
    authcfg: typing.Optional[str]
    description: str
    request: QtNetwork.QNetworkRequest
    request_payload: typing.Optional[str]
    reply_content: typing.Optional[QtCore.QByteArray]
    parsed_reply: typing.Optional[ParsedNetworkReply]
    redirect_policy: QtNetwork.QNetworkRequest.RedirectPolicy
    _reply: typing.Optional[QtNetwork.QNetworkReply]

    request_finished = QtCore.pyqtSignal()
    request_parsed = QtCore.pyqtSignal()

    def __init__(
        self,
        api_client: "BaseGeonodeClient",
        request: QtNetwork.QNetworkRequest,
        request_payload: typing.Optional[str] = None,
        authcfg: typing.Optional[str] = None,
        description: typing.Optional[str] = "MyNetworkfetcherTask",
        redirect_policy: typing.Optional[QtNetwork.QNetworkRequest.RedirectPolicy] = (
            QtNetwork.QNetworkRequest.NoLessSafeRedirectPolicy
        ),
    ):
        """
        Custom QgsTask that performs network requests

        This class is able to perform both GET and POST HTTP requests.

        It is needed because:

        - QgsNetworkContentFetcherTask only performs GET requests
        - QgsNetworkAcessManager.blockingPost() does not seem to handle redirects
          correctly

        Implementation is based on QgsNetworkContentFetcher. The run() method performs
        a normal async request using QtNetworkAccessManager's get() or post() methods.
        The resulting QNetworkReply instance has its `finished` signal be connected to
        a custom handler. The request is executed in scope of a custom Qt event loop,
        which blocks the current thread while the request is being processed.

        """

        super().__init__(description)
        self.api_client = api_client
        self.authcfg = authcfg
        self.request = request
        self.request_payload = request_payload
        self.reply_content = None
        self.parsed_reply = None
        self.redirect_policy = redirect_policy
        self.network_access_manager = qgis.core.QgsNetworkAccessManager.instance()
        self.network_access_manager.setRedirectPolicy(self.redirect_policy)
        self.network_access_manager.finished.connect(self._request_done)
        self._reply = None

    def run(self):
        if self.authcfg is not None:
            auth_manager = qgis.core.QgsApplication.authManager()
            auth_manager.updateNetworkRequest(self.request, self.authcfg)
        with wait_for_signal(self.request_parsed) as loop_result:
            if self.request_payload is None:
                self._reply = self.network_access_manager.get(self.request)
            else:
                self._reply = self.network_access_manager.post(
                    self.request,
                    QtCore.QByteArray(self.request_payload.encode("utf-8")),
                )
        try:
            if loop_result.result:
                result = self.parsed_reply.qt_error is None
            else:
                result = False
            self._reply.deleteLater()
            self._reply = None
        except AttributeError:
            result = False
        return result

    def finished(self, result: bool):
        self.network_access_manager.finished.disconnect(self._request_done)
        log(f"Inside finished. Result: {result}")
        self.request_finished.emit()
        if not result:
            if self.parsed_reply is not None:
                self.api_client.error_received[str, int, str].emit(
                    self.parsed_reply.qt_error,
                    self.parsed_reply.http_status_code,
                    self.parsed_reply.http_status_reason,
                )
            else:
                self.api_client.error_received.emit("Problem parsing network reply")

    def _request_done(self, qgis_reply: qgis.core.QgsNetworkReplyContent):
        log(f"requested_url: {qgis_reply.request().url().toString()}")
        if self._reply is None:
            log(
                "Some other request was completed, probably authentication, "
                "ignoring..."
            )
        elif reply_matches(qgis_reply, self._reply):
            self.reply_content = self._reply.readAll()
            self.parsed_reply = parse_network_reply(qgis_reply)
            log(f"http_status_code: {self.parsed_reply.http_status_code}")
            log(f"qt_error: {self.parsed_reply.qt_error}")
            self.request_parsed.emit()
        else:
            log(f"qgis_reply did not match the original reply id, ignoring...")


def reply_matches(
    qgis_reply: qgis.core.QgsNetworkReplyContent, qt_reply: QtNetwork.QNetworkReply
) -> bool:
    reply_id = int(qt_reply.property("requestId"))
    return qgis_reply.requestId() == reply_id


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
        qt_error = _get_qt_error(
            QtNetwork.QNetworkReply, QtNetwork.QNetworkReply.NetworkError, error
        )
    return ParsedNetworkReply(
        http_status_code=http_status_code,
        http_status_reason=http_status_reason,
        qt_error=qt_error,
        response_body=reply.content(),
    )


def _get_qt_error(cls, enum, error: QtNetwork.QNetworkReply.NetworkError) -> str:
    """workaround for accessing unsubscriptable sip enum types

    from https://stackoverflow.com/a/39677321

    """

    mapping = {}
    for key in dir(cls):
        value = getattr(cls, key)
        if isinstance(value, enum):
            mapping[key] = value
            mapping[value] = key
    return mapping[error]
