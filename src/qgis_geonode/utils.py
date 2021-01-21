import typing

from PyQt5.QtCore import QCoreApplication

from qgis.core import QgsMessageLog, Qgis


def log(message: str, name: str = "qgis_geonode", debug: bool = True):
    level = Qgis.Info if debug else Qgis.Warning
    QgsMessageLog.logMessage(message, name, level=level)


def tr(text):
    """Get the translation for a string using Qt translation API."""

    # noinspection PyTypeChecker,PyArgumentList,PyCallByClass
    if type(text) != str:
        text = str(text)
    return QCoreApplication.translate("QgisGeoNode", text)
