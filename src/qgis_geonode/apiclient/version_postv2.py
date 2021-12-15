import datetime as dt
import typing
import uuid

import qgis.core
from qgis.PyQt import QtCore

from .. import network
from .. import styles as geonode_styles
from ..utils import log

from . import models
from .base import BaseGeonodeClient


class GeonodePostV2ApiClient(BaseGeonodeClient):
    """An API Client for GeoNode versions above v3.2"""

    capabilities = [
        models.ApiClientCapability.FILTER_BY_TITLE,
        models.ApiClientCapability.FILTER_BY_RESOURCE_TYPES,
        models.ApiClientCapability.FILTER_BY_ABSTRACT,
        models.ApiClientCapability.FILTER_BY_KEYWORD,
        models.ApiClientCapability.FILTER_BY_TOPIC_CATEGORY,
        models.ApiClientCapability.FILTER_BY_PUBLICATION_DATE,
        models.ApiClientCapability.FILTER_BY_TEMPORAL_EXTENT,
        models.ApiClientCapability.LOAD_LAYER_METADATA,
        models.ApiClientCapability.LOAD_VECTOR_LAYER_STYLE,
        # NOTE: loading raster layer style is not present here
        # because QGIS does not currently support loading SLD for raster layers
        models.ApiClientCapability.MODIFY_VECTOR_LAYER_STYLE,
        models.ApiClientCapability.MODIFY_RASTER_LAYER_STYLE,
        models.ApiClientCapability.LOAD_VECTOR_DATASET_VIA_WMS,
        models.ApiClientCapability.LOAD_VECTOR_DATASET_VIA_WFS,
        models.ApiClientCapability.LOAD_RASTER_DATASET_VIA_WMS,
        models.ApiClientCapability.LOAD_RASTER_DATASET_VIA_WCS,
    ]

    @property
    def api_url(self):
        return f"{self.base_url}/api/v2"

    @property
    def dataset_list_url(self):
        return f"{self.api_url}/datasets/"

    def get_ordering_fields(self) -> typing.List[typing.Tuple[str, str]]:
        return [
            ("title", "Title"),
        ]

    def build_search_query(
        self, search_filters: models.GeonodeApiSearchFilters
    ) -> QtCore.QUrlQuery:
        query = QtCore.QUrlQuery()
        query.addQueryItem("page", str(search_filters.page))
        query.addQueryItem("page_size", str(self.page_size))
        if search_filters.title is not None:
            query.addQueryItem("filter{title.icontains}", search_filters.title)
        if search_filters.abstract is not None:
            query.addQueryItem("filter{abstract.icontains}", search_filters.abstract)
        if search_filters.keyword is not None:
            query.addQueryItem(
                "filter{keywords.name.icontains}", search_filters.keyword
            )
        if search_filters.topic_category is not None:
            query.addQueryItem(
                "filter{category.identifier}",
                search_filters.topic_category.name.lower(),
            )
        if search_filters.temporal_extent_start is not None:
            query.addQueryItem(
                "filter{temporal_extent_start.gte}",
                search_filters.temporal_extent_start.toString(QtCore.Qt.ISODate),
            )
        if search_filters.temporal_extent_end is not None:
            query.addQueryItem(
                "filter{temporal_extent_end.lte}",
                search_filters.temporal_extent_end.toString(QtCore.Qt.ISODate),
            )
        if search_filters.publication_date_start is not None:
            query.addQueryItem(
                "filter{date.gte}",
                search_filters.publication_date_start.toString(QtCore.Qt.ISODate),
            )
        if search_filters.publication_date_end is not None:
            query.addQueryItem(
                "filter{date.lte}",
                search_filters.publication_date_end.toString(QtCore.Qt.ISODate),
            )
        # TODO revisit once the support for spatial extent is available on
        # GeoNode API V2
        if (
            search_filters.spatial_extent is not None
            and not search_filters.spatial_extent.isNull()
        ):
            pass
        if search_filters.layer_types is None:
            types = [
                models.GeonodeResourceType.VECTOR_LAYER,
                models.GeonodeResourceType.RASTER_LAYER,
            ]
        else:
            types = list(search_filters.layer_types)
        is_vector = models.GeonodeResourceType.VECTOR_LAYER in types
        is_raster = models.GeonodeResourceType.RASTER_LAYER in types
        if is_vector:
            query.addQueryItem("filter{subtype}", "vector")
        if is_raster:
            query.addQueryItem("filter{subtype}", "raster")
        if search_filters.ordering_field is not None:
            query.addQueryItem(
                "sort[]", f"{'-' if search_filters.reverse_ordering else ''}name"
            )
        return query

    def get_dataset_list_url(
        self, search_filters: models.GeonodeApiSearchFilters
    ) -> QtCore.QUrl:
        url = QtCore.QUrl(self.dataset_list_url)
        query = self.build_search_query(search_filters)
        url.setQuery(query.query())
        return url

    def get_dataset_detail_url(self, dataset_id: int) -> QtCore.QUrl:
        return QtCore.QUrl(f"{self.dataset_list_url}{dataset_id}/")

    def get_layer_style_list_url(self, layer_id: int):
        return QtCore.QUrl(f"{self.dataset_list_url}{layer_id}/styles/")

    def handle_dataset_list(self, result: bool):
        brief_datasets = []
        pagination_info = models.GeonodePaginationInfo(
            total_records=0, current_page=1, page_size=0
        )
        if result:
            response_content: network.ParsedNetworkReply = (
                self.network_fetcher_task.response_contents[0]
            )
            if response_content.qt_error is None:
                deserialized_content = network.deserialize_json_response(
                    response_content.response_body
                )
                if deserialized_content is not None:
                    for raw_brief_dataset in deserialized_content.get("datasets", []):
                        try:
                            parsed_properties = _get_common_model_properties(
                                raw_brief_dataset
                            )
                            brief_dataset = models.BriefDataset(**parsed_properties)
                        except ValueError:
                            log(
                                f"Could not parse {raw_brief_dataset!r} into "
                                f"a valid item",
                                debug=False,
                            )
                        else:
                            brief_datasets.append(brief_dataset)
                    pagination_info = models.GeonodePaginationInfo(
                        total_records=deserialized_content.get("total") or 0,
                        current_page=deserialized_content.get("page") or 1,
                        page_size=deserialized_content.get("page_size") or 0,
                    )
            else:
                self.error_received[str, int, str].emit(
                    response_content.qt_error,
                    response_content.http_status_code,
                    response_content.http_status_reason,
                )
        else:
            self.error_received[str].emit("Could not complete request")
        self.dataset_list_received.emit(brief_datasets, pagination_info)

    def handle_dataset_detail(self, brief_dataset: models.BriefDataset, result: bool):
        dataset = None
        if result:
            detail_response_content: network.ParsedNetworkReply = (
                self.network_fetcher_task.response_contents[0]
            )
            deserialized_resource = network.deserialize_json_response(
                detail_response_content.response_body
            )
            if deserialized_resource is not None:
                try:
                    dataset = parse_dataset_detail(deserialized_resource["dataset"])
                except KeyError as exc:
                    log(
                        f"Could not parse server response into a dataset: {str(exc)}",
                        debug=False,
                    )
                else:
                    is_vector = (
                        brief_dataset.dataset_sub_type
                        == models.GeonodeResourceType.VECTOR_LAYER
                    )
                    if is_vector:
                        sld_named_layer, error_message = geonode_styles.get_usable_sld(
                            self.network_fetcher_task.response_contents[1]
                        )
                        if sld_named_layer is None:
                            raise RuntimeError(error_message)
                        dataset.default_style.sld = sld_named_layer
        self.dataset_detail_received.emit(dataset)


