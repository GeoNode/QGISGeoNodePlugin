import os
import re
import typing
import uuid
from functools import partial


from qgis.core import Qgis
from qgis.gui import QgsMessageBar
from qgis.PyQt import (
    QtWidgets,
    QtCore,
    QtGui,
)
from qgis.PyQt.uic import loadUiType

from ..apiclient import (
    GeonodeApiVersion,
    get_geonode_client,
)
from ..apiclient.base import BaseGeonodeClient
from ..apiclient import models
from ..conf import (
    ConnectionSettings,
    settings_manager,
)
from .. import network
from ..utils import tr

DialogUi, _ = loadUiType(
    os.path.join(os.path.dirname(__file__), "../ui/connection_dialog.ui")
)


class ConnectionDialog(QtWidgets.QDialog, DialogUi):
    connection_id: uuid.UUID
    api_client_class_path: typing.Optional[str]
    geonode_client: BaseGeonodeClient = None

    _autodetection_type_order: typing.List[GeonodeApiVersion] = [
        GeonodeApiVersion.V2,
        GeonodeApiVersion.OGC_CSW,
    ]

    def __init__(self, connection_settings: typing.Optional[ConnectionSettings] = None):
        super().__init__()
        self.setupUi(self)
        self._widgets_to_toggle_during_connection_test = [
            self.test_connection_btn,
            self.buttonBox,
            self.authcfg_acs,
            self.options_gb,
            self.connection_details,
        ]
        self.bar = QgsMessageBar()
        self.bar.setSizePolicy(
            QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Fixed
        )
        self.layout().addWidget(self.bar, 0, 0, alignment=QtCore.Qt.AlignTop)

        if connection_settings is not None:
            self.connection_id = connection_settings.id
            self.api_client_class_path = connection_settings.api_client_class_path
            self.load_connection_settings(connection_settings)
        else:
            self.connection_id = uuid.uuid4()
            self.api_client_class_path = None
        self.buttonBox.button(QtWidgets.QDialogButtonBox.Ok).setEnabled(False)
        ok_signals = [
            self.name_le.textChanged,
            self.url_le.textChanged,
        ]
        for signal in ok_signals:
            signal.connect(self.update_ok_buttons)
        self.test_connection_btn.clicked.connect(self.test_connection)
        # disallow names that have a slash since that is not compatible with how we
        # are storing plugin state in QgsSettings
        self.name_le.setValidator(
            QtGui.QRegExpValidator(QtCore.QRegExp("[^\\/]+"), self.name_le)
        )
        self.update_ok_buttons()

    def load_connection_settings(self, connection_settings: ConnectionSettings):
        self.name_le.setText(connection_settings.name)
        self.url_le.setText(connection_settings.base_url)
        self.authcfg_acs.setConfigId(connection_settings.auth_config)
        self.page_size_sb.setValue(connection_settings.page_size)

    def get_connection_settings(self) -> ConnectionSettings:
        return ConnectionSettings(
            id=self.connection_id,
            name=self.name_le.text().strip(),
            base_url=self.url_le.text().strip().rstrip("/"),
            auth_config=self.authcfg_acs.configId(),
            page_size=self.page_size_sb.value(),
            api_client_class_path=self.api_client_class_path,
        )

    def test_connection(self):
        for widget in self._widgets_to_toggle_during_connection_test:
            widget.setEnabled(False)
        current_settings = self.get_connection_settings()
        if self.api_client_class_path is None:
            discovery_task = network.ApiClientDiscovererTask(current_settings.base_url)
            discovery_task.discovery_finished.connect(self.handle_discovery_test)
        else:
            client = get_geonode_client(self.get_connection_settings())

        client = get_geonode_client(self.get_connection_settings())
        client.layer_list_received.connect(self.handle_connection_test_success)
        client.layer_list_received.connect(self.enable_post_test_connection_buttons)
        client.error_received.connect(self.handle_connection_test_error)
        client.error_received.connect(self.enable_post_test_connection_buttons)
        self.show_progress(tr("Testing connection..."))
        client.get_layers()

    def handle_discovery_test(self, discovered_api_client_class_path: str):
        self.bar.clearWidgets()
        self.api_client_class_path = discovered_api_client_class_path or None
        if self.api_client_class_path:
            self.bar.pushMessage("Connection is valid", level=Qgis.Info)
        else:
            self.bar.pushMessage("Connection is not valid", level=Qgis.Critical)

    def handle_connection_test_success(self, payload: typing.Union[typing.Dict, int]):
        self.bar.clearWidgets()
        self.bar.pushMessage("Connection is valid", level=Qgis.Info)

    def handle_connection_test_error(self, payload: typing.Union[typing.Dict, int]):
        self.bar.clearWidgets()
        self.bar.pushMessage("Connection is not valid", level=Qgis.Critical)

    def enable_post_test_connection_buttons(self):
        for widget in self._widgets_to_toggle_during_connection_test:
            try:
                widget.setEnabled(True)
            except RuntimeError:
                pass
        self.update_ok_buttons()

    def accept(self):
        connection_settings = self.get_connection_settings()
        name_pattern = re.compile(
            f"^{connection_settings.name}$|^{connection_settings.name}(\(\d+\))$"
        )
        duplicate_names = []
        for connection_conf in settings_manager.list_connections():
            if connection_conf.id == connection_settings.id:
                continue  # we don't want to compare against ourselves
            if name_pattern.search(connection_conf.name) is not None:
                duplicate_names.append(connection_conf.name)
        if len(duplicate_names) > 0:
            connection_settings.name = (
                f"{connection_settings.name}({len(duplicate_names)})"
            )
        settings_manager.save_connection_settings(connection_settings)
        settings_manager.set_current_connection(connection_settings.id)
        super().accept()

    def update_ok_buttons(self):
        enabled_state = self.name_le.text() != "" and self.url_le.text() != ""
        self.buttonBox.button(QtWidgets.QDialogButtonBox.Ok).setEnabled(enabled_state)
        self.test_connection_btn.setEnabled(enabled_state)

    def show_progress(self, message):
        message_bar_item = self.bar.createMessage(message)
        progress_bar = QtWidgets.QProgressBar()
        progress_bar.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
        progress_bar.setMinimum(0)
        progress_bar.setMaximum(0)
        message_bar_item.layout().addWidget(progress_bar)
        self.bar.pushWidget(message_bar_item, Qgis.Info)


def _clear_layout(layout: QtWidgets.QLayout):
    while layout.count() > 0:
        child = layout.takeAt(0)
        widget = child.widget()
        if widget is not None:
            widget.deleteLater()