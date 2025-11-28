import requests
import importlib
import typing

SUPPORTED_API_CLIENT = "/api/v2/"
_api_v2_cache: dict[str, bool] = {}


def is_api_client_supported(base_url: str) -> bool:
    """
    Returns True if SUPPORTED_API_CLIENT endpoint responds with HTTP 200
    and contains valid JSON.
    """

    if base_url in _api_v2_cache:
        return _api_v2_cache[base_url]

    # delegate to unified helper
    supported = _fetch_api_root(base_url) is not None

    _api_v2_cache[base_url] = supported
    return supported


def _fetch_api_root(base_url: str) -> dict | None:
    """
    Internal helper:
    - Makes a request to SUPPORTED_API_CLIENT
    - Returns the JSON dict if valid, otherwise None
    """
    url = f"{base_url.rstrip('/')}{SUPPORTED_API_CLIENT}"
    try:
        resp = requests.get(url, timeout=5)

        if resp.status_code != 200:
            return None

        data = resp.json()
        return data if isinstance(data, dict) else None

    except Exception:
        return None


def has_metadata_api(base_url: str) -> bool:
    """
    Does the /api/v2/ root include a 'metadata' key?
    """
    data = _fetch_api_root(base_url)
    return data is not None and "metadata" in data


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
