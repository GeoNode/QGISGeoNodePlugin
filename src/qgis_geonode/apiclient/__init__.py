import importlib
import typing

from ..network import UNSUPPORTED_REMOTE
from ..vendor.packaging import version as packaging_version


def get_geonode_client(
    connection_settings: "ConnectionSettings",
) -> typing.Optional["BaseGeonodeClient"]:
    version = connection_settings.geonode_version
    if version is not None and version != UNSUPPORTED_REMOTE:
        class_path = select_supported_client(connection_settings.geonode_version)
        module_path, class_name = class_path.rpartition(".")[::2]
        imported_module = importlib.import_module(module_path)
        class_type = getattr(imported_module, class_name)
        result = class_type.from_connection_settings(connection_settings)
    else:
        result = None
    return result


def select_supported_client(geonode_version: packaging_version.Version) -> str:
    if geonode_version.major == 4:
        result = "qgis_geonode.apiclient.geonode_api_v2.GeoNodeApiClient"

    return result
