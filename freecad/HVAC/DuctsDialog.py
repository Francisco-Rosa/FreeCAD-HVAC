# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the HVAC addon.

################################################################################
#                                                                              #
#   Copyright (c) 2026 Francisco Rosa                                          #
#                                                                              #
#   This addon is free software; you can redistribute it and/or modify it      #
#   under the terms of the GNU Lesser General Public License as published      #
#   by the Free Software Foundation; either version 2.1 of the License, or     #
#   (at your option) any later version.                                        #
#                                                                              #
#   This addon is distributed in the hope that it will be useful,              #
#   but WITHOUT ANY WARRANTY; without even the implied warranty of             #
#   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.                       #
#                                                                              #
#   See the GNU Lesser General Public License for more details.                #
#                                                                              #
#   You should have received a copy of the GNU Lesser General Public           #
#   License along with this addon. If not, see https://www.gnu.org/licenses    #
#                                                                              #
################################################################################

"""This module implements the Sun Analysis configuration dialog"""

import os
import FreeCAD
import FreeCADGui as Gui
from PySide import QtWidgets
import freecad.HVAC.Ducts as Ducts
import freecad.HVAC.hvaclib as hvaclib

translate = FreeCAD.Qt.translate


class DuctsConfigurationDialog(QtWidgets.QDialog):

    """HVAC ducts configuration dialog"""

    def __init__(self, parent = None):

        super().__init__(parent)

        # Load the UI
        ui_file = hvaclib.get_file_path("Ducts.ui")
        self.ui = Gui.PySideUic.loadUi(ui_file)

        self.setWindowTitle(translate("DucsDialog", "HVAC ducts configuration"))
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self.ui)
        self.resize(self.ui.size())

        # Connect signals/slots
        self.ui.pushButton_Apply.clicked.connect(self.on_button_apply_clicked)
        self.ui.buttonBox_Cancel_OK.clicked.connect(self.accept)
        self.ui.buttonBox_Cancel_OK.rejected.connect(self.reject)

        # translation
        self.ui.pushButton_Apply.setText(translate("DuctsDialog", "Apply"))

    def translate(self, text):
        return text

    # Slots -------------
    def show_dialog(self):
        """Show dialog"""
        result = self.exec_()
        return result == QtWidgets.QDialog.Accepted

    # Connection dialog x ducts properties
    def get_properties_data(self):
        """Get data from ducts properties and send them to dialog"""
        pass

    def save_to_propeties(self):
        """Save data from dialog to ducts properties"""
        pass

    def on_button_apply_clicked(self):
        """Apply button actions"""
        pass

def open_ducts_configuration():
    """Open ducts configuration"""
    dlg = DuctsConfigurationDialog()
    dlg.get_properties_data()
    if dlg.show_dialog():
        dlg.save_to_propeties()
