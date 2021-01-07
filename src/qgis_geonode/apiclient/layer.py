# coding=utf-8
"""Implementation of GeoNode layer API endpoint.
"""
from src.qgis_geonode.apiclient.api_client import ApiClient


class LayerAPI(ApiClient):
    """
    Managing GeoNode Layer API endpoints

    """

    def __init__(self, endpoint_url):
        """Implementation of GeoNode API client.

        API base url.
        :type endpoint_url: str
        """
        super(LayerAPI, self).__init__(endpoint_url)

    @property
    def base_url(self):
        """Base url of the API.

        :return: API url.
        :rtype: str
        """
        return "%s/layers/v2" % (self.endpoint_url)

    def get_layers(self, endpoint):
        """Abstract."""

        response = self.get(endpoint)
        return response.json()

    def get_layers_metadata(self, endpoint):
        """Abstract."""

        response = self.get(endpoint)
        return response.json()

    def get_layers_styles(self, endpoint):
        """Abstract."""

        response = self.get(endpoint)
        return response.json()
