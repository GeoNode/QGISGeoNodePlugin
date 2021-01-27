import datetime as dt
import enum
import json
import typing
import uuid
from functools import partial

from qgis.core import (
    QgsMessageLog,
    QgsNetworkContentFetcherTask,
    QgsRectangle,
    QgsCoordinateReferenceSystem,
)
from qgis.PyQt.QtCore import (
    QByteArray,
    QObject,
    QUrl,
    QUrlQuery,
    pyqtSignal,
)
from qgis.PyQt.QtNetwork import QNetworkReply, QNetworkRequest

from .conf import ConnectionSettings


class GeonodeResourceType(enum.Enum):
    VECTOR_LAYER = "vector"
    RASTER_LAYER = "raster"
    MAP = "map"


class BriefGeonodeResource:
    pk: int
    uuid: uuid.UUID
    name: str
    resource_type: GeonodeResourceType
    title: str
    abstract: str
    published_date: typing.Optional[dt.datetime]
    spatial_extent: QgsRectangle
    temporal_extent: typing.Optional[typing.List[dt.datetime]]
    crs: QgsCoordinateReferenceSystem
    thumbnail_url: str
    api_url: str
    gui_url: str
    keywords: typing.List[str]
    category: typing.Optional[str]
    service_urls: typing.Dict[str, str]

    def __init__(
            self,
            pk: int,
            uuid: uuid.UUID,
            name: str,
            resource_type: GeonodeResourceType,
            title: str,
            abstract: str,
            spatial_extent: QgsRectangle,
            crs: QgsCoordinateReferenceSystem,
            thumbnail_url: str,
            api_url: str,
            gui_url: str,
            published_date: typing.Optional[dt.datetime] = None,
            temporal_extent: typing.Optional[typing.List[dt.datetime]] = None,
            keywords: typing.Optional[typing.List[str]] = None,
            category: typing.Optional[str] = None,
            service_urls: typing.Dict[str, str] = None
    ):
        self.pk = pk
        self.uuid = uuid
        self.name = name
        self.resource_type = resource_type
        self.title = title
        self.abstract = abstract
        self.spatial_extent = spatial_extent
        self.crs = crs
        self.thumbnail_url = thumbnail_url
        self.api_url = api_url
        self.gui_url = gui_url
        self.published_date = published_date
        self.temporal_extent = temporal_extent
        self.keywords = list(keywords) if keywords is not None else []
        self.category = category
        self.service_urls = service_urls

    @classmethod
    def from_api_response(cls, payload: typing.Dict, geonode_base_url: str):
        return cls(
            pk=int(payload["pk"]),
            uuid=uuid.UUID(payload["uuid"]),
            name=payload.get("name", ""),
            resource_type=_get_resource_type(payload),
            title=payload.get("title", ""),
            abstract=payload.get("abstract", ""),
            spatial_extent=_get_spatial_extent(payload["bbox_polygon"]),
            crs=QgsCoordinateReferenceSystem(payload["srid"].replace("EPSG:", "")),
            thumbnail_url=payload["thumbnail_url"],
            api_url=f"{geonode_base_url}/api/v2/layers/{payload['pk']}",
            gui_url=payload["detail_url"],
            published_date=_get_published_date(payload),
            temporal_extent=_get_temporal_extent(payload),
            keywords=[k["name"] for k in payload.get("keywords", [])],
            category=payload.get("category"),
            service_urls=_build_service_urls(geonode_base_url, payload)
        )


class GeonodeResource(BriefGeonodeResource):
    pass


class BriefGeonodeStyle:
    pk: int
    name: str
    sld_url: str

    def __init__(self, pk: int, name: str, sld_url: str):
        self.pk = pk
        self.name = name
        self.sld_url = sld_url

    @classmethod
    def from_api_response(cls, payload: typing.Dict, geonode_base_url: str):
        return cls(
            pk=payload["pk"],
            name=payload["name"],
            sld_url=payload["sld_url"],
        )


class GeonodeApiEndpoint(enum.Enum):
    LAYER_LIST = "/api/v2/layers/"
    LAYER_DETAILS = "/api/v2/layers/"
    MAP_LIST = "/api/v2/maps/"


