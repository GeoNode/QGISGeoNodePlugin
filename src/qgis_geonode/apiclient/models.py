import dataclasses
import datetime as dt
import enum
import json
import math
import typing
from uuid import UUID

import qgis.core
from qgis.PyQt import (
    QtCore,
    QtXml,
)

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsRectangle,
)

from .. import styles as qgis_geonode_styles
from ..utils import log

DATASET_CUSTOM_PROPERTY_KEY = "plugins/qgis_geonode/dataset"
DATASET_CONNECTION_CUSTOM_PROPERTY_KEY = "plugins/qgis_geonode/dataset_connection"


class GeonodePermission(enum.Enum):
    VIEW_RESOURCEBASE = "view_resourcebase"
    DOWNLOAD_RESOURCEBASE = "download_resourcebase"
    CHANGE_RESOURCEBASE = "change_resourcebase"

    CHANGE_RESOURCEBASE_METADATA = "change_resourcebase_metadata"
    DELETE_RESOURCEBASE = "delete_resourcebase"
    CHANGE_RESOURCEBASE_PERMISSIONS = "change_resourcebase_permissions"
    PUBLISH_RESOURCEBASE = "publish_resourcebase"

    CHANGE_DATASET_DATA = "change_dataset_data"
    CHANGE_DATASET_STYLE = "change_dataset_style"


class ApiClientCapability(enum.Enum):
    # NOTE - Some capabilities are not made explicit here because their support
    # is mandatory far all API clients. For example, all clients must support
    # searching datasets, as otherwise there wouldn't be much point to their existence
    FILTER_BY_TITLE = enum.auto()
    FILTER_BY_ABSTRACT = enum.auto()
    FILTER_BY_KEYWORD = enum.auto()
    FILTER_BY_TOPIC_CATEGORY = enum.auto()
    FILTER_BY_RESOURCE_TYPES = enum.auto()
    FILTER_BY_TEMPORAL_EXTENT = enum.auto()
    FILTER_BY_PUBLICATION_DATE = enum.auto()
    FILTER_BY_SPATIAL_EXTENT = enum.auto()
    LOAD_LAYER_METADATA = enum.auto()
    MODIFY_LAYER_METADATA = enum.auto()
    LOAD_VECTOR_LAYER_STYLE = enum.auto()
    LOAD_RASTER_LAYER_STYLE = enum.auto()
    MODIFY_VECTOR_LAYER_STYLE = enum.auto()
    MODIFY_RASTER_LAYER_STYLE = enum.auto()
    LOAD_VECTOR_DATASET_VIA_WMS = enum.auto()
    LOAD_VECTOR_DATASET_VIA_WFS = enum.auto()
    LOAD_RASTER_DATASET_VIA_WMS = enum.auto()
    LOAD_RASTER_DATASET_VIA_WCS = enum.auto()
    UPLOAD_VECTOR_LAYER = enum.auto()
    UPLOAD_RASTER_LAYER = enum.auto()


# NOTE: for simplicity, this enum's variants are named directly after the GeoNode
# topic_category ids.
class IsoTopicCategory(enum.Enum):
    biota = "Biota"
    boundaries = "Boundaries"
    climatologyMeteorologyAtmosphere = "Climatology Meteorology Atmosphere"
    economy = "Economy"
    elevation = "Elevation"
    environment = "Environment"
    farming = "Farming"
    geoscientificInformation = "Geoscientific Information"
    health = "Health"
    imageryBaseMapsEarthCover = "Imagery Base Maps Earth Cover"
    inlandWaters = "Inland Waters"
    intelligenceMilitary = "Intelligence Military"
    location = "Location"
    oceans = "Oceans"
    planningCadastre = "Planning Cadastre"
    society = "Society"
    structure = "Structure"
    transportation = "Transportation"
    utilitiesCommunication = "Utilities Communication"


