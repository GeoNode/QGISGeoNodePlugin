import json
import typing
from pathlib import Path
from uuid import UUID

import qgis.core
import qgis.gui

from qgis.PyQt import (
    QtCore,
    QtWidgets,
    QtXml,
)
from qgis.PyQt.uic import loadUiType

from .. import (
    conf,
    network,
    styles,
)
from ..apiclient import models
from ..utils import (
    log,
)

WidgetUi, _ = loadUiType(Path(__file__).parents[1] / "ui/qgis_geonode_layer_dialog.ui")


class GeonodeMapLayerConfigWidget(qgis.gui.QgsMapLayerConfigWidget, WidgetUi):
    download_style_pb: QtWidgets.QPushButton
    upload_style_pb: QtWidgets.QPushButton

    network_task: typing.Optional[network.MultipleNetworkFetcherTask]
    _apply_geonode_style: bool

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
        self.message_bar = qgis.gui.QgsMessageBar()
        self.message_bar.setSizePolicy(
            QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Fixed
        )
        self.layout().insertWidget(0, self.message_bar)
        self.network_task = None
        self._apply_geonode_style = False
        self.layer = layer
        if self.layer.customProperty(models.DATASET_CUSTOM_PROPERTY_KEY) is not None:
            # this layer came from GeoNode
            # TODO: check if the API client has the relevant capabilities before enabling the GUI controls
            self._toggle_style_controls(enabled=True)
            self.download_style_pb.clicked.connect(self.download_style)
            self.upload_style_pb.clicked.connect(self.upload_style)
        else:
            pass  # this is not a GeoNode layer, disable widgets

    # def shouldTriggerLayerRepaint(self):
    #     return True

    def apply(self):
        self.message_bar.clearWidgets()
        self.message_bar.pushMessage(
            f"This is the apply slot, apply style: {self._apply_geonode_style}"
        )
        log(f"apply style: {self._apply_geonode_style}")
        if self._apply_geonode_style:
            self._apply_sld()
            self._apply_geonode_style = False

    def download_style(self):
        dataset = self.get_dataset()
        self.network_task = network.MultipleNetworkFetcherTask(
            [network.RequestToPerform(QtCore.QUrl(dataset.default_style.sld_url))],
            self.connection_settings.auth_config,
        )
        self.network_task.all_finished.connect(self.handle_style_downloaded)
        self._toggle_style_controls(enabled=False)
        progress_bar = QtWidgets.QProgressBar()
        progress_bar.setMinimum(0)
        progress_bar.setMaximum(0)
        self.message_bar.pushWidget(progress_bar)
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
                self.message_bar.pushMessage(
                    f"Unable to download and parse SLD style from "
                    f"remote GeoNode: {error_message}"
                )
        else:
            self.message_bar.pushMessage("Unable to retrieve GeoNode style")

    def upload_style(self):
        self.apply()
        doc = QtXml.QDomDocument()
        error_message = ""
        self.layer.exportSldStyle(doc, error_message)
        log(f"exportSldStyle error_message: {error_message!r}")
        if error_message == "":
            dataset = self.get_dataset()
            self.network_task = network.MultipleNetworkFetcherTask(
                [
                    network.RequestToPerform(
                        QtCore.QUrl(dataset.default_style.sld_url),
                        payload=json.dumps(doc),
                    )
                ],
                self.connection_settings.auth_config,
            )

    def _apply_sld(self):
        dataset = self.get_dataset()
        with open("/home/ricardo/Desktop/qgis_geonode_tests/test_sld.sld", "w") as fh:
            doc = dataset.default_style.sld.ownerDocument()
            fh.write(doc.toString())

        sld_load_error_msg = ""
        sld_load_result = self.layer.readSld(
            dataset.default_style.sld, sld_load_error_msg
        )
        log(
            f"sld_load_result: {sld_load_result} - sld_load_error_msg: {sld_load_error_msg}"
        )
        if sld_load_result:
            layer_properties_dialog = self._get_layer_properties_dialog()
            layer_properties_dialog.syncToLayer()

    def _get_layer_properties_dialog(self):
        # FIXME: This is a very hacky way to get the layer properties dialog, and it
        #  may not even work for layers that are not vector, but I've not been able
        #  to find a more elegant way to retrieve it yet
        return self.parent().parent().parent().parent()

    def _toggle_style_controls(self, enabled: bool):
        widgets = (
            self.upload_style_pb,
            self.download_style_pb,
        )
        for widget in widgets:
            widget.setEnabled(enabled)
