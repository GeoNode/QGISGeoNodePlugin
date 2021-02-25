import os
import typing
from functools import partial

from qgis.PyQt import QtCore, QtGui, QtNetwork, QtWidgets, QtXml
from qgis.PyQt.uic import loadUiType

from qgis.core import (
    QgsAbstractMetadataBase,
    QgsDateTimeRange,
    Qgis,
    QgsLayerMetadata,
    QgsMapLayerType,
    QgsNetworkContentFetcherTask,
    QgsProject,
    QgsRasterLayer,
    QgsVectorLayer,
)

from qgis.gui import QgsMessageBar

from ..apiclient import get_geonode_client
from ..apiclient.models import (
    BriefGeonodeResource,
    GeonodeResource,
    GeonodeService,
)
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
        self.name_la.setText(f"<h3>{geonode_resource.title}</h3>")
        if geonode_resource.resource_type is not None:
            self.resource_type_la.setText(geonode_resource.resource_type.value)
        else:
            self.resource_type_la.setText("unknown")
        self.description_la.setText(geonode_resource.abstract)
        self.geonode_resource = geonode_resource
        self.message_bar = message_bar
        connection_settings = connections_manager.get_current_connection()
        self.client = get_geonode_client(connection_settings)
        for service_type in GeonodeService:
            url = geonode_resource.service_urls.get(service_type)
            if url is not None:
                description, order, handler = self._get_service_button_details(
                    service_type
                )
                button = QtWidgets.QPushButton(description)
                button.setObjectName(f"{service_type.name.lower()}_btn")
                button.clicked.connect(handler)
                self.action_buttons_layout.insertWidget(order, button)

        self.toggle_service_url_buttons(True)
        self.load_thumbnail()

        self.browser_btn.clicked.connect(self.open_resource_page)

    def _get_service_button_details(
        self, service: GeonodeService
    ) -> typing.Tuple[str, int, typing.Callable]:
        return {
            GeonodeService.OGC_WMS: ("WMS", 1, self.load_map_resource),
            GeonodeService.OGC_WFS: ("WFS", 2, self.load_vector_layer),
            GeonodeService.OGC_WCS: ("WCS", 2, self.load_raster_layer),
            GeonodeService.FILE_DOWNLOAD: ("File download", 3, None),
        }[service]

    def load_map_resource(self):
        self.toggle_service_url_buttons(False)

        layer = QgsRasterLayer(
            self.geonode_resource.service_urls[GeonodeService.OGC_WMS],
            self.geonode_resource.title,
            "wms",
        )

        self.load_layer(layer)

    def load_raster_layer(self):
        self.toggle_service_url_buttons(False)
        layer = QgsRasterLayer(
            self.geonode_resource.service_urls[GeonodeService.OGC_WCS],
            self.geonode_resource.title,
            "wcs",
        )

        self.load_layer(layer)

    def load_vector_layer(self):
        self.toggle_service_url_buttons(False)
        layer = QgsVectorLayer(
            self.geonode_resource.service_urls[GeonodeService.OGC_WFS],
            self.geonode_resource.title,
            "WFS",
        )

        self.load_layer(layer)

    def load_layer(self, layer):
        if layer.isValid():
            self.client.layer_detail_received.connect(
                partial(self.prepare_layer, layer)
            )
            self.client.get_layer_detail_from_brief_resource(self.geonode_resource)
        else:
            log("Problem loading the layer into QGIS")
            self.message_bar.pushMessage(
                tr("Problem loading layer, couldn't " "add an invalid layer"),
                level=Qgis.Critical,
            )

    def prepare_layer(self, layer: "QgsMapLayer", geonode_resource: GeonodeResource):
        self.populate_metadata(layer, geonode_resource)
        if layer.type() == QgsMapLayerType.VectorLayer:
            self.client.style_detail_received.connect(
                partial(self.load_sld_layer, layer)
            )
            self.client.get_layer_style(geonode_resource)
        else:  # TODO: add support for loading SLDs for raster layers too
            self.add_layer_to_project(layer)

    def add_layer_to_project(self, layer: "QgsMapLayer"):
        QgsProject.instance().addMapLayer(layer)
        self.toggle_service_url_buttons(True)

    def populate_metadata(self, layer, geonode_resource):
        metadata = layer.metadata()
        metadata.setIdentifier(str(geonode_resource.uuid))
        metadata.setTitle(geonode_resource.title)
        metadata.setAbstract(geonode_resource.abstract)
        metadata.setLanguage(geonode_resource.language)
        metadata.setKeywords({"layer": geonode_resource.keywords})
        if geonode_resource.category:
            metadata.setCategories([geonode_resource.category])
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

    def load_sld_layer(self, layer, sld_named_layer: QtXml.QDomElement):
        """Retrieve SLD style and set it to the layer, then add layer to QGIS project"""
        error_message = ""
        loaded_sld = layer.readSld(sld_named_layer, error_message)
        if not loaded_sld:
            self.message_bar.clearWidgets()
            self.message_bar.pushMessage(
                tr(
                    "Problem in applying GeoNode style for the layer, {}".format(
                        error_message
                    )
                ),
                level=Qgis.Warning,
            )
        self.add_layer_to_project(layer)

    def toggle_service_url_buttons(self, enabled: bool):
        for index in range(self.action_buttons_layout.count()):
            widget = self.action_buttons_layout.itemAt(index).widget()
            if widget is not None:
                widget.setEnabled(enabled)

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
            log(f"Error retrieving thumbnail for {self.geonode_resource.title}")

    def style_download_error(self, layer, error):
        self.message_bar.clearWidgets()
        self.message_bar.pushMessage(
            tr("Problem in downloading style for the layer, {}").format(error),
            level=Qgis.Warning,
        )
        QgsProject.instance().addMapLayer(layer)
        self.toggle_service_url_buttons(True)

    def open_resource_page(self):
        if self.geonode_resource.gui_url is not None:
            QtGui.QDesktopServices.openUrl(QtCore.QUrl(self.geonode_resource.gui_url))
        else:
            log(
                "Couldn't open resource in browser page, the resource"
                "doesn't contain GeoNode layer page URL"
            )
            self.message_bar.pushMessage(
                tr(
                    "Couldn't open resource in browser page, the resource"
                    "doesn't contain GeoNode layer page URL"
                ),
                level=Qgis.Critical,
            )
