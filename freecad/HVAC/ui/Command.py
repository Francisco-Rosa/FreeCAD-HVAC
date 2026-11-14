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

import traceback

import FreeCAD
import Part
import FreeCADGui as Gui
from PySide import QtWidgets, QtCore, QtGui
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
            
    obs = Observer.SketchObserver(net, callback)
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
            
    obs = Observer.DraftLineObserver(net, callback)
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

            # Case 2: Terminal Junction selected (e.g. from the tree view,
            # where the logical DuctJunction node is still selectable even
            # though it has no shape of its own)
            if hvaclib.isDuctJunction(sel.Object):
                ana_nid = sel.Object.NodeId
                geo_points = parser.node_group_members_xyz(ana_nid)
                if geo_points:
                    points.add(geo_points[0])

            # Case 3: A junction's fitting geometry selected in the 3D view.
            # DuctJunction itself is purely logical and has no Shape (see
            # Junction.py), so the only thing a user can actually click on
            # at a junction is one of its DuctComponent fittings -- resolve
            # back to the owning junction via ParentJunctionName.
            if hvaclib.isDuctComponent(sel.Object):
                doc = sel.Object.Document
                parent_name = getattr(sel.Object, "ParentJunctionName", "")
                parent_junction = doc.getObject(parent_name) if parent_name else None
                if parent_junction is not None and hvaclib.isDuctJunction(parent_junction):
                    ana_nid = parent_junction.NodeId
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
                obs = Observer.DraftLineObserver(net, callback)
                FreeCAD.addDocumentObserver(obs)
                
                # Set change workbench and set edit mode
                Gui.activateWorkbench("DraftWorkbench")                
                Gui.ActiveDocument.setEdit(base)


