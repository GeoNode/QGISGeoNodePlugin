import os

from qgis.PyQt.QtWidgets import QWidget
from qgis.PyQt.uic import loadUiType

from qgis.core import (
    QgsProject,
    QgsRasterLayer,
    QgsVectorLayer
)

from ..api_client import BriefGeonodeResource
from ..resources import *
from ..conf import connections_manager
from ..utils import log, tr

WidgetUi, _ = loadUiType(
    os.path.join(os.path.dirname(__file__), "../ui/search_result_widget.ui")
)


class SearchResultWidget(QWidget, WidgetUi):
    def __init__(self, geonode_resource: BriefGeonodeResource, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self.name_la.setText(geonode_resource.title)
        self.description_la.setText(geonode_resource.abstract)
        self.geonode_resource = geonode_resource

        self.wms_btn.clicked.connect(self.wms_btn_clicked)
        self.wfs_btn.clicked.connect(self.wfs_btn_clicked)

    def wms_btn_clicked(self):
        self.load_ogc_layer('wms')

    def wfs_btn_clicked(self):
        self.load_ogc_layer('wfs')

    def load_ogc_layer(self, provider_key: str):
        layer_uri = self.construct_ogc_uri(self.geonode_resource, provider_key)

        if layer_uri == '':
            return

        if provider_key == 'wms' or provider_key == 'wcs':
            layer = QgsRasterLayer(layer_uri, self.geonode_resource.name, provider_key)
        elif provider_key == 'wfs':
            layer = QgsVectorLayer(layer_uri, self.geonode_resource.name, "WFS")

        if not layer.isValid():
            log("Problem loading the layer into QGIS")
        else:
            QgsProject.instance().addMapLayer(layer)

    def construct_ogc_uri(self, geonode_resource, provider_key):
        # TODO need to use the layer url from the API. At the moment of writing this,
        #  the url is not  available in the GeoNode layer API response.
        connection = connections_manager.get_current_connection()

        if provider_key == 'wms':
            uri = 'crs={}&format={}&layers={}:{}&' \
                  'styles&url={}/geoserver/ows'.format(
                geonode_resource.crs.authid(),
                'image/png',
                geonode_resource.workspace,
                geonode_resource.name,
                connection.base_url
            )

        elif provider_key == 'wfs':
            uri = '{}/geoserver/ows?service=WFS&' \
                  'version=1.1.0&request=GetFeature&typename={}:{}'.format(
                connection.base_url,
                geonode_resource.workspace,
                geonode_resource.name
            )
        elif provider_key == 'wcs':
            uri = '{}/geoserver/ows?identifier={}:{}'.format(
                connection.base_url,
                geonode_resource.workspace,
                geonode_resource.name
            )
        else:
            return ''

        return uri
