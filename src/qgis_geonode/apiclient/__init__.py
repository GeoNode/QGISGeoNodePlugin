import dataclasses
import importlib
import json
import time
import typing

from qgis.PyQt import QtCore

from ..httpclient import NetworkResponse, Request, RequestToPerform

SUPPORTED_API_CLIENT = "/api/v2/"
_CACHE_TTL_SECONDS = 5 * 60


@dataclasses.dataclass()
class _CachedApiRoot:
    """Memoised result of a recent ``/api/v2/`` probe.

    ``root`` is the parsed JSON dict on success, ``None`` on failure.
    ``supported`` is the boolean derived from the same probe and is kept as a
    field so the lookup paths don't have to re-derive it.
    """

    supported: bool
    root: typing.Optional[typing.Dict]
    fetched_at: float

    def is_fresh(self) -> bool:
        return (time.monotonic() - self.fetched_at) < _CACHE_TTL_SECONDS


_api_v2_cache: typing.Dict[str, _CachedApiRoot] = {}


def _api_root_url(base_url: str) -> str:
    return f"{base_url.rstrip('/')}{SUPPORTED_API_CLIENT}"


def is_api_client_supported(base_url: str) -> bool:
    """Cache-only check; returns ``False`` when the URL hasn't been probed
    recently. Trigger :func:`probe_api_client` first if a fresh answer is
    needed.
    """
    entry = _api_v2_cache.get(base_url)
    if entry is None or not entry.is_fresh():
        return False
    return entry.supported


def has_metadata_api(base_url: str) -> bool:
    """Cache-only check for the ``metadata`` key in the API root."""
    entry = _api_v2_cache.get(base_url)
    if entry is None or not entry.is_fresh() or entry.root is None:
        return False
    return "metadata" in entry.root


def invalidate_api_cache(base_url: typing.Optional[str] = None) -> None:
    """Drop a cached entry; pass ``None`` to clear all entries."""
    if base_url is None:
        _api_v2_cache.clear()
    else:
        _api_v2_cache.pop(base_url, None)


def probe_api_client(
    base_url: str,
    auth_config: typing.Optional[str] = None,
    timeout_ms: int = 5000,
    parent: typing.Optional[QtCore.QObject] = None,
) -> Request:
    """Async probe of ``<base_url>/api/v2/``.

    The cache is updated as a side-effect from the request's ``finished``
    signal. The returned :class:`Request` lets callers connect their own
    handler; by the time their slot fires the cache is already populated,
    so ``is_api_client_supported(base_url)`` reflects the probe outcome.
    """
    request = Request(parent=parent)
    request.finished.connect(
        lambda response, url=base_url: _ingest_probe_response(url, response)
    )
    request.send(
        RequestToPerform(url=QtCore.QUrl(_api_root_url(base_url))),
        authcfg=auth_config,
        timeout_ms=timeout_ms,
    )
    return request


def _ingest_probe_response(base_url: str, response: NetworkResponse) -> None:
    root: typing.Optional[typing.Dict] = None
    supported = False
    if response.ok and response.http_status == 200:
        try:
            decoded = json.loads(bytes(response.body).decode())
        except (json.JSONDecodeError, UnicodeDecodeError):
            decoded = None
        if isinstance(decoded, dict):
            root = decoded
            supported = True
    _api_v2_cache[base_url] = _CachedApiRoot(
        supported=supported,
        root=root,
        fetched_at=time.monotonic(),
    )


def get_geonode_client(
    connection_settings: "ConnectionSettings",
) -> typing.Optional["BaseGeonodeClient"]:
    if not is_api_client_supported(connection_settings.base_url):
        return None

    module_path, class_name = select_supported_client().rpartition(".")[::2]
    imported_module = importlib.import_module(module_path)
    class_type = getattr(imported_module, class_name)
    return class_type.from_connection_settings(connection_settings)


def select_supported_client() -> str:
    return "qgis_geonode.apiclient.geonode_api_v2.GeoNodeApiClient"
