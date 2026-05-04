import json
import re
import time
import urllib.parse

from pathlib import Path

from flask import Flask, request, Response
import flask.logging

geonode_flask_app = Flask("mock_geonode")
geonode_flask_app.logger.removeHandler(flask.logging.default_handler)

ROOT = Path(__file__).parent / "_mock_geonode_data"


# --- Endpoints used by the httpclient unit tests (Phase 1 refactor) -------
#
# These exist purely to exercise the new transport primitive (see
# ``test/test_httpclient.py``). They are kept small and self-contained so
# they don't interact with the GeoNode-shaped fixtures above.


@geonode_flask_app.route("/httpclient/status/<int:code>")
def _mock_status_code(code):
    return Response(f"status {code}", status=code, mimetype="text/plain")


@geonode_flask_app.route("/httpclient/slow")
def _mock_slow():
    time.sleep(2)
    return Response("eventually", status=200, mimetype="text/plain")


@geonode_flask_app.route("/httpclient/echo", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
def _mock_echo():
    payload = {
        "method": request.method,
        "content_type": request.headers.get("Content-Type"),
        "body": request.get_data(as_text=True),
    }
    return Response(
        json.dumps(payload), status=200, mimetype="application/json"
    )


@geonode_flask_app.route("/api/v2/datasets/")
def _mock_layer_list():
    query_string = urllib.parse.unquote(request.query_string.decode("utf-8"))
    if "filter" in query_string:
        pattern = re.compile("filter(.*)")
        match = pattern.search(query_string)
        filter_string = match.group(1)
        if filter_string:
            data_path = ROOT / "layer_list_filtered_response1.json"
        else:
            data_path = ROOT / "layer_list_response1.json"
    else:
        data_path = ROOT / "layer_list_response1.json"

    with data_path.open() as fh:
        result = json.load(fh)
        return result


@geonode_flask_app.route("/api/v2/datasets/<pk>/")
def _mock_layer_details(pk):
    data_path = ROOT / "layer_detail_response1.json"
    with data_path.open() as fh:
        result = json.load(fh)
        return result


@geonode_flask_app.route("/api/v2/datasets/<layer_id>/styles/")
def _mock_layer_styles(layer_id):
    data_path = ROOT / "layer_style_list_response1.json"
    with data_path.open() as fh:
        result = json.load(fh)
        return result


@geonode_flask_app.route("/api/v2/maps/")
def _mock_map_list():
    query_string = urllib.parse.unquote(request.query_string.decode("utf-8"))
    if "filter" in query_string:
        pattern = re.compile("filter(.*)")
        match = pattern.search(query_string)
        filter_string = match.group(1)
        if filter_string:
            data_path = ROOT / "map_list_filtered_response1.json"
        else:
            data_path = ROOT / "map_list_response1.json"
    else:
        data_path = ROOT / "map_list_response1.json"

    with data_path.open() as fh:
        result = json.load(fh)
        return result
