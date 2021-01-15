import pytest
from unittest import mock

from qgis_geonode.qgisgeonode import conf


@pytest.mark.parametrize("connections, expected", [
    pytest.param([], [], id="no connections"),
    pytest.param(["fake1"], ["fake1"], id="single connection"),
    pytest.param(["fake1", "fake2"], ["fake1", "fake2"], id="two connections"),
    pytest.param(["fake1", "a fake"], ["a fake", "fake1"], id="two connections reordered"),
])
@mock.patch.object(conf.QgsSettings, "childGroups")
def test_settings_manager_list_connections(mock_childgroups, qgis_application, connections, expected):
    mock_childgroups.return_value = connections
    manager = conf.SettingsManager()
    manager.BASE_GROUP_NAME = "qgis_geonode_test"
    assert manager.list_connections() == expected