import typing

import qgis.gui
from PyQt5 import QtCore, QtWidgets
from qgis.core import (
    Qgis,
    QgsMessageLog,
)

from .vendor.packaging.version import Version

MIN_SUPPORTED_VERSION = "4.0.0"
MAX_SUPPORTED_VERSION = "5.0.0dev0"

def validate_version(version: Version) -> bool:
    
    min = Version(MIN_SUPPORTED_VERSION)
    max = Version(MAX_SUPPORTED_VERSION)

    if version >= min and version < max:
        return True
    else:
        return False

def log(message: typing.Any, name: str = "qgis_geonode", debug: bool = True):
    level = Qgis.Info if debug else Qgis.Warning
    QgsMessageLog.logMessage(str(message), name, level=level)


def tr(text):
    """Get the translation for a string using Qt translation API."""

    # noinspection PyTypeChecker,PyArgumentList,PyCallByClass
    if type(text) != str:
        text = str(text)
    return QtCore.QCoreApplication.translate("QgisGeoNode", text)


def show_message(
    message_bar: qgis.gui.QgsMessageBar,
    message: str,
    level: typing.Optional[qgis.core.Qgis.MessageLevel] = qgis.core.Qgis.Info,
    add_loading_widget: bool = False,
) -> None:
    message_bar.clearWidgets()
    message_item = message_bar.createMessage(message)
    if add_loading_widget:
        progress_bar = QtWidgets.QProgressBar()
        progress_bar.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
        progress_bar.setMinimum(0)
        progress_bar.setMaximum(0)
        message_item.layout().addWidget(progress_bar)
    message_bar.pushWidget(message_item, level=level)
