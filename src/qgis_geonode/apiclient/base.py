import typing
import uuid

import qgis.core
from qgis.PyQt import (
    QtCore,
    QtNetwork,
    QtXml,
)
from qgis_geonode.apiclient.models import GeonodeApiSearchParameters

from . import models
from ..utils import log


class NetworkFetcherTask(qgis.core.QgsTask):
    authcfg: str
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
        authcfg: str = None,
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
        self.http_status_code = reply.attribute(
            QtNetwork.QNetworkRequest.HttpStatusCodeAttribute
        )
        self.http_status_reason = reply.attribute(
            QtNetwork.QNetworkRequest.HttpReasonPhraseAttribute
        )
        self.reply_content = reply.content()
        self.setProgress(100)
        error = reply.error()
        if error == QtNetwork.QNetworkReply.NoError:
            result = True
        else:
            result = False
            self.qt_error = _get_qt_error(
                QtNetwork.QNetworkReply, QtNetwork.QNetworkReply.NetworkError, error
            )
        return result

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

    def get_layer_detail_url_endpoint(
        self, id_: typing.Union[int, uuid.UUID]
    ) -> QtCore.QUrl:
        raise NotImplementedError

    def get_layer_styles_url_endpoint(self, layer_id: int):
        raise NotImplementedError

    def get_maps_url_endpoint(
        self,
        page: typing.Optional[int] = 1,
        page_size: typing.Optional[int] = 10,
        title: typing.Optional[str] = None,
        keyword: typing.Optional[str] = None,
        topic_category: typing.Optional[str] = None,
        ordering_field: typing.Optional[models.OrderingType] = None,
        reverse_ordering: typing.Optional[bool] = False,
        temporal_extent_start: typing.Optional[QtCore.QDateTime] = None,
        temporal_extent_end: typing.Optional[QtCore.QDateTime] = None,
        publication_date_start: typing.Optional[QtCore.QDateTime] = None,
        publication_date_end: typing.Optional[QtCore.QDateTime] = None,
        spatial_extent: typing.Optional[qgis.core.QgsRectangle] = None,
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

    def handle_layer_list(self, raw_reply_contents: QtCore.QByteArray):
        raise NotImplementedError

    def handle_layer_detail(self, raw_reply_contents: QtCore.QByteArray):
        raise NotImplementedError

    def handle_layer_style_detail(self, payload: QtXml.QDomDocument):
        sld_root = payload.documentElement()
        error_message = "Could not parse downloaded SLD document"
        if sld_root.isNull():
            raise RuntimeError(error_message)
        sld_named_layer = sld_root.firstChildElement("NamedLayer")
        if sld_named_layer.isNull():
            raise RuntimeError(error_message)
        self.style_detail_received.emit(sld_named_layer)

    def handle_layer_style_list(self, payload: typing.Any):
        raise NotImplementedError

    def handle_map_list(self, payload: typing.Any):
        raise NotImplementedError

    def get_layers(self, search_params: GeonodeApiSearchParameters):
        url = self.get_layers_url_endpoint(search_params)
        request_payload = self.get_layers_request_payload(search_params)
        log(f"URL: {url.toString()}")
        log(f"request_payload: {request_payload}")
        self.network_fetcher_task = NetworkFetcherTask(
            request=QtNetwork.QNetworkRequest(url),
            reply_handler=self.handle_layer_list,
            request_payload=request_payload,
            authcfg=self.auth_config,
        )
        qgis.core.QgsApplication.taskManager().addTask(self.network_fetcher_task)

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
        self.run_task(request, self.handle_layer_style_list)

    def get_layer_style(
        self, layer: models.GeonodeResource, style_name: typing.Optional[str] = None
    ):
        if style_name is None:
            style_url = layer.default_style.sld_url
        else:
            style_details = [i for i in layer.styles if i.name == style_name][0]
            style_url = style_details.sld_url
        request = QtNetwork.QNetworkRequest(QtCore.QUrl(style_url))
        self.run_task(
            request,
            self.handle_layer_style_detail,
            response_deserializer=self.deserialize_sld_style,
        )

    def get_maps(
        self,
        page: typing.Optional[int] = 1,
        page_size: typing.Optional[int] = 10,
        title: typing.Optional[str] = None,
        keyword: typing.Optional[str] = None,
        topic_category: typing.Optional[str] = None,
        ordering_field: typing.Optional[models.OrderingType] = None,
        reverse_ordering: typing.Optional[bool] = False,
        temporal_extent_start: typing.Optional[QtCore.QDateTime] = None,
        temporal_extent_end: typing.Optional[QtCore.QDateTime] = None,
        publication_date_start: typing.Optional[QtCore.QDateTime] = None,
        publication_date_end: typing.Optional[QtCore.QDateTime] = None,
        spatial_extent: typing.Optional[qgis.core.QgsRectangle] = None,
    ):
        url = self.get_maps_url_endpoint(
            page=page,
            page_size=page_size,
            title=title,
            keyword=keyword,
            topic_category=topic_category,
            ordering_field=ordering_field,
            reverse_ordering=reverse_ordering,
            temporal_extent_start=temporal_extent_start,
            temporal_extent_end=temporal_extent_end,
            publication_date_start=publication_date_start,
            publication_date_end=publication_date_end,
            spatial_extent=spatial_extent,
        )
        request = QtNetwork.QNetworkRequest(url)
        self.run_task(request, self.handle_map_list)


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
