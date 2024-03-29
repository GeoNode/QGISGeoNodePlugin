import datetime as dt
import json
import typing
import uuid

import qgis_geonode.apiclient.models
from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsDateTimeRange,
    QgsRectangle,
)
from qgis.PyQt import (
    QtCore,
)

from ..utils import log
from . import models
from . import base


class GeonodeApiV2Client(base.BaseGeonodeClient):

    capabilities = [
        models.ApiClientCapability.FILTER_BY_TITLE,
        models.ApiClientCapability.FILTER_BY_ABSTRACT,
        models.ApiClientCapability.FILTER_BY_KEYWORD,
        models.ApiClientCapability.FILTER_BY_TOPIC_CATEGORY,
        models.ApiClientCapability.FILTER_BY_RESOURCE_TYPES,
        models.ApiClientCapability.FILTER_BY_TEMPORAL_EXTENT,
        models.ApiClientCapability.FILTER_BY_PUBLICATION_DATE,
        models.ApiClientCapability.LOAD_VECTOR_DATASET_VIA_WMS,
        models.ApiClientCapability.LOAD_VECTOR_DATASET_VIA_WFS,
    ]

    @property
    def api_url(self):
        return f"{self.base_url}/api/v2"

    def get_ordering_filter_name(
        self,
        ordering_type: models.OrderingType,
        reverse_sort: typing.Optional[bool] = False,
    ) -> str:
        name = {
            models.OrderingType.TITLE: "name",
        }[ordering_type]
        return f"{'-' if reverse_sort else ''}{name}"

    def get_search_result_identifier(
        self, resource: models.BriefGeonodeResource
    ) -> str:
        return resource.name

    def get_layers_url_endpoint(
        self, search_params: models.GeonodeApiSearchFilters
    ) -> QtCore.QUrl:
        url = QtCore.QUrl(f"{self.api_url}/datasets/")
        query = self._build_search_query(search_params)
        url.setQuery(query.query())
        return url

    def _build_search_query(
        self, search_params: models.GeonodeApiSearchFilters
    ) -> QtCore.QUrlQuery:
        query = QtCore.QUrlQuery()
        query.addQueryItem("page", str(search_params.page))
        query.addQueryItem("page_size", str(search_params.page_size))
        if search_params.title is not None:
            query.addQueryItem("filter{title.icontains}", search_params.title)
        if search_params.abstract is not None:
            query.addQueryItem("filter{abstract.icontains}", search_params.abstract)
        if search_params.selected_keyword is not None:
            query.addQueryItem(
                "filter{keywords.name.icontains}", search_params.selected_keyword
            )
        if search_params.topic_category is not None:
            query.addQueryItem(
                "filter{category.identifier}", search_params.topic_category
            )
        if search_params.temporal_extent_start is not None:
            query.addQueryItem(
                "filter{temporal_extent_start.gte}",
                search_params.temporal_extent_start.toString(QtCore.Qt.ISODate),
            )
        if search_params.temporal_extent_end is not None:
            query.addQueryItem(
                "filter{temporal_extent_end.lte}",
                search_params.temporal_extent_end.toString(QtCore.Qt.ISODate),
            )
        if search_params.publication_date_start is not None:
            query.addQueryItem(
                "filter{date.gte}",
                search_params.publication_date_start.toString(QtCore.Qt.ISODate),
            )
        if search_params.publication_date_end is not None:
            query.addQueryItem(
                "filter{date.lte}",
                search_params.publication_date_end.toString(QtCore.Qt.ISODate),
            )
        # TODO revisit once the support for spatial extent is available on
        # GeoNode API V2
        if (
            search_params.spatial_extent is not None
            and not search_params.spatial_extent.isNull()
        ):
            pass
        if search_params.layer_types is None:
            types = [
                models.GeonodeResourceType.VECTOR_LAYER,
                models.GeonodeResourceType.RASTER_LAYER,
                models.GeonodeResourceType.MAP,
            ]
        else:
            types = list(search_params.layer_types)
        is_vector = models.GeonodeResourceType.VECTOR_LAYER in types
        is_raster = models.GeonodeResourceType.RASTER_LAYER in types
        is_map = models.GeonodeResourceType.MAP in types
        if is_vector and is_raster:
            pass
        elif is_vector:
            query.addQueryItem("filter{subtype}", "vector")
        elif is_raster:
            query.addQueryItem("filter{subtype}", "raster")
        else:
            raise NotImplementedError
        if search_params.ordering_field is not None:
            ordering_field_value = self.get_ordering_filter_name(
                search_params.ordering_field,
                reverse_sort=search_params.reverse_ordering,
            )
            query.addQueryItem("sort[]", ordering_field_value)
        return query

    def get_layer_detail_url_endpoint(self, id_: int) -> QtCore.QUrl:
        return QtCore.QUrl(f"{self.api_url}/datasets/{id_}/")

    def get_layer_styles_url_endpoint(self, layer_id: int):
        return QtCore.QUrl(f"{self.api_url}/datasets/{layer_id}/styles/")

    def get_maps_url_endpoint(
        self,
        search_params: base.GeonodeApiSearchFilters,
    ) -> QtCore.QUrl:
        url = QtCore.QUrl(f"{self.api_url}/maps/")
        query = self._build_search_query(search_params)
        url.setQuery(query.query())
        return url

    def get_layer_detail_from_brief_resource(
        self, brief_resource: models.BriefGeonodeResource
    ):
        self.get_layer_detail(brief_resource.pk)

    def deserialize_response_contents(
        self, contents: QtCore.QByteArray
    ) -> typing.Optional[typing.Union[typing.List, typing.Dict]]:
        decoded_contents: str = contents.data().decode()
        try:
            contents = json.loads(decoded_contents)
        except json.JSONDecodeError as exc:
            log(f"decoded_contents: {decoded_contents}")
            log(exc, debug=False)
            contents = None
        return contents

    #
    # def old_handle_layer_list(
    #     self,
    #     original_search_params: base.GeonodeApiSearchParameters,
    #     raw_reply_contents: QtCore.QByteArray,
    # ):
    #     deserialized = self.deserialize_response_contents(raw_reply_contents)
    #     layers = []
    #     for item in deserialized.get("layers", []):
    #         try:
    #             brief_resource = get_brief_geonode_resource(
    #                 item, self.base_url, self.auth_config
    #             )
    #         except ValueError:
    #             log(f"Could not parse {item!r} into a valid item")
    #         else:
    #             layers.append(brief_resource)
    #     pagination_info = models.GeoNodePaginationInfo(
    #         total_records=deserialized["total"],
    #         current_page=deserialized["page"],
    #         page_size=deserialized["page_size"],
    #     )
    #     self.layer_list_received.emit(layers, pagination_info)

    def handle_layer_list(
        self,
        original_search_params: base.GeonodeApiSearchFilters,
    ):
        deserialized = self.deserialize_response_contents(
            self.network_fetcher_task.reply_content
        )
        layers = []
        if deserialized is not None:
            for item in deserialized.get("datasets", []):
                try:
                    brief_resource = get_brief_geonode_resource(
                        item, self.base_url, self.auth_config
                    )
                except ValueError:
                    log(f"Could not parse {item!r} into a valid item")
                else:
                    layers.append(brief_resource)
            pagination_info = models.GeonodePaginationInfo(
                total_records=deserialized.get("total") or 0,
                current_page=deserialized.get("page") or 1,
                page_size=deserialized.get("page_size") or 0,
            )
        else:
            pagination_info = models.GeonodePaginationInfo(
                total_records=0, current_page=1, page_size=0
            )
        self.layer_list_received.emit(layers, pagination_info)

    def handle_layer_detail(self):
        deserialized = self.deserialize_response_contents(
            self.network_fetcher_task.reply_content
        )
        if deserialized is not None:
            layer = get_geonode_resource(
                deserialized["dataset"], self.base_url, self.auth_config
            )
            self.layer_detail_received.emit(layer)

    def handle_layer_style_list(self):
        deserialized = self.deserialize_response_contents(
            self.network_fetcher_task.reply_content
        )
        styles = []
        for item in deserialized.get("styles", []):
            styles.append(get_brief_geonode_style(item, self.base_url))
        self.layer_styles_received.emit(styles)

    def handle_map_list(
        self,
        original_search_params: base.GeonodeApiSearchFilters,
    ):
        deserialized = self.deserialize_response_contents(
            self.network_fetcher_task.reply_content
        )
        maps = []
        for item in deserialized.get("maps", []):
            maps.append(
                get_brief_geonode_resource(item, self.base_url, self.auth_config)
            )
        pagination_info = models.GeonodePaginationInfo(
            total_records=deserialized["total"],
            current_page=deserialized["page"],
            page_size=deserialized["page_size"],
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
    default_style = get_brief_geonode_style(deserialized_resource, geonode_base_url)
    styles = []
    for item in deserialized_resource.get("styles", []):
        styles.append(get_brief_geonode_style(item, geonode_base_url))
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
    if resource_type == models.GeonodeResourceType.VECTOR_LAYER:
        service_urls = {
            models.GeonodeService.OGC_WMS: _get_wms_uri(
                geonode_base_url, deserialized_resource, auth_config=auth_config
            ),
            models.GeonodeService.OGC_WFS: _get_wfs_uri(
                geonode_base_url, deserialized_resource, auth_config=auth_config
            ),
        }
    elif resource_type == models.GeonodeResourceType.RASTER_LAYER:
        service_urls = {
            models.GeonodeService.OGC_WMS: _get_wms_uri(
                geonode_base_url, deserialized_resource, auth_config=auth_config
            ),
            models.GeonodeService.OGC_WCS: _get_wcs_uri(
                geonode_base_url, deserialized_resource, auth_config=auth_config
            ),
        }
    elif resource_type == models.GeonodeResourceType.MAP:
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
        "api_url": (
            f"{geonode_base_url}/api/v2/datasets/{deserialized_resource['pk']}"
        ),
        "gui_url": deserialized_resource["detail_url"],
        "published_date": _get_published_date(deserialized_resource),
        "temporal_extent": _get_temporal_extent(deserialized_resource),
        "keywords": [k["name"] for k in deserialized_resource.get("keywords", [])],
        "category": category,
        "service_urls": service_urls,
    }


