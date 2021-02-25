import os

from qgis.core import QgsMapLayerType, QgsProject, Qgis

from qgis.gui import (
    QgsMapLayerConfigWidget,
    QgsMapLayerConfigWidgetFactory,
    QgsMessageBar,
)

from qgis.PyQt.uic import loadUiType
from qgis.PyQt.QtCore import QUrl
from qgis.PyQt.QtWidgets import QSizePolicy

from PyQt5.QtGui import QIcon, QDesktopServices

from ..resources import *
from ..utils import tr, log

WidgetUi, _ = loadUiType(
    os.path.join(os.path.dirname(__file__), "../ui/qgis_geonode_layer_dialog.ui")
)


class LayerPropertiesConfigWidgetFactory(QgsMapLayerConfigWidgetFactory):
    def createWidget(self, layer, canvas, dock_widget, parent):
        return LayerPropertiesConfigWidget(layer, canvas, parent)

    def supportsLayer(self, layer):
        return layer.type() in (
            QgsMapLayerType.VectorLayer,
            QgsMapLayerType.RasterLayer,
        )

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
        self.layer = layer
        self.message_bar = QgsMessageBar()
        self.message_bar.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        self.layout().insertWidget(0, self.message_bar)

        self.open_page_btn.clicked.connect(self.open_layer_page)

    def open_layer_page(self):
        for link in self.layer.metadata().links():
            if link.name == "Detail":
                QDesktopServices.openUrl(QUrl(link.url))
                return

        log(
            "Couldn't open layer page, the layer metadata "
            "doesn't contain the GeoNode layer page URL"
        )
        self.message_bar.pushMessage(
            tr(
                "Couldn't open layer page, the layer metadata "
                "doesn't contain the GeoNode layer page URL "
            ),
            level=Qgis.Critical,
        )

    def apply(self):
        pass
