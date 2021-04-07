import dataclasses
import datetime as dt
import enum
import io
import json
import math
import typing
import urllib.request
import urllib.parse
import uuid
from functools import partial
from xml.etree import ElementTree as ET

import qgis.core
from qgis.PyQt import (
    QtCore,
    QtNetwork,
)

from . import models
from . import base
from .base import wait_for_signal
from ..utils import (
    log,
    parse_network_reply,
)


@dataclasses.dataclass()
class GeoNodeCswLayerDetail:
    parsed_csw_record: typing.Optional[ET.Element]
    parsed_layer_detail: typing.Optional[typing.Dict]
    brief_style: typing.Optional[models.BriefGeonodeStyle]


class GeoNodeLegacyAuthenticatedRecordSearcherTask(base.NetworkFetcherTask):
    TIMEOUT: int = 10000
    username: str
    password: str
    base_url: str
    _first_login_reply: typing.Optional[QtNetwork.QNetworkReply]
    _second_login_reply: typing.Optional[QtNetwork.QNetworkReply]
    _final_reply: typing.Optional[QtNetwork.QNetworkReply]
    _logout_reply: typing.Optional[QtNetwork.QNetworkReply]

    first_login_parsed = QtCore.pyqtSignal()
    second_login_parsed = QtCore.pyqtSignal()
    logout_parsed = QtCore.pyqtSignal()

    def __init__(self, base_url: str, username: str, password: str, *args, **kwargs):
        """Performs authenticated POST requests against a GeoNode's legacy CSW endpoint.

        This is mainly usable for perfoming CSW GetRecords operations. In order to
        support a broader range of search filters, GeoNode CSW GetRecords requests
        ought to be sent as HTTP POST requests (why? in brief, pycsw has better
        support for POST when doing GetRecords). However, due to GeoNode having the
        CSW API protected by django's session-based authentication, before being able to
        perform a POST request we need to simulate a browser login. This is achieved
        by:

         1. Issuing a first GET request to the login url. This shall allow retrieving
         the necessary cookies and also the csrf token used by django

         2. Issuing a second POST request ot the login url. If successful, this shall
         complete the login process

         3. Finally perform the POST reequest to interact with the CSW API

        """

        super().__init__(
            *args,
            redirect_policy=QtNetwork.QNetworkRequest.ManualRedirectPolicy,
            **kwargs,
        )
        self.base_url = base_url
        self.username = username
        self.password = password
        self._first_login_reply = None
        self._second_login_reply = None
        self._final_reply = None
        self._logout_reply = None

    @property
    def login_url(self) -> QtCore.QUrl:
        return QtCore.QUrl(f"{self.base_url}/account/login/")

    @property
    def logout_url(self) -> QtCore.QUrl:
        return QtCore.QUrl(f"{self.base_url}/account/logout/")

    def run(self) -> bool:
        if self._blocking_get_csrf_token():
            logged_in = self._blocking_login()
            log(f"logged_in: {logged_in}")
            if logged_in:
                if self._blocking_get_authenticated_reply():
                    self.parsed_reply = parse_network_reply(self._final_reply)
                    self.reply_content = self._final_reply.readAll()
                self._blocking_logout()
                # self.network_access_manager.finished.disconnect(self._request_done)
                # self.request_finished.emit()
                result = self.parsed_reply.qt_error is None
            else:
                result = False
        else:
            result = False
        return result

    def _request_done(self, qgis_reply: qgis.core.QgsNetworkReplyContent):
        log(f"requested_url: {qgis_reply.request().url().toString()}")
        self.parsed_reply = parse_network_reply(qgis_reply)
        log(f"http_status_code: {self.parsed_reply.http_status_code}")
        log(f"qt_error: {self.parsed_reply.qt_error}")
        found_matched_reply = False
        if self._first_login_reply is not None:
            if base.reply_matches(qgis_reply, self._first_login_reply):
                found_matched_reply = True
                self.first_login_parsed.emit()
        if self._second_login_reply is not None:
            if base.reply_matches(qgis_reply, self._second_login_reply):
                found_matched_reply = True
                self.second_login_parsed.emit()
        if self._final_reply is not None:
            if base.reply_matches(qgis_reply, self._final_reply):
                found_matched_reply = True
                self.request_parsed.emit()
        if self._logout_reply is not None:
            if base.reply_matches(qgis_reply, self._logout_reply):
                found_matched_reply = True
                self.logout_parsed.emit()
        if not found_matched_reply:
            log("Could not match this reply with a previous one, ignoring...")

    def _blocking_get_csrf_token(self) -> bool:
        """Perform a first request to login URL to get a csrf token

        Logging in to a django-baased website (such as GeoNode) requires obtaining
        a CSRF token first. This token needs to be sent together with the login
        credentials. This function performs a first visit to the login page and gets
        the CSRF token.

        """

        with base.wait_for_signal(self.first_login_parsed, self.TIMEOUT) as loop_result:
            self._first_login_reply = self.network_access_manager.get(
                QtNetwork.QNetworkRequest(self.login_url)
            )
        if loop_result.result:
            result = self._first_login_reply.error() == QtNetwork.QNetworkReply.NoError
        else:
            result = False
        return result

    def _blocking_login(self) -> bool:
        """Login to GeoNode using the previously gotten CSRF token

        In order to perform a session-based login to a django app (i.e. GeoNode) we need
        to:

        - Perform a first GET request to the login page in order to get some relevant
          cookies:

          - sessionid
          - csrftoken

        - Retrieve the CSRF TOKEN from the cookies, as it also needs to be sent as form
          data

        - Perform a second request to the login page, this time using POST method,
          sending:

          - the previously gotten cookies
          - form data with the username, password and csrftoken

        """

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
            with wait_for_signal(self.second_login_parsed, self.TIMEOUT) as loop_result:
                self._second_login_reply = self.network_access_manager.post(
                    request, data_
                )
            log(f"loop result: {loop_result.result}")
            if loop_result:
                result = (
                    self._second_login_reply.error() == QtNetwork.QNetworkReply.NoError
                )
            else:
                result = False
        else:
            log("Could not retrieve CSRF token")
            result = False
        return result

    def _get_csrf_token(self) -> typing.Optional[str]:
        """Retrieves CSRF token from the current cookie jar."""

        cookie_jar = self.network_access_manager.cookieJar()
        for cookie in cookie_jar.cookiesForUrl(QtCore.QUrl(self.base_url)):
            if cookie.name() == "csrftoken":
                result = str(cookie.value(), encoding="utf-8")
                break
        else:
            result = None
        return result

    def _blocking_get_authenticated_reply(
        self,
    ) -> bool:
        """We are now logged in and can perform the final request"""
        with base.wait_for_signal(self.request_parsed, self.TIMEOUT) as loop_result:
            if self.request_payload is None:
                self._final_reply = self.network_access_manager.get(self.request)
            else:
                self._final_reply = self.network_access_manager.post(
                    self.request,
                    QtCore.QByteArray(self.request_payload.encode("utf-8")),
                )
        if loop_result.result:
            result = self._final_reply.error() == QtNetwork.QNetworkReply.NoError
        else:
            result = False
        return result

    def _blocking_logout(self) -> bool:
        csrf_token = self._get_csrf_token()
        log(f"csrf_token: {csrf_token}")
        if csrf_token is not None:
            form_data = QtCore.QUrlQuery()
            form_data.addQueryItem("csrfmiddlewaretoken", csrf_token)
            data_ = form_data.query().encode("utf-8")
            request = QtNetwork.QNetworkRequest(self.logout_url)
            request.setRawHeader(b"Referer", self.logout_url.toString().encode("utf-8"))
            with base.wait_for_signal(self.logout_parsed, self.TIMEOUT) as loop_result:
                self._logout_reply = self.network_access_manager.post(request, data_)
            if loop_result.result:
                result = self._logout_reply.error() == QtNetwork.QNetworkReply.NoError
            else:
                result = False
        else:
            log("Could not retrieve CSRF token")
            result = False
        return result