def get_brief_geonode_style(deserialized_style: typing.Dict, geonode_base_url: str):
    sld_url = (
        f"{geonode_base_url}/geoserver/rest/workspaces/"
        f"{deserialized_style['workspace']}/styles/{deserialized_style['name']}.sld"
    )

    return models.BriefGeonodeStyle(
        name=deserialized_style["name"],
        sld_url=sld_url,
    )


def _get_resource_type(
    payload: typing.Dict,
) -> typing.Optional[models.GeonodeResourceType]:
    resource_type = payload.get("resource_type")
    if resource_type == "map":
        result = models.GeonodeResourceType.MAP
    elif resource_type == "dataset":
        result = {
            "raster": models.GeonodeResourceType.RASTER_LAYER,
            "vector": models.GeonodeResourceType.VECTOR_LAYER,
        }.get(payload.get("subtype"))
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


def _get_wms_uri(
    base_url: str,
    payload: typing.Dict,
    auth_config: typing.Optional[str] = None,
) -> str:
    params = {
        "url": f"{base_url}/geoserver/ows",
        "format": "image/png",
        "layers": f"{payload['workspace']}:{payload['name']}",
        "crs": payload["srid"],
        "styles": "",
        "version": "auto",
    }
    if auth_config is not None:
        params["authcfg"] = auth_config
    return "&".join(f"{k}={v.replace('=', '%3D')}" for k, v in params.items())


def _get_wcs_uri(
    base_url: str,
    payload: typing.Dict,
    auth_config: typing.Optional[str] = None,
) -> str:
    params = {
        "identifier": f"{payload['workspace']}:{payload['name']}",
        "url": f"{base_url}/geoserver/ows",
    }
    if auth_config is not None:
        params["authcfg"] = auth_config
    return "&".join(f"{k}={v.replace('=', '%3D')}" for k, v in params.items())


def _get_wfs_uri(
    base_url: str, payload: typing.Dict, auth_config: typing.Optional[str] = None
) -> str:
    params = {
        "url": f"{base_url}/geoserver/ows",
        "typename": f"{payload['workspace']}:{payload['name']}",
        "version": "auto",
    }
    if auth_config is not None:
        params["authcfg"] = auth_config
    return " ".join(f"{k}='{v}'" for k, v in params.items())
