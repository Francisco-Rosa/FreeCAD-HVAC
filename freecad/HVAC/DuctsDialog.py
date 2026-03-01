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

translate = FreeCAD.Qt.translate

LanguagePath = os.path.dirname(__file__) + '/translations'
Gui.addLanguagePath(LanguagePath)

SA = None
NEW_GEOM = False

class DuctsConfigurationDialog(QtWidgets.QDialog):

    """HVAC ducts configuration dialog"""

    def __init__(self, parent = None):

        super().__init__(parent)

        # Load the UI
        ui_file = os.path.join(os.path.dirname(__file__), "Ducts.ui")
        self.ui = Gui.PySideUic.loadUi(ui_file)

        # Run tests on FC Pynthon console
        # user_mod_path = os.path.join(FreeCAD.getUserAppDataDir(), "Mod")
        # SunAnalysisUi = FreeCADGui.PySideUic.loadUi(
                                  #user_mod_path + '/HVAC/freecad/HVAC/Ducts.ui')
        # SunAnalysisUi.show()

        self.setWindowTitle(translate("DucsDialog", "HVAC ducts configuration"))
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self.ui)
        self.resize(self.ui.size())

        # Connect signals/slots
        # pushButton_Apply
        self.ui.pushButton_Apply.clicked.connect(self.on_button_apply_clicked)
        # buttonBox_Cancel_OK
        self.ui.buttonBox_Cancel_OK.clicked.connect(self.accept)
        self.ui.buttonBox_Cancel_OK.rejected.connect(self.reject)
        # translation
        #pushButton_Apply
        self.ui.pushButton_Apply.setText(
                       translate("DuctsDialog",
                       "Apply"))

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

    global NEW_GEOM
    dlg = DuctsConfigurationDialog()
    dlg.get_properties_data()
    if dlg.show_dialog():
        dlg.save_to_propeties()

