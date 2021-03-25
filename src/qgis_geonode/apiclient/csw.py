import datetime as dt
import enum
import json
import http.cookiejar
import math
import typing
import urllib.request
import urllib.parse
import uuid
from xml.etree import ElementTree as ET


from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsDateTimeRange,
    QgsNetworkAccessManager,
    QgsRectangle,
    QgsSettings,
)
from qgis.PyQt import (
    QtCore,
    QtNetwork,
)

from . import models
from .base import BaseGeonodeClient
from .models import GeonodeService
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

    python_cookie_jar: http.cookiejar.CookieJar
    request_opener: urllib.request.OpenerDirector
    host: str
    username: typing.Optional[str]
    password: typing.Optional[str]

    def __init__(
        self,
        *args,
        username: typing.Optional[str] = None,
        password: typing.Optional[str] = None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.username = username or "ricardo"
        self.password = password or "0seTY7nr4CAu"
        self.python_cookie_jar = http.cookiejar.CookieJar()
        self.request_opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.python_cookie_jar)
        )

    @property
    def catalogue_url(self):
        return f"{self.base_url}/catalogue/csw"

    @property
    def host(self):
        return urllib.parse.urlparse(self.base_url).netloc

    @property
    def login_url(self):
        return f"{self.base_url}/account/login/"

    @property
    def csrf_token(self) -> str:
        try:
            result = self.python_cookie_jar._cookies[self.host]["/"]["csrftoken"].value
        except KeyError:
            result = None
        return result

    def get_ordering_filter_name(
        self,
        ordering_type: models.OrderingType,
        reverse_sort: typing.Optional[bool] = False,
    ) -> str:
        """Return name of the term that is sent to the CSW API when performing searches.

        The CSW specification (and also ISO AP) only define `Title` as a core queryable
        therefore, for the `name` case we search for title instead.

        """

        name = {
            models.OrderingType.NAME: "apiso:Title",
        }[ordering_type]
        return f"{name}:{'D' if reverse_sort else 'A'}"

    def get_search_result_identifier(
        self, resource: models.BriefGeonodeResource
    ) -> str:
        """Field that should be shown on the QGIS GUI as the layer identifier

        In order to be consistent with the search filter, we use the `title` property.

        """

        return resource.title

    def get_layers_url_endpoint(
        self,
        title: typing.Optional[str] = None,
        abstract: typing.Optional[str] = None,
        keyword: typing.Optional[str] = None,
        topic_category: typing.Optional[str] = None,
        layer_types: typing.Optional[typing.List[models.GeonodeResourceType]] = None,
        page: typing.Optional[int] = 1,
        page_size: typing.Optional[int] = 10,
        ordering_field: typing.Optional[models.OrderingType] = None,
        reverse_ordering: typing.Optional[bool] = False,
        temporal_extent_start: typing.Optional[QtCore.QDateTime] = None,
        temporal_extent_end: typing.Optional[QtCore.QDateTime] = None,
        publication_date_start: typing.Optional[QtCore.QDateTime] = None,
        publication_date_end: typing.Optional[QtCore.QDateTime] = None,
        spatial_extent: typing.Optional[QgsRectangle] = None,
    ) -> (QtCore.QUrl, QtCore.QByteArray):
        url = QtCore.QUrl(f"{self.catalogue_url}")
        data = self._build_search_query(
            page,
            page_size,
            title,
            abstract,
            keyword,
            topic_category,
            layer_types,
            ordering_field,
            reverse_ordering,
            temporal_extent_start,
            temporal_extent_end,
            publication_date_start,
            publication_date_end,
            spatial_extent,
        )
        return url, data

    def _build_search_query(
        self,
        page: int,
        page_size: int,
        title: typing.Optional[str] = None,
        abstract: typing.Optional[str] = None,
        keyword: typing.Optional[str] = None,
        topic_category: typing.Optional[str] = None,
        layer_types: typing.Optional[
            typing.Iterable[models.GeonodeResourceType]
        ] = None,
        ordering_field: typing.Optional[models.OrderingType] = None,
        reverse_ordering: typing.Optional[bool] = False,
        temporal_extent_start: typing.Optional[QtCore.QDateTime] = None,
        temporal_extent_end: typing.Optional[QtCore.QDateTime] = None,
        publication_date_start: typing.Optional[QtCore.QDateTime] = None,
        publication_date_end: typing.Optional[QtCore.QDateTime] = None,
        spatial_extent: typing.Optional[QgsRectangle] = None,
    ) -> QtCore.QByteArray:
        # FIXME: Add support for filtering with the other parameters
        if layer_types is None:
            types = [
                models.GeonodeResourceType.VECTOR_LAYER,
                models.GeonodeResourceType.RASTER_LAYER,
                models.GeonodeResourceType.MAP,
            ]
        else:
            types = list(layer_types)
        cql_filter_params = (
            title,
            abstract,
            keyword,
            topic_category,
            types,
            temporal_extent_start,
            temporal_extent_end,
            publication_date_start,
            publication_date_end,
            spatial_extent,
        )

        data = QtCore.QByteArray()

        record_tag = _get_record_tag(
            position=str((page_size * page + 1) - page_size),
            records=str(page_size),
            name=self.TYPE_NAME,
            schema=self.OUTPUT_SCHEMA,
        )

        record_tag = record_tag + '<csw:Constraint version="1.1.0">'

        if ordering_field is not None:
            sort_tag = _get_sort_tag("dc:title", reverse_ordering)
            record_tag = record_tag + sort_tag

        if any(cql_filter_params):
            if title is not None:
                record_tag = (
                    record_tag + f"<csw:CqlText>dc:title like '{title}'</csw:CqlText>"
                )
                pass
            if abstract is not None:
                pass
            if keyword is not None:
                pass
            if topic_category is not None:
                pass
            if types is not None:
                pass
            if temporal_extent_start is not None:
                pass
            if temporal_extent_end is not None:
                pass
            if publication_date_start is not None:
                pass
            if publication_date_end is not None:
                pass
            if spatial_extent is not None and not spatial_extent.isNull():
                spatial_filter = _get_spatial_extent_filter(spatial_extent)
                filter_tag = "<ogc:Filter>" + spatial_filter + "</ogc:Filter>"
                record_tag = record_tag + filter_tag

            record_tag = (
                record_tag + "</ csw:Constraint >" "</ csw:Query>" "</ csw:GetRecords>"
            )
            data.append(record_tag)
        return data

    def get_layer_detail_from_brief_resource(
        self, brief_resource: models.BriefGeonodeResource
    ):
        self.get_layer_detail(brief_resource.uuid)

    def get_layer_detail_url_endpoint(self, id_: uuid.UUID) -> QtCore.QUrl:
        url = QtCore.QUrl(f"{self.catalogue_url}")
        query = QtCore.QUrlQuery()
        query.addQueryItem("service", "CSW")
        query.addQueryItem("version", "2.0.2")
        query.addQueryItem("request", "GetRecordById")
        query.addQueryItem("outputschema", self.OUTPUT_SCHEMA)
        query.addQueryItem("elementsetname", "full")
        query.addQueryItem("id", str(id_))
        url.setQuery(query.query())
        return url

    def blocking_login(self) -> bool:
        csrf_token = self._get_csrf_token(self.login_url)
        if csrf_token is not None:
            form_data = {
                "login": self.username,
                "password": self.password,
                "csrfmiddlewaretoken": csrf_token,
            }
            login_request = urllib.request.Request(
                self.login_url,
                data=urllib.parse.urlencode(form_data).encode("ascii"),
                headers={"Referer": self.login_url},
                method="POST",
            )
            login_response = self.request_opener.open(login_request)
            result = login_response.status == 200
        else:
            result = False
        return result

    def _get_csrf_token(self, url: str):
        token_response = self.request_opener.open(url)
        if token_response.status == 200:
            result = self.python_cookie_jar._cookies[self.host]["/"]["csrftoken"].value
        else:
            result = None
        return result

    def get_layers(
        self,
        title: typing.Optional[str] = None,
        abstract: typing.Optional[str] = None,
        keyword: typing.Optional[str] = None,
        topic_category: typing.Optional[str] = None,
        layer_types: typing.Optional[typing.List[models.GeonodeResourceType]] = None,
        page: typing.Optional[int] = 1,
        page_size: typing.Optional[int] = 10,
        ordering_field: typing.Optional[models.OrderingType] = None,
        reverse_ordering: typing.Optional[bool] = False,
        temporal_extent_start: typing.Optional[QtCore.QDateTime] = None,
        temporal_extent_end: typing.Optional[QtCore.QDateTime] = None,
        publication_date_start: typing.Optional[QtCore.QDateTime] = None,
        publication_date_end: typing.Optional[QtCore.QDateTime] = None,
        spatial_extent: typing.Optional[QgsRectangle] = None,
    ):
        """Get layers from the CSW endpoint

        Unfortunately the GeoNode CSW endpoint does not use OAuth2 authentication,
        instead it relies on the same session-based authentication used by the main
        GeoNode GUI. Therefore we need to login, then retrieve a list of layers,
        and finally logout. To complicate things a bit more, the login process requires
        an additional GET request to retrieve the csrf token. Oh, and we need to
        provide the username and password for being able to login, which means we
        cannot use QGIS auth infrastructure.

        """

        if self.username is not None:
            logged_in = self.blocking_login()
            if logged_in:
                session_cookie = QtNetwork.QNetworkCookie(
                    name="sessionid".encode("utf-8"),
                    value=self.python_cookie_jar._cookies[self.host]["/"][
                        "sessionid"
                    ].value.encode("utf-8"),
                )
                session_cookie.setDomain(self.host)
                session_cookie.setPath("/")
                network_manager = QgsNetworkAccessManager.instance()
                qt_cookie_jar: QtNetwork.QNetworkCookieJar = network_manager.cookieJar()
                qt_cookie_jar.insertCookie(session_cookie)
            else:
                raise RuntimeError("Unable to login")
        super().get_layers(
            title,
            abstract,
            keyword,
            topic_category,
            layer_types,
            page,
            page_size,
            ordering_field,
            reverse_ordering,
            temporal_extent_start,
            temporal_extent_end,
            publication_date_start,
            publication_date_end,
            spatial_extent,
        )

    def deserialize_response_contents(self, contents: QtCore.QByteArray) -> ET.Element:
        decoded_contents: str = contents.data().decode()
        return ET.fromstring(decoded_contents)

    def handle_layer_list(self, payload: ET.Element):
        layers = []
        search_results = payload.find(f"{{{Csw202Namespace.CSW.value}}}SearchResults")
        if search_results is not None:
            total = int(search_results.attrib["numberOfRecordsMatched"])
            next_record = int(search_results.attrib["nextRecord"])
            if next_record == 0:  # reached the last page
                current_page = max(int(math.ceil(total / self.PAGE_SIZE)), 1)
            else:
                current_page = max(int((next_record - 1) / self.PAGE_SIZE), 1)
            items = search_results.findall(
                f"{{{Csw202Namespace.GMD.value}}}MD_Metadata"
            )
            for item in items:
                try:
                    brief_resource = get_brief_geonode_resource(
                        item, self.base_url, self.auth_config
                    )
                except (AttributeError, ValueError):
                    log(f"Could not parse {item!r} into a valid item")
                else:
                    layers.append(brief_resource)
            pagination_info = models.GeoNodePaginationInfo(
                total_records=total, current_page=current_page, page_size=self.PAGE_SIZE
            )
            self.layer_list_received.emit(layers, pagination_info)
        else:
            self.layer_list_received.emit(
                layers,
                models.GeoNodePaginationInfo(
                    total_records=0, current_page=1, page_size=self.PAGE_SIZE
                ),
            )

    def handle_layer_detail(self, payload: ET.Element):
        """Parse the input payload into a GeonodeResource instance

        This method performs additional blocking HTTP requests.

        A required property of ``GeonodeResource`` instances is their respective
        default style. Since the GeoNode CSW endpoint does not provide information on a
        layer's style, we need to make additional HTTP requests in order to get this
        from the API v1 endpoints.

        With this in mind, this method proceeds to:

        1. Make a GET request to API v1 to get the layer detail page
        2. Parse the layer detail, retrieve the style uri and build a full URL for it
        3. Make a GET request to API v1 to get the style detail page
        4. Parse the style detail, retrieve the style URL and name

        """

        record = payload.find(f"{{{Csw202Namespace.GMD.value}}}MD_Metadata")
        layer_title = record.find(
            f"{{{Csw202Namespace.GMD.value}}}identificationInfo/"
            f"{{{Csw202Namespace.GMD.value}}}MD_DataIdentification/"
            f"{{{Csw202Namespace.GMD.value}}}citation/"
            f"{{{Csw202Namespace.GMD.value}}}CI_Citation/"
            f"{{{Csw202Namespace.GMD.value}}}title/"
            f"{{{Csw202Namespace.GCO.value}}}CharacterString"
        ).text
        try:
            layer_detail = self.blocking_get_layer_detail(layer_title)
            brief_style = self.blocking_get_style_detail(layer_detail["default_style"])
        except IOError:
            raise
        else:
            layer = get_geonode_resource(
                payload.find(f"{{{Csw202Namespace.GMD.value}}}MD_Metadata"),
                self.base_url,
                self.auth_config,
                default_style=brief_style,
            )
            self.layer_detail_received.emit(layer)

    def blocking_get_layer_detail(self, layer_title: str) -> typing.Dict:
        if self.username is not None:
            self.blocking_login()
        layer_detail_url = "?".join(
            (
                f"{self.base_url}/api/layers/",
                urllib.parse.urlencode({"title": layer_title}),
            )
        )
        request = urllib.request.Request(
            layer_detail_url, headers={"Referer": self.base_url}, method="GET"
        )
        layer_detail_response = self.request_opener.open(request)
        if layer_detail_response.status != 200:
            raise IOError(f"Could not retrieve layer {layer_title!r} detail")
        payload = json.load(layer_detail_response)
        try:
            layer_detail = payload["objects"][0]
        except (KeyError, IndexError):
            raise IOError(
                f"Received unexpected API response for layer {layer_title!r} details: "
                f"url: {layer_detail_url} "
                f"payload: {payload} "
                f"cookies: {self.python_cookie_jar._cookies[self.host]['/']}"
            )
        else:
            return layer_detail

    def blocking_get_style_detail(self, style_uri: str) -> models.BriefGeonodeStyle:
        request = urllib.request.Request(
            f"{self.base_url}{style_uri}",
            headers={"Referer": self.base_url},
            method="GET",
        )
        style_detail_response = self.request_opener.open(request)
        if style_detail_response.status != 200:
            raise IOError(f"Could not retrieve style {style_uri!r} detail")
        style_detail = json.load(style_detail_response)
        return models.BriefGeonodeStyle(
            name=style_detail["name"],
            sld_url=(
                f"{self.base_url}{urllib.parse.urlparse(style_detail['sld_url']).path}"
            ),
        )


