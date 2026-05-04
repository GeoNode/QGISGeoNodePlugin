"""Structured errors for the new transport primitive.

This module is part of the Phase 1 networking refactor. It coexists with the
legacy ``qgis_geonode.network`` module until later phases migrate call sites.
"""

import dataclasses
import enum
import typing


class ErrorKind(enum.Enum):
    """Categories of failure surfaced by :class:`Request`."""

    TIMEOUT = "timeout"
    HTTP = "http"
    TRANSPORT = "transport"
    CANCELLED = "cancelled"
    AUTH = "auth"


@dataclasses.dataclass()
class NetworkError:
    """Structured description of a failed network operation.

    ``http_status`` is populated for HTTP-level errors (4xx/5xx) where the
    server still produced a response. ``qt_error`` carries the symbolic name
    of the underlying ``QNetworkReply.NetworkError`` value when relevant.
    ``body`` may carry the raw response body for diagnostic purposes.
    """

    kind: ErrorKind
    url: str
    message: str
    http_status: typing.Optional[int] = None
    qt_error: typing.Optional[str] = None
    body: typing.Optional[bytes] = None
