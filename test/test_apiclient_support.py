"""Gating of remote GeoNode instances.

GEONODE_5_ROOT is what https://stable.demo.geonode.org/api/v2/ answers;
GEONODE_3_ROOT holds the endpoints registered by GeoNode 3.3.3.
"""

import json
import typing

import pytest

from qgis.PyQt import QtCore

from qgis_geonode import apiclient
from qgis_geonode.httpclient import (
    ErrorKind,
    NetworkError,
    NetworkResponse,
    RequestToPerform,
)

BASE_URL = "https://example.org"


def _root(*endpoints: str) -> typing.Dict:
    return {name: f"{BASE_URL}/api/v2/{name}/" for name in endpoints}


GEONODE_5_ROOT = _root(
    "assets",
    "categories",
    "datasets",
    "documents",
    "executionrequest",
    "geoapps",
    "groups",
    "keywords",
    "maps",
    "metadata",
    "owners",
    "regions",
    "resources",
    "tkeywords",
    "upload-parallelism-limits",
    "upload-size-limits",
    "users",
)

GEONODE_3_ROOT = _root(
    "categories",
    "documents",
    "geoapps",
    "groups",
    "keywords",
    "layers",  # renamed to `datasets` in GeoNode 4
    "maps",
    "owners",
    "regions",
    "resources",
    "tkeywords",
    "uploads",
    "users",
)


@pytest.fixture(autouse=True)
def pristine_api_state():
    """Keep the module-level cache and gate from leaking between tests."""
    original_check = apiclient.api_support_check()
    apiclient.invalidate_api_cache()
    yield
    apiclient.set_api_support_check(original_check)
    apiclient.invalidate_api_cache()


def _probe(body: bytes, http_status: int = 200, failed: bool = False) -> None:
    """Feed a response through the probe ingestion path."""
    error = None
    if failed:
        error = NetworkError(
            kind=ErrorKind.TRANSPORT,
            url=BASE_URL,
            message="boom",
            http_status=http_status,
        )
    apiclient._ingest_probe_response(
        BASE_URL,
        NetworkResponse(
            request=RequestToPerform(url=QtCore.QUrl(f"{BASE_URL}/api/v2/")),
            http_status=http_status,
            body=body,
            error=error,
        ),
    )


def test_geonode_5_is_supported():
    _probe(json.dumps(GEONODE_5_ROOT).encode())
    assert apiclient.api_client_support(BASE_URL) is apiclient.ApiSupport.SUPPORTED
    assert apiclient.is_api_client_supported(BASE_URL)


def test_geonode_3_is_rejected_even_though_it_answers_api_v2():
    _probe(json.dumps(GEONODE_3_ROOT).encode())
    assert apiclient.api_client_support(BASE_URL) is apiclient.ApiSupport.UNSUPPORTED
    assert not apiclient.is_api_client_supported(BASE_URL)


@pytest.mark.parametrize(
    "body, http_status, failed",
    [
        pytest.param(b"<html>nope</html>", 200, False, id="not-json"),
        pytest.param(b'["datasets"]', 200, False, id="json-but-not-an-object"),
        pytest.param(b"", 404, False, id="http-404"),
        pytest.param(b"", 500, True, id="transport-error"),
    ],
)
def test_a_non_api_root_is_unknown_rather_than_rejected(body, http_status, failed):
    _probe(body, http_status=http_status, failed=failed)
    assert apiclient.api_client_support(BASE_URL) is apiclient.ApiSupport.UNKNOWN
    assert not apiclient.is_api_client_supported(BASE_URL)


def test_unprobed_url_is_unknown():
    assert (
        apiclient.api_client_support("https://never-probed.example")
        is apiclient.ApiSupport.UNKNOWN
    )


def test_metadata_api_is_detected_from_the_same_probe():
    _probe(json.dumps(GEONODE_5_ROOT).encode())
    assert apiclient.has_metadata_api(BASE_URL)
    _probe(json.dumps(GEONODE_3_ROOT).encode())
    assert not apiclient.has_metadata_api(BASE_URL)


def test_gating_can_be_replaced():
    class RejectEverything(apiclient.ApiSupportCheck):
        def check(self, api_root):
            return apiclient.ApiSupport.UNSUPPORTED

        def unsupported_message(self):
            return "nothing passes"

    apiclient.set_api_support_check(RejectEverything())
    _probe(json.dumps(GEONODE_5_ROOT).encode())
    assert apiclient.api_client_support(BASE_URL) is apiclient.ApiSupport.UNSUPPORTED
    assert apiclient.api_support_check().unsupported_message() == "nothing passes"


def test_installing_a_check_discards_stale_verdicts():
    _probe(json.dumps(GEONODE_5_ROOT).encode())
    assert apiclient.is_api_client_supported(BASE_URL)

    class AcceptEverything(apiclient.ApiSupportCheck):
        def check(self, api_root):
            return apiclient.ApiSupport.SUPPORTED

        def unsupported_message(self):
            return "unreachable"

    apiclient.set_api_support_check(AcceptEverything())
    # back to "not probed yet" until something probes again
    assert apiclient.api_client_support(BASE_URL) is apiclient.ApiSupport.UNKNOWN


def test_the_check_is_abstract():
    with pytest.raises(TypeError):
        apiclient.ApiSupportCheck()
