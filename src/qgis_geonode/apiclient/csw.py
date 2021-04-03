import datetime as dt
import enum
import io
import json
import http.cookiejar
import math
import typing
import urllib.request
import urllib.parse
import uuid
from contextlib import contextmanager
from functools import partial
from xml.etree import ElementTree as ET


import qgis.core
from qgis.PyQt import (
    QtCore,
    QtNetwork,
)

from . import models
from .base import (
    BaseGeonodeClient,
    GeonodeApiSearchParameters,
    NetworkFetcherTask,
    MyNetworkFetcherTask,
)
from ..utils import (
    log,
    parse_network_reply,
    ParsedNetworkReply,
)


@contextmanager
def custom_event_loop(signal, timeout: int = 10000, **kwargs):
    loop = QtCore.QEventLoop()
    signal.connect(loop.quit)
    yield
    QtCore.QTimer.singleShot(timeout, loop.quit)
    log(f"About to start custom event loop...")
    loop.exec_()
    log(f"First event loop ended, resuming...")


class GeonodeCswAuthenticatedNetworkFetcher(MyNetworkFetcherTask):
    TIMEOUT: int = 10000
    username: str
    password: str
    base_url: str
    _first_login_reply: typing.Optional[QtNetwork.QNetworkReply]
    _second_login_reply: typing.Optional[QtNetwork.QNetworkReply]
    _final_reply: typing.Optional[QtNetwork.QNetworkReply]

    first_login_parsed = QtCore.pyqtSignal()
    second_login_parsed = QtCore.pyqtSignal()

    def __init__(self, base_url: str, username: str, password: str, *args, **kwargs):
        """A class suitable for performing POST requests to GeoNode's CSW endpoint

        This is most suitable for perfoming CSW GetRecords operations. These need to
        be sent as HTTP POST requests. However, due to GeoNode having the CSW API
        protected by django's session-based authentication, before being able to
        perform a POST request we need to simulate a browser login. This is achieved
        by:

         1. Issuing a first GET request to the login url. This shall allow retrieving
         the necessary cookies and also the csrf token used by django

         2. Issuing a second POST request ot the login url. If successful, this shall
         complete the login process

         3. Finally perform the POST reequest to interact with the CSW API

        """

        super().__init__(*args, **kwargs)
        self.base_url = base_url
        self.username = username
        self.password = password
        self._first_login_reply = None
        self._second_login_reply = None
        self._final_reply = None

    @property
    def login_url(self) -> QtCore.QUrl:
        return QtCore.QUrl(f"{self.base_url}/account/login/")

    def run(self) -> bool:
        if self._run_first_loop():
            if self._run_second_loop():
                parsed_reply, reply_content = self._run_third_loop()
                # the reply object in self._final_reply is now finished
                self.parsed_reply = parsed_reply
                self.reply_content = reply_content
                self.request_finished.emit()
                result = self.parsed_reply.qt_error is None
            else:
                result = False
        else:
            result = False
        return result

    def _run_first_loop(self) -> bool:
        with custom_event_loop(self.first_login_parsed, self.TIMEOUT):
            self._first_login_reply = self.network_access_manager.get(
                QtNetwork.QNetworkRequest(self.login_url)
            )
        return self._first_login_reply.error() == QtNetwork.QNetworkReply.NoError

    def _run_second_loop(self) -> bool:
        csrf_token = self._get_csrf_token()
        log(f"csrf_token: {csrf_token}")
        if csrf_token is not None:
            form_data = QtCore.QUrlQuery()
            form_data.addQueryItem("login", self.username)
            form_data.addQueryItem("password", self.password)
            form_data.addQueryItem("csrfmiddlewaretoken", csrf_token)
            data_ = form_data.query().encode("utf-8")
            request = QtNetwork.QNetworkRequest(self.login_url)
            request.setRawHeader(b"Referer", self.login_url.toString().encode("utf-8"))
            # self.request.setHeader(
            #     QtNetwork.QNetworkRequest.ContentTypeHeader,
            #     "application/x-www-form-urlencoded",
            # )
            with custom_event_loop(self.second_login_parsed, self.TIMEOUT):
                self._second_login_reply = self.network_access_manager.post(
                    request, data_
                )
            result = self._second_login_reply.error() == QtNetwork.QNetworkReply.NoError
            # self._first_login_reply.deleteLater()
        else:
            log("Could not retrieve CSRF token")
            result = False
        return result

    def _run_third_loop(self) -> typing.Tuple[ParsedNetworkReply, QtCore.QByteArray]:
        """We are now logged in and can perform the final request"""
        with custom_event_loop(self.request_parsed, self.TIMEOUT):
            if self.request_payload is None:
                self._final_reply = self.network_access_manager.get(self.request)
            else:
                self._final_reply = self.network_access_manager.post(
                    self.request,
                    QtCore.QByteArray(self.request_payload.encode("utf-8")),
                )
        parsed_reply = parse_network_reply(self._final_reply)
        reply_content = self._final_reply.readAll()
        return parsed_reply, reply_content

    def _request_done(self, qgis_reply: qgis.core.QgsNetworkReplyContent):
        log(f"requested_url: {qgis_reply.request().url().toString()}")
        this_request_id = qgis_reply.requestId()
        self.parsed_reply = parse_network_reply(qgis_reply)
        log(f"http_status_code: {self.parsed_reply.http_status_code}")
        log(f"qt_error: {self.parsed_reply.qt_error}")

        prop_name = "requestId"
        if self._first_login_reply is not None:
            if self._first_login_reply.property(prop_name) == this_request_id:
                self.first_login_parsed.emit()
        if self._second_login_reply is not None:
            if self._second_login_reply.property(prop_name) == this_request_id:
                self.second_login_parsed.emit()
        if self._final_reply is not None:
            if self._final_reply.property(prop_name) == this_request_id:
                self.request_parsed.emit()
        else:
            raise RuntimeError("Could not match this reply with a previous one")

    def old_run(self):
        self._first_login_reply = self.network_access_manager.get(
            QtNetwork.QNetworkRequest(self.login_url)
        )
        event_loop = QtCore.QEventLoop()
        self.request_parsed.connect(event_loop.quit)
        QtCore.QTimer.singleShot(10000, event_loop.quit)
        log(f"About to start the custom event loop...")
        event_loop.exec_()
        log(f"Custom event loop ended, resuming...")
        self.request_finished.emit()
        return self.parsed_reply.qt_error is None

    def _old_request_done(self, qgis_reply: qgis.core.QgsNetworkReplyContent):
        """
        Find out if this is the last request or not and act accordingly.

        - If this is the last request
        - If this is not the last request but the next one will be, then we need to
          make sure to perform the original request provided by the client
        - If this is not the last and the next one is also not the last, then we need
          to perform a GET request with the next request to be performed

        """

        log(f"requested_url: {qgis_reply.request().url().toString()}")
        this_request_id = qgis_reply.requestId()
        self.parsed_reply = parse_network_reply(qgis_reply)
        log(f"http_status_code: {self.parsed_reply.http_status_code}")
        log(f"qt_error: {self.parsed_reply.qt_error}")

        log(f"first_login_reply is None: {self._first_login_reply is None}")
        log(f"second_login_reply is None: {self._second_login_reply is None}")
        log(f"final_reply is None: {self._final_reply is None}")
        handler = None
        reply = None
        prop_name = "requestId"
        if self._first_login_reply is not None:
            if self._first_login_reply.property(prop_name) == this_request_id:
                reply = self._first_login_reply
                handler = self._handle_first_login_reply
        if self._second_login_reply is not None:
            if self._second_login_reply.property(prop_name) == this_request_id:
                reply = self._second_login_reply
                handler = self._handle_second_login_reply
        if self._final_reply is not None:
            if self._final_reply.property(prop_name) == this_request_id:
                reply = self._final_reply
                handler = self._handle_final_reply
        if reply is not None:
            if reply.error() == QtNetwork.QNetworkReply.NoError:
                result = handler()
            else:
                # TODO: improve error handling here
                log(
                    f"login reply: {self.parsed_reply.qt_error} - "
                    f"{self.parsed_reply.http_status_code}"
                )
                raise RuntimeError("Some error happened")
        else:
            raise RuntimeError("Could not match this reply with a previous one")
        return result

    def _handle_first_login_reply(self):
        log("inside _handle_first_login_reply")
        csrf_token = self._get_csrf_token()
        log(f"csrf_token: {csrf_token}")
        if csrf_token is not None:
            form_data = QtCore.QUrlQuery()
            form_data.addQueryItem("login", self.username)
            form_data.addQueryItem("password", self.password)
            form_data.addQueryItem("csrfmiddlewaretoken", csrf_token)
            data_ = form_data.query().encode("utf-8")
            request = QtNetwork.QNetworkRequest(self.login_url)
            request.setRawHeader(b"Referer", self.login_url.toString().encode("utf-8"))
            # self.request.setHeader(
            #     QtNetwork.QNetworkRequest.ContentTypeHeader,
            #     "application/x-www-form-urlencoded",
            # )
            reply = self.network_access_manager.post(request, data_)
            self._second_login_reply = reply
            # self._first_login_reply.deleteLater()
            log("About to leave from _handle_first_login_reply...")
        else:
            raise RuntimeError("Could not retrieve CSRF token")

    def _get_csrf_token(self) -> typing.Optional[str]:
        jar = self.network_access_manager.cookieJar()
        for cookie in jar.cookiesForUrl(QtCore.QUrl(self.base_url)):
            if cookie.name() == "csrftoken":
                result = str(cookie.value(), encoding="utf-8")
                break
        else:
            result = None
            log("Unable to retrieve csrf_token from cookies")
        return result

    def _handle_second_login_reply(self):
        log("inside _handle_second_login_reply")
        if self.request_payload is None:
            reply = self.network_access_manager.get(self.request)
        else:
            reply = self.network_access_manager.post(
                self.request, QtCore.QByteArray(self.request_payload.encode("utf-8"))
            )
        self._final_reply = reply
        # self._second_login_reply.deleteLater()

    def _handle_final_reply(self):
        log("inside _handle_final_reply")
        self.reply_content = self._final_reply.readAll()
        # self._final_reply.deleteLater()
        self.request_parsed.emit()


