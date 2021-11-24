import contextlib
import dataclasses
import json
import logging
import typing
import uuid

from qgis.PyQt import (
    QtCore,
)
from qgis.core import QgsRectangle, QgsSettings

from .apiclient import models

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
    page_size: int
    api_client_class_path: typing.Optional[str] = None
    auth_config: typing.Optional[str] = None

    @classmethod
    def from_qgs_settings(cls, connection_identifier: str, settings: QgsSettings):
        try:
            reported_auth_cfg = settings.value("auth_config").strip()
        except AttributeError:
            reported_auth_cfg = None
        return cls(
            id=uuid.UUID(connection_identifier),
            name=settings.value("name"),
            base_url=settings.value("base_url"),
            page_size=int(settings.value("page_size", defaultValue=10)),
            auth_config=reported_auth_cfg,
            api_client_class_path=settings.value("api_client_class_path")
        )

    def to_json(self):
        return json.dumps(
            {
                "id": str(self.id),
                "name": self.name,
                "base_url": self.base_url,
                "page_size": self.page_size,
                "auth_config": self.auth_config,
                "api_client_class_path": self.api_client_class_path
            }
        )


class SettingsManager(QtCore.QObject):
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

    def store_current_search_filters(
        self, current_filters: models.GeonodeApiSearchParameters
    ):
        with qgis_settings(
            f"{self.BASE_GROUP_NAME}/current_search_filters"
        ) as settings:
            settings.setValue("title", current_filters.title)
            settings.setValue("abstract", current_filters.abstract)
            settings.setValue("selected_keyword", current_filters.selected_keyword)
            settings.setValue("keywords", current_filters.keywords)
            settings.setValue("topic_category", current_filters.topic_category)
            if current_filters.layer_types is not None:
                settings.setValue(
                    "resource_types_vector",
                    (
                        models.GeonodeResourceType.VECTOR_LAYER
                        in current_filters.layer_types
                    ),
                )
                settings.setValue(
                    "resource_types_raster",
                    (
                        models.GeonodeResourceType.RASTER_LAYER
                        in current_filters.layer_types
                    ),
                )
                settings.setValue(
                    "resource_types_map",
                    (models.GeonodeResourceType.MAP in current_filters.layer_types),
                )
            if current_filters.temporal_extent_start is not None:
                settings.setValue(
                    "temporal_extent_start",
                    current_filters.temporal_extent_start.toString(QtCore.Qt.ISODate),
                )
            else:
                settings.setValue("temporal_extent_start", None)
            if current_filters.temporal_extent_end is not None:
                settings.setValue(
                    "temporal_extent_end",
                    current_filters.temporal_extent_end.toString(QtCore.Qt.ISODate),
                )
            else:
                settings.setValue("temporal_extent_end", None)

            if current_filters.publication_date_start is not None:
                settings.setValue(
                    "publication_date_start",
                    current_filters.publication_date_start.toString(QtCore.Qt.ISODate),
                )
            else:
                settings.setValue("publication_date_start", None)
            if current_filters.publication_date_end is not None:
                settings.setValue(
                    "publication_date_end",
                    current_filters.publication_date_end.toString(QtCore.Qt.ISODate),
                )
            else:
                settings.setValue("publication_date_end", None)
            if current_filters.spatial_extent is not None:
                settings.setValue(
                    "spatial_extent_north", current_filters.spatial_extent.yMaximum()
                )
                settings.setValue(
                    "spatial_extent_south", current_filters.spatial_extent.yMinimum()
                )
                settings.setValue(
                    "spatial_extent_east", current_filters.spatial_extent.xMaximum()
                )
                settings.setValue(
                    "spatial_extent_west", current_filters.spatial_extent.xMinimum()
                )
            settings.setValue("sort_by_field", current_filters.ordering_field.value)
            settings.setValue("reverse_sort_order", current_filters.reverse_ordering)

    def get_current_search_filters(self) -> models.GeonodeApiSearchParameters:
        with qgis_settings(
            f"{self.BASE_GROUP_NAME}/current_search_filters"
        ) as settings:
            resources_types = []
            temporal_extent_start = None
            temporal_extent_end = None
            publication_date_start = None
            publication_date_end = None
            spatial_extent = None

            if settings.value("resource_types_vector", True, type=bool):
                resources_types.append(models.GeonodeResourceType.VECTOR_LAYER)
            if settings.value("resource_types_raster", True, type=bool):
                resources_types.append(models.GeonodeResourceType.RASTER_LAYER)
            if settings.value("resource_types_map", True, type=bool):
                resources_types.append(models.GeonodeResourceType.MAP)
            if settings.value("temporal_extent_start"):
                temporal_extent_start = QtCore.QDateTime.fromString(
                    settings.value("temporal_extent_start"), QtCore.Qt.ISODate
                )
            if settings.value("temporal_extent_end"):
                temporal_extent_end = QtCore.QDateTime.fromString(
                    settings.value("temporal_extent_end"), QtCore.Qt.ISODate
                )
            if settings.value("publication_date_start"):
                publication_date_start = QtCore.QDateTime.fromString(
                    settings.value("publication_date_start"), QtCore.Qt.ISODate
                )
            if settings.value("publication_date_end"):
                publication_date_end = QtCore.QDateTime.fromString(
                    settings.value("publication_date_end"), QtCore.Qt.ISODate
                )
            if settings.value("spatial_extent_north") is not None:
                spatial_extent = QgsRectangle(
                    float(settings.value("spatial_extent_east")),
                    float(settings.value("spatial_extent_south")),
                    float(settings.value("spatial_extent_west")),
                    float(settings.value("spatial_extent_north")),
                )
            ordering_field = models.OrderingType(
                settings.value("sort_by_field", models.OrderingType.NAME.value)
            )
            reverse_sort_order = settings.value("reverse_sort_order", False, type=bool)

            return models.GeonodeApiSearchParameters(
                title=settings.value("title", None),
                abstract=settings.value("abstract", None),
                selected_keyword=settings.value("selected_keyword", None),
                keywords=settings.value("keywords", None),
                topic_category=settings.value("topic_category", None),
                layer_types=resources_types,
                temporal_extent_start=temporal_extent_start,
                temporal_extent_end=temporal_extent_end,
                publication_date_start=publication_date_start,
                publication_date_end=publication_date_end,
                spatial_extent=spatial_extent,
                ordering_field=ordering_field,
                reverse_ordering=reverse_sort_order,
            )


settings_manager = SettingsManager()
