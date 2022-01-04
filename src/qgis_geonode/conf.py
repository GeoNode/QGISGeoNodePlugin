import contextlib
import dataclasses
import json
import typing
import uuid

from qgis.PyQt import (
    QtCore,
)
from qgis.core import QgsRectangle, QgsSettings

from .apiclient import models
from .apiclient.models import GeonodeResourceType, IsoTopicCategory
from .utils import log
from .vendor.packaging import version as packaging_version


@contextlib.contextmanager
def qgis_settings(group_root: str):
    """A simple context manager to help managing our own settings in QgsSettings"""
    settings = QgsSettings()
    settings.beginGroup(group_root)
    try:
        yield settings
    finally:
        settings.endGroup()


def _get_network_requests_timeout():
    settings = QgsSettings()
    return settings.value(
        "qgis/networkAndProxy/networkTimeout", type=int, defaultValue=5000
    )


@dataclasses.dataclass
class ConnectionSettings:
    """Helper class to manage settings for a Connection"""

    id: uuid.UUID
    name: str
    base_url: str
    page_size: int
    network_requests_timeout: int = dataclasses.field(
        default_factory=_get_network_requests_timeout, init=False
    )
    geonode_version: typing.Optional[packaging_version.Version] = None
    auth_config: typing.Optional[str] = None

    @classmethod
    def from_qgs_settings(cls, connection_identifier: str, settings: QgsSettings):
        try:
            reported_auth_cfg = settings.value("auth_config").strip()
        except AttributeError:
            reported_auth_cfg = None
        raw_geonode_version = settings.value("geonode_version") or None
        if raw_geonode_version is not None:
            geonode_version = packaging_version.parse(raw_geonode_version)
        else:
            geonode_version = None
        return cls(
            id=uuid.UUID(connection_identifier),
            name=settings.value("name"),
            base_url=settings.value("base_url"),
            page_size=int(settings.value("page_size", defaultValue=10)),
            auth_config=reported_auth_cfg,
            geonode_version=geonode_version,
        )

    def to_json(self):
        return json.dumps(
            {
                "id": str(self.id),
                "name": self.name,
                "base_url": self.base_url,
                "page_size": self.page_size,
                "auth_config": self.auth_config,
                "geonode_version": str(self.geonode_version)
                if self.geonode_version is not None
                else None,
            }
        )


class SettingsManager(QtCore.QObject):
    """Manage saving/loading settings for the plugin in QgsSettings"""

    BASE_GROUP_NAME: str = "qgis_geonode"
    SELECTED_CONNECTION_KEY: str = "selected_connection"
    CURRENT_FILTERS_KEY: str = "current_search_filters"

    current_connection_changed = QtCore.pyqtSignal(str)

    _TEMPORAL_FILTER_NAMES = (
        "temporal_extent_start",
        "temporal_extent_end",
        "publication_date_start",
        "publication_date_end",
    )

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
            settings.setValue(
                "geonode_version",
                (
                    str(connection_settings.geonode_version)
                    if connection_settings.geonode_version is not None
                    else ""
                ),
            )

    def delete_connection(self, connection_id: uuid.UUID):
        if self.is_current_connection(connection_id):
            self.clear_current_connection()
        with qgis_settings(f"{self.BASE_GROUP_NAME}/connections") as settings:
            settings.remove(str(connection_id))

    def get_current_connection_settings(self) -> typing.Optional[ConnectionSettings]:
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
        current = self.get_current_connection_settings()
        return False if current is None else current.id == connection_id

    def _get_connection_settings_base(self, identifier: typing.Union[str, uuid.UUID]):
        return f"{self.BASE_GROUP_NAME}/connections/{str(identifier)}"

    def store_current_search_filters(self, filters: models.GeonodeApiSearchFilters):
        with qgis_settings(
            f"{self.BASE_GROUP_NAME}/{self.CURRENT_FILTERS_KEY}"
        ) as settings:
            settings.setValue("title", filters.title)
            settings.setValue("abstract", filters.abstract)
            settings.setValue("keyword", filters.keyword)
            if filters.topic_category is not None:
                settings.setValue("topic_category", filters.topic_category.name)
            else:
                settings.setValue("topic_category", None)
            if filters.layer_types is not None:
                settings.setValue(
                    "resource_types_vector",
                    GeonodeResourceType.VECTOR_LAYER in filters.layer_types,
                )
                settings.setValue(
                    "resource_types_raster",
                    GeonodeResourceType.RASTER_LAYER in filters.layer_types,
                )
            for temporal_filter_name in self._TEMPORAL_FILTER_NAMES:
                filter_value: typing.Optional[QtCore.QDateTime] = getattr(
                    filters, temporal_filter_name
                )
                if filter_value is not None:
                    settings.setValue(
                        temporal_filter_name, filter_value.toString(QtCore.Qt.ISODate)
                    )
                else:
                    settings.setValue(temporal_filter_name, None)
            if filters.spatial_extent is not None:
                settings.setValue(
                    "spatial_extent_north", filters.spatial_extent.yMaximum()
                )
                settings.setValue(
                    "spatial_extent_south", filters.spatial_extent.yMinimum()
                )
                settings.setValue(
                    "spatial_extent_east", filters.spatial_extent.xMaximum()
                )
                settings.setValue(
                    "spatial_extent_west", filters.spatial_extent.xMinimum()
                )
            settings.setValue("sort_by_field", filters.ordering_field)
            settings.setValue("reverse_sort_order", filters.reverse_ordering)

    def get_current_search_filters(self) -> models.GeonodeApiSearchFilters:
        result = models.GeonodeApiSearchFilters()
        with qgis_settings(
            f"{self.BASE_GROUP_NAME}/{self.CURRENT_FILTERS_KEY}"
        ) as settings:
            stored_category = settings.value("topic_category", None)
            try:
                category = IsoTopicCategory[stored_category]
            except KeyError:
                category = None
            result.title = settings.value("title", None)
            result.abstract = settings.value("abstract", None)
            result.keyword = settings.value("keyword", None)
            result.topic_category = category
            if settings.value("resource_types_vector", True, type=bool):
                result.layer_types.append(models.GeonodeResourceType.VECTOR_LAYER)
            if settings.value("resource_types_raster", True, type=bool):
                result.layer_types.append(models.GeonodeResourceType.RASTER_LAYER)

            for temporal_filter_name in self._TEMPORAL_FILTER_NAMES:
                value = settings.value(temporal_filter_name)
                if value is not None:
                    setattr(
                        result,
                        temporal_filter_name,
                        QtCore.QDateTime.fromString(value, QtCore.Qt.ISODate),
                    )

            if settings.value("spatial_extent_north") is not None:
                result.spatial_extent = QgsRectangle(
                    float(settings.value("spatial_extent_east")),
                    float(settings.value("spatial_extent_south")),
                    float(settings.value("spatial_extent_west")),
                    float(settings.value("spatial_extent_north")),
                )
            result.ordering_field = settings.value("sort_by_field")
            result.reverse_ordering = settings.value(
                "reverse_sort_order", False, type=bool
            )
        return result

    def clear_current_search_filters(self):
        with qgis_settings(self.BASE_GROUP_NAME) as settings:
            settings.setValue(self.CURRENT_FILTERS_KEY, None)
        self.current_connection_changed.emit("")


settings_manager = SettingsManager()
