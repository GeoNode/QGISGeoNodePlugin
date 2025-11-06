import requests
import importlib
import typing

SUPPORTED_API_CLIENT = "/api/v2/"


def is_api_client_supported(base_url: str) -> bool:
    """
    Returns True if SUPPORTED_API_CLIENT endpoint responds with HTTP 200
    and contains valid JSON.
    """
    url = f"{base_url.rstrip('/')}{SUPPORTED_API_CLIENT}"
    try:
        resp = requests.get(url, timeout=5)

        if resp.status_code != 200:
            return False

        return isinstance(resp.json(), dict)

    except Exception:
        return False


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
