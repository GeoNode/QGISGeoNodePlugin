import datetime as dt
import typing
import uuid

import pytest

import qgis.core
from qgis.PyQt import QtCore

from qgis_geonode.conf import WfsVersion
from qgis_geonode.apiclient import (
    geonode_v3,
    models,
)


@pytest.mark.parametrize(
    "raw_links, link_type, expected",
    [
        pytest.param([{"link_type": "foo", "url": "bar"}], "foo", "bar"),
        pytest.param([{}], "foo", None),
    ],
)
def test_get_link(raw_links, link_type, expected):
    result = geonode_v3._get_link(raw_links, link_type)
    assert result == expected


@pytest.mark.parametrize(
    "payload, expected",
    [
        pytest.param(
            {
                "temporal_extent_start": "2021-01-30T10:23:22Z",
                "temporal_extent_end": "2021-01-30T10:23:22Z",
            },
            [
                dt.datetime(2021, 1, 30, 10, 23, 22),
                dt.datetime(2021, 1, 30, 10, 23, 22),
            ],
        ),
        pytest.param(
            {
                "temporal_extent_start": "2021-01-30T10:23:22Z",
            },
            [dt.datetime(2021, 1, 30, 10, 23, 22), None],
        ),
        pytest.param(
            {
                "temporal_extent_end": "2021-01-30T10:23:22Z",
            },
            [
                None,
                dt.datetime(2021, 1, 30, 10, 23, 22),
            ],
        ),
        pytest.param(
            {},
            None,
        ),
    ],
)
def test_get_temporal_extent(payload, expected):
    result = geonode_v3._get_temporal_extent(payload)
    assert result == expected


@pytest.mark.parametrize(
    "raw_dataset, expected",
    [
        pytest.param({"subtype": "raster"}, models.GeonodeResourceType.RASTER_LAYER),
        pytest.param({"subtype": "vector"}, models.GeonodeResourceType.VECTOR_LAYER),
        pytest.param({}, models.GeonodeResourceType.UNKNOWN),
    ],
)
def test_get_resource_type(raw_dataset, expected):
    result = geonode_v3._get_resource_type(raw_dataset)
    assert result == expected


# @pytest.mark.parametrize("geojson_geom, expected", [
#     pytest.param(
#         {},
#         qgis.core.QgsRectangle(0, 0, 10, 10)
#     ),
# ])
# def test_get_spatial_extent(geojson_geom, expected):
#     result = geonode_v3._get_spatial_extent(geojson_geom)
#     assert result == expected


@pytest.mark.parametrize(
    "raw_value, expected",
    [
        pytest.param("2021-10-02T09:22:01Z", dt.datetime(2021, 10, 2, 9, 22, 1)),
        pytest.param(
            "2021-10-02T09:22:01.123456Z", dt.datetime(2021, 10, 2, 9, 22, 1, 123456)
        ),
    ],
)
def test_parse_datetime(raw_value, expected):
    result = geonode_v3._parse_datetime(raw_value)
    assert result == expected


@pytest.mark.parametrize(
    "base_url, expected",
    [
        pytest.param("http://fake.com", "http://fake.com/api/v2/layers/"),
    ],
)
def test_apiclient_v_3_3_0_dataset_list_url(base_url, expected):
    client = geonode_v3.GeonodeApiClientVersion_3_3_0(
        base_url, 10, wfs_version=WfsVersion.V_1_1_0, network_requests_timeout=0
    )
    assert client.dataset_list_url == expected


@pytest.mark.parametrize(
    "client_class, base_url, expected",
    [
        pytest.param(
            geonode_v3.GeonodeApiClientVersion_3_3_0,
            "http://fake.com",
            "http://fake.com/api/v2/layers/",
        ),
        pytest.param(
            geonode_v3.GeonodeApiClientVersion_3_4_0,
            "http://fake.com",
            "http://fake.com/api/v2/datasets/",
        ),
    ],
)
def test_apiclient_dataset_list_url(client_class: typing.Type, base_url, expected):
    client = client_class(
        base_url, 10, wfs_version=WfsVersion.V_1_1_0, network_requests_timeout=0
    )
    assert client.dataset_list_url == expected