def parse_dataset_detail(raw_dataset: typing.Dict) -> models.Dataset:
    properties = _get_common_model_properties(raw_dataset)
    properties.update(
        language=raw_dataset.get("language"),
        license=(raw_dataset.get("license") or {}).get("identifier", ""),
        constraints=raw_dataset.get("raw_constraints_other", ""),
        owner=raw_dataset.get("owner", {}).get("username", ""),
        metadata_author=raw_dataset.get("metadata_author", {}).get("username", ""),
    )
    return models.Dataset(**properties)


def _get_common_model_properties(raw_dataset: typing.Dict) -> typing.Dict:
    type_ = _get_resource_type(raw_dataset)
    raw_links = raw_dataset.get("links", [])
    if type_ == models.GeonodeResourceType.VECTOR_LAYER:
        service_urls = _get_vector_service_urls(raw_links)
    elif type_ == models.GeonodeResourceType.RASTER_LAYER:
        service_urls = _get_raster_service_urls(raw_links)
    else:
        service_urls = {}
    raw_style = raw_dataset.get("default_style") or {}
    return {
        "pk": int(raw_dataset["pk"]),
        "uuid": uuid.UUID(raw_dataset["uuid"]),
        "name": raw_dataset.get("alternate", raw_dataset.get("name", "")),
        "title": raw_dataset.get("title", ""),
        "abstract": raw_dataset.get("raw_abstract", ""),
        "thumbnail_url": raw_dataset["thumbnail_url"],
        "link": raw_dataset.get("link"),
        "detail_url": raw_dataset["detail_url"],
        "dataset_sub_type": type_,
        "service_urls": service_urls,
        "spatial_extent": _get_spatial_extent(raw_dataset["bbox_polygon"]),
        "srid": qgis.core.QgsCoordinateReferenceSystem(raw_dataset["srid"]),
        "published_date": _get_published_date(raw_dataset),
        "temporal_extent": _get_temporal_extent(raw_dataset),
        "keywords": [k["name"] for k in raw_dataset.get("keywords", [])],
        "category": (raw_dataset.get("category") or {}).get("identifier"),
        "default_style": models.BriefGeonodeStyle(
            name=raw_style.get("name", ""), sld_url=raw_style.get("sld_url")
        ),
    }


def _get_link(raw_links: typing.List, link_type: str) -> typing.Optional[str]:
    for link_info in raw_links:
        if link_info.get("link_type") == link_type:
            result = link_info.get("url")
            break
    else:
        result = None
    return result


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


def _get_resource_type(
    raw_dataset: typing.Dict,
) -> typing.Optional[models.GeonodeResourceType]:
    result = {
        "raster": models.GeonodeResourceType.RASTER_LAYER,
        "vector": models.GeonodeResourceType.VECTOR_LAYER,
    }.get(raw_dataset.get("subtype"))
    return result


def _get_vector_service_urls(raw_links: typing.Dict):
    return {
        models.GeonodeService.OGC_WMS: _get_link(raw_links, "OGC:WMS"),
        models.GeonodeService.OGC_WFS: _get_link(raw_links, "OGC:WFS"),
    }


def _get_raster_service_urls(raw_links: typing.Dict):
    return {
        models.GeonodeService.OGC_WMS: _get_link(raw_links, "OGC:WMS"),
        models.GeonodeService.OGC_WCS: _get_link(raw_links, "OGC:WCS"),
    }


def _get_spatial_extent(
    geojson_polygon_geometry: typing.Dict,
) -> qgis.core.QgsRectangle:
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
    return qgis.core.QgsRectangle(min_x, min_y, max_x, max_y)


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
