import os
from pathlib import Path

import qgis.core
import qgis.gui

from qgis.PyQt import (
    QtCore,
    QtGui,
    QtWidgets,
)
from qgis.PyQt.uic import loadUiType

from ..utils import tr, log

WidgetUi, _ = loadUiType(Path(__file__).parents[1] / "ui/qgis_geonode_layer_dialog.ui")


class LayerPropertiesConfigWidgetFactory(qgis.gui.QgsMapLayerConfigWidgetFactory):
    def createWidget(self, layer, canvas, dock_widget, parent):
        return LayerPropertiesConfigWidget(layer, canvas, parent)

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


class LayerPropertiesConfigWidget(qgis.gui.QgsMapLayerConfigWidget, WidgetUi):
    available_styles_cb: QtWidgets.QCheckBox

    def __init__(self, layer, canvas, parent):
        super(LayerPropertiesConfigWidget, self).__init__(layer, canvas, parent)
        self.setupUi(self)
        # self.layer = layer
        # self.message_bar = qgis.gui.QgsMessageBar()
        # self.message_bar.setSizePolicy(
        #     QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Fixed)
        # self.layout().insertWidget(0, self.message_bar)
        # self.open_page_btn.clicked.connect(self.open_layer_page)

    # def open_layer_page(self):
    #     for link in self.layer.metadata().links():
    #         if link.name == "Detail":
    #             QtGui.QDesktopServices.openUrl(QtCore.QUrl(link.url))
    #             return
    #
    #     log(
    #         "Couldn't open layer page, the layer metadata "
    #         "doesn't contain the GeoNode layer page URL"
    #     )
    #     self.message_bar.pushMessage(
    #         tr(
    #             "Couldn't open layer page, the layer metadata "
    #             "doesn't contain the GeoNode layer page URL "
    #         ),
    #         level=qgis.core.Qgis.Critical,
    #     )
    #
    # def apply(self):
    #     pass
