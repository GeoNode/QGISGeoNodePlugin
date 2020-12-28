# coding=utf-8
"""Abstract class for Geonode API .
"""
import os

from qgis.core import QgsApplication, QgsNetworkAccessManager
# noinspection PyPackageRequirements
from qgis.PyQt.QtCore import QUrl, QObject
# noinspection PyPackageRequirements
from qgis.PyQt.QtNetwork import QNetworkReply, QNetworkRequest


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