class GeonodeLayerDetailFetcherMixin:
    TIMEOUT: int
    base_url: str
    authcfg: str
    network_access_manager: qgis.core.QgsNetworkAccessManager

    layer_detail_api_v1_parsed: QtCore.pyqtSignal
    layer_style_parsed: QtCore.pyqtSignal

    def _blocking_get_layer_detail_v1_api(
        self, layer_title: str
    ) -> typing.Optional[typing.Dict]:
        layer_detail_url = "?".join(
            (
                f"{self.base_url}/api/layers/",
                urllib.parse.urlencode({"title": layer_title}),
            )
        )
        request = QtNetwork.QNetworkRequest(QtCore.QUrl(layer_detail_url))
        auth_manager = qgis.core.QgsApplication.authManager()
        auth_manager.updateNetworkRequest(request, self.authcfg)
        with base.wait_for_signal(self.layer_detail_api_v1_parsed, self.TIMEOUT):
            self._layer_detail_api_v1_reply = self.network_access_manager.get(request)
        if self._layer_detail_api_v1_reply.error() == QtNetwork.QNetworkReply.NoError:
            raw_layer_detail = self._layer_detail_api_v1_reply.readAll()
            layer_detail_response = json.loads(raw_layer_detail.data().decode())
            try:
                result = layer_detail_response["objects"][0]
            except (KeyError, IndexError):
                raise IOError(f"Received unexpected API response for {layer_title!r}")
        else:
            result = None
        return result

    def _blocking_get_style_detail(self, style_uri: str) -> models.BriefGeonodeStyle:
        request = QtNetwork.QNetworkRequest(QtCore.QUrl(f"{self.base_url}{style_uri}"))
        auth_manager = qgis.core.QgsApplication.authManager()
        auth_manager.updateNetworkRequest(request, self.authcfg)
        with base.wait_for_signal(self.layer_style_parsed, self.TIMEOUT):
            self._layer_style_reply = self.network_access_manager.get(request)
        if self._layer_style_reply.error() == QtNetwork.QNetworkReply.NoError:
            raw_style_detail = self._layer_style_reply.readAll()
            style_detail = json.loads(raw_style_detail.data().decode())
            sld_path = urllib.parse.urlparse(style_detail["sld_url"]).path
            result = models.BriefGeonodeStyle(
                name=style_detail["name"],
                sld_url=f"{self.base_url}{sld_path}",
            )
        else:
            parsed_reply = parse_network_reply(self._layer_style_reply)
            msg = (
                f"Received an error retrieving style detail: {parsed_reply.qt_error} - "
                f"{parsed_reply.http_status_code} - {parsed_reply.http_status_reason} "
                f"- {self._layer_style_reply.readAll()}"
            )
            raise RuntimeError(msg)
        return result


