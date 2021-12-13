import typing

from PyQt5 import QtCore, QtXml
from qgis.PyQt import QtXml

from . import network


def deserialize_sld_style(raw_sld: QtCore.QByteArray) -> QtXml.QDomDocument:
    sld_doc = QtXml.QDomDocument()
    # in the line below, `True` means use XML namespaces and it is crucial for
    # QGIS to be able to load the SLD
    sld_loaded = sld_doc.setContent(raw_sld, True)
    if not sld_loaded:
        raise RuntimeError("Could not load downloaded SLD document")
    return sld_doc


def get_usable_sld(
    http_response: network.ParsedNetworkReply,
) -> typing.Tuple[typing.Optional[QtXml.QDomElement], str]:
    raw_sld = http_response.response_body
    sld_doc = deserialize_sld_style(raw_sld)
    sld_root = sld_doc.documentElement()
    error_message = "Could not parse downloaded SLD document"
    result = None
    if not sld_root.isNull():
        sld_named_layer = sld_root.firstChildElement("NamedLayer")
        if not sld_named_layer.isNull():
            result = sld_named_layer
            error_message = ""
    return result, error_message
