import os
import typing
import uuid

from qgis.core import QgsProject
from qgis.gui import QgsSourceSelectProvider, QgsAbstractDataSourceWidget

from qgis.PyQt.uic import loadUiType

from qgis.PyQt.QtGui import QIcon

from qgis.PyQt.QtWidgets import QApplication, QMessageBox, QTreeWidgetItem
from qgis.PyQt.QtCore import Qt

from ..utils import tr
from ..conf import connections_manager
from ..gui.connection_dialog import ConnectionDialog


from qgis_geonode.apiclient.api_client import GeonodeClient


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
        self.connections_cmb.currentIndexChanged.connect(
            self.toggle_connection_management_buttons
        )
        self.btnNew.clicked.connect(self.add_connection)
        self.btnEdit.clicked.connect(self.edit_connection)
        self.btnDelete.clicked.connect(self.delete_connection)
        self.toggle_connection_management_buttons()

        connections_manager.current_connection_changed.connect(
            self.update_connections_combobox
        )

        self.update_connections_combobox()

        self.currentPage = 1
        self.totalLayers = 0

        self.search_btn.clicked.connect(self.searchGeonode)

        current_connection = connections_manager.get_current_connection()
        if current_connection is None:
            existing_connections = connections_manager.list_connections()
            if len(existing_connections) > 0:
                current_connection = existing_connections[0]
                connections_manager.set_current_connection(current_connection.id)
        else:
            self.update_connections_combobox(str(current_connection.id))

        self.next_btn.clicked.connect(self.searchGeonode)
        self.previous_btn.clicked.connect(self.searchGeonode)

        self.next_btn.setEnabled(False)
        self.previous_btn.setEnabled(False)

        self.treeWidget.setHeaderLabels([tr("Title"), tr("Abstract")])

    def add_connection(self):
        connection_dialog = ConnectionDialog()
        connection_dialog.exec_()

    def edit_connection(self):
        selected_name = self.connections_cmb.currentText()
        connection_settings = connections_manager.find_connection_by_name(selected_name)
        connection_dialog = ConnectionDialog(connection_settings=connection_settings)
        connection_dialog.exec_()

    def delete_connection(self):
        name = self.connections_cmb.currentText()
        current_connection = connections_manager.find_connection_by_name(name)
        if self._confirm_deletion(name):
            existing_connections = connections_manager.list_connections()
            current_index = self.connections_cmb.currentIndex()
            if current_index > 0:
                next_current_connection = existing_connections[current_index - 1]
            elif current_index == 0 and len(existing_connections) > 1:
                next_current_connection = existing_connections[current_index + 1]
            else:
                next_current_connection = None
            connections_manager.delete_connection(current_connection.id)
            if next_current_connection is not None:
                connections_manager.set_current_connection(next_current_connection.id)

    def update_connections_combobox(
        self, current_identifier: typing.Optional[str] = ""
    ):
        self.connections_cmb.clear()
        existing_connections = connections_manager.list_connections()
        self.connections_cmb.addItems(conn.name for conn in existing_connections)
        if current_identifier != "":
            current_connection = connections_manager.get_connection_settings(
                uuid.UUID(current_identifier)
            )
            current_index = self.connections_cmb.findText(current_connection.name)
            self.connections_cmb.setCurrentIndex(current_index)

    def toggle_connection_management_buttons(self):
        enabled = len(connections_manager.list_connections()) > 0
        self.btnEdit.setEnabled(enabled)
        self.btnDelete.setEnabled(enabled)
        self.search_btn.setEnabled(enabled)

    def _confirm_deletion(self, connection_name: str):
        message = tr('Remove the following connection "{}"?').format(connection_name)
        confirmation = QMessageBox.warning(
            self, tr("QGIS GeoNode"), message, QMessageBox.Yes, QMessageBox.No
        )

        return confirmation == QMessageBox.Yes

    def searchGeonode(self, page=None):
        sender_name = self.sender().objectName()
        if sender_name == "next_btn":
            self.currentPage += 1
            page = self.currentPage
        elif sender_name == "previous_btn":
            self.currentPage -= 1
            page = self.currentPage

        connection_name = self.connections_cmb.currentText()
        connection = connections_manager.find_connection_by_name(connection_name)

        base_url = connection.base_url

        geonode_client = GeonodeClient(base_url)
        geonode_client.layer_list_received.connect(self.show_layers)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        geonode_client.get_layers(page=page)

    def show_layers(self, payload):
        QApplication.setOverrideCursor(Qt.ArrowCursor)

        if payload["layers"]:
            self.next_btn.setEnabled(
                self.currentPage < int(payload["total"]) / int(payload["page_size"])
            )
            self.previous_btn.setEnabled(self.currentPage > 0)
            self.resultsLabel.setText(
                tr(
                    "Showing page {} of {} layers".format(
                        payload["page"], payload["total"]
                    )
                )
            )
            self.treeWidget.clear()

            for i in range(len(payload["layers"])):
                QTreeWidgetItem(
                    self.treeWidget,
                    [payload["layers"][i]["title"], payload["layers"][i]["abstract"]],
                )

        else:
            self.resultsLabel.setText(tr("No layers found"))

        self.search_btn.setEnabled(True)
