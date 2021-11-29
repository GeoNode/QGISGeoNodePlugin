import datetime as dt
import typing
import uuid

import qgis.core
from qgis.PyQt import QtCore

from .. import network
from ..utils import log

from . import models
from .base import BaseGeonodeClient


class GeonodeLegacyApiClient(BaseGeonodeClient):
    """API client for GeoNode versions where there is no v2 API."""

    capabilities = [
        models.ApiClientCapability.FILTER_BY_TITLE,
        models.ApiClientCapability.FILTER_BY_ABSTRACT,
    ]

    @property
    def api_url(self):
        return f"{self.base_url}/api"

    @property
    def dataset_list_url(self):
        return f"{self.api_url}/layers/"

    def get_ordering_fields(self) -> typing.List[typing.Tuple[str, str]]:
        return [
            ("title", "Title"),
        ]

    def build_search_query(
        self, search_filters: models.GeonodeApiSearchFilters
    ) -> QtCore.QUrlQuery:
        query = QtCore.QUrlQuery()
        query.addQueryItem("limit", str(self.page_size))
        query.addQueryItem("offset", str(search_filters.page * self.page_size))
        if search_filters.title is not None:
            query.addQueryItem("title__icontains", search_filters.title)
        if search_filters.abstract is not None:
            query.addQueryItem("abstract__icontains", search_filters.abstract)
        if search_filters.ordering_field is not None:
            query.addQueryItem(
                "order_by",
                (
                    f"{'-' if search_filters.reverse_ordering else ''}"
                    f"{search_filters.ordering_field}"
                ),
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
                    for raw_brief_dataset in deserialized_content.get("objects", []):
                        try:
                            parsed_properties = self._get_common_model_properties(
                                raw_brief_dataset
                            )
                            brief_dataset = models.BriefDataset(**parsed_properties)
                        except ValueError:
                            log(
                                f"Could not parse {raw_brief_dataset!r} into a "
                                f"valid item",
                                debug=False,
                            )
                        else:
                            brief_datasets.append(brief_dataset)
                    meta = deserialized_content.get("meta", {})
                    page_size = meta.get("limit", self.page_size)
                    current_page = meta.get("offset", 0) * page_size
                    pagination_info = models.GeonodePaginationInfo(
                        total_records=meta.get("total_count") or 0,
                        current_page=current_page,
                        page_size=page_size,
                    )
        self.dataset_list_received.emit(brief_datasets, pagination_info)

    def _get_common_model_properties(self, raw_dataset: typing.Dict) -> typing.Dict:
        type_ = _get_resource_type(raw_dataset)
        return {
            "pk": int(raw_dataset["id"]),
            "uuid": uuid.UUID(raw_dataset["uuid"]),
            "name": raw_dataset.get("alternate", raw_dataset.get("name", "")),
            "title": raw_dataset.get("title", ""),
            "abstract": raw_dataset.get("raw_abstract", ""),
            "thumbnail_url": raw_dataset["thumbnail_url"],
            "link": f"{self.api_url}{raw_dataset['resource_uri']}",
            "detail_url": f"{self.base_url}/{raw_dataset['detail_url']}",
            "dataset_sub_type": type_,
            "service_urls": self._get_service_urls(type_),
            "spatial_extent": qgis.core.QgsRectangle.fromWkt(
                raw_dataset["csw_wkt_geometry"]
            ),
            "srid": qgis.core.QgsCoordinateReferenceSystem(raw_dataset["srid"]),
            "published_date": _get_published_date(raw_dataset),
            "temporal_extent": _get_temporal_extent(raw_dataset),
            "keywords": raw_dataset.get("keywords", []),
        }

    def _get_service_urls(
        self, resource_type: models.GeonodeResourceType
    ) -> typing.Dict:
        common_url = f"{self.base_url}/geoserver/ows"
        result = {models.GeonodeService.OGC_WMS: common_url}
        if resource_type == models.GeonodeResourceType.VECTOR_LAYER:
            result[models.GeonodeService.OGC_WFS] = common_url
        elif resource_type == models.GeonodeResourceType.RASTER_LAYER:
            result[models.GeonodeService.OGC_WCS] = common_url
        return result


def _get_resource_type(
    raw_dataset: typing.Dict,
) -> typing.Optional[models.GeonodeResourceType]:
    return {
        "dataStore": models.GeonodeResourceType.VECTOR_LAYER,
        "coverageStore": models.GeonodeResourceType.RASTER_LAYER,
    }.get(raw_dataset.get("storeType", raw_dataset.get("store_type")))


def _parse_datetime(raw_value: str) -> dt.datetime:
    format_ = "%Y-%m-%dT%H:%M:%S"
    return dt.datetime.strptime(raw_value, format_)


def _get_published_date(payload: typing.Dict) -> typing.Optional[dt.datetime]:
    if payload["date_type"] == "publication":
        result = _parse_datetime(payload["date"])
    else:
        result = None
    return result


def _get_temporal_extent(
    payload: typing.Dict,
) -> typing.Optional[typing.List[typing.Optional[dt.datetime]]]:
    start = payload.get("temporal_extent_start")
    end = payload.get("temporal_extent_end")
    if start is not None and end is not None:
        result = [_parse_datetime(start), _parse_datetime(end)]
    elif start is not None and end is None:
        result = [_parse_datetime(start), None]
    elif start is None and end is not None:
        result = [None, _parse_datetime(end)]
    else:
        result = None
    return result
