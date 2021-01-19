import os
import typing
import uuid


from qgis.core import Qgis
from qgis.gui import QgsMessageBar
from qgis.PyQt.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QSizePolicy,
)
from qgis.PyQt.QtGui import QRegExpValidator
from qgis.PyQt.QtCore import QRegExp
from qgis.PyQt.uic import loadUiType

from ..apiclient.api_client import GeonodeClient
from ..qgisgeonode.conf import ConnectionSettings, connections_manager

DialogUi, _ = loadUiType(
    os.path.join(os.path.dirname(__file__), "../ui/connection_dialog.ui")
)


class ConnectionDialog(QDialog, DialogUi):
    connection_id: uuid.UUID
    geonode_client: GeonodeClient = None

    def __init__(self, connection_settings: typing.Optional[ConnectionSettings] = None):
        super().__init__()
        self.setupUi(self)
        self._widgets_to_toggle_during_connection_test = [
            self.test_connection_btn,
            self.buttonBox
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
        # disallow names that have a slash since that is not compatible with how we
        # are storing plugin state in QgsSettings
        self.name_le.setValidator(QRegExpValidator(QRegExp("[^\\/]+"), self.name_le))
        self.update_ok_buttons()

    def load_connection_settings(self, connection_settings: ConnectionSettings):
        self.name_le.setText(connection_settings.name)
        self.url_le.setText(connection_settings.base_url)
        self.authcfg_acs.setConfigId(connection_settings.auth_config)

    def get_connection_settings(self) -> ConnectionSettings:
        return ConnectionSettings(
            id=self.connection_id,
            name=self.name_le.text().strip(),
            base_url=self.url_le.text().strip(),
            auth_config=self.authcfg_acs.configId(),
        )

    def test_connection(self):
        for widget in self._widgets_to_toggle_during_connection_test:
            widget.setEnabled(False)
        self.geonode_client = GeonodeClient.from_connection_settings(
            self.get_connection_settings()
        )
        self.geonode_client.layer_list_received.connect(
            self.handle_connection_test_success
        )
        self.geonode_client.error_received.connect(self.handle_connection_test_error)
        self.geonode_client.layer_list_received.connect(
            self.enable_post_test_connection_buttons)
        self.geonode_client.error_received.connect(
            self.enable_post_test_connection_buttons)
        self.geonode_client.get_layers()

    def handle_connection_test_success(self, payload: typing.Union[typing.Dict, int]):
        self.bar.pushMessage("Connection is valid", level=Qgis.Info)

    def handle_connection_test_error(self, payload: typing.Union[typing.Dict, int]):
        self.bar.pushMessage("Connection is not valid", level=Qgis.Critical)

    def enable_post_test_connection_buttons(self):
        for widget in self._widgets_to_toggle_during_connection_test:
            widget.setEnabled(True)
        self.update_ok_buttons()

    def accept(self):
        connection_settings = self.get_connection_settings()
        connections_manager.save_connection_settings(connection_settings)
        connections_manager.set_current_connection(connection_settings.id)
        super().accept()

    def update_ok_buttons(self):
        enabled_state = self.name_le.text() != "" and self.url_le.text() != ""
        self.buttonBox.button(QDialogButtonBox.Ok).setEnabled(enabled_state)
        self.test_connection_btn.setEnabled(enabled_state)
