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

"""This module implements HVAC duct description classes."""

import FreeCAD
import FreeCADGui as Gui
from PySide import QtWidgets, QtCore
from PySide.QtCore import QT_TRANSLATE_NOOP
translate = FreeCAD.Qt.translate

from . import hvaclib
from . import DuctNetwork


#=================================================
# Command classes
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
        DuctNetwork.create_new_duct_network()


class CommandActivateDuctNetwork:
    """Activate HVAC Duct Network."""

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
        from .TaskPanel import TaskPanelActivate
        
        hvac_networks = hvaclib.allHVACNetworks()
        selected_hvac_networks = hvaclib.selectedHVACNetworks()

        if len(hvac_networks) == 1:
            # If there's only one, activate it directly without showing a dialog
            DuctNetwork.activate_duct_network(hvac_networks[0], set_edit=False)
        elif selected_hvac_networks:
            # Select first selected
            DuctNetwork.activate_duct_network(selected_hvac_networks[0], set_edit=False)
        elif len(hvac_networks) > 1:
            # If there are multiple, show a task panel to let the user choose
            self.task_panel = TaskPanelActivate(hvac_networks, activate_callback = DuctNetwork.activate_duct_network)
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
            active_hvac_network = hvaclib.activeHVACNetwork()
            if selected_hvac_networks or active_hvac_network:
                return True
        else:
            return False

    def Activated(self):
        selected_hvac_networks = hvaclib.selectedHVACNetworks()
        if selected_hvac_networks:
            DuctNetwork.modify_duct_network(selected_hvac_networks[0])
        else:
            active_hvac_network = hvaclib.activeHVACNetwork()
            DuctNetwork.modify_duct_network(active_hvac_network)
            
            
class CommandEditBaseObject:
    """Edit base object of selected duct."""

    def QT_TRANSLATE_NOOP(self, text):
        return text

    def GetResources(self):
        return {'Pixmap': 'Draft_SubelementHighlight',
                'MenuText': QT_TRANSLATE_NOOP('HVAC_EditBaseObject', 'Modify routing'),
                'ToolTip': QT_TRANSLATE_NOOP('HVAC_EditBaseObject',  'Modify routing of selected duct')}

    def IsActive(self):
        if Gui.ActiveDocument:
            active_hvac_network = hvaclib.activeHVACNetwork()
            selected_geom = [
                o for o in (hvaclib.selectedGeometryObjects() or [])
                if hvaclib.isDuctSegment(o)
            ]
            if active_hvac_network and selected_geom:
                return True
        else:
            return False

    def Activated(self):
        base_objs = [
            o for o in (hvaclib.selectedGeometryObjects() or [])
            if hvaclib.isDuctSegment(o)
        ]
        if base_objs:
            base = DuctNetwork.DuctNetwork.getOwnerBaseObject(base_objs[0])
            if base:
                if hvaclib.obj_is_sketch(base):
                    Gui.ActiveDocument.setEdit(base.Name)
                elif hvaclib.obj_is_wire(base):
                    Gui.Selection.clearSelection()
                    Gui.Selection.addSelection(base)
                    Gui.ActiveDocument.setEdit(base)


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
            DuctNetwork.delete_duct_networks(selected_hvac_networks)
            
    
class CommandCreateSketch:
    """interactively adds a sketch to the currently active network"""
    
    def QT_TRANSLATE_NOOP(self, text):
        return text
    
    def GetResources(self):
        return {
            "Pixmap": "Sketcher_NewSketch",
            "MenuText": QT_TRANSLATE_NOOP('HVAC_CreateSketch', 'New Sketch'),
            "ToolTip": QT_TRANSLATE_NOOP('HVAC_CreateSketch', 'Create a new sketch inside the active duct network')
        }

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None and hvaclib.activeHVACNetwork() is not None

    def Activated(self):
        net = hvaclib.activeHVACNetwork()
        if net:
            DuctNetwork.DuctNetwork.createSketchInteractive(net)
            
            
