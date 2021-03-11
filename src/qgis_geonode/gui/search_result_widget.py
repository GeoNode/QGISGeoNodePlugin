import os
import typing
from functools import partial

from qgis.PyQt import QtCore, QtGui, QtNetwork, QtWidgets, QtXml
from qgis.PyQt.uic import loadUiType
import qgis.core
import qgis.gui


from ..apiclient import get_geonode_client
from ..apiclient.base import BaseGeonodeClient
from ..apiclient.models import (
    BriefGeonodeResource,
    GeonodeResource,
    GeonodeResourceType,
    GeonodeService,
)
from ..resources import *
from ..utils import log, tr
from ..conf import connections_manager

WidgetUi, _ = loadUiType(
    os.path.join(os.path.dirname(__file__), "../ui/search_result_widget.ui")
)


class SearchResultWidget(QtWidgets.QWidget, WidgetUi):
    name_la: QtWidgets.QLabel
    description_la: QtWidgets.QLabel
    resource_type_la: QtWidgets.QLabel
    resource_type_icon_la: QtWidgets.QLabel
    thumbnail_la: QtWidgets.QLabel
    message_bar: qgis.gui.QgsMessageBar
    action_buttons_layout: QtWidgets.QHBoxLayout
    browser_btn: QtWidgets.QPushButton
    thumbnail_loader_task: typing.Optional[qgis.core.QgsTask]

    load_layer_started = QtCore.pyqtSignal()
    load_layer_ended = QtCore.pyqtSignal()

    def __init__(
        self,
        geonode_resource: BriefGeonodeResource,
        api_client: BaseGeonodeClient,
        parent=None,
    ):
        super().__init__(parent)
        self.setupUi(self)
        self.thumbnail_loader_task = None
        self.name_la.setText(f"<h3>{geonode_resource.name}</h3>")

        name = api_client.get_search_result_identifier(geonode_resource)
        self.name_la.setText(f"<h3>{name}</h3>")

        if geonode_resource.resource_type is not None:
            self.resource_type_la.setText(geonode_resource.resource_type.value)
            icon_path = {
                GeonodeResourceType.RASTER_LAYER: (
                    ":/images/themes/default/mIconRaster.svg"
                ),
                GeonodeResourceType.VECTOR_LAYER: (
                    ":/images/themes/default/mIconVector.svg"
                ),
                GeonodeResourceType.MAP: ":/images/themes/default/mIconRaster.svg",
            }[geonode_resource.resource_type]
            self.resource_type_icon_la.setPixmap(QtGui.QPixmap(icon_path))
        else:
            self.resource_type_icon_la.setText("")
            self.resource_type_la.setText(tr("Unknown type"))
        sliced_abstract = (
            f"{geonode_resource.abstract[:700]}..."
            if len(geonode_resource.abstract) > 700
            else geonode_resource.abstract
        )

        self.description_la.setText(sliced_abstract)
        self.geonode_resource = geonode_resource
        connection_settings = connections_manager.get_current_connection()
        self.client = get_geonode_client(connection_settings)
        for service_type in GeonodeService:
            url = geonode_resource.service_urls.get(service_type)
            if url is not None:
                (
                    description,
                    order,
                    icon_path,
                    handler,
                ) = self._get_service_button_details(service_type)
                icon = QtGui.QIcon(icon_path)
                button = QtWidgets.QPushButton()
                button.setObjectName(f"{service_type.name.lower()}_btn")
                button.setIcon(icon)
                button.setToolTip(tr("Load layer via {}").format(description))
                button.clicked.connect(handler)
                self.action_buttons_layout.insertWidget(order, button)

        self.toggle_service_url_buttons(True)
        self.load_thumbnail()
        self.browser_btn.setIcon(QtGui.QIcon(":/plugins/qgis_geonode/mIconGeonode.svg"))
        self.browser_btn.clicked.connect(self.open_resource_page)
        qgs_project = qgis.core.QgsProject.instance()
        qgs_project.layerWasAdded.connect(self.handle_layer_load_end)

    def _get_service_button_details(
        self, service: GeonodeService
    ) -> typing.Tuple[str, int, str, typing.Callable]:
        icon_path = f":/plugins/qgis_geonode/icon_{service.value}.svg"
        return {
            GeonodeService.OGC_WMS: (
                "WMS",
                1,
                icon_path,
                partial(self.load_layer, service),
            ),
            GeonodeService.OGC_WFS: (
                "WFS",
                2,
                icon_path,
                partial(self.load_layer, service),
            ),
            GeonodeService.OGC_WCS: (
                "WCS",
                2,
                icon_path,
                partial(self.load_layer, service),
            ),
            GeonodeService.FILE_DOWNLOAD: ("File download", 3, None, None),
        }[service]

    def get_datasource_widget(self):
        return self.parent().parent().parent().parent()

    def handle_layer_load_start(self):
        # disable our own buttons and also any buttons on the parent
        parent = self.get_datasource_widget()
        parent.toggle_search_controls(False)
        parent.show_progress(tr("Loading layer..."))
        self.toggle_service_url_buttons(False)

    def handle_layer_load_end(self):
        # enable our own buttons and also any buttons on the parent
        parent = self.get_datasource_widget()
        parent.toggle_search_controls(True)
        parent.toggle_search_buttons()
        self.toggle_service_url_buttons(True)
        self.clear_progress()

    def load_layer(self, service_type: GeonodeService):
        # self.load_layer_started.emit()
        self.handle_layer_load_start()
        uri = self.geonode_resource.service_urls[service_type]
        log(f"service_uri: {uri}")
        # self.toggle_service_url_buttons(False)
        # self.get_datasource_widget().show_progress(tr("Loading layer..."))
        layer_class, provider = {
            GeonodeService.OGC_WMS: (qgis.core.QgsRasterLayer, "wms"),
            GeonodeService.OGC_WCS: (qgis.core.QgsRasterLayer, "wcs"),
            GeonodeService.OGC_WFS: (
                qgis.core.QgsVectorLayer,
                "WFS",
            ),  # TODO: does this really require all caps?
        }[service_type]
        layer = layer_class(uri, self.geonode_resource.title, provider)
        if layer.isValid():
            self.client.layer_detail_received.connect(
                partial(self.prepare_layer, layer)
            )
            self.client.get_layer_detail_from_brief_resource(self.geonode_resource)
        else:
            message = "Invalid layer, cannot load"
            log(message)
            self.get_datasource_widget().show_message(
                message, level=qgis.core.Qgis.Critical
            )
            self.toggle_service_url_buttons(True)

    def prepare_layer(self, layer: "QgsMapLayer", geonode_resource: GeonodeResource):
        self.populate_metadata(layer, geonode_resource)
        if layer.type() == qgis.core.QgsMapLayerType.VectorLayer:
            self.client.style_detail_received.connect(
                partial(self.load_sld_layer, layer)
            )
            self.client.get_layer_style(geonode_resource)
        else:  # TODO: add support for loading SLDs for raster layers too
            self.add_layer_to_project(layer)

    def add_layer_to_project(self, layer: "QgsMapLayer"):
        qgis.core.QgsProject.instance().addMapLayer(layer)
        # self.toggle_service_url_buttons(True)
        # self.clear_progress()

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
            constraints = [
                qgis.core.QgsLayerMetadata.Constraint(geonode_resource.constraints)
            ]
            metadata.setConstraints(constraints)

        metadata.setCrs(geonode_resource.crs)

        spatial_extent = qgis.core.QgsLayerMetadata.SpatialExtent()
        spatial_extent.extentCrs = geonode_resource.crs
        if geonode_resource.spatial_extent:
            spatial_extent.bounds = geonode_resource.spatial_extent.toBox3d(0, 0)
            if geonode_resource.temporal_extent:
                metadata.extent().setTemporalExtents(
                    [
                        qgis.core.QgsDateTimeRange(
                            geonode_resource.temporal_extent[0],
                            geonode_resource.temporal_extent[1],
                        )
                    ]
                )

        metadata.extent().setSpatialExtents([spatial_extent])

        if geonode_resource.owner:
            owner_contact = qgis.core.QgsAbstractMetadataBase.Contact(
                geonode_resource.owner["username"]
            )
            owner_contact.role = tr("owner")
            metadata.addContact(owner_contact)
        if geonode_resource.metadata_author:
            metadata_author = qgis.core.QgsAbstractMetadataBase.Contact(
                geonode_resource.metadata_author["username"]
            )
            metadata_author.role = tr("metadata_author")
            metadata.addContact(metadata_author)

        links = []

        if geonode_resource.thumbnail_url:
            link = qgis.core.QgsAbstractMetadataBase.Link(
                tr("Thumbnail"), tr("Thumbail_link"), geonode_resource.thumbnail_url
            )
            links.append(link)

        if geonode_resource.api_url:
            link = qgis.core.QgsAbstractMetadataBase.Link(
                tr("API"), tr("API_URL"), geonode_resource.api_url
            )
            links.append(link)

        if geonode_resource.gui_url:
            link = qgis.core.QgsAbstractMetadataBase.Link(
                tr("Detail"), tr("Detail_URL"), geonode_resource.gui_url
            )
            links.append(link)

        metadata.setLinks(links)

        layer.setMetadata(metadata)

    def load_sld_layer(self, layer, sld_named_layer: QtXml.QDomElement):
        """Retrieve SLD style and set it to the layer, then add layer to QGIS project"""
        log(f"inside load_sld_layer...")
        error_message = ""
        loaded_sld = layer.readSld(sld_named_layer, error_message)
        if not loaded_sld:
            self.get_datasource_widget().show_message(
                tr(f"Problem in applying GeoNode style for the layer: {error_message}")
            )
            # self.toggle_service_url_buttons(True)
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
        task = qgis.core.QgsNetworkContentFetcherTask(request)
        task.fetched.connect(partial(self.handle_thumbnail_response, task))
        task.run()

    def handle_thumbnail_response(self, task: qgis.core.QgsNetworkContentFetcherTask):
        reply: QtNetwork.QNetworkReply = task.reply()
        error = reply.error()
        if error == QtNetwork.QNetworkReply.NoError:
            contents: QtCore.QByteArray = reply.readAll()
            self.thumbnail_loader_task = ThumbnailLoader(
                contents,
                self.thumbnail_la,
                self.geonode_resource.title,
            )
            qgis.core.QgsApplication.taskManager().addTask(self.thumbnail_loader_task)
        else:
            log(f"Error retrieving thumbnail for {self.geonode_resource.title}")

    def open_resource_page(self):
        if self.geonode_resource.gui_url is not None:
            QtGui.QDesktopServices.openUrl(QtCore.QUrl(self.geonode_resource.gui_url))
        else:
            message = (
                "Couldn't open resource in browser page, the resource doesn't contain "
                "GeoNode layer page URL"
            )
            log(message)
            self.get_datasource_widget().show_message(tr(message))

    def clear_progress(self):
        self.get_datasource_widget().message_bar.clearWidgets()


class ThumbnailLoader(qgis.core.QgsTask):
    def __init__(
        self,
        raw_thumbnail: QtCore.QByteArray,
        label: QtWidgets.QLabel,
        resource_title: str,
    ):
        super().__init__()
        self.raw_thumbnail = raw_thumbnail
        self.label = label
        self.resource_title = resource_title
        self.thumbnail_image = None
        self.exception = None

    def run(self):
        self.thumbnail_image = QtGui.QImage.fromData(self.raw_thumbnail)
        return True

    def finished(self, result: bool):
        if result:
            thumbnail = QtGui.QPixmap.fromImage(self.thumbnail_image)
            self.label.setPixmap(thumbnail)
        else:
            log(f"Error retrieving thumbnail for {self.resource_title!r}")
