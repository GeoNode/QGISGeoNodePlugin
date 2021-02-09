import logging
import math
import os
import typing
import uuid

from qgis.core import (
    QgsProject,
    Qgis,
)
from qgis.gui import (
    QgsAbstractDataSourceWidget,
    QgsMessageBar,
    QgsSourceSelectProvider,
)

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtNetwork import QNetworkReply
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.uic import loadUiType

from qgis.PyQt.QtWidgets import (
    QMessageBox,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
    QLabel,
)

from ..api_client import (
    GeonodeClient,
    BriefGeonodeResource,
    GeonodeResourceType
)
from ..conf import connections_manager
from ..gui.connection_dialog import ConnectionDialog
from ..gui.search_result_widget import SearchResultWidget
from ..utils import enum_mapping, log, tr

logger = logging.getLogger(__name__)

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
        self.connections_cmb.currentIndexChanged.connect(self.update_current_connection)
        self.btnNew.clicked.connect(self.add_connection)
        self.btnEdit.clicked.connect(self.edit_connection)
        self.btnDelete.clicked.connect(self.delete_connection)
        self.toggle_connection_management_buttons()
        connections_manager.current_connection_changed.connect(
            self.update_connections_combobox
        )
        self.update_connections_combobox()
        current_connection = connections_manager.get_current_connection()
        if current_connection is None:
            existing_connections = connections_manager.list_connections()
            if len(existing_connections) > 0:
                current_connection = existing_connections[0]
                connections_manager.set_current_connection(current_connection.id)
        else:
            self.update_connections_combobox(str(current_connection.id))
        self.current_page = 1
        self.search_btn.clicked.connect(self.search_geonode)
        self.next_btn.clicked.connect(self.request_next_page)
        self.previous_btn.clicked.connect(self.request_previous_page)
        self.next_btn.setEnabled(False)
        self.previous_btn.setEnabled(False)
        self.message_bar = QgsMessageBar()
        self.message_bar.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        self.layout().insertWidget(4, self.message_bar)

        self.populate_search_items()

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

        existing_connections = connections_manager.list_connections()

        if self.connections_cmb.count() != len(existing_connections):
            self.connections_cmb.clear()
            self.connections_cmb.addItems(conn.name for conn in existing_connections)
        if current_identifier != "":
            current_connection = connections_manager.get_connection_settings(
                uuid.UUID(current_identifier)
            )
            if current_connection.name != self.connections_cmb.currentText():
                current_index = self.connections_cmb.findText(current_connection.name)
                self.connections_cmb.setCurrentIndex(current_index)

    def toggle_connection_management_buttons(self):
        enabled = len(connections_manager.list_connections()) > 0
        self.btnEdit.setEnabled(enabled)
        self.btnDelete.setEnabled(enabled)
        self.search_btn.setEnabled(enabled)
        self.clear_search()
        self.keywords_cmb.clear()
        self.search_keywords()
        self.current_page = 1

    def update_current_connection(self):
        if self.connections_cmb.currentText() != "":
            current_connection = connections_manager.find_connection_by_name(
                self.connections_cmb.currentText()
            )
            connections_manager.set_current_connection(current_connection.id)

    def _confirm_deletion(self, connection_name: str):
        message = tr('Remove the following connection "{}"?').format(connection_name)
        confirmation = QMessageBox.warning(
            self, tr("QGIS GeoNode"), message, QMessageBox.Yes, QMessageBox.No
        )

        return confirmation == QMessageBox.Yes

    def request_next_page(self):
        self.current_page += 1
        self.search_geonode()

    def request_previous_page(self):
        self.current_page = max(self.current_page - 1, 1)
        self.search_geonode()

    def search_geonode(self):
        self.clear_search()
        self.search_btn.setEnabled(False)
        self.next_btn.setEnabled(False)
        self.previous_btn.setEnabled(False)
        self.message_bar.pushMessage(tr("Searching..."), level=Qgis.Info)
        connection_name = self.connections_cmb.currentText()
        connection = connections_manager.find_connection_by_name(connection_name)
        client = GeonodeClient.from_connection_settings(connection)
        # client.layer_list_received.connect(self.show_layers)
        client.layer_list_received.connect(self.handle_layer_list)
        client.layer_list_received.connect(self.handle_pagination)

        client.error_received.connect(self.show_search_error)
        if self.search_group_box.isChecked():
            title = self.free_text_edit.text()
            keyword = self.keywords_cmb.currentText()
            category = self.category_cmb.currentText().lower()
            resource_type_text = self.resource_type_cmb.currentText()
            resource_type_list = [resource_type for resource_type in GeonodeResourceType
                                  if resource_type.value == resource_type_text
                                  ]
            start_date_time = self.start_date_time.dateTime()
            end_date_time = self.end_date_time.dateTime()

            if self.free_text_box.isChecked():
                client.get_layers(
                    page=self.current_page,
                    title=title
                )
            elif self.keywords_box.isChecked():
                client.get_layers(
                    page=self.current_page,
                    keyword=keyword
                )
            elif self.category_box.isChecked():
                client.get_layers(
                    page=self.current_page,
                    topic_category=category
                )
            elif self.resource_type_box.isChecked():
                client.get_layers(
                    page=self.current_page,
                    layer_type=resource_type_list
                )
            else:
                client.get_layers(
                    page=self.current_page
                )

    def show_search_error(self, error):
        self.message_bar.clearWidgets()
        self.search_btn.setEnabled(True)
        network_error_enum = enum_mapping(QNetworkReply, QNetworkReply.NetworkError)
        self.message_bar.pushMessage(
            tr("Problem in searching, network error {} - {}").format(
                error, network_error_enum[error]
            ),
            level=Qgis.Critical,
        )

    def handle_layer_list(
            self,
            layer_list: typing.List[BriefGeonodeResource],
            total_records: int,
            current_page: int,
            page_size: int,
    ):
        self.message_bar.clearWidgets()
        self.search_btn.setEnabled(True)
        if len(layer_list) > 0:
            self.populate_scroll_area(layer_list)

    def handle_pagination(
            self,
            layer_list: typing.List[BriefGeonodeResource],
            total_records: int,
            current_page: int,
            page_size: int,
    ):
        self.current_page = current_page
        total_pages = math.ceil(total_records / page_size)
        self.previous_btn.setEnabled(self.current_page > 1)
        self.next_btn.setEnabled(self.current_page < total_pages)
        if total_records > 0:
            self.resultsLabel.setText(
                tr(
                    "Showing page {} of {} ({} results)".format(
                        self.current_page, total_pages, total_records
                    )
                )
            )
        else:
            self.resultsLabel.setText(tr("No results found"))

    def populate_scroll_area(self, layers: typing.List[BriefGeonodeResource]):
        scroll_container = QWidget()
        layout = QVBoxLayout()
        for layer in layers:
            search_result_widget = SearchResultWidget(
                self.message_bar, geonode_resource=layer
            )
            layout.addWidget(search_result_widget)
        scroll_container.setLayout(layout)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setWidget(scroll_container)

    def clear_search(self):
        self.scroll_area.setWidget(QWidget())
        self.resultsLabel.clear()
        self.previous_btn.setEnabled(False)
        self.next_btn.setEnabled(False)

    def populate_search_items(self):
        default_categories = [
            tr("Farming"), tr("Climatology Meteorology Atmosphere"),
            tr("Location"),tr("Intelligence Military"),
            tr("Transportation"), tr("Structure"),
            tr("Boundaries"), tr("Inland Waters"), tr("Planning Cadastre"),
            tr("Geoscientific Information"), tr("Elevation"), tr("Health"),
            tr("Biota"), tr("Oceans"), tr("Environment"),
            tr("Utilities Communication"),
            tr("Economy"), tr("Society"), tr("Imagery Base Maps Earth Cover")
        ]

        self.category_cmb.addItems(category for category in default_categories)

        self.resource_type_cmb.addItems(
            resource_type.value for resource_type in GeonodeResourceType
        )
        self.search_keywords()

    def search_keywords(self):
        connection_name = self.connections_cmb.currentText()
        if connection_name:
            connection = connections_manager.find_connection_by_name(connection_name)
            client = GeonodeClient.from_connection_settings(connection)
            client.keyword_list_received.connect(self.update_keywords)
            client.get_keywords()

    def update_keywords(
            self,
            keywords: typing.Optional[list] = None
    ):
        if keywords:
            self.keywords_cmb.addItems(keyword['text'] for keyword in keywords)
