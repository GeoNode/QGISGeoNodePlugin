import multiprocessing
import os
from pathlib import Path
from wsgiref.simple_server import make_server

import pytest
from flask import Flask
import flask.logging
import qgis.core

import _mock_geonode

QGIS_PREFIX_PATH = Path(os.getenv("QGIS_PREFIX_PATH", "/usr"))


@pytest.fixture(scope="session")
def qgis_application():
    qgis.core.QgsApplication.setPrefixPath(str(QGIS_PREFIX_PATH), True)
    profile_directory = (
        Path("~").expanduser() / ".local/share/QGIS/QGIS3/profiles/default"
    )
    app = qgis.core.QgsApplication([], True, str(profile_directory))
    app.initQgis()
    yield app
    app.exitQgis()


def _spawn_geonode_server(port=9000):
    with make_server("", port, _mock_geonode.geonode_flask_app) as http_server:
        http_server.serve_forever()


@pytest.fixture(scope="session")
def mock_geonode_server():
    """Spawn a new GeoNode-like http server in a new process
    This fixture creates a mock GeoNode server to be used by tests. This mock server
    is a flask application that has fixed responses to the known-endpoints.
    The server is shutdown when a test run finishes
    Use this in tests that expect to communicate with a remote GeoNode server by adding
    `mock_geonode_server` as an extra test parameter
    """

    # TODO: allow configuring the port via an env variable
    process = multiprocessing.Process(target=_spawn_geonode_server)
    print("starting mock GeoNode server...")
    process.start()
    yield
    print("terminating mock GeoNode server...")
    process.terminate()
