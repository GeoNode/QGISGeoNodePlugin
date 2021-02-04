import json
import re
import urllib.parse

from pathlib import Path

from flask import Flask, request
import flask.logging

geonode_flask_app = Flask("mock_geonode")
geonode_flask_app.logger.removeHandler(flask.logging.default_handler)

ROOT = Path(__file__).parent / "_mock_geonode_data"


def _filter_json(data, resource_type, query_string):
    query_string = urllib.parse.unquote(
        query_string.decode("utf-8")
    )

    if "filter" not in query_string:
        return data

    pattern = re.compile("filter(.*)")
    match = pattern.search(query_string)
    filter_string = match.group(1)

    # parsing the required field and value
    # for filtering from the query string
    filter_part = filter_string.split('=')
    field_operator_string = filter_part[0]
    field_operator_list = field_operator_string.split('.')
    field = field_operator_list[0].replace('{', '').replace('}', '')
    value = filter_part[1]

    resources = [resource for resource in data[resource_type]
                 if resource[field] == value]
    data[resource_type] = resources
    return data


@geonode_flask_app.route("/api/v2/layers/")
def _mock_layer_list():
    data_path = ROOT / "layer_list_response1.json"
    with data_path.open() as fh:
        result = json.load(fh)
        result = _filter_json(
            result,
            "layers",
            request.query_string
        )
        return result


@geonode_flask_app.route("/api/v2/layers/<pk>/")
def _mock_layer_details(pk):
    data_path = ROOT / "layer_detail_response1.json"
    with data_path.open() as fh:
        result = json.load(fh)
        return result


@geonode_flask_app.route("/api/v2/layers/<layer_id>/styles/")
def _mock_layer_styles(layer_id):
    data_path = ROOT / "layer_style_list_response1.json"
    with data_path.open() as fh:
        result = json.load(fh)
        return result


@geonode_flask_app.route("/api/v2/maps/")
def _mock_map_list():
    data_path = ROOT / "map_list_response1.json"
    with data_path.open() as fh:
        result = json.load(fh)
        result = _filter_json(
            result,
            "maps",
            request.query_string
        )
        return result
