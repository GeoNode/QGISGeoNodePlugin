import typing

from . import (
    apiv2,
    csw,
    geonode,
)
from .models import UNSUPPORTED_REMOTE


def get_geonode_client(
    connection_settings: "ConnectionSettings",
) -> typing.Optional["BaseGeonodeClient"]:
    client_type: typing.Type["BaseGeonodeClient"] = {
        "qgis_geonode.apiclient.csw.GeonodeCswClient": csw.GeonodeCswClient,
        "qgis_geonode.apiclient.apiv2.GeonodeApiV2Client": apiv2.GeonodeApiV2Client,
        "qgis_geonode.apiclient.geonode.GeonodePostV2ApiClient": geonode.GeonodePostV2ApiClient,
        UNSUPPORTED_REMOTE: None,
    }[connection_settings.api_client_class_path]
    if client_type:
        result = client_type.from_connection_settings(connection_settings)
    else:
        result = None
    return result
