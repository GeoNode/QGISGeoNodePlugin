import logging
import os
import typing
from functools import partial

import qgis.core
import qgis.gui
from qgis.PyQt import (
    QtCore,
    QtGui,
    QtNetwork,
    QtWidgets,
)
from qgis.PyQt.uic import loadUiType

from ..apiclient import get_geonode_client
from ..apiclient import models
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


class GeonodeSourceSelectProvider(qgis.gui.QgsSourceSelectProvider):
    def createDataSourceWidget(self, parent, fl, widgetMode):
        return GeonodeDataSourceWidget(parent, fl, widgetMode)

    def providerKey(self):
        return "geonodeprovider"

    def icon(self):
        return QtGui.QIcon(":/plugins/qgis_geonode/mIconGeonode.svg")

    def text(self):
        return tr("GeoNode Plugin Provider")

    def toolTip(self):
        return tr("Add Geonode Layer")

    def ordering(self):
        return qgis.gui.QgsSourceSelectProvider.OrderOtherProvider


class GeonodeDataSourceWidget(qgis.gui.QgsAbstractDataSourceWidget, WidgetUi):
    sort_field_cmb: QtWidgets.QComboBox
    search_btn: QtWidgets.QPushButton
    next_btn: QtWidgets.QPushButton
    previous_btn: QtWidgets.QPushButton
    message_bar: qgis.gui.QgsMessageBar

    def __init__(self, parent, fl, widgetMode):
        super().__init__(parent, fl, widgetMode)
        self.setupUi(self)
        self.project = qgis.core.QgsProject.instance()
        self.resource_types_btngrp.buttonClicked.connect(self.toggle_search_buttons)
        self.btnNew.clicked.connect(self.add_connection)
        self.btnEdit.clicked.connect(self.edit_connection)
        self.btnDelete.clicked.connect(self.delete_connection)
        self.connections_cmb.currentIndexChanged.connect(
            self.toggle_connection_management_buttons
        )
        self.connections_cmb.currentIndexChanged.connect(self.toggle_search_controls)
        self.update_connections_combobox()
        self.toggle_connection_management_buttons()
        self.connections_cmb.activated.connect(self.update_current_connection)

        self.current_page = 1
        self.search_btn.setIcon(QtGui.QIcon(":/images/themes/default/search.svg"))
        self.next_btn.setIcon(
            QtGui.QIcon(":/images/themes/default/mActionAtlasNext.svg")
        )
        self.previous_btn.setIcon(
            QtGui.QIcon(":/images/themes/default/mActionAtlasPrev.svg")
        )
        self.search_btn.clicked.connect(
            partial(self.search_geonode, reset_pagination=True)
        )
        self.next_btn.clicked.connect(self.request_next_page)
        self.previous_btn.clicked.connect(self.request_previous_page)
        self.next_btn_state = False
        self.previous_btn_state = False
        self.search_btn_state = True
        self.next_btn.setEnabled(self.next_btn_state)
        self.previous_btn.setEnabled(self.previous_btn_state)
        self.message_bar = qgis.gui.QgsMessageBar()
        self.message_bar.setSizePolicy(
            QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Fixed
        )
        self.layout().insertWidget(4, self.message_bar)

        self.keyword_tool_btn.clicked.connect(self.search_keywords)
        self.toggle_search_buttons()
        self.start_dte.clear()
        self.end_dte.clear()
        self.load_categories()
        self.load_sorting_fields(selected_by_default=models.OrderingType.NAME)

    def add_connection(self):
        connection_dialog = ConnectionDialog()
        connection_dialog.exec_()
        self.update_connections_combobox()

    def edit_connection(self):
        selected_name = self.connections_cmb.currentText()
        connection_settings = connections_manager.find_connection_by_name(selected_name)
        connection_dialog = ConnectionDialog(connection_settings=connection_settings)
        connection_dialog.exec_()
        self.update_connections_combobox()

    def delete_connection(self):
        name = self.connections_cmb.currentText()
        current_connection = connections_manager.find_connection_by_name(name)
        if self._confirm_deletion(name):
            existing_connections = connections_manager.list_connections()
            if len(existing_connections) == 1:
                next_current_connection = None
            else:
                for i in range(len(existing_connections)):
                    current_ = existing_connections[i]
                    if current_.id == current_connection.id:
                        try:
                            next_current_connection = existing_connections[i - 1]
                        except IndexError:
                            try:
                                next_current_connection = existing_connections[i + 1]
                            except IndexError:
                                next_current_connection = None
                        break
                else:
                    next_current_connection = None

            connections_manager.delete_connection(current_connection.id)
            if next_current_connection is not None:
                connections_manager.set_current_connection(next_current_connection.id)
            self.update_connections_combobox()

    def update_connections_combobox(self):
        existing_connections = connections_manager.list_connections()
        self.connections_cmb.clear()
        if len(existing_connections) > 0:
            self.connections_cmb.addItems(conn.name for conn in existing_connections)
            current_connection = connections_manager.get_current_connection()
            if current_connection is not None:
                current_index = self.connections_cmb.findText(current_connection.name)
                self.connections_cmb.setCurrentIndex(current_index)
            else:
                self.connections_cmb.setCurrentIndex(0)

    def toggle_search_buttons(self):
        search_buttons = {
            self.search_btn: self.search_btn_state,
            self.previous_btn: self.previous_btn_state,
            self.next_btn: self.next_btn_state,
        }
        for check_box in self.resource_types_btngrp.buttons():
            if check_box.isChecked():
                enabled = True
                break
        else:
            enabled = False
        for button, state in search_buttons.items():
            if enabled:
                button.setEnabled(state)
            else:
                button.setEnabled(enabled)

    def toggle_connection_management_buttons(self):
        current_name = self.connections_cmb.currentText()
        enabled = current_name != ""
        self.btnEdit.setEnabled(enabled)
        self.btnDelete.setEnabled(enabled)

    def toggle_search_controls(self):
        current_name = self.connections_cmb.currentText()
        enabled = current_name != ""
        self.search_btn.setEnabled(enabled)
        self.clear_search()
        self.current_page = 1

    def update_current_connection(self, current_index: int):
        current_text = self.connections_cmb.itemText(current_index)
        current_connection = connections_manager.find_connection_by_name(current_text)
        connections_manager.set_current_connection(current_connection.id)

    def _confirm_deletion(self, connection_name: str):
        message = tr('Remove the following connection "{}"?').format(connection_name)
        confirmation = QtWidgets.QMessageBox.warning(
            self,
            tr("QGIS GeoNode"),
            message,
            QtWidgets.QMessageBox.Yes,
            QtWidgets.QMessageBox.No,
        )

        return confirmation == QtWidgets.QMessageBox.Yes

    def request_next_page(self):
        self.current_page += 1
        self.search_geonode()

    def request_previous_page(self):
        self.current_page = max(self.current_page - 1, 1)
        self.search_geonode()

    def _get_api_client(self):
        connection_name = self.connections_cmb.currentText()
        connection_settings = connections_manager.find_connection_by_name(
            connection_name
        )
        return get_geonode_client(connection_settings)

    def show_progress(self, message):
        message_bar_item = self.message_bar.createMessage(message)
        progress_bar = QtWidgets.QProgressBar()
        progress_bar.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
        progress_bar.setMinimum(0)
        progress_bar.setMaximum(0)
        message_bar_item.layout().addWidget(progress_bar)
        self.message_bar.pushWidget(message_bar_item, qgis.core.Qgis.Info)

    def show_message(self, message: str, level=qgis.core.Qgis.Warning):
        self.message_bar.clearWidgets()
        self.message_bar.pushMessage(message, level=level)

    def search_geonode(self, reset_pagination: bool = False):
        self.clear_search()
        self.search_btn_state = False
        self.previous_btn_state = False
        self.next_btn_state = False
        self.search_btn.setEnabled(self.search_btn_state)
        self.next_btn.setEnabled(self.next_btn_state)
        self.previous_btn.setEnabled(self.previous_btn_state)
        self.show_progress(tr("Searching..."))
        connection_name = self.connections_cmb.currentText()
        connection_settings = connections_manager.find_connection_by_name(
            connection_name
        )
        client = self._get_api_client()
        client.layer_list_received.connect(self.handle_layer_list)
        client.layer_list_received.connect(self.handle_pagination)
        client.error_received.connect(self.show_search_error)
        resource_types = []
        search_vector = self.vector_chb.isChecked()
        search_raster = self.raster_chb.isChecked()
        search_map = self.map_chb.isChecked()
        if any((search_vector, search_raster, search_map)):
            if search_vector:
                resource_types.append(models.GeonodeResourceType.VECTOR_LAYER)
            if search_raster:
                resource_types.append(models.GeonodeResourceType.RASTER_LAYER)
            if search_map:
                resource_types.append(models.GeonodeResourceType.MAP)
            # FIXME: Implement these as search filters
            start = self.start_dte.dateTime()
            end = self.end_dte.dateTime()
            if reset_pagination:
                self.current_page = 1
            client.get_layers(
                page=self.current_page,
                page_size=connection_settings.page_size,
                title=self.title_le.text() or None,
                abstract=self.abstract_le.text() or None,
                keyword=self.keyword_cmb.currentText() or None,
                topic_category=self.category_cmb.currentText().lower() or None,
                layer_types=resource_types,
                ordering_field=self.sort_field_cmb.currentData(QtCore.Qt.UserRole),
                reverse_ordering=self.reverse_order_chk.isChecked(),
            )

    def show_search_error(self, error):
        self.message_bar.clearWidgets()
        self.search_btn_state = True
        self.search_btn.setEnabled(self.search_btn_state)
        network_error_enum = enum_mapping(
            QtNetwork.QNetworkReply, QtNetwork.QNetworkReply.NetworkError
        )
        self.show_message(
            tr(
                f"Problem in searching, network "
                f"error {error} - {network_error_enum[error]}"
            ),
            level=qgis.core.Qgis.Critical,
        )

    def handle_layer_list(
        self,
        layer_list: typing.List[models.BriefGeonodeResource],
        pagination_info: models.GeoNodePaginationInfo,
    ):
        if len(layer_list) > 0:
            self.populate_scroll_area(layer_list)

    def handle_pagination(
        self,
        layer_list: typing.List[models.BriefGeonodeResource],
        pagination_info: models.GeoNodePaginationInfo,
    ):
        self.current_page = pagination_info.current_page

        self.next_btn_state = self.current_page < pagination_info.total_pages
        self.previous_btn_state = self.current_page > 1

        self.previous_btn.setEnabled(self.previous_btn_state)
        self.next_btn.setEnabled(self.next_btn_state)

        if pagination_info.total_records > 0:
            self.resultsLabel.setText(
                tr(
                    f"Showing page {self.current_page} of {pagination_info.total_pages} "
                    f"({pagination_info.total_records} results)"
                )
            )
        else:
            self.resultsLabel.setText(tr("No results found"))

    def populate_scroll_area(self, layers: typing.List[models.BriefGeonodeResource]):
        scroll_container = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout()
        layout.setContentsMargins(1, 1, 1, 1)
        layout.setSpacing(1)
        client = self._get_api_client()
        for layer in layers:
            search_result_widget = SearchResultWidget(
                geonode_resource=layer,
                api_client=client,
            )
            layout.addWidget(search_result_widget)
            layout.setAlignment(search_result_widget, QtCore.Qt.AlignTop)
        scroll_container.setLayout(layout)
        self.scroll_area.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOn)
        self.scroll_area.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setWidget(scroll_container)
        self.message_bar.clearWidgets()
        self.search_btn_state = True
        self.search_btn.setEnabled(self.search_btn_state)

    def clear_search(self):
        self.scroll_area.setWidget(QtWidgets.QWidget())
        self.resultsLabel.clear()
        self.next_btn_state = False
        self.previous_btn_state = False
        self.previous_btn.setEnabled(self.previous_btn_state)
        self.next_btn.setEnabled(self.next_btn_state)

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

    def load_sorting_fields(self, selected_by_default: models.OrderingType):
        labels = {
            models.OrderingType.NAME: tr("Name"),
        }
        for ordering_type, item_text in labels.items():
            self.sort_field_cmb.addItem(item_text, ordering_type)
        self.sort_field_cmb.setCurrentIndex(
            self.sort_field_cmb.findData(selected_by_default, role=QtCore.Qt.UserRole)
        )

    def search_keywords(self):
        connection_name = self.connections_cmb.currentText()
        if connection_name:
            client = self._get_api_client()
            client.keyword_list_received.connect(self.update_keywords)
            client.error_received.connect(self.show_search_error)
            self.show_progress(tr("Searching for keywords..."))
            client.get_keywords()

    def update_keywords(self, keywords: typing.Optional[typing.List[str]] = None):
        if keywords:
            self.keyword_cmb.addItem("")
            self.keyword_cmb.addItems(keywords)
