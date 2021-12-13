import os
import re
import typing
import uuid


import qgis.core
from qgis.gui import QgsMessageBar
from qgis.PyQt import (
    QtWidgets,
    QtCore,
    QtGui,
)
from qgis.PyQt.uic import loadUiType

from .. import network
from ..apiclient.base import BaseGeonodeClient
from ..conf import (
    ConnectionSettings,
    settings_manager,
)
from ..utils import tr

DialogUi, _ = loadUiType(
    os.path.join(os.path.dirname(__file__), "../ui/connection_dialog.ui")
)


class ConnectionDialog(QtWidgets.QDialog, DialogUi):
    connection_id: uuid.UUID
    api_client_class_path: typing.Optional[str]
    discovery_task: typing.Optional[network.ApiClientDiscovererTask]
    geonode_client: BaseGeonodeClient = None

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
        self.layout().insertWidget(0, self.bar, alignment=QtCore.Qt.AlignTop)
        self.discovery_task = None

        if connection_settings is not None:
            self.connection_id = connection_settings.id
            self.api_client_class_path = connection_settings.api_client_class_path
            self.name_le.setText(connection_settings.name)
            self.url_le.setText(connection_settings.base_url)
            self.authcfg_acs.setConfigId(connection_settings.auth_config)
            self.page_size_sb.setValue(connection_settings.page_size)
            if self.api_client_class_path == network.UNSUPPORTED_REMOTE:
                self.show_progress(
                    tr("Invalid configuration. Correct GeoNode URL and/or test again."),
                    message_level=qgis.core.Qgis.Critical,
                )
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
        self.discovery_task = network.ApiClientDiscovererTask(current_settings.base_url)
        self.discovery_task.discovery_finished.connect(self.handle_discovery_test)
        self.discovery_task.discovery_finished.connect(
            self.enable_post_test_connection_buttons
        )
        self.show_progress(tr("Testing connection..."), include_progress_bar=True)
        qgis.core.QgsApplication.taskManager().addTask(self.discovery_task)

    def handle_discovery_test(self, discovered_api_client_class_path: str):
        self.bar.clearWidgets()
        self.api_client_class_path = discovered_api_client_class_path
        if self.api_client_class_path != network.UNSUPPORTED_REMOTE:
            self.bar.pushMessage("Connection is valid", level=qgis.core.Qgis.Info)
        else:
            self.bar.pushMessage(
                "Connection is not valid", level=qgis.core.Qgis.Critical
            )

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

    def show_progress(
        self,
        message: str,
        message_level: typing.Optional[qgis.core.Qgis] = qgis.core.Qgis.Info,
        include_progress_bar: typing.Optional[bool] = False,
    ):
        message_bar_item = self.bar.createMessage(message)
        if include_progress_bar:
            progress_bar = QtWidgets.QProgressBar()
            progress_bar.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
            progress_bar.setMinimum(0)
            progress_bar.setMaximum(0)
            message_bar_item.layout().addWidget(progress_bar)
        self.bar.pushWidget(message_bar_item, message_level)


def _clear_layout(layout: QtWidgets.QLayout):
    while layout.count() > 0:
        child = layout.takeAt(0)
        widget = child.widget()
        if widget is not None:
            widget.deleteLater()
