from pathlib import Path

import qgis.core
import qgis.gui

from qgis.PyQt import QtGui
from qgis.PyQt.uic import loadUiType

from ..utils import tr

from .geonode_map_layer_config_widget import GeonodeMapLayerConfigWidget

WidgetUi, _ = loadUiType(Path(__file__).parents[1] / "ui/qgis_geonode_layer_dialog.ui")


class GeonodeMapLayerConfigWidgetFactory(qgis.gui.QgsMapLayerConfigWidgetFactory):
    def createWidget(self, layer, canvas, dock_widget, parent):
        return GeonodeMapLayerConfigWidget(layer, canvas, parent)

    def supportsLayer(self, layer):
        return layer.type() in (
            qgis.core.QgsMapLayerType.VectorLayer,
            qgis.core.QgsMapLayerType.RasterLayer,
        )

    def supportLayerPropertiesDialog(self):
        return True

    def icon(self):
        return QtGui.QIcon(":/plugins/qgis_geonode/mIconGeonode.svg")

    def title(self):
        return tr("GeoNode")
