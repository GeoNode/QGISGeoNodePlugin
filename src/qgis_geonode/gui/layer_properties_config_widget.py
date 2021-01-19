import os

from qgis.core import QgsProject
from qgis.gui import QgsMapLayerConfigWidget, QgsMapLayerConfigWidgetFactory

from qgis.PyQt.uic import loadUiType

from PyQt5.QtGui import QIcon

from ..resources import *
from ..utils import tr

WidgetUi, _ = loadUiType(
    os.path.join(os.path.dirname(__file__), "../ui/qgis_geonode_layer_dialog.ui")
)


class LayerPropertiesConfigWidgetFactory(QgsMapLayerConfigWidgetFactory):
    def createWidget(self, layer, canvas, dock_widget, parent):
        return LayerPropertiesConfigWidget(layer, canvas, parent)

    def supportsLayer(self, layer):
        return True

    def supportLayerPropertiesDialog(self):
        return True

    def icon(self):
        return QIcon(":/plugins/qgis_geonode/mIconGeonode.svg")

    def title(self):
        return tr("GeoNode")


class LayerPropertiesConfigWidget(QgsMapLayerConfigWidget, WidgetUi):
    def __init__(self, layer, canvas, parent):
        super(LayerPropertiesConfigWidget, self).__init__(layer, canvas, parent)
        self.setupUi(self)
        self.project = QgsProject.instance()

    def apply(self):
        pass
