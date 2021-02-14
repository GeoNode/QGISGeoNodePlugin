import os
import typing
import uuid
from functools import partial


from qgis.core import Qgis
from qgis.gui import QgsMessageBar
from qgis.PyQt.QtWidgets import QDialog, QDialogButtonBox, QSizePolicy
from qgis.PyQt.QtGui import QRegExpValidator
from qgis.PyQt.QtCore import QRegExp
from qgis.PyQt.uic import loadUiType

from ..apiclient import (
    GeonodeApiVersion,
    get_geonode_client,
)
from ..apiclient.base import BaseGeonodeClient
from ..conf import (
    ConnectionSettings,
    connections_manager,
)

DialogUi, _ = loadUiType(
    os.path.join(os.path.dirname(__file__), "../ui/connection_dialog.ui")
)


class ConnectionDialog(QDialog, DialogUi):
    connection_id: uuid.UUID
    geonode_client: BaseGeonodeClient = None

    _autodetection_type_order: typing.List[GeonodeApiVersion] = [
        GeonodeApiVersion.V2,
        GeonodeApiVersion.OGC_CSW,
    ]

    def __init__(self, connection_settings: typing.Optional[ConnectionSettings] = None):
        super().__init__()
        self.setupUi(self)
        api_version_names = list(GeonodeApiVersion)
        api_version_names.sort(key=lambda member: member.name, reverse=True)
        self.api_version_cmb.insertItems(
            0, [member.name for member in api_version_names]
        )
        self._widgets_to_toggle_during_connection_test = [
            self.test_connection_btn,
            self.buttonBox,
        ]
        self.bar = QgsMessageBar()
        self.bar.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        self.layout().insertWidget(0, self.bar)
        if connection_settings is not None:
            self.connection_id = connection_settings.id
            self.load_connection_settings(connection_settings)
        else:
            self.connection_id = uuid.uuid4()
        self.buttonBox.button(QDialogButtonBox.Ok).setEnabled(False)
        ok_signals = [
            self.name_le.textChanged,
            self.url_le.textChanged,
        ]
        for signal in ok_signals:
            signal.connect(self.update_ok_buttons)
        self.test_connection_btn.clicked.connect(self.test_connection)
        self.detect_version_btn.clicked.connect(self.initiate_api_version_detection)
        # disallow names that have a slash since that is not compatible with how we
        # are storing plugin state in QgsSettings
        self.name_le.setValidator(QRegExpValidator(QRegExp("[^\\/]+"), self.name_le))
        self.update_ok_buttons()

    def load_connection_settings(self, connection_settings: ConnectionSettings):
        self.name_le.setText(connection_settings.name)
        self.url_le.setText(connection_settings.base_url)
        self.authcfg_acs.setConfigId(connection_settings.auth_config)
        self.api_version_cmb.setCurrentText(connection_settings.api_version.name)
        self.page_size_sb.setValue(connection_settings.page_size)

    def get_connection_settings(self) -> ConnectionSettings:
        return ConnectionSettings(
            id=self.connection_id,
            name=self.name_le.text().strip(),
            base_url=self.url_le.text().strip(),
            auth_config=self.authcfg_acs.configId(),
            api_version=GeonodeApiVersion[self.api_version_cmb.currentText().upper()],
            page_size=self.page_size_sb.value(),
        )

    def test_connection(self):
        for widget in self._widgets_to_toggle_during_connection_test:
            widget.setEnabled(False)
        client = get_geonode_client(self.get_connection_settings())
        client.layer_list_received.connect(self.handle_connection_test_success)
        client.error_received.connect(self.handle_connection_test_error)
        client.layer_list_received.connect(self.enable_post_test_connection_buttons)
        client.error_received.connect(self.enable_post_test_connection_buttons)
        client.get_layers()

    def handle_connection_test_success(self, payload: typing.Union[typing.Dict, int]):
        self.bar.pushMessage("Connection is valid", level=Qgis.Info)

    def handle_connection_test_error(self, payload: typing.Union[typing.Dict, int]):
        self.bar.pushMessage("Connection is not valid", level=Qgis.Critical)

    def enable_post_test_connection_buttons(self):
        for widget in self._widgets_to_toggle_during_connection_test:
            widget.setEnabled(True)
        self.update_ok_buttons()

    def initiate_api_version_detection(self):
        self.detect_api_version(self._autodetection_type_order[0])

    def detect_api_version(self, version: GeonodeApiVersion):

        connection_settings = self.get_connection_settings()
        connection_settings.api_version = version

        client = get_geonode_client(connection_settings)
        success_handler = partial(self.handle_autodetection_success, version)
        error_handler = partial(self.handle_autodetection_error, version)
        client.layer_list_received.connect(success_handler)
        client.error_received.connect(error_handler)
        client.get_layers()

    def handle_autodetection_success(self, version: GeonodeApiVersion):
        self.bar.pushMessage(f"Using API version: {version.name}", level=Qgis.Info)
        self.api_version_cmb.setCurrentText(version.name)

    def handle_autodetection_error(self, version: GeonodeApiVersion):
        self.bar.pushMessage(
            f"API version {version.name} does not work", level=Qgis.Warning
        )
        current_index = self._autodetection_type_order.index(version)
        if current_index < len(self._autodetection_type_order) - 1:
            next_version_to_try = self._autodetection_type_order[current_index + 1]
            self.detect_api_version(next_version_to_try)
        else:
            self.bar.pushMessage(
                f"Could not detect a suitable API version", level=Qgis.Critical
            )

    def accept(self):
        connection_settings = self.get_connection_settings()
        connections_manager.save_connection_settings(connection_settings)
        connections_manager.set_current_connection(connection_settings.id)
        super().accept()

    def update_ok_buttons(self):
        enabled_state = self.name_le.text() != "" and self.url_le.text() != ""
        self.buttonBox.button(QDialogButtonBox.Ok).setEnabled(enabled_state)
        self.test_connection_btn.setEnabled(enabled_state)
