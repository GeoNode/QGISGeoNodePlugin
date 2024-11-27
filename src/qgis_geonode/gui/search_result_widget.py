import os
import typing
import urllib.parse
from functools import partial

from qgis.PyQt import (
    QtCore,
    QtGui,
    QtWidgets,
)
from qgis.PyQt.uic import loadUiType
import qgis.core
import qgis.gui


from ..apiclient import (
    base,
    models,
)
from .. import network
from ..apiclient.models import ApiClientCapability
from ..conf import settings_manager
from ..metadata import populate_metadata
from ..resources import *
from ..utils import log, tr

WidgetUi, _ = loadUiType(
    os.path.join(os.path.dirname(__file__), "../ui/search_result_widget.ui")
)


class SearchResultWidget(QtWidgets.QWidget, WidgetUi):
    action_buttons_layout: QtWidgets.QHBoxLayout
    browser_btn: QtWidgets.QPushButton
    description_la: QtWidgets.QLabel
    title_la: QtWidgets.QLabel
    resource_type_icon_la: QtWidgets.QLabel
    resource_type_la: QtWidgets.QLabel
    thumbnail_la: QtWidgets.QLabel

    dataset_loader_task: typing.Optional[qgis.core.QgsTask]
    # thumbnail_fetcher_task fetches the thumbnail over the network
    # thumbnail_loader_task then loads the thumbnail
    thumbnail_fetcher_task: typing.Optional[network.NetworkRequestTask]
    thumbnail_loader_task: typing.Optional[qgis.core.QgsTask]

    load_layer_started = QtCore.pyqtSignal()
    load_layer_ended = QtCore.pyqtSignal()

    api_client: base.BaseGeonodeClient
    brief_dataset: models.BriefDataset
    layer: typing.Optional["QgsMapLayer"]
    data_source_widget: "GeonodeDataSourceWidget"

    def __init__(
        self,
        brief_dataset: models.BriefDataset,
        api_client: base.BaseGeonodeClient,
        data_source_widget: "GeonodeDataSourceWidget",
        parent=None,
    ):
        super().__init__(parent)
        self.setupUi(self)
        self.project = qgis.core.QgsProject.instance()
        self.data_source_widget = data_source_widget
        self.thumbnail_loader_task = None
        self.thumbnail_fetcher_task = None
        self.dataset_loader_task = None
        self.layer = None
        self.brief_dataset = brief_dataset
        self.api_client = api_client
        self._initialize_ui()
        self.toggle_service_url_buttons(True)
        self.load_thumbnail()

    def _add_loadable_button(self, geonode_service: models.GeonodeService):
        url = self.brief_dataset.service_urls.get(geonode_service)
        if url is not None:
            icon = QtGui.QIcon(
                f":/plugins/qgis_geonode/icon_{geonode_service.value}.svg"
            )
            button = QtWidgets.QPushButton()
            button.setObjectName(f"{geonode_service.value.lower()}_btn")
            button.setIcon(icon)
            button.setToolTip(tr(f"Load layer via {geonode_service.value}"))
            button.clicked.connect(partial(self.load_dataset, geonode_service))
            order = 1 if geonode_service == models.GeonodeService.OGC_WMS else 2
            self.action_buttons_layout.insertWidget(order, button)

    def _initialize_ui_for_vector_dataset(self):
        self.resource_type_icon_la.setPixmap(
            QtGui.QPixmap(":/images/themes/default/mIconVector.svg")
        )
        able_to_load_wms = (
            ApiClientCapability.LOAD_VECTOR_DATASET_VIA_WMS
            in self.api_client.capabilities
        )
        allowed_to_load_wms = (
            models.GeonodePermission.VIEW_RESOURCEBASE in self.brief_dataset.permissions
        )
        if able_to_load_wms and allowed_to_load_wms:
            self._add_loadable_button(models.GeonodeService.OGC_WMS)
        able_to_load_wfs = (
            ApiClientCapability.LOAD_VECTOR_DATASET_VIA_WFS
            in self.api_client.capabilities
        )
        allowed_to_load_wfs = (
            models.GeonodePermission.DOWNLOAD_RESOURCEBASE
            in self.brief_dataset.permissions
        )
        if able_to_load_wfs and allowed_to_load_wfs:
            self._add_loadable_button(models.GeonodeService.OGC_WFS)

    def _initialize_ui_for_raster_dataset(self):
        self.resource_type_icon_la.setPixmap(
            QtGui.QPixmap(":/images/themes/default/mIconRaster.svg")
        )
        able_to_load_wms = (
            ApiClientCapability.LOAD_RASTER_DATASET_VIA_WMS
            in self.api_client.capabilities
        )
        allowed_to_load_wms = (
            models.GeonodePermission.VIEW_RESOURCEBASE in self.brief_dataset.permissions
        )
        if able_to_load_wms and allowed_to_load_wms:
            self._add_loadable_button(models.GeonodeService.OGC_WMS)
        able_to_load_wcs = (
            ApiClientCapability.LOAD_RASTER_DATASET_VIA_WCS
            in self.api_client.capabilities
        )
        allowed_to_load_wcs = (
            models.GeonodePermission.DOWNLOAD_RESOURCEBASE
            in self.brief_dataset.permissions
        )
        if able_to_load_wcs and allowed_to_load_wcs:
            self._add_loadable_button(models.GeonodeService.OGC_WCS)

    def _initialize_ui(self):
        self.title_la.setText(f"<h3>{self.brief_dataset.title}</h3>")
        self.resource_type_la.setText(self.brief_dataset.dataset_sub_type.value)
        self.description_la.setText(self.brief_dataset.abstract)
        if self.brief_dataset.detail_url:
            self.browser_btn.setIcon(
                QtGui.QIcon(":/plugins/qgis_geonode/mIconGeonode.svg")
            )
            self.browser_btn.clicked.connect(self.open_resource_page)
        else:
            self.browser_btn.setEnabled(False)
        if (
            self.brief_dataset.dataset_sub_type
            == models.GeonodeResourceType.VECTOR_LAYER
        ):
            self._initialize_ui_for_vector_dataset()
        elif (
            self.brief_dataset.dataset_sub_type
            == models.GeonodeResourceType.RASTER_LAYER
        ):
            self._initialize_ui_for_raster_dataset()
        else:
            pass

    def open_resource_page(self):
        QtGui.QDesktopServices.openUrl(QtCore.QUrl(self.brief_dataset.detail_url))

    def toggle_service_url_buttons(self, enabled: bool):
        for index in range(self.action_buttons_layout.count()):
            widget = self.action_buttons_layout.itemAt(index).widget()
            if widget is not None:
                widget.setEnabled(enabled)

    def load_thumbnail(self):
        """Fetch the thumbnail from its remote URL and load it"""
        self.thumbnail_fetcher_task = network.NetworkRequestTask(
            [
                network.RequestToPerform(
                    url=QtCore.QUrl(self.brief_dataset.thumbnail_url)
                )
            ],
            self.api_client.network_requests_timeout,
            self.api_client.auth_config,
            description=f"Get thumbnail for {self.brief_dataset.title!r}",
        )
        self.thumbnail_fetcher_task.task_done.connect(self.handle_thumbnail_response)
        qgis.core.QgsApplication.taskManager().addTask(self.thumbnail_fetcher_task)

    def handle_thumbnail_response(self, fetch_result: bool):
        if fetch_result:
            data_ = self.thumbnail_fetcher_task.response_contents[0].response_body
            self.thumbnail_loader_task = ThumbnailLoaderTask(
                data_, self.thumbnail_la, self.brief_dataset.title
            )
            qgis.core.QgsApplication.taskManager().addTask(self.thumbnail_loader_task)
        else:
            log(f"Could not fetch thumbnail")

    def handle_dataset_load_start(self):
        self.data_source_widget.toggle_search_controls(False)
        self.data_source_widget.show_message(
            tr("Loading layer..."), add_loading_widget=True
        )
        self.toggle_service_url_buttons(False)

    def handle_layer_load_end(self, clear_message_bar: typing.Optional[bool] = True):
        self.data_source_widget.toggle_search_controls(True)
        self.data_source_widget.toggle_search_buttons()
        self.toggle_service_url_buttons(True)
        if clear_message_bar:
            self.data_source_widget.message_bar.clearWidgets()

    def load_dataset(self, service_type: models.GeonodeService):
        self.handle_dataset_load_start()
        self.dataset_loader_task = LayerLoaderTask(
            self.brief_dataset,
            service_type,
            api_client=self.api_client,
        )
        self.dataset_loader_task.taskCompleted.connect(self.prepare_loaded_layer)
        self.dataset_loader_task.taskTerminated.connect(self.handle_loading_error)
        qgis.core.QgsApplication.taskManager().addTask(self.dataset_loader_task)

    def prepare_loaded_layer(self):
        if self.dataset_loader_task._exception is not None:
            log(self.dataset_loader_task._exception)
        self.layer = self.dataset_loader_task.layer
        self.api_client.dataset_detail_received.connect(self.handle_layer_detail)
        self.api_client.dataset_detail_error_received.connect(self.handle_loading_error)
        self.api_client.style_detail_error_received.connect(self.handle_style_error)
        self.api_client.get_dataset_detail(
            self.brief_dataset, get_style_too=self.layer.dataProvider().name() != "wms"
        )

    def handle_layer_detail(
        self, dataset: typing.Optional[models.Dataset], retrieved_style: bool = False
    ):
        self.api_client.dataset_detail_received.disconnect(self.handle_layer_detail)
        self.layer.setCustomProperty(
            models.DATASET_CUSTOM_PROPERTY_KEY,
            dataset.to_json() if dataset is not None else None,
        )
        current_connection_settings = settings_manager.get_current_connection_settings()
        self.layer.setCustomProperty(
            models.DATASET_CONNECTION_CUSTOM_PROPERTY_KEY,
            str(current_connection_settings.id),
        )
        if ApiClientCapability.LOAD_LAYER_METADATA in self.api_client.capabilities:
            metadata = populate_metadata(self.layer.metadata(), dataset)
            self.layer.setMetadata(metadata)
        can_load_style = models.loading_style_supported(
            self.layer.type(), self.api_client.capabilities
        )

        if dataset.default_style.sld is not None:
            retrieved_style = True

        if can_load_style and retrieved_style:
            error_message = ""
            loaded_sld = self.layer.readSld(dataset.default_style.sld, error_message)
            if not loaded_sld:
                log(f"Could not apply SLD to layer: {error_message}")
        self.add_layer_to_project()

    def handle_loading_error(self):
        message = f"Unable to load layer {self.brief_dataset.title}: {self.dataset_loader_task._exception}"
        self.data_source_widget.show_message(message, level=qgis.core.Qgis.Critical)
        self.handle_layer_load_end(clear_message_bar=False)

    def handle_style_error(self):
        message = f"Unable to retrieve the style of {self.brief_dataset.title}"
        self.data_source_widget.show_message(message, level=qgis.core.Qgis.Critical)
        self.handle_layer_load_end(clear_message_bar=False)

    def add_layer_to_project(self):
        self.api_client.dataset_detail_error_received.disconnect(
            self.handle_loading_error
        )
        self.api_client.style_detail_error_received.disconnect(self.handle_style_error)
        self.project.addMapLayer(self.layer)
        self.handle_layer_load_end()


