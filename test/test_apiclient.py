import typing

import pytest
import qgis_geonode.apiclient.models

from qgis_geonode.apiclient import apiv2

SIGNAL_TIMEOUT = 5  # seconds


class ResponseCollector:
    """This class is used solely for capturing the contents of the
    `GeonodeClient`-emitted signals.

    """

    received_response: typing.Any

    def __init__(self):
        self.received_response = None

    def collect_response(self, *response_args):
        print(f"received_response: {response_args}")
        self.received_response = response_args


@pytest.mark.parametrize("page", [pytest.param(None, id="no explicit page")])
def test_layer_list(qtbot, qgis_application, mock_geonode_server, page):
    app = ResponseCollector()
    client = apiv2.GeonodeApiV2Client(base_url="http://localhost:9000")
    client.layer_list_received.connect(app.collect_response)
    with qtbot.waitSignal(client.layer_list_received, timeout=SIGNAL_TIMEOUT * 1000):
        client.get_layers(page=page)
    layers, total_results, page_number, page_size = app.received_response

    print(f"layer ids: {[la.pk for la in layers]}")

    layers_size = len(layers)

    assert layers_size == 2
    assert page_number == 1
    assert page_size == 2


@pytest.mark.parametrize("page", [pytest.param(None, id="no explicit page")])
def test_layer_list_filtering(qtbot, qgis_application, mock_geonode_server, page):
    app = ResponseCollector()
    client = api_client.GeonodeClient(base_url="http://localhost:9000")
    client.layer_list_received.connect(app.collect_response)
    with qtbot.waitSignal(client.layer_list_received, timeout=SIGNAL_TIMEOUT * 1000):
        client.get_layers(page=page, title="TEMPERATURASMINENERO2030")
    layers, total_results, page_number, page_size = app.received_response

    print(f"layer ids: {[la.pk for la in layers]}")

    layers_size = len(layers)

    assert layers_size == 1
    assert layers[0].name == "TEMPERATURASMINENERO2030"


@pytest.mark.parametrize("id_", [pytest.param(184)])
def test_layer_details(qtbot, qgis_application, mock_geonode_server, id_):
    app = ResponseCollector()
    client = apiv2.GeonodeApiV2Client(base_url="http://localhost:9000")
    client.layer_detail_received.connect(app.collect_response)
    with qtbot.waitSignal(client.layer_detail_received, timeout=SIGNAL_TIMEOUT * 1000):
        client.get_layer_detail(id_=id_)
    layer: qgis_geonode.apiclient.models.GeonodeResource = app.received_response[0]
    assert id_ == layer.pk


@pytest.mark.parametrize("id_", [184])
def test_layer_styles(qtbot, qgis_application, mock_geonode_server, id_):
    app = ResponseCollector()
    client = apiv2.GeonodeApiV2Client(base_url="http://localhost:9000")
    client.layer_styles_received.connect(app.collect_response)
    with qtbot.waitSignal(client.layer_styles_received, timeout=SIGNAL_TIMEOUT * 1000):
        client.get_layer_styles(layer_id=id_)
        styles = app.received_response[0]
    assert len(styles) == 1


@pytest.mark.parametrize("page", [pytest.param(None, id="no explicit page")])
def test_map_list(qtbot, qgis_application, mock_geonode_server, page):
    app = ResponseCollector()
    client = apiv2.GeonodeApiV2Client(base_url="http://localhost:9000")
    client.map_list_received.connect(app.collect_response)
    with qtbot.waitSignal(client.map_list_received, timeout=SIGNAL_TIMEOUT * 1000):
        client.get_maps(page=page)
    maps, total_results, page_number, page_size = app.received_response
    assert page_size == 2
    assert maps[0].pk == 43


@pytest.mark.parametrize("page", [pytest.param(None, id="no explicit page")])
def test_map_list_filtering(qtbot, qgis_application, mock_geonode_server, page):
    app = ResponseCollector()
    client = api_client.GeonodeClient(base_url="http://localhost:9000")
    client.map_list_received.connect(app.collect_response)
    with qtbot.waitSignal(client.map_list_received, timeout=SIGNAL_TIMEOUT * 1000):
        client.get_maps(page=page, title="AIRPORT")
    maps, total_results, page_number, page_size = app.received_response

    assert page_size == 2
    assert len(maps) == 1
    assert maps[0].pk == 70