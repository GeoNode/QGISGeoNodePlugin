import os

from qgis.PyQt.QtWidgets import QWidget
from qgis.PyQt.uic import loadUiType

from ..resources import *


WidgetUi, _ = loadUiType(
    os.path.join(os.path.dirname(__file__), "../ui/search_result_widget.ui")
)


class SearchResultWidget(QWidget, WidgetUi):
    def __init__(self, name, description, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self.name_la.setText(name)
        self.description_la.setText(description)
