import datetime as dt
import json
import typing
import uuid

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsRectangle,
)
from qgis.PyQt.QtCore import (
    QByteArray,
    QUrl,
    QUrlQuery,
)

from . import models
from .models import GeonodeResourceType
from .base import BaseGeonodeClient


class GeonodeApiV2Client(BaseGeonodeClient):
    _api_path: str = "/api/v2"

    @property
    def api_url(self):
        return f"{self.base_url}{self._api_path}"

    def get_layers_url_endpoint(
        self,
        title: typing.Optional[str] = None,
        abstract: typing.Optional[str] = None,
        keyword: typing.Optional[str] = None,
        topic_category: typing.Optional[str] = None,
        layer_types: typing.Optional[typing.List[models.GeonodeResourceType]] = None,
        page: typing.Optional[int] = 1,
        page_size: typing.Optional[int] = 10,
    ) -> QUrl:
        url = QUrl(f"{self.api_url}/layers/")
        query = QUrlQuery()
        query.addQueryItem("page", str(page))
        query.addQueryItem("page_size", str(page_size))
        if title is not None:
            query.addQueryItem("filter{title.icontains}", title)
        if abstract is not None:
            query.addQueryItem("filter{abstract.icontains}", abstract)
        if keyword is not None:  # TODO: Allow using multiple keywords
            query.addQueryItem("filter{keywords.name.icontains}", keyword)
        if topic_category is not None:
            query.addQueryItem("filter{category.identifier}", topic_category)
        if layer_types is None:
            types = [
                GeonodeResourceType.VECTOR_LAYER,
                GeonodeResourceType.RASTER_LAYER,
                GeonodeResourceType.MAP,
            ]
        else:
            types = list(layer_types)
        is_vector = GeonodeResourceType.VECTOR_LAYER in types
        is_raster = GeonodeResourceType.RASTER_LAYER in types
        is_map = GeonodeResourceType.MAP in types
        if is_vector and is_raster:
            pass
        elif is_vector:
            query.addQueryItem("filter{storeType}", "dataStore")
        elif is_raster:
            query.addQueryItem("filter{storeType}", "coverageStore")
        else:
            raise NotImplementedError
        url.setQuery(query.query())
        return url

    def get_layer_detail_url_endpoint(self, id_: int) -> QUrl:
        return QUrl(f"{self.api_url}/layers/{id_}/")

    def get_layer_styles_url_endpoint(self, layer_id: int):
        return QUrl(f"{self.api_url}/layers/{layer_id}/styles/")

    def get_maps_url_endpoint(
        self,
        page: typing.Optional[int] = 1,
        page_size: typing.Optional[int] = 10,
        title: typing.Optional[str] = None,
        keyword: typing.Optional[str] = None,
        topic_category: typing.Optional[str] = None,
    ) -> QUrl:
        url = QUrl(f"{self.api_url}/maps/")
        query = QUrlQuery()
        query.addQueryItem("page", str(page))
        query.addQueryItem("page_size", str(page_size))
        if title:
            query.addQueryItem("filter{title.icontains}", title)
        if keyword:  # TODO: Allow using multiple keywords
            query.addQueryItem("filter{keywords.name.icontains}", keyword)
        if topic_category:
            query.addQueryItem("filter{category.identifier}", topic_category)
        url.setQuery(query.query())
        return url

    def get_layer_detail_from_brief_resource(
        self, brief_resource: models.BriefGeonodeResource
    ):
        self.get_layer_detail(brief_resource.pk)

    def deserialize_response_contents(self, contents: QByteArray) -> typing.Dict:
        decoded_contents: str = contents.data().decode()
        return json.loads(decoded_contents)

    def handle_layer_list(self, payload: typing.Dict):
        layers = []
        for item in payload.get("layers", []):
            layers.append(
                get_brief_geonode_resource(item, self.base_url, self.auth_config)
            )
        pagination_info = models.GeoNodePaginationInfo(
            total_records=payload["total"],
            current_page=payload["page"],
            page_size=payload["page_size"],
        )
        self.layer_list_received.emit(layers, pagination_info)

    def handle_layer_detail(self, payload: typing.Dict):
        layer = get_geonode_resource(payload["layer"], self.base_url, self.auth_config)
        self.layer_detail_received.emit(layer)

    def handle_layer_style_list(self, payload: typing.Dict):
        styles = []
        for item in payload.get("styles", []):
            styles.append(get_brief_geonode_style(item, self.base_url))
        self.layer_styles_received.emit(styles)

    def handle_map_list(self, payload: typing.Dict):
        maps = []
        for item in payload.get("maps", []):
            maps.append(
                get_brief_geonode_resource(item, self.base_url, self.auth_config)
            )
        pagination_info = models.GeoNodePaginationInfo(
            total_records=payload["total"],
            current_page=payload["page"],
            page_size=payload["page_size"],
        )
        self.map_list_received.emit(maps, pagination_info)


def get_brief_geonode_resource(
    deserialized_resource: typing.Dict,
    geonode_base_url: str,
    auth_config: str,
) -> models.BriefGeonodeResource:
    return models.BriefGeonodeResource(
        **_get_common_model_fields(deserialized_resource, geonode_base_url, auth_config)
    )