@pytest.mark.parametrize(
    "client_class, base_url, dataset_id, expected",
    [
        pytest.param(
            geonode_v3.GeonodeApiClientVersion_3_3_0,
            "http://fake.com",
            1,
            "http://fake.com/api/v2/layers/1/",
        ),
        pytest.param(
            geonode_v3.GeonodeApiClientVersion_3_4_0,
            "http://fake.com",
            1,
            "http://fake.com/api/v2/datasets/1/",
        ),
    ],
)
def test_apiclient_get_dataset_detail_url(
    client_class: typing.Type, base_url, dataset_id, expected
):
    client = client_class(
        base_url, 10, wfs_version=WfsVersion.V_1_1_0, network_requests_timeout=0
    )
    result = client.get_dataset_detail_url(dataset_id)
    assert result.toString() == expected


@pytest.mark.parametrize(
    "client_class, search_filters, expected",
    [
        pytest.param(
            geonode_v3.GeonodeApiClientVersion_3_4_0,
            models.GeonodeApiSearchFilters(),
            "page=1&page_size=10",
        ),
        pytest.param(
            geonode_v3.GeonodeApiClientVersion_3_4_0,
            models.GeonodeApiSearchFilters(title="fake-title"),
            "page=1&page_size=10&filter%7Btitle.icontains%7D=fake-title",
        ),
        pytest.param(
            geonode_v3.GeonodeApiClientVersion_3_4_0,
            models.GeonodeApiSearchFilters(abstract="fake-abstract"),
            "page=1&page_size=10&filter%7Babstract.icontains%7D=fake-abstract",
        ),
        pytest.param(
            geonode_v3.GeonodeApiClientVersion_3_4_0,
            models.GeonodeApiSearchFilters(keyword="fake-keyword"),
            "page=1&page_size=10&filter%7Bkeywords.name.icontains%7D=fake-keyword",
        ),
        pytest.param(
            geonode_v3.GeonodeApiClientVersion_3_4_0,
            models.GeonodeApiSearchFilters(
                topic_category=models.IsoTopicCategory.biota
            ),
            "page=1&page_size=10&filter%7Bcategory.identifier%7D=biota",
        ),
        pytest.param(
            geonode_v3.GeonodeApiClientVersion_3_4_0,
            models.GeonodeApiSearchFilters(
                temporal_extent_start=QtCore.QDateTime(2021, 7, 31, 10, 22)
            ),
            "page=1&page_size=10&filter%7Btemporal_extent_start.gte%7D=2021-07-31T10:22:00",
        ),
        pytest.param(
            geonode_v3.GeonodeApiClientVersion_3_4_0,
            models.GeonodeApiSearchFilters(
                temporal_extent_end=QtCore.QDateTime(2021, 7, 31, 10, 22)
            ),
            "page=1&page_size=10&filter%7Btemporal_extent_end.lte%7D=2021-07-31T10:22:00",
        ),
        pytest.param(
            geonode_v3.GeonodeApiClientVersion_3_4_0,
            models.GeonodeApiSearchFilters(
                publication_date_start=QtCore.QDateTime(2021, 7, 31, 10, 22)
            ),
            "page=1&page_size=10&filter%7Bdate.gte%7D=2021-07-31T10:22:00",
        ),
        pytest.param(
            geonode_v3.GeonodeApiClientVersion_3_4_0,
            models.GeonodeApiSearchFilters(
                publication_date_end=QtCore.QDateTime(2021, 7, 31, 10, 22)
            ),
            "page=1&page_size=10&filter%7Bdate.lte%7D=2021-07-31T10:22:00",
        ),
        pytest.param(
            geonode_v3.GeonodeApiClientVersion_3_4_0,
            models.GeonodeApiSearchFilters(
                layer_types=[models.GeonodeResourceType.VECTOR_LAYER]
            ),
            "page=1&page_size=10&filter%7Bsubtype.in%7D=vector",
        ),
        pytest.param(
            geonode_v3.GeonodeApiClientVersion_3_4_0,
            models.GeonodeApiSearchFilters(
                layer_types=[models.GeonodeResourceType.RASTER_LAYER]
            ),
            "page=1&page_size=10&filter%7Bsubtype.in%7D=raster",
        ),
        pytest.param(
            geonode_v3.GeonodeApiClientVersion_3_4_0,
            models.GeonodeApiSearchFilters(
                layer_types=[
                    models.GeonodeResourceType.VECTOR_LAYER,
                    models.GeonodeResourceType.RASTER_LAYER,
                ]
            ),
            "page=1&page_size=10&filter%7Bsubtype.in%7D=vector&filter%7Bsubtype.in%7D=raster",
        ),
        pytest.param(
            geonode_v3.GeonodeApiClientVersion_3_4_0,
            models.GeonodeApiSearchFilters(ordering_field="name"),
            "page=1&page_size=10&sort[]=name",
        ),
        pytest.param(
            geonode_v3.GeonodeApiClientVersion_3_4_0,
            models.GeonodeApiSearchFilters(
                ordering_field="name", reverse_ordering=True
            ),
            "page=1&page_size=10&sort[]=-name",
        ),
        pytest.param(
            geonode_v3.GeonodeApiClientVersion_3_3_0,
            models.GeonodeApiSearchFilters(),
            "page=1&page_size=10",
        ),
        pytest.param(
            geonode_v3.GeonodeApiClientVersion_3_3_0,
            models.GeonodeApiSearchFilters(title="fake-title"),
            "page=1&page_size=10&filter%7Btitle.icontains%7D=fake-title",
        ),
        pytest.param(
            geonode_v3.GeonodeApiClientVersion_3_3_0,
            models.GeonodeApiSearchFilters(abstract="fake-abstract"),
            "page=1&page_size=10&filter%7Babstract.icontains%7D=fake-abstract",
        ),
        pytest.param(
            geonode_v3.GeonodeApiClientVersion_3_3_0,
            models.GeonodeApiSearchFilters(keyword="fake-keyword"),
            "page=1&page_size=10&filter%7Bkeywords.name.icontains%7D=fake-keyword",
        ),
        pytest.param(
            geonode_v3.GeonodeApiClientVersion_3_3_0,
            models.GeonodeApiSearchFilters(
                topic_category=models.IsoTopicCategory.biota
            ),
            "page=1&page_size=10&filter%7Bcategory.identifier%7D=biota",
        ),
        pytest.param(
            geonode_v3.GeonodeApiClientVersion_3_3_0,
            models.GeonodeApiSearchFilters(
                temporal_extent_start=QtCore.QDateTime(2021, 7, 31, 10, 22)
            ),
            "page=1&page_size=10&filter%7Btemporal_extent_start.gte%7D=2021-07-31T10:22:00",
        ),
        pytest.param(
            geonode_v3.GeonodeApiClientVersion_3_3_0,
            models.GeonodeApiSearchFilters(
                temporal_extent_end=QtCore.QDateTime(2021, 7, 31, 10, 22)
            ),
            "page=1&page_size=10&filter%7Btemporal_extent_end.lte%7D=2021-07-31T10:22:00",
        ),
        pytest.param(
            geonode_v3.GeonodeApiClientVersion_3_3_0,
            models.GeonodeApiSearchFilters(
                publication_date_start=QtCore.QDateTime(2021, 7, 31, 10, 22)
            ),
            "page=1&page_size=10&filter%7Bdate.gte%7D=2021-07-31T10:22:00",
        ),
        pytest.param(
            geonode_v3.GeonodeApiClientVersion_3_3_0,
            models.GeonodeApiSearchFilters(
                publication_date_end=QtCore.QDateTime(2021, 7, 31, 10, 22)
            ),
            "page=1&page_size=10&filter%7Bdate.lte%7D=2021-07-31T10:22:00",
        ),
        pytest.param(
            geonode_v3.GeonodeApiClientVersion_3_3_0,
            models.GeonodeApiSearchFilters(
                layer_types=[models.GeonodeResourceType.VECTOR_LAYER]
            ),
            "page=1&page_size=10&filter%7BstoreType.in%7D=dataStore",
        ),
        pytest.param(
            geonode_v3.GeonodeApiClientVersion_3_3_0,
            models.GeonodeApiSearchFilters(
                layer_types=[models.GeonodeResourceType.RASTER_LAYER]
            ),
            "page=1&page_size=10&filter%7BstoreType.in%7D=coverageStore",
        ),
        pytest.param(
            geonode_v3.GeonodeApiClientVersion_3_3_0,
            models.GeonodeApiSearchFilters(
                layer_types=[
                    models.GeonodeResourceType.VECTOR_LAYER,
                    models.GeonodeResourceType.RASTER_LAYER,
                ]
            ),
            "page=1&page_size=10&filter%7BstoreType.in%7D=dataStore&filter%7BstoreType.in%7D=coverageStore",
        ),
        pytest.param(
            geonode_v3.GeonodeApiClientVersion_3_3_0,
            models.GeonodeApiSearchFilters(ordering_field="name"),
            "page=1&page_size=10&sort[]=name",
        ),
        pytest.param(
            geonode_v3.GeonodeApiClientVersion_3_3_0,
            models.GeonodeApiSearchFilters(
                ordering_field="name", reverse_ordering=True
            ),
            "page=1&page_size=10&sort[]=-name",
        ),
    ],
)
def test_apiclient_build_search_filters(
    client_class: typing.Type, search_filters, expected
):
    client = client_class(
        "phony-base-url", 10, wfs_version=WfsVersion.V_1_1_0, network_requests_timeout=0
    )
    result = client.build_search_query(search_filters)
    assert result.toString() == expected


