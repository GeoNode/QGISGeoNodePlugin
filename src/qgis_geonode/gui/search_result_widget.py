import os

from qgis.PyQt.uic import loadUiType

from qgis.PyQt.QtWidgets import QWidget


WidgetUi, _ = loadUiType(
    os.path.join(os.path.dirname(__file__), "../ui/search_result_widget.ui")
)


class SearchResultWidget(QWidget, WidgetUi):
    def __init__(self, name, description, parent=None):
        super(SearchResultWidget, self).__init__(parent)
        self.name = name
        self.description = description
