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

from ..utils import hvaclib
from ..core import Network
from . import Observer


#=================================================
# Helper functions
#=================================================

def createSketchInteractive(net):
    """
    Open the standard FreeCAD sketch creation panel and,
    after the sketch is created, move it under obj.Base.
    """
    if FreeCAD.ActiveDocument is None or Gui.ActiveDocument is None:
        return

    # Make this network active in the 3D view context
    net.Proxy.setActive()
    
    # Install observer before running the command
    def callback(obj, sketch):
        if sketch:
            obj.Proxy.addBaseObject(sketch)
            obj.Proxy.showAllJunctionGeometry()
            
    obs = Observer.NewSketchObserver(net, callback)
    FreeCAD.addDocumentObserver(obs)
    
    # Launch the built-in sketch creation command
    net.Proxy.hideAllJunctionGeometry()
    Gui.runCommand("Sketcher_NewSketch")
    
def createDraftLineInteractive(net, linetype='Line'):
    """
    Open the standard Draft Line command and, after the user exits the tool,
    move all newly created Draft line objects under obj.Base.
    """
    if FreeCAD.ActiveDocument is None or Gui.ActiveDocument is None:
        return

    # Make this network active in the 3D view context
    net.Proxy.setActive()
    
    # Install observer before running the command
    def callback(net, objs):
        for obj in objs:
            if hvaclib.isWire(obj):
                net.Proxy.addBaseObject(obj)
        net.Proxy.showAllJunctionGeometry()
            
    obs = Observer.NewDraftLineObserver(net, callback)
    FreeCAD.addDocumentObserver(obs)
    
    # Launch the built-in Draft Line/ BSpline creation command
    net.Proxy.hideAllJunctionGeometry()
    Gui.activateWorkbench("DraftWorkbench")
    if linetype=='Line':
        Gui.runCommand("Draft_Line")
    elif linetype=='BSpline':
        Gui.runCommand("Draft_BSpline")
        
        
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
                'ToolTip': QT_TRANSLATE_NOOP('HVAC_CreateDuctNetwork', 'Create a new HVAC Duct Network')}

    def IsActive(self):
        if Gui.ActiveDocument:
            return True
        else:
            return False

    def Activated(self):
        Network.create_new_duct_network()