class GeonodeService(enum.Enum):
    OGC_WMS = "wms"
    OGC_WFS = "wfs"
    OGC_WCS = "wcs"
    FILE_DOWNLOAD = "file_download"


class GeonodeResourceType(enum.Enum):
    VECTOR_LAYER = "vector"
    RASTER_LAYER = "raster"
    UNKNOWN = "unknown"


@dataclasses.dataclass
class GeonodePaginationInfo:
    total_records: int
    current_page: int
    page_size: int

    @property
    def total_pages(self):
        try:
            result = math.ceil(self.total_records / self.page_size)
        except ZeroDivisionError:
            result = 1
        return result


@dataclasses.dataclass()
class BriefGeonodeStyle:
    name: str
    sld_url: str
    sld: typing.Optional[QtXml.QDomElement] = None


@dataclasses.dataclass()
class BriefDataset:
    pk: int
    uuid: UUID
    name: str
    dataset_sub_type: GeonodeResourceType
    title: str
    abstract: str
    published_date: typing.Optional[dt.datetime]
    spatial_extent: QgsRectangle
    temporal_extent: typing.Optional[typing.List[dt.datetime]]
    srid: QgsCoordinateReferenceSystem
    thumbnail_url: str
    link: str
    detail_url: str
    keywords: typing.List[str]
    category: typing.Optional[str]
    service_urls: typing.Dict[GeonodeService, str]
    default_style: BriefGeonodeStyle
    permissions: typing.List[GeonodePermission]


@dataclasses.dataclass()
class Dataset(BriefDataset):
    language: str
    license: str
    constraints: str
    owner: typing.Dict[str, str]
    metadata_author: typing.Dict[str, str]

    def to_json(self):
        if self.temporal_extent is not None:
            serialized_temporal_extent = []
            for temporal_extent_item in self.temporal_extent:
                temporal_extent_item: dt.datetime
                serialized_temporal_extent.append(temporal_extent_item.isoformat())
        else:
            serialized_temporal_extent = None
        if self.default_style.sld is not None:
            serialized_sld = qgis_geonode_styles.serialize_sld_named_layer(
                self.default_style.sld
            )
        else:
            serialized_sld = None
        return json.dumps(
            {
                "pk": self.pk,
                "uuid": str(self.uuid),
                "name": self.name,
                "dataset_sub_type": self.dataset_sub_type.value,
                "title": self.title,
                "abstract": self.abstract,
                "published_date": self.published_date.isoformat()
                if self.published_date
                else None,
                "spatial_extent": self.spatial_extent.asWktPolygon(),
                "temporal_extent": serialized_temporal_extent,
                "srid": self.srid.postgisSrid(),
                "thumbnail_url": self.thumbnail_url,
                "link": self.link,
                "detail_url": self.detail_url,
                "keywords": self.keywords,
                "category": self.category,
                "service_urls": {
                    service.value: value for service, value in self.service_urls.items()
                },
                "language": self.language,
                "license": self.license,
                "constraints": self.constraints,
                "owner": self.owner,
                "metadata_author": self.metadata_author,
                "default_style": {
                    "name": self.default_style.name,
                    "sld_url": self.default_style.sld_url,
                    "sld": serialized_sld,
                },
                "permissions": [perm.value for perm in self.permissions],
            }
        )

    @classmethod
    def from_json(cls, contents: str):
        parsed = json.loads(contents)
        raw_published = parsed["published_date"]
        raw_temporal_extent = parsed["temporal_extent"]
        if raw_temporal_extent is not None:
            temporal_extent = [
                dt.datetime.fromisoformat(i) for i in raw_temporal_extent
            ]
        else:
            temporal_extent = None
        service_urls = {}
        for service_type, url in parsed["service_urls"].items():
            type_ = GeonodeService(service_type)
            service_urls[type_] = url
        default_sld = parsed.get("default_style", {}).get("sld")
        if default_sld is not None:
            sld, sld_error_message = qgis_geonode_styles.deserialize_sld_named_layer(
                default_sld
            )
            if sld is None:
                log(f"Could not deserialize SLD style: {sld_error_message}")
        else:
            sld = None
        return cls(
            pk=parsed["pk"],
            uuid=UUID(parsed["uuid"]),
            name=parsed["name"],
            dataset_sub_type=GeonodeResourceType(parsed["dataset_sub_type"]),
            title=parsed["title"],
            abstract=parsed["abstract"],
            published_date=(
                dt.datetime.fromisoformat(raw_published)
                if raw_published is not None
                else None
            ),
            spatial_extent=qgis.core.QgsRectangle.fromWkt(parsed["spatial_extent"]),
            temporal_extent=temporal_extent,
            srid=qgis.core.QgsCoordinateReferenceSystem.fromEpsgId(parsed["srid"]),
            thumbnail_url=parsed["thumbnail_url"],
            link=parsed["link"],
            detail_url=parsed["detail_url"],
            keywords=parsed["keywords"],
            category=parsed["category"],
            service_urls=service_urls,
            language=parsed["language"],
            license=parsed["license"],
            constraints=parsed["constraints"],
            owner=parsed["owner"],
            metadata_author=parsed["metadata_author"],
            default_style=BriefGeonodeStyle(
                name=parsed.get("default_style", {}).get("name", ""),
                sld_url=parsed.get("default_style", {}).get("sld_url"),
                sld=sld,
            ),
            permissions=[
                GeonodePermission(perm) for perm in parsed.get("permissions", [])
            ],
        )

    # we need this property for GeoNode 5
    @property
    def metadata_link(self) -> typing.Optional[str]:
        if self.link and self.pk:
            # dataset.link: https://my-geonode.org/api/v2/datasets/123
            return self.link.replace(
                f"/datasets/{self.pk}", f"/metadata/instance/{self.pk}"
            )
        return None


