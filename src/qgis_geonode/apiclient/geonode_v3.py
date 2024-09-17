"""API client classes for GeoNode versions 3.3.0 and up"""

import dataclasses
import datetime as dt
import json
import shutil
import tempfile
import typing
import uuid
from pathlib import Path

import qgis.core
import qgis.utils
from qgis.PyQt import (
    QtCore,
    QtNetwork,
)

from .. import network
from .. import styles as geonode_styles
from ..utils import (
    log,
)

from . import models
from .base import BaseGeonodeClient


@dataclasses.dataclass()
class ExportFormat:
    driver_name: str
    file_extension: str


class GeonodeApiClientVersion_3_x(BaseGeonodeClient):
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

    def handle_dataset_detail(self, task_result: bool) -> None:
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
                try:
                    style_response_contents = (
                        self.network_fetcher_task.response_contents[1]
                    )
                except IndexError:
                    pass
                else:
                    (
                        sld_named_layer,
                        error_message,
                    ) = geonode_styles.get_usable_sld(style_response_contents)
                    if sld_named_layer is None:
                        raise RuntimeError(error_message)
                    dataset.default_style.sld = sld_named_layer
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
                prefix, suffix = sld_url.partition("geoserver")[::2]
                sld_url = f"{self.base_url}/gs{suffix}"
                log(f"sld_url: {sld_url}")
            except AttributeError:
                pass
        return sld_url

    def _get_common_model_properties(self, raw_dataset: typing.Dict) -> typing.Dict:
        raise NotImplementedError

    def _parse_dataset_detail(self, raw_dataset: typing.Dict) -> models.Dataset:
        raise NotImplementedError