def test_get_common_model_properties_client_v_3_4_0():
    dataset_uuid = "c22e838f-9503-484e-8769-b5b09a2b6104"
    raw_dataset = {
        "pk": 1,
        "uuid": dataset_uuid,
        "alternate": "fake name",
        "title": "fake title",
        "raw_abstract": "fake abstract",
        "thumbnail_url": "fake thumbnail url",
        "link": "fake link",
        "detail_url": "fake detail url",
        "subtype": "vector",
        "links": [
            {"link_type": "OGC:WMS", "url": "fake-wms-url"},
            {"link_type": "OGC:WFS", "url": "fake-wfs-url"},
        ],
        "bbox_polygon": {
            "type": "Polygon",
            "coordinates": [
                [
                    [-180.0, -90.0],
                    [-180.0, 90.0],
                    [180.0, 90.0],
                    [180.0, -90.0],
                    [-180.0, -90.0],
                ]
            ],
        },
        "srid": "EPSG:4326",
        "date_type": "publication",
        "date": "2021-02-12T23:00:00Z",
        "temporal_extent_start": "2021-03-02T10:45:22Z",
        "temporal_extent_end": "2021-03-02T19:45:22Z",
        "keywords": [{"name": "fake-keyword1"}, {"name": "fake-keyword2"}],
        "category": {"identifier": "fake-category"},
        "default_style": {"name": "fake-style-name", "sld_url": "fake-sld-url"},
    }
    expected = {
        "pk": 1,
        "uuid": uuid.UUID(dataset_uuid),
        "name": "fake name",
        "title": "fake title",
        "abstract": "fake abstract",
        "thumbnail_url": "fake thumbnail url",
        "link": "fake link",
        "detail_url": "fake detail url",
        "dataset_sub_type": models.GeonodeResourceType.VECTOR_LAYER,
        "service_urls": {
            models.GeonodeService.OGC_WMS: "fake-wms-url",
            models.GeonodeService.OGC_WFS: "fake-wfs-url",
        },
        "spatial_extent": qgis.core.QgsRectangle(-180.0, -90.0, 180.0, 90.0),
        "srid": qgis.core.QgsCoordinateReferenceSystem("EPSG:4326"),
        "published_date": dt.datetime(2021, 2, 12, 23),
        "temporal_extent": [
            dt.datetime(2021, 3, 2, 10, 45, 22),
            dt.datetime(2021, 3, 2, 19, 45, 22),
        ],
        "keywords": ["fake-keyword1", "fake-keyword2"],
        "category": "fake-category",
        "default_style": models.BriefGeonodeStyle(
            name="fake-style-name", sld_url="fake-sld-url"
        ),
    }
    client = geonode_v3.GeonodeApiClientVersion_3_4_0(
        "fake-base-url", 10, WfsVersion.V_1_1_0, 0
    )
    result = client._get_common_model_properties(raw_dataset)
    for k, v in expected.items():
        assert result[k] == v
