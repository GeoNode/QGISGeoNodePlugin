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

from . import models


class BaseGeonodeClient(QObject):
    auth_config: str
    base_url: str

    layer_list_received = pyqtSignal(list, int, int, int)
    layer_detail_received = pyqtSignal(models.GeonodeResource)
    layer_styles_received = pyqtSignal(list)
    map_list_received = pyqtSignal(list, int, int, int)
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

    def handle_layer_list(self, payload: typing.Any):
        raise NotImplementedError

    def handle_layer_detail(self, payload: typing.Any):
        raise NotImplementedError

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
            layer_types: typing.Optional[
                typing.List[models.GeonodeResourceType]] = None,
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

    def run_task(self, request, handler: typing.Callable):
        """Fetches the response from the GeoNode API"""
        task = QgsNetworkContentFetcherTask(request, authcfg=self.auth_config)
        response_handler = partial(self.response_fetched, task, handler)
        task.fetched.connect(response_handler)
        task.run()

    def response_fetched(
        self, task: QgsNetworkContentFetcherTask, handler: typing.Callable
    ):
        """Process GeoNode API response and dispatch the appropriate handler"""
        reply: QNetworkReply = task.reply()
        error = reply.error()
        if error == QNetworkReply.NoError:
            contents: QByteArray = reply.readAll()
            payload = self.deserialize_response_contents(contents)
            handler(payload)
        else:
            QgsMessageLog.logMessage("received error", "qgis_geonode")
            self.error_received.emit(error)
