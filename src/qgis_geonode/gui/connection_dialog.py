import os
import typing

from qgis.PyQt.uic import loadUiType

from qgis.PyQt.QtWidgets import QDialog, QDialogButtonBox
from qgis.PyQt.QtGui import QValidator, QRegExpValidator
from qgis.PyQt.QtCore import QRegExp, QUrl

from ..qgisgeonode.utils import settings_manager

DialogUi, _ = loadUiType(
    os.path.join(os.path.dirname(__file__), "../ui/qgis_geonode_connection.ui")
)


class ConnectionDialog(QDialog, DialogUi):
    def __init__(self, name: typing.Optional[str] = None):
        super().__init__()
        self.setupUi(self)
        if name is not None:
            self.load_details(name)
        self.buttonBox.button(QDialogButtonBox.Ok).setEnabled(False)
        ok_signals = [
            self.name.textChanged,
            self.url.textChanged,
        ]
        for signal in ok_signals:
            signal.connect(self.update_ok_button)

        # disallow names that have a slash since that is not compatible with how we
        # are storing plugin state in QgsSettings
        self.name.setValidator(QRegExpValidator(QRegExp("[^\\/]+"), self.name))
        self.update_ok_button()

    def load_details(self, name: str):
        details = settings_manager.get_connection_settings(name)
        self.name.setText(details.get("name", ""))
        self.url.setText(details.get("url", ""))
        self.authConfigSelect.setConfigId(details.get("authcfg", ""))

    def save_details(self):
        details = {
            "name": self.name.text().strip(),
            "url": self.url.text().strip(),
            "authcfg": self.authConfigSelect.configId()
        }
        settings_manager.save_connection_settings(**details)

    def accept(self):
        """Add connection"""

        self.save_details()
        super().accept()

    def update_ok_button(self):
        enabled_state = self.name.text() != "" and self.url.text() != ""
        self.buttonBox.button(QDialogButtonBox.Ok).setEnabled(enabled_state)
