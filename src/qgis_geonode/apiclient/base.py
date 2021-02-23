import typing
import uuid
from functools import partial

from qgis.core import (
    QgsMessageLog,
    QgsNetworkContentFetcherTask,
)
from qgis.PyQt.QtCore import (
    QByteArray,
    QObject,
    QUrl,
    pyqtSignal,
)
from qgis.PyQt.QtNetwork import (
    QNetworkReply,
    QNetworkRequest,
)
from qgis.PyQt import QtXml

from . import models


class BaseGeonodeClient(QObject):
    auth_config: str
    base_url: str

    layer_list_received = pyqtSignal(list, models.GeoNodePaginationInfo)
    layer_detail_received = pyqtSignal(models.GeonodeResource)
    style_detail_received = pyqtSignal(QtXml.QDomElement)
    layer_styles_received = pyqtSignal(list)
    map_list_received = pyqtSignal(list, models.GeoNodePaginationInfo)
    error_received = pyqtSignal(int)

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

    def get_layers_url_endpoint(
        self,
        page: typing.Optional[int] = 1,
        page_size: typing.Optional[int] = 10,
        title: typing.Optional[str] = None,
        abstract: typing.Optional[str] = None,
        keyword: typing.Optional[str] = None,
        topic_category: typing.Optional[str] = None,
        layer_type: typing.Optional[models.GeonodeResourceType] = None,
    ) -> QUrl:
        raise NotImplementedError

    def get_layer_detail_url_endpoint(self, id_: typing.Union[int, uuid.UUID]) -> QUrl:
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
    ) -> QUrl:
        raise NotImplementedError

    def deserialize_response_contents(self, contents: QByteArray) -> typing.Any:
        raise NotImplementedError

    def deserialize_sld_style(self, raw_sld: QByteArray) -> QtXml.QDomDocument:
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
    ):
        url = self.get_layers_url_endpoint(
            title=title,
            abstract=abstract,
            keyword=keyword,
            topic_category=topic_category,
            layer_types=layer_types,
            page=page,
            page_size=page_size,
        )
        request = QNetworkRequest(url)
        self.run_task(request, self.handle_layer_list)

    def get_layer_detail_from_brief_resource(
        self, brief_resource: models.BriefGeonodeResource
    ):
        raise NotImplementedError

    def get_layer_detail(self, id_: typing.Union[int, uuid.UUID]):
        request = QNetworkRequest(self.get_layer_detail_url_endpoint(id_))
        self.run_task(request, self.handle_layer_detail)

    def get_layer_styles(self, layer_id: int):
        request = QNetworkRequest(self.get_layer_styles_url_endpoint(layer_id))
        self.run_task(request, self.handle_layer_style_list)

    def get_layer_style(
        self, layer: models.GeonodeResource, style_name: typing.Optional[str] = None
    ):
        if style_name is None:
            style_url = layer.default_style.sld_url
        else:
            style_details = [i for i in layer.styles if i.name == style_name][0]
            style_url = style_details.sld_url
        request = QNetworkRequest(QUrl(style_url))
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
    ):
        url = self.get_maps_url_endpoint(
            page=page,
            page_size=page_size,
            title=title,
            keyword=keyword,
            topic_category=topic_category,
        )
        request = QNetworkRequest(url)
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
        reply: QNetworkReply = task.reply()
        error = reply.error()
        if error == QNetworkReply.NoError:
            contents: QByteArray = reply.readAll()
            payload = deserializer(contents)
            handler(payload)
        else:
            QgsMessageLog.logMessage("received error", "qgis_geonode")
            self.error_received.emit(error)
