import os
import typing
from functools import partial

from qgis.PyQt import QtCore, QtGui, QtNetwork, QtWidgets, QtXml
from qgis.PyQt.uic import loadUiType
import qgis.core
import qgis.gui


from ..apiclient import base
from ..apiclient.models import (
    BriefGeonodeResource,
    GeonodeResource,
    GeonodeResourceType,
    GeonodeService,
)
from ..resources import *
from ..utils import log, tr

WidgetUi, _ = loadUiType(
    os.path.join(os.path.dirname(__file__), "../ui/search_result_widget.ui")
)


class SearchResultWidget(QtWidgets.QWidget, WidgetUi):
    action_buttons_layout: QtWidgets.QHBoxLayout
    browser_btn: QtWidgets.QPushButton
    description_la: QtWidgets.QLabel
    name_la: QtWidgets.QLabel
    resource_type_icon_la: QtWidgets.QLabel
    resource_type_la: QtWidgets.QLabel
    thumbnail_la: QtWidgets.QLabel

    layer_loader_task: typing.Optional[qgis.core.QgsTask]
    thumbnail_fetcher_task: typing.Optional[base.NetworkFetcherTask]
    thumbnail_loader_task: typing.Optional[qgis.core.QgsTask]

    load_layer_started = QtCore.pyqtSignal()
    load_layer_ended = QtCore.pyqtSignal()

    api_client: base.BaseGeonodeClient
    brief_resource: BriefGeonodeResource
    full_resource: typing.Optional[GeonodeResource]
    layer: typing.Optional["QgsMapLayer"]

    def __init__(
        self,
        brief_resource: BriefGeonodeResource,
        api_client: base.BaseGeonodeClient,
        parent=None,
    ):
        super().__init__(parent)
        self.setupUi(self)
        self.project = qgis.core.QgsProject.instance()
        self.thumbnail_loader_task = None
        self.thumbnail_fetcher_task = None
        self.layer_loader_task = None
        self.layer = None
        self.brief_resource = brief_resource
        self.full_resource = None
        self.api_client = api_client
        self._initialize_ui()
        self.toggle_service_url_buttons(True)
        self.load_thumbnail()

    def _initialize_ui(self):
        name = self.api_client.get_search_result_identifier(self.brief_resource)
        self.name_la.setText(f"<h3>{name}</h3>")

        if self.brief_resource.resource_type is not None:
            self.resource_type_la.setText(self.brief_resource.resource_type.value)
            icon_path = {
                GeonodeResourceType.RASTER_LAYER: (
                    ":/images/themes/default/mIconRaster.svg"
                ),
                GeonodeResourceType.VECTOR_LAYER: (
                    ":/images/themes/default/mIconVector.svg"
                ),
                GeonodeResourceType.MAP: ":/images/themes/default/mIconRaster.svg",
            }[self.brief_resource.resource_type]
            self.resource_type_icon_la.setPixmap(QtGui.QPixmap(icon_path))
        else:
            self.resource_type_icon_la.setText("")
            self.resource_type_la.setText(tr("Unknown type"))
        sliced_abstract = (
            f"{self.brief_resource.abstract[:700]}..."
            if len(self.brief_resource.abstract) > 700
            else self.brief_resource.abstract
        )
        self.description_la.setText(sliced_abstract)

        for service_type in GeonodeService:
            url = self.brief_resource.service_urls.get(service_type)
            if url is not None and service_type != GeonodeService.FILE_DOWNLOAD:
                icon = QtGui.QIcon(
                    f":/plugins/qgis_geonode/icon_{service_type.value}.svg"
                )
                button = QtWidgets.QPushButton()
                button.setObjectName(f"{service_type.name.lower()}_btn")
                button.setIcon(icon)
                button.setToolTip(tr("Load layer via {}").format(service_type.value))
                button.clicked.connect(partial(self.load_layer, service_type))
                order = 1 if service_type == GeonodeService.OGC_WMS else 2
                self.action_buttons_layout.insertWidget(order, button)
        self.browser_btn.setIcon(QtGui.QIcon(":/plugins/qgis_geonode/mIconGeonode.svg"))
        self.browser_btn.clicked.connect(self.open_resource_page)

    def open_resource_page(self):
        if self.brief_resource.gui_url is not None:
            QtGui.QDesktopServices.openUrl(QtCore.QUrl(self.brief_resource.gui_url))
        else:
            message = (
                "Couldn't open resource in browser page, the resource doesn't contain "
                "GeoNode layer page URL"
            )
            log(message)
            self._get_datasource_widget().show_message(tr(message))

    def toggle_service_url_buttons(self, enabled: bool):
        for index in range(self.action_buttons_layout.count()):
            widget = self.action_buttons_layout.itemAt(index).widget()
            if widget is not None:
                widget.setEnabled(enabled)

    def load_thumbnail(self):
        """Fetch the thumbnail from its remote URL and load it"""
        # TODO: do we need to provide auth config here?
        # task = qgis.core.QgsNetworkContentFetcherTask(
        #     QtCore.QUrl(self.brief_resource.thumbnail_url)
        # )
        # task.fetched.connect(partial(self.handle_thumbnail_response, task))
        # task.run()

        log(f"thumbnail URL: {self.brief_resource.thumbnail_url}")
        self.thumbnail_fetcher_task = base.NetworkFetcherTask(
            self.api_client,
            QtNetwork.QNetworkRequest(QtCore.QUrl(self.brief_resource.thumbnail_url)),
        )
        self.thumbnail_fetcher_task.request_finished.connect(
            self.handle_thumbnail_response
        )
        qgis.core.QgsApplication.taskManager().addTask(self.thumbnail_fetcher_task)

    def handle_thumbnail_response(self):
        self.thumbnail_loader_task = ThumbnailLoader(
            self.thumbnail_fetcher_task.reply_content,
            self.thumbnail_la,
            self.brief_resource.title,
        )
        qgis.core.QgsApplication.taskManager().addTask(self.thumbnail_loader_task)

    def _get_datasource_widget(self):
        return self.parent().parent().parent().parent()

    def handle_layer_load_start(self):
        parent = self._get_datasource_widget()
        parent.toggle_search_controls(False)
        parent.show_progress(tr("Loading layer..."))
        self.toggle_service_url_buttons(False)

    def handle_layer_load_end(self):
        parent = self._get_datasource_widget()
        parent.toggle_search_controls(True)
        parent.toggle_search_buttons()
        self.toggle_service_url_buttons(True)
        self._get_datasource_widget().message_bar.clearWidgets()

    def handle_loading_error(
        self, qt_error: str, http_status_code: int, http_status_reason: str
    ):
        if http_status_code != 0:
            http_status = f"{http_status_code} - {http_status_reason}"
        else:
            http_status = ""
        self.handle_layer_load_end()
        message = " ".join((qt_error, http_status))
        self._get_datasource_widget().show_message(
            message, level=qgis.core.Qgis.Critical
        )

    def load_layer(self, service_type: GeonodeService):
        self.handle_layer_load_start()
        uri = self.brief_resource.service_urls[service_type]
        self.layer_loader_task = LayerLoaderTask(
            uri,
            self.brief_resource.title,
            service_type,
            api_client=self.api_client,
            layer_handler=self.prepare_loaded_layer,
            error_handler=self.handle_loading_error,
        )
        qgis.core.QgsApplication.taskManager().addTask(self.layer_loader_task)

    def prepare_loaded_layer(self, layer: "QgsMapLayer"):
        """Retrieve layer details for the layer that has been loaded"""
        self.layer = layer
        self.api_client.layer_detail_received.connect(self.handle_layer_detail)
        self.api_client.error_received.connect(self.handle_loading_error)
        self.api_client.get_layer_detail_from_brief_resource(self.brief_resource)

    def handle_layer_detail(self, resource: GeonodeResource):
        """Populate the loaded layer with metadata from the retrieved GeoNode resource

        Then either retrieve the layer's SLD or add it to QGIS project.

        """

        self.full_resource = resource
        self.api_client.layer_detail_received.disconnect(self.handle_layer_detail)
        metadata = populate_metadata(self.layer.metadata(), resource)
        self.layer.setMetadata(metadata)
        if self.layer.type() == qgis.core.QgsMapLayer.VectorLayer:
            self.api_client.style_detail_received.connect(self.handle_sld_received)
            if self.full_resource.default_style is not None:
                self.api_client.get_layer_style(self.full_resource)
            else:
                self.add_layer_to_project()
        else:  # TODO: add support for loading SLDs for raster layers too
            self.add_layer_to_project()

    def handle_sld_received(self, sld_named_layer: QtXml.QDomElement):
        """Retrieve SLD style and set it to the layer, then add layer to QGIS project"""
        self.api_client.style_detail_received.disconnect(self.handle_sld_received)
        error_message = ""
        loaded_sld = self.layer.readSld(sld_named_layer, error_message)
        if not loaded_sld:
            self._get_datasource_widget().show_message(
                tr(f"Problem in applying GeoNode style for the layer: {error_message}")
            )
        self.add_layer_to_project()

    def add_layer_to_project(self):
        self.api_client.error_received.disconnect(self.handle_loading_error)
        self.project.addMapLayer(self.layer)
        self.handle_layer_load_end()


