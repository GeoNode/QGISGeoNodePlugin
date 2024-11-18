import json
import typing
import xml.etree.ElementTree as ET
from pathlib import Path
from uuid import UUID

import qgis.core
import qgis.gui
import qgis.utils

from qgis.PyQt import (
    QtCore,
    QtGui,
    QtWidgets,
    QtXml,
)
from qgis.PyQt.uic import loadUiType

from .. import (
    conf,
    network,
    styles,
    utils,
)
from ..apiclient import (
    base,
    get_geonode_client,
    models,
)
from ..metadata import populate_metadata
from ..utils import (
    log,
)

WidgetUi, _ = loadUiType(Path(__file__).parents[1] / "ui/qgis_geonode_layer_dialog.ui")


class GeonodeMapLayerConfigWidget(qgis.gui.QgsMapLayerConfigWidget, WidgetUi):
    style_gb: qgis.gui.QgsCollapsibleGroupBox
    download_style_pb: QtWidgets.QPushButton
    upload_style_pb: QtWidgets.QPushButton
    metadata_gb: qgis.gui.QgsCollapsibleGroupBox
    download_metadata_pb: QtWidgets.QPushButton
    upload_metadata_pb: QtWidgets.QPushButton
    links_gb: qgis.gui.QgsCollapsibleGroupBox
    open_detail_url_pb: QtWidgets.QPushButton
    open_link_url_pb: QtWidgets.QPushButton
    upload_gb: qgis.gui.QgsCollapsibleGroupBox
    geonode_connection_cb: QtWidgets.QComboBox
    public_access_chb: QtWidgets.QCheckBox
    upload_layer_pb: QtWidgets.QPushButton
    message_bar: qgis.gui.QgsMessageBar

    network_task: typing.Optional[network.NetworkRequestTask]
    _apply_geonode_style: bool
    _apply_geonode_metadata: bool
    _layer_upload_api_client: typing.Optional[base.BaseGeonodeClient]
    _api_client: typing.Optional[base.BaseGeonodeClient]

    @property
    def connection_settings(self) -> typing.Optional[conf.ConnectionSettings]:
        connection_settings_id = self.layer.customProperty(
            models.DATASET_CONNECTION_CUSTOM_PROPERTY_KEY
        )
        if connection_settings_id is not None:
            result = conf.settings_manager.get_connection_settings(
                UUID(connection_settings_id)
            )
        else:
            result = None
        return result

    def __init__(self, layer, canvas, parent):
        super().__init__(layer, canvas, parent)
        self.setupUi(self)
        self.setProperty("helpPage", conf.plugin_metadata.get("help_page"))
        self.open_detail_url_pb.setIcon(
            QtGui.QIcon(":/plugins/qgis_geonode/mIconGeonode.svg")
        )
        self.download_style_pb.setIcon(
            QtGui.QIcon(":/images/themes/default/mActionRefresh.svg")
        )
        self.upload_style_pb.setIcon(
            QtGui.QIcon(":/images/themes/default/mActionFileSave.svg")
        )
        self.message_bar = qgis.gui.QgsMessageBar()
        self.message_bar.setSizePolicy(
            QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Fixed
        )
        self.layout().insertWidget(0, self.message_bar)
        self.public_access_chb.setChecked(True)
        self.network_task = None
        self._apply_geonode_style = False
        self._apply_geonode_metadata = False
        self.layer = layer
        self._layer_upload_api_client = None
        if self.connection_settings is not None:
            self._api_client = get_geonode_client(self.connection_settings)
        else:
            self._api_client = None
        self.upload_layer_pb.clicked.connect(self.upload_layer_to_geonode)
        suitable_connections = self._get_suitable_upload_connections()
        if len(suitable_connections) > 0:
            self._populate_geonode_connection_combo_box(suitable_connections)
            self._toggle_upload_controls(enabled=True)
        else:
            self._toggle_upload_controls(enabled=False)
        self._toggle_style_controls(enabled=False)
        self._toggle_link_controls(enabled=False)
        self._toggle_metadata_controls(enabled=False)
        if self.layer.customProperty(models.DATASET_CUSTOM_PROPERTY_KEY) is not None:
            # this layer came from GeoNode
            self.download_style_pb.clicked.connect(self.download_style)
            self.upload_style_pb.clicked.connect(self.upload_style)
            self.open_detail_url_pb.clicked.connect(self.open_detail_url)
            self.open_link_url_pb.clicked.connect(self.open_link_url)
            self.download_metadata_pb.clicked.connect(self.download_metadata)
            self.upload_metadata_pb.clicked.connect(self.upload_metadata)
            self._toggle_style_controls(enabled=True)
            self._toggle_link_controls(enabled=True)
            self._toggle_metadata_controls(enabled=True)
        else:  # this is not a GeoNode layer
            pass

    def apply(self):
        self.message_bar.clearWidgets()
        if self._apply_geonode_style:
            self._apply_sld()
            self._apply_geonode_style = False
        if self._apply_geonode_metadata:
            self._apply_metadata()
            self._apply_geonode_metadata = False

    def get_dataset(self) -> typing.Optional[models.Dataset]:
        serialized_dataset = self.layer.customProperty(
            models.DATASET_CUSTOM_PROPERTY_KEY
        )
        if serialized_dataset is not None:
            result = models.Dataset.from_json(serialized_dataset)
        else:
            result = None
        return result

    def update_dataset(self, new_dataset: models.Dataset) -> None:
        serialized = new_dataset.to_json()
        self.layer.setCustomProperty(models.DATASET_CUSTOM_PROPERTY_KEY, serialized)

    def download_style(self):
        dataset = self.get_dataset()
        self.network_task = network.NetworkRequestTask(
            [network.RequestToPerform(QtCore.QUrl(dataset.default_style.sld_url))],
            self._api_client.network_requests_timeout,
            self.connection_settings.auth_config,
            description="Get dataset style",
        )
        self.network_task.task_done.connect(self.handle_style_downloaded)
        self._toggle_style_controls(enabled=False)
        self._show_message(message="Retrieving style...", add_loading_widget=True)
        qgis.core.QgsApplication.taskManager().addTask(self.network_task)

    def handle_style_downloaded(self, task_result: bool):
        self._toggle_style_controls(enabled=True)
        if task_result:
            sld_named_layer, error_message = styles.get_usable_sld(
                self.network_task.response_contents[0]
            )
            if sld_named_layer is not None:
                dataset = self.get_dataset()
                dataset.default_style.sld = sld_named_layer
                self.update_dataset(dataset)
                self._apply_geonode_style = True
                self.apply()
            else:
                self._show_message(
                    message=(
                        f"Unable to download and parse SLD style from remote "
                        f"GeoNode: {error_message}"
                    ),
                    level=qgis.core.Qgis.Warning,
                )
        else:
            self._show_message(
                "Unable to retrieve GeoNode style", level=qgis.core.Qgis.Warning
            )

    def upload_style(self):
        self.apply()
        sld_data = self._prepare_style_for_upload()
        if sld_data is not None:
            serialized_sld, content_type = sld_data
            dataset = self.get_dataset()
            self.network_task = network.NetworkRequestTask(
                [
                    network.RequestToPerform(
                        QtCore.QUrl(dataset.default_style.sld_url),
                        method=network.HttpMethod.PUT,
                        payload=serialized_sld,
                        content_type=content_type,
                    )
                ],
                self._api_client.network_requests_timeout,
                self.connection_settings.auth_config,
                description="Upload dataset style to GeoNode",
            )
            self.network_task.task_done.connect(self.handle_style_uploaded)
            self._toggle_style_controls(enabled=False)
            self._show_message(message="Uploading style...", add_loading_widget=True)
            qgis.core.QgsApplication.taskManager().addTask(self.network_task)

    def _prepare_style_for_upload(self) -> typing.Optional[typing.Tuple[str, str]]:
        doc = QtXml.QDomDocument()
        error_message = ""
        self.layer.exportSldStyle(doc, error_message)
        log(f"exportSldStyle error_message: {error_message!r}")
        if error_message == "":
            serialized_sld = doc.toString(0)
            if self.layer.type() == qgis.core.QgsMapLayerType.VectorLayer:
                # For vector layers QGIS exports SLD version 1.1.0.
                #
                # According to GeoServer docs here:
                #
                #     https://docs.geoserver.org/stable/en/user/rest/api/styles.html#styles-format
                #
                # updating an SLD v1.1.0 requires a content-type of
                # `application/vnd.ogc.se+xml`. I've not been able to find mention to
                # this content-type in the OGC standards for Symbology (SE v1.1.0)
                # nor Styled Layer Descriptor Profile for WMS v1.1.0 though (I
                # probably missed it). However, it seems to work OK
                # with GeoNode+GeoServer.
                result = (serialized_sld, "application/vnd.ogc.se+xml")
            elif self.layer.type() == qgis.core.QgsMapLayerType.RasterLayer:
                result = self._prepare_raster_style_for_upload(serialized_sld)
            else:
                raise NotImplementedError("Unknown layer type")
        else:
            result = None
        return result

    def _prepare_raster_style_for_upload(
        self, sld_generated_by_qgis: str
    ) -> typing.Tuple[str, str]:
        """Prepare raster SLD for uploading to remote GeoNode.

        For raster layers, QGIS exports SLD version 1.0.0 with an element of
        `sld:UserLayer`. We modify to `sld:NamedLayer` and adjust the content-type
        accordingly.

        """

        nsmap = {
            "sld": "http://www.opengis.net/sld",
            "ogc": "http://www.opengis.net/ogc",
            "xlink": "http://www.w3.org/1999/xlink",
            "se": "http://www.opengis.net/se",
        }
        old_root = ET.fromstring(sld_generated_by_qgis)
        old_user_style_el = old_root.find(f".//{{{nsmap['sld']}}}UserStyle")
        old_name_el = old_user_style_el.find(f"./{{{nsmap['sld']}}}Name")
        new_root = ET.Element(f"{{{nsmap['sld']}}}StyledLayerDescriptor")
        new_root.set("version", "1.0.0")
        named_layer_el = ET.SubElement(new_root, f"{{{nsmap['sld']}}}NamedLayer")
        name_el = ET.SubElement(named_layer_el, f"{{{nsmap['sld']}}}Name")
        name_el.text = old_name_el.text
        named_layer_el.append(old_user_style_el)
        new_serialized = ET.tostring(new_root, encoding="unicode")
        content_type = "application/vnd.ogc.sld+xml"
        return new_serialized, content_type

    def handle_style_uploaded(self, task_result: bool) -> None:
        self._toggle_style_controls(enabled=True)
        if task_result:
            parsed_reply = self.network_task.response_contents[0]
            if parsed_reply is not None:
                if parsed_reply.http_status_code == 200:
                    self._show_message("Style uploaded successfully!")
                else:
                    error_message_parts = [
                        "Could not upload style",
                        parsed_reply.qt_error,
                        f"HTTP {parsed_reply.http_status_code}",
                        parsed_reply.http_status_reason,
                    ]
                    error_message = " - ".join(i for i in error_message_parts if i)
                    self._show_message(error_message, level=qgis.core.Qgis.Warning)
        else:
            self._show_message(
                f"Could not upload style",
                level=qgis.core.Qgis.Warning,
            )

    def download_metadata(self) -> None:
        """Initiate download of metadata from the remote GeoNode"""

        self._api_client.dataset_detail_received.connect(
            self.handle_metadata_downloaded
        )
        self._api_client.dataset_detail_error_received.connect(
            self.handle_metadata_downloaded
        )
        self._toggle_metadata_controls(enabled=False)
        self._show_message("Retrieving metadata...", add_loading_widget=True)
        dataset = self.get_dataset()
        self._api_client.get_dataset_detail(dataset, get_style_too=False)

    def handle_metadata_download_error(self) -> None:
        log("inside handle_metadata_download_error")

    def handle_metadata_downloaded(self, downloaded_dataset: models.Dataset) -> None:
        self._toggle_metadata_controls(enabled=True)
        self.update_dataset(downloaded_dataset)
        self._apply_geonode_metadata = True
        self.apply()

    def _apply_metadata(self) -> None:
        dataset = self.get_dataset()
        updated_metadata = populate_metadata(self.layer.metadata(), dataset)
        self.layer.setMetadata(updated_metadata)
        # sync layer properties with the reloaded SLD and/or Metadata from GeoNode
        self.sync_layer_properties()

    # FIXME: rather use the api_client to perform the metadata upload
    def upload_metadata(self) -> None:
        self.apply()
        current_metadata = self.layer.metadata()
        self.network_task = network.NetworkRequestTask(
            [
                network.RequestToPerform(
                    QtCore.QUrl(self.get_dataset().link),
                    method=network.HttpMethod.PATCH,
                    payload=json.dumps(
                        {
                            "title": current_metadata.title(),
                            "abstract": current_metadata.abstract(),
                        }
                    ),
                    content_type="application/json",
                )
            ],
            self._api_client.network_requests_timeout,
            self._api_client.auth_config,
            description="Upload metadata",
        )
        self.network_task.task_done.connect(self.handle_metadata_uploaded)
        self._toggle_metadata_controls(enabled=False)
        self._show_message(message="Uploading metadata...", add_loading_widget=True)
        qgis.core.QgsApplication.taskManager().addTask(self.network_task)

    def handle_metadata_uploaded(self, task_result: bool) -> None:
        self._toggle_metadata_controls(enabled=True)
        if task_result:
            parsed_reply = self.network_task.response_contents[0]
            if parsed_reply is not None:
                if parsed_reply.http_status_code == 200:
                    self._show_message("Metadata uploaded successfully!")
                else:
                    error_message_parts = [
                        "Could not upload metadata",
                        parsed_reply.qt_error,
                        f"HTTP {parsed_reply.http_status_code}",
                        parsed_reply.http_status_reason,
                    ]
                    error_message = " - ".join(i for i in error_message_parts if i)
                    self._show_message(error_message, level=qgis.core.Qgis.Warning)
            else:
                self._show_message(
                    "Could not upload metadata", level=qgis.core.Qgis.Warning
                )
        else:
            self._show_message(
                "Could not upload metadata", level=qgis.core.Qgis.Warning
            )

    def open_detail_url(self) -> None:
        dataset = self.get_dataset()
        QtGui.QDesktopServices.openUrl(QtCore.QUrl(dataset.detail_url))

    def open_link_url(self) -> None:
        dataset = self.get_dataset()
        QtGui.QDesktopServices.openUrl(QtCore.QUrl(dataset.link))

    def upload_layer_to_geonode(self) -> None:
        self._toggle_upload_controls(enabled=False)
        self._show_message("Uploading layer to GeoNode...", add_loading_widget=True)
        connection_settings: conf.ConnectionSettings = (
            self.geonode_connection_cb.currentData()
        )
        self._layer_upload_api_client = get_geonode_client(connection_settings)
        self._layer_upload_api_client.dataset_uploaded.connect(
            self.handle_layer_uploaded
        )
        self._layer_upload_api_client.dataset_upload_error_received.connect(
            self.handle_layer_upload_error
        )
        self._layer_upload_api_client.upload_layer(
            self.layer, allow_public_access=self.public_access_chb.isChecked()
        )

    def handle_layer_uploaded(self):
        self._toggle_upload_controls(enabled=True)
        self._show_message("Layer uploaded successfully!")

    def handle_layer_upload_error(self, *args):
        self._toggle_upload_controls(enabled=True)
        self._show_message(
            " - ".join(str(i) for i in args), level=qgis.core.Qgis.Critical
        )
        self._layer_upload_api_client = None

    def _get_suitable_upload_connections(self) -> typing.List[conf.ConnectionSettings]:
        result = []
        for connection_settings in conf.settings_manager.list_connections():
            client: typing.Optional[base.BaseGeonodeClient] = get_geonode_client(
                connection_settings
            )
            if client is not None:
                target_capability = {
                    qgis.core.QgsMapLayerType.VectorLayer: models.ApiClientCapability.UPLOAD_VECTOR_LAYER,
                    qgis.core.QgsMapLayerType.RasterLayer: models.ApiClientCapability.UPLOAD_RASTER_LAYER,
                }[self.layer.type()]
                if target_capability in client.capabilities:
                    result.append(connection_settings)
        return result

    def _populate_geonode_connection_combo_box(
        self, suitable_connections: typing.List[conf.ConnectionSettings]
    ) -> None:
        for connection in suitable_connections:
            self.geonode_connection_cb.addItem(connection.name, connection)

    def _apply_sld(self) -> None:
        dataset = self.get_dataset()
        sld_load_error_msg = ""
        sld_load_result = self.layer.readSld(
            dataset.default_style.sld, sld_load_error_msg
        )
        if sld_load_result:
            self.sync_layer_properties()
        else:
            self._show_message(
                message=f"Could not load GeoNode style: {sld_load_error_msg}",
                level=qgis.core.Qgis.Warning,
            )

    def _show_message(
        self,
        message: str,
        level: typing.Optional[qgis.core.Qgis.MessageLevel] = qgis.core.Qgis.Info,
        add_loading_widget: bool = False,
    ) -> None:
        utils.show_message(self.message_bar, message, level, add_loading_widget)

    def find_parent_by_type(self, obj, target_type):
        # Find the desired object by type
        # from a structure: self.parent().parent()...
        current_obj = obj
        while current_obj is not None:
            if isinstance(current_obj, target_type):
                return current_obj
            if hasattr(current_obj, "parent"):
                current_obj = current_obj.parent()
            else:
                break
        return None

    def sync_layer_properties(self):
        # get layer properties dialog
        # We need to find QDialog object from a structure like:
        # self.parent().parent()...
        properties_dialog = self.find_parent_by_type(self, QtWidgets.QDialog)

        if properties_dialog is not None:
            # Sync GeoNode's SLD or / and metadata with the layer properties dialog
            properties_dialog.syncToLayer()
        else:
            self._show_message(
                "The corresponding layer properties from GeoNode cannot be loaded correctly...",
                level=qgis.core.Qgis.Critical,
            )

    def _toggle_link_controls(self, enabled: bool) -> None:
        self.links_gb.setEnabled(enabled)

    def _toggle_style_controls(self, enabled: bool) -> None:
        widgets = []
        if enabled and self.connection_settings is not None:
            can_load_style = models.loading_style_supported(
                self.layer.type(), self._api_client.capabilities
            )
            log(f"can_load_style: {can_load_style}")
            can_modify_style = models.modifying_style_supported(
                self.layer.type(), self._api_client.capabilities
            )
            dataset = self.get_dataset()
            allowed_to_modify = (
                models.GeonodePermission.CHANGE_DATASET_STYLE in dataset.permissions
            )
            is_service = self.layer.dataProvider().name().lower() in ("wfs", "wcs")
            has_style_url = dataset.default_style.sld_url is not None
            if can_load_style and has_style_url and is_service:
                widgets.append(self.download_style_pb)
            else:
                self.download_style_pb.setEnabled(False)
            if allowed_to_modify and can_modify_style and has_style_url and is_service:
                widgets.append(self.upload_style_pb)
            else:
                self.upload_style_pb.setEnabled(False)
            if len(widgets) > 0:
                widgets.append(self.style_gb)
        else:
            widgets.append(self.style_gb)
        for widget in widgets:
            widget.setEnabled(enabled)

    def _toggle_metadata_controls(self, enabled: bool) -> None:
        widgets = []
        if enabled and self.connection_settings is not None:
            can_load_metadata = (
                models.ApiClientCapability.LOAD_LAYER_METADATA
                in self._api_client.capabilities
            )
            if can_load_metadata:
                widgets.append(self.download_metadata_pb)
            else:
                self.download_metadata_pb.setEnabled(False)
            can_modify_metadata = (
                models.ApiClientCapability.MODIFY_LAYER_METADATA
                in self._api_client.capabilities
            )
            dataset = self.get_dataset()
            allowed_to_modify = (
                models.GeonodePermission.CHANGE_RESOURCEBASE_METADATA
                in dataset.permissions
            )
            log(f"allowed_to_modify metadata: {allowed_to_modify}")
            if can_modify_metadata and allowed_to_modify:
                widgets.append(self.upload_metadata_pb)
            else:
                self.upload_metadata_pb.setEnabled(False)
            if len(widgets) > 0:
                widgets.append(self.metadata_gb)
        else:
            widgets.append(self.metadata_gb)
        log(f"widgets:{[w.__class__.__name__ for w in widgets]}")
        for widget in widgets:
            widget.setEnabled(enabled)

    def _toggle_upload_controls(self, enabled: bool) -> None:
        self.upload_gb.setEnabled(enabled)
