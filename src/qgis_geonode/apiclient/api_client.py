import enum
import json
import typing
import os
from functools import partial

from qgis.core import (
    QgsApplication,
    QgsMessageLog,
    QgsNetworkAccessManager,
    QgsNetworkContentFetcherTask,
)
from qgis.PyQt.QtCore import (
    QByteArray,
    QObject,
    QUrl,
    QUrlQuery,
    pyqtSignal,
)
from qgis.PyQt.QtNetwork import (
    QNetworkReply,
    QNetworkRequest
)


class GeonodeApiEndpoint(enum.Enum):
    LAYER_LIST = "/api/v2/layers/"
    LAYER_DETAILS = "/api/v2/layers/"
    MAP_LIST = "/api/v2/maps/"


class GeonodeClient(QObject):
    """Asynchronous GeoNode API client"""
    auth_config: str
    base_url: str

    layer_list_received = pyqtSignal(dict)
    layer_details_received = pyqtSignal(dict)
    layer_styles_received = pyqtSignal(dict)
    map_list_received = pyqtSignal(dict)
    error_received = pyqtSignal(int)

    def __init__(
            self,
            base_url: str,
            *args,
            auth_config: typing.Optional[str] = None,
            **kwargs
    ):
        super().__init__(*args, **kwargs)
        self.auth_config = auth_config or ""
        self.base_url = base_url.rstrip("/")

    def get_layers(self, page: typing.Optional[int] = None):
        """Slot to retrieve list of layers available in GeoNode"""
        request = QNetworkRequest(
            QUrl(f"{self.base_url}{GeonodeApiEndpoint.LAYER_LIST.value}"))

        self.run_task(request, self.layer_list_received)

    def get_layer_details(self, id: int):
        """Slot to retrieve layer details available in GeoNode"""
        request = QNetworkRequest(
            QUrl(f"{self.base_url}{GeonodeApiEndpoint.LAYER_DETAILS.value}{id}/"))

        self.run_task(request, self.layer_details_received)

    def get_layer_styles(self, id: int):
        """Slot to retrieve layer styles available in GeoNode"""
        request = QNetworkRequest(
            QUrl(f"{self.base_url}{GeonodeApiEndpoint.LAYER_DETAILS.value}{id}/styles/"))

        signal_handler = self.layer_styles_received
        self.run_task(request, signal_handler)

    def get_maps(self, page: typing.Optional[int] = None):
        """Slot to retrieve list of maps available in GeoNode"""
        url = QUrl(f"{self.base_url}{GeonodeApiEndpoint.MAP_LIST.value}")
        if page:
            query = QUrlQuery()
            query.addQueryItem('page', str(page))
            url.setQuery(query.query())

        request = QNetworkRequest(url)

        self.run_task(request, self.map_list_received)

    def run_task(self, request, signal_to_emit):
        """Fetches the response from the GeoNode API"""
        task = QgsNetworkContentFetcherTask(request, authcfg=self.auth_config)
        response_handler = partial(self.response_fetched, task, signal_to_emit)
        task.fetched.connect(response_handler)
        task.run()

    def response_fetched(self, task: QgsNetworkContentFetcherTask, signal_to_emit: pyqtSignal):
        """Process GeoNode API response and emit the appropriate signal"""
        reply: QNetworkReply = task.reply()
        error = reply.error()
        if error == QNetworkReply.NoError:
            QgsMessageLog.logMessage("no error received", "qgis_geonode")
            contents: QByteArray = reply.readAll()
            QgsMessageLog.logMessage(f"contents: {contents}", "qgis_geonode")
            decoded_contents: str = contents.data().decode()
            QgsMessageLog.logMessage(f"decoded_contents: {decoded_contents}", "qgis_geonode")
            payload: typing.Dict = json.loads(decoded_contents)
            QgsMessageLog.logMessage(f"payload: {payload}", "qgis_geonode")
            QgsMessageLog.logMessage(f"about to emit {signal_to_emit}...", "qgis_geonode")
            signal_to_emit.emit(payload)
        else:
            QgsMessageLog.logMessage("received error", "qgis_geonode")
            self.error_received.emit(error)


class ApiClient(QObject):

    def __init__(self, access_token='', endpoint_url=''):
        """Base class for API client.

        :param access_token: The access token.
        :type access_token: str

        :param endpoint_url: API base url.
        :type endpoint_url: str
        """
        self.access_token = access_token
        self.endpoint_url = QUrl(endpoint_url)
        self.headers = {
            'authorization': 'Bearer %s' % self.access_token
        }
        self.proxy = {}

        self.manager = QgsNetworkAccessManager.instance()

    @property
    def base_url(self):
        """Base url of the API.

        :return: API url.
        :rtype: str
        """
        return self.endpoint_url

    def get(self, url, **kwargs):
        """Fetch JSON response from get request to the API.

        :param url: API url.
        :type url: str

        :param kwargs: requests.get parameters
        :type kwargs: dict

        :return: The API response.
        :rtype: response object
        """

        request = QNetworkRequest(QUrl(url))
        self.reply = self.manager.get(request)
        return self.reply

    def post(self, url, **kwargs):
        """Fetch JSON response from post request to the API.

        :param url: API url.
        :type url: str

        :param kwargs: requests.post parameters
        :type kwargs: dict

        :return: The API response.
        :rtype: response object
        """
        request = QNetworkRequest(QUrl(url))
        self.reply = self.manager.post(request)
        return self.reply
