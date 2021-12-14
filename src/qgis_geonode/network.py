import dataclasses
import enum
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

UNSUPPORTED_REMOTE = "unsupported"


class HttpMethod(enum.Enum):
    GET = "get"
    POST = "post"
    PUT = "put"


@dataclasses.dataclass()
class ParsedNetworkReply:
    http_status_code: int
    http_status_reason: str
    qt_error: str
    response_body: QtCore.QByteArray


@dataclasses.dataclass()
class RequestToPerform:
    url: QtCore.QUrl
    method: typing.Optional[HttpMethod] = HttpMethod.GET
    payload: typing.Optional[str] = None
    content_type: typing.Optional[str] = None


class AnotherNetworkRequestTask(qgis.core.QgsTask):
    requests_to_perform: typing.List[RequestToPerform]

    # stores the results
    response_contents: typing.List[typing.Optional[ParsedNetworkReply]]

    _pending_replies: typing.Dict[int, QtNetwork.QNetworkReply]
    _finished_replies: typing.Dict[int, ParsedNetworkReply]
    _current_request_index: typing.Optional[int]

    network_access_manager: qgis.core.QgsNetworkAccessManager

    _all_requests_finished = QtCore.pyqtSignal()
    task_done = QtCore.pyqtSignal()

    def __init__(
        self,
        requests_to_perform: typing.List[RequestToPerform],
        description: typing.Optional[str] = "AnotherNetworkRequestTask",
    ):
        """A QGIS task to run a series of network requests in sequence."""
        super().__init__(description)
        self.requests_to_perform = requests_to_perform
        self.response_contents = [None] * len(requests_to_perform)
        self._current_request_index = 0
        self._pending_replies = {}
        self.network_access_manager = qgis.core.QgsNetworkAccessManager.instance()
        self.network_access_manager.finished.connect(self._handle_request_finished)

    def run(self) -> bool:
        """Run the QGIS task

        This method is called by the QGIS task manager.

        Implementation uses a custom Qt event loop that waits until
        all of the task's requests have been performed.

        """

        with wait_for_signal(self._all_requests_finished) as event_loop_result:
            try:
                next_request = self._requests_todo[self._current_request_index]
            except IndexError:  # there are no requests to perform
                self._all_requests_finished.emit()
            else:
                self._dispatch_request(next_request)
        return event_loop_result.result

    def finished(self, result: bool) -> None:
        if result:
            for index in self.requests_to_perform:
                self.response_contents[index] = self._finished_replies.get(index)
        else:
            pass
        self.task_done.emit()

    def _dispatch_request(self, request_params: RequestToPerform) -> None:
        request = QtNetwork.QNetworkRequest(request_params.url)
        if request_params.content_type is not None:
            request.setHeader(
                QtNetwork.QNetworkRequest.ContentTypeHeader, request_params.content_type
            )
        if request_params.method == HttpMethod.GET:
            reply = self.network_access_manager.get(request)
        elif request_params.method == HttpMethod.PUT:
            data_ = QtCore.QByteArray(request_params.payload.encode())
            reply = self.network_access_manager.put(request, data_)
        else:
            raise NotImplementedError
        request_id = reply.property("requestId")
        self._pending_replies[request_id] = reply

    def _handle_request_finished(self, reply: QtNetwork.QNetworkReply):
        request_id = reply.property("requestId")
        if request_id in self._pending_replies.keys():
            parsed = parse_network_reply(reply)
            self._finished_replies[self._current_request_index] = parsed
            self._current_request_index += 1
            del self._pending_replies[request_id]
            try:
                next_request = self.requests_to_perform[self._current_request_index]
            except IndexError:
                pass  # there are no more requests to perform, we are done!
                self._all_requests_finished.emit()
            else:
                self._dispatch_request(next_request)
            reply.deleteLater()
        else:
            pass  # this is some other request that we are not managing, ignore it


class MultipleNetworkFetcherTask(qgis.core.QgsTask):

    network_access_manager: qgis.core.QgsNetworkAccessManager
    requests_to_perform: typing.List[RequestToPerform]
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
        self.network_access_manager = qgis.core.QgsNetworkAccessManager.instance()
        self.authcfg = authcfg
        self.response_contents = []
        self._exceptions_raised = []

    def run(self) -> bool:
        result = True
        self.network_access_manager.requestTimedOut.connect(
            self._handle_request_timeout
        )
        self.network_access_manager.authBrowserAborted.connect(
            self._handle_auth_browser_aborted
        )
        self.network_access_manager.requestRequiresAuth.connect(
            self._handle_request_requires_auth
        )
        self.network_access_manager.requestRequiresAuth.connect(
            self._handle_request_requires_auth
        )
        self.network_access_manager.requestAboutToBeCreated.connect(
            self._handle_request_about_to_be_created
        )
        for request_params in self.requests_to_perform:
            log(f"Performing request for {request_params.url}...")
            request = QtNetwork.QNetworkRequest(request_params.url)
            if request_params.content_type is not None:
                request.setHeader(
                    QtNetwork.QNetworkRequest.ContentTypeHeader,
                    request_params.content_type,
                )
            if request_params.payload is None:
                reply_content = self.network_access_manager.blockingGet(
                    request, self.authcfg
                )
            else:
                reply_content = self.network_access_manager.blockingPost(
                    request,
                    QtCore.QByteArray(request_params.payload.encode()),
                    self.authcfg,
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

    def _handle_request_about_to_be_created(
        self, request_params: qgis.core.QgsNetworkRequestParameters
    ):
        log("inside _handle_request_about_to_be_created")

    def _handle_request_requires_auth(self, request_id: int, realm: str):
        log(f"Inside _request_requires_auth - locals: {locals()}")

    def _handle_auth_browser_aborted(self):
        log(f"Inside _handle_auth_browser_aborted")
        self._exceptions_raised.append("Authentication aborted")

    def _handle_request_timeout(
        self, request_params: qgis.core.QgsNetworkRequestParameters
    ):
        log(
            f"Inside _handle_request_timeout - request id is: {request_params.requestId()}"
        )

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
