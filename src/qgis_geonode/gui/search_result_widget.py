import os
from functools import partial

from qgis.PyQt import (
    QtCore,
    QtGui,
    QtNetwork,
    QtWidgets,
)
from qgis.PyQt.uic import loadUiType

from qgis.core import (
    QgsAbstractMetadataBase,
    QgsDateTimeRange,
    Qgis,
    QgsLayerMetadata,
    QgsNetworkContentFetcherTask,
    QgsProject,
    QgsRasterLayer,
    QgsVectorLayer,
)

from qgis.gui import QgsMessageBar

from ..api_client import BriefGeonodeResource, GeonodeClient, GeonodeResourceType
from ..resources import *
from ..utils import log, tr
from ..conf import connections_manager

WidgetUi, _ = loadUiType(
    os.path.join(os.path.dirname(__file__), "../ui/search_result_widget.ui")
)


class SearchResultWidget(QtWidgets.QWidget, WidgetUi):
    def __init__(
        self,
        message_bar: QgsMessageBar,
        geonode_resource: BriefGeonodeResource,
        parent=None,
    ):
        super().__init__(parent)
        self.setupUi(self)
        self.name_la.setText(geonode_resource.title)
        self.description_la.setText(geonode_resource.abstract)
        self.geonode_resource = geonode_resource
        self.message_bar = message_bar

        connection = connections_manager.get_current_connection()
        self.client = GeonodeClient.from_connection_settings(connection)

        self.wms_btn.clicked.connect(self.load_map_resource)
        self.wcs_btn.clicked.connect(self.load_raster_layer)
        self.wfs_btn.clicked.connect(self.load_vector_layer)

        self.reset_ogc_buttons_state()
        self.load_thumbnail()

    def load_map_resource(self):
        self.wms_btn.setEnabled(False)

        layer = QgsRasterLayer(
            self.geonode_resource.service_urls["wms"], self.geonode_resource.name, "wms"
        )

        self.load_layer(layer)

    def load_raster_layer(self):
        self.wcs_btn.setEnabled(False)
        layer = QgsRasterLayer(
            self.geonode_resource.service_urls["wcs"], self.geonode_resource.name, "wcs"
        )

        self.load_layer(layer)

    def load_vector_layer(self):
        self.wfs_btn.setEnabled(False)
        layer = QgsVectorLayer(
            self.geonode_resource.service_urls["wfs"], self.geonode_resource.name, "WFS"
        )

        self.load_layer(layer)

    def load_layer(self, layer):
        if layer.isValid():
            show_layer_handler = partial(self.show_layer, layer)
            self.client.layer_detail_received.connect(show_layer_handler)
            self.client.get_layer_detail(self.geonode_resource.pk)

        else:
            log("Problem loading the layer into QGIS")
            self.message_bar.pushMessage(
                tr("Problem loading layer, couldn't " "add an invalid layer"),
                level=Qgis.Critical,
            )

    def show_layer(self, layer, geonode_resource):
        self.populate_metadata(layer, geonode_resource)

        QgsProject.instance().addMapLayer(layer)
        self.reset_ogc_buttons_state()

    def populate_metadata(self, layer, geonode_resource):
        metadata = layer.metadata()
        metadata.setIdentifier(str(geonode_resource.uuid))
        metadata.setTitle(geonode_resource.title)
        metadata.setAbstract(geonode_resource.abstract)
        metadata.setLanguage(geonode_resource.language)
        metadata.setKeywords({"layer": geonode_resource.keywords})
        if geonode_resource.category:
            metadata.setCategories([c["identifier"] for c in geonode_resource.category])
        if geonode_resource.license:
            metadata.setLicenses([geonode_resource.license])
        if geonode_resource.constraints:
            constraints = [QgsLayerMetadata.Constraint(geonode_resource.constraints)]
            metadata.setConstraints(constraints)

        metadata.setCrs(geonode_resource.crs)

        spatial_extent = QgsLayerMetadata.SpatialExtent()
        spatial_extent.extentCrs = geonode_resource.crs
        if geonode_resource.spatial_extent:
            spatial_extent.bounds = geonode_resource.spatial_extent.toBox3d(0, 0)
            if geonode_resource.temporal_extent:
                metadata.extent().setTemporalExtents(
                    [
                        QgsDateTimeRange(
                            geonode_resource.temporal_extent[0],
                            geonode_resource.temporal_extent[1],
                        )
                    ]
                )

        metadata.extent().setSpatialExtents([spatial_extent])

        if geonode_resource.owner:
            owner_contact = QgsAbstractMetadataBase.Contact(
                geonode_resource.owner["username"]
            )
            owner_contact.role = tr("owner")
            metadata.addContact(owner_contact)
        if geonode_resource.metadata_author:
            metadata_author = QgsAbstractMetadataBase.Contact(
                geonode_resource.metadata_author["username"]
            )
            metadata_author.role = tr("metadata_author")
            metadata.addContact(metadata_author)

        links = []

        if geonode_resource.thumbnail_url:
            link = QgsAbstractMetadataBase.Link(
                tr("Thumbnail"), tr("Thumbail_link"), geonode_resource.thumbnail_url
            )
            links.append(link)

        if geonode_resource.api_url:
            link = QgsAbstractMetadataBase.Link(
                tr("API"), tr("API_URL"), geonode_resource.api_url
            )
            links.append(link)

        if geonode_resource.gui_url:
            link = QgsAbstractMetadataBase.Link(
                tr("Detail"), tr("Detail_URL"), geonode_resource.gui_url
            )
            links.append(link)

        metadata.setLinks(links)

        layer.setMetadata(metadata)

    def reset_ogc_buttons_state(self):
        self.wms_btn.setEnabled(True)
        self.wcs_btn.setEnabled(
            self.geonode_resource.resource_type == GeonodeResourceType.RASTER_LAYER
        )
        self.wfs_btn.setEnabled(
            self.geonode_resource.resource_type == GeonodeResourceType.VECTOR_LAYER
        )

    def load_thumbnail(self):
        """Fetch the thumbnail from its remote URL and load it"""
        request = QtCore.QUrl(self.geonode_resource.thumbnail_url)
        # TODO: do we need to provide auth config here?
        task = QgsNetworkContentFetcherTask(request)
        task.fetched.connect(partial(self.handle_thumbnail_response, task))
        task.run()

    def handle_thumbnail_response(self, task: QgsNetworkContentFetcherTask):
        reply: QtNetwork.QNetworkReply = task.reply()
        error = reply.error()
        if error == QtNetwork.QNetworkReply.NoError:
            contents: QtCore.QByteArray = reply.readAll()
            thumbnail = QtGui.QPixmap()
            thumbnail.loadFromData(contents)
            self.thumbnail_la.setPixmap(thumbnail)
        else:
            log(f"Error retrieving thumbnail for {self.geonode_resource.name}")