class CommandActivateDuctNetwork:
    """Activate HVAC Duct Network."""

    def __init__(self):
        self.task_panel = None

    def GetResources(self):
        return {
            'Pixmap': hvaclib.get_icon_path("ActivateDuctsIcon.svg"),
            "MenuText": QT_TRANSLATE_NOOP("HVAC_ActivateDuctNetwork", "Activate Network"),
            "ToolTip": QT_TRANSLATE_NOOP("HVAC_ActivateDuctNetwork", "Sets an HVAC duct network as the active for editing."),
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
            Network.activate_duct_network(hvac_networks[0], set_edit=False)
        elif selected_hvac_networks:
            # Select first selected
            Network.activate_duct_network(selected_hvac_networks[0], set_edit=False)
        elif len(hvac_networks) > 1:
            # If there are multiple, show a task panel to let the user choose
            self.task_panel = TaskPanelActivate(hvac_networks, activate_callback = Network.activate_duct_network)
            Gui.Control.showDialog(self.task_panel)


class CommandModifyDuctNetwork:
    """Modify HVAC Duct Network."""

    def QT_TRANSLATE_NOOP(self, text):
        return text

    def GetResources(self):
        return {'Pixmap': hvaclib.get_icon_path("ModifyDuctsIcon.svg"),
                'MenuText': QT_TRANSLATE_NOOP('HVAC_ModifyDuctNetwork', 'Modify Network'),
                'ToolTip': QT_TRANSLATE_NOOP('HVAC_ModifyDuctNetwork',  'Modify base geometry for the selected HVAC Duct Network')}

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
            Network.modify_duct_network(selected_hvac_networks[0])
        else:
            active_hvac_network = hvaclib.activeHVACNetwork()
            Network.modify_duct_network(active_hvac_network)
            
            
class CommandCreateVirtualJunction:
    def GetResources(self):
        return {
            "Pixmap": hvaclib.get_icon_path("CreateVirtJunction.svg"),
            "MenuText": "Create Junction",
            "ToolTip": "Create a virtual junction from the selected base points/ junctions",
        }

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None and hvaclib.activeHVACNetwork() is not None
            
    def _GetSelectedPoints(self, parser):
        
        from ..core.Network import DuctNetwork, DuctJunction
        
        # Get selection extended including points
        sels = Gui.Selection.getSelectionEx()
        if not sels:
            FreeCAD.Console.PrintWarning("HVAC - Select two or more base points.\n")
            return
        
        points = set()
        
        for sel in sels:
            if sel.Object is None:
                return None
        
            # Case 1: Base point selected
            if DuctNetwork.isBaseObject(sel.Object):
                # Find point in selection
                point = None
                for sub in list(getattr(sel, "SubObjects", []) or []):
                    if hasattr(sub, "Point"):
                        point = sub.Point
                        break
                    if hasattr(sub, "Vertexes") and len(sub.Vertexes) == 1:
                        point = sub.Vertexes[0].Point
                        break
                if point:
                    points.add(hvaclib.vec_to_xyz(point))

            # Case 2: Terminal Junction selected
            if hvaclib.isDuctJunction(sel.Object):
                ana_nid = sel.Object.NodeId
                geo_points = parser.node_group_members_xyz(ana_nid)
                if geo_points:
                    points.add(geo_points[0])
                
        return list(points)

    def Activated(self):
        from ..core.Network import DuctNetwork, DuctJunctionVirtual
        
        # Get active network
        net = hvaclib.activeHVACNetwork()
        if net is None:
            FreeCAD.Console.PrintWarning("HVAC - No active duct network.\n")
            return
            
        # Get parser from network object
        parser = net.Proxy.getParser()

        # Get selected points
        selected_points = self._GetSelectedPoints(parser)
        # Get quantised nodemap from parser
        geo_node_map = {key: item for (key, item) in parser.geometric_node_point_map().items()}
        # Find nodekeys from nodemap
        member_keys = []
        member_points = []
        for id, point in geo_node_map.items():
            if hvaclib.vec_in_list(point, selected_points) and not hvaclib.vec_in_list(point, member_points):
                key = parser.geometric_node_key(id)
                member_keys.append(key)
                member_points.append(point)
        
        if len(member_keys) < 2:
            FreeCAD.Console.PrintWarning("HVAC - Select at least two valid base points.\n")
            return

        # Reject overlap with existing virtual junction definitions
        used = set()
        for vj in net.Proxy.collectVirtualJunctionObjects():
            used.update(vj.Proxy.getMemberNodeKeys())
            
        overlap = used.intersection(member_keys)
        if overlap:
            FreeCAD.Console.PrintWarning(
                "HVAC - Selected point(s) already belong to another virtual junction: {}\n".format(
                    ", ".join(sorted(overlap))
                )
            )
            return
        
        # Create virtual junction
        doc = net.Document
        doc.openTransaction("Create Virtual Junction")
        try:
            net.Proxy.addVirtualJunctionObject(member_keys, member_points)
            net.Proxy.requestSync()
            doc.commitTransaction()
        except Exception:
            doc.abortTransaction()
            raise
            
            
class CommandEditBaseObject:
    """Edit base object of selected duct."""

    def QT_TRANSLATE_NOOP(self, text):
        return text

    def GetResources(self):
        return {'Pixmap': hvaclib.get_icon_path("ModifyRouting.svg"),
                'MenuText': QT_TRANSLATE_NOOP('HVAC_EditBaseObject', 'Modify Routing'),
                'ToolTip': QT_TRANSLATE_NOOP('HVAC_EditBaseObject',  'Modify routing of selected duct segment')}

    def IsActive(self):
        if Gui.ActiveDocument:
            active_hvac_network = hvaclib.activeHVACNetwork()
            selected_geom = [
                o for o in (hvaclib.selectedGeometryObjects() or [])
                if hvaclib.isDuctSegment(o)
            ]
            selected_base_obj = hvaclib.selectedBaseObjects()
            if active_hvac_network and (selected_geom or selected_base_obj):
                return True
        else:
            return False

    def Activated(self):
        selected_geo_objs = [
            o for o in (hvaclib.selectedGeometryObjects() or [])
            if hvaclib.isDuctSegment(o)
        ]
        selected_base_objs = hvaclib.selectedBaseObjects()
        if selected_geo_objs:
            base = Network.DuctNetwork.getOwnerBaseObject(selected_geo_objs[0])
        elif selected_base_objs:
            base = selected_base_objs[0]
            
        if base:
            if hvaclib.isSketch(base):
                Gui.ActiveDocument.setEdit(base.Name)
            elif hvaclib.isWire(base):
                Gui.Selection.clearSelection()
                Gui.Selection.addSelection(base)
                
                # Install observer before running the command
                def callback(net, objs):
                    pass
                net = hvaclib.activeHVACNetwork()
                obs = Observer.NewDraftLineObserver(net, callback)
                FreeCAD.addDocumentObserver(obs)
                
                # Set change workbench and set edit mode
                Gui.activateWorkbench("DraftWorkbench")                
                Gui.ActiveDocument.setEdit(base)


class CommandDeleteDuctNetwork:
    """Delete a selected HVAC Duct Network."""

    def QT_TRANSLATE_NOOP(self, text):
        return text

    def GetResources(self):
        return {'Pixmap': "",
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
            Network.delete_duct_networks(selected_hvac_networks)
            
    
class CommandCreateSketch:
    """interactively adds a sketch to the currently active network"""
    
    def QT_TRANSLATE_NOOP(self, text):
        return text
    
    def GetResources(self):
        return {
            'Pixmap': hvaclib.get_icon_path("NewSketch.svg"),
            "MenuText": QT_TRANSLATE_NOOP('HVAC_CreateSketch', 'New Sketch'),
            "ToolTip": QT_TRANSLATE_NOOP('HVAC_CreateSketch', 'Create a constrained sketch for defining routing of ducts inside the active duct network')
        }

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None and hvaclib.activeHVACNetwork() is not None

    def Activated(self):
        net = hvaclib.activeHVACNetwork()
        if net:
            createSketchInteractive(net)
            

class CommandCreateLine:
    """Interactively adds Draft line objects to the currently active network."""

    def QT_TRANSLATE_NOOP(self, text):
        return text

    def GetResources(self):
        return {
            'Pixmap': hvaclib.get_icon_path("CreateWire.svg"),
            "MenuText": QT_TRANSLATE_NOOP("HVAC_CreateLine", "New Straight"),
            "ToolTip": QT_TRANSLATE_NOOP(
                "HVAC_CreateLine",
                "Create straight duct routes inside the active duct network"
            ),
        }

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None and hvaclib.activeHVACNetwork() is not None

    def Activated(self):
        net = hvaclib.activeHVACNetwork()
        if net:
            createDraftLineInteractive(net)
            
            
class CommandCreateSpline:
    """Interactively adds Draft Spline object to the currently active network."""

    def QT_TRANSLATE_NOOP(self, text):
        return text

    def GetResources(self):
        return {
            'Pixmap': hvaclib.get_icon_path("CreateSpline.svg"),
            "MenuText": QT_TRANSLATE_NOOP("HVAC_CreateSpline", "New Curved"),
            "ToolTip": QT_TRANSLATE_NOOP(
                "HVAC_CreateLine",
                "Create curved duct routes inside the active duct network"
            ),
        }

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None and hvaclib.activeHVACNetwork() is not None

    def Activated(self):
        net = hvaclib.activeHVACNetwork()
        if net:
            createDraftLineInteractive(net, linetype='BSpline')
          
            
class CommandEditType:
    """Edit library/type selection of selected HVAC geometry."""

    def __init__(self):
        self.task_panel = None

    def QT_TRANSLATE_NOOP(self, text):
        return text

    def GetResources(self):
        return {
            'Pixmap': hvaclib.get_icon_path("EditType.svg"),
            'MenuText': QT_TRANSLATE_NOOP('HVAC_EditType', 'Edit Type'),
            'ToolTip': QT_TRANSLATE_NOOP('HVAC_EditType', 'Edit library/ type of selected duct segment(s) or junction(s)'),
            'CmdType': 'ForEdit',
        }

    def IsActive(self):
        if Gui.ActiveDocument is None:
            return False
        selected_geom = hvaclib.selectedGeometryObjects()
        return bool(selected_geom)

    def Activated(self):
        from ..ui.TaskPanel import TaskPanelTypeEditor

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
            apply_callback=Network.DuctNetwork.applyTypeSelection,
        )
        Gui.Control.showDialog(self.task_panel)


class CommandEditPlacement:
    """Edit attachment, offset and profile X axis of selected duct segments."""

    def __init__(self):
        self.task_panel = None

    def GetResources(self):
        return {
            'Pixmap': hvaclib.get_icon_path("EditPlacement.svg"),
            'MenuText': QT_TRANSLATE_NOOP('HVAC_EditPlacement', 'Edit Placement'),
            'ToolTip': QT_TRANSLATE_NOOP(
                'HVAC_EditPlacement',
                'Edit Attachment, User offset and Profile X axis of selected duct segment(s)'
            ),
            'CmdType': 'ForEdit',
        }

    def IsActive(self):
        if Gui.ActiveDocument is None:
            return False
        selected_geom = hvaclib.selectedGeometryObjects() or []
        return any(hvaclib.isDuctSegment(o) for o in selected_geom)

    def Activated(self):
        from ..ui.TaskPanel import TaskPanelSegmentPlacementEditor
        selected_geom = hvaclib.selectedGeometryObjects() or []
        selected_segments = [o for o in selected_geom if hvaclib.isDuctSegment(o)]
        if not selected_segments:
            return

        self.task_panel = TaskPanelSegmentPlacementEditor(
            selected_segments,
            apply_callback=Network.DuctNetwork.applyPlacementSelection,
        )
        Gui.Control.showDialog(self.task_panel)
        
        
class CommandEditNetworkTypeDefaults:
    """Edit network-level HVAC type defaults."""

    def __init__(self):
        self.task_panel = None

    def GetResources(self):
        return {
            'Pixmap': hvaclib.get_icon_path("Defaults.svg"),
            'MenuText': QT_TRANSLATE_NOOP('HVAC_NetworkTypeDefaults', 'Network Defaults'),
            'ToolTip': QT_TRANSLATE_NOOP('HVAC_NetworkTypeDefaults', 'Edit default settings for the active network'),
            'CmdType': 'ForEdit',
        }

    def IsActive(self):
        if Gui.ActiveDocument is None:
            return False
        return hvaclib.activeHVACNetwork() is not None

    def Activated(self):
        from ..ui.TaskPanel import TaskPanelNetworkTypeDefaults

        net = hvaclib.activeHVACNetwork()
        if net is None:
            return

        self.task_panel = TaskPanelNetworkTypeDefaults(
            net,
            apply_callback=Network.DuctNetwork.applyNetworkTypeDefaults,
        )
        Gui.Control.showDialog(self.task_panel)


class CommandResetTypesToNetworkDefaults:
    """Reset selected HVAC geometry objects to their network defaults."""

    def GetResources(self):
        return {
            'Pixmap': hvaclib.get_icon_path("ResetType.svg"),
            'MenuText': QT_TRANSLATE_NOOP('HVAC_ResetTypesToDefaults', 'Reset to Defaults'),
            'ToolTip': QT_TRANSLATE_NOOP(
                'HVAC_ResetTypesToDefaults',
                'Reset the type and placement options of selected duct segment(s) to their owner network defaults'
            ),
            'CmdType': 'ForEdit',
        }

    def IsActive(self):
        if Gui.ActiveDocument is None:
            return False
        selected_geom = hvaclib.selectedGeometryObjects()
        return bool(selected_geom)

    def Activated(self):
        selected_geom = hvaclib.selectedGeometryObjects()
        if not selected_geom:
            return

        Network.DuctNetwork.resetObjectsToNetworkDefaults(selected_geom)
        
        FreeCAD.Console.PrintMessage(
            "HVAC - Reset {} object(s) to network defaults.\n".format(len(selected_geom))
        )
        

class CommandReloadHVACLibraries:
    """Reload HVAC libraries from configured search paths."""

    def GetResources(self):
        return {
            'Pixmap': hvaclib.get_icon_path("ModifyDuctsIcon.svg"),
            'MenuText': QT_TRANSLATE_NOOP('HVAC_ReloadLibraries', 'Reload Libraries'),
            'ToolTip': QT_TRANSLATE_NOOP('HVAC_ReloadLibraries', 'Reload HVAC libraries from disk'),
            'CmdType': 'ForEdit',
        }

    def IsActive(self):
        return Gui.ActiveDocument is not None

    def Activated(self):
        hvaclib.reload_hvac_libraries()
        hvaclib.debug_print_loaded_libraries()
        
        
#=================================================
# Register Commands
#=================================================

if FreeCAD.GuiUp:
    FreeCAD.Gui.addCommand('HVAC_CreateDuctNetwork', CommandCreateDuctNetwork())
    FreeCAD.Gui.addCommand('HVAC_ModifyDuctNetwork', CommandModifyDuctNetwork())
    FreeCAD.Gui.addCommand('HVAC_EditBaseObject', CommandEditBaseObject())
    FreeCAD.Gui.addCommand('HVAC_CreateVirtualJunction', CommandCreateVirtualJunction())
    FreeCAD.Gui.addCommand('HVAC_DeleteDuctNetwork', CommandDeleteDuctNetwork())
    FreeCAD.Gui.addCommand('HVAC_ActivateDuctNetwork', CommandActivateDuctNetwork())
    FreeCAD.Gui.addCommand("HVAC_CreateSketch", CommandCreateSketch())
    FreeCAD.Gui.addCommand("HVAC_CreateLine", CommandCreateLine())
    FreeCAD.Gui.addCommand("HVAC_CreateSpline", CommandCreateSpline())
    FreeCAD.Gui.addCommand('HVAC_EditType', CommandEditType())
    FreeCAD.Gui.addCommand('HVAC_EditPlacement', CommandEditPlacement())
    FreeCAD.Gui.addCommand('HVAC_EditNetworkTypeDefaults', CommandEditNetworkTypeDefaults())
    FreeCAD.Gui.addCommand('HVAC_ResetTypesToDefaults', CommandResetTypesToNetworkDefaults())
    FreeCAD.Gui.addCommand('HVAC_ReloadLibraries', CommandReloadHVACLibraries())  # Debug method
