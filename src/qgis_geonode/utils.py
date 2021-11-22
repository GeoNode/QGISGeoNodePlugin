import enum
import typing

from PyQt5 import (
    QtCore,
)

from qgis.core import (
    Qgis,
    QgsMessageLog,
)


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
