import typing
from functools import partial
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
    available_styles_cb: QtWidgets.QComboBox
    apply_style_pb: QtWidgets.QPushButton
    network_task: typing.Optional[network.MultipleNetworkFetcherTask]
    _retrieved_slds: typing.Dict[str, typing.Optional[QtXml.QDomElement]]
    _sld_to_be_applied: typing.Optional[str]

    def __init__(self, layer, canvas, parent):
        super().__init__(layer, canvas, parent)
        self.setupUi(self)
        self.message_bar = qgis.gui.QgsMessageBar()
        self.message_bar.setSizePolicy(
            QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Fixed
        )
        self.layout().insertWidget(0, self.message_bar)
        self.network_task = None
        self._retrieved_slds = {}
        self._sld_to_be_applied = None
        self.layer = layer
        serialized_dataset = self.layer.customProperty(
            models.DATASET_CUSTOM_PROPERTY_KEY
        )
        if serialized_dataset is not None:
            self._populate_styles_combobox()
        self.apply_style_pb.clicked.connect(self._trigger_apply_selected_style)

    def apply(self):
        self.message_bar.pushMessage("This is the apply slot")
        self._apply_sld()
        self._sld_to_be_applied = None

    def shouldTriggerLayerRepaint(self):
        return True

    def _trigger_apply_selected_style(self):
        selected_style = self.available_styles_cb.currentData()
        log(f"selected_style: {selected_style}")

        if selected_style["name"] in self._retrieved_slds.keys():
            # we already have it locally, no need to re-download
            self._sld_to_be_applied = selected_style["name"]
            self._apply_sld()
        else:  # lets download it
            connection_settings_id = self.layer.customProperty(
                models.DATASET_CONNECTION_CUSTOM_PROPERTY_KEY
            )
            connection_settings = conf.settings_manager.get_connection_settings(
                UUID(connection_settings_id)
            )
            self.network_task = network.MultipleNetworkFetcherTask(
                [network.RequestToPerform(QtCore.QUrl(selected_style["sld_url"]))],
                connection_settings.auth_config,
            )
            self.network_task.all_finished.connect(
                partial(self._handle_sld_style_downloaded, selected_style["name"])
            )
            qgis.core.QgsApplication.taskManager().addTask(self.network_task)

    def _handle_sld_style_downloaded(self, style_name, task_result: bool):
        if task_result:
            usable_sld = styles.get_usable_sld(self.network_task.response_contents[0])
            if usable_sld is not None:
                self.message_bar.pushMessage(
                    "Applied downloaded SLD style from remote GeoNode"
                )
                self._retrieved_slds[style_name] = usable_sld
                self._sld_to_be_applied = style_name
                self.apply()
            else:
                self.message_bar.pushMessage(
                    "Unable to apply downloaded SLD style from remote GeoNode"
                )
        else:
            self.message_bar.pushMessage("Unable to retrieve GeoNode style")
            self._retrieved_slds[style_name] = None

    def _populate_styles_combobox(self):
        dataset = models.Dataset.from_json(
            self.layer.customProperty(models.DATASET_CUSTOM_PROPERTY_KEY)
        )
        for style in dataset.styles:
            if style.get("sld_url") or None is not None:
                self.available_styles_cb.addItem(style["name"], style)

    def _apply_sld(self):
        sld = self._retrieved_slds.get(self._sld_to_be_applied)
        if sld is not None:
            sld_load_error_msg = ""
            sld_load_result = self.layer.readSld(sld, sld_load_error_msg)
            log(
                f"sld_load_result: {sld_load_result} - seld_load_error_msg: {sld_load_error_msg}"
            )
            if sld_load_result:
                layer_properties_dialog = self._get_layer_properties_dialog()
                layer_properties_dialog.syncToLayer()
                # self.parent().parent().parent().parent().syncToLayer()

    def _get_layer_properties_dialog(self):
        # FIXME: This is a very hacky way to get the layer properties dialog, and it may not
        # even work for layers that are not vector, but I've not been able to find a
        # more elegant way to retrieve it yet
        return self.parent().parent().parent().parent()
