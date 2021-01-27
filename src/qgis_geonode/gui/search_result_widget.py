import os

from qgis.PyQt.QtWidgets import QWidget
from qgis.PyQt.uic import loadUiType

from qgis.core import (
    Qgis,
    QgsProject,
    QgsRasterLayer,
    QgsVectorLayer
)

from qgis.gui import QgsMessageBar

from ..api_client import BriefGeonodeResource
from ..resources import *
from ..utils import log, tr

WidgetUi, _ = loadUiType(
    os.path.join(os.path.dirname(__file__), "../ui/search_result_widget.ui")
)


class SearchResultWidget(QWidget, WidgetUi):
    def __init__(
            self,
            message_bar: QgsMessageBar,
            geonode_resource: BriefGeonodeResource,
            parent=None
    ):
        super().__init__(parent)
        self.setupUi(self)
        self.name_la.setText(geonode_resource.title)
        self.description_la.setText(geonode_resource.abstract)
        self.geonode_resource = geonode_resource
        self.message_bar = message_bar

        self.wms_btn.clicked.connect(self.wms_btn_clicked)
        self.wfs_btn.clicked.connect(self.wfs_btn_clicked)

    def wms_btn_clicked(self):
        self.load_ogc_layer('wms')

    def wfs_btn_clicked(self):
        self.load_ogc_layer('wfs')

    def load_ogc_layer(self, provider_key: str):
        layer_uri = self.geonode_resource.service_urls[provider_key]

        if layer_uri == '':
            log("Problem loading the layer into QGIS, "
                "couldn't create layer URI")
            self.message_bar.pushMessage(
                tr("Problem loading layer, couldn't "
                   "create layer URI"),
                level=Qgis.Critical
            )
            return

        if provider_key == 'wms' or provider_key == 'wcs':
            layer = QgsRasterLayer(layer_uri, self.geonode_resource.name, provider_key)
        elif provider_key == 'wfs':
            layer = QgsVectorLayer(layer_uri, self.geonode_resource.name, "WFS")

        if not layer.isValid():
            log("Problem loading the layer into QGIS")
            self.message_bar.pushMessage(
                tr("Problem loading layer, couldn't "
                   "add an invalid layer"),
                level=Qgis.Critical
            )
        else:
            QgsProject.instance().addMapLayer(layer)
