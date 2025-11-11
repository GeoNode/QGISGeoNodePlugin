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
from packaging import version as packaging_version

UNSUPPORTED_REMOTE = "unsupported"


class HttpMethod(enum.Enum):
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    PATCH = "PATCH"


@dataclasses.dataclass()
class PendingReply:
    index: int
    reply: qgis.core.QgsNetworkReplyContent
    fullfilled: bool = False


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


_Q_NETWORK_REPLY_ERROR_MAP: typing.Dict[
    QtNetwork.QNetworkReply.NetworkError, str
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


def create_request(
    url: QtCore.QUrl, content_type: typing.Optional[str] = None
) -> QtNetwork.QNetworkRequest:
    request = QtNetwork.QNetworkRequest(url)
    if content_type is not None:
        request.setHeader(QtNetwork.QNetworkRequest.ContentTypeHeader, content_type)
    return request


def handle_discovery_test(
    finished_task_result: bool, finished_task: qgis.core.QgsTask
) -> typing.Optional[packaging_version.Version]:
    geonode_version = None
    if finished_task_result:
        response_contents = finished_task.response_contents[0]
        if response_contents is not None and response_contents.qt_error is None:
            geonode_version = packaging_version.parse(
                response_contents.response_body.data().decode()
            )
    return geonode_version


def build_multipart(
    layer_metadata: qgis.core.QgsLayerMetadata,
    permissions: typing.Dict,
    main_file: QtCore.QFile,
    sidecar_files: typing.List[typing.Tuple[str, QtCore.QFile]],
) -> QtNetwork.QHttpMultiPart:
    encoding = "utf-8"
    multipart = QtNetwork.QHttpMultiPart(QtNetwork.QHttpMultiPart.FormDataType)
    title = layer_metadata.title()
    if title:
        title_part = QtNetwork.QHttpPart()
        title_part.setHeader(
            QtNetwork.QNetworkRequest.ContentDispositionHeader,
            'form-data; name="dataset_title"',
        )
        title_part.setBody(layer_metadata.title().encode(encoding))
        multipart.append(title_part)
    abstract = layer_metadata.abstract()
    if abstract:
        abstract_part = QtNetwork.QHttpPart()
        abstract_part.setHeader(
            QtNetwork.QNetworkRequest.ContentDispositionHeader,
            'form-data; name="abstract"',
        )
        abstract_part.setBody(layer_metadata.abstract().encode(encoding))
        multipart.append(abstract_part)
    false_items = (
        "time",
        "mosaic",
        "metadata_uploaded_preserve",
        "metadata_upload_form",
        "style_upload_form",
    )
    for item in false_items:
        part = QtNetwork.QHttpPart()
        part.setHeader(
            QtNetwork.QNetworkRequest.ContentDispositionHeader,
            f'form-data; name="{item}"',
        )
        part.setBody("false".encode("utf-8"))
        multipart.append(part)

    # Add action=upload
    action_part = QtNetwork.QHttpPart()
    action_part.setHeader(
        QtNetwork.QNetworkRequest.ContentDispositionHeader,
        'form-data; name="action"',
    )
    action_part.setBody("upload".encode("utf-8"))
    multipart.append(action_part)

    permissions_part = QtNetwork.QHttpPart()
    permissions_part.setHeader(
        QtNetwork.QNetworkRequest.ContentDispositionHeader,
        'form-data; name="permissions"',
    )
    permissions_part.setBody(json.dumps(permissions).encode(encoding))
    multipart.append(permissions_part)
    file_parts = [("base_file", main_file)]
    for additional_file_form_name, additional_file_handler in sidecar_files:
        file_parts.append((additional_file_form_name, additional_file_handler))
    for form_element_name, file_handler in file_parts:
        file_name = file_handler.fileName().rpartition("/")[-1]
        part = QtNetwork.QHttpPart()
        part.setHeader(
            QtNetwork.QNetworkRequest.ContentDispositionHeader,
            f'form-data; name="{form_element_name}"; filename="{file_name}"',
        )
        if file_name.rpartition(".")[-1] == "tif":
            content_type = "image/tiff"
        else:
            content_type = "application/qgis"
        part.setHeader(QtNetwork.QNetworkRequest.ContentTypeHeader, content_type)
        part.setBodyDevice(file_handler)
        multipart.append(part)
    return multipart
