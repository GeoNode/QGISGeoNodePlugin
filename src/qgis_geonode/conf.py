import contextlib
import dataclasses
import logging
import typing
import uuid

from qgis.PyQt import (
    QtCore,
    QtWidgets,
)
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


class ApiVersionSpecificSettings:
    PREFIX = "api_version_settings"

    @classmethod
    def from_qgs_settings(cls, settings: QgsSettings):
        raise NotImplementedError

    @classmethod
    def from_widgets(cls, ancestor: QtWidgets.QWidget):
        raise NotImplementedError

    @classmethod
    def get_widgets(cls):
        raise NotImplementedError

    def fill_widgets(self, ancestor: QtWidgets.QWidget):
        raise NotImplementedError

    def to_qgs_settings(self):
        raise NotImplementedError


@dataclasses.dataclass
class GeonodeCswSpecificConnectionSettings(ApiVersionSpecificSettings):
    username: typing.Optional[str] = None
    password: typing.Optional[str] = None
    _username_widget_name: str = "username_le"
    _password_widget_name: str = "password_le"

    @classmethod
    def from_qgs_settings(cls, settings: QgsSettings):
        api_version_settings = settings.value(cls.PREFIX)
        return cls(
            username=api_version_settings["username"],
            password=api_version_settings["password"],
        )

    @classmethod
    def from_widgets(cls, ancestor: QtWidgets.QWidget):
        username_le = ancestor.findChild(
            QtWidgets.QLineEdit, cls._username_widget_name)
        password_le = ancestor.findChild(
            QtWidgets.QLineEdit, cls._password_widget_name)
        return cls(
            username=username_le.text() or None,
            password=password_le.text() or None
        )

    @classmethod
    def get_widgets(cls) -> QtWidgets.QLayout:
        username_le = QtWidgets.QLineEdit()
        username_le.setObjectName(cls._username_widget_name)
        password_le = QtWidgets.QLineEdit()
        password_le.setObjectName(cls._password_widget_name)
        layout = QtWidgets.QFormLayout()
        layout.addRow(QtWidgets.QLabel("Username"), username_le)
        layout.addRow(QtWidgets.QLabel("Password"), password_le)
        return layout

    def fill_widgets(self, ancestor: QtWidgets.QWidget):
        if self.username is not None:
            username_le = ancestor.findChild(
                QtWidgets.QLineEdit, self._username_widget_name)
            username_le.setText(self.username)
        if self.password is not None:
            password_le = ancestor.findChild(
                QtWidgets.QLineEdit, self._password_widget_name)
            password_le.setText(self.password)

    def to_qgs_settings(self) -> typing.Dict:
        return {
            "username": self.username,
            "password": self.password
        }


def get_api_version_settings_handler(
        api_version: GeonodeApiVersion) -> typing.Optional[typing.Type]:
    return {
        GeonodeApiVersion.OGC_CSW: GeonodeCswSpecificConnectionSettings,
    }.get(api_version)


@dataclasses.dataclass
class ConnectionSettings:
    """Helper class to manage settings for a Connection"""

    id: uuid.UUID
    name: str
    base_url: str
    api_version: GeonodeApiVersion
    page_size: int
    api_version_settings: typing.Optional[
        typing.Union[GeonodeCswSpecificConnectionSettings]] = None
    auth_config: typing.Optional[str] = None

    @classmethod
    def from_qgs_settings(cls, connection_identifier: str, settings: QgsSettings):
        try:
            reported_auth_cfg = settings.value("auth_config").strip()
        except AttributeError:
            reported_auth_cfg = None
        api_version = settings.value("api_version")
        handler = get_api_version_settings_handler(api_version)
        if handler is not None:
            api_version_settings = handler.from_qgs_settings(settings)
        else:
            api_version_settings = None
        return cls(
            id=uuid.UUID(connection_identifier),
            name=settings.value("name"),
            base_url=settings.value("base_url"),
            api_version=api_version,
            api_version_settings=api_version_settings,
            page_size=int(settings.value("page_size", defaultValue=10)),
            auth_config=reported_auth_cfg,
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
            settings.setValue("page_size", connection_settings.page_size)
            settings.setValue("auth_config", connection_settings.auth_config)
            settings.setValue("api_version", connection_settings.api_version)
            if connection_settings.api_version_settings is not None:
                settings.setValue(
                    ApiVersionSpecificSettings.PREFIX,
                    connection_settings.api_version_settings.to_qgs_settings()
                )

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
