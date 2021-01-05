
import os

from qgis.core import Qgis, QgsProject, QgsMapLayer
from qgis.gui import QgsMapLayerConfigWidget, QgsMapLayerConfigWidgetFactory

from qgis.PyQt.uic import loadUiType


WidgetUi, _ = loadUiType(os.path.join(os.path.dirname(__file__), '../ui/qgis_geonode_layer_dialog.ui'))


class LayerPropertiesConfigWidgetFactory(QgsMapLayerConfigWidgetFactory):
    def __init__(self, title, icon):
        super( LayerPropertiesConfigWidgetFactory, self).__init__(title, icon)

    def createWidget(self, layer, canvas, dock_widget, parent):
        return LayerPropertiesConfigWidget(layer, canvas, parent)

    def supportsLayer(self, layer):
        return True

    def supportLayerPropertiesDialog(self):
        return True


class LayerPropertiesConfigWidget(QgsMapLayerConfigWidget, WidgetUi):
    def __init__(self, layer, canvas, parent):
        super(LayerPropertiesConfigWidget, self).__init__(layer, canvas, parent)
        self.setupUi(self)
        self.project = QgsProject.instance()

    def apply(self):
        pass
