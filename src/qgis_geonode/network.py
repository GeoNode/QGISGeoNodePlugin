"""Lightweight JSON-decoding helper for the GeoNode API client.

Phase 5 stripped this module down to its only surviving export. The legacy
``NetworkRequestTask`` machinery (``wait_for_signal``, ``PendingReply``,
``parse_qt_network_reply``, ``HttpMethod``, …) was removed once every call
site moved to the ``httpclient`` package; the only piece still consumed by
``apiclient.geonode_api_v2`` is the QByteArray → dict helper below.
"""

import json
import typing

from qgis.PyQt import QtCore

from .utils import log


def deserialize_json_response(
    contents: QtCore.QByteArray,
) -> typing.Optional[typing.Union[typing.List, typing.Dict]]:
    decoded_contents: str = contents.data().decode()
    try:
        return json.loads(decoded_contents)
    except json.JSONDecodeError as exc:
        log(f"JSON decode error - decoded_contents: {decoded_contents}")
        log(exc, debug=False)
        return None