class GeoNodeLegacyLayerDetailFetcher(
    GeonodeLayerDetailFetcherMixin, base.NetworkFetcherTask
):
    TIMEOUT: int = 10000
    base_url: str
    reply_content = GeoNodeCswLayerDetail
    _layer_detail_api_v1_reply: typing.Optional[QtNetwork.QNetworkReply]
    _layer_style_reply: typing.Optional[QtNetwork.QNetworkReply]

    layer_detail_api_v1_parsed = QtCore.pyqtSignal()
    layer_style_parsed = QtCore.pyqtSignal()

    def __init__(self, base_url: str, *args, **kwargs):
        """Fetch layer details from GeoNode using CSW API with anonymous access."""
        super().__init__(*args, **kwargs)
        self.base_url = base_url
        self.reply_content = GeoNodeCswLayerDetail(None, None, None)
        self._layer_detail_api_v1_reply = None
        self._layer_style_reply = None

    def run(self):
        record = self._blocking_get_reply()
        if record is not None:
            self.reply_content.parsed_csw_record = record
            layer_title = _extract_layer_title(record)
            layer_detail = self._blocking_get_layer_detail_v1_api(layer_title)
            if layer_detail is not None:
                self.reply_content.parsed_layer_detail = layer_detail
                style_uri = layer_detail["default_style"]
                try:
                    brief_style = self._blocking_get_style_detail(style_uri)
                    self.reply_content.brief_style = brief_style
                    result = brief_style is not None
                except RuntimeError as exc:
                    log(str(exc))
                    result = False
            else:
                result = False
        else:
            result = False
        return result

    def _request_done(self, qgis_reply: qgis.core.QgsNetworkReplyContent):
        self.parsed_reply = parse_network_reply(qgis_reply)
        log(f"requested_url: {qgis_reply.request().url().toString()}")
        log(f"http_status_code: {self.parsed_reply.http_status_code}")
        log(f"qt_error: {self.parsed_reply.qt_error}")
        found_matched_reply = False
        if self._final_reply is not None:
            if base.reply_matches(qgis_reply, self._final_reply):
                found_matched_reply = True
                self.request_parsed.emit()
        if self._layer_detail_api_v1_reply is not None:
            if base.reply_matches(qgis_reply, self._layer_detail_api_v1_reply):
                found_matched_reply = True
                self.layer_detail_api_v1_parsed.emit()
        if self._layer_style_reply is not None:
            if base.reply_matches(qgis_reply, self._layer_style_reply):
                found_matched_reply = True
                self.layer_style_parsed.emit()
        if not found_matched_reply:
            log("Could not match this reply with a previous one, ignoring...")

    def _blocking_get_reply(
        self,
    ) -> typing.Optional[ET.Element]:
        with base.wait_for_signal(self.request_parsed, self.TIMEOUT) as loop_result:
            if self.request_payload is None:
                self._final_reply = self.network_access_manager.get(self.request)
            else:
                self._final_reply = self.network_access_manager.post(
                    self.request,
                    QtCore.QByteArray(self.request_payload.encode("utf-8")),
                )
        if loop_result.result:
            decoded = self._final_reply.readAll().data().decode("utf-8")
            decoded_element = ET.fromstring(decoded)
            record = decoded_element.find(f"{{{Csw202Namespace.GMD.value}}}MD_Metadata")
        else:
            record = None
        return record


