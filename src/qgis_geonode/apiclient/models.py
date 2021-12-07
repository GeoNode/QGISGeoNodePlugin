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

from ..utils import IsoTopicCategory

UNSUPPORTED_REMOTE = "unsupported"
DATASET_CUSTOM_PROPERTY_KEY = "plugins/qgis_geonode/dataset"


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
    LOAD_LAYER_STYLE = enum.auto()
    MODIFY_LAYER_STYLE = enum.auto()
    LOAD_VECTOR_DATASET_VIA_WMS = enum.auto()
    LOAD_VECTOR_DATASET_VIA_WFS = enum.auto()
    LOAD_RASTER_DATASET_VIA_WMS = enum.auto()
    LOAD_RASTER_DATASET_VIA_WCS = enum.auto()


class GeonodeService(enum.Enum):
    OGC_WMS = "wms"
    OGC_WFS = "wfs"
    OGC_WCS = "wcs"
    FILE_DOWNLOAD = "file_download"


class GeonodeResourceType(enum.Enum):
    VECTOR_LAYER = "vector"
    RASTER_LAYER = "raster"


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


@dataclasses.dataclass()
class Dataset(BriefDataset):
    language: str
    license: str
    constraints: str
    owner: typing.Dict[str, str]
    metadata_author: typing.Dict[str, str]
    styles: typing.List[BriefGeonodeStyle]
    default_style: typing.Optional[QtXml.QDomElement]

    def to_json(self):
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
                "temporal_extent": None,  # TODO
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
                # TODO: add styles
            }
        )

    # @classmethod
    # def from_json(cls, contents: str):
    #     parsed = json.loads(contents)
    #     return cls(
    #         pk=parsed["pk"],
    #         uuid=UUID(parsed["uuid"]),
    #         name=parsed["name"],
    #         dataset_sub_type=GeonodeResourceType(parsed["dataset_sub_type.value"]),
    #         title=parsed["title"],
    #         abstract=parsed["abstract"],
    #     )


@dataclasses.dataclass
class GeonodeApiSearchFilters:
    page: typing.Optional[int] = 1
    title: typing.Optional[str] = None
    abstract: typing.Optional[str] = None
    keyword: typing.Optional[typing.List[str]] = None
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
