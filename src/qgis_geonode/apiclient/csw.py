import datetime as dt
import enum
import math
import re
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
        self,
        page: typing.Optional[int] = 1,
        page_size: typing.Optional[int] = 10,
        title: typing.Optional[str] = None,
        abstract: typing.Optional[str] = None,
        keyword: typing.Optional[str] = None,
        topic_category: typing.Optional[str] = None,
        layer_type: typing.Optional[models.GeonodeResourceType] = None,
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
        if any((title, abstract, keyword, topic_category, layer_type)):
            query.addQueryItem("constraintlanguage", "CQL_TEXT")
            constraint_values = []
            if title is not None:
                constraint_values.append(f"dc:title like '{title}'")
            # FIXME: Add support for filtering with the other parameters
            query.addQueryItem("constraint", " AND ".join(constraint_values))
        url.setQuery(query.query())
        return url

    def get_layer_detail_from_brief_resource(
        self, brief_resource: models.BriefGeonodeResource
    ):
        self.get_layer_detail(brief_resource.uuid)

    def get_layer_detail_url_endpoint(self, id_: uuid.UUID) -> QUrl:
        url = QUrl(f"{self.catalogue_url}")
        query = QUrlQuery()
        query.addQueryItem("service", "CSW")
        query.addQueryItem("version", "2.0.2")
        query.addQueryItem("request", "GetRecordById")
        query.addQueryItem("outputschema", self.OUTPUT_SCHEMA)
        query.addQueryItem("elementsetname", "full")
        query.addQueryItem("id", str(id_))
        url.setQuery(query.query())
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
                f"{{{Csw202Namespace.GMD.value}}}MD_Metadata"
            )
            for item in items:
                layers.append(
                    get_brief_geonode_resource(item, self.base_url, self.auth_config)
                )
        else:
            raise RuntimeError("Could not find search results")
        self.layer_list_received.emit(layers, total, current_page, self.PAGE_SIZE)

    def handle_layer_detail(self, payload: ET.Element):
        layer = get_geonode_resource(
            payload.find(f"{{{Csw202Namespace.GMD.value}}}MD_Metadata"),
            self.base_url,
            self.auth_config,
        )
        self.layer_detail_received.emit(layer)


def get_brief_geonode_resource(
    record: ET.Element, geonode_base_url: str, auth_config: str
) -> models.BriefGeonodeResource:
    return models.BriefGeonodeResource(
        **_get_common_model_fields(record, geonode_base_url, auth_config)
    )


def get_geonode_resource(
    record: ET.Element, geonode_base_url: str, auth_config: str
) -> models.GeonodeResource:
    common_fields = _get_common_model_fields(record, geonode_base_url, auth_config)

    return models.GeonodeResource(
        language=record.find(
            f"{{{Csw202Namespace.GMD.value}}}identificationInfo/"
            f"{{{Csw202Namespace.GMD.value}}}MD_DataIdentification/"
            f"{{{Csw202Namespace.GMD.value}}}language/"
            f"{{{Csw202Namespace.GCO.value}}}CharacterString"
        ).text,
        license=_get_license(record),
        constraints="",  # FIXME: get constraints from record
        owner="",  # FIXME: extract owner
        metadata_author="",  # FIXME: extract metadata author
        **common_fields,
    )


