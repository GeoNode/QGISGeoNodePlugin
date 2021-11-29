import enum
import typing

from PyQt5 import (
    QtCore,
)

from qgis.core import (
    Qgis,
    QgsMessageLog,
)


# NOTE: for simplicity, this enum's variants are named directly after the GeoNode
# topic_category ids.
class IsoTopicCategory(enum.Enum):
    biota = "Biota"
    boundaries = "Boundaries"
    climatologyMeteorologyAtmosphere = "Climatology Meteorology Atmosphere"
    economy = "Economy"
    elevation = "Elevation"
    environment = "Environment"
    farming = "Farming"
    geoscientificInformation = "Geoscientific Information"
    health = "Health"
    imageryBaseMapsEarthCover = "Imagery Base Maps Earth Cover"
    inlandWaters = "Inland Waters"
    intelligenceMilitary = "Intelligence Military"
    location = "Location"
    oceans = "Oceans"
    planningCadastre = "Planning Cadastre"
    society = "Society"
    structure = "Structure"
    transportation = "Transportation"
    utilitiesCommunication = "Utilities Communication"


def log(message: typing.Any, name: str = "qgis_geonode", debug: bool = True):
    level = Qgis.Info if debug else Qgis.Warning
    QgsMessageLog.logMessage(str(message), name, level=level)


def tr(text):
    """Get the translation for a string using Qt translation API."""

    # noinspection PyTypeChecker,PyArgumentList,PyCallByClass
    if type(text) != str:
        text = str(text)
    return QtCore.QCoreApplication.translate("QgisGeoNode", text)
