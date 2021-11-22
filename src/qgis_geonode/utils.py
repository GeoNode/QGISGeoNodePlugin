import enum
import typing

from PyQt5 import (
    QtCore,
    QtNetwork,
)

from qgis.core import (
    Qgis,
    QgsMessageLog,
    QgsNetworkReplyContent,
)


class ParsedNetworkReply(typing.NamedTuple):
    http_status_code: int
    http_status_reason: str
    qt_error: str


class IsoTopicCategory(enum.Enum):
    FARMING = "Farming"
    CLIMATOLOGY_METEOROLOGY_ATMOSPHERE = "Climatology Meteorology Atmosphere"
    LOCATION = "Location"
    INTELLIGENCE_MILITARY = "Intelligence Military"
    TRANSPORTATION = "Transportation"
    STRUCTURE = "Structure"
    BOUNDARIES = "Boundaries"
    INLAND_WATERS = "Inland Waters"
    PLANNING_CADASTRE = "Planning Cadastre"
    GEOSCIENTIFIC_INFORMATION = "Geoscientific Information"
    ELEVATION = "Elevation"
    HEALTH = "Health"
    BIOTA = "Biota"
    OCEANS = "Oceans"
    ENVIRONMENT = "Environment"
    UTILITIES_COMMUNICATION = "Utilities Communication"
    ECONOMY = "Economy"
    SOCIETY = "Society"
    IMAGERY_BASE_MAPS_EARTH_COVER = "Imagery Base Maps Earth Cover"


def log(message: typing.Any, name: str = "qgis_geonode", debug: bool = True):
    level = Qgis.Info if debug else Qgis.Warning
    QgsMessageLog.logMessage(str(message), name, level=level)


def tr(text):
    """Get the translation for a string using Qt translation API."""

    # noinspection PyTypeChecker,PyArgumentList,PyCallByClass
    if type(text) != str:
        text = str(text)
    return QtCore.QCoreApplication.translate("QgisGeoNode", text)


def parse_network_reply(reply: QgsNetworkReplyContent) -> ParsedNetworkReply:
    http_status_code = reply.attribute(
        QtNetwork.QNetworkRequest.HttpStatusCodeAttribute
    )
    http_status_reason = reply.attribute(
        QtNetwork.QNetworkRequest.HttpReasonPhraseAttribute
    )
    error = reply.error()
    if error == QtNetwork.QNetworkReply.NoError:
        qt_error = None
    else:
        qt_error = _get_qt_error(
            QtNetwork.QNetworkReply, QtNetwork.QNetworkReply.NetworkError, error
        )
    return ParsedNetworkReply(http_status_code, http_status_reason, qt_error)


def _get_qt_error(cls, enum, error: QtNetwork.QNetworkReply.NetworkError) -> str:
    """workaround for accessing unsubscriptable sip enum types

    from https://stackoverflow.com/a/39677321

    """

    mapping = {}
    for key in dir(cls):
        value = getattr(cls, key)
        if isinstance(value, enum):
            mapping[key] = value
            mapping[value] = key
    return mapping[error]
