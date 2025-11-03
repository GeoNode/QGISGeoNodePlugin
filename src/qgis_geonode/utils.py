import typing
from urllib.parse import urlparse
import requests

import qgis.gui
from PyQt5 import QtCore, QtWidgets
from qgis.core import (
    Qgis,
    QgsMessageLog,
)

def has_metadata_api(base_url: str) -> bool:
    """
    Check if the GeoNode server exposes the /api/v2/metadata endpoint.
    
    Args:
        base_url: Base URL of GeoNode, e.g., "https://my-geonode.org"
    
    Returns:
        True if metadata endpoint exists (GeoNode 5+), False otherwise.
    """
    #FIXME replace the hardcoded /api/v2 with a clear var like api_client_link
    url = base_url.rstrip('/') + '/api/v2/'
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        return "metadata" in data
    except Exception:
        # network error, 404, 400, or JSON parsing issue → assume no metadata
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


def remove_comments_from_sld(element):
    child = element.firstChild()
    while not child.isNull():
        if child.isComment():
            element.removeChild(child)
        else:
            if child.isElement():
                remove_comments_from_sld(child)
        child = child.nextSibling()


def url_from_geoserver(base_url: str, raw_url: str):

    # Clean the URL path from trailing and back slashes
    url_path = urlparse(raw_url).path.strip("/")

    url_path = url_path.split("/")
    # re-join URL path without the geoserver path
    suffix = "/".join(url_path[1:])
    result = f"{base_url}/gs/{suffix}"

    return result


def sanitize_layer_name(name: str) -> str:
    chars_to_replace = [
        ">",
        "<",
        "|",
        " ",
    ]
    return "".join(c if c not in chars_to_replace else "_" for c in name)
