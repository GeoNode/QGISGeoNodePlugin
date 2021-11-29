import typing
from functools import partial
from pathlib import Path

import qgis.gui
from qgis.PyQt import (
    QtCore,
    QtGui,
    QtWidgets,
)
from qgis.PyQt.uic import loadUiType
from qgis.utils import iface

from ..apiclient import (
    base,
    get_geonode_client,
    models,
)
from .. import conf
from ..apiclient.models import ApiClientCapability
from ..gui.connection_dialog import ConnectionDialog
from ..gui.search_result_widget import SearchResultWidget
from .. import network
from ..utils import (
    IsoTopicCategory,
    log,
    tr,
)

WidgetUi, _ = loadUiType(Path(__file__).parent / "../ui/geonode_datasource_widget.ui")

_INVALID_CONNECTION_MESSAGE = (
    "Current connection is invalid. Please review connection settings."
)


class GeonodeDataSourceWidget(qgis.gui.QgsAbstractDataSourceWidget, WidgetUi):
    api_client: typing.Optional[base.BaseGeonodeClient] = None
    discovery_task: typing.Optional[network.ApiClientDiscovererTask]
    abstract_la: QtWidgets.QLabel
    abstract_le: QtWidgets.QLineEdit
    category_la: QtWidgets.QLabel
    category_cmb: QtWidgets.QComboBox
    connections_cmb: QtWidgets.QComboBox
    current_page: int = 0
    edit_connection_btn: QtWidgets.QPushButton
    delete_connection_btn: QtWidgets.QPushButton
    keyword_la: QtWidgets.QLabel
    keyword_le: QtWidgets.QLineEdit
    message_bar: qgis.gui.QgsMessageBar
    next_btn: QtWidgets.QPushButton
    new_connection_btn: QtWidgets.QPushButton
    pagination_info_la: QtWidgets.QLabel
    previous_btn: QtWidgets.QPushButton
    publication_date_box: qgis.gui.QgsCollapsibleGroupBox
    publication_start_dte: qgis.gui.QgsDateTimeEdit
    publication_end_dte: qgis.gui.QgsDateTimeEdit
    raster_chb: QtWidgets.QCheckBox
    resource_types_la: QtWidgets.QLabel
    resource_types_btngrp: QtWidgets.QButtonGroup
    reverse_order_chb: QtWidgets.QCheckBox
    scroll_area: QtWidgets.QScrollArea
    search_btn: QtWidgets.QPushButton
    sort_field_cmb: QtWidgets.QComboBox
    spatial_extent_box: qgis.gui.QgsExtentGroupBox
    temporal_extent_box: qgis.gui.QgsCollapsibleGroupBox
    temporal_extent_start_dte: qgis.gui.QgsDateTimeEdit
    temporal_extent_end_dte: qgis.gui.QgsDateTimeEdit
    title_la: QtWidgets.QLabel
    title_le: QtWidgets.QLineEdit
    total_pages: int = 0
    vector_chb: QtWidgets.QCheckBox

    search_started = QtCore.pyqtSignal()
    search_finished = QtCore.pyqtSignal(str)
    load_layer_started = QtCore.pyqtSignal()
    load_layer_finished = QtCore.pyqtSignal()

    _connection_controls = typing.List[QtWidgets.QWidget]
    _search_controls = typing.List[QtWidgets.QWidget]
    _search_filters = typing.List[QtWidgets.QWidget]
    _usable_search_filters = typing.List[QtWidgets.QWidget]
    _unusable_search_filters = typing.List[QtWidgets.QWidget]

    def __init__(self, parent, fl, widgetMode):
        super().__init__(parent, fl, widgetMode)
        self.setupUi(self)
        self.search_btn.setIcon(QtGui.QIcon(":/images/themes/default/search.svg"))
        self.next_btn.setIcon(
            QtGui.QIcon(":/images/themes/default/mActionAtlasNext.svg")
        )
        self.previous_btn.setIcon(
            QtGui.QIcon(":/images/themes/default/mActionAtlasPrev.svg")
        )
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

        self.project = qgis.core.QgsProject.instance()
        self.discovery_task = None
        self.current_page = 1
        self.total_pages = 1
        # we use these to control enabling/disabling UI controls during searches
        self._connection_controls = [
            self.connections_cmb,
            self.new_connection_btn,
            self.edit_connection_btn,
            self.delete_connection_btn,
        ]
        self._search_filters = [
            self.title_la,
            self.title_le,
            self.abstract_la,
            self.abstract_le,
            self.keyword_la,
            self.keyword_le,
            self.category_la,
            self.category_cmb,
            self.vector_chb,
            self.raster_chb,
            self.temporal_extent_box,
            self.publication_date_box,
            self.spatial_extent_box,
            self.resource_types_la,
        ]
        self._search_controls = [
            self.search_btn,
            self.next_btn,
            self.previous_btn,
            self.sort_field_cmb,
            self.reverse_order_chb,
            self.pagination_info_la,
        ]
        # these are populated below, based on the capabilities supported by the
        # api client
        self._usable_search_filters = []
        self._unusable_search_filters = []

        self.resource_types_btngrp.buttonClicked.connect(self.toggle_search_buttons)
        self.new_connection_btn.clicked.connect(
            partial(self.spawn_connection_config_dialog, True)
        )
        self.edit_connection_btn.clicked.connect(self.spawn_connection_config_dialog)
        self.delete_connection_btn.clicked.connect(self.delete_connection_configuration)
        self.connections_cmb.currentIndexChanged.connect(
            self.activate_connection_configuration
        )
        self.search_started.connect(self.handle_search_start)
        self.search_finished.connect(self.handle_search_end)

        # TODO: these signals should only be connected/disconnected when we update the
        #  GUI with the capabilities of the API client
        self.search_btn.clicked.connect(
            partial(self.search_geonode, reset_pagination=True)
        )
        self.next_btn.clicked.connect(self.request_next_page)
        self.previous_btn.clicked.connect(self.request_previous_page)

        self.temporal_extent_start_dte.clear()
        self.temporal_extent_end_dte.clear()
        self.publication_start_dte.clear()
        self.publication_end_dte.clear()

        self._load_categories()
        self._load_sorting_fields(selected_by_default=models.OrderingType.NAME)
        self._initialize_spatial_extent_box()
        self.title_le.textChanged.connect(self.store_search_filters)
        self.abstract_le.textChanged.connect(self.store_search_filters)
        self.keyword_le.textChanged.connect(self.store_search_filters)
        self.category_cmb.currentIndexChanged.connect(self.store_search_filters)
        self.resource_types_btngrp.buttonToggled.connect(self.store_search_filters)
        self.temporal_extent_start_dte.valueChanged.connect(self.store_search_filters)
        self.temporal_extent_end_dte.valueChanged.connect(self.store_search_filters)
        self.publication_start_dte.valueChanged.connect(self.store_search_filters)
        self.publication_end_dte.valueChanged.connect(self.store_search_filters)
        self.spatial_extent_box.extentChanged.connect(self.store_search_filters)
        self.sort_field_cmb.currentIndexChanged.connect(self.store_search_filters)
        self.reverse_order_chb.toggled.connect(self.store_search_filters)
        self.restore_search_filters()

        # this method calls connections_cmb.setCurrentIndex(), which in turn emits
        # connections_cmb.currentIndexChanged, which causes
        # self.activate_connection_configuration to run
        self.update_connections_combobox()

    def _initialize_spatial_extent_box(self):
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

    def toggle_connection_management_buttons(self):
        """Enable/disable connection edit and delete buttons."""
        current_name = self.connections_cmb.currentText()
        enabled = current_name != ""
        self.edit_connection_btn.setEnabled(enabled)
        self.delete_connection_btn.setEnabled(enabled)

    def spawn_connection_config_dialog(self, add_new: bool):
        if add_new:
            dialog = ConnectionDialog()
        else:
            connection_settings = (
                conf.settings_manager.get_current_connection_settings()
            )
            dialog = ConnectionDialog(connection_settings=connection_settings)
        dialog.exec_()
        self.update_connections_combobox()

    def delete_connection_configuration(self):
        name = self.connections_cmb.currentText()
        current_connection = conf.settings_manager.find_connection_by_name(name)
        if self._confirm_deletion(name):
            existing_connections = conf.settings_manager.list_connections()
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
            conf.settings_manager.delete_connection(current_connection.id)
            if next_current_connection is not None:
                conf.settings_manager.set_current_connection(next_current_connection.id)
            else:
                self.message_bar.clearWidgets()
            self.update_connections_combobox()

    def update_connections_combobox(self):
        """Populate the connections combobox with existing connection configurations

        Also, set the currently selected combobox item accordingly.

        """

        self.connections_cmb.clear()
        existing_connections = conf.settings_manager.list_connections()
        if len(existing_connections) > 0:
            # NOTE: self.connections_cmb.addItems() emits the currentIndexChanged
            # signal with the index of the first element that gets added. This causes
            # the self.activate_connection_configuration() method to run and eventually
            # messes the current connection settings up. As such, we store the id of
            # the current connection before adding items to the combo box and then,
            # after having added them, manually set the current connection back to the
            # original value
            current_id = conf.settings_manager.get_current_connection_settings().id
            self.connections_cmb.addItems(conn.name for conn in existing_connections)
            conf.settings_manager.set_current_connection(current_id)
            current_connection = conf.settings_manager.get_current_connection_settings()
            if current_connection is not None:
                current_index = self.connections_cmb.findText(current_connection.name)
            else:
                current_index = 0
            self.connections_cmb.setCurrentIndex(current_index)

    def activate_connection_configuration(self, index: int):
        self.toggle_connection_management_buttons()
        self.clear_search_results()
        self.current_page = 1
        self.total_pages = 1
        current_text = self.connections_cmb.itemText(index)
        try:
            current_connection = conf.settings_manager.find_connection_by_name(
                current_text
            )
        except ValueError:
            self.toggle_search_buttons(enable=False)
        else:
            conf.settings_manager.set_current_connection(current_connection.id)
            if current_connection.api_client_class_path == models.UNSUPPORTED_REMOTE:
                self.show_message(
                    tr(_INVALID_CONNECTION_MESSAGE), level=qgis.core.Qgis.Critical
                )
            else:
                if current_connection.api_client_class_path:
                    self.api_client = get_geonode_client(current_connection)
                    self.api_client.dataset_list_received.connect(
                        self.handle_dataset_list
                    )
                    self.api_client.error_received.connect(self.show_search_error)
                else:
                    # don't know if current config is valid or not yet, need to detect it
                    pass
            self.update_gui(current_connection)
        self.toggle_search_buttons()

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

    #
    # def update_current_connection(self, current_index: int):
    #     current_text = self.connections_cmb.itemText(current_index)
    #     try:
    #         current_connection = conf.settings_manager.find_connection_by_name(
    #             current_text
    #         )
    #     except ValueError:
    #         pass
    #     else:
    #         conf.settings_manager.set_current_connection(current_connection.id)
    #         self.api_client = get_geonode_client(current_connection)
    #         self.api_client.layer_list_received.connect(self.handle_layer_list)
    #         self.api_client.error_received.connect(self.show_search_error)
    #         self.update_gui(current_connection)

    def update_gui(self, connection_settings: conf.ConnectionSettings):
        """Update our UI based on the capabilities of the current API client"""
        for search_widget in self._search_controls:
            search_widget.setEnabled(True)
        self._usable_search_filters = self._get_usable_search_filters()
        self._unusable_search_filters = [
            i for i in self._search_filters if i not in self._usable_search_filters
        ]
        for usable_search_widget in self._usable_search_filters:
            usable_search_widget.setEnabled(True)
        for unusable_search_widget in self._unusable_search_filters:
            unusable_search_widget.setEnabled(False)

    def _get_usable_search_filters(self) -> typing.List:
        capabilities = self.api_client.capabilities if self.api_client else []
        result = []
        if ApiClientCapability.FILTER_BY_NAME in capabilities:
            result.extend((self.title_la, self.title_le))
        if ApiClientCapability.FILTER_BY_ABSTRACT in capabilities:
            result.extend((self.abstract_la, self.abstract_le))
        if ApiClientCapability.FILTER_BY_KEYWORD in capabilities:
            result.extend(
                (
                    self.keyword_la,
                    self.keyword_le,
                )
            )
        if ApiClientCapability.FILTER_BY_TOPIC_CATEGORY in capabilities:
            result.extend((self.category_la, self.category_cmb))
        if ApiClientCapability.FILTER_BY_RESOURCE_TYPES in capabilities:
            result.extend(
                (
                    self.resource_types_la,
                    self.vector_chb,
                    self.raster_chb,
                )
            )
        if ApiClientCapability.FILTER_BY_TEMPORAL_EXTENT in capabilities:
            result.append(self.temporal_extent_box)
        if ApiClientCapability.FILTER_BY_PUBLICATION_DATE in capabilities:
            result.append(self.publication_date_box)
        if ApiClientCapability.FILTER_BY_SPATIAL_EXTENT in capabilities:
            result.append(self.spatial_extent_box)
        return result

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

    def request_next_page(self):
        self.current_page += 1
        self.search_geonode()

    def request_previous_page(self):
        self.current_page = max(self.current_page - 1, 1)
        self.search_geonode()

    def discover_api_client(self, next_: typing.Callable, *next_args, **next_kwargs):
        current_connection = conf.settings_manager.get_current_connection_settings()
        self.discovery_task = network.ApiClientDiscovererTask(
            current_connection.base_url
        )
        self.discovery_task.discovery_finished.connect(
            partial(self.handle_api_client_discovery, next_, *next_args, **next_kwargs)
        )
        qgis.core.QgsApplication.taskManager().addTask(self.discovery_task)

    def handle_api_client_discovery(
        self, next_: typing.Callable, discovery_result, *next_args, **next_kwargs
    ):
        log(f"inside handle_api_client_discovery. locals: {locals()}")
        current_connection = conf.settings_manager.get_current_connection_settings()
        current_connection.api_client_class_path = discovery_result
        conf.settings_manager.save_connection_settings(current_connection)
        self.update_connections_combobox()
        next_(*next_args, **next_kwargs)

    def search_geonode(self, reset_pagination: bool = False):
        search_params = self.get_search_filters()
        if len(search_params.layer_types) > 0:
            self.search_started.emit()
            if reset_pagination:
                self.current_page = 1
                self.total_pages = 1
            current_connection = conf.settings_manager.get_current_connection_settings()
            if not current_connection.api_client_class_path:
                self.discover_api_client(
                    next_=self.search_geonode, reset_pagination=reset_pagination
                )
            elif self.api_client is None:
                self.search_finished.emit(tr(_INVALID_CONNECTION_MESSAGE))
            else:
                self.api_client.get_dataset_list(search_params)

    def toggle_search_controls(self, enabled: bool):
        for widget in self._unusable_search_filters:
            widget.setEnabled(False)
        for widget in self._usable_search_filters + self._search_controls:
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
        self,
        qt_error_message: str,
        http_status_code: int = 0,
        http_status_reason: str = None,
    ):
        if http_status_code != 0:
            http_error = f"{http_status_code!r} - {http_status_reason!r}"
        else:
            http_error = ""
        error_message = f"Request error: {' '.join((qt_error_message, http_error))}"
        self.search_finished.emit(error_message)

    def handle_dataset_list(
        self,
        dataset_list: typing.List[models.BriefGeonodeResource],
        pagination_info: models.GeonodePaginationInfo,
    ):
        """Handle incoming dataset list

        This method is called when the api client emits the `layer_list_received`
        signal. It expects to receive a list of brief dataset descriptions, as found
        on the remote GeoNode server.

        """

        self.handle_pagination(pagination_info)
        if len(dataset_list) > 0:
            scroll_container = QtWidgets.QWidget()
            layout = QtWidgets.QVBoxLayout()
            layout.setContentsMargins(1, 1, 1, 1)
            layout.setSpacing(1)
            for brief_dataset in dataset_list:
                search_result_widget = SearchResultWidget(
                    brief_dataset,
                    self.api_client,
                    data_source_widget=self,
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
        pagination_info: models.GeonodePaginationInfo,
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

    def _load_categories(self):
        self.category_cmb.addItem("", "")
        items_to_add = []
        for name, member in IsoTopicCategory.__members__.items():
            items_to_add.append((tr(member.value), name))
        items_to_add.sort()
        for display_name, data_ in items_to_add:
            self.category_cmb.addItem(display_name, data_)

    def _load_sorting_fields(self, selected_by_default: models.OrderingType):
        labels = {
            models.OrderingType.NAME: tr("Name"),
        }
        for ordering_type, item_text in labels.items():
            self.sort_field_cmb.addItem(item_text, ordering_type)
        self.sort_field_cmb.setCurrentIndex(
            self.sort_field_cmb.findData(selected_by_default, role=QtCore.Qt.UserRole)
        )

    def restore_search_filters(self):
        current_search_filters = conf.settings_manager.get_current_search_filters()
        self.keyword_le.setText(current_search_filters.keyword or "")
        self.title_le.setText(current_search_filters.title or "")
        self.abstract_le.setText(current_search_filters.abstract or "")
        if current_search_filters.topic_category is not None:
            index = self.category_cmb.findData(
                current_search_filters.topic_category.name
            )
            self.category_cmb.setCurrentIndex(index)

        if current_search_filters.temporal_extent_start is not None:
            self.temporal_extent_start_dte.setDateTime(
                current_search_filters.temporal_extent_start
            )
        if current_search_filters.temporal_extent_end is not None:
            self.temporal_extent_end_dte.setDateTime(
                current_search_filters.temporal_extent_end
            )
        if current_search_filters.publication_date_start is not None:
            self.publication_start_dte.setDateTime(
                current_search_filters.publication_date_start
            )
        if current_search_filters.publication_date_end is not None:
            self.publication_end_dte.setDateTime(
                current_search_filters.publication_date_end
            )
        if current_search_filters.spatial_extent is not None:
            self.spatial_extent_box.setOutputExtentFromUser(
                current_search_filters.spatial_extent,
                qgis.core.QgsCoordinateReferenceSystem("EPSG:4326"),
            )
        self.vector_chb.setChecked(
            (
                models.GeonodeResourceType.VECTOR_LAYER
                in current_search_filters.layer_types
            )
        )
        self.raster_chb.setChecked(
            (
                models.GeonodeResourceType.RASTER_LAYER
                in current_search_filters.layer_types
            )
        )
        # trigger actions when resource types buttons have been toggled
        self.resource_types_btngrp.buttonClicked.emit(None)
        sort_index = self.sort_field_cmb.findData(current_search_filters.ordering_field)
        self.sort_field_cmb.setCurrentIndex(sort_index)
        self.reverse_order_chb.setChecked(current_search_filters.reverse_ordering)

    def store_search_filters(self):
        """Store current search filters in the QGIS Settings."""
        current_search_params = self.get_search_filters()
        conf.settings_manager.store_current_search_filters(current_search_params)

    def get_search_filters(self) -> base.GeonodeApiSearchFilters:
        resource_types = []
        if self.vector_chb.isChecked():
            resource_types.append(models.GeonodeResourceType.VECTOR_LAYER)
        if self.raster_chb.isChecked():
            resource_types.append(models.GeonodeResourceType.RASTER_LAYER)
        temp_ex_start = self.temporal_extent_start_dte.dateTime()
        temp_ex_end = self.temporal_extent_end_dte.dateTime()
        pub_start = self.publication_start_dte.dateTime()
        pub_end = self.publication_end_dte.dateTime()
        try:
            current_raw_category = self.category_cmb.currentData()
            category = IsoTopicCategory[current_raw_category]
        except KeyError:
            category = None
        result = models.GeonodeApiSearchFilters(
            page=self.current_page,
            title=self.title_le.text() or None,
            abstract=self.abstract_le.text() or None,
            keyword=self.keyword_le.text() or None,
            topic_category=category,
            layer_types=resource_types,
            ordering_field=self.sort_field_cmb.currentData(QtCore.Qt.UserRole),
            reverse_ordering=self.reverse_order_chb.isChecked(),
            temporal_extent_start=temp_ex_start if not temp_ex_start.isNull() else None,
            temporal_extent_end=temp_ex_end if not temp_ex_end.isNull() else None,
            publication_date_start=pub_start if not pub_start.isNull() else None,
            publication_date_end=pub_end if not pub_end.isNull() else None,
            spatial_extent=self.spatial_extent_box.outputExtent(),
        )
        return result