class CommandCreateLine:
    """Interactively adds Draft line objects to the currently active network."""

    def QT_TRANSLATE_NOOP(self, text):
        return text

    def GetResources(self):
        return {
            "Pixmap": "Draft_Line",
            "MenuText": QT_TRANSLATE_NOOP("HVAC_CreateLine", "New Line"),
            "ToolTip": QT_TRANSLATE_NOOP(
                "HVAC_CreateLine",
                "Create line objects inside the active duct network"
            ),
        }

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None and hvaclib.activeHVACNetwork() is not None

    def Activated(self):
        net = hvaclib.activeHVACNetwork()
        if net:
            DuctNetwork.DuctNetwork.createDraftLineInteractive(net)
          
            
class CommandEditType:
    """Edit library/type selection of selected HVAC geometry."""

    def __init__(self):
        self.task_panel = None

    def QT_TRANSLATE_NOOP(self, text):
        return text

    def GetResources(self):
        return {
            'Pixmap': hvaclib.get_icon_path("ModifyDuctsIcon.svg"),
            'MenuText': QT_TRANSLATE_NOOP('HVAC_EditType', 'Edit Type'),
            'ToolTip': QT_TRANSLATE_NOOP('HVAC_EditType', 'Edit library/type of selected duct segments or junctions'),
            'CmdType': 'ForEdit',
        }

    def IsActive(self):
        if Gui.ActiveDocument is None:
            return False
        selected_geom = hvaclib.selectedGeometryObjects()
        return bool(selected_geom)

    def Activated(self):
        from .TaskPanel import TaskPanelTypeEditor

        selected_geom = hvaclib.selectedGeometryObjects()
        if not selected_geom:
            return

        # Keep selection homogeneous for the first version
        has_segments = any(hvaclib.isDuctSegment(o) for o in selected_geom)
        has_junctions = any(hvaclib.isDuctJunction(o) for o in selected_geom)
        if has_segments and has_junctions:
            FreeCAD.Console.PrintWarning(
                "HVAC - Please select only segments or only junctions.\n"
            )
            return

        self.task_panel = TaskPanelTypeEditor(
            selected_geom,
            apply_callback=DuctNetwork.DuctNetwork.applyTypeSelection,
        )
        Gui.Control.showDialog(self.task_panel)


class CommandEditNetworkTypeDefaults:
    """Edit network-level HVAC type defaults."""

    def __init__(self):
        self.task_panel = None

    def GetResources(self):
        return {
            'Pixmap': hvaclib.get_icon_path("ModifyDuctsIcon.svg"),
            'MenuText': QT_TRANSLATE_NOOP('HVAC_NetworkTypeDefaults', 'Network Type Defaults'),
            'ToolTip': QT_TRANSLATE_NOOP('HVAC_NetworkTypeDefaults', 'Edit default HVAC library and segment auto-type settings for the active network'),
            'CmdType': 'ForEdit',
        }

    def IsActive(self):
        if Gui.ActiveDocument is None:
            return False
        return hvaclib.activeHVACNetwork() is not None

    def Activated(self):
        from .TaskPanel import TaskPanelNetworkTypeDefaults

        net = hvaclib.activeHVACNetwork()
        if net is None:
            return

        self.task_panel = TaskPanelNetworkTypeDefaults(
            net,
            apply_callback=DuctNetwork.DuctNetwork.applyNetworkTypeDefaults,
        )
        Gui.Control.showDialog(self.task_panel)

#=================================================
# Register Commands
#=================================================

if FreeCAD.GuiUp:
    FreeCAD.Gui.addCommand('HVAC_CreateDuctNetwork', CommandCreateDuctNetwork())
    FreeCAD.Gui.addCommand('HVAC_ModifyDuctNetwork', CommandModifyDuctNetwork())
    FreeCAD.Gui.addCommand('HVAC_EditBaseObject', CommandEditBaseObject())
    FreeCAD.Gui.addCommand('HVAC_DeleteDuctNetwork', CommandDeleteDuctNetwork())
    FreeCAD.Gui.addCommand('HVAC_ActivateDuctNetwork', CommandActivateDuctNetwork())
    FreeCAD.Gui.addCommand("HVAC_CreateSketch", CommandCreateSketch())
    FreeCAD.Gui.addCommand("HVAC_CreateLine", CommandCreateLine())
    FreeCAD.Gui.addCommand('HVAC_EditType', CommandEditType())
    FreeCAD.Gui.addCommand('HVAC_EditNetworkTypeDefaults', CommandEditNetworkTypeDefaults())
