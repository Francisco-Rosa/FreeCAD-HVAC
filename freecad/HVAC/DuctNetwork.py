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
from PySide import QtWidgets, QtCore
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
    def createObject(name):
        net = FreeCAD.ActiveDocument.addObject('App::DocumentObjectGroupPython', name)
        DuctNetwork(net)
        DuctNetworkViewProvider(net.ViewObject)
        return net

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
        
    def setEdit(self, vobj, mode):
        panel = TaskPanelEditDuctNetwork(vobj.Object)
        Gui.Control.showDialog(panel)
        return True
        
    def unsetEdit(self, vobj, mode):
        Gui.Control.closeDialog()
        return True
        
    def doubleClicked(self, vobj):
        obj = vobj.Object
        # Make it the active network
        activate_duct_network(obj, set_edit=False)
        return True 


#=================================================
# B. Command classes
#=================================================


class CommandCreateDuctNetwork:

    """Create HVAC Duct Network."""

    def QT_TRANSLATE_NOOP(self, text):
        return text

    def GetResources(self):
        return {'Pixmap': hvaclib.get_icon_path("CreateDuctsIcon.svg"),
                'MenuText': QT_TRANSLATE_NOOP('HVAC_CreateDuctNetwork', 'Create Network'),
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
            "MenuText": QT_TRANSLATE_NOOP("HVAC_ActivateDuctNetwork", "Activate Network"),
            "ToolTip": QT_TRANSLATE_NOOP("HVAC_ActivateDuctNetwork", "Sets a HVAC duct network as the active one for editing."),
            "CmdType": "ForEdit",
        }

    def IsActive(self):
        if Gui.ActiveDocument is None:
            return False

        # Command is active only if there is at least one HVAC network in the document to activate
        if hvaclib.allHVACNetworks():
            return True

        return False

    def Activated(self):
        hvac_networks = hvaclib.allHVACNetworks()
        selected_hvac_networks = hvaclib.selectedHVACNetworks()
        
        if len(hvac_networks) == 1:
            # If there's only one, activate it directly without showing a dialog
            activate_duct_network(hvac_networks[0], set_edit=False)
        elif selected_hvac_networks:
            # Select first selected
            activate_duct_network(selected_hvac_networks[0], set_edit=False)
        elif len(hvac_networks) > 1:
            # If there are multiple, show a task panel to let the user choose
            self.task_panel = TaskPanelActivate(hvac_networks)
            Gui.Control.showDialog(self.task_panel)


class CommandModifyDuctNetwork:

    """Modify HVAC Duct Network."""

    def QT_TRANSLATE_NOOP(self, text):
        return text

    def GetResources(self):
        return {'Pixmap': hvaclib.get_icon_path("ModifyDuctsIcon.svg"),
                'MenuText': QT_TRANSLATE_NOOP('HVAC_ModifyDuctNetwork', 'Modify Network'),
                'ToolTip': QT_TRANSLATE_NOOP('HVAC_ModifyDuctNetwork',  'Modify the selected HVAC Duct Network')}

    def IsActive(self):
        if Gui.ActiveDocument:
            selected_hvac_networks = hvaclib.selectedHVACNetworks()
            if selected_hvac_networks:
                return True
        else:
            return False

    def Activated(self):
        selected_hvac_networks = hvaclib.selectedHVACNetworks()
        if selected_hvac_networks:
            modify_duct_network(selected_hvac_networks[0])


class CommandDeleteDuctNetwork:

    """Delete a selected HVAC Duct Network."""

    def QT_TRANSLATE_NOOP(self, text):
        return text

    def GetResources(self):
        return {'Pixmap': hvaclib.get_icon_path("DeleteDuctsIcon.svg"),
                'MenuText': QT_TRANSLATE_NOOP('HVAC_DeleteDuctNetwork', 'Delete Network'),
                'ToolTip': QT_TRANSLATE_NOOP('HVAC_DeleteDuctNetwork', 'Delete the selected HVAC Duct Network')}

    def IsActive(self):
        if Gui.ActiveDocument:
            selected_hvac_networks = hvaclib.selectedHVACNetworks()
            if selected_hvac_networks:
                return True
        else:
            return False

    def Activated(self):
        selected_hvac_networks = hvaclib.selectedHVACNetworks()
        if selected_hvac_networks:
            delete_duct_networks(selected_hvac_networks)


#=================================================
# C. Task Panel classes
#=================================================


class TaskPanelActivate:
    """A basic TaskPanel to select an HVAC netowrk to activate."""

    def __init__(self, hvac_networks):
        self.hvac_networks = hvac_networks
        self.hvac_networks_dict = {}
        self.form = QtWidgets.QWidget()
        self.form.setWindowTitle(translate("HVAC_ActivateDuctNetwork", "Activate Network"))

        layout = QtWidgets.QVBoxLayout(self.form)
        label = QtWidgets.QLabel(translate("HVAC_ActivateDuctNetwork", "Select Network :"))
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
            QtCore.QTimer.singleShot(0, lambda: activate_duct_network(self.hvac_networks_dict[selected_name], set_edit=False))
        return True

    def reject(self):
        """Called when the user clicks Cancel or closes the panel."""
        return True
        

class TaskPanelEditDuctNetwork:
    """A basic TaskPanel to edit an HVAC netowrk."""

    def __init__(self, hvac_network):
        self.hvac_network = hvac_network
        self.hvac_networks_dict = {}
        self.form = QtWidgets.QWidget()
        self.form.setWindowTitle(translate("HVAC_EditDuctNetwork", "Edit Network"))

        layout = QtWidgets.QVBoxLayout(self.form)
        #TODO

    def accept(self):
        """Called when the user clicks OK."""
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
    net = DuctNetwork.createObject(name)
    print("HVAC - New DuctNetwork created")
    # Set as active network and enable edit mode
    activate_duct_network(net, set_edit=True)
    
def activate_duct_network(net, set_edit=False):
    DuctNetwork.setActive(net)
    # Set network to edit mode
    if set_edit:
        Gui.ActiveDocument.setEdit(net.Name)
    # Recompute document
    FreeCAD.ActiveDocument.recompute()

def modify_duct_network(net):
    """Modify the selected HVAC duct network object"""
    # Set as active network and enable edit mode
    activate_duct_network(net, set_edit=True)
    FreeCAD.ActiveDocument.recompute()
    print("HVAC - Edit DuctNetwork completed")

def delete_duct_networks(nets):
    """Delete the selected HVAC duct network object"""
    doc = FreeCAD.ActiveDocument
    for net in nets:
        if net.Document == doc:
            doc.removeObject(net.Name)
    doc.recompute()
    print("HVAC - Deleted selected {} DuctNetwork(s)".format(len(nets)))


#=================================================
# E. Register Commands
#=================================================

if FreeCAD.GuiUp:
    FreeCAD.Gui.addCommand('HVAC_CreateDuctNetwork', CommandCreateDuctNetwork())
    FreeCAD.Gui.addCommand('HVAC_ModifyDuctNetwork', CommandModifyDuctNetwork())
    FreeCAD.Gui.addCommand('HVAC_DeleteDuctNetwork', CommandDeleteDuctNetwork())
    FreeCAD.Gui.addCommand('HVAC_ActivateDuctNetwork', CommandActivateDuctNetwork())