def get_geonode_resource(
    deserialized_resource: typing.Dict, geonode_base_url: str, auth_config: str
) -> models.GeonodeResource:
    common_fields = _get_common_model_fields(
        deserialized_resource, geonode_base_url, auth_config
    )
    license_value = deserialized_resource.get("license", "")
    if license_value and isinstance(license_value, dict):
        license_ = license_value["identifier"]
    else:
        license_ = license_value
    default_style = get_brief_geonode_style(
        deserialized_resource,
        geonode_base_url
    )
    styles = []
    for item in deserialized_resource.get("styles", []):
        styles.append(get_brief_geonode_style(
            item,
            geonode_base_url
        ))
    return models.GeonodeResource(
        language=deserialized_resource.get("language", ""),
        license=license_,
        constraints=deserialized_resource.get("constraints_other", ""),
        owner=deserialized_resource.get("owner", ""),
        metadata_author=deserialized_resource.get("metadata_author", ""),
        default_style=default_style,
        styles=styles,
        **common_fields,
    )


def _get_common_model_fields(
    deserialized_resource: typing.Dict, geonode_base_url: str, auth_config: str
) -> typing.Dict:
    resource_type = _get_resource_type(deserialized_resource)
    if resource_type == GeonodeResourceType.VECTOR_LAYER:
        service_urls = {
            "wms": _get_wms_uri(auth_config, geonode_base_url, deserialized_resource),
            "wfs": _get_wfs_uri(auth_config, geonode_base_url, deserialized_resource),
        }
    elif resource_type == GeonodeResourceType.RASTER_LAYER:
        service_urls = {
            "wms": _get_wms_uri(auth_config, geonode_base_url, deserialized_resource),
            "wcs": _get_wcs_uri(auth_config, geonode_base_url, deserialized_resource),
        }
    elif resource_type == GeonodeResourceType.MAP:
        service_urls = None  # FIXME: devise a way to retrieve WMS URL for maps
    else:
        service_urls = None
    reported_category = deserialized_resource.get("category")
    category = reported_category["identifier"] if reported_category else None
    return {
        "pk": int(deserialized_resource["pk"]),
        "uuid": uuid.UUID(deserialized_resource["uuid"]),
        "name": deserialized_resource.get("name", ""),
        "resource_type": resource_type,
        "title": deserialized_resource.get("title", ""),
        "abstract": deserialized_resource.get("abstract", ""),
        "spatial_extent": _get_spatial_extent(deserialized_resource["bbox_polygon"]),
        "crs": QgsCoordinateReferenceSystem(deserialized_resource["srid"]),
        "thumbnail_url": deserialized_resource["thumbnail_url"],
        "api_url": (f"{geonode_base_url}/api/v2/layers/{deserialized_resource['pk']}"),
        "gui_url": f"{geonode_base_url}{deserialized_resource['detail_url']}",
        "published_date": _get_published_date(deserialized_resource),
        "temporal_extent": _get_temporal_extent(deserialized_resource),
        "keywords": [k["name"] for k in deserialized_resource.get("keywords", [])],
        "category": category,
        "service_urls": service_urls,
    }


def get_brief_geonode_style(deserialized_style: typing.Dict, geonode_base_url: str):
    sld_url = _get_sld_style_url(geonode_base_url, deserialized_style)
    return models.BriefGeonodeStyle(
        name=deserialized_style["name"],
        sld_url=sld_url,
    )


def _get_resource_type(
    payload: typing.Dict,
) -> typing.Optional[models.GeonodeResourceType]:
    resource_type = payload["resource_type"]
    if resource_type == "map":
        result = models.GeonodeResourceType.MAP
    elif resource_type == "layer":
        result = {
            "coverageStore": models.GeonodeResourceType.RASTER_LAYER,
            "dataStore": models.GeonodeResourceType.VECTOR_LAYER,
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


def _get_wms_uri(auth_config: str, base_url: str, payload: typing.Dict):
    layer_name = f"{payload['workspace']}:{payload['name']}"
    return (
        f"crs={payload['srid']}&format=image/png&layers={layer_name}&"
        f"styles&url={base_url}/geoserver/ows&authkey={auth_config}"
    )


def _get_wcs_uri(auth_config: str, base_url: str, payload: typing.Dict):
    layer_name = f"{payload['workspace']}:{payload['name']}"
    return (
        f"identifier={layer_name}&url={base_url}/geoserver/ows&"
        f"authkey={auth_config}"
    )


def _get_wfs_uri(auth_config: str, base_url: str, payload: typing.Dict):
    layer_name = f"{payload['workspace']}:{payload['name']}"
    return (
        f"{base_url}/geoserver/ows?service=WFS&version=1.1.0&"
        f"request=GetFeature&typename={layer_name}&authkey={auth_config}"
    )


def _get_sld_style_url(base_url: str, payload: typing.Dict):

    return (
        f"{base_url}/geoserver/rest/workspaces/"
        f"{payload['workspace']}/styles/{payload['name']}.sld"
    )