class CommandReverseGeometryDirection:
    """
    Reverse direction of selected base geometry.

    Supported selection:
        - Sketch selected edges
        - Draft Line object
        - Draft Wire / Polyline object

    Notes:
        - For Sketches, only selected EdgeN sub-elements are reversed.
        - For Draft objects, the whole Draft object is reversed.
        - For Draft Wire sub-edge selection, the full wire is reversed.
    """

    def GetResources(self):
        return {
            "Pixmap": hvaclib.get_icon_path("ReverseDirection.svg"),
            "MenuText": QT_TRANSLATE_NOOP(
                "HVAC_ReverseGeometryDirection",
                "Reverse Curve"
            ),
            "ToolTip": QT_TRANSLATE_NOOP(
                "HVAC_ReverseGeometryDirection",
                "Reverse the direction of selected Sketch or Draft geometry"
            )
        }

    def IsActive(self):
        if Gui.ActiveDocument is None:
            return False
        if self._get_sketch_indices():
            return True
        if self._get_draft_objects():
            return True
        return False

    def Activated(self):
        # Collect sketch and draft selections
        sketch_selection = self._get_sketch_indices()
        draft_objects = self._get_draft_objects()
        if not sketch_selection and not draft_objects:
            FreeCAD.Console.PrintWarning(
                "HVAC - Select Sketch edge(s) or Draft Line/Wire object(s) to reverse.\n"
            )
            return
            
        doc = FreeCAD.ActiveDocument
        reversed_sketch_count = 0
        reversed_draft_count = 0
        failed = []
        doc.openTransaction("Reverse Geometry Direction")
        try:
            # -----------------------------------------
            # Reverse selected Sketch geometry
            # -----------------------------------------
            for sketch, indices in sketch_selection.items():
                # Reverse geometry and collect reversed geometries
                reversed_geometries = {}
                for geo_index in sorted(indices):
                    geo = sketch.Geometry[geo_index]
                    try:
                        reversed_geometries[geo_index] = (
                            self._reversed_sketch_geometry(geo)
                        )
                    except Exception as err:
                        failed.append(
                            "{}.Edge{}: {}".format(
                                sketch.Name,
                                geo_index + 1,
                                err,
                            )
                        )
                if not reversed_geometries:
                    continue
                # Swap endpoint constraint references and replace geometry
                self._swap_endpoint_constraint_refs(
                    sketch,
                    reversed_geometries.keys(),
                )
                for geo_index, new_geo in reversed_geometries.items():
                    self._replace_sketch_geometry(sketch, geo_index, new_geo)
                    reversed_sketch_count += 1
                # Solve sketch and recompute
                try:
                    sketch.solve()
                except Exception as e:
                    FreeCAD.Console.PrintWarning(
                        "HVAC - Sketch solve failed: {}\n".format(e)
                    )
                sketch.recompute()
            # -----------------------------------------
            # Reverse selected Draft objects
            # -----------------------------------------
            for obj in draft_objects:
                try:
                    self._reverse_draft_object_direction(obj)
                    obj.recompute()
                    reversed_draft_count += 1
                except Exception as err:
                    failed.append(
                        "{}: {}".format(
                            getattr(obj, "Name", "<unknown>"),
                            err,
                        )
                    )
            doc.recompute()
            doc.commitTransaction()
        except Exception:
            doc.abortTransaction()
            raise

        total = reversed_sketch_count + reversed_draft_count
        if total:
            FreeCAD.Console.PrintMessage(
                "HVAC - Reversed direction of {} item(s): {} sketch edge(s), {} Draft object(s).\n".format(
                    total,
                    reversed_sketch_count,
                    reversed_draft_count,
                )
            )
        for msg in failed:
            FreeCAD.Console.PrintWarning(
                "HVAC - Could not reverse {}\n".format(msg)
            )

    # =================================================
    # Reverse geometry direction helpers
    # =================================================
    
    def _get_sketch_indices(self):
        """
        Return {sketch: set(geo_indices)} for selected non-construction sketch edges.
    
        Handles both:
            1. Sketch edit mode:
            selected EdgeN -> Nth visible/non-construction sketch geometry
    
            2. Normal 3D view mode:
            selected EdgeN -> sketch.Shape EdgeN -> matched back to sketch.Geometry
        """
            
        result = {}
    
        for sel in Gui.Selection.getSelectionEx():
            sketch = getattr(sel, "Object", None)
            if not hvaclib.isSketch(sketch):
                continue
    
            # Check whether this sketch is currently in edit mode.
            in_edit = Gui.ActiveDocument.getInEdit() is sketch.ViewObject
    
            # Find valid geometric indices
            visible_geo_indices = []
            for geo_index, geo in enumerate(sketch.Geometry):
                # Skip construction geometry and point geometry.
                if sketch.getConstruction(geo_index):
                    continue
                if "Point" in geo.TypeId or geo.__class__.__name__ in ("Point", "Point2d"):
                    continue
                # Add valid geometry index to the list.
                visible_geo_indices.append(geo_index)
    

            # Edit-mode sketcher edge mapping.
            if in_edit:
                edge_to_geo = {
                    edge_no: geo_index
                    for edge_no, geo_index in enumerate(visible_geo_indices, start=1)
                }
            else:
                edge_to_geo = {}

            # Geometry matching function.
            def match_shape_edge_to_geo(sub_name):
                """
                Normal-mode mapping:
                    sketch.Shape EdgeN -> matching sketch.Geometry index
                """
                try:
                    selected_edge = sketch.Shape.getElement(sub_name)
                except Exception:
                    try:
                        edge_no = int(sub_name[4:])
                        selected_edge = sketch.Shape.Edges[edge_no - 1]
                    except Exception:
                        return None
    
                if getattr(selected_edge, "ShapeType", "") != "Edge":
                    return None
    
                try:
                    diag = sketch.Shape.BoundBox.DiagonalLength
                except Exception:
                    diag = 1.0
    
                tol = 1e-7 * max(1.0, diag)
    
                best_geo = None
                best_score = None
    
                for geo_index in visible_geo_indices:
                    geo = sketch.Geometry[geo_index]
    
                    try:
                        geo_shape = geo.toShape()
                    except Exception:
                        continue
    
                    try:
                        dist = selected_edge.distToShape(geo_shape)[0]
                        length_diff = abs(selected_edge.Length - geo_shape.Length)
                    except Exception:
                        continue
    
                    if dist <= tol and length_diff <= tol:
                        score = dist + length_diff
                        if best_score is None or score < best_score:
                            best_score = score
                            best_geo = geo_index
    
                return best_geo
    
            # Find selected geometry indices.

            indices = set()

            for sub in (getattr(sel, "SubElementNames", None) or []):
                if not sub.startswith("Edge"):
                    continue
    
                geo_index = None

                if not in_edit:
                    geo_index = match_shape_edge_to_geo(sub)

                if geo_index is None:
                    try:
                        selected_edge_no = int(sub[4:])
                    except ValueError:
                        continue
                
                    geo_index = edge_to_geo.get(selected_edge_no)
                
                    if geo_index is not None and not in_edit:
                        FreeCAD.Console.PrintWarning(
                            "HVAC - Used fallback EdgeN mapping for {}.{}; "
                            "normal-view Sketch.Shape edge order may be unstable.\n".format(
                                sketch.Name,
                                sub,
                            )
                        )
    
                if geo_index is None:
                    FreeCAD.Console.PrintWarning(
                        "HVAC - Could not map {}.{} to sketch geometry.\n".format(
                            sketch.Name,
                            sub,
                        )
                    )
                    continue
    
                indices.add(geo_index)
    
            if indices:
                result.setdefault(sketch, set()).update(indices)
    
        return result
    
    
    def _get_draft_objects(self):
            """Return list of unique selected Draft wire/line objects."""
            seen = set()
            result = []
            for sel in Gui.Selection.getSelectionEx():
                obj = getattr(sel, "Object", None)
                if hvaclib.isWire(obj) and obj.Name not in seen:
                    seen.add(obj.Name)
                    result.append(obj)
            return result
    
    
    def _reversed_sketch_geometry(self, geo):
        """
        Return a reversed copy of a Sketcher geometry object.
        Primary path:
            copy + reverse()
        Fallback:
            StartPoint/EndPoint swap for line-like bounded geometry.
        """
        # Generic geometry path.
        try:
            new_geo = geo.copy()
            reverse_fn = getattr(new_geo, "reverse", None)
            if callable(reverse_fn):
                reverse_fn()
                return new_geo
        except Exception:
            pass
        # Fallback for line segments.
        if "LineSegment" in geo.TypeId or "LineSegment" in geo.__class__.__name__:
            sp = getattr(geo, "StartPoint", None)
            ep = getattr(geo, "EndPoint", None)
            return Part.LineSegment( 
                FreeCAD.Vector(ep),
                FreeCAD.Vector(sp),
            )
        # Fallback for unsupported geometry types.
        raise TypeError(
            "Unsupported sketch geometry type: {}".format(
                geo.TypeId or geo.__class__.__name__
            )
        )
    
    def _replace_sketch_geometry(self, sketch, geo_index, new_geo):
        """
        Replace one geometry item in a sketch.
        """
        set_geometry = getattr(sketch, "setGeometry", None)
        if callable(set_geometry):
            try:
                set_geometry(geo_index, new_geo)
                return
            except Exception:
                pass
        geos = list(sketch.Geometry)
        geos[geo_index] = new_geo
        sketch.Geometry = geos
    
    def _swap_endpoint_constraint_refs(self, sketch, reversed_indices):
        """
        Keep endpoint constraints attached to the same physical endpoint
        after geometry reversal.
        Sketcher point references:
            1 -> start point
            2 -> end point
        """
        reversed_indices = set(reversed_indices)
        constraints = list(getattr(sketch, "Constraints", []) or [])
        changed = False
    
        for c in constraints:
            for geo_attr, pos_attr in (
                ("First", "FirstPos"),
                ("Second", "SecondPos"),
                ("Third", "ThirdPos"),
            ):
                if not hasattr(c, geo_attr) or not hasattr(c, pos_attr):
                    continue
                try:
                    geo_id = getattr(c, geo_attr)
                    pos_id = getattr(c, pos_attr)
                except Exception:
                    continue
                if geo_id not in reversed_indices:
                    continue
    
                if pos_id == 1:
                    setattr(c, pos_attr, 2)
                    changed = True
                elif pos_id == 2:
                    setattr(c, pos_attr, 1)
                    changed = True
    
        if changed:
            sketch.Constraints = constraints
    
    
    def _reverse_draft_object_direction(self, obj):
        """
        Reverse Draft object direction by changing parametric properties.
    
        Do not reverse obj.Shape directly.
        """
        # Draft Wire / Polyline / BSpline-like path.
        if hasattr(obj, "Points"):
            pts = list(obj.Points)
            if len(pts) < 2:
                raise ValueError("Object has fewer than two points.")
            obj.Points = list(reversed(pts))
            return
        # Draft Line-like fallback.
        if hasattr(obj, "Start") and hasattr(obj, "End"):
            start = FreeCAD.Vector(obj.Start)
            end = FreeCAD.Vector(obj.End)
            obj.Start = end
            obj.End = start
            return
        # Unsupported object type.
        raise TypeError(
            "Unsupported Draft object type: {}".format(
                getattr(obj, "TypeId", type(obj).__name__)
            )
        )


