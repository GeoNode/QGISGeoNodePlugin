import importlib
import typing

from ..network import UNSUPPORTED_REMOTE, MIN_SUPPORTED_VERSION,MAX_SUPPORTED_VERSION
from ..vendor.packaging import version as packaging_version

def validate_version(version: packaging_version.Version) -> bool:
    
    min = packaging_version.Version(MIN_SUPPORTED_VERSION)
    max = packaging_version.Version(MAX_SUPPORTED_VERSION)

    if version >= min and version < max:
        return True
    else:
        return False

def get_geonode_client(
    connection_settings: "ConnectionSettings",
) -> typing.Optional["BaseGeonodeClient"]:
    version = connection_settings.geonode_version

    result = None
    if version is not None and version != UNSUPPORTED_REMOTE:
        class_path = select_supported_client(connection_settings.geonode_version)
        if class_path != None:
            module_path, class_name = class_path.rpartition(".")[::2]
            imported_module = importlib.import_module(module_path)
            class_type = getattr(imported_module, class_name)
            result = class_type.from_connection_settings(connection_settings)
    return result


def select_supported_client(geonode_version: packaging_version.Version) -> str:

    result = None
    if validate_version(geonode_version):
        result = "qgis_geonode.apiclient.geonode_api_v2.GeoNodeApiClient"

    return result
