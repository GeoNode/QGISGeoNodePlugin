import typing

import qgis.gui
from PyQt5 import QtCore, QtWidgets
from qgis.core import (
    Qgis,
    QgsMessageLog,
)

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
