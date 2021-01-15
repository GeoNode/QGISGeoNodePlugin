import os
import typing

from qgis.PyQt.uic import loadUiType

from qgis.PyQt.QtWidgets import QDialog, QDialogButtonBox
from qgis.PyQt.QtGui import QRegExpValidator
from qgis.PyQt.QtCore import QRegExp

from ..qgisgeonode.conf import settings_manager

DialogUi, _ = loadUiType(
    os.path.join(os.path.dirname(__file__), "../ui/connection_dialog.ui")
)


class ConnectionDialog(QDialog, DialogUi):
    def __init__(self, name: typing.Optional[str] = None):
        super().__init__()
        self.setupUi(self)
        if name is not None:
            self.load_details(name)
        self.buttonBox.button(QDialogButtonBox.Ok).setEnabled(False)
        ok_signals = [
            self.name_le.textChanged,
            self.url_le.textChanged,
        ]
        for signal in ok_signals:
            signal.connect(self.update_ok_button)

        # disallow names that have a slash since that is not compatible with how we
        # are storing plugin state in QgsSettings
        self.name_le.setValidator(QRegExpValidator(QRegExp("[^\\/]+"), self.name_le))
        self.update_ok_button()

    def load_details(self, name: str):
        details = settings_manager.get_connection_settings(name)
        self.name_le.setText(details["name"])
        self.url_le.setText(details["url"])
        self.authcfg_acs.setConfigId(details.get("authcfg", ""))

    def save_details(self) -> typing.Dict:
        details = {
            "name": self.name_le.text().strip(),
            "url": self.url_le.text().strip(),
            "authcfg": self.authcfg_acs.configId()
        }
        settings_manager.save_connection_settings(**details)
        return details

    def accept(self):
        details = self.save_details()
        settings_manager.set_current_connection(details["name"])
        super().accept()

    def update_ok_button(self):
        enabled_state = self.name_le.text() != "" and self.url_le.text() != ""
        self.buttonBox.button(QDialogButtonBox.Ok).setEnabled(enabled_state)
