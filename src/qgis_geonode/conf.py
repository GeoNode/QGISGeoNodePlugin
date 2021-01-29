import contextlib
import dataclasses
import logging
import typing
import uuid

from qgis.PyQt import QtCore
from qgis.core import QgsSettings

from .apiclient import GeonodeApiVersion

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


@dataclasses.dataclass
class ConnectionSettings:
    """Helper class to manage settings for a Connection"""

    id: uuid.UUID
    name: str
    base_url: str
    api_version: GeonodeApiVersion
    auth_config: typing.Optional[str] = None

    @classmethod
    def from_qgs_settings(cls, connection_identifier: str, settings: QgsSettings):
        reported_auth_cfg = settings.value("auth_config").strip()
        return cls(
            id=uuid.UUID(connection_identifier),
            name=settings.value("name"),
            base_url=settings.value("base_url"),
            api_version=GeonodeApiVersion[settings.value("api_version")],
            auth_config=reported_auth_cfg if reported_auth_cfg != "" else None,
        )


class ConnectionManager(QtCore.QObject):
    """Manage saving/loading settings for the plugin in QgsSettings"""

    BASE_GROUP_NAME: str = "qgis_geonode"
    SELECTED_CONNECTION_KEY: str = "selected_connection"

    current_connection_changed = QtCore.pyqtSignal(str)

    def list_connections(self) -> typing.List[ConnectionSettings]:
        result = []
        with qgis_settings(f"{self.BASE_GROUP_NAME}/connections") as settings:
            for connection_id in settings.childGroups():
                connection_settings_key = self._get_connection_settings_base(
                    connection_id
                )
                with qgis_settings(connection_settings_key) as connection_settings:
                    result.append(
                        ConnectionSettings.from_qgs_settings(
                            connection_id, connection_settings
                        )
                    )
        result.sort(key=lambda obj: obj.name)
        return result

    def delete_all_connections(self):
        with qgis_settings(f"{self.BASE_GROUP_NAME}/connections") as settings:
            for connection_name in settings.childGroups():
                settings.remove(connection_name)
        self.clear_current_connection()

    def find_connection_by_name(self, name) -> ConnectionSettings:
        with qgis_settings(f"{self.BASE_GROUP_NAME}/connections") as settings:
            for connection_id in settings.childGroups():
                connection_settings_key = self._get_connection_settings_base(
                    connection_id
                )
                with qgis_settings(connection_settings_key) as connection_settings:
                    connection_name = connection_settings.value("name")
                    if connection_name == name:
                        found_id = uuid.UUID(connection_id)
                        break
            else:
                raise ValueError(
                    f"Could not find a connection named {name!r} in QgsSettings"
                )
        return self.get_connection_settings(found_id)

    def get_connection_settings(self, connection_id: uuid.UUID) -> ConnectionSettings:
        settings_key = self._get_connection_settings_base(connection_id)
        with qgis_settings(settings_key) as settings:
            connection_settings = ConnectionSettings.from_qgs_settings(
                str(connection_id), settings
            )
        return connection_settings

    def save_connection_settings(self, connection_settings: ConnectionSettings):
        settings_key = self._get_connection_settings_base(connection_settings.id)
        with qgis_settings(settings_key) as settings:
            settings.setValue("name", connection_settings.name)
            settings.setValue("base_url", connection_settings.base_url)
            settings.setValue("auth_config", connection_settings.auth_config)
            settings.setValue("api_version", connection_settings.api_version.name)

    def delete_connection(self, connection_id: uuid.UUID):
        with qgis_settings(f"{self.BASE_GROUP_NAME}/connections") as settings:
            settings.remove(str(connection_id))
        if self.is_current_connection(connection_id):
            self.clear_current_connection()

    def get_current_connection(self) -> typing.Optional[ConnectionSettings]:
        with qgis_settings(self.BASE_GROUP_NAME) as settings:
            current = settings.value(self.SELECTED_CONNECTION_KEY)
        if current is not None:
            result = self.get_connection_settings(uuid.UUID(current))
        else:
            result = None
        return result

    def set_current_connection(self, connection_id: uuid.UUID):
        if connection_id not in [conn.id for conn in self.list_connections()]:
            raise ValueError(f"Invalid connection identifier: {connection_id!r}")
        serialized_id = str(connection_id)
        with qgis_settings(self.BASE_GROUP_NAME) as settings:
            settings.setValue(self.SELECTED_CONNECTION_KEY, serialized_id)
        self.current_connection_changed.emit(serialized_id)

    def clear_current_connection(self):
        with qgis_settings(self.BASE_GROUP_NAME) as settings:
            settings.setValue(self.SELECTED_CONNECTION_KEY, None)
        self.current_connection_changed.emit("")

    def is_current_connection(self, connection_id: uuid.UUID):
        current = self.get_current_connection()
        return False if current is None else current.id == connection_id

    def _get_connection_settings_base(self, identifier: typing.Union[str, uuid.UUID]):
        return f"{self.BASE_GROUP_NAME}/connections/{str(identifier)}"


connections_manager = ConnectionManager()