class CommandEditDuctDirections:
    """Enter temporary direction-edit mode for base duct routes."""

    def __init__(self):
        self.session = None
        self.task_panel = None

    def GetResources(self):
        return {
            "Pixmap": hvaclib.get_icon_path("ReverseDirection.svg"),
            "MenuText": QT_TRANSLATE_NOOP(
                "HVAC_EditDuctDirections",
                "Edit Directions",
            ),
            "ToolTip": QT_TRANSLATE_NOOP(
                "HVAC_EditDuctDirections",
                "Enter direction edit mode. Select base route elements to reverse their duct direction.",
            ),
            "CmdType": "ForEdit",
        }

    def IsActive(self):
        if Gui.ActiveDocument is None:
            return False

        net = hvaclib.activeHVACNetwork()
        if net is None:
            return False

        base = getattr(net, "Base", None)
        return bool(base and list(base.OutList))

    def Activated(self):
        from .Observer import DuctDirectionEditSession
        from .TaskPanel import TaskPanelDirectionEditMode

        net = hvaclib.activeHVACNetwork()
        if net is None:
            FreeCAD.Console.PrintWarning("HVAC - No active duct network.\n")
            return

        self.session = DuctDirectionEditSession(net)
        self.task_panel = TaskPanelDirectionEditMode(net, self.session)

        self.session.start()
        Gui.Control.showDialog(self.task_panel)
            

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

        # A DuctJunction has no type of its own -- retarget to its Primary
        # DuctComponent so picking a junction node in the tree still lets
        # you edit "its" fitting type directly.
        resolved = []
        for o in selected_geom:
            if hvaclib.isDuctJunction(o):
                primary = o.Proxy.getPrimaryComponent()
                if primary is not None:
                    resolved.append(primary)
                continue
            resolved.append(o)
        selected_geom = resolved
        if not selected_geom:
            return

        # Keep selection homogeneous for the first version
        has_segments = any(hvaclib.isDuctSegment(o) for o in selected_geom)
        has_components = any(hvaclib.isDuctComponent(o) for o in selected_geom)
        if has_segments and has_components:
            FreeCAD.Console.PrintWarning(
                "HVAC - Please select only segments or only junctions/components.\n"
            )
            return

        self.task_panel = TaskPanelTypeEditor(
            selected_geom,
            apply_callback=Network.DuctNetwork.applyTypeSelection,
        )
        Gui.Control.showDialog(self.task_panel)


