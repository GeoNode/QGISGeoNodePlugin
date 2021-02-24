import uuid
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from qgis_geonode.apiclient import (
    csw,
    models,
)


def test_get_brief_geonode_resource():
    sample_response_path = (
        Path(__file__).parent / "_mock_geonode_data/layer_detail_response2.xml"
    )
    sample_response = ET.fromstring(sample_response_path.read_text("utf-8"))
    record = sample_response.find(f"{{{csw.Csw202Namespace.GMD.value}}}MD_Metadata")
    base_url = "https://dummy"
    auth_config = "dummy_auth"
    result = csw.get_brief_geonode_resource(record, base_url, auth_config)
    assert result.uuid == uuid.UUID("5db808ae-6671-11eb-91f3-0242ac150008")
    assert result.name == "geonode:tejo0"
    assert result.resource_type == models.GeonodeResourceType.VECTOR_LAYER
    assert result.title == "tejo0"
    assert result.abstract == "HTML abstract? OK"
    assert result.spatial_extent.xMaximum() == pytest.approx(-9.10356043720555)
    assert result.spatial_extent.xMinimum() == pytest.approx(-9.15099431239243)
    assert result.spatial_extent.yMaximum() == pytest.approx(38.7166450851236)
    assert result.spatial_extent.yMinimum() == pytest.approx(38.6700664670482)
    assert result.crs.postgisSrid() == 4326
    assert (
        result.thumbnail_url
        == "https://master.demo.geonode.org/static/thumbs/layer-5db808ae-6671-11eb-91f3-0242ac150008-thumb.5cc326a7beec.png?v=c1509f76"
    )
    assert (
        result.gui_url
        == "https://master.demo.geonode.org/layers/geonode_master_data:geonode:tejo0"
    )
    assert (
        result.published_date.strftime("%Y-%m-%dT%H:%M:%SZ") == "2021-02-03T22:44:00Z"
    )
    assert (
        result.temporal_extent[0].strftime("%Y-%m-%dT%H:%M:%S%z")
        == "2021-02-01T22:46:00+0000"
    )
    assert (
        result.temporal_extent[1].strftime("%Y-%m-%dT%H:%M:%S%z")
        == "2021-02-28T22:46:00+0000"
    )
    assert result.keywords == ["blah", "Portugal"]
    assert result.category == "planningcadastre"
    assert (
        result.service_urls[models.GeonodeService.OGC_WFS]
        == f"https://master.demo.geonode.org/geoserver/ows?service=WFS&version=1.1.0&request=GetFeature&typename=geonode:tejo0&authkey={auth_config}"
    )
    assert (
        result.service_urls[models.GeonodeService.OGC_WMS]
        == f"crs=EPSG:4326&format=image/png&layers=geonode:tejo0&styles&url=https://master.demo.geonode.org/geoserver/ows&authkey={auth_config}"
    )