@dataclasses.dataclass
class GeonodeApiSearchFilters:
    page: typing.Optional[int] = 1
    title: typing.Optional[str] = None
    abstract: typing.Optional[str] = None
    keyword: typing.Optional[str] = None
    topic_category: typing.Optional[IsoTopicCategory] = None
    layer_types: typing.Optional[typing.List[GeonodeResourceType]] = dataclasses.field(
        default_factory=list
    )
    ordering_field: typing.Optional[str] = None
    reverse_ordering: typing.Optional[bool] = False
    temporal_extent_start: typing.Optional[QtCore.QDateTime] = None
    temporal_extent_end: typing.Optional[QtCore.QDateTime] = None
    publication_date_start: typing.Optional[QtCore.QDateTime] = None
    publication_date_end: typing.Optional[QtCore.QDateTime] = None
    spatial_extent: typing.Optional[qgis.core.QgsRectangle] = None


def loading_style_supported(
    layer_type: qgis.core.QgsMapLayerType,
    capabilities: typing.List[ApiClientCapability],
) -> bool:
    result = False
    if layer_type == qgis.core.QgsMapLayerType.VectorLayer:
        if ApiClientCapability.LOAD_VECTOR_LAYER_STYLE in capabilities:
            result = True
    elif layer_type == qgis.core.QgsMapLayerType.RasterLayer:
        if ApiClientCapability.LOAD_RASTER_LAYER_STYLE in capabilities:
            result = True
    else:
        pass
    return result


def modifying_style_supported(
    layer_type: qgis.core.QgsMapLayerType,
    capabilities: typing.List[ApiClientCapability],
) -> bool:
    result = False
    if layer_type == qgis.core.QgsMapLayerType.VectorLayer:
        if ApiClientCapability.MODIFY_VECTOR_LAYER_STYLE in capabilities:
            result = True
    elif layer_type == qgis.core.QgsMapLayerType.RasterLayer:
        if ApiClientCapability.MODIFY_RASTER_LAYER_STYLE in capabilities:
            result = True
    else:
        pass
    return result
