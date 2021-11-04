import enum
import typing

from . import (
    apiv2,
    csw,
)


class GeonodeApiVersion(enum.IntEnum):
    OGC_CSW = 1
    V2 = 2
    PRE_V2 = 3
    POST_V2 = 4


def get_geonode_client(
    connection_settings: "ConnectionSettings",
) -> "BaseGeonodeClient":
    client_type: typing.Type["BaseGeonodeClient"] = {
        GeonodeApiVersion.OGC_CSW: csw.GeonodeCswClient,
        GeonodeApiVersion.V2: apiv2.GeonodeApiV2Client,
    }[connection_settings.api_version]
    return client_type.from_connection_settings(connection_settings)
