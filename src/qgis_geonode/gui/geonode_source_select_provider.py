import logging
import os
import typing
from functools import partial

import qgis.core
from qgis.utils import iface
import qgis.gui
from qgis.PyQt import (
    QtCore,
    QtGui,
    QtWidgets,
)
from qgis.PyQt.uic import loadUiType

from ..apiclient import get_geonode_client
from ..apiclient import models
from ..conf import connections_manager
from ..gui.connection_dialog import ConnectionDialog
from ..gui.search_result_widget import SearchResultWidget
from ..utils import (
    IsoTopicCategory,
    log,
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
    abstract_le: QtWidgets.QLineEdit
    category_cmb: QtWidgets.QComboBox
    connections_cmb: QtWidgets.QComboBox
    current_page: int = 0
    edit_connection_btn: QtWidgets.QPushButton
    delete_connection_btn: QtWidgets.QPushButton
    keyword_cmb: QtWidgets.QComboBox
    keyword_tool_btn: QtWidgets.QToolButton
    load_connection_btn: QtWidgets.QPushButton
    map_chb: QtWidgets.QCheckBox
    message_bar: qgis.gui.QgsMessageBar
    next_btn: QtWidgets.QPushButton
    new_connection_btn: QtWidgets.QPushButton
    pagination_info_la: QtWidgets.QLabel
    previous_btn: QtWidgets.QPushButton
    publication_start_dte: qgis.gui.QgsDateTimeEdit
    publication_end_dte: qgis.gui.QgsDateTimeEdit
    raster_chb: QtWidgets.QCheckBox
    resource_types_btngrp: QtWidgets.QButtonGroup
    reverse_order_chb: QtWidgets.QCheckBox
    save_connection_btn: QtWidgets.QPushButton
    scroll_area: QtWidgets.QScrollArea
    search_btn: QtWidgets.QPushButton
    sort_field_cmb: QtWidgets.QComboBox
    spatial_extent_box: qgis.gui.QgsExtentGroupBox
    temporal_extent_start_dte: qgis.gui.QgsDateTimeEdit
    temporal_extent_end_dte: qgis.gui.QgsDateTimeEdit
    title_le: QtWidgets.QLineEdit
    total_pages: int = 0
    vector_chb: QtWidgets.QCheckBox

    search_started = QtCore.pyqtSignal()
    search_finished = QtCore.pyqtSignal(str)
    load_layer_started = QtCore.pyqtSignal()
    load_layer_finished = QtCore.pyqtSignal()

    def __init__(self, parent, fl, widgetMode):
        super().__init__(parent, fl, widgetMode)
        self.setupUi(self)
        self.project = qgis.core.QgsProject.instance()
        self.resource_types_btngrp.buttonClicked.connect(self.toggle_search_buttons)
        self.new_connection_btn.clicked.connect(self.add_connection)
        self.edit_connection_btn.clicked.connect(self.edit_connection)
        self.delete_connection_btn.clicked.connect(self.delete_connection)
        self.connections_cmb.currentIndexChanged.connect(
            self.toggle_connection_management_buttons
        )
        self.search_started.connect(self.handle_search_start)
        self.search_finished.connect(self.handle_search_end)

        self.connections_cmb.currentIndexChanged.connect(self.reset_search_controls)
        self.update_connections_combobox()
        self.toggle_connection_management_buttons()
        self.connections_cmb.activated.connect(self.update_current_connection)

        self.current_page = 1
        self.total_pages = 1
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
        self.grid_layout = QtWidgets.QGridLayout()
        self.message_bar = qgis.gui.QgsMessageBar()
        self.message_bar.setSizePolicy(
            QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Fixed
        )
        self.grid_layout.addWidget(self.scroll_area, 0, 0, 1, 1)
        self.grid_layout.addWidget(
            self.message_bar, 0, 0, 1, 1, alignment=QtCore.Qt.AlignTop
        )
        self.layout().insertLayout(4, self.grid_layout)

        self.keyword_tool_btn.clicked.connect(self.search_keywords)
        self.toggle_search_buttons()
        self.temporal_extent_start_dte.clear()
        self.temporal_extent_end_dte.clear()
        self.publication_start_dte.clear()
        self.publication_end_dte.clear()
        self.load_categories()
        self.load_sorting_fields(selected_by_default=models.OrderingType.NAME)

        # ATTENTION: the order of initialization of the self.spatial_extent_box widget
        # is crucial here. Only call self.spatial_extent_box.setMapCanvas() after
        # having called self.spatial_extent_box.setOutputExtentFromCurrent()
        epsg_4326 = qgis.core.QgsCoordinateReferenceSystem("EPSG:4326")
        self.spatial_extent_box.setOutputCrs(epsg_4326)
        map_canvas = iface.mapCanvas()
        current_crs = map_canvas.mapSettings().destinationCrs()
        self.spatial_extent_box.setCurrentExtent(current_crs.bounds(), current_crs)
        self.spatial_extent_box.setOutputExtentFromCurrent()
        self.spatial_extent_box.setMapCanvas(map_canvas)

        # we use these to control enabling/disabling UI controls during searches
        self._connection_controls = [
            self.connections_cmb,
            self.new_connection_btn,
            self.edit_connection_btn,
            self.delete_connection_btn,
            self.load_connection_btn,
            self.save_connection_btn,
        ]
        self._search_controls = [
            self.title_le,
            self.abstract_le,
            self.keyword_cmb,
            self.keyword_tool_btn,
            self.category_cmb,
            self.vector_chb,
            self.raster_chb,
            self.map_chb,
            self.temporal_extent_start_dte,
            self.temporal_extent_end_dte,
            self.publication_start_dte,
            self.publication_end_dte,
            self.search_btn,
            self.next_btn,
            self.previous_btn,
            self.sort_field_cmb,
            self.spatial_extent_box,
            self.reverse_order_chb,
            self.pagination_info_la,
        ]

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

    def toggle_search_buttons(self, enable: typing.Optional[bool] = None):
        enable_search = False
        enable_previous = False
        enable_next = False
        if enable is None or enable:
            if self.connections_cmb.currentText() != "":
                for check_box in self.resource_types_btngrp.buttons():
                    if check_box.isChecked():
                        enable_search = True
                        enable_previous = self.current_page > 1
                        enable_next = self.current_page < self.total_pages
                        break
        self.search_btn.setEnabled(enable_search)
        self.previous_btn.setEnabled(enable_previous)
        self.next_btn.setEnabled(enable_next)

    def toggle_connection_management_buttons(self):
        current_name = self.connections_cmb.currentText()
        enabled = current_name != ""
        self.edit_connection_btn.setEnabled(enabled)
        self.delete_connection_btn.setEnabled(enabled)

    def reset_search_controls(self):
        self.clear_search_results()
        self.current_page = 1
        self.total_pages = 1
        self.toggle_search_buttons()

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
        self.search_started.emit()
        connection_name = self.connections_cmb.currentText()
        connection_settings = connections_manager.find_connection_by_name(
            connection_name
        )
        client = self._get_api_client()
        client.layer_list_received.connect(self.handle_layer_list)
        client.error_received.connect(self.show_search_error)
        resource_types = []
        search_vector = self.vector_chb.isChecked()
        search_raster = self.raster_chb.isChecked()
        search_map = self.map_chb.isChecked()
        spatial_extent_epsg4326 = self.spatial_extent_box.outputExtent()
        if any((search_vector, search_raster, search_map)):
            if search_vector:
                resource_types.append(models.GeonodeResourceType.VECTOR_LAYER)
            if search_raster:
                resource_types.append(models.GeonodeResourceType.RASTER_LAYER)
            if search_map:
                resource_types.append(models.GeonodeResourceType.MAP)
            if reset_pagination:
                self.current_page = 1
                self.total_pages = 1
            temp_extent_start = self.temporal_extent_start_dte.dateTime()
            temp_extent_end = self.temporal_extent_end_dte.dateTime()
            pub_start = self.publication_start_dte.dateTime()
            pub_end = self.publication_end_dte.dateTime()
            client.get_layers(
                page=self.current_page,
                page_size=connection_settings.page_size,
                title=self.title_le.text() or None,
                abstract=self.abstract_le.text() or None,
                keyword=self.keyword_cmb.currentText() or None,
                topic_category=self.category_cmb.currentText().lower() or None,
                layer_types=resource_types,
                ordering_field=self.sort_field_cmb.currentData(QtCore.Qt.UserRole),
                reverse_ordering=self.reverse_order_chb.isChecked(),
                temporal_extent_start=(
                    temp_extent_start if not temp_extent_start.isNull() else None
                ),
                temporal_extent_end=(
                    temp_extent_end if not temp_extent_end.isNull() else None
                ),
                publication_date_start=pub_start if not pub_start.isNull() else None,
                publication_date_end=pub_end if not pub_end.isNull() else None,
                spatial_extent=spatial_extent_epsg4326,
            )

    def toggle_search_controls(self, enabled: bool):
        for widget in self._connection_controls + self._search_controls:
            widget.setEnabled(enabled)

    def handle_search_start(self):
        self.toggle_search_controls(False)
        self.clear_search_results()
        self.show_progress(tr("Searching..."))

    def handle_search_end(self, message: str):
        self.message_bar.clearWidgets()
        if message != "":
            self.show_message(message, level=qgis.core.Qgis.Critical)
        self.toggle_search_controls(True)
        self.toggle_search_buttons()

    def show_search_error(
        self, qt_error_message: str, http_status_code: int, http_status_reason: str
    ):
        if http_status_code != 0:
            http_error = f"{http_status_code!r} - {http_status_reason!r}"
        else:
            http_error = ""
        error_message = f"Request error: {' '.join((qt_error_message, http_error))}"
        self.search_finished.emit(error_message)

    def handle_layer_list(
        self,
        layer_list: typing.List[models.BriefGeonodeResource],
        pagination_info: models.GeoNodePaginationInfo,
    ):
        self.handle_pagination(pagination_info)
        if len(layer_list) > 0:
            scroll_container = QtWidgets.QWidget()
            layout = QtWidgets.QVBoxLayout()
            layout.setContentsMargins(1, 1, 1, 1)
            layout.setSpacing(1)
            client = self._get_api_client()
            for layer in layer_list:
                search_result_widget = SearchResultWidget(
                    layer,
                    client,
                )
                layout.addWidget(search_result_widget)
                layout.setAlignment(search_result_widget, QtCore.Qt.AlignTop)
            scroll_container.setLayout(layout)
            self.scroll_area.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOn)
            self.scroll_area.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
            self.scroll_area.setWidgetResizable(True)
            self.scroll_area.setWidget(scroll_container)
            self.message_bar.clearWidgets()
        self.search_finished.emit("")

    def handle_pagination(
        self,
        pagination_info: models.GeoNodePaginationInfo,
    ):
        self.current_page = pagination_info.current_page
        self.total_pages = pagination_info.total_pages
        if pagination_info.total_records > 0:
            self.pagination_info_la.setText(
                tr(
                    f"Showing page {self.current_page} of "
                    f"{pagination_info.total_pages} ({pagination_info.total_records} "
                    f"results)"
                )
            )
        else:
            self.pagination_info_la.setText(tr("No results found"))

    def clear_search_results(self):
        self.scroll_area.setWidget(QtWidgets.QWidget())
        self.pagination_info_la.clear()

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
