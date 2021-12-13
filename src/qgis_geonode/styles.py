import typing

from PyQt5 import QtCore, QtXml
from qgis.PyQt import QtXml

from . import network


def deserialize_sld_style(
    raw_sld: QtCore.QByteArray,
) -> typing.Tuple[QtXml.QDomElement, str]:
    sld_doc = QtXml.QDomDocument()
    # in the line below, `True` means use XML namespaces and it is crucial for
    # QGIS to be able to load the SLD
    sld_loaded = sld_doc.setContent(raw_sld, True)
    error_message = "Could not parse downloaded SLD document"
    named_layer_element = None
    if sld_loaded:
        root = sld_doc.documentElement()
        if not root.isNull():
            sld_named_layer = root.firstChildElement("NamedLayer")
            if not sld_named_layer.isNull():
                named_layer_element = sld_named_layer
                error_message = ""
    return named_layer_element, error_message


# TODO: refactor in order to not need this 2-line function
def get_usable_sld(
    http_response: network.ParsedNetworkReply,
) -> typing.Tuple[typing.Optional[QtXml.QDomElement], str]:
    raw_sld = http_response.response_body
    return deserialize_sld_style(raw_sld)
