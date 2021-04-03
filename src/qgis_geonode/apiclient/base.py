import typing
import uuid
from functools import partial

import qgis.core
from qgis.PyQt import (
    QtCore,
    QtNetwork,
    QtXml,
)
from qgis_geonode.apiclient.models import GeonodeApiSearchParameters

from . import models
from ..utils import (
    ParsedNetworkReply,
    log,
    parse_network_reply,
)


class MyNetworkFetcherTask(qgis.core.QgsTask):
    authcfg: typing.Optional[str]
    description: str
    request: QtNetwork.QNetworkRequest
    request_payload: typing.Optional[str]
    reply_content: typing.Optional[QtCore.QByteArray]
    parsed_reply: typing.Optional[ParsedNetworkReply]
    redirect_policy: QtNetwork.QNetworkRequest.RedirectPolicy
    _reply: typing.Optional[QtNetwork.QNetworkReply]
    _request_id: typing.Optional[int]

    request_finished = QtCore.pyqtSignal()
    request_parsed = QtCore.pyqtSignal()

    def __init__(
        self,
        request: QtNetwork.QNetworkRequest,
        request_payload: typing.Optional[str] = None,
        authcfg: typing.Optional[str] = None,
        description: typing.Optional[str] = "MyNetworkfetcherTask",
        redirect_policy: QtNetwork.QNetworkRequest.RedirectPolicy = (
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
        self._request_id = None

    def run(self):
        if self.request_payload is None:
            self._reply = self.network_access_manager.get(self.request)
        else:
            self._reply = self.network_access_manager.post(
                self.request, QtCore.QByteArray(self.request_payload.encode("utf-8"))
            )
            self._request_id = int(self._reply.property("requestId"))
        event_loop = QtCore.QEventLoop()
        self.request_parsed.connect(event_loop.quit)
        QtCore.QTimer.singleShot(5000, event_loop.quit)
        log(f"About to start the custom event loop...")
        event_loop.exec_()
        log(f"Custom event loop ended, resuming...")
        self.request_finished.emit()
        return self.parsed_reply.qt_error is None

    def finished(self, result: bool):
        log(f"Inside finished() method with result: {result!r}")

    def _request_done(self, qgis_reply: qgis.core.QgsNetworkReplyContent):
        log(f"requested_url: {qgis_reply.request().url().toString()}")
        self.reply_content = self._reply.readAll()
        #log(f"reply_content: {self.reply_content}")
        self.parsed_reply = parse_network_reply(qgis_reply)
        log(f"http_status_code: {self.parsed_reply.http_status_code}")
        log(f"qt_error: {self.parsed_reply.qt_error}")
        self._reply.deleteLater()
        self._reply = None
        self.request_parsed.emit()


class NetworkFetcherTask(qgis.core.QgsTask):
    authcfg: typing.Optional[str]
    reply_handler: typing.Callable
    request: QtNetwork.QNetworkRequest
    request_payload: typing.Optional[str]
    reply_content: typing.Optional[QtCore.QByteArray]
    http_status_code: typing.Optional[int]
    http_status_reason: typing.Optional[str]
    qt_error: typing.Optional[str]

    def __init__(
        self,
        request: QtNetwork.QNetworkRequest,
        reply_handler: typing.Callable,
        request_payload: typing.Optional[str] = None,
        authcfg: typing.Optional[str] = None,
    ):
        super().__init__()
        self.authcfg = authcfg
        self.request = request
        self.request_payload = request_payload
        self.reply_handler = reply_handler
        self.reply_content = None
        self.http_status_code = None
        self.http_status_reason = None
        self.qt_error = None

    def run(self):
        if self.request_payload is None:
            reply = self._perform_get_request()
        else:
            reply = self._perform_post_request()

        self.reply_content = reply.content()
        parsed_reply = parse_network_reply(reply)
        self.http_status_code = parsed_reply.http_status_code
        self.http_status_reason = parsed_reply.http_status_reason
        self.qt_error = parsed_reply.qt_error
        self.setProgress(100)
        return self.qt_error is None

    def finished(self, result: bool):
        if result:
            self.reply_handler(self.reply_content)
        else:
            log(f"requested url: {self.request.url().toString()}")
            log(
                f"received error: {self.qt_error} http_status: {self.http_status_code} "
                f"- {self.http_status_reason}"
            )

    def _perform_get_request(self) -> qgis.core.QgsNetworkReplyContent:
        network_access_manager = qgis.core.QgsNetworkAccessManager.instance()
        return network_access_manager.blockingGet(self.request, self.authcfg)

    def _perform_post_request(self) -> qgis.core.QgsNetworkReplyContent:
        network_access_manager = qgis.core.QgsNetworkAccessManager.instance()
        self.request.setHeader(
            QtNetwork.QNetworkRequest.ContentTypeHeader,
            "application/x-www-form-urlencoded",
        )
        return network_access_manager.blockingPost(
            self.request,
            QtCore.QByteArray(self.request_payload.encode("utf-8")),
            self.authcfg,
        )


class BaseGeonodeClient(QtCore.QObject):
    auth_config: str
    base_url: str
    network_fetcher_task: typing.Optional[NetworkFetcherTask]
    capabilities: typing.List[models.ApiClientCapability]

    layer_list_received = QtCore.pyqtSignal(list, models.GeoNodePaginationInfo)
    layer_detail_received = QtCore.pyqtSignal(models.GeonodeResource)
    style_detail_received = QtCore.pyqtSignal(QtXml.QDomElement)
    layer_styles_received = QtCore.pyqtSignal(list)
    map_list_received = QtCore.pyqtSignal(list, models.GeoNodePaginationInfo)
    error_received = QtCore.pyqtSignal(str, int, str)

    def __init__(
        self, base_url: str, *args, auth_config: typing.Optional[str] = None, **kwargs
    ):
        super().__init__(*args, **kwargs)
        self.auth_config = auth_config or ""
        self.base_url = base_url.rstrip("/")
        self.network_fetcher_task = None

    @classmethod
    def from_connection_settings(cls, connection_settings: "ConnectionSettings"):
        return cls(
            base_url=connection_settings.base_url,
            auth_config=connection_settings.auth_config,
        )

    def get_ordering_filter_name(
        self,
        ordering_type: models.OrderingType,
        reverse_sort: typing.Optional[bool] = False,
    ) -> str:
        raise NotImplementedError

    def get_search_result_identifier(
        self, resource: models.BriefGeonodeResource
    ) -> str:
        raise NotImplementedError

    def get_layers_url_endpoint(
        self, search_params: GeonodeApiSearchParameters
    ) -> QtCore.QUrl:
        raise NotImplementedError

    def get_layers_request_payload(
        self, search_params: GeonodeApiSearchParameters
    ) -> typing.Optional[str]:
        return None

    def get_maps_request_payload(
        self, search_params: GeonodeApiSearchParameters
    ) -> typing.Optional[str]:
        return None

    def get_layer_detail_url_endpoint(
        self, id_: typing.Union[int, uuid.UUID]
    ) -> QtCore.QUrl:
        raise NotImplementedError

    def get_layer_styles_url_endpoint(self, layer_id: int):
        raise NotImplementedError

    def get_maps_url_endpoint(
        self, search_params: GeonodeApiSearchParameters
    ) -> QtCore.QUrl:
        raise NotImplementedError

    def deserialize_response_contents(self, contents: QtCore.QByteArray) -> typing.Any:
        raise NotImplementedError

    def deserialize_sld_style(self, raw_sld: QtCore.QByteArray) -> QtXml.QDomDocument:
        sld_doc = QtXml.QDomDocument()
        # in the line below, `True` means use XML namespaces and it is crucial for
        # QGIS to be able to load the SLD
        sld_loaded = sld_doc.setContent(raw_sld, True)
        if not sld_loaded:
            raise RuntimeError("Could not load downloaded SLD document")
        return sld_doc

    def handle_layer_list(
        self,
        original_search_params: GeonodeApiSearchParameters,
        raw_reply_contents: QtCore.QByteArray,
    ):
        raise NotImplementedError

    def handle_layer_detail(self, raw_reply_contents: QtCore.QByteArray):
        raise NotImplementedError

    def handle_layer_style_detail(self, raw_reply_contents: QtCore.QByteArray):
        deserialized = self.deserialize_sld_style(raw_reply_contents)
        sld_root = deserialized.documentElement()
        error_message = "Could not parse downloaded SLD document"
        if sld_root.isNull():
            raise RuntimeError(error_message)
        sld_named_layer = sld_root.firstChildElement("NamedLayer")
        if sld_named_layer.isNull():
            raise RuntimeError(error_message)
        self.style_detail_received.emit(sld_named_layer)

    def handle_layer_style_list(self, payload: typing.Any):
        raise NotImplementedError

    def handle_map_list(
        self, original_search_params: GeonodeApiSearchParameters, payload: typing.Any
    ):
        raise NotImplementedError

    def get_layers(
        self, search_params: typing.Optional[GeonodeApiSearchParameters] = None
    ):
        url = self.get_layers_url_endpoint(search_params)
        params = (
            search_params if search_params is not None else GeonodeApiSearchParameters()
        )
        request_payload = self.get_layers_request_payload(params)
        log(f"URL: {url.toString()}")
        self.network_fetcher_task = NetworkFetcherTask(
            request=QtNetwork.QNetworkRequest(url),
            reply_handler=partial(self.handle_layer_list, params),
            request_payload=request_payload,
            authcfg=self.auth_config,
        )
        qgis.core.QgsApplication.taskManager().addTask(self.network_fetcher_task)

    def new_get_layers(
        self, search_params: typing.Optional[GeonodeApiSearchParameters] = None
    ):
        params = (
            search_params if search_params is not None else GeonodeApiSearchParameters()
        )
        self.network_fetcher_task = MyNetworkFetcherTask(
            QtNetwork.QNetworkRequest(self.get_layers_url_endpoint(params)),
            request_payload=self.get_layers_request_payload(params),
            authcfg=self.auth_config,
        )
        self.network_fetcher_task.request_finished.connect(
            partial(self.new_handle_layer_list, params)
        )
        qgis.core.QgsApplication.taskManager().addTask(self.network_fetcher_task)

    def new_handle_layer_list(self, original_search_params: GeonodeApiSearchParameters):
        raise NotImplementedError

    def get_layer_detail_from_brief_resource(
        self, brief_resource: models.BriefGeonodeResource
    ):
        raise NotImplementedError

    def get_layer_detail(self, id_: typing.Union[int, uuid.UUID]):
        self.network_fetcher_task = NetworkFetcherTask(
            request=QtNetwork.QNetworkRequest(self.get_layer_detail_url_endpoint(id_)),
            reply_handler=self.handle_layer_detail,
            authcfg=self.auth_config,
        )
        qgis.core.QgsApplication.taskManager().addTask(self.network_fetcher_task)

    def get_layer_styles(self, layer_id: int):
        request = QtNetwork.QNetworkRequest(
            self.get_layer_styles_url_endpoint(layer_id)
        )
        self.network_fetcher_task = NetworkFetcherTask(
            request, self.handle_layer_style_list, authcfg=self.auth_config
        )
        qgis.core.QgsApplication.taskManager().addTask(self.network_fetcher_task)

    def get_layer_style(
        self, layer: models.GeonodeResource, style_name: typing.Optional[str] = None
    ):
        if style_name is None:
            style_url = layer.default_style.sld_url
        else:
            style_details = [i for i in layer.styles if i.name == style_name][0]
            style_url = style_details.sld_url
        self.network_fetcher_task = NetworkFetcherTask(
            request=QtNetwork.QNetworkRequest(QtCore.QUrl(style_url)),
            reply_handler=self.handle_layer_style_detail,
            authcfg=self.auth_config,
        )
        qgis.core.QgsApplication.taskManager().addTask(self.network_fetcher_task)

    def get_maps(self, search_params: GeonodeApiSearchParameters):
        url = self.get_maps_url_endpoint(search_params)
        request_payload = self.get_maps_request_payload(search_params)
        log(f"URL: {url.toString()}")
        self.network_fetcher_task = NetworkFetcherTask(
            request=QtNetwork.QNetworkRequest(url),
            reply_handler=partial(self.handle_map_list, search_params),
            request_payload=request_payload,
            authcfg=self.auth_config,
        )
        qgis.core.QgsApplication.taskManager().addTask(self.network_fetcher_task)
