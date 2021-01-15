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

from qgis_geonode.qgisgeonode.resources import *
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QDialog, QMessageBox
from qgis.core import QgsSettings

from ..qgisgeonode import utils
from ..qgisgeonode.default import SETTINGS_GROUP_NAME
from ..gui.connection_dialog import ConnectionDialog


WidgetUi, _ = loadUiType(
    os.path.join(os.path.dirname(__file__), "../ui/qgis_geonode_main_ui.ui")
)


class GeonodeSourceSelectProvider(QgsSourceSelectProvider):
    def createDataSourceWidget(self, parent, fl, widgetMode):
        return CustomGeonodeWidget(parent, fl, widgetMode)

    def providerKey(self):
        return "geonodeprovider"

    def icon(self):
        return QIcon(":/plugins/qgis_geonode/mIconGeonode.svg")

    def text(self):
        return utils.tr("GeoNode Plugin Provider")

    def toolTip(self):
        return utils.tr("Add Geonode Layer")

    def ordering(self):
        return QgsSourceSelectProvider.OrderOtherProvider


class CustomGeonodeWidget(QgsAbstractDataSourceWidget, WidgetUi):
    def __init__(self, parent, fl, widgetMode):
        super(CustomGeonodeWidget, self).__init__(parent, fl, widgetMode)
        self.setupUi(self)
        self.project = QgsProject.instance()
        self.settings = QgsSettings()

        self.btnNew.clicked.connect(self.add_connection)
        self.btnEdit.clicked.connect(self.edit_connection)
        self.btnDelete.clicked.connect(self.delete_connection)
        self.cmbConnections.activated.connect(self.update_current_connection)

        # Update GUI

        self.update_connections_combobox()

    def add_connection(self):
        """Create a new connection"""

        connection = ConnectionDialog()
        if connection.exec_() == QDialog.Accepted:
            self.update_connections_combobox()

    def update_connections_combobox(self):
        """ Save connection"""

        self.cmbConnections.clear()
        existing_connections = utils.settings_manager.list_connections()
        self.cmbConnections.addItems(existing_connections)
        try:
            current = utils.settings_manager.get_current_connection()
        except ValueError:
            current_index = len(existing_connections) - 1
        else:
            try:
                current_index = existing_connections.index(current["name"])
            except (ValueError, TypeError):
                current_index = len(existing_connections) - 1
        self.cmbConnections.setCurrentIndex(current_index)

        # Enable some buttons if there is any saved connection
        enabled = len(existing_connections) > 0
        self.btnEdit.setEnabled(enabled)
        self.btnDelete.setEnabled(enabled)

    def update_current_connection(self, index):
        if index != -1:
            current_name = self.cmbConnections.currentText()
            utils.settings_manager.set_current_connection(current_name)

    def edit_connection(self):
        """Edit connection"""

        current = utils.settings_manager.get_current_connection()
        edit_dlg = ConnectionDialog(name=current["name"])
        if edit_dlg.exec_() == QDialog.Accepted:
            self.update_connections_combobox()

    def delete_connection(self):
        connection_name = self.cmbConnections.currentText()
        existing_connections = utils.settings_manager.list_connections()
        index = existing_connections.index(connection_name)
        new_index = index - 1
        if new_index < 0 and len(existing_connections) > 1:
            new_index = 0
        try:
            next_connection = existing_connections[new_index]
        except ValueError:
            next_connection = None

        message = utils.tr('Remove the following connection "{}"?').format(connection_name)
        confirmation = QMessageBox.warning(self, utils.tr("QGIS GeoNode"), message, QMessageBox.Yes, QMessageBox.No)
        if confirmation == QMessageBox.Yes:
            utils.settings_manager.delete_connection(connection_name)
            utils.settings_manager.set_current_connection(next_connection)
            self.update_connections_combobox()
