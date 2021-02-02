import datetime as dt
import enum
import math
import typing
import uuid
from xml.etree import ElementTree as ET


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
from .base import BaseGeonodeClient


class Csw202Namespace(enum.Enum):
    CSW = "http://www.opengis.net/cat/csw/2.0.2"
    DC = "http://purl.org/dc/elements/1.1/"
    DCT = "http://purl.org/dc/terms/"
    GCO = "http://www.isotc211.org/2005/gco"
    GMD = "http://www.isotc211.org/2005/gmd"
    GML = "http://www.opengis.net/gml"
    OWS = "http://www.opengis.net/ows"


class GeonodeCswClient(BaseGeonodeClient):
    """Asynchronous GeoNode API client for pre-v2 API"""

    OUTPUT_SCHEMA = "http://www.isotc211.org/2005/gmd"
    TYPE_NAME = "gmd:MD_Metadata"

    @property
    def catalogue_url(self):
        return f"{self.base_url}/catalogue/csw"

    def get_layers_url_endpoint(
        self, page: typing.Optional[int] = 1, page_size: typing.Optional[int] = 10
    ) -> QUrl:
        url = QUrl(f"{self.catalogue_url}")
        query = QUrlQuery()
        query.addQueryItem("service", "CSW")
        query.addQueryItem("version", "2.0.2")
        query.addQueryItem("request", "GetRecords")
        query.addQueryItem("resulttype", "results")
        query.addQueryItem("startposition", str(page_size * page))
        query.addQueryItem("maxrecords", str(page_size))
        query.addQueryItem("typenames", self.TYPE_NAME)
        query.addQueryItem("outputschema", self.OUTPUT_SCHEMA)
        query.addQueryItem("elementsetname", "full")
        return url

    def get_layer_detail_url_endpoint(self, id_: int) -> QUrl:
        url = QUrl(f"{self.catalogue_url}")
        query = QUrlQuery()
        query.addQueryItem("service", "CSW")
        query.addQueryItem("version", "2.0.2")
        query.addQueryItem("request", "GetRecordById")
        query.addQueryItem("elementsetname", "full")
        query.addQueryItem("id", str(id_))
        return url

    def deserialize_response_contents(self, contents: QByteArray) -> ET.Element:
        decoded_contents: str = contents.data().decode()
        return ET.fromstring(decoded_contents)

    def handle_layer_list(self, payload: ET.Element):
        layers = []
        search_results = payload.find(f"{{{Csw202Namespace.CSW}}}SearchResults")
        # TODO: how does this work on the last page?
        total = int(search_results.attrib["numberOfRecordsMatched"])
        page_size = int(search_results.attrib["numberOfRecordsReturned"])
        next_record = int(search_results.attrib["nextRecord"])
        next_page = math.ceil(next_record / page_size)
        current_page = next_page - 1
        if search_results is not None:
            for item in search_results.findall(f"{{{Csw202Namespace.GMD}}}MD_Metadata"):
                layers.append(get_brief_geonode_resource(item, self.base_url))
        else:
            raise RuntimeError("Could not find search results")
        self.layer_list_received.emit(layers, total, current_page, page_size)


