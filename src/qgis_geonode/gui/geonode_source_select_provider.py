import os

from qgis.core import QgsProject
from qgis.gui import QgsSourceSelectProvider, QgsAbstractDataSourceWidget

from qgis.PyQt.uic import loadUiType

from qgis_geonode.qgisgeonode.resources import *
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QDialog, QMessageBox
from qgis.core import QgsSettings

from ..qgisgeonode.utils import tr
from ..qgisgeonode.conf import settings_manager
from ..gui.connection_dialog import ConnectionDialog


WidgetUi, _ = loadUiType(
    os.path.join(os.path.dirname(__file__), "../ui/geonode_datasource_widget.ui")
)


class GeonodeSourceSelectProvider(QgsSourceSelectProvider):
    def createDataSourceWidget(self, parent, fl, widgetMode):
        return GeonodeDataSourceWidget(parent, fl, widgetMode)

    def providerKey(self):
        return "geonodeprovider"

    def icon(self):
        return QIcon(":/plugins/qgis_geonode/mIconGeonode.svg")

    def text(self):
        return tr("GeoNode Plugin Provider")

    def toolTip(self):
        return tr("Add Geonode Layer")

    def ordering(self):
        return QgsSourceSelectProvider.OrderOtherProvider


class GeonodeDataSourceWidget(QgsAbstractDataSourceWidget, WidgetUi):
    def __init__(self, parent, fl, widgetMode):
        super().__init__(parent, fl, widgetMode)
        self.setupUi(self)
        self.project = QgsProject.instance()
        self.settings = QgsSettings()
        self.connections_cmb.currentIndexChanged.connect(
            self.toggle_connection_management_buttons
        )
        self.btnNew.clicked.connect(self.add_connection)
        self.btnEdit.clicked.connect(self.edit_connection)
        self.btnDelete.clicked.connect(self.delete_connection)
        self.toggle_connection_management_buttons()

        settings_manager.current_connection_changed.connect(
            self.update_connections_combobox
        )

    def add_connection(self):
        connection_dialog = ConnectionDialog()
        connection_dialog.exec_()

    def update_connections_combobox(self, current_connection: str):
        self.connections_cmb.clear()
        existing_connections = settings_manager.list_connections()
        self.connections_cmb.addItems(existing_connections)
        current_index = self.connections_cmb.findText(current_connection)
        self.connections_cmb.setCurrentIndex(current_index)

    def toggle_connection_management_buttons(self):
        enabled = len(settings_manager.list_connections()) > 0
        self.btnEdit.setEnabled(enabled)
        self.btnDelete.setEnabled(enabled)
        self.search_btn.setEnabled(enabled)

    def edit_connection(self):
        connection_dialog = ConnectionDialog(name=self.connections_cmb.currentText())
        connection_dialog.exec_()

    def delete_connection(self):
        connection_name = self.connections_cmb.currentText()
        existing_connections = settings_manager.list_connections()
        current_index = existing_connections.index(connection_name)

        if len(existing_connections) > 2:
            new_index = current_index
        elif len(existing_connections) == 2:
            new_index = current_index - 1
        elif len(existing_connections) == 1:
            new_index = None
        else:
            raise RuntimeError("Something is wrong - there are no existing connections")

        message = tr('Remove the following connection "{}"?').format(connection_name)
        confirmation = QMessageBox.warning(
            self, tr("QGIS GeoNode"), message, QMessageBox.Yes, QMessageBox.No
        )
        if confirmation == QMessageBox.Yes:
            settings_manager.delete_connection(connection_name)
            if new_index is not None:
                new_current = settings_manager.list_connections()[new_index]
                settings_manager.set_current_connection(new_current)
