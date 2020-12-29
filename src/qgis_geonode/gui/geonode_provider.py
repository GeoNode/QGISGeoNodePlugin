# -*- coding: utf-8 -*-
"""
/***************************************************************************
QgisGeoNode
                                 A QGIS plugin
                             -------------------
        begin                : 2020-12-28
        git sha              : $Format:%H$
        copyright            : (C) 2020 by kartoza
        email                : info at kartoza dot com
***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
"""
import os

from qgis.core import QgsProject
from qgis.gui import QgsSourceSelectProvider, QgsAbstractDataSourceWidget

from qgis.PyQt.uic import loadUiType

WidgetUi, _ = loadUiType(os.path.join(os.path.dirname(__file__), '../ui/qgis_geonode_main_ui.ui'))


class GeonodeProvider(QgsSourceSelectProvider):
    def __init__(self, title, icon):
        super(GeonodeProvider, self).__init__()
        self.title = title
        self.icon = icon

    def createDataSourceWidget(self, parent, fl, widgetMode):
        return CustomGeonodeWidget(parent, fl, widgetMode)

    def providerKey(self):
        return 'geonodeprovider'

    def icon(self):
        return self.icon

    def text(self):
        return self.title

    def toolTip(self):
        return self.title

    def ordering(self):
        return QgsSourceSelectProvider.OrderOtherProvider


class CustomGeonodeWidget(QgsAbstractDataSourceWidget, WidgetUi):
    def __init__(self, parent, fl, widgetMode):
        super(CustomGeonodeWidget, self).__init__(parent, fl, widgetMode)
        self.setupUi(self)
        self.project = QgsProject.instance()