class GeoNodeLegacyAuthenticatedLayerDetailFetcherTask(
    GeonodeLayerDetailFetcherMixin, GeoNodeLegacyAuthenticatedRecordSearcherTask
):
    reply_content: GeoNodeCswLayerDetail

    _layer_detail_api_v1_reply: typing.Optional[QtNetwork.QNetworkReply]
    _layer_style_reply: typing.Optional[QtNetwork.QNetworkReply]

    layer_detail_api_v1_parsed = QtCore.pyqtSignal()
    layer_style_parsed = QtCore.pyqtSignal()

    def __init__(self, *args, **kwargs):
        """Fetch a layer's detail when using the GeoNode legacy API

        Using the GeoNode legacy API for fetching a layer's details involves making
        more than one network request, since we need to:

        - login
        - GetRecordById with the CSW API
        - /api/layer/id with the pre-v1 API
        - get the style detail
        - logout

        """
        super().__init__(*args, **kwargs)
        self.reply_content = GeoNodeCswLayerDetail(None, None, None)
        self._layer_detail_api_v1_reply = None
        self._layer_style_reply = None

    def run(self):
        if self._blocking_get_csrf_token():
            logged_in = self._blocking_login()
            log(f"logged_in: {logged_in}")
            if logged_in:
                record = self._blocking_get_authenticated_reply()
                if record is not None:
                    self.reply_content.parsed_csw_record = record
                    layer_title = _extract_layer_title(record)
                    layer_detail = self._blocking_get_layer_detail_v1_api(layer_title)
                    if layer_detail is not None:
                        self.reply_content.parsed_layer_detail = layer_detail
                        style_uri = layer_detail["default_style"]
                        try:
                            brief_style = self._blocking_get_style_detail(style_uri)
                            self.reply_content.brief_style = brief_style
                        except RuntimeError as exc:
                            log(str(exc))
                self._blocking_logout()
                # self.network_access_manager.finished.disconnect(self._request_done)
                # self.request_finished.emit()
                # self.parsed_reply = parse_network_reply(self._final_reply)
                result = self.parsed_reply.qt_error is None
            else:
                result = False
            # self._first_login_reply.deleteLater()
            # self._second_login_reply.deleteLater()
            # self._first_login_reply.deleteLater()
            # self._final_reply.deleteLater()
            # self._layer_detail_api_v1_reply.deleteLater()
            # self._layer_style_reply.deleteLater()
        else:
            result = False
        return result

    # def finished(self, result: bool):
    #     self.network_access_manager.finished.disconnect(self._request_done)
    #     self.parsed_reply = parse_network_reply(self._final_reply)
    #     if not result:
    #         self.api_client.error_received.emit(
    #             self.parsed_reply.qt_error,
    #             self.parsed_reply.http_status_code,
    #             self.parsed_reply.http_status_reason
    #         )
    #     self.request_finished.emit()

    def _request_done(self, qgis_reply: qgis.core.QgsNetworkReplyContent):
        """Handle finished network requests

        This slot is cannected to the network access manager and is used as a handler
        for all HTTP requests.

        The logic defined herein is something like:

        - test whether the request that has just finished is known to us
        - if it is, emit a signal that causes the relevant event loop to quit. This is
        part of the strategy that this class adopts, which is to block the current
        thread until a network request finishes

        """

        self.parsed_reply = parse_network_reply(qgis_reply)
        log(f"requested_url: {qgis_reply.request().url().toString()}")
        log(f"http_status_code: {self.parsed_reply.http_status_code}")
        log(f"qt_error: {self.parsed_reply.qt_error}")
        found_matched_reply = False
        if self._first_login_reply is not None:
            if base.reply_matches(qgis_reply, self._first_login_reply):
                found_matched_reply = True
                self.first_login_parsed.emit()
        if self._second_login_reply is not None:
            if base.reply_matches(qgis_reply, self._second_login_reply):
                found_matched_reply = True
                self.second_login_parsed.emit()
        if self._final_reply is not None:
            if base.reply_matches(qgis_reply, self._final_reply):
                found_matched_reply = True
                self.request_parsed.emit()
        if self._layer_detail_api_v1_reply is not None:
            if base.reply_matches(qgis_reply, self._layer_detail_api_v1_reply):
                found_matched_reply = True
                self.layer_detail_api_v1_parsed.emit()
        if self._layer_style_reply is not None:
            if base.reply_matches(qgis_reply, self._layer_style_reply):
                found_matched_reply = True
                self.layer_style_parsed.emit()
        if self._logout_reply is not None:
            if base.reply_matches(qgis_reply, self._logout_reply):
                found_matched_reply = True
                self.logout_parsed.emit()
        if not found_matched_reply:
            log("Could not match this reply with a previous one, ignoring...")

    def _blocking_get_authenticated_reply(
        self,
    ) -> typing.Optional[ET.Element]:
        result = super()._blocking_get_authenticated_reply()
        if result:
            decoded = self._final_reply.readAll().data().decode("utf-8")
            decoded_element = ET.fromstring(decoded)
            record = decoded_element.find(f"{{{Csw202Namespace.GMD.value}}}MD_Metadata")
        else:
            record = None
        return record

    # def _blocking_get_layer_detail_v1_api(
    #     self, layer_title: str
    # ) -> typing.Optional[typing.Dict]:
    #     layer_detail_url = "?".join(
    #         (
    #             f"{self.base_url}/api/layers/",
    #             urllib.parse.urlencode({"title": layer_title}),
    #         )
    #     )
    #     request = QtNetwork.QNetworkRequest(QtCore.QUrl(layer_detail_url))
    #     auth_manager = qgis.core.QgsApplication.authManager()
    #     auth_manager.updateNetworkRequest(request, self.authcfg)
    #     with base.wait_for_signal(self.layer_detail_api_v1_parsed, self.TIMEOUT):
    #         self._layer_detail_api_v1_reply = self.network_access_manager.get(request)
    #     if self._layer_detail_api_v1_reply.error() == QtNetwork.QNetworkReply.NoError:
    #         raw_layer_detail = self._layer_detail_api_v1_reply.readAll()
    #         layer_detail_response = json.loads(raw_layer_detail.data().decode())
    #         try:
    #             result = layer_detail_response["objects"][0]
    #         except (KeyError, IndexError):
    #             raise IOError(f"Received unexpected API response for {layer_title!r}")
    #     else:
    #         result = None
    #     return result

    # def _blocking_get_style_detail(self, style_uri: str) -> models.BriefGeonodeStyle:
    #     request = QtNetwork.QNetworkRequest(QtCore.QUrl(f"{self.base_url}{style_uri}"))
    #     auth_manager = qgis.core.QgsApplication.authManager()
    #     auth_manager.updateNetworkRequest(request, self.authcfg)
    #     with base.wait_for_signal(self.layer_style_parsed, self.TIMEOUT):
    #         self._layer_style_reply = self.network_access_manager.get(request)
    #     if self._layer_style_reply.error() == QtNetwork.QNetworkReply.NoError:
    #         raw_style_detail = self._layer_style_reply.readAll()
    #         style_detail = json.loads(raw_style_detail.data().decode())
    #         sld_path = urllib.parse.urlparse(style_detail["sld_url"]).path
    #         result = models.BriefGeonodeStyle(
    #             name=style_detail["name"],
    #             sld_url=f"{self.base_url}{sld_path}",
    #         )
    #     else:
    #         parsed_reply = parse_network_reply(self._layer_style_reply)
    #         msg = (
    #             f"Received an error retrieving style detail: {parsed_reply.qt_error} - "
    #             f"{parsed_reply.http_status_code} - {parsed_reply.http_status_reason} "
    #             f"- {self._layer_style_reply.readAll()}"
    #         )
    #         raise RuntimeError(msg)
    #     return result


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


