import importlib
import typing

from ..network import UNSUPPORTED_REMOTE
from ..vendor.packaging import version as packaging_version
from packaging.specifiers import SpecifierSet

SUPPORTED_VERSIONS = SpecifierSet(">=4.0.0, <5.0.0dev0")


def validate_version(
    version: packaging_version.Version, supported_versions=SUPPORTED_VERSIONS
) -> bool:

    # We need to convert the Version class to string
    # because the plugin uses a vendorized older packaging.version
    # which cannot compare Version classes with strings directly.
    # The new version of packaging can do this.
    # TODO update the packaging vendorized version
    version = version.base_version

    if version in supported_versions:
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