class ThumbnailLoader(qgis.core.QgsTask):
    def __init__(
        self,
        raw_thumbnail: QtCore.QByteArray,
        label: QtWidgets.QLabel,
        resource_title: str,
    ):
        """Load thumbnail data

        This task reads the thumbnail gotten over the network into a QImage object in a
        separate thread and then loads it up onto the main GUI in its `finished()`
        method - `finished` runs in the main thread. This is done because this plugin's
        GUI wants to load multiple thumbnails concurrently. If we were to read the raw
        thumbnail bytes into a pixmap in the main thread it would not be possible to
        load them in parallel because QPixmap does blocking IO.

        """

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


class LayerLoaderTask(qgis.core.QgsTask):
    brief_resource: BriefGeonodeResource
    service_type: GeonodeService
    api_client: base.BaseGeonodeClient
    layer_handler: typing.Callable
    error_handler: typing.Callable
    layer: typing.Optional["QgsMapLayer"]

    def __init__(
        self,
        uri: str,
        layer_title: str,
        service_type: GeonodeService,
        api_client: base.BaseGeonodeClient,
        layer_handler: typing.Callable,
        error_handler: typing.Callable,
    ):
        """Load a QGIS layer

        This is done in a QgsTask in order to allow the loading of a layer from the
        network to be done in a background thread and not block the main QGIS UI.

        """

        super().__init__()
        self.uri = uri
        self.layer_title = layer_title
        self.service_type = service_type
        self.api_client = api_client
        self.layer_handler = layer_handler
        self.error_handler = error_handler
        self.layer = None

    def run(self):
        log(f"service_uri: {self.uri}")
        layer_class, provider = {
            GeonodeService.OGC_WMS: (qgis.core.QgsRasterLayer, "wms"),
            GeonodeService.OGC_WCS: (qgis.core.QgsRasterLayer, "wcs"),
            GeonodeService.OGC_WFS: (
                qgis.core.QgsVectorLayer,
                "WFS",
            ),  # TODO: does this really require all caps?
        }[self.service_type]
        layer = layer_class(self.uri, self.layer_title, provider)
        if layer.isValid():
            self.layer = layer
        return self.layer is not None

    def finished(self, result: bool):
        if result:
            # Cloning the layer seems to be required in order to make sure the WMS
            # layers work appropriately - Otherwise we get random crashes when loading
            # WMS layers. This may be related to how the layer is moved from the
            # secondary thread by QgsTaskManager and the layer's ownership.
            cloned_layer = self.layer.clone()
            self.layer_handler(cloned_layer)
        else:
            message = f"Error loading layer {self.uri!r}"
            log(message)
            self.error_handler(message)


def populate_metadata(
    metadata: qgis.core.QgsLayerMetadata, geonode_resource: GeonodeResource
):
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
    return metadata
