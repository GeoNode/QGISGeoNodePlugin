import typing
import uuid

import qgis.core
from qgis.PyQt import (
    QtCore,
    QtNetwork,
    QtXml,
)

from . import models
from ..utils import log


class NetworkFetcherTask(qgis.core.QgsTask):
    authcfg: str
    deserializer: typing.Callable
    handler: typing.Callable
    request: QtNetwork.QNetworkRequest
    request_payload: typing.Optional[str]
    reply_content: typing.Optional[QtCore.QByteArray]
    http_status_code: typing.Optional[int]

    def __init__(
        self,
        request: QtNetwork.QNetworkRequest,
        handler: typing.Callable,
        deserializer: typing.Callable,
        request_payload: typing.Optional[str] = None,
        authcfg: str = None,
    ):
        super().__init__()
        self.authcfg = authcfg
        self.request = request
        self.request_payload = request_payload
        self.handler = handler
        self.deserializer = deserializer
        self.reply_content = None
        self.http_status_code = None

    def run(self):
        network_access_manager = qgis.core.QgsNetworkAccessManager.instance()
        if self.payload is None:
            reply = network_access_manager.blockingGet(self.request, self.authcfg)
        else:
            self.request.setHeader(
                QtNetwork.QNetworkRequest.ContentTypeHeader,
                "application/x-www-form-urlencoded",
            )
            reply = network_access_manager.blockingPost(
                self.request, self.payload, self.authcfg
            )
        self.http_status_code = reply.attribute(
            QtNetwork.QNetworkRequest.HttpStatusCodeAttribute
        )
        self.reply_content = reply.content()
        return True if reply.error == QtNetwork.QNetworkReply.NoError else False

    def finished(self, result: bool):
        if result:
            self.handler(self.deserializer(self.reply_content.content()))
        else:
            message = "Error fetching content over network"
            log(message)

    def cancel(self):
        log("Operation was canceled")
        super().cancel()


class BaseGeonodeClient(QtCore.QObject):
    auth_config: str
    base_url: str

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
        self,
        page: typing.Optional[int] = 1,
        page_size: typing.Optional[int] = 10,
        title: typing.Optional[str] = None,
        abstract: typing.Optional[str] = None,
        keyword: typing.Optional[str] = None,
        topic_category: typing.Optional[str] = None,
        layer_types: typing.Optional[models.GeonodeResourceType] = None,
        ordering_field: typing.Optional[models.OrderingType] = None,
        reverse_ordering: typing.Optional[bool] = False,
        temporal_extent_start: typing.Optional[QtCore.QDateTime] = None,
        temporal_extent_end: typing.Optional[QtCore.QDateTime] = None,
        publication_date_start: typing.Optional[QtCore.QDateTime] = None,
        publication_date_end: typing.Optional[QtCore.QDateTime] = None,
        spatial_extent: typing.Optional[qgis.core.QgsRectangle] = None,
    ) -> (QtCore.QUrl, QtCore.QByteArray):
        raise NotImplementedError

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

    def handle_layer_list(self, payload: typing.Any):
        raise NotImplementedError

    def handle_layer_detail(self, payload: typing.Any):
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

    def get_layers(
        self,
        title: typing.Optional[str] = None,
        abstract: typing.Optional[str] = None,
        keyword: typing.Optional[str] = None,
        topic_category: typing.Optional[str] = None,
        layer_types: typing.Optional[typing.List[models.GeonodeResourceType]] = None,
        page: typing.Optional[int] = 1,
        page_size: typing.Optional[int] = 10,
        ordering_field: typing.Optional[models.OrderingType] = None,
        reverse_ordering: typing.Optional[bool] = False,
        temporal_extent_start: typing.Optional[QtCore.QDateTime] = None,
        temporal_extent_end: typing.Optional[QtCore.QDateTime] = None,
        publication_date_start: typing.Optional[QtCore.QDateTime] = None,
        publication_date_end: typing.Optional[QtCore.QDateTime] = None,
        spatial_extent: typing.Optional[qgis.core.QgsRectangle] = None,
    ):
        url, data = self.get_layers_url_endpoint(
            page=page,
            page_size=page_size,
            title=title,
            abstract=abstract,
            keyword=keyword,
            topic_category=topic_category,
            layer_types=layer_types,
            ordering_field=ordering_field,
            reverse_ordering=reverse_ordering,
            temporal_extent_start=temporal_extent_start,
            temporal_extent_end=temporal_extent_end,
            publication_date_start=publication_date_start,
            publication_date_end=publication_date_end,
            spatial_extent=spatial_extent,
        )
        log(f"URL: {url.toString()}")
        task = NetworkFetcherTask(
            request=QtNetwork.QNetworkRequest(url),
            handler=self.handle_layer_list(),
            deserializer=self.deserialize_response_contents,
            request_payload=data,
            authcfg=self.auth_config,
        )
        qgis.core.QgsApplication.taskManager().addTask(task)

    def get_layer_detail_from_brief_resource(
        self, brief_resource: models.BriefGeonodeResource
    ):
        raise NotImplementedError

    def get_layer_detail(self, id_: typing.Union[int, uuid.UUID]):
        request = QtNetwork.QNetworkRequest(self.get_layer_detail_url_endpoint(id_))
        self.run_task(request, self.handle_layer_detail)

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

    def _run_task(
        self,
        request,
        handler: typing.Callable,
        payload: str = None,
        response_deserializer: typing.Optional[typing.Callable] = None,
    ):
        """Fetches the response from the GeoNode API"""
        task = NetworkFetcherTask(
            request=request,
            handler=handler,
            deserializer=response_deserializer,
            request_payload=payload,
            authcfg=self.auth_config,
        )
        qgis.core.QgsApplication.taskManager().addTask(task)

    def response_fetched(
        self,
        task: NetworkFetcherTask,
        handler: typing.Callable,
        deserializer: typing.Callable,
    ):
        """Process GeoNode API response and dispatch the appropriate handler"""
        reply: QtNetwork.QNetworkReply = task.reply()
        error = reply.error()
        if error == QtNetwork.QNetworkReply.NoError:
            contents: QtCore.QByteArray = reply.content()
            payload = deserializer(contents)
            handler(payload)
        else:
            qt_error = _get_qt_error(
                QtNetwork.QNetworkReply, QtNetwork.QNetworkReply.NetworkError, error
            )
            http_status_code = reply.attribute(
                QtNetwork.QNetworkRequest.HttpStatusCodeAttribute
            )
            http_status_reason = reply.attribute(
                QtNetwork.QNetworkRequest.HttpReasonPhraseAttribute
            )
            log(f"requested url: {reply.url().toString()}")
            log(f"received error: {qt_error} http_status: {http_status_code}")
            self.error_received.emit(
                qt_error, http_status_code or 0, http_status_reason or ""
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
