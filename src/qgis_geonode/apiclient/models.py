import dataclasses
import datetime as dt
import enum
import math
import typing
from uuid import UUID

import qgis.core
from qgis.PyQt import QtCore

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsRectangle,
)


class GeonodeService(enum.Enum):
    OGC_WMS = "wms"
    OGC_WFS = "wfs"
    OGC_WCS = "wcs"
    FILE_DOWNLOAD = "file_download"


class GeonodeResourceType(enum.Enum):
    VECTOR_LAYER = "vector"
    RASTER_LAYER = "raster"
    MAP = "map"


class OrderingType(enum.Enum):
    NAME = "name"


@dataclasses.dataclass
class GeoNodePaginationInfo:
    total_records: int
    current_page: int
    page_size: int

    @property
    def total_pages(self):
        return math.ceil(self.total_records / self.page_size)


class BriefGeonodeStyle:
    name: str
    sld_url: str

    def __init__(self, name: str, sld_url: str):
        self.name = name
        self.sld_url = sld_url


class BriefGeonodeResource:
    pk: typing.Optional[int]
    uuid: UUID
    name: str
    resource_type: GeonodeResourceType
    title: str
    abstract: str
    published_date: typing.Optional[dt.datetime]
    spatial_extent: QgsRectangle
    temporal_extent: typing.Optional[typing.List[dt.datetime]]
    crs: QgsCoordinateReferenceSystem
    thumbnail_url: str
    api_url: typing.Optional[str]
    gui_url: str
    keywords: typing.List[str]
    category: typing.Optional[str]
    service_urls: typing.Dict[GeonodeService, str]

    def __init__(
        self,
        uuid: UUID,
        name: str,
        resource_type: GeonodeResourceType,
        title: str,
        abstract: str,
        spatial_extent: QgsRectangle,
        crs: QgsCoordinateReferenceSystem,
        thumbnail_url: str,
        gui_url: str,
        pk: typing.Optional[int] = None,
        api_url: typing.Optional[str] = None,
        published_date: typing.Optional[dt.datetime] = None,
        temporal_extent: typing.Optional[typing.List[dt.datetime]] = None,
        keywords: typing.Optional[typing.List[str]] = None,
        category: typing.Optional[str] = None,
        service_urls: typing.Optional[typing.Dict[GeonodeService, str]] = None,
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
        self.service_urls = dict(service_urls) if service_urls is not None else {}


class GeonodeResource(BriefGeonodeResource):
    language: str
    license: str
    constraints: str
    owner: typing.Dict[str, str]
    metadata_author: typing.Dict[str, str]
    default_style: BriefGeonodeStyle
    styles: typing.List[BriefGeonodeStyle]

    def __init__(
        self,
        language: str,
        license: str,
        constraints: str,
        owner: typing.Dict[str, str],
        metadata_author: typing.Dict[str, str],
        default_style: BriefGeonodeStyle,
        styles: typing.List[BriefGeonodeStyle],
        *args,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.language = language
        self.license = license
        self.constraints = constraints
        self.owner = owner
        self.metadata_author = metadata_author
        self.default_style = default_style
        self.styles = styles


@dataclasses.dataclass
class GeonodeApiSearchParameters:
    page: typing.Optional[int] = 1
    page_size: typing.Optional[int] = 10
    title: typing.Optional[str] = None
    abstract: typing.Optional[str] = None
    keyword: typing.Optional[str] = None
    topic_category: typing.Optional[str] = None
    layer_types: typing.Optional[typing.List[GeonodeResourceType]] = None
    ordering_field: typing.Optional[OrderingType] = None
    reverse_ordering: typing.Optional[bool] = False
    temporal_extent_start: typing.Optional[QtCore.QDateTime] = None
    temporal_extent_end: typing.Optional[QtCore.QDateTime] = None
    publication_date_start: typing.Optional[QtCore.QDateTime] = None
    publication_date_end: typing.Optional[QtCore.QDateTime] = None
    spatial_extent: typing.Optional[qgis.core.QgsRectangle] = None
