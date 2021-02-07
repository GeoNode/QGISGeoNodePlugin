import uuid
from pathlib import Path
from xml.etree import ElementTree as ET

from qgis_geonode.apiclient import csw


def test_get_brief_geonode_resource():
    sample_response_path = Path(
        __file__).parent / "_mock_geonode_data/layer_detail_response2.xml"
    sample_response = ET.fromstring(sample_response_path.read_text("utf-8"))
    record = sample_response.find(f"{{{csw.Csw202Namespace.GMD.value}}}MD_Metadata")
    base_url = "https://dummy"
    auth_config = "dummy_auth"
    result = csw.get_brief_geonode_resource(record, base_url, auth_config)
    assert result.uuid == uuid.UUID("5db808ae-6671-11eb-91f3-0242ac150008")