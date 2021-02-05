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
from ..utils import log


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
    # TODO: move this to the connection settings
    PAGE_SIZE: int = 10

    @property
    def catalogue_url(self):
        return f"{self.base_url}/catalogue/csw"

    def get_layers_url_endpoint(
            self, page: typing.Optional[int] = 1, page_size: typing.Optional[int] = 10,
            name_like: typing.Optional[str] = None

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
        if name_like is not None:
            query.addQueryItem("constraintlanguage", "CQL_TEXT")
            query.addQueryItem("constraint", f"dc:title like '{name_like}'")
        url.setQuery(query.query())
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
        log(f"decoded_contents: {decoded_contents}")
        return ET.fromstring(decoded_contents)

    def handle_layer_list(self, payload: ET.Element):
        layers = []
        search_results = payload.find(f"{{{Csw202Namespace.CSW.value}}}SearchResults")
        total = int(search_results.attrib["numberOfRecordsMatched"])
        next_record = int(search_results.attrib["nextRecord"])
        if next_record == 0:  # reached the last page
            current_page = int(math.ceil(total / self.PAGE_SIZE))
        else:
            current_page = int((next_record - 1) / self.PAGE_SIZE)
        if search_results is not None:
            items = search_results.findall(
                f"{{{Csw202Namespace.GMD.value}}}MD_Metadata")
            for item in items:
                layers.append(get_brief_geonode_resource(item, self.base_url))
        else:
            raise RuntimeError("Could not find search results")
        self.layer_list_received.emit(layers, total, current_page, self.PAGE_SIZE)

    def handle_layer_detail(self, payload: ET.Element):
        layer = get_geonode_resource(
            payload.find(f"{{{Csw202Namespace.GMD.value}}}MD_Metadata"), self.base_url)
        self.layer_detail_received.emit(layer)


def get_brief_geonode_resource(
    record: ET.Element, geonode_base_url: str
) -> models.BriefGeonodeResource:
    return _get_model_resource(
        record, geonode_base_url, model_class=models.BriefGeonodeResource)


def get_geonode_resource(
        record: ET.Element, geonode_base_url: str) -> models.GeonodeResource:
    return _get_model_resource(
        record, geonode_base_url, model_class=models.GeonodeResource)


def _get_model_resource(
        resource: ET.Element, geonode_base_url: str,
        model_class: typing.Type
) -> typing.Union[models.BriefGeonodeResource, models.GeonodeResource]:
    try:
        topic_category = resource.find(
            f"{{{Csw202Namespace.GMD.value}}}identificationInfo/"
            f"{{{Csw202Namespace.GMD.value}}}MD_DataIdentification/"
            f"{{{Csw202Namespace.GMD.value}}}topicCategory/"
            f"{{{Csw202Namespace.GMD.value}}}MD_TopicCategoryCode"
        ).text
    except AttributeError:
        topic_category = None
    return model_class(
        uuid=uuid.UUID(
            resource.find(
                f"{{{Csw202Namespace.GMD.value}}}fileIdentifier/"
                f"{{{Csw202Namespace.GCO.value}}}CharacterString"
            ).text
        ),
        name=resource.find(
            f"{{{Csw202Namespace.GMD.value}}}identificationInfo/"
            f"{{{Csw202Namespace.GMD.value}}}MD_DataIdentification/"
            f"{{{Csw202Namespace.GMD.value}}}citation/"
            f"{{{Csw202Namespace.GMD.value}}}CI_Citation/"
            f"{{{Csw202Namespace.GMD.value}}}name/"
            f"{{{Csw202Namespace.GCO.value}}}CharacterString"
        ).text,
        resource_type=_get_resource_type(resource),
        title=resource.find(
            f"{{{Csw202Namespace.GMD.value}}}identificationInfo/"
            f"{{{Csw202Namespace.GMD.value}}}MD_DataIdentification/"
            f"{{{Csw202Namespace.GMD.value}}}citation/"
            f"{{{Csw202Namespace.GMD.value}}}CI_Citation/"
            f"{{{Csw202Namespace.GMD.value}}}title/"
            f"{{{Csw202Namespace.GCO.value}}}CharacterString"
        ).text,
        abstract=resource.find(
            f"{{{Csw202Namespace.GMD.value}}}identificationInfo/"
            f"{{{Csw202Namespace.GMD.value}}}MD_DataIdentification/"
            f"{{{Csw202Namespace.GMD.value}}}abstract/"
            f"{{{Csw202Namespace.GCO.value}}}CharacterString"
        ).text,
        spatial_extent=_get_spatial_extent(
            resource.find(
                f"{{{Csw202Namespace.GMD.value}}}identificationInfo/"
                f"{{{Csw202Namespace.GMD.value}}}MD_DataIdentification/"
                f"{{{Csw202Namespace.GMD.value}}}extent/"
                f"{{{Csw202Namespace.GMD.value}}}EX_Extent/"
                f"{{{Csw202Namespace.GMD.value}}}geographicElement/"
                f"{{{Csw202Namespace.GMD.value}}}EX_GeographicBoundingBox"
            )
        ),
        crs=_get_crs(
            resource.find(
                f"{{{Csw202Namespace.GMD.value}}}referenceSystemInfo/"
                f"{{{Csw202Namespace.GMD.value}}}MD_ReferenceSystem/"
                f"{{{Csw202Namespace.GMD.value}}}referenceSystemIdentifier/"
                f"{{{Csw202Namespace.GMD.value}}}RS_Identifier"
            )
        ),
        thumbnail_url=resource.find(
            f"{{{Csw202Namespace.GMD.value}}}identificationInfo/"
            f"{{{Csw202Namespace.GMD.value}}}MD_DataIdentification/"
            f"{{{Csw202Namespace.GMD.value}}}graphicOverview/"
            f"{{{Csw202Namespace.GMD.value}}}MD_BrowseGraphic/"
            f"{{{Csw202Namespace.GMD.value}}}fileName/"
            f"{{{Csw202Namespace.GCO.value}}}CharacterString"
        ).text,
        gui_url=resource.find(
            f"{{{Csw202Namespace.GMD.value}}}distributionInfo/"
            f"{{{Csw202Namespace.GMD.value}}}MD_Distribution/"
            f"{{{Csw202Namespace.GMD.value}}}transferOptions/"
            f"{{{Csw202Namespace.GMD.value}}}MD_DigitalTransferOptions/"
            f"{{{Csw202Namespace.GMD.value}}}onLine/"
            f"{{{Csw202Namespace.GMD.value}}}CI_OnlineResource/"
            f"{{{Csw202Namespace.GMD.value}}}linkage/"
            f"{{{Csw202Namespace.GMD.value}}}URL"
        ).text,
        published_date=_get_published_date(resource),
        temporal_extent=_get_temporal_extent(resource),
        keywords=_get_keywords(resource),
        category=topic_category,
    )


def _get_resource_type(
    record: ET.Element,
) -> typing.Optional[models.GeonodeResourceType]:
    content_info = record.find(f"{{{Csw202Namespace.GMD.value}}}contentInfo")
    is_raster = content_info.find(f"{{{Csw202Namespace.GMD.value}}}MD_CoverageDescription")
    is_vector = content_info.find(
        f"{{{Csw202Namespace.GMD.value}}}MD_FeatureCatalogueDescription"
    )
    if is_raster:
        result = models.GeonodeResourceType.RASTER_LAYER
    elif is_vector:
        result = models.GeonodeResourceType.VECTOR_LAYER
    else:
        result = None
    return result


def _get_crs(rs_identifier: ET.Element) -> QgsCoordinateReferenceSystem:
    code = rs_identifier.find(
        f"{{{Csw202Namespace.GMD.value}}}code/"
        f"{{{Csw202Namespace.GCO.value}}}CharacterString"
    ).text
    authority = rs_identifier.find(
        f"{{{Csw202Namespace.GMD.value}}}codeSpace/"
        f"{{{Csw202Namespace.GCO.value}}}CharacterString"
    ).text
    return QgsCoordinateReferenceSystem(f"{authority}:{code}")


def _get_spatial_extent(geographic_bounding_box: ET.Element) -> QgsRectangle:
    # sometimes pycsw returns the extent fields with a comma as the decimal separator,
    # so we replace a comma with a dot
    min_x = float(
        geographic_bounding_box.find(
            f"{{{Csw202Namespace.GMD.value}}}westBoundLongitude/"
            f"{{{Csw202Namespace.GCO.value}}}Decimal"
        ).text.replace(",", ".")
    )
    min_y = float(
        geographic_bounding_box.find(
            f"{{{Csw202Namespace.GMD.value}}}southBoundLatitude/"
            f"{{{Csw202Namespace.GCO.value}}}Decimal"
        ).text.replace(",", ".")
    )
    max_x = float(
        geographic_bounding_box.find(
            f"{{{Csw202Namespace.GMD.value}}}eastBoundLongitude/"
            f"{{{Csw202Namespace.GCO.value}}}Decimal"
        ).text.replace(",", ".")
    )
    max_y = float(
        geographic_bounding_box.find(
            f"{{{Csw202Namespace.GMD.value}}}northBoundLatitude/"
            f"{{{Csw202Namespace.GCO.value}}}Decimal"
        ).text.replace(",", ".")
    )
    return QgsRectangle(min_x, min_y, max_x, max_y)


def _get_temporal_extent(
    payload: ET.Element,
) -> typing.Optional[typing.List[typing.Optional[dt.datetime]]]:
    time_period = payload.find(
        f"{{{Csw202Namespace.GMD.value}}}identificationInfo/"
        f"{{{Csw202Namespace.GMD.value}}}extent/"
        f"{{{Csw202Namespace.GMD.value}}}EX_Extent/"
        f"{{{Csw202Namespace.GMD.value}}}temporalElement/"
        f"{{{Csw202Namespace.GMD.value}}}EX_TemporalExtent/"
        f"{{{Csw202Namespace.GMD.value}}}extent/"
        f"{{{Csw202Namespace.GML.value}}}TimePeriod/"
    )
    if time_period is not None:
        start = _parse_datetime(
            time_period.find(f"{{{Csw202Namespace.GML.value}}}beginPosition").text)
        end = _parse_datetime(
            time_period.find(f"{{{Csw202Namespace.GML.value}}}endPosition").text)
        result = [start, end]
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


def _get_published_date(record: ET.Element) -> dt.datetime:
    raw_date = record.find(
        f"{{{Csw202Namespace.GMD.value}}}identificationInfo/"
        f"{{{Csw202Namespace.GMD.value}}}MD_DataIdentification/"
        f"{{{Csw202Namespace.GMD.value}}}citation/"
        f"{{{Csw202Namespace.GMD.value}}}CI_Citation/"
        f"{{{Csw202Namespace.GMD.value}}}date/"
        f"{{{Csw202Namespace.GMD.value}}}CI_Date/"
        f"{{{Csw202Namespace.GMD.value}}}date/"
        f"{{{Csw202Namespace.GCO.value}}}DateTime"
    ).text
    result = _parse_datetime(raw_date)
    return result


def _get_keywords(payload: ET.Element) -> typing.List[str]:
    keywords = payload.findall(f".//{{{Csw202Namespace.GMD.value}}}keyword")
    result = []
    for keyword in keywords:
        result.append(
            keyword.find(f"{{{Csw202Namespace.GCO.value}}}CharacterString").text)
    return result