import abc
import dataclasses
import enum
import importlib
import json
import time
import typing

from qgis.PyQt import QtCore

from ..httpclient import NetworkResponse, Request, RequestToPerform
from ..utils import tr

SUPPORTED_API_CLIENT = "/api/v2/"
_CACHE_TTL_SECONDS = 5 * 60


class ApiSupport(enum.Enum):
    """Verdict of the active ``ApiSupportCheck`` on an ``/api/v2/`` probe."""

    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"  # answered, and turned down
    UNKNOWN = "unknown"  # not probed recently, unreachable, or not an API root


class ApiSupportCheck(abc.ABC):
    """Gates which remote GeoNode instances the plugin talks to.

    Subclass and install with ``set_api_support_check()`` to gate differently.
    """

    @abc.abstractmethod
    def check(self, api_root: typing.Dict) -> ApiSupport:
        """Classify an instance from its parsed ``/api/v2/`` root.

        Return ``ApiSupport.UNKNOWN`` when the root does not settle it.
        """

    @abc.abstractmethod
    def unsupported_message(self) -> str:
        """Translated reason to show when ``check()`` rejects an instance."""


class DatasetsEndpointCheck(ApiSupportCheck):
    """Require the ``datasets`` endpoint, renamed from ``layers`` in GeoNode 4.

    GeoNode 3.3 serves ``/api/v2/`` too, so the endpoint - not the root - is
    what tells them apart.
    """

    endpoint: str = "datasets"

    def check(self, api_root: typing.Dict) -> ApiSupport:
        if self.endpoint in api_root:
            return ApiSupport.SUPPORTED
        return ApiSupport.UNSUPPORTED

    def unsupported_message(self) -> str:
        return tr(
            "GeoNode 3 is not supported. This plugin requires GeoNode 4 or newer."
        )


_api_support_check: ApiSupportCheck = DatasetsEndpointCheck()


def api_support_check() -> ApiSupportCheck:
    """The check currently gating instances."""
    return _api_support_check


def set_api_support_check(check: ApiSupportCheck) -> None:
    """Install a different gate, discarding cached verdicts."""
    global _api_support_check
    _api_support_check = check
    invalidate_api_cache()


@dataclasses.dataclass()
class _CachedApiRoot:
    """Memoised result of a recent ``/api/v2/`` probe.

    ``root`` is the parsed JSON dict on success, ``None`` on failure.
    ``support`` is the verdict reached on the same probe and is kept as a
    field so the lookup paths don't have to re-run the check.
    """

    support: ApiSupport
    root: typing.Optional[typing.Dict]
    fetched_at: float

    def is_fresh(self) -> bool:
        return (time.monotonic() - self.fetched_at) < _CACHE_TTL_SECONDS


_api_v2_cache: typing.Dict[str, _CachedApiRoot] = {}


def _api_root_url(base_url: str) -> str:
    return f"{base_url.rstrip('/')}{SUPPORTED_API_CLIENT}"


def api_client_support(base_url: str) -> ApiSupport:
    """Cache-only verdict; ``UNKNOWN`` when the URL hasn't been probed
    recently. Trigger :func:`probe_api_client` first if a fresh answer is
    needed.
    """
    entry = _api_v2_cache.get(base_url)
    if entry is None or not entry.is_fresh():
        return ApiSupport.UNKNOWN
    return entry.support


def is_api_client_supported(base_url: str) -> bool:
    """Cache-only check; see :func:`api_client_support` for why it is false."""
    return api_client_support(base_url) is ApiSupport.SUPPORTED


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
    support = ApiSupport.UNKNOWN
    if response.ok and response.http_status == 200:
        try:
            decoded = json.loads(bytes(response.body).decode())
        except (json.JSONDecodeError, UnicodeDecodeError):
            decoded = None
        if isinstance(decoded, dict):
            # answering /api/v2/ is not enough - the check decides
            root = decoded
            support = _api_support_check.check(decoded)
    _api_v2_cache[base_url] = _CachedApiRoot(
        support=support,
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
