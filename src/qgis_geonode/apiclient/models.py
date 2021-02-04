import datetime as dt
import enum
import typing
from uuid import UUID

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsRectangle,
)


class GeonodeResourceType(enum.Enum):
    VECTOR_LAYER = "vector"
    RASTER_LAYER = "raster"
    MAP = "map"


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
    service_urls: typing.Dict[str, str]

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
        self.service_urls = {}


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