class GeonodeCswClient(base.BaseGeonodeClient):
    """Asynchronous GeoNode API client for pre-v2 API"""

    SERVICE = "CSW"
    VERSION = "2.0.2"
    OUTPUT_SCHEMA = Csw202Namespace.GMD.value
    OUTPUT_FORMAT = "application/xml"
    TYPE_NAME = ET.QName(Csw202Namespace.GMD.value, "MD_Metadata")

    capabilities = [
        models.ApiClientCapability.FILTER_BY_NAME,
        models.ApiClientCapability.FILTER_BY_ABSTRACT,
        # models.ApiClientCapability.FILTER_BY_SPATIAL_EXTENT,
    ]
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

    def get_layers(
        self, search_params: typing.Optional[models.GeonodeApiSearchParameters] = None
    ):
        url = self.get_layers_url_endpoint(search_params)
        params = search_params or models.GeonodeApiSearchParameters()
        request_payload = self.get_layers_request_payload(params)
        log(f"URL: {url.toString()}")
        request = QtNetwork.QNetworkRequest(url)
        if self.username is not None:
            self.network_fetcher_task = GeoNodeLegacyAuthenticatedRecordSearcherTask(
                self.base_url,
                self.username,
                self.password,
                self,
                request=request,
                request_payload=request_payload,
                authcfg=self.auth_config,
            )
        else:
            self.network_fetcher_task = base.NetworkFetcherTask(
                self, request, request_payload=request_payload, authcfg=self.auth_config
            )
        self.network_fetcher_task.request_finished.connect(
            partial(self.handle_layer_list, params)
        )
        qgis.core.QgsApplication.taskManager().addTask(self.network_fetcher_task)

    def get_layer_detail(self, id_: typing.Union[int, uuid.UUID]):
        request = QtNetwork.QNetworkRequest(self.get_layer_detail_url_endpoint(id_))
        if self.username is not None:
            self.network_fetcher_task = (
                GeoNodeLegacyAuthenticatedLayerDetailFetcherTask(
                    self,
                    self.base_url,
                    self.username,
                    self.password,
                    request,
                    authcfg=self.auth_config,
                )
            )
        else:
            self.network_fetcher_task = GeoNodeLegacyLayerDetailFetcher(
                self.base_url, self, request
            )
        self.network_fetcher_task.request_finished.connect(
            partial(self.handle_layer_detail)
        )
        qgis.core.QgsApplication.taskManager().addTask(self.network_fetcher_task)

    def deserialize_response_contents(self, contents: QtCore.QByteArray) -> ET.Element:
        decoded_contents: str = contents.data().decode()
        return ET.fromstring(decoded_contents)

    def handle_layer_list(
        self,
        original_search_params: models.GeonodeApiSearchParameters,
    ):
        log(f"inside handle_layer_list")
        layers = []
        if self.network_fetcher_task.parsed_reply.qt_error is None:
            deserialized = self.deserialize_response_contents(
                self.network_fetcher_task.reply_content
            )
            search_results = deserialized.find(
                f"{{{Csw202Namespace.CSW.value}}}SearchResults"
            )
        else:
            search_results = None
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

    def handle_layer_detail(self):
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

        self.network_fetcher_task: typing.Union[
            GeoNodeLegacyLayerDetailFetcher,
            GeoNodeLegacyAuthenticatedLayerDetailFetcherTask,
        ]
        layer = get_geonode_resource(
            self.network_fetcher_task.reply_content.parsed_csw_record,
            self.base_url,
            self.auth_config,
            default_style=self.network_fetcher_task.reply_content.brief_style,
        )
        self.layer_detail_received.emit(layer)


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
    reported_thumbnail_url = record.find(
        f"{{{Csw202Namespace.GMD.value}}}identificationInfo/"
        f"{{{Csw202Namespace.GMD.value}}}MD_DataIdentification/"
        f"{{{Csw202Namespace.GMD.value}}}graphicOverview/"
        f"{{{Csw202Namespace.GMD.value}}}MD_BrowseGraphic/"
        f"{{{Csw202Namespace.GMD.value}}}fileName/"
        f"{{{Csw202Namespace.GCO.value}}}CharacterString"
    ).text
    if reported_thumbnail_url.startswith(geonode_base_url):
        thumbnail_url = reported_thumbnail_url
    else:
        # Sometimes GeoNode returns the full thumbnail URL, others it returns a
        # relative URI
        thumbnail_url = f"{geonode_base_url}{reported_thumbnail_url}"
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
        "thumbnail_url": thumbnail_url,
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
        # search_params.spatial_extent,
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


def _extract_layer_title(record: ET.Element):
    return record.find(
        f"{{{Csw202Namespace.GMD.value}}}identificationInfo/"
        f"{{{Csw202Namespace.GMD.value}}}MD_DataIdentification/"
        f"{{{Csw202Namespace.GMD.value}}}citation/"
        f"{{{Csw202Namespace.GMD.value}}}CI_Citation/"
        f"{{{Csw202Namespace.GMD.value}}}title/"
        f"{{{Csw202Namespace.GCO.value}}}CharacterString"
    ).text