def get_brief_geonode_resource(
    record: ET.Element, geonode_base_url: str, auth_config: str
) -> models.BriefGeonodeResource:
    return models.BriefGeonodeResource(
        **_get_common_model_fields(record, geonode_base_url, auth_config)
    )


def get_geonode_resource(
    record: ET.Element,
    geonode_base_url: str,
    auth_config: str,
    default_style: models.BriefGeonodeStyle,
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
        default_style=default_style,
        styles=[],
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
    layer_name = (
        record.find(
            f"{{{Csw202Namespace.GMD.value}}}identificationInfo/"
            f"{{{Csw202Namespace.GMD.value}}}MD_DataIdentification/"
            f"{{{Csw202Namespace.GMD.value}}}citation/"
            f"{{{Csw202Namespace.GMD.value}}}CI_Citation/"
            f"{{{Csw202Namespace.GMD.value}}}name/"
            f"{{{Csw202Namespace.GCO.value}}}CharacterString"
        ).text
        or ""
    )

    resource_type = _get_resource_type(record)
    if resource_type == models.GeonodeResourceType.VECTOR_LAYER:
        service_urls = {
            GeonodeService.OGC_WMS: _get_wms_uri(record, layer_name, crs, auth_config),
            GeonodeService.OGC_WFS: _get_wfs_uri(record, layer_name, auth_config),
        }
    elif resource_type == models.GeonodeResourceType.RASTER_LAYER:
        service_urls = {
            GeonodeService.OGC_WMS: _get_wms_uri(record, layer_name, crs, auth_config),
            GeonodeService.OGC_WCS: _get_wcs_uri(record, layer_name, auth_config),
        }
    elif resource_type == models.GeonodeResourceType.MAP:
        service_urls = {
            GeonodeService.OGC_WMS: _get_wms_uri(record, layer_name, crs, auth_config),
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
        ).text
        or "",
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
    params = {
        "url": _find_protocol_linkage(record, "ogc:wms"),
        "format": wms_format,
        "layers": layer_name,
        "crs": f"EPSG:{crs.postgisSrid()}",
        "styles": "",
        "version": "auto",
    }
    if auth_config is not None:
        params["authcfg"] = auth_config
    return "&".join(f"{k}={v.replace('=', '%3D')}" for k, v in params.items())


def _get_wcs_uri(
    record: ET.Element,
    layer_name: str,
    auth_config: typing.Optional[str] = None,
) -> str:
    params = {
        "identifier": layer_name,
        "url": _find_protocol_linkage(record, "ogc:wcs"),
    }
    if auth_config is not None:
        params["authcfg"] = auth_config
    return "&".join(f"{k}={v.replace('=', '%3D')}" for k, v in params.items())


def _get_wfs_uri(
    record: ET.Element,
    layer_name: str,
    auth_config: typing.Optional[str] = None,
) -> str:
    params = {
        "url": _find_protocol_linkage(record, "ogc:wfs"),
        "typename": layer_name,
        "version": "auto",
    }
    if auth_config is not None:
        params["authcfg"] = auth_config
    return " ".join(f"{k}='{v}'" for k, v in params.items())


def _get_spatial_extent_filter(extent: QgsRectangle):
    spatial_filter = (
        "<ogc:BBOX>"
        "<ogc:PropertyName>ows:BoundingBox</ogc:PropertyName>"
        '<gml:Envelope srsName="urn:ogc:def:crs:OGC:1.3:CRS84">'
        f"<gml:lowerCorner>{extent.xMinimum()} {extent.yMinimum()}</gml:lowerCorner>"
        f"<gml:upperCorner>{extent.xMaximum()} {extent.yMaximum()}</gml:upperCorner>"
        "</gml:Envelope>"
        "</ogc:BBOX>"
    )

    return spatial_filter


def _get_record_tag(position: str, records: str, name: str, schema: str):
    return (
        '<?xml version="1.0" encoding="ISO-8859-1" standalone="no"?>'
        '<csw:GetRecords xmlns:csw="http://www.opengis.net/cat/csw/2.0.2"'
        ' xmlns:ogc="http://www.opengis.net/ogc" service="CSW" version="2.0.2" '
        'resultType="results" startPosition="{}" maxRecords="{}" outputFormat="application/json"'
        ' outputSchema="{}"'
        ' xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"'
        ' xsi:schemaLocation="http://www.opengis.net/cat/csw/2.0.2 '
        'http://schemas.opengis.net/csw/2.0.2/CSW-discovery.xsd" '
        'xmlns:gml="http://www.opengis.net/gml">'
        '<csw:Query typeNames="{}">'
        "<csw:ElementSetName>full</csw:ElementSetName>".format(
            position, records, schema, name
        )
    )


def _get_sort_tag(property: str, reverse):
    order = "DESC" if reverse else "ASC"
    return (
        "<ogc:SortBy >"
        "< ogc:SortProperty >"
        "< ogc:PropertyName > {} < / ogc:PropertyName >"
        "< ogc:SortOrder > {} < / ogc:SortOrder >"
        "< / ogc:SortProperty >"
        "< / ogc:SortBy >".format(property, order)
    )


def _get_all_record():

    return (
        '<?xml version="1.0" encoding="ISO-8859-1" standalone="no"?>'
        '<csw:GetRecords xmlns:csw="http://www.opengis.net/cat/csw/2.0.2" '
        'xmlns:ogc="http://www.opengis.net/ogc" service="CSW" version="2.0.2"'
        ' resultType="results" startPosition="1" maxRecords="5"'
        'outputFormat="application/json" outputSchema="http://www.opengis.net/cat/csw/2.0.2"'
        ' xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"'
        'xsi:schemaLocation="http://www.opengis.net/cat/csw/2.0.2 http://schemas.opengis.net/csw/2.0.2/CSW-discovery.xsd">'
        '<csw:Query typeNames="csw:Record" >'
        "<csw:ElementSetName > full < / csw:ElementSetName >"
        "< / csw:Query >"
        "< / csw:GetRecords >"
    )
