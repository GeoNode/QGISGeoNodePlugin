import qgis.core
import qgis.gui
from qgis.PyQt import QtGui

from ..utils import tr

from .geonode_data_source_widget import GeonodeDataSourceWidget


class GeonodeSourceSelectProvider(qgis.gui.QgsSourceSelectProvider):
    def createDataSourceWidget(self, parent, fl, widgetMode):
        return GeonodeDataSourceWidget(parent, fl, widgetMode)

    def providerKey(self):
        return "qgis_geonode_plugin_provider"

    def icon(self):
        return QtGui.QIcon(":/plugins/qgis_geonode/mIconGeonode.svg")

    def text(self):
        return tr("GeoNode Plugin")

    def toolTip(self):
        return tr("Add Geonode Layer")

    def ordering(self):
        return qgis.gui.QgsSourceSelectProvider.OrderOtherProvider
