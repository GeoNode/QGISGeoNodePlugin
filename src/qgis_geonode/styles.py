import typing

import qgis.core
from qgis.PyQt import QtXml

from . import (
    network,
    utils,
)
from .utils import log


def load_layer_sld(
    layer: qgis.core.QgsMapLayer, http_response: network.ParsedNetworkReply
) -> typing.Tuple[bool, str]:
    raw_sld = http_response.response_body
    log(f"raw_sld: {raw_sld}")
    sld_doc = utils.deserialize_sld_style(raw_sld)
    sld_root = sld_doc.documentElement()
    error_message = "Could not parse downloaded SLD document"
    result = False
    if not sld_root.isNull():
        sld_named_layer = sld_root.firstChildElement("NamedLayer")
        if not sld_named_layer.isNull():
            sld_load_error_msg = ""
            result = layer.readSld(sld_named_layer, sld_load_error_msg)
            error_message = ": ".join((error_message, sld_load_error_msg))
    log(error_message)
    return result, error_message


def get_usable_sld(
    http_response: network.ParsedNetworkReply,
) -> typing.Optional[QtXml.QDomElement]:
    raw_sld = http_response.response_body
    log(f"raw_sld: {raw_sld}")
    sld_doc = utils.deserialize_sld_style(raw_sld)
    sld_root = sld_doc.documentElement()
    error_message = "Could not parse downloaded SLD document"
    result = None
    if not sld_root.isNull():
        sld_named_layer = sld_root.firstChildElement("NamedLayer")
        if not sld_named_layer.isNull():
            result = sld_named_layer
    return result
