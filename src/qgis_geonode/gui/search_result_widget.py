import os

from qgis.PyQt.QtWidgets import QWidget
from qgis.PyQt.uic import loadUiType

from ..api_client import BriefGeonodeResource
from ..resources import *


WidgetUi, _ = loadUiType(
    os.path.join(os.path.dirname(__file__), "../ui/search_result_widget.ui")
)


class SearchResultWidget(QWidget, WidgetUi):
    def __init__(self, geonode_resource: BriefGeonodeResource, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self.name_la.setText(geonode_resource.title)
        self.description_la.setText(geonode_resource.abstract)
