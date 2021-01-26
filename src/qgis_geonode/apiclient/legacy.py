import typing
from xml.etree import ElementTree as ET


from qgis.PyQt.QtCore import (
    QByteArray,
    QUrl,
    QUrlQuery,
)

from . import models
from .base import BaseGeonodeClient


class GeonodeLegacyClient(BaseGeonodeClient):
    """Asynchronous GeoNode API client for pre-v2 API"""

    @property
    def catalogue_url(self):
        return f"{self.base_url}/catalogue/csw"

    def get_layers_url_endpoint(
            self,
            page: typing.Optional[int] = 1,
            page_size: typing.Optional[int] = 10
    ) -> QUrl:
        url = QUrl(f"{self.catalogue_url}")
        query = QUrlQuery()
        query.addQueryItem("service", "CSW")
        query.addQueryItem("version", "2.0.2")
        query.addQueryItem("request", "GetRecords")
        query.addQueryItem("resultType", "results")
        query.addQueryItem("startPosition", str(page_size * page))
        query.addQueryItem("maxRecords", str(page_size))
        query.addQueryItem("typeNames", "csw:Record")
        query.addQueryItem("ElementSetName", "full")
        return url

    def get_layer_detail_url_endpoint(self, id_: int) -> QUrl:
        url = QUrl(f"{self.catalogue_url}")
        query = QUrlQuery()
        query.addQueryItem("service", "CSW")
        query.addQueryItem("version", "2.0.2")
        query.addQueryItem("request", "GetRecordById")
        query.addQueryItem("ElementSetName", "full")
        query.addQueryItem("Id", str(id_))
        return url

    def deserialize_response_contents(self, contents: QByteArray) -> ET.Element:
        decoded_contents: str = contents.data().decode()
        return ET.fromstring(decoded_contents)

    def handle_layer_list(self, payload: typing.Any):
        pass


def get_brief_geonode_resource(
        deserialized_resource: ET.Element,
        geonode_base_url: str
) -> models.BriefGeonodeResource:
    return models.BriefGeonodeResource(
        pk=int(deserialized_resource["pk"]),
        uuid=uuid.UUID(deserialized_resource["uuid"]),
        name=deserialized_resource.get("name", ""),
        resource_type=_get_resource_type(deserialized_resource),
        title=deserialized_resource.get("title", ""),
        abstract=deserialized_resource.get("abstract", ""),
        spatial_extent=_get_spatial_extent(deserialized_resource["bbox_polygon"]),
        crs=QgsCoordinateReferenceSystem(
            deserialized_resource["srid"].replace("EPSG:", "")),
        thumbnail_url=deserialized_resource["thumbnail_url"],
        api_url=(
            f"{geonode_base_url}/api/v2/layers/{deserialized_resource['pk']}"),
        gui_url=deserialized_resource["detail_url"],
        published_date=_get_published_date(deserialized_resource),
        temporal_extent=_get_temporal_extent(deserialized_resource),
        keywords=[k["name"] for k in deserialized_resource.get("keywords", [])],
        category=deserialized_resource.get("category"),
    )
