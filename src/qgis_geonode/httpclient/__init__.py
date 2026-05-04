"""New transport primitive for the QGIS GeoNode plugin.

Phase 1 of the networking refactor introduces this package alongside the
legacy ``qgis_geonode.network`` module. Subsequent phases migrate call sites
and eventually rename this package to ``network`` once the legacy module is
deleted.
"""

from .errors import ErrorKind, NetworkError
from .transport import (
    Request,
    RequestBatch,
    HttpMethod,
    NetworkResponse,
    RequestToPerform,
)

__all__ = [
    "ErrorKind",
    "Request",
    "RequestBatch",
    "HttpMethod",
    "NetworkError",
    "NetworkResponse",
    "RequestToPerform",
]
