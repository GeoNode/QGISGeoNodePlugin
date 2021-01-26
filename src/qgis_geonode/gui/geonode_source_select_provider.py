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

from ..apiclient import get_geonode_client
from ..apiclient.models import (
    BriefGeonodeResource,
    GeonodeResourceType,
)
from ..conf import connections_manager
from ..gui.connection_dialog import ConnectionDialog
from ..gui.search_result_widget import SearchResultWidget
from ..utils import (
    enum_mapping,
    IsoTopicCategory,
    tr,
)

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
        self.resource_types_btngrp.buttonClicked.connect(self.toggle_search_buttons)
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

        self.keyword_tool_btn.clicked.connect(self.search_keywords)
        self.toggle_search_buttons()
        self.start_dte.clear()
        self.end_dte.clear()
        self.load_categories()

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

    def toggle_search_buttons(self):
        search_buttons = (
            self.search_btn,
            self.previous_btn,
            self.next_btn,
        )
        for check_box in self.resource_types_btngrp.buttons():
            if check_box.isChecked():
                enabled = True
                break
        else:
            enabled = False
        for button in search_buttons:
            button.setEnabled(enabled)

    def toggle_connection_management_buttons(self):
        enabled = len(connections_manager.list_connections()) > 0
        self.btnEdit.setEnabled(enabled)
        self.btnDelete.setEnabled(enabled)
        self.search_btn.setEnabled(enabled)
        self.clear_search()
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
        connection_settings = connections_manager.find_connection_by_name(connection_name)
        client = get_geonode_client(connection_settings)
        client.layer_list_received.connect(self.handle_layer_list)
        client.layer_list_received.connect(self.handle_pagination)
        client.error_received.connect(self.show_search_error)
        resource_types = []
        search_vector = self.vector_chb.isChecked()
        search_raster = self.raster_chb.isChecked()
        search_map = self.map_chb.isChecked()
        if any((search_vector, search_raster, search_map)):
            if search_vector:
                resource_types.append(GeonodeResourceType.VECTOR_LAYER)
            if search_raster:
                resource_types.append(GeonodeResourceType.RASTER_LAYER)
            if search_map:
                resource_types.append(GeonodeResourceType.MAP)
            # FIXME: Implement these as search filters
            start = self.start_dte.dateTime()
            end = self.end_dte.dateTime()
            client.get_layers(
                page=self.current_page,
                title=self.title_le.text() or None,
                abstract=self.abstract_le.text() or None,
                keyword=self.keyword_cmb.currentText() or None,
                topic_category=self.category_cmb.currentText().lower() or None,
                layer_types=resource_types,
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

    def load_categories(self):
        self.category_cmb.addItems(
            [
                "",
                tr(IsoTopicCategory.FARMING.value),
                tr(IsoTopicCategory.CLIMATOLOGY_METEOROLOGY_ATMOSPHERE.value),
                tr(IsoTopicCategory.LOCATION.value),
                tr(IsoTopicCategory.INTELLIGENCE_MILITARY.value),
                tr(IsoTopicCategory.TRANSPORTATION.value),
                tr(IsoTopicCategory.STRUCTURE.value),
                tr(IsoTopicCategory.BOUNDARIES.value),
                tr(IsoTopicCategory.INLAND_WATERS.value),
                tr(IsoTopicCategory.PLANNING_CADASTRE.value),
                tr(IsoTopicCategory.GEOSCIENTIFIC_INFORMATION.value),
                tr(IsoTopicCategory.ELEVATION.value),
                tr(IsoTopicCategory.HEALTH.value),
                tr(IsoTopicCategory.BIOTA.value),
                tr(IsoTopicCategory.OCEANS.value),
                tr(IsoTopicCategory.ENVIRONMENT.value),
                tr(IsoTopicCategory.UTILITIES_COMMUNICATION.value),
                tr(IsoTopicCategory.ECONOMY.value),
                tr(IsoTopicCategory.SOCIETY.value),
                tr(IsoTopicCategory.IMAGERY_BASE_MAPS_EARTH_COVER.value),
            ]
        )

    def search_keywords(self):
        connection_name = self.connections_cmb.currentText()
        if connection_name:
            connection = connections_manager.find_connection_by_name(connection_name)
            client = get_geonode_client(connection)
            client.keyword_list_received.connect(self.update_keywords)
            client.error_received.connect(self.show_search_error)

            self.message_bar.pushMessage(
                tr("Searching for keywords..."), level=Qgis.Info
            )

            client.get_keywords()

    def update_keywords(self, keywords: typing.Optional[typing.List[str]] = None):
        if keywords:
            self.keyword_cmb.addItem("")
            self.keyword_cmb.addItems(keywords)