class ThumbnailLoaderTask(qgis.core.QgsTask):
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
    brief_dataset: models.BriefDataset
    brief_resource: models.BriefDataset
    service_type: models.GeonodeService
    api_client: base.BaseGeonodeClient
    layer: typing.Optional["QgsMapLayer"]
    _exception: typing.Optional[str]

    def __init__(
        self,
        brief_dataset: models.BriefDataset,
        service_type: models.GeonodeService,
        api_client: base.BaseGeonodeClient,
    ):
        """Load a QGIS layer

        This is done in a QgsTask in order to allow the loading of a layer from the
        network to be done in a background thread and not block the main QGIS UI.

        """

        super().__init__()
        self.brief_dataset = brief_dataset
        self.service_type = service_type
        self.api_client = api_client
        self.layer = None
        self._exception = None

    def run(self):
        if self.service_type == models.GeonodeService.OGC_WMS:
            layer = self._load_wms()
        elif self.service_type == models.GeonodeService.OGC_WFS:
            layer = self._load_wfs()
        elif self.service_type == models.GeonodeService.OGC_WCS:
            layer = self._load_wcs()
        else:
            layer = None
            self._exception = f"Unrecognized layer type: {self.service_type!r}"

        result = False
        if layer is not None and layer.isValid():
            self.layer = layer
            result = True
        else:
            layer_error_message_list = layer.error().messageList()
            layer_error = ", ".join(err.message() for err in layer_error_message_list)
            self._exception = layer_error
            log(f"layer errors: {layer_error}")
            provider_error_message_list = layer.dataProvider().error().messageList()
            log(
                f"provider errors: "
                f"{', '.join([err.message() for err in provider_error_message_list])}"
            )
        return result

    def finished(self, result: bool):
        if result:
            # Cloning the layer seems to be required in order to make sure the WMS
            # layers work appropriately - Otherwise we get random crashes when loading
            # WMS layers. This may be related to how the layer is moved from the
            # secondary thread by QgsTaskManager and the layer's ownership.
            self.layer = self.layer.clone()
        else:
            message = (
                f"Error loading layer {self.brief_dataset.title!r} from "
                f"{self.brief_dataset.service_urls[self.service_type]!r}: "
                f"{self._exception}"
            )
            log(message)

    def _load_wms(self) -> qgis.core.QgsMapLayer:
        params = {
            "crs": f"EPSG:{self.brief_dataset.srid.postgisSrid()}",
            "url": self.brief_dataset.service_urls[self.service_type],
            "format": "image/png",
            "layers": self.brief_dataset.name,
            "styles": "",
            "version": "auto",
        }
        if self.api_client.auth_config:
            params["authcfg"] = self.api_client.auth_config
        return qgis.core.QgsRasterLayer(
            urllib.parse.unquote(urllib.parse.urlencode(params)),
            self.brief_dataset.title,
            "wms",
        )

    def _load_wcs(self) -> qgis.core.QgsMapLayer:
        params = {
            "url": self.brief_dataset.service_urls[self.service_type],
            "identifier": self.brief_dataset.name,
            "crs": f"EPSG:{self.brief_dataset.srid.postgisSrid()}",
        }
        if self.api_client.auth_config:
            params["authcfg"] = self.api_client.auth_config
        return qgis.core.QgsRasterLayer(
            urllib.parse.unquote(urllib.parse.urlencode(params)),
            self.brief_dataset.title,
            "wcs",
        )

    def _load_wfs(self) -> qgis.core.QgsMapLayer:
        params = {
            "srsname": f"EPSG:{self.brief_dataset.srid.postgisSrid()}",
            "typename": self.brief_dataset.name,
            "url": self.brief_dataset.service_urls[self.service_type].rstrip("/"),
            "version": self.api_client.wfs_version.value,
        }
        if self.api_client.auth_config:
            params["authcfg"] = self.api_client.auth_config
        uri = " ".join(f"{key}='{value}'" for key, value in params.items())
        return qgis.core.QgsVectorLayer(uri, self.brief_dataset.title, "WFS")
