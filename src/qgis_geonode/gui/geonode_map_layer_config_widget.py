import typing
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

    network_task: typing.Optional[network.AnotherNetworkRequestTask]
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
        self.network_task = network.AnotherNetworkRequestTask(
            [network.RequestToPerform(QtCore.QUrl(dataset.default_style.sld_url))],
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
        doc = QtXml.QDomDocument()
        error_message = ""
        self.layer.exportSldStyle(doc, error_message)
        log(f"exportSldStyle error_message: {error_message!r}")
        # QGIS exports SLD version 1.1.0. According to GeoServer docs here:
        #
        #     https://docs.geoserver.org/stable/en/user/rest/api/styles.html#styles-format
        #
        # updating an SLD v1.1.0 requires a content-type of application/vnd.ogc.se+xml
        # I've not been able to find mention to this content-type in the OGC standards
        # for Symbology (SE v1.1.0) nor Styled Layer Descriptor Profile for WMS v1.1.0
        # though. However, it seems to work OK with GeoNode+GeoServer.
        if error_message == "":
            dataset = self.get_dataset()
            self.network_task = network.AnotherNetworkRequestTask(
                [
                    network.RequestToPerform(
                        QtCore.QUrl(dataset.default_style.sld_url),
                        method=network.HttpMethod.PUT,
                        payload=doc.toString(0),
                        content_type="application/vnd.ogc.se+xml",
                    )
                ],
                self.connection_settings.auth_config,
            )
            qgis.core.QgsApplication.taskManager().addTask(self.network_task)
            self.network_task.task_done.connect(self.handle_style_uploaded)
            self._toggle_style_controls(enabled=False)
            self._show_message(message="Uploading style...", add_loading_widget=True)

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
                    # if parsed_reply.qt_error:
                    #     error_message += f" - {parsed_reply.qt_error}"
                    # error_message += f" - HTTP {parsed_reply.http_status_code}"
                    # if parsed_reply.http_status_reason:
                    #     error_message += f" - {parsed_reply.http_status_reason}"
                    self._show_message(error_message, level=qgis.core.Qgis.Warning)
        else:
            self._show_message(
                f"Could not upload style: {self.network_task._exceptions_raised}",
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
        message: typing.Optional[str] = None,
        widget: typing.Optional[QtWidgets.QWidget] = None,
        level: typing.Optional[qgis.core.Qgis.MessageLevel] = qgis.core.Qgis.Info,
        add_loading_widget: bool = False,
    ) -> None:
        self.message_bar.clearWidgets()
        if message is not None:
            self.message_bar.pushMessage(str(message), level=level)
        if widget is not None:
            self.message_bar.pushWidget(widget, level=level)
        if add_loading_widget:
            progress_bar = QtWidgets.QProgressBar()
            progress_bar.setMinimum(0)
            progress_bar.setMaximum(0)
            self.message_bar.pushWidget(progress_bar)

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
                api_client: base.BaseGeonodeClient = get_geonode_client(
                    self.connection_settings
                )
                can_load_style = models.loading_style_supported(
                    self.layer.type(), api_client.capabilities
                )
                can_modify_style = models.modifying_style_supported(
                    self.layer.type(), api_client.capabilities
                )
                if can_load_style:
                    widgets.append(self.download_style_pb)
                if can_modify_style:
                    widgets.append(self.upload_style_pb)
        else:
            widgets = [
                self.upload_style_pb,
                self.download_style_pb,
            ]
        for widget in widgets:
            widget.setEnabled(enabled)
