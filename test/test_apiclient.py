import typing

import pytest

from qgis_geonode.apiclient import api_client


class ResponseCollector:
    """This class is used solely for capturing the contents of the
    `GeonodeClient`-emitted signals.

    """

    received_response: typing.Optional[typing.Dict]

    def __init__(self):
        self.received_response = None

    def collect_response(self, payload):
        print(f"received_response: {payload}")
        self.received_response = payload


@pytest.mark.parametrize("page", [
    pytest.param(None, id="no explicit page")
])
def test_layer_list(qtbot, qgis_application, mock_geonode_server, page):
    app = ResponseCollector()
    client = api_client.GeonodeClient(
        # base_url="https://master.demo.geonode.org",
        base_url = "http://localhost:8000",
    )
    client.layer_list_received.connect(app.collect_response)
    with qtbot.waitSignal(client.layer_list_received, timeout=2*1000) as blocker:
        client.get_layers(page=page)
    page_size = int(app.received_response["page_size"])
    print(f"layer ids: {[la['pk'] for la in app.received_response['layers']]}")
    assert page_size == 10