class CommandEditMaterial:
    """
    Assign native FreeCAD materials to each of the selected duct
    segment(s)/component(s)' own construction layers, via one TaskPanel
    covering every layer present on the selection (see
    ui/TaskPanel.py:TaskPanelEditMaterial) -- FreeCAD's generic property
    editor has no interactive picker for Materials::PropertyMaterial on an
    arbitrary object (confirmed: no shipped FreeCAD workbench relies on
    inline editing for it either -- CAM's own "Assign Material" feature
    builds its own dialog the same way).
    """

    def __init__(self):
        self.task_panel = None

    def GetResources(self):
        return {
            'Pixmap': hvaclib.get_icon_path("EditMaterial.svg"),
            'MenuText': QT_TRANSLATE_NOOP('HVAC_EditMaterial', 'Edit Material'),
            'ToolTip': QT_TRANSLATE_NOOP(
                'HVAC_EditMaterial',
                'Assign native FreeCAD materials to each construction layer of the selected duct segment(s)/component(s)'
            ),
            'CmdType': 'ForEdit',
        }

    def IsActive(self):
        if Gui.ActiveDocument is None:
            return False
        return bool(self._resolveTargets())

    @staticmethod
    def _resolveTargets():
        # A DuctJunction has no material of its own -- retarget to its
        # Primary DuctComponent, same convention as CommandEditType.
        selected_geom = hvaclib.selectedGeometryObjects() or []
        targets = []
        for o in selected_geom:
            if hvaclib.isDuctJunction(o):
                primary = o.Proxy.getPrimaryComponent()
                if primary is not None:
                    targets.append(primary)
                continue
            if hvaclib.isDuctSegment(o) or hvaclib.isDuctComponent(o):
                targets.append(o)
        return targets

    def Activated(self):
        from ..ui.TaskPanel import TaskPanelEditMaterial

        targets = self._resolveTargets()
        if not targets:
            return

        self.task_panel = TaskPanelEditMaterial(
            targets,
            apply_callback=Network.DuctNetwork.applyMaterialSelection,
        )
        Gui.Control.showDialog(self.task_panel)


