import typing
import xml.etree.ElementTree as ET
from pathlib import Path
from uuid import UUID

import qgis.core
import qgis.gui

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
from ..utils import (
    log,
)

WidgetUi, _ = loadUiType(Path(__file__).parents[1] / "ui/qgis_geonode_layer_dialog.ui")


class GeonodeMapLayerConfigWidget(qgis.gui.QgsMapLayerConfigWidget, WidgetUi):
    download_style_pb: QtWidgets.QPushButton
    upload_style_pb: QtWidgets.QPushButton
    open_detail_url_pb: QtWidgets.QPushButton
    open_link_url_pb: QtWidgets.QPushButton
    message_bar: qgis.gui.QgsMessageBar

    network_task: typing.Optional[network.NetworkRequestTask]
    _apply_geonode_style: bool

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

    @property
    def api_client(self) -> typing.Optional[base.BaseGeonodeClient]:
        connection_settings = self.connection_settings
        if connection_settings is not None:
            result = get_geonode_client(connection_settings)
        else:
            result = None
        return result

    def __init__(self, layer, canvas, parent):
        super().__init__(layer, canvas, parent)
        self.setupUi(self)
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
        self.network_task = None
        self._apply_geonode_style = False
        self.layer = layer
        self._toggle_style_controls(enabled=False)
        self._toggle_link_controls(enabled=False)
        if self.layer.customProperty(models.DATASET_CUSTOM_PROPERTY_KEY) is not None:
            # this layer came from GeoNode
            self.download_style_pb.clicked.connect(self.download_style)
            self.upload_style_pb.clicked.connect(self.upload_style)
            self.open_detail_url_pb.clicked.connect(self.open_detail_url)
            self.open_link_url_pb.clicked.connect(self.open_link_url)
            self._toggle_style_controls(enabled=True)
            self._toggle_link_controls(enabled=True)
        else:  # this is not a GeoNode layer
            pass

    def apply(self):
        self.message_bar.clearWidgets()
        if self._apply_geonode_style:
            self._apply_sld()
            self._apply_geonode_style = False

    def get_dataset(self) -> typing.Optional[models.Dataset]:
        serialized_dataset = self.layer.customProperty(
            models.DATASET_CUSTOM_PROPERTY_KEY
        )
        if serialized_dataset is not None:
            result = models.Dataset.from_json(
                self.layer.customProperty(models.DATASET_CUSTOM_PROPERTY_KEY)
            )
        else:
            result = None
        return result

    def update_dataset(self, new_dataset: models.Dataset):
        serialized = new_dataset.to_json()
        self.layer.setCustomProperty(models.DATASET_CUSTOM_PROPERTY_KEY, serialized)

    def download_style(self):
        dataset = self.get_dataset()
        self.network_task = network.NetworkRequestTask(
            [network.RequestToPerform(QtCore.QUrl(dataset.default_style.sld_url))],
            self.connection_settings.auth_config,
            network_task_timeout=self.api_client.network_requests_timeout,
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
                self.connection_settings.auth_config,
                network_task_timeout=self.api_client.network_requests_timeout,
                description="Upload dataset style to GeoNode",
            )
            qgis.core.QgsApplication.taskManager().addTask(self.network_task)
            self.network_task.task_done.connect(self.handle_style_uploaded)
            self._toggle_style_controls(enabled=False)
            self._show_message(message="Uploading style...", add_loading_widget=True)

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
        new_serialized = ET.tostring(new_root, encoding="unicode", xml_declaration=True)
        content_type = "application/vnd.ogc.sld+xml"
        return new_serialized, content_type

    def handle_style_uploaded(self, task_result: bool):
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

    def open_detail_url(self) -> None:
        dataset = self.get_dataset()
        QtGui.QDesktopServices.openUrl(QtCore.QUrl(dataset.detail_url))

    def open_link_url(self) -> None:
        dataset = self.get_dataset()
        QtGui.QDesktopServices.openUrl(QtCore.QUrl(dataset.link))

    def _apply_sld(self) -> None:
        dataset = self.get_dataset()
        sld_load_error_msg = ""
        sld_load_result = self.layer.readSld(
            dataset.default_style.sld, sld_load_error_msg
        )
        if sld_load_result:
            layer_properties_dialog = self._get_layer_properties_dialog()
            layer_properties_dialog.syncToLayer()
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

    def _get_layer_properties_dialog(self):
        # FIXME: This is a very hacky way to get the layer properties dialog, and it
        #  may not even work for layers that are not vector, but I've not been able
        #  to find a more elegant way to retrieve it yet
        return self.parent().parent().parent().parent()

    def _toggle_link_controls(self, enabled: bool) -> None:
        widgets = (
            self.open_detail_url_pb,
            self.open_link_url_pb,
        )
        for widget in widgets:
            widget.setEnabled(enabled)

    def _toggle_style_controls(self, enabled: bool) -> None:
        if enabled:
            widgets = []
            if self.connection_settings is not None:
                can_load_style = models.loading_style_supported(
                    self.layer.type(), self.api_client.capabilities
                )
                can_modify_style = models.modifying_style_supported(
                    self.layer.type(), self.api_client.capabilities
                )
                dataset = self.get_dataset()
                has_style_url = dataset.default_style.sld_url is not None
                if can_load_style and has_style_url:
                    widgets.append(self.download_style_pb)
                if can_modify_style and has_style_url:
                    widgets.append(self.upload_style_pb)
        else:
            widgets = [
                self.upload_style_pb,
                self.download_style_pb,
            ]
        for widget in widgets:
            widget.setEnabled(enabled)