class GeonodeApiClientVersion_3_4_0(GeonodeApiClientVersion_3_x):

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

    def get_dataset_upload_url(self) -> QtCore.QUrl:
        return QtCore.QUrl(f"{self.api_url}/uploads/upload/")

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
        return LayerUploaderTask(
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
                deserialized = network.deserialize_json_response(
                    response_contents.response_body
                )
                catalogue_url = deserialized["url"]
                dataset_pk = catalogue_url.rsplit("/")[-1]
                self.dataset_uploaded.emit(int(dataset_pk))
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
                    prefix, suffix = retrieved_url.partition("geoserver")[::2]
                    result[service_type] = f"{self.base_url}/gs{suffix}"
                    log(f"result[service_type]: {self.base_url}/gs{suffix}")
                except AttributeError:
                    pass
        return result

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

    def _parse_dataset_detail(self, raw_dataset: typing.Dict) -> models.Dataset:
        properties = self._get_common_model_properties(raw_dataset)
        properties.update(
            language=raw_dataset.get("language"),
            license=(raw_dataset.get("license") or {}).get("identifier", ""),
            constraints=raw_dataset.get("raw_constraints_other", ""),
            owner=raw_dataset.get("owner", {}).get("username", ""),
            metadata_author=raw_dataset.get("metadata_author", {}).get("username", ""),
        )
        return models.Dataset(**properties)


class GeonodeApiClientVersion_4_2_0(GeonodeApiClientVersion_3_4_0):
    """API client for GeoNode version >= 4.2.x.

    GeoNode from version 4.2 uses list of contacts instead of a single contact,
    which neccassitates to parse contacts from a list.
    """
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


class GeonodeApiClientVersion_3_3_0(GeonodeApiClientVersion_3_x):
    """API client for GeoNode version 3.3.x.

    GeoNode version 3.3.0 still used `layers` instead of `datasets`. It also did not
    allow the upload of new datasets via API when using OAuth2 auth.

    """

    _DATASET_NAME = "layer"
    _DATASET_NAME_PLURAL = "layers"

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
        # upload of datasets via API using OAuth2 auth does not work, so the relevant
        # capabilities are not included
    ]

    def build_search_query(
        self, search_filters: models.GeonodeApiSearchFilters
    ) -> QtCore.QUrlQuery:
        # GeoNode v3.3.0 layers did not have the `subtype` property,
        # but rather a `dataStore` property
        query = super().build_search_query(search_filters)
        subtype_key = "filter{subtype.in}"
        datastore_key = "filter{storeType.in}"
        while query.hasQueryItem(subtype_key):
            old_value = query.queryItemValue(subtype_key)
            value = {
                "vector": "dataStore",
                "raster": "coverageStore",
            }[old_value]
            query.addQueryItem(datastore_key, value)
            query.removeQueryItem(subtype_key)
        return query

    def _get_service_urls(
        self,
        raw_dataset: typing.Dict,
        dataset_type: models.GeonodeResourceType,
    ) -> typing.Dict[models.GeonodeService, str]:
        result = {
            models.GeonodeService.OGC_WMS: raw_dataset["ows_url"],
        }
        if dataset_type == models.GeonodeResourceType.VECTOR_LAYER:
            result[models.GeonodeService.OGC_WFS] = raw_dataset["ows_url"]
        elif dataset_type == models.GeonodeResourceType.RASTER_LAYER:
            result[models.GeonodeService.OGC_WCS] = raw_dataset["ows_url"]
        else:
            log(f"Invalid dataset type: {dataset_type}")
            result = {}
        auth_manager = qgis.core.QgsApplication.authManager()
        auth_provider_name = auth_manager.configAuthMethodKey(self.auth_config).lower()
        if auth_provider_name == "basic":
            for service_type, retrieved_url in result.items():
                try:
                    prefix, suffix = retrieved_url.partition("geoserver")[::2]
                    result[service_type] = f"{self.base_url}/gs{suffix}"
                    log(f"result[service_type]: {self.base_url}/gs{suffix}")
                except AttributeError:
                    pass
        return result

    def _get_common_model_properties(self, raw_dataset: typing.Dict) -> typing.Dict:
        type_ = {
            "coverageStore": models.GeonodeResourceType.RASTER_LAYER,
            "dataStore": models.GeonodeResourceType.VECTOR_LAYER,
        }.get(raw_dataset.get("storeType"), models.GeonodeResourceType.UNKNOWN)
        service_urls = self._get_service_urls(raw_dataset, type_)
        raw_style = raw_dataset.get("default_style") or {}
        return {
            "pk": int(raw_dataset["pk"]),
            "uuid": uuid.UUID(raw_dataset["uuid"]),
            "name": raw_dataset.get("alternate", raw_dataset.get("name", "")),
            "title": raw_dataset.get("title", ""),
            "abstract": raw_dataset.get("raw_abstract", ""),
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

    def _parse_dataset_detail(self, raw_dataset: typing.Dict) -> models.Dataset:
        properties = self._get_common_model_properties(raw_dataset)
        properties.update(
            language=raw_dataset.get("language"),
            license=(raw_dataset.get("license") or {}).get("identifier", ""),
            constraints=raw_dataset.get("raw_constraints_other", ""),
            owner=raw_dataset.get("owner", {}).get("username", ""),
            metadata_author=raw_dataset.get("metadata_author", {}).get("username", ""),
        )
        return models.Dataset(**properties)


class LayerUploaderTask(network.NetworkRequestTask):
    VECTOR_UPLOAD_FORMAT = ExportFormat("ESRI Shapefile", "shp")
    RASTER_UPLOAD_FORMAT = ExportFormat("GTiff", "tif")

    layer: qgis.core.QgsMapLayer
    allow_public_access: bool
    _upload_url: QtCore.QUrl
    _temporary_directory: typing.Optional[Path]

    def __init__(
        self,
        layer: qgis.core.QgsMapLayer,
        upload_url: QtCore.QUrl,
        allow_public_access: bool,
        authcfg: str,
        network_task_timeout: int,
        description: str = "LayerUploaderTask",
    ):
        """Task to perform upload of QGIS layers to remote GeoNode servers."""
        super().__init__(
            requests_to_perform=[],
            authcfg=authcfg,
            description=description,
            network_task_timeout=network_task_timeout,
        )
        self.response_contents = [None]
        self.layer = layer
        self.allow_public_access = allow_public_access
        self._upload_url = upload_url
        self._temporary_directory = None

    def run(self) -> bool:
        if self._is_layer_uploadable():
            source_path = Path(
                self.layer.dataProvider().dataSourceUri().partition("|")[0]
            )
            export_error = None
        else:
            log(
                "Exporting layer to an uploadable format before proceeding with "
                "the upload..."
            )
            source_path, export_error = self._export_layer_to_temp_dir()
        log(f"source_path: {source_path}")
        if export_error is None:
            sld_path, sld_error = self._export_layer_style()
            log(f"sld_path: {sld_path}")
            if sld_path is None:
                log(
                    f"Could not export the layer's style as SLD "
                    f"({sld_error}), skipping..."
                )
            multipart = self._prepare_multipart(source_path, sld_path=sld_path)
            with network.wait_for_signal(
                self._all_requests_finished, timeout=self.network_task_timeout
            ) as event_loop_result:
                request = QtNetwork.QNetworkRequest(self._upload_url)
                request.setHeader(
                    QtNetwork.QNetworkRequest.ContentTypeHeader,
                    f"multipart/form-data; boundary={multipart.boundary().data().decode()}",
                )
                if self.authcfg:
                    auth_manager = qgis.core.QgsApplication.authManager()
                    auth_added, _ = auth_manager.updateNetworkRequest(
                        request, self.authcfg
                    )
                else:
                    auth_added = True
                if auth_added:
                    qt_reply = self._dispatch_request(
                        request, network.HttpMethod.POST, multipart
                    )
                    multipart.setParent(qt_reply)
                    request_id = qt_reply.property("requestId")
                    self._pending_replies[request_id] = (0, qt_reply)
                else:
                    self._all_requests_finished.emit()
            loop_forcibly_ended = not bool(event_loop_result.result)
            if loop_forcibly_ended:
                result = False
            else:
                result = self._num_finished >= len(self.requests_to_perform)
        else:
            result = False
        return result

    def finished(self, result: bool) -> None:
        if self._temporary_directory is not None:
            shutil.rmtree(self._temporary_directory, ignore_errors=True)
        super().finished(result)

    def _prepare_multipart(
        self, source_path: Path, sld_path: typing.Optional[Path] = None
    ) -> QtNetwork.QHttpMultiPart:
        main_file = QtCore.QFile(str(source_path))
        main_file.open(QtCore.QIODevice.ReadOnly)
        sidecar_files = []
        if sld_path is not None:
            sld_file = QtCore.QFile(str(sld_path))
            sld_file.open(QtCore.QIODevice.ReadOnly)
            sidecar_files.append(("sld_file", sld_file))
        if self.layer.type() == qgis.core.QgsMapLayerType.VectorLayer:
            dbf_file = QtCore.QFile(str(source_path.parent / f"{source_path.stem}.dbf"))
            dbf_file.open(QtCore.QIODevice.ReadOnly)
            sidecar_files.append(("dbf_file", dbf_file))
            prj_file = QtCore.QFile(str(source_path.parent / f"{source_path.stem}.prj"))
            prj_file.open(QtCore.QIODevice.ReadOnly)
            sidecar_files.append(("prj_file", prj_file))
            shx_file = QtCore.QFile(str(source_path.parent / f"{source_path.stem}.shx"))
            shx_file.open(QtCore.QIODevice.ReadOnly)
            sidecar_files.append(("shx_file", shx_file))
        elif self.layer.type() == qgis.core.QgsMapLayerType.RasterLayer:
            # when uploading tif files GeoNode seems to want the same file be uploaded
            # twice - one under the `base_file` form field and another under the
            # `tif_file` form field. This seems like a bug in GeoNode though
            tif_file = QtCore.QFile(str(source_path))
            tif_file.open(QtCore.QIODevice.ReadOnly)
            sidecar_files.append(("tif_file", tif_file))
        permissions = {
            "users": {},
            "groups": {},
        }
        if self.allow_public_access:
            permissions["users"]["AnonymousUser"] = [
                "view_resourcebase",
                "download_resourcebase",
            ]
        multipart = build_multipart(
            self.layer.metadata(), permissions, main_file, sidecar_files=sidecar_files
        )
        # below we set all QFiles as children of the multipart object and later we
        # also make the multipart object a children on the network reply object. This is
        # done in order to ensure deletion of resources at the correct time, as
        # recommended by the Qt documentation at:
        # https://doc.qt.io/qt-5/qhttppart.html#details
        main_file.setParent(multipart)
        for _, qt_file in sidecar_files:
            qt_file.setParent(multipart)
        return multipart

    def _is_layer_uploadable(self) -> bool:
        """Check if the layer is in a format suitable for uploading to GeoNode."""
        ds_uri = self.layer.dataProvider().dataSourceUri()
        fragment = ds_uri.split("|")[0]
        extension = fragment.rpartition(".")[-1]
        return extension in (
            self.VECTOR_UPLOAD_FORMAT.file_extension,
            self.RASTER_UPLOAD_FORMAT.file_extension,
        )

    def _export_layer_to_temp_dir(
        self,
    ) -> typing.Tuple[typing.Optional[Path], typing.Optional[str]]:
        if self._temporary_directory is None:
            self._temporary_directory = Path(tempfile.mkdtemp(prefix="qgis_geonode_"))
        if self.layer.type() == qgis.core.QgsMapLayerType.VectorLayer:
            exported_path, error_message = self._export_vector_layer()
        elif self.layer.type() == qgis.core.QgsMapLayerType.RasterLayer:
            exported_path, export_error = self._export_raster_layer()
            error_message = str(export_error)
        else:
            raise NotImplementedError()
        return exported_path, (error_message or None)

    def _export_vector_layer(
        self,
    ) -> typing.Tuple[typing.Optional[Path], str]:
        sanitized_layer_name = network.sanitize_layer_name(self.layer.name())
        target_path = self._temporary_directory / f"{sanitized_layer_name}.shp"
        export_code, error_message = qgis.core.QgsVectorLayerExporter.exportLayer(
            layer=self.layer,
            uri=str(target_path),
            providerKey="ogr",
            destCRS=qgis.core.QgsCoordinateReferenceSystem(),
            options={
                "driverName": "ESRI Shapefile",
            },
        )
        if export_code == qgis.core.Qgis.VectorExportResult.Success:
            result = (target_path, error_message)
        else:
            result = (None, error_message)
        return result

    def _export_raster_layer(
        self,
    ) -> typing.Tuple[typing.Optional[Path], typing.Optional[int]]:
        sanitized_layer_name = network.sanitize_layer_name(self.layer.name())
        target_path = (
            self._temporary_directory
            / f"{sanitized_layer_name}.{self.RASTER_UPLOAD_FORMAT.file_extension}"
        )
        writer = qgis.core.QgsRasterFileWriter(str(target_path))
        writer.setOutputFormat(self.RASTER_UPLOAD_FORMAT.driver_name)
        pipe = self.layer.pipe()
        raster_interface = self.layer.dataProvider()
        write_error = writer.writeRaster(
            pipe,
            raster_interface.xSize(),
            raster_interface.ySize(),
            raster_interface.extent(),
            raster_interface.crs(),
            qgis.core.QgsCoordinateTransformContext(),
        )
        if write_error == qgis.core.QgsRasterFileWriter.NoError:
            result = (target_path, None)
        else:
            result = (None, write_error)
        return result

    def _export_layer_style(self) -> typing.Tuple[typing.Optional[Path], str]:
        sanitized_layer_name = network.sanitize_layer_name(self.layer.name())
        if self._temporary_directory is None:
            self._temporary_directory = Path(tempfile.mkdtemp(prefix="qgis_geonode_"))
        target_path = self._temporary_directory / f"{sanitized_layer_name}.sld"
        saved_sld_details, sld_exported_flag = self.layer.saveSldStyle(str(target_path))
        if "created default style" in saved_sld_details.lower():
            result = (target_path, "")
        else:
            result = (None, saved_sld_details)
        return result


def build_multipart(
    layer_metadata: qgis.core.QgsLayerMetadata,
    permissions: typing.Dict,
    main_file: QtCore.QFile,
    sidecar_files: typing.List[typing.Tuple[str, QtCore.QFile]],
) -> QtNetwork.QHttpMultiPart:
    encoding = "utf-8"
    multipart = QtNetwork.QHttpMultiPart(QtNetwork.QHttpMultiPart.FormDataType)
    title = layer_metadata.title()
    if title:
        title_part = QtNetwork.QHttpPart()
        title_part.setHeader(
            QtNetwork.QNetworkRequest.ContentDispositionHeader,
            'form-data; name="dataset_title"',
        )
        title_part.setBody(layer_metadata.title().encode(encoding))
        multipart.append(title_part)
    abstract = layer_metadata.abstract()
    if abstract:
        abstract_part = QtNetwork.QHttpPart()
        abstract_part.setHeader(
            QtNetwork.QNetworkRequest.ContentDispositionHeader,
            'form-data; name="abstract"',
        )
        abstract_part.setBody(layer_metadata.abstract().encode(encoding))
        multipart.append(abstract_part)
    false_items = (
        "time",
        "mosaic",
        "metadata_uploaded_preserve",
        "metadata_upload_form",
        "style_upload_form",
    )
    for item in false_items:
        part = QtNetwork.QHttpPart()
        part.setHeader(
            QtNetwork.QNetworkRequest.ContentDispositionHeader,
            f'form-data; name="{item}"',
        )
        part.setBody("false".encode("utf-8"))
        multipart.append(part)
    permissions_part = QtNetwork.QHttpPart()
    permissions_part.setHeader(
        QtNetwork.QNetworkRequest.ContentDispositionHeader,
        'form-data; name="permissions"',
    )
    permissions_part.setBody(json.dumps(permissions).encode(encoding))
    multipart.append(permissions_part)
    file_parts = [("base_file", main_file)]
    for additional_file_form_name, additional_file_handler in sidecar_files:
        file_parts.append((additional_file_form_name, additional_file_handler))
    for form_element_name, file_handler in file_parts:
        file_name = file_handler.fileName().rpartition("/")[-1]
        part = QtNetwork.QHttpPart()
        part.setHeader(
            QtNetwork.QNetworkRequest.ContentDispositionHeader,
            f'form-data; name="{form_element_name}"; filename="{file_name}"',
        )
        if file_name.rpartition(".")[-1] == "tif":
            content_type = "image/tiff"
        else:
            content_type = "application/qgis"
        part.setHeader(QtNetwork.QNetworkRequest.ContentTypeHeader, content_type)
        part.setBodyDevice(file_handler)
        multipart.append(part)
    return multipart


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
