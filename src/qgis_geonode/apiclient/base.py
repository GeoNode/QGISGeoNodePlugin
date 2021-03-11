import typing
import uuid
from functools import partial

from qgis.core import (
    QgsMessageLog,
    QgsNetworkContentFetcherTask,
)
from qgis.PyQt import (
    QtCore,
    QtNetwork,
    QtXml,
)

from . import models


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
        layer_type: typing.Optional[models.GeonodeResourceType] = None,
        ordering_field: typing.Optional[models.OrderingType] = None,
        reverse_ordering: typing.Optional[bool] = False,
    ) -> QtCore.QUrl:
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
    ):
        url = self.get_layers_url_endpoint(
            title=title,
            abstract=abstract,
            keyword=keyword,
            topic_category=topic_category,
            layer_types=layer_types,
            page=page,
            page_size=page_size,
            ordering_field=ordering_field,
            reverse_ordering=reverse_ordering,
        )
        request = QtNetwork.QNetworkRequest(url)
        self.run_task(request, self.handle_layer_list)

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
    ):
        url = self.get_maps_url_endpoint(
            page=page,
            page_size=page_size,
            title=title,
            keyword=keyword,
            topic_category=topic_category,
            ordering_field=ordering_field,
            reverse_ordering=reverse_ordering,
        )
        request = QtNetwork.QNetworkRequest(url)
        self.run_task(request, self.handle_map_list)

    def run_task(
        self,
        request,
        handler: typing.Callable,
        response_deserializer: typing.Optional[typing.Callable] = None,
    ):
        """Fetches the response from the GeoNode API"""
        task = QgsNetworkContentFetcherTask(request, authcfg=self.auth_config)
        response_handler = partial(
            self.response_fetched,
            task,
            handler,
            response_deserializer or self.deserialize_response_contents,
        )
        task.fetched.connect(response_handler)
        task.run()

    def response_fetched(
        self,
        task: QgsNetworkContentFetcherTask,
        handler: typing.Callable,
        deserializer: typing.Callable,
    ):
        """Process GeoNode API response and dispatch the appropriate handler"""
        reply: QtNetwork.QNetworkReply = task.reply()
        error = reply.error()
        if error == QtNetwork.QNetworkReply.NoError:
            contents: QtCore.QByteArray = reply.readAll()
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
            QgsMessageLog.logMessage(
                f"requested url: {reply.url().toString()}", "qgis_geonode"
            )
            QgsMessageLog.logMessage(
                f"received error: {qt_error} http_status: {http_status_code}",
                "qgis_geonode",
            )
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
