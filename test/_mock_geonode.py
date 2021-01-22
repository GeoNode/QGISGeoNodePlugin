import json
from pathlib import Path

from flask import Flask
import flask.logging

geonode_flask_app = Flask("mock_geonode")
geonode_flask_app.logger.removeHandler(flask.logging.default_handler)

ROOT = Path(__file__).parent / "_mock_geonode_data"


@geonode_flask_app.route("/api/v2/layers/")
def _mock_layer_list():
    data_path = ROOT / "layer_list_response1.json"
    with data_path.open() as fh:
        result = json.load(fh)
        return result


@geonode_flask_app.route("/api/v2/layers/<id>/")
def _mock_layer_details(id):
    id = int(id)
    style = {
        "pk": 1,
        "name": "test_style",
        "workspace": "test",
        "sld_title": "",
        "sld_body": "",
        "sld_version": "",
        "sld_url": "http://testUrl",
    }
    layers = [
        {"pk": 1, "default_style": {}, "styles": [style]},
        {"pk": 2, "default_style": {}, "styles": [style]},
    ]

    for layer in layers:
        if id == layer["pk"]:
            return {"layer": layer}

    return {"detail": "Not found."}


@geonode_flask_app.route("/api/v2/layers/<id>/styles/")
def _mock_layer_styles(id):
    return {
        "styles": [
            {
                "pk": 1,
                "name": "test_style",
                "workspace": "test",
                "sld_title": "",
                "sld_body": "",
                "sld_version": "",
                "sld_url": "http://testUrl",
            }
        ]
    }


@geonode_flask_app.route("/api/v2/maps/")
def _mock_map_list():
    return {
        "links": {"next": "", "previous": ""},
        "page": 1,
        "page_size": 10,
        "maps": [{"pk": "1"}],
    }
