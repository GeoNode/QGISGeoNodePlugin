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

from ..api_client import BriefGeonodeResource, GeonodeResourceType
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

        self.wms_btn.clicked.connect(self.load_map_resource)
        self.wcs_btn.clicked.connect(self.load_raster_layer)
        self.wfs_btn.clicked.connect(self.load_vector_layer)

        self.wcs_btn.setEnabled(
            self.geonode_resource.resource_type ==
            GeonodeResourceType.RASTER_LAYER
        )
        self.wfs_btn.setEnabled(
            self.geonode_resource.resource_type ==
            GeonodeResourceType.VECTOR_LAYER
        )

    def load_map_resource(self):
        layer = QgsRasterLayer(
            self.geonode_resource.service_urls['wms'],
            self.geonode_resource.name,
            'wms')

        self.load_layer(layer)

    def load_raster_layer(self):
        layer = QgsRasterLayer(
            self.geonode_resource.service_urls['wcs'],
            self.geonode_resource.name,
            'wcs')

        self.load_layer(layer)

    def load_vector_layer(self):
        layer = QgsVectorLayer(
            self.geonode_resource.service_urls['wfs'],
            self.geonode_resource.name,
            "WFS")

        self.load_layer(layer)

    def load_layer(self, layer):
        if not layer.isValid():
            log("Problem loading the layer into QGIS")
            self.message_bar.pushMessage(
                tr("Problem loading layer, couldn't "
                   "add an invalid layer"),
                level=Qgis.Critical
            )
        else:
            QgsProject.instance().addMapLayer(layer)