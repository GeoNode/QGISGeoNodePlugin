import os

from qgis.PyQt.uic import loadUiType

from qgis.PyQt.QtWidgets import QDialog, QDialogButtonBox
from qgis.core import QgsSettings
from qgis.PyQt.QtGui import QValidator, QRegExpValidator
from qgis.PyQt.QtCore import QRegExp, QUrl

from qgis_geonode.qgisgeonode.utils import tr

DialogUi, _ = loadUiType(
    os.path.join(os.path.dirname(__file__), "../ui/qgis_geonode_connection.ui")
)


class ConnectionDialog(QDialog, DialogUi):
    def __init__(self):
        super(ConnectionDialog, self).__init__()
        self.setupUi(self)
        self.settings = QgsSettings()
        self.connection_name = None

        self.buttonBox.button(QDialogButtonBox.Ok).setEnabled(False)

        self.name.textChanged.connect(self.update_ok_button)
        self.url.textChanged.connect(self.update_ok_button)

        self.name.setValidator(QRegExpValidator(QRegExp("[^\\/]+"), self.name))

    def accept(self):
        """Add connection"""

        connection_name = self.name.text().strip()
        connection_url = self.url.text().strip()

        if any([connection_name == "", connection_url == ""]):
            return

        if "/" in connection_name:
            return

        if connection_name is not None:
            name = "/Qgis_GeoNode/%s" % connection_name
            url = "%s/url" % name

            # When editing a connection, remove the old settings before adding new ones.
            if self.connection_name and self.connection_name != connection_name:
                self.settings.remove("/Qgis_GeoNode/{}".format(self.connection_name))

            self.settings.setValue(url, connection_url)
            self.settings.setValue("/Qgis_GeoNode/selected", connection_name)

            QDialog.accept(self)

    def reject(self):
        QDialog.reject(self)

    def set_connection_name(self, name):
        self.connection_name = name

    def update_ok_button(self):
        enabled_state = self.name.text() != "" and self.url.text() != ""
        self.buttonBox.button(QDialogButtonBox.Ok).setEnabled(enabled_state)