def _get_common_model_fields(
    record: ET.Element, geonode_base_url: str, auth_config: str
) -> typing.Dict:
    try:
        topic_category = record.find(
            f"{{{Csw202Namespace.GMD.value}}}identificationInfo/"
            f"{{{Csw202Namespace.GMD.value}}}MD_DataIdentification/"
            f"{{{Csw202Namespace.GMD.value}}}topicCategory/"
            f"{{{Csw202Namespace.GMD.value}}}MD_TopicCategoryCode"
        ).text
    except AttributeError:
        topic_category = None
    crs = _get_crs(
        record.find(
            f"{{{Csw202Namespace.GMD.value}}}referenceSystemInfo/"
            f"{{{Csw202Namespace.GMD.value}}}MD_ReferenceSystem/"
            f"{{{Csw202Namespace.GMD.value}}}referenceSystemIdentifier/"
            f"{{{Csw202Namespace.GMD.value}}}RS_Identifier"
        )
    )
    layer_name = record.find(
        f"{{{Csw202Namespace.GMD.value}}}identificationInfo/"
        f"{{{Csw202Namespace.GMD.value}}}MD_DataIdentification/"
        f"{{{Csw202Namespace.GMD.value}}}citation/"
        f"{{{Csw202Namespace.GMD.value}}}CI_Citation/"
        f"{{{Csw202Namespace.GMD.value}}}name/"
        f"{{{Csw202Namespace.GCO.value}}}CharacterString"
    ).text
    resource_type = _get_resource_type(record)
    if resource_type == models.GeonodeResourceType.VECTOR_LAYER:
        service_urls = {
            "wms": _get_wms_uri(record, layer_name, crs, auth_config),
            "wfs": _get_wfs_uri(record, layer_name, auth_config),
        }
    elif resource_type == models.GeonodeResourceType.RASTER_LAYER:
        service_urls = {
            "wms": _get_wms_uri(record, layer_name, crs, auth_config),
            "wcs": _get_wcs_uri(record, layer_name, auth_config),
        }
    elif resource_type == models.GeonodeResourceType.MAP:
        service_urls = {
            "wms": _get_wms_uri(record, layer_name, crs, auth_config),
        }
    else:
        service_urls = None
    return {
        "uuid": uuid.UUID(
            record.find(
                f"{{{Csw202Namespace.GMD.value}}}fileIdentifier/"
                f"{{{Csw202Namespace.GCO.value}}}CharacterString"
            ).text
        ),
        "name": layer_name,
        "resource_type": resource_type,
        "title": record.find(
            f"{{{Csw202Namespace.GMD.value}}}identificationInfo/"
            f"{{{Csw202Namespace.GMD.value}}}MD_DataIdentification/"
            f"{{{Csw202Namespace.GMD.value}}}citation/"
            f"{{{Csw202Namespace.GMD.value}}}CI_Citation/"
            f"{{{Csw202Namespace.GMD.value}}}title/"
            f"{{{Csw202Namespace.GCO.value}}}CharacterString"
        ).text,
        "abstract": record.find(
            f"{{{Csw202Namespace.GMD.value}}}identificationInfo/"
            f"{{{Csw202Namespace.GMD.value}}}MD_DataIdentification/"
            f"{{{Csw202Namespace.GMD.value}}}abstract/"
            f"{{{Csw202Namespace.GCO.value}}}CharacterString"
        ).text,
        "spatial_extent": _get_spatial_extent(
            record.find(
                f"{{{Csw202Namespace.GMD.value}}}identificationInfo/"
                f"{{{Csw202Namespace.GMD.value}}}MD_DataIdentification/"
                f"{{{Csw202Namespace.GMD.value}}}extent/"
                f"{{{Csw202Namespace.GMD.value}}}EX_Extent/"
                f"{{{Csw202Namespace.GMD.value}}}geographicElement/"
                f"{{{Csw202Namespace.GMD.value}}}EX_GeographicBoundingBox"
            )
        ),
        "crs": crs,
        "thumbnail_url": record.find(
            f"{{{Csw202Namespace.GMD.value}}}identificationInfo/"
            f"{{{Csw202Namespace.GMD.value}}}MD_DataIdentification/"
            f"{{{Csw202Namespace.GMD.value}}}graphicOverview/"
            f"{{{Csw202Namespace.GMD.value}}}MD_BrowseGraphic/"
            f"{{{Csw202Namespace.GMD.value}}}fileName/"
            f"{{{Csw202Namespace.GCO.value}}}CharacterString"
        ).text,
        # FIXME: this XPATH is not unique
        "gui_url": record.find(
            f"{{{Csw202Namespace.GMD.value}}}distributionInfo/"
            f"{{{Csw202Namespace.GMD.value}}}MD_Distribution/"
            f"{{{Csw202Namespace.GMD.value}}}transferOptions/"
            f"{{{Csw202Namespace.GMD.value}}}MD_DigitalTransferOptions/"
            f"{{{Csw202Namespace.GMD.value}}}onLine/"
            f"{{{Csw202Namespace.GMD.value}}}CI_OnlineResource/"
            f"{{{Csw202Namespace.GMD.value}}}linkage/"
            f"{{{Csw202Namespace.GMD.value}}}URL"
        ).text,
        "published_date": _get_published_date(record),
        "temporal_extent": _get_temporal_extent(record),
        "keywords": _get_keywords(record),
        "category": topic_category,
        "service_urls": service_urls,
    }


def _get_resource_type(
    record: ET.Element,
) -> typing.Optional[models.GeonodeResourceType]:
    content_info = record.find(f"{{{Csw202Namespace.GMD.value}}}contentInfo")
    is_raster = content_info.find(
        f"{{{Csw202Namespace.GMD.value}}}MD_CoverageDescription"
    )
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
        f"{{{Csw202Namespace.GMD.value}}}MD_DataIdentification/"
        f"{{{Csw202Namespace.GMD.value}}}extent/"
        f"{{{Csw202Namespace.GMD.value}}}EX_Extent/"
        f"{{{Csw202Namespace.GMD.value}}}temporalElement/"
        f"{{{Csw202Namespace.GMD.value}}}EX_TemporalExtent/"
        f"{{{Csw202Namespace.GMD.value}}}extent/"
        f"{{{Csw202Namespace.GML.value}}}TimePeriod"
    )
    if time_period is not None:
        temporal_format = "%Y-%m-%dT%H:%M:%S%z"
        start = _parse_datetime(
            time_period.find(f"{{{Csw202Namespace.GML.value}}}beginPosition").text,
            format_=temporal_format,
        )
        end = _parse_datetime(
            time_period.find(f"{{{Csw202Namespace.GML.value}}}endPosition").text,
            format_=temporal_format,
        )
        result = [start, end]
    else:
        result = None
    return result


