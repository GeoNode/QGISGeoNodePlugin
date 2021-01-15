import contextlib
import logging
import typing

from qgis.PyQt import QtCore
from qgis.core import QgsSettings

logger = logging.getLogger(__name__)


@contextlib.contextmanager
def qgis_settings(group_root: str):
    """A simple context manager to help managing our own settings in QgsSettings"""
    settings = QgsSettings()
    settings.beginGroup(group_root)
    try:
        yield settings
    finally:
        settings.endGroup()


class SettingsManager(QtCore.QObject):
    """Manage saving/loading settings for the plugin in QgsSettings"""

    BASE_GROUP_NAME: str = "qgis_geonode"
    SELECTED_CONNECTION_KEY: str = "selected_connection"

    current_connection_changed = QtCore.pyqtSignal(str)

    def list_connections(self) -> typing.List[str]:
        with qgis_settings(f"{self.BASE_GROUP_NAME}/connections") as settings:
            result = settings.childGroups()
        result.sort()
        return result

    def get_connection_settings(self, name) -> typing.Dict:
        details = {}
        with qgis_settings(self._get_connection_settings_base(name)) as settings:
            for key in settings.allKeys():
                details[key] = settings.value(key)
        if len(details) == 0:
            raise ValueError(
                f"Could not find a connection named {name!r} in QgsSettings"
            )
        details["name"] = name
        return details

    def save_connection_settings(self, name, **additional_settings):
        with qgis_settings(self._get_connection_settings_base(name)) as settings:
            for name, value in additional_settings.items():
                settings.setValue(name, value)

    def delete_connection(self, name: str):
        with qgis_settings(f"{self.BASE_GROUP_NAME}/connections") as settings:
            settings.remove(name)
        self.set_current_connection()

    def get_current_connection(self) -> typing.Optional[str]:
        with qgis_settings(self.BASE_GROUP_NAME) as settings:
            return settings.value(self.SELECTED_CONNECTION_KEY)

    def set_current_connection(
        self, name: typing.Optional[str] = None
    ) -> typing.Optional[str]:
        """Modify the current connection"""
        if name is not None and name not in self.list_connections():
            raise ValueError(f"Invalid connection name: {name!r}")
        previous_current = self.get_current_connection()
        with qgis_settings(self.BASE_GROUP_NAME) as settings:
            settings.setValue(self.SELECTED_CONNECTION_KEY, name)
        if name is None and previous_current is not None:
            self.current_connection_changed.emit("")
        elif name is not None and previous_current is None:
            self.current_connection_changed.emit(name)
        elif name is not None and previous_current != name:
            self.current_connection_changed.emit(name)
        else:
            pass
        return name

    def _get_connection_settings_base(self, name):
        return f"{self.BASE_GROUP_NAME}/connections/{name}"


settings_manager = SettingsManager()