class GeonodeClient(QObject):
    """Asynchronous GeoNode API client"""

    auth_config: str
    base_url: str

    layer_list_received = pyqtSignal(list, int, int, int)
    layer_detail_received = pyqtSignal(GeonodeResource)
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
    def from_connection_settings(cls, connection_settings: ConnectionSettings):
        return cls(
            base_url=connection_settings.base_url,
            auth_config=connection_settings.auth_config,
        )

    def get_layers(self, page: typing.Optional[int] = None):
        url = QUrl(f"{self.base_url}{GeonodeApiEndpoint.LAYER_LIST.value}")
        if page:
            query = QUrlQuery()
            query.addQueryItem("page", str(page))
            url.setQuery(query.query())
        request = QNetworkRequest(url)
        self.run_task(request, self.handle_layer_list)

    def get_layer_detail(self, id_: int):
        """Slot to retrieve layer details available in GeoNode"""
        request = QNetworkRequest(
            QUrl(f"{self.base_url}{GeonodeApiEndpoint.LAYER_DETAILS.value}{id_}/")
        )
        self.run_task(request, self.handle_layer_detail)

    def get_layer_styles(self, layer_id: int):
        """Slot to retrieve layer styles available in GeoNode"""
        request = QNetworkRequest(
            QUrl(
                f"{self.base_url}{GeonodeApiEndpoint.LAYER_DETAILS.value}{layer_id}/styles/"
            )
        )
        self.run_task(request, self.handle_layer_style_list)

    def get_maps(self, page: typing.Optional[int] = None):
        """Slot to retrieve list of maps available in GeoNode"""
        url = QUrl(f"{self.base_url}{GeonodeApiEndpoint.MAP_LIST.value}")
        if page:
            query = QUrlQuery()
            query.addQueryItem("page", str(page))
            url.setQuery(query.query())
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
            decoded_contents: str = contents.data().decode()
            payload: typing.Dict = json.loads(decoded_contents)
            handler(payload)
        else:
            QgsMessageLog.logMessage("received error", "qgis_geonode")
            self.error_received.emit(error)

    def handle_layer_list(self, payload: typing.Dict):
        layers = []
        for item in payload.get("layers", []):
            layers.append(BriefGeonodeResource.from_api_response(item, self.base_url))
        self.layer_list_received.emit(
            layers, payload["total"], payload["page"], payload["page_size"]
        )

    def handle_layer_detail(self, payload: typing.Dict):
        layer = GeonodeResource.from_api_response(payload["layer"], self.base_url)
        self.layer_detail_received.emit(layer)

    def handle_layer_style_list(self, payload: typing.Dict):
        styles = []
        for item in payload.get("styles", []):
            styles.append(BriefGeonodeStyle.from_api_response(item, self.base_url))
        self.layer_styles_received.emit(styles)

    def handle_map_list(self, payload: typing.Dict):
        maps = []
        for item in payload.get("maps", []):
            maps.append(BriefGeonodeResource.from_api_response(item, self.base_url))
        self.map_list_received.emit(
            maps, payload["total"], payload["page"], payload["page_size"]
        )


def _get_temporal_extent(
        payload: typing.Dict,
) -> typing.Optional[typing.List[typing.Optional[dt.datetime]]]:
    start = payload["temporal_extent_start"]
    end = payload["temporal_extent_end"]
    if start is not None and end is not None:
        result = [_parse_datetime(start), _parse_datetime(end)]
    elif start is not None and end is None:
        result = [_parse_datetime(start), None]
    elif start is None and end is not None:
        result = [None, _parse_datetime(end)]
    else:
        result = None
    return result


def _parse_datetime(raw_value: str) -> dt.datetime:
    format_ = "%Y-%m-%dT%H:%M:%SZ"
    try:
        result = dt.datetime.strptime(raw_value, format_)
    except ValueError:
        microsecond_format = "%Y-%m-%dT%H:%M:%S.%fZ"
        result = dt.datetime.strptime(raw_value, microsecond_format)
    return result


def _get_published_date(payload: typing.Dict) -> typing.Optional[dt.datetime]:
    if payload["date_type"] == "publication":
        result = _parse_datetime(payload["date"])
    else:
        result = None
    return result


def _get_resource_type(payload: typing.Dict) -> typing.Optional[GeonodeResourceType]:
    resource_type = payload["resource_type"]
    if resource_type == "map":
        result = GeonodeResourceType.MAP
    elif resource_type == "layer":
        result = {
            "coverageStore": GeonodeResourceType.RASTER_LAYER,
            "dataStore": GeonodeResourceType.VECTOR_LAYER,
        }.get(payload.get("storeType"))
    else:
        result = None
    return result


def _get_spatial_extent(geojson_polygon_geometry: typing.Dict) -> QgsRectangle:
    min_x = None
    min_y = None
    max_x = None
    max_y = None
    for coord in geojson_polygon_geometry["coordinates"][0]:
        x, y = coord
        min_x = x if min_x is None else min(x, min_x)
        min_y = y if min_y is None else min(y, min_y)
        max_x = x if max_x is None else max(x, max_x)
        max_y = y if max_y is None else max(y, max_y)
    return QgsRectangle(min_x, min_y, max_x, max_y)


def _get_wms_uri(base_url: str, payload: typing.Dict) -> str:
    uri = 'crs={}&format={}&layers={}:{}&' \
          'styles&url={}/geoserver/ows'.format(
        payload["srid"],
        'image/png',
        payload.get("workspace", ""),
        payload.get("name", ""),
        base_url
    )
    return uri


def _get_wcs_uri(base_url: str, payload: typing.Dict) -> str:

    uri = 'identifier={}:{}&url={}/geoserver/ows'.format(
        payload.get("workspace", ""),
        payload.get("name", ""),
        base_url
    )
    return uri


def _get_wfs_uri(base_url: str, payload: typing.Dict) -> str:
    uri = '{}/geoserver/ows?service=WFS&' \
          'version=1.1.0&request=GetFeature&typename={}:{}'.format(
        base_url,
        payload.get("workspace", ""),
        payload.get("name", "")
    )
    return uri


def _build_service_urls(base_url, payload):
    urls = {}

    resource_type = _get_resource_type(payload)
    urls['wms'] = _get_wms_uri(base_url, payload)

    if resource_type == GeonodeResourceType.RASTER_LAYER:
        urls['wcs'] = _get_wcs_uri(base_url, payload)
    elif resource_type == GeonodeResourceType.VECTOR_LAYER:
        urls['wfs'] = _get_wfs_uri(base_url, payload)

    return urls