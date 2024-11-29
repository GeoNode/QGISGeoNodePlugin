"""API client class for GeoNode 4"""

import datetime as dt
import json
import typing
import uuid

import qgis.core
import qgis.utils
from qgis.PyQt import (
    QtCore,
    QtNetwork,
)

from .. import network
from .. import styles as geonode_styles
from ..utils import log, url_from_geoserver
from ..tasks import tasks

from . import models
from .base import BaseGeonodeClient


class GeoNodeApiClient(BaseGeonodeClient):

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
        models.ApiClientCapability.MODIFY_LAYER_METADATA,
        # NOTE: loading raster layer style is not present here
        # because QGIS does not currently support loading SLD for raster layers
        models.ApiClientCapability.MODIFY_VECTOR_LAYER_STYLE,
        models.ApiClientCapability.MODIFY_RASTER_LAYER_STYLE,
        models.ApiClientCapability.LOAD_VECTOR_DATASET_VIA_WMS,
        models.ApiClientCapability.LOAD_VECTOR_DATASET_VIA_WFS,
        models.ApiClientCapability.LOAD_RASTER_DATASET_VIA_WMS,
        models.ApiClientCapability.LOAD_RASTER_DATASET_VIA_WCS,
        models.ApiClientCapability.UPLOAD_VECTOR_LAYER,
        models.ApiClientCapability.UPLOAD_RASTER_LAYER,
    ]

    _DATASET_NAME = "dataset"
    _DATASET_NAME_PLURAL = "datasets"

    @property
    def api_url(self):
        return f"{self.base_url}/api/v2"

    @property
    def dataset_list_url(self):
        return f"{self.api_url}/{self._DATASET_NAME_PLURAL}/"

    def get_ordering_fields(self) -> typing.List[typing.Tuple[str, str]]:
        return [
            ("title", "Title"),
        ]

    def get_dataset_upload_url(self) -> QtCore.QUrl:
        return QtCore.QUrl(f"{self.api_url}/uploads/upload/")

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
            query.addQueryItem("filter{subtype.in}", "vector")
        if is_raster:
            query.addQueryItem("filter{subtype.in}", "raster")
        if search_filters.ordering_field is not None:
            query.addQueryItem(
                "sort[]", f"{'-' if search_filters.reverse_ordering else ''}name"
            )
        return query

    def handle_dataset_detail_from_id(self, task_result: bool) -> None:
        deserialized_resource = self._retrieve_response(
            task_result, 0, self.dataset_detail_error_received
        )
        if deserialized_resource is not None:
            try:
                dataset = self._parse_dataset_detail(deserialized_resource["dataset"])
            except KeyError as exc:
                log(
                    f"Could not parse server response into a dataset: {str(exc)}",
                    debug=False,
                )
            else:
                if dataset.dataset_sub_type == models.GeonodeResourceType.VECTOR_LAYER:
                    self.get_dataset_style(dataset, emit_dataset_detail_received=True)
                else:
                    self.dataset_detail_received.emit(dataset)

    def get_uploader_task(
        self, layer: qgis.core.QgsMapLayer, allow_public_access: bool, timeout: int
    ) -> qgis.core.QgsTask:
        return tasks.LayerUploaderTask(
            layer,
            self.get_dataset_upload_url(),
            allow_public_access,
            self.auth_config,
            network_task_timeout=timeout,
            description="Upload layer to GeoNode",
        )

    def handle_layer_upload(self, result: bool):
        success_statuses = (
            200,
            201,
        )
        if result:
            response_contents = self.network_fetcher_task.response_contents[0]
            if response_contents.http_status_code in success_statuses:
                self.dataset_uploaded.emit()
            else:
                self.dataset_upload_error_received[str, int, str].emit(
                    response_contents.qt_error,
                    response_contents.http_status_code,
                    response_contents.http_status_reason,
                )
        else:
            self.dataset_upload_error_received[str].emit(
                "Could not upload layer to GeoNode"
            )

    def _get_service_urls(
        self,
        raw_links: typing.Dict,
        dataset_type: models.GeonodeResourceType,
    ) -> typing.Dict[models.GeonodeService, str]:
        result = {models.GeonodeService.OGC_WMS: _get_link(raw_links, "OGC:WMS")}
        if dataset_type == models.GeonodeResourceType.VECTOR_LAYER:
            result[models.GeonodeService.OGC_WFS] = _get_link(raw_links, "OGC:WFS")
        elif dataset_type == models.GeonodeResourceType.RASTER_LAYER:
            result[models.GeonodeService.OGC_WCS] = _get_link(raw_links, "OGC:WCS")
        else:
            log(f"Invalid dataset type: {dataset_type}")
            result = {}
        auth_manager = qgis.core.QgsApplication.authManager()
        auth_provider_name = auth_manager.configAuthMethodKey(self.auth_config).lower()
        if auth_provider_name == "basic":
            for service_type, retrieved_url in result.items():
                try:
                    result[service_type] = url_from_geoserver(
                        self.base_url, retrieved_url
                    )
                    log(f"result[service_type]: {result[service_type]}")
                except AttributeError:
                    pass
        return result

    def get_dataset_list_url(
        self, search_filters: models.GeonodeApiSearchFilters
    ) -> QtCore.QUrl:
        url = QtCore.QUrl(self.dataset_list_url)
        query = self.build_search_query(search_filters)
        url.setQuery(query.query())
        return url

    def get_dataset_detail_url(self, dataset_id: int) -> QtCore.QUrl:
        return QtCore.QUrl(f"{self.dataset_list_url}{dataset_id}/")

    def handle_dataset_list(self, task_result: bool) -> None:
        deserialized_content = self._retrieve_response(
            task_result, 0, self.search_error_received
        )
        if deserialized_content is not None:
            brief_datasets = []
            for raw_brief_ds in deserialized_content.get(self._DATASET_NAME_PLURAL, []):
                try:
                    parsed_properties = self._get_common_model_properties(raw_brief_ds)
                    brief_dataset = models.BriefDataset(**parsed_properties)
                except ValueError as exc:
                    log(
                        f"Could not parse {raw_brief_ds!r} into a valid item: {str(exc)}",
                        debug=False,
                    )
                else:
                    brief_datasets.append(brief_dataset)
            pagination_info = models.GeonodePaginationInfo(
                total_records=deserialized_content.get("total") or 0,
                current_page=deserialized_content.get("page") or 1,
                page_size=deserialized_content.get("page_size") or 0,
            )
            self.dataset_list_received.emit(brief_datasets, pagination_info)

    def handle_dataset_detail(
        self,
        task_result: bool,
        get_style_too: bool = False,
        authenticated: bool = False,
    ) -> None:
        log("inside the API client's handle_dataset_detail")
        deserialized_resource = self._retrieve_response(
            task_result, 0, self.dataset_detail_error_received
        )
        if deserialized_resource is not None:
            try:
                dataset = self._parse_dataset_detail(
                    deserialized_resource[self._DATASET_NAME]
                )
            except KeyError as exc:
                log(
                    f"Could not parse server response into a dataset: {str(exc)}",
                    debug=False,
                )
            else:
                # check if the request is from a WFS to see if it will retrieve the style
                if get_style_too and authenticated:
                    is_vector = (
                        dataset.dataset_sub_type
                        == models.GeonodeResourceType.VECTOR_LAYER
                    )
                    should_load_vector_style = (
                        models.ApiClientCapability.LOAD_VECTOR_LAYER_STYLE
                        in self.capabilities
                    )
                    # Check if the layer is vector and if it has the permissions to read the style
                    if is_vector and should_load_vector_style:
                        self.get_dataset_style(
                            dataset, emit_dataset_detail_received=True
                        )
                else:
                    self.dataset_detail_received.emit(dataset)

    def handle_dataset_style(
        self,
        dataset: models.Dataset,
        task_result: bool,
        emit_dataset_detail_received: bool = False,
    ) -> None:
        response_contents = self._retrieve_response(
            task_result, 0, self.style_detail_error_received, deserialize_as_json=False
        )
        if response_contents is not None:
            sld_named_layer, error_message = geonode_styles.get_usable_sld(
                response_contents
            )
            if sld_named_layer is None:
                self.style_detail_error_received[str].emit(
                    f"Could not parse downloaded SLD: {error_message}"
                )
            dataset.default_style.sld = sld_named_layer
            if emit_dataset_detail_received:
                self.dataset_detail_received.emit(dataset)

    def _retrieve_response(
        self,
        task_result: bool,
        contents_index: int,
        error_signal,
        deserialize_as_json: typing.Optional[bool] = True,
    ) -> typing.Optional[typing.Union[typing.Dict, network.ParsedNetworkReply]]:
        """Internal method that takes care of boilerplate-ish response parsing."""
        result = None
        if task_result:
            response_content = self.network_fetcher_task.response_contents[
                contents_index
            ]
            if response_content.qt_error is None:
                result = response_content
                if deserialize_as_json:
                    deserialized = network.deserialize_json_response(
                        response_content.response_body
                    )
                    if deserialized is not None:
                        result = deserialized
                    else:
                        error_signal[str].emit(
                            "Could not parse response from remote GeoNode"
                        )
            else:
                error_signal[str, int, str].emit(
                    response_content.qt_error,
                    response_content.http_status_code,
                    response_content.http_status_reason,
                )
        else:
            error_signal[str].emit("Could not complete network request")
        return result

    def _get_sld_url(self, raw_style: typing.Dict) -> typing.Optional[str]:
        auth_manager = qgis.core.QgsApplication.authManager()
        auth_provider_name = auth_manager.configAuthMethodKey(self.auth_config).lower()
        sld_url = raw_style.get("sld_url")
        if auth_provider_name == "basic":
            try:
                sld_url = url_from_geoserver(self.base_url, sld_url)
                log(f"sld_url: {sld_url}")
            except AttributeError:
                pass
        return sld_url

    def _get_common_model_properties(self, raw_dataset: typing.Dict) -> typing.Dict:
        type_ = _get_resource_type(raw_dataset)
        raw_links = raw_dataset.get("links", [])
        service_urls = self._get_service_urls(raw_links, type_)
        raw_style = raw_dataset.get("default_style") or {}
        return {
            "pk": int(raw_dataset["pk"]),
            "uuid": uuid.UUID(raw_dataset["uuid"]),
            "name": raw_dataset.get("alternate", raw_dataset.get("name", "")),
            "title": raw_dataset.get("title", ""),
            "abstract": raw_dataset.get(
                "raw_abstract", raw_dataset.get("abstract", "")
            ),
            "thumbnail_url": raw_dataset["thumbnail_url"],
            "link": raw_dataset["link"],
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
                name=raw_style.get("name", ""), sld_url=self._get_sld_url(raw_style)
            ),
            "permissions": self.parse_permissions(raw_dataset.get("perms", [])),
        }

    @staticmethod
    def _parse_metadata_authors(
        metadata_author: typing.Union[typing.Dict, typing.List]
    ) -> str:
        if isinstance(metadata_author, dict):
            return metadata_author.get("username", "")
        elif isinstance(metadata_author, list):
            return ", ".join(
                [author.get("username", "") for author in metadata_author]
            ).strip()
        else:
            return None

    def _parse_dataset_detail(self, raw_dataset: typing.Dict) -> models.Dataset:
        properties = self._get_common_model_properties(raw_dataset)
        properties.update(
            language=raw_dataset.get("language"),
            license=(raw_dataset.get("license") or {}).get("identifier", ""),
            constraints=raw_dataset.get("raw_constraints_other", ""),
            owner=raw_dataset.get("owner", {}).get("username", ""),
            metadata_author=self._parse_metadata_authors(
                raw_dataset.get("metadata_author", [])
            ),
        )
        return models.Dataset(**properties)


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
    start = payload.get("temporal_extent_start") or None
    end = payload.get("temporal_extent_end") or None
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
    }.get(raw_dataset.get("subtype"), models.GeonodeResourceType.UNKNOWN)
    return result


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
