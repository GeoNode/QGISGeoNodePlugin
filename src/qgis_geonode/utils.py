import typing

from PyQt5 import (
    QtCore,
    QtXml,
)

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


def deserialize_sld_style(raw_sld: QtCore.QByteArray) -> QtXml.QDomDocument:
    sld_doc = QtXml.QDomDocument()
    # in the line below, `True` means use XML namespaces and it is crucial for
    # QGIS to be able to load the SLD
    sld_loaded = sld_doc.setContent(raw_sld, True)
    if not sld_loaded:
        raise RuntimeError("Could not load downloaded SLD document")
    return sld_doc
