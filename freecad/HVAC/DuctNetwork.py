# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the Solar addon.

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

"""This module implements HVAC duct description classes."""

import FreeCAD
import FreeCADGui as Gui
from PySide import QtWidgets
import freecad.HVAC.DuctNetworkConfigDialog as DuctNetworkConfigDialog
import freecad.HVAC.hvaclib as hvaclib

from PySide.QtCore import QT_TRANSLATE_NOOP
translate = FreeCAD.Qt.translate

#=================================================
# A. Main classes
#=================================================

class DuctNetwork:

    """Visualize and configure HVAC duct network in FreeCAD's 3D view."""

    CONTEXT_KEY = hvaclib.DUCT_NETWORK_CONTEXT_KEY

    def __init__(self, obj):
        obj.Proxy = self
        self.setProperties(obj)

    def setProperties(self,obj):
        """Gives the object properties to HVAC ducts."""
        pass

    @staticmethod
    def setActive(obj):
        """Set this DuctNetwork as the active container in the 3D view."""
        Gui.ActiveDocument.ActiveView.setActiveObject(DuctNetwork.CONTEXT_KEY, obj)

    @staticmethod
    def getActive(doc=None):
        """Get the active DuctNetwork container from the 3D view."""
        if not App.GuiUp:
            return None
        if doc is None:
            doc = App.ActiveDocument
        if doc is None or Gui.ActiveDocument is None:
            return None
        return Gui.ActiveDocument.ActiveView.getActiveObject(DuctNetwork.CONTEXT_KEY)

    @staticmethod
    def isDuctNetwork(obj):
        """Test whether obj is a DuctNetwork FeaturePython object."""
        return bool(obj) and hasattr(obj, "Proxy") and isinstance(obj.Proxy, DuctNetwork)


class DuctNetworkViewProvider:

    """A View Provider for the HVAC duct network object"""

    def __init__(self, obj):
        obj.Proxy = self

    def getIcon(self):
        return hvaclib.get_icon_path("DuctsIcon.svg")


#=================================================
# B. Command classes
#=================================================


class CommandCreateDuctNetwork:

    """Create HVAC Duct Network."""

    def QT_TRANSLATE_NOOP(self, text):
        return text

    def GetResources(self):
        return {'Pixmap': hvaclib.get_icon_path("CreateDuctsIcon.svg"),
                'MenuText': QT_TRANSLATE_NOOP('HVAC_CreateDuctNetwork', 'Create HVAC Duct Network'),
                'ToolTip': QT_TRANSLATE_NOOP('HVAC_CreateDuctNetwork', 'Create HVAC Duct Network from Sketch/ Line base Geometries')}

    def IsActive(self):
        if Gui.ActiveDocument:
            return True
        else:
            return False

    def Activated(self):
        create_new_duct_network()


class CommandActivateDuctNetwork:
    def __init__(self):
        self.task_panel = None

    def GetResources(self):
        return {
            'Pixmap': hvaclib.get_icon_path("ActivateDuctsIcon.svg"),
            "MenuText": QT_TRANSLATE_NOOP("HVAC_ActivateDuctNetwork", "Activate HVAC Network"),
            "ToolTip": QT_TRANSLATE_NOOP("HVAC_ActivateDuctNetwork", "Sets a HVAC duct network as the active one for editing."),
            "CmdType": "ForEdit",
        }

    def IsActive(self):
        return True
        if App.ActiveDocument is None:
            return False

        # Command is only active if no HVAC network is currently active
        if hvaclib.activeHVACNetwork() is not None:
            return False

        # And if there is at least one HVAC network in the document to activate
        if hvaclib.allHVACNetworks():
            return True

        return False

    def Activated(self):
        hvac_networks = hvaclib.allHVACNetworks()

        if len(hvac_networks) == 1:
            # If there's only one, activate it directly without showing a dialog
            DuctNetwork.setActive(hvac_networks[0])
        elif len(hvac_networks) > 1:
            # If there are multiple, show a task panel to let the user choose
            self.task_panel = ActivateHVACTaskPanel(hvac_networks)
            Gui.Control.showDialog(self.task_panel)


