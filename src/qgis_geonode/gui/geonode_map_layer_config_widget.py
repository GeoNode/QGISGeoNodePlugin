import json
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

    download_style_pb: QtWidgets.QPushButton
    upload_style_pb: QtWidgets.QPushButton

    network_task: typing.Optional[network.MultipleNetworkFetcherTask]
    _style_to_be_applied: typing.Optional[models.BriefGeonodeStyle]

    @property
    def dataset(self) -> typing.Optional[models.Dataset]:
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
        self._style_to_be_applied = None
        self.layer = layer
        serialized_dataset = self.layer.customProperty(
            models.DATASET_CUSTOM_PROPERTY_KEY
        )
        if serialized_dataset is not None:
            pass
            # this layer came from GeoNode
            # self.apply_style_pb.clicked.connect(self._trigger_apply_selected_style)
            # self._populate_styles_combobox()
        else:
            pass  # this is not a GeoNode layer, disable widgets

    def apply(self):
        self.message_bar.pushMessage("This is the apply slot")
        if self._style_to_be_applied is not None:
            self._apply_sld()
            self._style_to_be_applied = None

    def download_style(self):
        self.network_task = network.MultipleNetworkFetcherTask(
            [network.RequestToPerform(QtCore.QUrl(self.dataset.default_style.sld_url))],
            self.connection_settings.auth_config,
        )
        self.network_task.all_finished.connect(self._handle_sld_downloaded)
        qgis.core.QgsApplication.taskManager().addTask(self.network_task)

    def upload_style(self):
        self.apply()
        doc = QtXml.QDomDocument()
        error_message = ""
        self.layer.exportSldStyle(doc, error_message)
        log(f"exportSldStyle error_message: {error_message!r}")
        if error_message == "":
            self.network_task = network.MultipleNetworkFetcherTask(
                [
                    network.RequestToPerform(
                        QtCore.QUrl(self.dataset.default_style.sld_url),
                        payload=json.dumps(doc),
                    )
                ],
                self.connection_settings.auth_config,
            )

    # def shouldTriggerLayerRepaint(self):
    #     return True

    # def _trigger_apply_selected_style(self):
    #     selected_style = self.available_styles_cb.currentData()
    #     selected_style: models.BriefGeonodeStyle
    #     if selected_style.sld is not None:
    #         # we already have it locally, no need to re-download
    #         self._style_to_be_applied = selected_style
    #         self._apply_sld()
    #     else:  # let's download it
    #         connection_settings_id = self.layer.customProperty(
    #             models.DATASET_CONNECTION_CUSTOM_PROPERTY_KEY
    #         )
    #         connection_settings = conf.settings_manager.get_connection_settings(
    #             UUID(connection_settings_id)
    #         )
    #         self.network_task = network.MultipleNetworkFetcherTask(
    #             [network.RequestToPerform(QtCore.QUrl(selected_style.sld_url))],
    #             connection_settings.auth_config,
    #         )
    #         self.network_task.all_finished.connect(
    #             partial(self._handle_sld_style_downloaded, selected_style)
    #         )
    #         qgis.core.QgsApplication.taskManager().addTask(self.network_task)

    def _handle_sld_downloaded(self, task_result: bool):
        if task_result:
            usable_sld = styles.get_usable_sld(self.network_task.response_contents[0])
            if usable_sld is not None:
                self.dataset.default_style.sld = usable_sld
                self._style_to_be_applied = self.dataset.default_style
                self.apply()
                self.message_bar.pushMessage(
                    "Applied downloaded SLD style from remote GeoNode"
                )
            else:
                self.message_bar.pushMessage(
                    "Unable to apply downloaded SLD style from remote GeoNode"
                )
        else:
            self.message_bar.pushMessage("Unable to retrieve GeoNode style")

    # def _handle_sld_style_downloaded(
    #     self, style: models.BriefGeonodeStyle, task_result: bool
    # ):
    #     if task_result:
    #         usable_sld = styles.get_usable_sld(self.network_task.response_contents[0])
    #         if usable_sld is not None:
    #             self.message_bar.pushMessage(
    #                 "Applied downloaded SLD style from remote GeoNode"
    #             )
    #             style.sld = usable_sld
    #             self._style_to_be_applied = style
    #             self.apply()
    #         else:
    #             self.message_bar.pushMessage(
    #                 "Unable to apply downloaded SLD style from remote GeoNode"
    #             )
    #     else:
    #         self.message_bar.pushMessage("Unable to retrieve GeoNode style")

    # def _populate_styles_combobox(self):
    #     for style_name, style in self.dataset.styles.items():
    #         if (style.sld_url or None) is not None:
    #             self.available_styles_cb.addItem(style_name, style)

    def _apply_sld(self):
        sld_load_error_msg = ""
        sld_load_result = self.layer.readSld(
            self._style_to_be_applied.sld, sld_load_error_msg
        )
        log(
            f"sld_load_result: {sld_load_result} - seld_load_error_msg: {sld_load_error_msg}"
        )
        if sld_load_result:
            layer_properties_dialog = self._get_layer_properties_dialog()
            layer_properties_dialog.syncToLayer()

    def _get_layer_properties_dialog(self):
        # FIXME: This is a very hacky way to get the layer properties dialog, and it
        #  may not even work for layers that are not vector, but I've not been able
        #  to find a more elegant way to retrieve it yet
        return self.parent().parent().parent().parent()
