import typing

from PyQt5 import QtCore, QtXml
from qgis.PyQt import QtXml

from . import network


def deserialize_sld_doc(
    raw_sld_doc: QtCore.QByteArray,
) -> typing.Tuple[typing.Optional[QtXml.QDomElement], str]:
    """Deserialize SLD document gotten from GeoNode into a usable named layer element"""
    sld_doc = QtXml.QDomDocument()
    # in the line below, `True` means use XML namespaces and it is crucial for
    # QGIS to be able to load the SLD
    sld_loaded = sld_doc.setContent(raw_sld_doc, True)
    error_message = "Could not parse SLD document"
    named_layer_element = None
    if sld_loaded:
        root = sld_doc.documentElement()
        if not root.isNull():
            sld_named_layer = root.firstChildElement("NamedLayer")
            if not sld_named_layer.isNull():
                named_layer_element = sld_named_layer
                error_message = ""
    return named_layer_element, error_message


def deserialize_sld_named_layer(
    raw_sld_named_layer: str,
) -> typing.Tuple[typing.Optional[QtXml.QDomElement], str]:
    """Deserialize the SLD named layer element which is used to style QGIS layers."""
    sld_doc = QtXml.QDomDocument()
    sld_loaded = sld_doc.setContent(
        QtCore.QByteArray(raw_sld_named_layer.encode()), True
    )
    error_message = "Could not parse SLD document"
    named_layer_element = None
    if sld_loaded:
        named_layer_element = sld_doc.documentElement()
        if not named_layer_element.isNull():
            error_message = ""
    return named_layer_element, error_message


def serialize_sld_named_layer(sld_named_layer: QtXml.QDomElement) -> str:
    buffer_ = QtCore.QByteArray()
    stream = QtCore.QTextStream(buffer_)
    sld_named_layer.save(stream, 0)
    return buffer_.data().decode(encoding="utf-8")


def get_usable_sld(
    http_response: network.ParsedNetworkReply,
) -> typing.Tuple[typing.Optional[QtXml.QDomElement], str]:
    raw_sld = http_response.response_body
    return deserialize_sld_doc(raw_sld)
