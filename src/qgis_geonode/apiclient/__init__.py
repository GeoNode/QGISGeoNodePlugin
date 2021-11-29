import importlib
import typing

from .models import UNSUPPORTED_REMOTE


# def old_get_geonode_client(
#     connection_settings: "ConnectionSettings",
# ) -> typing.Optional["BaseGeonodeClient"]:
#     client_type: typing.Type["BaseGeonodeClient"] = {
#         "qgis_geonode.apiclient.version_legacy.GeonodeLegacyApiClient": version_legacy.GeonodeLegacyApiClient,
#         "qgis_geonode.apiclient.apiv2.GeonodeApiV2Client": apiv2.GeonodeApiV2Client,
#         "qgis_geonode.apiclient.geonode.GeonodePostV2ApiClient": version_postv2.GeonodePostV2ApiClient,
#         UNSUPPORTED_REMOTE: None,
#     }[connection_settings.api_client_class_path]
#     if client_type:
#         result = client_type.from_connection_settings(connection_settings)
#     else:
#         result = None
#     return result


def get_geonode_client(
    connection_settings: "ConnectionSettings",
) -> typing.Optional["BaseGeonodeClient"]:
    module_path, class_name = connection_settings.api_client_class_path.rpartition(".")[
        ::2
    ]
    imported_module = importlib.import_module(module_path)
    class_type = getattr(imported_module, class_name)
    return class_type.from_connection_settings(connection_settings)
