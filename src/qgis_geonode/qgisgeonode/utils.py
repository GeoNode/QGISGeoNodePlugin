import contextlib
import logging
import typing

from PyQt5.QtCore import QCoreApplication
from qgis.core import QgsSettings
from qgis.core import QgsMessageLog

from .default import SETTINGS_GROUP_NAME

logger = logging.getLogger(__name__)


def tr(text):
    """Get the translation for a string using Qt translation API."""

    # noinspection PyTypeChecker,PyArgumentList,PyCallByClass
    if type(text) != str:
        text = str(text)
    return QCoreApplication.translate("QgisGeoNode", text)


@contextlib.contextmanager
def qgis_settings(group_root: str):
    """A simple context manager to help managing our own settings in QgsSettings"""
    settings = QgsSettings()
    settings.beginGroup(group_root)
    try:
        yield settings
    finally:
        settings.endGroup()


class SettingsManager:
    """Manage saving/loading settings for the plugin in QgsSettings"""

    BASE_GROUP_NAME: str = "qgis_geonode"
    SELECTED_CONNECTION_KEY: str = "selected_connection"

    def list_connections(self) -> typing.List[str]:
        with qgis_settings(f"{self.BASE_GROUP_NAME}/connections") as settings:
            return settings.childGroups()

    def get_connection_settings(self, name) -> typing.Dict:
        details = {}
        with qgis_settings(self._get_connection_settings_base(name)) as settings:
            for key in settings.allKeys():
                details[key] = settings.value(key)
        if len(details) == 0:
            raise ValueError(f"Could not find a connection named {name!r} in QgsSettings")
        details["name"] = name
        return details

    def save_connection_settings(self, name, set_current: bool = True, **additional_settings):
        with qgis_settings(self._get_connection_settings_base(name)) as settings:
            for name, value in additional_settings.items():
                settings.setValue(name, value)
        if set_current:
            self.set_current_connection(name)

    def delete_connection(self, name: str):
        with qgis_settings(f"{self.BASE_GROUP_NAME}/connections") as settings:
            settings.remove(name)

    def get_current_connection(self) -> typing.Optional[typing.Dict]:
        current_name = None
        with qgis_settings(self.BASE_GROUP_NAME) as settings:
            current_name = settings.value(self.SELECTED_CONNECTION_KEY)
        if current_name is not None:
            group = self._get_connection_settings_base(current_name)
            with qgis_settings(group) as settings:
                result = self.get_connection_settings(current_name)
        else:
            result = None
        return result

    def set_current_connection(self, name: typing.Optional[str] = None):
        with qgis_settings(self.BASE_GROUP_NAME) as settings:
            settings.setValue(self.SELECTED_CONNECTION_KEY, name)

    def _get_connection_settings_base(self, name):
        return f"{self.BASE_GROUP_NAME}/connections/{name}"


settings_manager = SettingsManager()
#
#
# def get_connection_settings(name: str):
#     root = QgsSettings()
#     root.beginGroup(f"{SETTINGS_GROUP_NAME}/connections/{name}")
#     result = {"name": name}
#     for key in root.allKeys:
#         result[key] = root.value(key)
#     root.endGroup()
#     return result
#
#
# def save_connection_settings(
#         name: str,
#         set_currently_selected: bool = True,
#         **additional_settings
# ):
#     root = QgsSettings()
#     root.beginGroup(f"{SETTINGS_GROUP_NAME}/{name}")
#     for name, value in additional_settings.items():
#         root.setValue(name, value)
#     root.endGroup()
#     if set_currently_selected:
#         root.setValue(f"{SETTINGS_GROUP_NAME}/selected", name)
