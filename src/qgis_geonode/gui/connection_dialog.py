import os
import re
import typing
import uuid


import qgis.core
from qgis.gui import QgsMessageBar
from qgis.PyQt import (
    QtWidgets,
    QtCore,
    QtGui,
    QtXml,
)
from qgis.PyQt.uic import loadUiType

from .. import apiclient, network, utils
from ..apiclient.base import BaseGeonodeClient
from ..conf import (
    ConnectionSettings,
    WfsVersion,
    settings_manager,
)
from ..utils import tr
from ..vendor.packaging import version as packaging_version

DialogUi, _ = loadUiType(
    os.path.join(os.path.dirname(__file__), "../ui/connection_dialog.ui")
)


class ConnectionDialog(QtWidgets.QDialog, DialogUi):
    name_le: QtWidgets.QLineEdit
    url_le: QtWidgets.QLineEdit
    authcfg_acs: qgis.gui.QgsAuthConfigSelect
    page_size_sb: QtWidgets.QSpinBox
    wfs_version_cb: QtWidgets.QComboBox
    detect_wfs_version_pb: QtWidgets.QPushButton
    network_timeout_sb: QtWidgets.QSpinBox
    test_connection_pb: QtWidgets.QPushButton
    buttonBox: QtWidgets.QDialogButtonBox
    options_gb: QtWidgets.QGroupBox
    bar: qgis.gui.QgsMessageBar
    detected_version_gb: qgis.gui.QgsCollapsibleGroupBox
    detected_version_le: QtWidgets.QLineEdit
    detected_capabilities_lw: QtWidgets.QListWidget
    api_client_class_le: QtWidgets.QLineEdit

    connection_id: uuid.UUID
    remote_geonode_version: typing.Optional[
        typing.Union[packaging_version.Version, str]
    ]
    discovery_task: typing.Optional[network.NetworkRequestTask]
    geonode_client: BaseGeonodeClient = None

    def __init__(self, connection_settings: typing.Optional[ConnectionSettings] = None):
        super().__init__()
        self.setupUi(self)
        self._widgets_to_toggle_during_connection_test = [
            self.test_connection_pb,
            self.buttonBox,
            self.authcfg_acs,
            self.options_gb,
            self.connection_details,
            self.detected_version_gb,
        ]
        self.bar = QgsMessageBar()
        self.bar.setSizePolicy(
            QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Fixed
        )
        self.layout().insertWidget(0, self.bar, alignment=QtCore.Qt.AlignTop)
        self.discovery_task = None
        self._populate_wfs_version_combobox()
        if connection_settings is not None:
            self.connection_id = connection_settings.id
            self.remote_geonode_version = connection_settings.geonode_version
            self.name_le.setText(connection_settings.name)
            self.url_le.setText(connection_settings.base_url)
            self.authcfg_acs.setConfigId(connection_settings.auth_config)
            self.page_size_sb.setValue(connection_settings.page_size)
            wfs_version_index = self.wfs_version_cb.findData(
                connection_settings.wfs_version
            )
            self.wfs_version_cb.setCurrentIndex(wfs_version_index)
            if self.remote_geonode_version == network.UNSUPPORTED_REMOTE:
                utils.show_message(
                    self.bar,
                    tr("Invalid configuration. Correct GeoNode URL and/or test again."),
                    level=qgis.core.Qgis.Critical,
                )
        else:
            self.connection_id = uuid.uuid4()
            self.remote_geonode_version = None
        self.update_connection_details()
        self.buttonBox.button(QtWidgets.QDialogButtonBox.Ok).setEnabled(False)
        ok_signals = [
            self.name_le.textChanged,
            self.url_le.textChanged,
        ]
        for signal in ok_signals:
            signal.connect(self.update_ok_buttons)
        self.detect_wfs_version_pb.clicked.connect(self.detect_wfs_version)
        self.test_connection_pb.clicked.connect(self.test_connection)
        # disallow names that have a slash since that is not compatible with how we
        # are storing plugin state in QgsSettings
        self.name_le.setValidator(
            QtGui.QRegExpValidator(QtCore.QRegExp("[^\\/]+"), self.name_le)
        )
        self.update_ok_buttons()

    def _populate_wfs_version_combobox(self):
        self.wfs_version_cb.clear()
        for name, member in WfsVersion.__members__.items():
            self.wfs_version_cb.addItem(member.value, member)

    def detect_wfs_version(self):
        for widget in self._widgets_to_toggle_during_connection_test:
            widget.setEnabled(False)
        current_settings = self.get_connection_settings()
        query = QtCore.QUrlQuery()
        query.addQueryItem("service", "WFS")
        query.addQueryItem("request", "GetCapabilities")
        url = QtCore.QUrl(f"{current_settings.base_url}/gs/ows")
        url.setQuery(query)
        self.discovery_task = network.NetworkRequestTask(
            [network.RequestToPerform(url)],
            network_task_timeout=current_settings.network_requests_timeout,
            authcfg=current_settings.auth_config,
            description="Detect WFS version",
        )
        self.discovery_task.task_done.connect(self.handle_wfs_version_detection_test)
        utils.show_message(
            self.bar, tr("Detecting WFS version..."), add_loading_widget=True
        )
        qgis.core.QgsApplication.taskManager().addTask(self.discovery_task)

    def get_connection_settings(self) -> ConnectionSettings:
        return ConnectionSettings(
            id=self.connection_id,
            name=self.name_le.text().strip(),
            base_url=self.url_le.text().strip().rstrip("/"),
            auth_config=self.authcfg_acs.configId(),
            page_size=self.page_size_sb.value(),
            geonode_version=self.remote_geonode_version,
            wfs_version=self.wfs_version_cb.currentData(),
        )

    def test_connection(self):
        for widget in self._widgets_to_toggle_during_connection_test:
            widget.setEnabled(False)
        current_settings = self.get_connection_settings()
        self.discovery_task = network.NetworkRequestTask(
            [
                network.RequestToPerform(
                    QtCore.QUrl(f"{current_settings.base_url}/version.txt")
                )
            ],
            network_task_timeout=current_settings.network_requests_timeout,
            authcfg=current_settings.auth_config,
            description="Test GeoNode connection",
        )
        self.discovery_task.task_done.connect(self.handle_discovery_test)
        utils.show_message(
            self.bar, tr("Testing connection..."), add_loading_widget=True
        )
        qgis.core.QgsApplication.taskManager().addTask(self.discovery_task)

    def handle_discovery_test(self, task_result: bool):
        self.enable_post_test_connection_buttons()
        geonode_version = network.handle_discovery_test(
            task_result, self.discovery_task
        )
        if geonode_version is not None:
            self.remote_geonode_version = geonode_version
            message = "Connection is valid"
            level = qgis.core.Qgis.Info
        else:
            message = "Connection is not valid"
            level = qgis.core.Qgis.Critical
            self.remote_geonode_version = network.UNSUPPORTED_REMOTE
        utils.show_message(self.bar, message, level)
        self.update_connection_details()

    def handle_wfs_version_detection_test(self, task_result: bool):
        self.enable_post_test_connection_buttons()
        # TODO: set the default to WfsVersion.AUTO when this QGIS issue has been resolved:
        #
        # https://github.com/qgis/QGIS/issues/47254
        #
        default_version = WfsVersion.V_1_1_0
        version = default_version
        if task_result:
            response_contents = self.discovery_task.response_contents[0]
            if response_contents is not None and response_contents.qt_error is None:
                raw_response = response_contents.response_body
                detected_versions = _get_wfs_declared_versions(raw_response)
                preference_order = [
                    "1.1.0",
                    "2.0.0",
                    "1.0.0",
                ]
                for preference in preference_order:
                    if preference in detected_versions:
                        version = WfsVersion(preference)
                        break
                else:
                    version = default_version
            self.bar.clearWidgets()
        else:
            utils.show_message(
                self.bar,
                tr("Unable to detect WFS version"),
                level=qgis.core.Qgis.Warning,
            )
        index = self.wfs_version_cb.findData(version)
        self.wfs_version_cb.setCurrentIndex(index)

    def update_connection_details(self):
        invalid_version = (
            self.remote_geonode_version is None
            or self.remote_geonode_version == network.UNSUPPORTED_REMOTE
        )
        self.detected_capabilities_lw.clear()
        self.api_client_class_le.clear()
        self.detected_version_le.clear()
        if not invalid_version:
            self.detected_version_gb.setEnabled(True)
            current_settings = self.get_connection_settings()
            client: BaseGeonodeClient = apiclient.get_geonode_client(current_settings)
            self.detected_version_le.setText(str(current_settings.geonode_version))
            self.api_client_class_le.setText(client.__class__.__name__)
            self.detected_capabilities_lw.insertItems(
                0, [cap.name for cap in client.capabilities]
            )
        else:
            self.detected_version_gb.setEnabled(False)

    def enable_post_test_connection_buttons(self):
        for widget in self._widgets_to_toggle_during_connection_test:
            try:
                widget.setEnabled(True)
            except RuntimeError:
                pass
        self.update_ok_buttons()

    def accept(self):
        connection_settings = self.get_connection_settings()
        name_pattern = re.compile(
            f"^{connection_settings.name}$|^{connection_settings.name}(\(\d+\))$"
        )
        duplicate_names = []
        for connection_conf in settings_manager.list_connections():
            if connection_conf.id == connection_settings.id:
                continue  # we don't want to compare against ourselves
            if name_pattern.search(connection_conf.name) is not None:
                duplicate_names.append(connection_conf.name)
        if len(duplicate_names) > 0:
            connection_settings.name = (
                f"{connection_settings.name}({len(duplicate_names)})"
            )
        settings_manager.save_connection_settings(connection_settings)
        settings_manager.set_current_connection(connection_settings.id)
        super().accept()

    def update_ok_buttons(self):
        enabled_state = self.name_le.text() != "" and self.url_le.text() != ""
        self.buttonBox.button(QtWidgets.QDialogButtonBox.Ok).setEnabled(enabled_state)
        self.test_connection_pb.setEnabled(enabled_state)


def _get_wfs_declared_versions(raw_response: QtCore.QByteArray) -> typing.List[str]:
    """
    Parse capabilities response and retrieve WFS versions supported by the WFS server.
    """

    capabilities_doc = QtXml.QDomDocument()
    loaded = capabilities_doc.setContent(raw_response, True)
    result = []
    if loaded:
        root = capabilities_doc.documentElement()
        if not root.isNull():
            operations_meta_elements = root.elementsByTagName("ows:OperationsMetadata")
            operations_meta_element = operations_meta_elements.at(0)
            if not operations_meta_element.isNull():
                for operation_node in operations_meta_element.childNodes():
                    op_name = operation_node.attributes().namedItem("name").nodeValue()
                    if op_name == "GetCapabilities":
                        operation_el = operation_node.toElement()
                        for par_node in operation_el.elementsByTagName("ows:Parameter"):
                            param_name = (
                                par_node.attributes().namedItem("name").nodeValue()
                            )
                            if param_name == "AcceptVersions":
                                param_el = par_node.toElement()
                                for val_node in param_el.elementsByTagName("ows:Value"):
                                    result.append(val_node.firstChild().nodeValue())
    return result