class CswNetworkFetcherTask(NetworkFetcherTask):
    base_url: str
    username: typing.Optional[str]
    password: typing.Optional[str]

    def __init__(
        self,
        base_url: str,
        *args,
        username: typing.Optional[str] = None,
        password: typing.Optional[str] = None,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.base_url = base_url
        self.username = username
        self.password = password

    @property
    def login_url(self):
        return f"{self.base_url}/account/login/"

    def run(self):
        if self.username is not None:
            logged_in = self._login()
            log(f"logged_in: {logged_in}")
            if logged_in:
                self.setProgress(30)
                result = super().run()
            else:
                result = False
        else:
            result = super().run()
        return result

    def _login(self) -> bool:
        csrf_token = self._get_csrf_token(self.login_url)
        log(f"login_url: {self.login_url}")
        log(f"csrf_token: {csrf_token}")
        if csrf_token is not None:
            form_data = QtCore.QUrlQuery()
            form_data.addQueryItem("login", self.username)
            form_data.addQueryItem("password", self.password)
            form_data.addQueryItem("csrfmiddlewaretoken", csrf_token)
            data_ = form_data.query().encode("utf-8")
            log(f"data_: {data_}")

            url = QtCore.QUrl(self.login_url)
            # query = QtCore.QUrlQuery()
            # query.addQueryItem("next", "/")
            # url.setQuery(query)
            request = QtNetwork.QNetworkRequest(url)
            request.setRawHeader(b"Referer", self.login_url.encode("utf-8"))
            # self.request.setHeader(
            #     QtNetwork.QNetworkRequest.ContentTypeHeader,
            #     "application/x-www-form-urlencoded",
            # )
            network_access_manager = qgis.core.QgsNetworkAccessManager.instance()
            old_redirect_policy = network_access_manager.redirectPolicy()
            log(f"old redirect policy: {old_redirect_policy}")
            network_access_manager.setRedirectPolicy(
                QtNetwork.QNetworkRequest.SameOriginRedirectPolicy
            )
            log(f"new redirect policy: {network_access_manager.redirectPolicy()}")
            reply = network_access_manager.blockingPost(request, data_)
            parsed_reply = parse_network_reply(reply)
            log(
                f"login reply: {parsed_reply.qt_error} - "
                f"{parsed_reply.http_status_code} - {reply.content()}"
            )
            result = parsed_reply.qt_error is None
        else:
            result = False
        return result

    def _get_csrf_token(self, url: str) -> typing.Optional[str]:
        network_access_manager = qgis.core.QgsNetworkAccessManager.instance()
        request = QtNetwork.QNetworkRequest(QtCore.QUrl(url))
        reply = network_access_manager.blockingGet(request)
        result = None
        if reply.error() == QtNetwork.QNetworkReply.NoError:
            jar = network_access_manager.cookieJar()
            for cookie in jar.cookiesForUrl(QtCore.QUrl(self.base_url)):
                if cookie.name() == "csrftoken":
                    result = str(cookie.value(), encoding="utf-8")
                    break
            else:
                log("Unable to retrieve csrf_token from cookies")
        else:
            log("Unable to reach login_url")
        return result


class Csw202Namespace(enum.Enum):
    CSW = "http://www.opengis.net/cat/csw/2.0.2"
    DC = "http://purl.org/dc/elements/1.1/"
    DCT = "http://purl.org/dc/terms/"
    GCO = "http://www.isotc211.org/2005/gco"
    GMD = "http://www.isotc211.org/2005/gmd"
    GML = "http://www.opengis.net/gml"
    OWS = "http://www.opengis.net/ows"
    OGC = "http://www.opengis.net/ogc"
    APISO = "http://www.opengis.net/cat/csw/apiso/1.0"


class GeonodeCswClient(BaseGeonodeClient):
    """Asynchronous GeoNode API client for pre-v2 API"""

    SERVICE = "CSW"
    VERSION = "2.0.2"
    OUTPUT_SCHEMA = Csw202Namespace.GMD.value
    OUTPUT_FORMAT = "application/xml"
    TYPE_NAME = ET.QName(Csw202Namespace.GMD.value, "MD_Metadata")

    capabilities = [
        models.ApiClientCapability.FILTER_BY_NAME,
        models.ApiClientCapability.FILTER_BY_ABSTRACT,
        # models.ApiClientCapability.FILTER_BY_KEYWORD,
        # models.ApiClientCapability.FILTER_BY_TOPIC_CATEGORY,
        # models.ApiClientCapability.FILTER_BY_RESOURCE_TYPES,
        # models.ApiClientCapability.FILTER_BY_TEMPORAL_EXTENT,
        # models.ApiClientCapability.FILTER_BY_PUBLICATION_DATE,
        # models.ApiClientCapability.FILTER_BY_SPATIAL_EXTENT,
    ]
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
        self.username = username
        self.password = password
        self.python_cookie_jar = http.cookiejar.CookieJar()
        self.request_opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.python_cookie_jar)
        )

    @classmethod
    def from_connection_settings(cls, connection_settings: "ConnectionSettings"):
        return cls(
            username=connection_settings.api_version_settings.username,
            password=connection_settings.api_version_settings.password,
            base_url=connection_settings.base_url,
            auth_config=connection_settings.auth_config,
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
        self, search_params: models.GeonodeApiSearchParameters
    ) -> QtCore.QUrl:
        return QtCore.QUrl(self.catalogue_url)

    def get_layers_request_payload(
        self, search_params: models.GeonodeApiSearchParameters
    ) -> typing.Optional[str]:
        start_position = (
            search_params.page_size * search_params.page + 1
        ) - search_params.page_size
        for member in Csw202Namespace:
            ET.register_namespace(member.name.lower(), member.value)
        get_records_el = ET.Element(
            ET.QName(Csw202Namespace.CSW.value, "GetRecords"),
            attrib={
                "service": self.SERVICE,
                "version": self.VERSION,
                "resultType": "results",
                "startPosition": str(start_position),
                "maxRecords": str(search_params.page_size),
                "outputFormat": self.OUTPUT_FORMAT,
                "outputSchema": self.OUTPUT_SCHEMA,
            },
        )
        log(f"get_records_el: {ET.tostring(get_records_el, encoding='unicode')}")
        query_el = ET.SubElement(
            get_records_el,
            ET.QName(Csw202Namespace.CSW.value, "Query"),
            attrib={"typeNames": self.TYPE_NAME},
        )
        elementsetname_el = ET.SubElement(
            query_el, ET.QName(Csw202Namespace.CSW.value, "ElementSetName")
        )
        elementsetname_el.text = "full"
        _add_constraints(query_el, search_params)
        _add_ordering(query_el, "dc:title", search_params.reverse_ordering)
        tree = ET.ElementTree(get_records_el)
        buffer = io.StringIO()
        tree.write(buffer, xml_declaration=True, encoding="unicode")
        result = buffer.getvalue()
        # with open(
        #     "/home/ricardo/SCRATCH/test_request_payload.xml", "w", encoding="utf-8"
        # ) as fh:
        #     fh.write(result)
        buffer.close()
        log(f"result: {result}")
        return result

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
        search_params: typing.Optional[models.GeonodeApiSearchParameters] = None,
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

        # if self.username is not None:
        #     logged_in = self.blocking_login()
        #     if logged_in:
        #         session_cookie = QtNetwork.QNetworkCookie(
        #             name="sessionid".encode("utf-8"),
        #             value=self.python_cookie_jar._cookies[self.host]["/"][
        #                 "sessionid"
        #             ].value.encode("utf-8"),
        #         )
        #         session_cookie.setDomain(self.host)
        #         session_cookie.setPath("/")
        #         network_manager = qgis.core.QgsNetworkAccessManager.instance()
        #         qt_cookie_jar: QtNetwork.QNetworkCookieJar = network_manager.cookieJar()
        #         qt_cookie_jar.insertCookie(session_cookie)
        #     else:
        #         raise RuntimeError("Unable to login")
        # super().get_layers(search_params)
        url = self.get_layers_url_endpoint(search_params)
        params = (
            search_params if search_params is not None else GeonodeApiSearchParameters()
        )
        request_payload = self.get_layers_request_payload(params)
        log(f"URL: {url.toString()}")
        self.network_fetcher_task = CswNetworkFetcherTask(
            request=QtNetwork.QNetworkRequest(url),
            reply_handler=partial(self.handle_layer_list, params),
            request_payload=request_payload,
            authcfg=self.auth_config,
            base_url=self.base_url,
            username=self.username,
            password=self.password,
        )
        qgis.core.QgsApplication.taskManager().addTask(self.network_fetcher_task)

    def new_get_layers(
        self, search_params: typing.Optional[GeonodeApiSearchParameters] = None
    ):
        url = self.get_layers_url_endpoint(search_params)
        params = (
            search_params if search_params is not None else GeonodeApiSearchParameters()
        )
        request_payload = self.get_layers_request_payload(params)
        log(f"URL: {url.toString()}")
        request = QtNetwork.QNetworkRequest(url)
        if self.username is not None:
            self.network_fetcher_task = GeonodeCswAuthenticatedNetworkFetcher(
                self.base_url,
                self.username,
                self.password,
                request=request,
                request_payload=request_payload,
                authcfg=self.auth_config,
            )
        else:
            self.network_fetcher_task = MyNetworkFetcherTask(
                request, request_payload=request_payload, authcfg=self.auth_config
            )
        self.network_fetcher_task.request_finished.connect(
            partial(self.new_handle_layer_list, params)
        )
        qgis.core.QgsApplication.taskManager().addTask(self.network_fetcher_task)

    def deserialize_response_contents(self, contents: QtCore.QByteArray) -> ET.Element:
        decoded_contents: str = contents.data().decode()
        return ET.fromstring(decoded_contents)

    def handle_layer_list(
        self,
        original_search_params: GeonodeApiSearchParameters,
        raw_reply_contents: QtCore.QByteArray,
    ):
        deserialized = self.deserialize_response_contents(raw_reply_contents)
        layers = []
        search_results = deserialized.find(
            f"{{{Csw202Namespace.CSW.value}}}SearchResults"
        )
        if search_results is not None:
            total = int(search_results.attrib["numberOfRecordsMatched"])
            next_record = int(search_results.attrib["nextRecord"])
            if next_record == 0:  # reached the last page
                current_page = max(
                    int(math.ceil(total / original_search_params.page_size)), 1
                )
            else:
                current_page = max(
                    int((next_record - 1) / original_search_params.page_size), 1
                )
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
                total_records=total,
                current_page=current_page,
                page_size=original_search_params.page_size,
            )
            self.layer_list_received.emit(layers, pagination_info)
        else:
            self.layer_list_received.emit(
                layers,
                models.GeoNodePaginationInfo(
                    total_records=0,
                    current_page=1,
                    page_size=original_search_params.page_size,
                ),
            )

    def new_handle_layer_list(
        self,
        original_search_params: GeonodeApiSearchParameters,
    ):
        deserialized = self.deserialize_response_contents(
            self.network_fetcher_task.reply_content
        )
        layers = []
        search_results = deserialized.find(
            f"{{{Csw202Namespace.CSW.value}}}SearchResults"
        )
        if search_results is not None:
            total = int(search_results.attrib["numberOfRecordsMatched"])
            next_record = int(search_results.attrib["nextRecord"])
            if next_record == 0:  # reached the last page
                current_page = max(
                    int(math.ceil(total / original_search_params.page_size)), 1
                )
            else:
                current_page = max(
                    int((next_record - 1) / original_search_params.page_size), 1
                )
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
                total_records=total,
                current_page=current_page,
                page_size=original_search_params.page_size,
            )
            self.layer_list_received.emit(layers, pagination_info)
        else:
            self.layer_list_received.emit(
                layers,
                models.GeoNodePaginationInfo(
                    total_records=0,
                    current_page=1,
                    page_size=original_search_params.page_size,
                ),
            )

    def handle_layer_detail(self, raw_reply_contents: QtCore.QByteArray):
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

        deserialized = self.deserialize_response_contents(raw_reply_contents)
        record = deserialized.find(f"{{{Csw202Namespace.GMD.value}}}MD_Metadata")
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
                deserialized.find(f"{{{Csw202Namespace.GMD.value}}}MD_Metadata"),
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
            models.GeonodeService.OGC_WMS: _get_wms_uri(
                record, layer_name, crs, auth_config
            ),
            models.GeonodeService.OGC_WFS: _get_wfs_uri(
                record, layer_name, auth_config
            ),
        }
    elif resource_type == models.GeonodeResourceType.RASTER_LAYER:
        service_urls = {
            models.GeonodeService.OGC_WMS: _get_wms_uri(
                record, layer_name, crs, auth_config
            ),
            models.GeonodeService.OGC_WCS: _get_wcs_uri(
                record, layer_name, auth_config
            ),
        }
    elif resource_type == models.GeonodeResourceType.MAP:
        service_urls = {
            models.GeonodeService.OGC_WMS: _get_wms_uri(
                record, layer_name, crs, auth_config
            ),
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


def _get_crs(rs_identifier: ET.Element) -> qgis.core.QgsCoordinateReferenceSystem:
    code = rs_identifier.find(
        f"{{{Csw202Namespace.GMD.value}}}code/"
        f"{{{Csw202Namespace.GCO.value}}}CharacterString"
    ).text
    authority = rs_identifier.find(
        f"{{{Csw202Namespace.GMD.value}}}codeSpace/"
        f"{{{Csw202Namespace.GCO.value}}}CharacterString"
    ).text
    return qgis.core.QgsCoordinateReferenceSystem(f"{authority}:{code}")


def _get_spatial_extent(geographic_bounding_box: ET.Element) -> qgis.core.QgsRectangle:
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
    return qgis.core.QgsRectangle(min_x, min_y, max_x, max_y)


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
    crs: qgis.core.QgsCoordinateReferenceSystem,
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


def _add_constraints(
    parent: ET.Element,
    search_params: models.GeonodeApiSearchParameters,
):
    if search_params.layer_types is None:
        types = [
            models.GeonodeResourceType.VECTOR_LAYER,
            models.GeonodeResourceType.RASTER_LAYER,
            models.GeonodeResourceType.MAP,
        ]
    else:
        types = list(search_params.layer_types)
    filter_params = (
        search_params.title,
        search_params.abstract,
    )
    if any(filter_params):
        constraint_el = ET.SubElement(
            parent,
            ET.QName(Csw202Namespace.CSW.value, "Constraint"),
            attrib={"version": "1.1.0"},
        )
        filter_el = ET.SubElement(
            constraint_el, ET.QName(Csw202Namespace.OGC.value, "Filter")
        )
        multiple_conditions = len([i for i in filter_params if i]) > 1
        filter_root_el = filter_el
        if multiple_conditions:
            and_el = ET.SubElement(
                filter_el, ET.QName(Csw202Namespace.OGC.value, "And")
            )
            filter_root_el = and_el
        if search_params.title is not None:
            _add_property_is_like_element(
                filter_root_el, "dc:title", search_params.title
            )
        if search_params.abstract is not None:
            _add_property_is_like_element(
                filter_root_el, "dc:abstract", search_params.abstract
            )
        # if search_params.keyword is not None:
        #     pass
        # if search_params.topic_category is not None:
        #     pass
        # if types is not None:
        #     pass
        # if search_params.temporal_extent_start is not None:
        #     pass
        # if search_params.temporal_extent_end is not None:
        #     pass
        # if search_params.publication_date_start is not None:
        #     pass
        # if search_params.publication_date_end is not None:
        #     pass
        # if search_params.spatial_extent is not None:
        #     _add_bbox_operator(filter_root_el, search_params.spatial_extent)


def _add_ordering(parent: ET.Element, ordering_field: str, reverse: bool):
    sort_by_el = ET.SubElement(parent, ET.QName(Csw202Namespace.OGC.value, "SortBy"))
    sort_property_el = ET.SubElement(
        sort_by_el, ET.QName(Csw202Namespace.OGC.value, "SortProperty")
    )
    property_name_el = ET.SubElement(
        sort_property_el, ET.QName(Csw202Namespace.OGC.value, "PropertyName")
    )
    property_name_el.text = ordering_field
    sort_order_el = ET.SubElement(
        sort_property_el, ET.QName(Csw202Namespace.OGC.value, "SortOrder")
    )
    sort_order_el.text = "DESC" if reverse else "ASC"


def _add_property_is_like_element(parent: ET.Element, name: str, value: str):
    wildcard = "*"
    property_is_like_el = ET.SubElement(
        parent,
        ET.QName(Csw202Namespace.OGC.value, "PropertyIsLike"),
        attrib={
            "wildCard": wildcard,
            "escapeChar": "",
            "singleChar": "?",
            "matchCase": "false",
        },
    )
    property_name_el = ET.SubElement(
        property_is_like_el, ET.QName(Csw202Namespace.OGC.value, "PropertyName")
    )
    property_name_el.text = name
    literal_el = ET.SubElement(
        property_is_like_el, ET.QName(Csw202Namespace.OGC.value, "Literal")
    )
    literal_el.text = f"{wildcard}{value}{wildcard}"


def _add_bbox_operator(parent: ET.Element, spatial_extent: qgis.core.QgsRectangle):
    bbox_el = ET.SubElement(parent, ET.QName(Csw202Namespace.OGC.value, "BBOX"))
    property_name_el = ET.SubElement(
        bbox_el, ET.QName(Csw202Namespace.OGC.value, "PropertyName")
    )
    property_name_el.text = "apiso:BoundingBox"
    envelope_el = ET.SubElement(
        bbox_el, ET.QName(Csw202Namespace.GML.value, "Envelope")
    )
    lower_corner_el = ET.SubElement(
        envelope_el, ET.QName(Csw202Namespace.GML.value, "lowerCorner")
    )
    lower_corner_el.text = f"{spatial_extent.yMinimum()} {spatial_extent.xMinimum()}"
    upper_corner_el = ET.SubElement(
        envelope_el, ET.QName(Csw202Namespace.GML.value, "upperCorner")
    )
    upper_corner_el.text = f"{spatial_extent.yMaximum()} {spatial_extent.xMaximum()}"