def _parse_datetime(raw_value: str, format_="%Y-%m-%dT%H:%M:%SZ") -> dt.datetime:
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
            keyword.find(f"{{{Csw202Namespace.GCO.value}}}CharacterString").text
        )
    return result


def _get_license(record: ET.Element) -> typing.Optional[str]:
    license_element = record.find(
        f"{{{Csw202Namespace.GMD.value}}}identificationInfo/"
        f"{{{Csw202Namespace.GMD.value}}}MD_DataIdentification/"
        f"{{{Csw202Namespace.GMD.value}}}resourceConstraints/"
        f"{{{Csw202Namespace.GMD.value}}}MD_LegalConstraints/"
        f"{{{Csw202Namespace.GMD.value}}}useConstraints/"
        f"{{{Csw202Namespace.GMD.value}}}MD_RestrictionCode[@codeListValue='license']/"
        f"../../"
        f"{{{Csw202Namespace.GMD.value}}}otherConstraints/"
        f"{{{Csw202Namespace.GCO.value}}}CharacterString"
    )
    return license_element.text if license_element is not None else None


def _get_online_elements(record: ET.Element) -> typing.List[ET.Element]:
    return record.findall(
        f"{{{Csw202Namespace.GMD.value}}}distributionInfo/"
        f"{{{Csw202Namespace.GMD.value}}}MD_Distribution/"
        f"{{{Csw202Namespace.GMD.value}}}transferOptions/"
        f"{{{Csw202Namespace.GMD.value}}}MD_DigitalTransferOptions/"
        f"{{{Csw202Namespace.GMD.value}}}onLine/"
        f"{{{Csw202Namespace.GMD.value}}}CI_OnlineResource"
    )


def _find_protocol_linkage(record: ET.Element, protocol: str) -> typing.Optional[str]:
    online_elements = record.findall(
        f"{{{Csw202Namespace.GMD.value}}}distributionInfo/"
        f"{{{Csw202Namespace.GMD.value}}}MD_Distribution/"
        f"{{{Csw202Namespace.GMD.value}}}transferOptions/"
        f"{{{Csw202Namespace.GMD.value}}}MD_DigitalTransferOptions/"
        f"{{{Csw202Namespace.GMD.value}}}onLine/"
        f"{{{Csw202Namespace.GMD.value}}}CI_OnlineResource"
    )
    for item in online_elements:
        reported_protocol = item.find(
            f"{{{Csw202Namespace.GMD.value}}}protocol/"
            f"{{{Csw202Namespace.GCO.value}}}CharacterString"
        ).text
        if reported_protocol.lower() == protocol.lower():
            linkage_url = item.find(
                f"{{{Csw202Namespace.GMD.value}}}linkage/"
                f"{{{Csw202Namespace.GMD.value}}}URL"
            ).text
            break
    else:
        linkage_url = None
    return linkage_url


def _get_wms_uri(
    record: ET.Element,
    layer_name: str,
    crs: QgsCoordinateReferenceSystem,
    auth_config: typing.Optional[str] = None,
    wms_format: typing.Optional[str] = "image/png",
) -> str:
    wms_base_url = _find_protocol_linkage(record, "ogc:wms")
    wms_uri = (
        f"crs=EPSG:{crs.postgisSrid()}&format={wms_format}&layers={layer_name}&"
        f"styles&url={wms_base_url}"
    )
    if auth_config is not None:
        wms_uri += f"&authkey={auth_config}"
    return wms_uri


def _get_wcs_uri(
    record: ET.Element,
    layer_name: str,
    auth_config: typing.Optional[str] = None,
) -> str:
    wcs_base_url = _find_protocol_linkage(record, "ogc:wcs")
    wcs_uri = f"identifier={layer_name}&url={wcs_base_url}"
    if auth_config is not None:
        wcs_uri += f"&authkey={auth_config}"
    return wcs_uri


def _get_wfs_uri(
    record: ET.Element,
    layer_name: str,
    auth_config: typing.Optional[str] = None,
) -> str:
    wfs_base_url = _find_protocol_linkage(record, "ogc:wfs")
    wfs_uri = (
        f"{wfs_base_url}?service=WFS&version=1.1.0&"
        f"request=GetFeature&typename={layer_name}"
    )
    if auth_config is not None:
        wfs_uri += f"&authkey={auth_config}"
    return wfs_uri