def get_brief_geonode_resource(
    record: ET.Element, geonode_base_url: str
) -> models.BriefGeonodeResource:
    return models.BriefGeonodeResource(
        pk=None,
        uuid=uuid.UUID(
            record.find(
                f"{{{Csw202Namespace.GMD}}}fileIdentifier/"
                f"{{{Csw202Namespace.GCO}}}CharacterString"
            ).text
        ),
        name=record.find(
            f"{{{Csw202Namespace.GMD}}}identificationInfo/"
            f"{{{Csw202Namespace.GMD}}}MD_DataIdentification/"
            f"{{{Csw202Namespace.GMD}}}citation/"
            f"{{{Csw202Namespace.GMD}}}CI_Citation/"
            f"{{{Csw202Namespace.GMD}}}name/"
            f"{{{Csw202Namespace.GCO}}}CharacterString/"
        ).text,
        resource_type=_get_resource_type(record),
        title=record.find(
            f"{{{Csw202Namespace.GMD}}}identificationInfo/"
            f"{{{Csw202Namespace.GMD}}}MD_DataIdentification/"
            f"{{{Csw202Namespace.GMD}}}citation/"
            f"{{{Csw202Namespace.GMD}}}CI_Citation/"
            f"{{{Csw202Namespace.GMD}}}title/"
            f"{{{Csw202Namespace.GCO}}}CharacterString"
        ).text,
        abstract=record.find(
            f"{{{Csw202Namespace.GMD}}}identificationInfo/"
            f"{{{Csw202Namespace.GMD}}}MD_DataIdentification/"
            f"{{{Csw202Namespace.GMD}}}abstract/"
            f"{{{Csw202Namespace.GCO}}}CharacterString"
        ).text,
        spatial_extent=_get_spatial_extent(
            record.find(
                f"{{{Csw202Namespace.GMD}}}identificationInfo/"
                f"{{{Csw202Namespace.GMD}}}MD_DataIdentification/"
                f"{{{Csw202Namespace.GMD}}}extent/"
                f"{{{Csw202Namespace.GMD}}}EX_Extent/"
                f"{{{Csw202Namespace.GMD}}}geographicElement/"
                f"{{{Csw202Namespace.GMD}}}EX_GeographicBoundingBox"
            )
        ),
        crs=QgsCoordinateReferenceSystem(
            record.find(
                f"{{{Csw202Namespace.GMD}}}referenceSystemInfo/"
                f"{{{Csw202Namespace.GMD}}}MD_ReferenceSystem/"
                f"{{{Csw202Namespace.GMD}}}referenceSystemIdentifier/"
                f"{{{Csw202Namespace.GMD}}}RS_Identifier/"
                f"{{{Csw202Namespace.GMD}}}code/"
                f"{{{Csw202Namespace.GCO}}}CharacterString"
            ).text
        ),
        thumbnail_url=record.find(
            f"{{{Csw202Namespace.GMD}}}identificationInfo/"
            f"{{{Csw202Namespace.GMD}}}MD_DataIdentification/"
            f"{{{Csw202Namespace.GMD}}}graphicOverview/"
            f"{{{Csw202Namespace.GMD}}}MD_BrowseGraphic/"
            f"{{{Csw202Namespace.GMD}}}fileName/"
            f"{{{Csw202Namespace.GCO}}}CharacterString"
        ).text,
        api_url=None,
        gui_url=record.find(
            f"{{{Csw202Namespace.GMD}}}distributionInfo/"
            f"{{{Csw202Namespace.GMD}}}MD_Distribution/"
            f"{{{Csw202Namespace.GMD}}}transferOptions/"
            f"{{{Csw202Namespace.GMD}}}MD_DigitalTransferOptions/"
            f"{{{Csw202Namespace.GMD}}}onLine/"
            f"{{{Csw202Namespace.GMD}}}CI_OnlineResource/"
            f"{{{Csw202Namespace.GMD}}}linkage/"
            f"{{{Csw202Namespace.GMD}}}URL"
        ).text,
        published_date=_get_published_date(record),
        temporal_extent=None,
        keywords=[],
        category=None,
    )


def _get_resource_type(
    record: ET.Element,
) -> typing.Optional[models.GeonodeResourceType]:
    content_info = record.find(f"{{{Csw202Namespace.GMD}}}contentInfo")
    is_raster = content_info.find(f"{{{Csw202Namespace.GMD}}}MD_CoverageDescription")
    is_vector = content_info.find(
        f"{{{Csw202Namespace.GMD}}}MD_FeatureCatalogueDescription"
    )
    if is_raster:
        result = models.GeonodeResourceType.RASTER_LAYER
    elif is_vector:
        result = models.GeonodeResourceType.VECTOR_LAYER
    else:
        result = None
    return result


def _get_spatial_extent(geographic_bounding_box: ET.Element) -> QgsRectangle:
    min_x = float(
        geographic_bounding_box.find(
            f"{{{Csw202Namespace.GMD}}}westBoundLongitude/"
            f"{{{Csw202Namespace.GCO}}}Decimal"
        ).text
    )
    min_y = float(
        geographic_bounding_box.find(
            f"{{{Csw202Namespace.GMD}}}southBoundLatitude/"
            f"{{{Csw202Namespace.GCO}}}Decimal"
        ).text
    )
    max_x = float(
        geographic_bounding_box.find(
            f"{{{Csw202Namespace.GMD}}}eastBoundLongitude/"
            f"{{{Csw202Namespace.GCO}}}Decimal"
        ).text
    )
    max_y = float(
        geographic_bounding_box.find(
            f"{{{Csw202Namespace.GMD}}}northBoundLatitude/"
            f"{{{Csw202Namespace.GCO}}}Decimal"
        ).text
    )
    return QgsRectangle(min_x, min_y, max_x, max_y)


def _get_temporal_extent(
    payload: typing.Dict,
) -> typing.Optional[typing.List[typing.Optional[dt.datetime]]]:
    pass


def _parse_datetime(raw_value: str) -> dt.datetime:
    format_ = "%Y-%m-%dT%H:%M:%SZ"
    try:
        result = dt.datetime.strptime(raw_value, format_)
    except ValueError:
        microsecond_format = "%Y-%m-%dT%H:%M:%S.%fZ"
        result = dt.datetime.strptime(raw_value, microsecond_format)
    return result


def _get_published_date(record: ET.Element) -> dt.datetime:
    raw_date = record.find(f"{{{Csw202Namespace.DC}}}date").text
    result = _parse_datetime(raw_date)
    return result