class CommandModifyDuctNetwork:

    """Modify HVAC Duct Network."""

    def QT_TRANSLATE_NOOP(self, text):
        return text

    def GetResources(self):
        return {'Pixmap': hvaclib.get_icon_path("ModifyDuctsIcon.svg"),
                'MenuText': QT_TRANSLATE_NOOP('HVAC_ModifyDuctNetwork', 'Modify HVAC Duct Network'),
                'ToolTip': QT_TRANSLATE_NOOP('HVAC_ModifyDuctNetwork',  'Modify the selected HVAC Duct Network')}

    def IsActive(self):
        if Gui.ActiveDocument:
            try:
                FreeCAD.ActiveDocument.findObjects(Name = "DuctNetwork")[0].Name
                return True
            except:
                pass
        else:
            return False

    def Activated(self):
        modify_duct_network()


class CommandDeleteDuctNetwork:

    """Delete a selected HVAC Duct Network."""

    def QT_TRANSLATE_NOOP(self, text):
        return text

    def GetResources(self):
        return {'Pixmap': hvaclib.get_icon_path("DeleteDuctsIcon.svg"),
                'MenuText': QT_TRANSLATE_NOOP('HVAC_DeleteDuctNetwork', 'Delete HVAC Duct Network'),
                'ToolTip': QT_TRANSLATE_NOOP('HVAC_DeleteDuctNetwork', 'Delete the selected HVAC Duct Network')}

    def IsActive(self):
        if Gui.ActiveDocument:
            try:
                FreeCAD.ActiveDocument.findObjects(Name = "DuctNetwork")[0].Name
                return True
            except:
                pass
        else:
            return False

    def Activated(self):
        delete_duct_network()


#=================================================
# C. Task Panel classes
#=================================================


class ActivateHVACTaskPanel:
    """A basic TaskPanel to create an assembly to activate."""

    def __init__(self, hvac_networks):
        self.hvac_networks = hvac_networks
        self.hvac_networks_dict = {}
        self.form = QtWidgets.QWidget()
        self.form.setWindowTitle(translate("HVAC_ActivateDuctNetwork", "Activate HVAC Duct Network"))

        layout = QtWidgets.QVBoxLayout(self.form)
        label = QtWidgets.QLabel(translate("HVAC_ActivateDuctNetwork", "Select a HVAC Duct Network to Activate:"))
        self.combo = QtWidgets.QComboBox()

        for net in self.hvac_networks:
            # Store the user-friendly Label for display, and the internal Name for activation
            self.combo.addItem(net.Label, net.Name)
            self.hvac_networks_dict[net.Name] = net

        layout.addWidget(label)
        layout.addWidget(self.combo)

    def accept(self):
        """Called when the user clicks OK."""
        selected_name = self.combo.currentData()
        if selected_name:
            DuctNetwork.setActive(self.hvac_networks_dict[selected_name])
        return True

    def reject(self):
        """Called when the user clicks Cancel or closes the panel."""
        return True


#=================================================
# D. General functions
#=================================================


def create_new_duct_network(name="DuctNetwork", set_active=True):
    """Create new duct network"""
    # Create new duct netowork and create default folders
    net = FreeCAD.ActiveDocument.addObject('App::DocumentObjectGroupPython', name)
    DuctNetwork(net)
    DuctNetworkViewProvider(net.ViewObject)
    print("HVAC - New DuctNetwork created")
    # Open duct network settings
    DuctNetworkConfigDialog.open_duct_network_configuration()
    # Set as active network
    if set_active:
        DuctNetwork.setActive(net)
    # Recompute document
    FreeCAD.ActiveDocument.recompute()

def modify_duct_network():
    """Modify the selected HVAC duct network object"""
    pass

def delete_duct_network():
    """Delete the selected HVAC duct network object"""
    pass


#=================================================
# E. Register Commands
#=================================================

if FreeCAD.GuiUp:
    FreeCAD.Gui.addCommand('HVAC_CreateDuctNetwork', CommandCreateDuctNetwork())
    FreeCAD.Gui.addCommand('HVAC_ModifyDuctNetwork', CommandModifyDuctNetwork())
    FreeCAD.Gui.addCommand('HVAC_DeleteDuctNetwork', CommandDeleteDuctNetwork())
    FreeCAD.Gui.addCommand('HVAC_ActivateDuctNetwork', CommandActivateDuctNetwork())
