import importlib
import typing

from ..vendor.packaging import version as packaging_version


def get_geonode_client(
    connection_settings: "ConnectionSettings",
) -> typing.Optional["BaseGeonodeClient"]:
    module_path, class_name = connection_settings.api_client_class_path.rpartition(".")[
        ::2
    ]
    imported_module = importlib.import_module(module_path)
    class_type = getattr(imported_module, class_name)
    return class_type.from_connection_settings(connection_settings)


def select_client_class_path(geonode_version: packaging_version.Version) -> str:
    if geonode_version.is_devrelease or geonode_version.major == 4:
        result = "qgis_geonode.apiclient.version_postv2.GeonodePostV2ApiClient"
    elif geonode_version.major == 3 and geonode_version.minor >= 4:
        result = "qgis_geonode.apiclient.version_postv2.GeonodePostV2ApiClient"
    elif geonode_version.major == 3 and geonode_version.minor == 3:
        result = "qgis_geonode.apiclient.version_postv2.GeonodePostV2ApiClient"
    else:
        result = "qgis_geonode.apiclient.version_legacy.GeonodeLegacyApiClient"
    return result