class CommandEditInlineComponents:
    """
    Manage a junction's Inline devices (dampers, silencers, ...) from one
    TaskPanel: list what's already there (selecting an entry highlights it
    in the 3D view), delete any of them, and add a new one to a chosen
    edge -- replaces the previous separate Add/Remove Inline Component
    commands (see ui/TaskPanel.py:TaskPanelEditInlineComponents).
    """

    @staticmethod
    def _eligibleJunction():
        # A DuctJunction has no Shape any more, so it can't be picked in the
        # 3D view -- a user naturally selects the fitting itself (its
        # Primary/Inline DuctComponent) instead. Accept either: a directly
        # selected junction, or a component, retargeted to its parent.
        selected_geom = hvaclib.selectedGeometryObjects() or []
        junction = None
        for o in selected_geom:
            if hvaclib.isDuctJunction(o):
                candidate = o
            elif hvaclib.isDuctComponent(o):
                parent_name = getattr(o, "ParentJunctionName", "")
                candidate = o.Document.getObject(parent_name) if parent_name else None
            else:
                continue
            if candidate is None:
                continue
            if junction is not None and junction is not candidate:
                return None  # selection implicates more than one junction
            junction = candidate

        if junction is None:
            return None
        if int(getattr(junction, "Degree", 0) or 0) < 1:
            return None
        return junction

    def __init__(self):
        self.task_panel = None

    def GetResources(self):
        return {
            'Pixmap': hvaclib.get_icon_path("EditInlineComponent.svg"),
            'MenuText': QT_TRANSLATE_NOOP('HVAC_EditInlineComponents', 'Edit Inline Components'),
            'ToolTip': QT_TRANSLATE_NOOP(
                'HVAC_EditInlineComponents',
                'View, add, or remove inline devices (dampers, silencers, ...) on a junction'
            ),
            'CmdType': 'ForEdit',
        }

    def IsActive(self):
        if Gui.ActiveDocument is None:
            return False
        return self._eligibleJunction() is not None

    def Activated(self):
        from ..ui.TaskPanel import TaskPanelEditInlineComponents

        junction = self._eligibleJunction()
        if junction is None:
            return

        self.task_panel = TaskPanelEditInlineComponents(
            junction,
            add_callback=Network.DuctNetwork.applyAddInlineComponent,
            remove_callback=Network.DuctNetwork.applyRemoveInlineComponent,
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


class CommandCalculateAirflow:
    """Solve airflow and pressure drop for the active network."""

    def __init__(self):
        self.task_panel = None

    def GetResources(self):
        return {
            'Pixmap': hvaclib.get_icon_path("CalculateAirflow.svg"),
            'MenuText': QT_TRANSLATE_NOOP('HVAC_CalculateAirflow', 'Calculate Airflow'),
            'ToolTip': QT_TRANSLATE_NOOP(
                'HVAC_CalculateAirflow',
                'Solve airflow and pressure drop for the active network'
            ),
            'CmdType': 'ForEdit',
        }

    def IsActive(self):
        if Gui.ActiveDocument is None:
            return False
        return hvaclib.activeHVACNetwork() is not None

    def Activated(self):
        from ..core.AirflowSolver import AirflowSolver
        from ..ui.TaskPanel import TaskPanelAirflowResults

        net = hvaclib.activeHVACNetwork()
        if net is None:
            return

        try:
            result = AirflowSolver(net).solve()
        except Exception as e:
            FreeCAD.Console.PrintWarning(
                "HVAC - CalculateAirflow - Error solving network '{}': {}\n".format(net.Label, e)
            )
            FreeCAD.Console.PrintMessage(traceback.format_exc())
            return

        net.Document.recompute()

        self.task_panel = TaskPanelAirflowResults(net, result)
        Gui.Control.showDialog(self.task_panel)


class CommandSizeDucts:
    """
    Compute proposed duct sizes for the active network (preview before
    applying). Opens one task panel covering both the network's own sizing
    parameters (SizingMethod/TargetVelocity/etc -- previously only
    reachable through the raw property editor) and the results/warnings of
    the last "Run Duct Sizing" click -- see
    ui/TaskPanel.py:TaskPanelSizeDucts.
    """

    def __init__(self):
        self.task_panel = None

    def GetResources(self):
        return {
            'Pixmap': hvaclib.get_icon_path("SizeDucts.svg"),
            'MenuText': QT_TRANSLATE_NOOP('HVAC_SizeDucts', 'Size Ducts'),
            'ToolTip': QT_TRANSLATE_NOOP(
                'HVAC_SizeDucts',
                'Compute proposed duct sizes for the active network from a target velocity or friction rate'
            ),
            'CmdType': 'ForEdit',
        }

    def IsActive(self):
        if Gui.ActiveDocument is None:
            return False
        return hvaclib.activeHVACNetwork() is not None

    def Activated(self):
        from ..ui.TaskPanel import TaskPanelSizeDucts

        net = hvaclib.activeHVACNetwork()
        if net is None:
            return

        self.task_panel = TaskPanelSizeDucts(net)
        Gui.Control.showDialog(self.task_panel)


class CommandRenumberNetwork:
    """Renumber the active/selected HVAC Duct Network's segments/junctions/components."""

    def GetResources(self):
        return {
            'Pixmap': hvaclib.get_icon_path("RenumberNetwork.svg"),
            'MenuText': QT_TRANSLATE_NOOP('HVAC_RenumberNetwork', 'Renumber Network'),
            'ToolTip': QT_TRANSLATE_NOOP(
                'HVAC_RenumberNetwork',
                'Assign documentation numbers (D.../J...) to the network\'s segments, '
                'junctions and components, walking outward from a source terminal'
            ),
            'CmdType': 'ForEdit',
        }

    def IsActive(self):
        if Gui.ActiveDocument is None:
            return False
        return bool(hvaclib.selectedHVACNetworks()) or hvaclib.activeHVACNetwork() is not None

    def Activated(self):
        from ..core.Numbering import renumber_network

        selected_hvac_networks = hvaclib.selectedHVACNetworks()
        net = selected_hvac_networks[0] if selected_hvac_networks else hvaclib.activeHVACNetwork()
        if net is None:
            return

        doc = net.Document
        doc.openTransaction("Renumber Network")
        try:
            result = renumber_network(net)
            doc.commitTransaction()
        except Exception:
            doc.abortTransaction()
            raise

        for warning in result.warnings:
            FreeCAD.Console.PrintWarning("HVAC - RenumberNetwork - {}\n".format(warning))

        FreeCAD.Console.PrintMessage(
            "HVAC - Renumbered {} segment(s), {} junction(s), {} component(s) in '{}'.\n".format(
                result.segment_count, result.junction_count, result.component_count, net.Label
            )
        )

        net.Document.recompute()


class CommandSelectAllSegments:
    """Select every duct segment in the active/selected HVAC Duct Network."""

    def GetResources(self):
        return {
            'Pixmap': hvaclib.get_icon_path("SelectSegments.svg"),
            'MenuText': QT_TRANSLATE_NOOP('HVAC_SelectAllSegments', 'Select All Segments'),
            'ToolTip': QT_TRANSLATE_NOOP(
                'HVAC_SelectAllSegments', 'Select every duct segment in the network'
            ),
            'CmdType': 'ForEdit',
        }

    def IsActive(self):
        if Gui.ActiveDocument is None:
            return False
        return bool(hvaclib.selectedHVACNetworks()) or hvaclib.activeHVACNetwork() is not None

    def Activated(self):
        selected_hvac_networks = hvaclib.selectedHVACNetworks()
        net = selected_hvac_networks[0] if selected_hvac_networks else hvaclib.activeHVACNetwork()
        if net is None:
            return
        net.Proxy.selectAllSegments()


class CommandSelectAllComponents:
    """Select every junction fitting (Primary and Inline) in the active/selected HVAC Duct Network."""

    def GetResources(self):
        return {
            'Pixmap': hvaclib.get_icon_path("SelectComponents.svg"),
            'MenuText': QT_TRANSLATE_NOOP('HVAC_SelectAllComponents', 'Select All Components'),
            'ToolTip': QT_TRANSLATE_NOOP(
                'HVAC_SelectAllComponents', 'Select every junction fitting (Primary and Inline) in the network'
            ),
            'CmdType': 'ForEdit',
        }

    def IsActive(self):
        if Gui.ActiveDocument is None:
            return False
        return bool(hvaclib.selectedHVACNetworks()) or hvaclib.activeHVACNetwork() is not None

    def Activated(self):
        selected_hvac_networks = hvaclib.selectedHVACNetworks()
        net = selected_hvac_networks[0] if selected_hvac_networks else hvaclib.activeHVACNetwork()
        if net is None:
            return
        net.Proxy.selectAllComponents()


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
        # Library code may have changed: rebuild every fitting (a normal sync only rebuilds what changed).
        for net in hvaclib.allHVACNetworks() or []:
            proxy = getattr(net, "Proxy", None)
            if proxy is not None:
                proxy.requestSync(rebuild_all=True)
        
        
def _is_hvac_object(obj):
    """A network object or base geometry: never a model to turn into equipment or a custom fitting."""
    checks = (
        hvaclib.isDuctNetwork,
        hvaclib.isDuctSegment,
        hvaclib.isDuctJunction,
        hvaclib.isDuctComponent,
        hvaclib.isDuctJunctionVirtual,
        hvaclib.isDuctManagedFolder,
        hvaclib.isSketch,
        hvaclib.isWire,
    )
    return any(check(obj) for check in checks)


def _has_solid(obj):
    shape = getattr(obj, "Shape", None)
    try:
        return shape is not None and not shape.isNull() and len(shape.Solids) > 0
    except Exception:
        return False


def _selected_part():
    """
    The model the selection points at: the first App::Part in the selection
    (picking a face or a body inside it counts too), else a selected solid
    (a Part cube, a PartDesign body, ...) that sits in no App::Part, which
    _container_for() wraps in a new App::Part on use. None when nothing
    usable is selected.
    """
    for sel in Gui.Selection.getSelectionEx("", 0) or []:
        obj = sel.Object
        if obj.TypeId == "App::Part":
            return obj
        parent = obj.getParentGeoFeatureGroup() if hasattr(obj, "getParentGeoFeatureGroup") else None
        if parent is not None and parent.TypeId == "App::Part":
            return parent
        if parent is None and not _is_hvac_object(obj) and _has_solid(obj):
            return obj
    return None


def _container_for(obj, name):
    """`obj` itself when it is an App::Part, else a new App::Part (named `name`) that `obj` is moved into."""
    if obj.TypeId == "App::Part":
        return obj
    part = obj.Document.addObject("App::Part", name)
    part.Label = obj.Label + " " + name
    part.addObject(obj)
    return part


class CommandCreateEquipment:
    """Make (or edit) HVAC equipment from a modelled unit, an App::Part (ROADMAP 6.5)."""

    def GetResources(self):
        return {
            'Pixmap': hvaclib.get_icon_path("CreateDuctsIcon.svg"),
            'MenuText': QT_TRANSLATE_NOOP('HVAC_CreateEquipment', 'Create / Edit Equipment'),
            'ToolTip': QT_TRANSLATE_NOOP(
                'HVAC_CreateEquipment',
                'Make the selected App::Part or solid (a modelled AHU, fan, ...) an HVAC equipment, or edit one: a panel '
                'lists its ports by kind (supply, return, outdoor air, exhaust) and adds new ones on a picked face '
                'at an X/Y offset from its centre. A duct drawn to end on a port is connected to it automatically',
            ),
            'CmdType': 'ForEdit',
        }

    def IsActive(self):
        return Gui.ActiveDocument is not None and _selected_part() is not None and not Gui.Control.activeDialog()

    def Activated(self):
        from ..core import Equipment
        from ..ui.TaskPanel import TaskPanelPortContainer

        selected = _selected_part()
        doc = selected.Document
        part = selected
        if selected.TypeId != "App::Part" or not Equipment.is_equipment(selected):
            doc.openTransaction("Create Equipment")
            try:
                part = _container_for(selected, "Equipment")
                Equipment.make_equipment(part)
            finally:
                doc.commitTransaction()
            FreeCAD.Console.PrintMessage("HVAC - '{}' is now HVAC equipment\n".format(part.Label))
        self.task_panel = TaskPanelPortContainer(part, kind="equipment")
        Gui.Control.showDialog(self.task_panel)


class CommandAddEquipment:
    """Add a library equipment model (air handling unit, fan, ...) as HVAC equipment."""

    def __init__(self):
        self.task_panel = None

    def GetResources(self):
        return {
            'Pixmap': hvaclib.get_icon_path("CreateDuctsIcon.svg"),
            'MenuText': QT_TRANSLATE_NOOP('HVAC_AddEquipment', 'Add Equipment from Library'),
            'ToolTip': QT_TRANSLATE_NOOP(
                'HVAC_AddEquipment',
                'Add a ready-made unit from the library (an air handling unit, a fan): pick the model, set its sizes '
                'and position. It comes with its ports and their snap points; a duct drawn to end on a port is '
                'connected to it automatically',
            ),
            'CmdType': 'ForEdit',
        }

    def IsActive(self):
        return FreeCAD.ActiveDocument is not None and not Gui.Control.activeDialog()

    def Activated(self):
        from ..core import Equipment
        from ..ui.TaskPanel import TaskPanelAddEquipment

        self.task_panel = TaskPanelAddEquipment(FreeCAD.ActiveDocument, Equipment.library_models())
        Gui.Control.showDialog(self.task_panel)


class CommandCreateCustomFitting:
    """Make (or edit) a custom fitting from a modelled App::Part (ROADMAP 6.3)."""

    def GetResources(self):
        return {
            'Pixmap': hvaclib.get_icon_path("EditPlacement.svg"),
            'MenuText': QT_TRANSLATE_NOOP('HVAC_CreateCustomFitting', 'Create / Edit Custom Fitting'),
            'ToolTip': QT_TRANSLATE_NOOP(
                'HVAC_CreateCustomFitting',
                'Use the selected App::Part or solid (a modelled fitting) as a custom junction fitting: a panel lists its '
                'ports and adds new ones on a picked face at an X/Y offset from its centre. Ducts drawn to end on '
                'its ports become one junction that uses the fitting where it is modelled',
            ),
            'CmdType': 'ForEdit',
        }

    def IsActive(self):
        from ..core import Equipment

        part = _selected_part()
        return (
            Gui.ActiveDocument is not None
            and part is not None
            and not Equipment.is_equipment(part)
            and not Gui.Control.activeDialog()
        )

    def Activated(self):
        from ..core import _custom_fitting
        from ..ui.TaskPanel import TaskPanelPortContainer

        selected = _selected_part()
        doc = selected.Document
        part = selected
        # Mark the part, so ducts drawn to its ports attach to it (a bare solid is first put in an App::Part).
        if selected.TypeId != "App::Part" or not _custom_fitting.is_custom_fitting(selected):
            doc.openTransaction("Create Custom Fitting")
            try:
                part = _container_for(selected, "CustomFitting")
                _custom_fitting.make_custom_fitting(part)
            finally:
                doc.commitTransaction()
            FreeCAD.Console.PrintMessage("HVAC - '{}' is now an HVAC custom fitting\n".format(part.Label))
        self.task_panel = TaskPanelPortContainer(part, kind="fitting")
        Gui.Control.showDialog(self.task_panel)


class CommandConnectEquipment:
    """Connect an equipment port marker to a network terminal (ROADMAP 6.5)."""

    def GetResources(self):
        return {
            'Pixmap': hvaclib.get_icon_path("ModifyDuctsIcon.svg"),
            'MenuText': QT_TRANSLATE_NOOP('HVAC_ConnectEquipment', 'Connect to Equipment'),
            'ToolTip': QT_TRANSLATE_NOOP(
                'HVAC_ConnectEquipment',
                'Select an equipment port marker and a duct end (its terminal node or fitting): the duct end '
                'becomes its network\'s source, fed by (or feeding) that port',
            ),
            'CmdType': 'ForEdit',
        }

    @staticmethod
    def _pieces():
        from ..core import Equipment, _custom_fitting

        marker = junction = None
        for obj in Gui.Selection.getSelection() or []:
            if _custom_fitting.is_port(obj) or obj.TypeId == "Part::LocalCoordinateSystem":
                marker = obj
            elif hvaclib.isDuctJunction(obj):
                junction = obj
            elif hvaclib.isDuctComponent(obj):
                parent = obj.Document.getObject(getattr(obj, "ParentJunctionName", "") or "")
                junction = parent or junction
        equipment = Equipment.equipment_of_marker(marker) if marker is not None else None
        return equipment, marker, junction

    def IsActive(self):
        if Gui.ActiveDocument is None:
            return False
        _equipment, marker, junction = self._pieces()
        return marker is not None and junction is not None

    def Activated(self):
        from ..core import Equipment

        equipment, marker, junction = self._pieces()
        if equipment is None:
            FreeCAD.Console.PrintWarning(
                "HVAC - Connect to Equipment: '{}' belongs to no equipment; use Create / Edit Equipment on its "
                "App::Part first\n".format(marker.Label)
            )
            return
        doc = junction.Document
        doc.openTransaction("Connect to Equipment")
        try:
            warnings = Equipment.connect(equipment, marker, junction)
        except ValueError as e:
            doc.abortTransaction()
            FreeCAD.Console.PrintWarning("HVAC - Connect to Equipment: {}\n".format(e))
            return
        doc.commitTransaction()
        for warning in warnings:
            FreeCAD.Console.PrintWarning("HVAC - Connect to Equipment: {}\n".format(warning))
        FreeCAD.Console.PrintMessage(
            "HVAC - Connected '{}' to {} port '{}'\n".format(junction.Label, equipment.Label, marker.Label)
        )


class CommandLayerVisibility:
    """
    Layer visibility of the active network (Stage 9): the network's
    ShowLayer_<Role> / ShowFeatures switches (display only, applied at once,
    no recompute). Run from the menu, the context menu or the Tasks pane it
    opens the Layer Visibility panel; its toolbar button is a drop-down with
    the same switches (populate_layer_visibility_menu, attached by the
    workbench through Toolbar.attach_dropdown).
    """

    def __init__(self):
        self.task_panel = None

    def GetResources(self):
        return {
            'Pixmap': hvaclib.get_icon_path("EditMaterial.svg"),
            'MenuText': QT_TRANSLATE_NOOP('HVAC_LayerVisibility', 'Layer Visibility'),
            'ToolTip': QT_TRANSLATE_NOOP(
                'HVAC_LayerVisibility',
                'Show or hide construction layers (by role) and construction features of the active network. '
                'Display only, applied at once',
            ),
            'CmdType': 'ForEdit',
        }

    def IsActive(self):
        net = hvaclib.activeHVACNetwork()
        return net is not None and net.Document == FreeCAD.ActiveDocument

    def Activated(self):
        from ..ui.TaskPanel import TaskPanelLayerVisibility

        net = hvaclib.activeHVACNetwork()
        if net is None:
            return
        self.task_panel = TaskPanelLayerVisibility(net)
        Gui.Control.showDialog(self.task_panel)


def populate_layer_visibility_menu(menu):
    """
    Fill the Layer Visibility toolbar drop-down for the active network: one
    checkbox per switch, then "Show All". Checkboxes inside the menu
    (QWidgetAction) keep it open, so several layers can be switched in one go.
    """
    from ..ui.TaskPanel import layer_visibility_entries, set_layer_visibility

    net = hvaclib.activeHVACNetwork()
    entries = layer_visibility_entries(net) if net is not None else []
    if not entries:
        menu.addAction(translate("HVAC_LayerVisibility", "No active network")).setEnabled(False)
        return
    checks = []
    for prop_name, label in entries:
        check = QtWidgets.QCheckBox(label)
        check.setChecked(bool(getattr(net, prop_name, True)))
        check.toggled.connect(lambda checked, prop_name=prop_name: set_layer_visibility(net, prop_name, checked))
        holder = QtWidgets.QWidget()
        row = QtWidgets.QHBoxLayout(holder)
        row.setContentsMargins(8, 3, 8, 3)
        row.addWidget(check)
        action = QtWidgets.QWidgetAction(menu)
        action.setDefaultWidget(holder)
        menu.addAction(action)
        checks.append(check)
    menu.addSeparator()
    show_all = menu.addAction(translate("HVAC_LayerVisibility", "Show All"))
    show_all.triggered.connect(lambda: [check.setChecked(True) for check in checks])


#=================================================
# Register Commands
#=================================================

if FreeCAD.GuiUp:
    FreeCAD.Gui.addCommand('HVAC_CreateDuctNetwork', CommandCreateDuctNetwork())
    FreeCAD.Gui.addCommand('HVAC_ModifyDuctNetwork', CommandModifyDuctNetwork())
    FreeCAD.Gui.addCommand('HVAC_EditBaseObject', CommandEditBaseObject())
    FreeCAD.Gui.addCommand('HVAC_ReverseGeometryDirection', CommandReverseGeometryDirection())
    FreeCAD.Gui.addCommand("HVAC_EditDuctDirections", CommandEditDuctDirections())
    FreeCAD.Gui.addCommand('HVAC_CreateVirtualJunction', CommandCreateVirtualJunction())
    FreeCAD.Gui.addCommand('HVAC_DeleteDuctNetwork', CommandDeleteDuctNetwork())
    FreeCAD.Gui.addCommand('HVAC_ActivateDuctNetwork', CommandActivateDuctNetwork())
    FreeCAD.Gui.addCommand("HVAC_CreateSketch", CommandCreateSketch())
    FreeCAD.Gui.addCommand("HVAC_CreateLine", CommandCreateLine())
    FreeCAD.Gui.addCommand("HVAC_CreateSpline", CommandCreateSpline())
    FreeCAD.Gui.addCommand('HVAC_EditType', CommandEditType())
    FreeCAD.Gui.addCommand('HVAC_EditMaterial', CommandEditMaterial())
    FreeCAD.Gui.addCommand('HVAC_EditInlineComponents', CommandEditInlineComponents())
    FreeCAD.Gui.addCommand('HVAC_EditPlacement', CommandEditPlacement())
    FreeCAD.Gui.addCommand('HVAC_EditNetworkTypeDefaults', CommandEditNetworkTypeDefaults())
    FreeCAD.Gui.addCommand('HVAC_CalculateAirflow', CommandCalculateAirflow())
    FreeCAD.Gui.addCommand('HVAC_SizeDucts', CommandSizeDucts())
    FreeCAD.Gui.addCommand('HVAC_ResetTypesToDefaults', CommandResetTypesToNetworkDefaults())
    FreeCAD.Gui.addCommand('HVAC_RenumberNetwork', CommandRenumberNetwork())
    FreeCAD.Gui.addCommand('HVAC_SelectAllSegments', CommandSelectAllSegments())
    FreeCAD.Gui.addCommand('HVAC_SelectAllComponents', CommandSelectAllComponents())
    FreeCAD.Gui.addCommand('HVAC_CreateEquipment', CommandCreateEquipment())
    FreeCAD.Gui.addCommand('HVAC_AddEquipment', CommandAddEquipment())
    FreeCAD.Gui.addCommand('HVAC_LayerVisibility', CommandLayerVisibility())
    FreeCAD.Gui.addCommand('HVAC_CreateCustomFitting', CommandCreateCustomFitting())
    FreeCAD.Gui.addCommand('HVAC_ConnectEquipment', CommandConnectEquipment())
    FreeCAD.Gui.addCommand('HVAC_ReloadLibraries', CommandReloadHVACLibraries())  # Debug method
