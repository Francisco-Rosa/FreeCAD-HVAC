# -*- coding: utf-8 -*-
#***************************************************************************
#*                                                                         *
#*   Copyright (c) 2026 Francisco Rosa                                     *
#*                                                                         *
#*   Portions of code based on kbwbe's A2Plus Workbench                    *
#*                                                                         *
#*   This program is free software; you can redistribute it and/or modify  *
#*   it under the terms of the GNU Lesser General Public License (LGPL)    *
#*   as published by the Free Software Foundation; either version 2 of     *
#*   the License, or (at your option) any later version.                   *
#*   for detail see the LICENCE text file.                                 *
#*                                                                         *
#*   This program is distributed in the hope that it will be useful,       *
#*   but WITHOUT ANY WARRANTY; without even the implied warranty of        *
#*   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the         *
#*   GNU Library General Public License for more details.                  *
#*                                                                         *
#*   You should have received a copy of the GNU Library General Public     *
#*   License along with this program; if not, write to the Free Software   *
#*   Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  *
#*   USA                                                                   *
#*                                                                         *
#***************************************************************************

import os, platform, sys
from dataclasses import dataclass
import FreeCAD
import FreeCADGui as Gui
import Part
from PySide import QtGui, QtCore
translate = FreeCAD.Qt.translate
preferences = FreeCAD.ParamGet("User parameter:BaseApp/Preferences/Mod/HVAC")

# Enable loading external libraries from the ext_libs directory
path = os.path.dirname(__file__)
vendor_path = os.path.join(path, "ext_libs")
# Add to sys.path if not already there
if vendor_path not in sys.path:
    sys.path.append(vendor_path)

# Load external libraries
import networkx as nx


#------------------------------------------------------------------------------
# Variables...
#------------------------------------------------------------------------------


WORKBENCH_NAME = 'HVAC'
WORKBENCH_STATE = 'DEFAULT'
DUCT_NETWORK_CONTEXT_KEY = "hvac_ductnetwork"
OBSERVER_TIMER_POLL_INTERVAL = 100

DUCT_SECTION_SHAPES = ["Rectangular", "Circular"]

#------------------------------------------------------------------------------
# Detect the operating system...
#------------------------------------------------------------------------------

tmp = platform.system()
tmp = tmp.upper()
tmp = tmp.split(' ')

OPERATING_SYSTEM = 'UNKNOWN'
if "WINDOWS" in tmp:
    OPERATING_SYSTEM = "WINDOWS"
elif "LINUX" in tmp:
    OPERATING_SYSTEM = "LINUX"
else:
    OPERATING_SYSTEM = "OTHER"


#------------------------------------------------------------------------------
# State management
#------------------------------------------------------------------------------


def isDuctNetwork(obj):
    from .DuctNetwork import DuctNetwork
    return hasattr(obj, "Proxy") and isinstance(obj.Proxy, DuctNetwork)
    
def isDuctSegment(obj):
    from .DuctNetwork import DuctSegment
    return hasattr(obj, "Proxy") and isinstance(obj.Proxy, DuctSegment)
    
def isDuctManagedFolder(obj):
    from .DuctNetwork import DuctManagedFolder
    return hasattr(obj, "Proxy") and isinstance(obj.Proxy, DuctManagedFolder)

def activeHVACNetwork():
    doc = Gui.ActiveDocument

    if doc is None or doc.ActiveView is None:
        return None
    active_network = doc.ActiveView.getActiveObject(DUCT_NETWORK_CONTEXT_KEY)

    if active_network:
        return active_network

def allHVACNetworks(doc: FreeCAD.Document | None = None) -> list | None:
    from .DuctNetwork import DuctNetwork
    doc = FreeCAD.ActiveDocument if doc is None else doc
    if doc is None:
        return None
    hvac_networks = []
    if hasattr(doc, "Objects"):
        hvac_networks = [
            n for n in doc.Objects 
            if DuctNetwork.isDuctNetwork(n)
        ]
    return hvac_networks

def selectedHVACNetworks():
    from .DuctNetwork import DuctNetwork
    objs = Gui.Selection.getSelection()
    if objs:
        filtered = [o for o in objs if DuctNetwork.isDuctNetwork(o)]
        return filtered
    return None

def selectedGeometryObjects():
    from freecad.HVAC.DuctNetwork import DuctSegment
    objs = Gui.Selection.getSelection()
    if objs:
        filtered = [o for o in objs if DuctSegment.isDuctSegment(o)]
        return filtered
    return None
    
def selectedBaseObjects():
    from .DuctNetwork import DuctNetwork
    objs = Gui.Selection.getSelection()
    if objs:
        filtered = [o for o in objs if DuctNetwork.isBaseObject(o)]
        return filtered
    return None
    
def getOwnerNetwork(obj):
    from .DuctNetwork import DuctNetwork
    return DuctNetwork.getOwnerNetwork(obj)

def refreshState():
    if not FreeCAD.GuiUp:
        return
    
    # Recompute document
    doc = FreeCAD.ActiveDocument
    if doc:
        FreeCAD.ActiveDocument.recompute()
    
    # Refresh TaskWatchers
    def _do_refresh():
        """Refresh HVAC task watchers after commands that change watcher conditions"""
        try:
            wb = Gui.activeWorkbench()
            if wb and hasattr(wb, "refreshWatchers"):
                wb.refreshWatchers()
        except Exception:
            pass
    
    QtCore.QTimer.singleShot(0, _do_refresh)
    

#------------------------------------------------------------------------------
# Object query
#------------------------------------------------------------------------------


def obj_is_sketch(obj):
    # Robust check for Sketcher objects
    try:
        return hasattr(obj, "TypeId") and (
            obj.TypeId.startswith("Sketcher::SketchObject")
            or obj.TypeId.startswith("Sketcher::SketchObjectPython")
        )
    except:
        return None

def obj_is_wire(obj):
    # Draft Wire is usually Part::Feature (or FeaturePython) with Draft properties
    try:
        return (
            obj.TypeId == "Part::FeaturePython"
            and hasattr(obj, "Proxy")
            and hasattr(obj.Proxy, "Type")
            and getattr(obj.Proxy, "Type") == "Wire"
        )
    except:
        return None

def get_obj_name(obj):
    # Get object name from FreeCAD object
    return getattr(obj, "Name", "")

def get_obj_by_name(name, doc=None):
    # Get object by name from FreeCAD document
    if doc is None:
        doc = FreeCAD.ActiveDocument
    obj = doc.getObject(name)
    return obj


#------------------------------------------------------------------------------
# Object data manipulation
#------------------------------------------------------------------------------


def vec_to_xyz(v):
    """Return (x,y,z) tuple from a FreeCAD.Vector-like object."""
    return (float(v.x), float(v.y), float(v.z))

@dataclass(frozen=True)
class EdgeRef:
    """Stable reference to an edge created from (obj_name, local_line_index)."""
    obj_name: str
    local_index: int
    tag: str

class DuctNetworkParser:

    def __init__(self, objs=None):

        # Input line storage
        self.lines_map = {}   # Obj_Name -> [(sp, ep, tag), ...]
        self.all_lines = []   # [(sp, ep, tag), ...]

        # Graph storage (generated)
        self.tol = 1e-6
        self.node_id_by_key = {}
        self.node_point = {}      # node_id -> representative point
        self.edge_u_v = {}        # edge_ref -> (u, v)
        self.edge_geom = {}       # edge_ref -> (sp, ep)
        self.obj_edges = {}       # obj_name -> [edge_ref,...]

        # Optional networkx graph (recommended)
        self.graph = None

        # Build data structures
        if objs:
            self.compile_lines_from_objects(objs)
        self.build_graph()

    ## Data Parser Methods

    def compile_lines_from_objects(self, objs):
        self.lines_map = {}
        self.all_lines = []
        for obj in objs:
            if obj_is_wire(obj):
                for sp, ep, tag in self.iter_line_segments_from_shape(obj):
                    self.parse_obj(obj, sp, ep, tag)
            elif obj_is_sketch(obj):
                for sp, ep, tag in self.iter_line_segments_from_sketch(obj):
                    self.parse_obj(obj, sp, ep, tag)
        return self.lines_map, self.all_lines

    def parse_obj(self, obj, sp, ep, tag):
        obj_name = getattr(obj, "Name", None)
        if obj_name:
            if obj_name not in self.lines_map:
                self.lines_map[obj_name] = []
            self.lines_map[obj_name].append((sp, ep, tag))
            self.all_lines.append((sp, ep, tag))

    def iter_line_segments_from_sketch(self, sketch_obj, tol=1e-9):
        """
        Yield (start_point, end_point) for all LINE segments in a Sketch.
        Sketch line geo is typically Part.LineSegment.
        """
        for geo in getattr(sketch_obj, "Geometry", []) or []:
            # Accept only straight line segments
            if hasattr(geo, "StartPoint") and hasattr(geo, "EndPoint"):
                # Filter out arcs/circles/etc by type
                # Part.LineSegment usually has TypeId or is instance of Part.LineSegment
                typeid = getattr(geo, "TypeId", "")
                if "Line" in typeid or (typeid == "" and geo.__class__.__name__ in ("LineSegment", "Line")):
                    sp = geo.StartPoint
                    ep = geo.EndPoint
                    # Skip degenerate lines
                    if (sp.sub(ep)).Length > tol:
                        yield (vec_to_xyz(sp), vec_to_xyz(ep), getattr(geo, "Tag", ""))

    def iter_line_segments_from_shape(self, obj, tol=1e-9):
        """
        Yield (start_point, end_point) for all straight edges in obj.Shape.
        Works for Draft Wire (and many Part-based objects) as long as Shape exists.
        """
        shape = getattr(obj, "Shape", None)
        if shape is None:
            return
        for e in getattr(shape, "Edges", []) or []:
            c = getattr(e, "Curve", None)
            if c is None:
                continue
            typeid = getattr(c, "TypeId", "")
            # Straight edges typically have Part::GeomLine / GeomLine
            if "GeomLine" in typeid or c.__class__.__name__ in ("GeomLine",):
                v1 = e.Vertexes[0].Point
                v2 = e.Vertexes[-1].Point
                if (v1.sub(v2)).Length > tol:
                    tag = "{}_{}".format(getattr(obj, "Name", ""), getattr(e, "Tag", ""))
                    yield (vec_to_xyz(v1), vec_to_xyz(v2), tag)

    ## Graph build utilities

    def _key(self, p):
        """
        Collapse points by tolerance using quantization.
        Points within ~tol map to the same key.
        """
        t = float(self.tol)
        return (
            int(round(p[0] / t)),
            int(round(p[1] / t)),
            int(round(p[2] / t)),
        )

    def _get_node_id(self, p):
        k = self._key(p)
        nid = self.node_id_by_key.get(k)
        if nid is None:
            nid = len(self.node_id_by_key) + 1  # start node ids from 1
            self.node_id_by_key[k] = nid
            self.node_point[nid] = p
        return nid

    def build_graph(self, tol=1e-6):
        """
        Build a graph where:
            - nodes = junction points (collapsed by tol)
            - edges = duct centerlines (your lines)
        """
        self.tol = float(tol)

        # reset generated structures
        self.node_id_by_key.clear()
        self.node_point.clear()
        self.edge_u_v.clear()
        self.edge_geom.clear()
        self.obj_edges.clear()

        G = nx.Graph()

        for obj_name, lines in self.lines_map.items():
            for i, (sp, ep, tag) in enumerate(lines):
                u = self._get_node_id(sp)
                v = self._get_node_id(ep)

                eref = EdgeRef(obj_name=obj_name, local_index=i, tag=tag)
                self.edge_u_v[eref] = (u, v)
                self.edge_geom[eref] = (sp, ep)
                self.obj_edges.setdefault(obj_name, []).append(eref)

                # Similar pattern to referenced build_graph_model(): add_edge with attributes.
                G.add_edge(
                    u, v,
                    key=eref,
                    obj=obj_name,
                    local_index=i,
                    sp=sp, ep=ep,
                )

        self.graph = G
        return G

    ## Convenience queries
    def node_count(self):
        return len(self.node_point)

    def edge_count(self):
        return len(self.edge_u_v)

    def nodes(self):
        return sorted(self.node_point.keys())

    def node_xyz(self, node_id):
        return self.node_point[node_id]

    def edges(self):
        return list(self.edge_u_v.keys())

    def edges_of_obj(self, obj_name):
        return list(self.obj_edges.get(obj_name, []))

    def edge_nodes(self, eref):
        return self.edge_u_v[eref]

    def edge_line(self, eref):
        return self.edge_geom[eref]

    def connected_components(self):
        """Return connected components as lists of node_ids."""
        if self.graph is None:
            raise RuntimeError("Graph not built. Call build_graph() first.")
        return [sorted(list(c)) for c in nx.connected_components(self.graph)]

    def shortest_path_by_points(self, p1, p2):
        """
        Path between two geometric points (snapped by tol).
        Returns node_id path.
        """
        if self.graph is None:
            raise RuntimeError("Graph not built. Call build_graph() first.")

        n1 = self.node_id_by_key[self._key(p1)]
        n2 = self.node_id_by_key[self._key(p2)]
        return nx.shortest_path(self.graph, n1, n2)


#------------------------------------------------------------------------------
# Geometry generation functions
#------------------------------------------------------------------------------


def create_rectangular_duct_geom(start_point, end_point, width, height):
    """
    Create a cuboid centered on the line between two points.

    start_point, end_point : (x,y,z)
    width  : cross-section width
    height : cross-section height

    Returns:
        Part.Shape
    """

    p1 = FreeCAD.Vector(*start_point)
    p2 = FreeCAD.Vector(*end_point)

    direction = p2 - p1
    length = direction.Length

    if length == 0:
        raise ValueError("Start and end points cannot be identical")

    direction_unit = FreeCAD.Vector(direction)
    direction_unit.normalize()

    # Create box with length along X and cross-section in YZ
    # Box origin is at (0,0,0) and spans X:[0,length], Y:[0,width], Z:[0,height]
    shape = Part.makeBox(length, width, height)

    # We want the duct centerline to lie along the box X axis at Y=0, Z=0.
    # Therefore shift the box in its local coordinates by (0, -width/2, -height/2)
    # Then apply rotation that aligns X to the direction vector and translate to p1.
    rotation = FreeCAD.Rotation(FreeCAD.Vector(1, 0, 0), direction_unit)

    local_shift = FreeCAD.Vector(0.0, -width / 2.0, -height / 2.0)
    world_shift = rotation.multVec(local_shift)
    placement_origin = p1.add(world_shift)
    placement = FreeCAD.Placement(placement_origin, rotation)

    shape_mod = shape.copy()
    shape_mod.transformShape(placement.toMatrix(), True, False)

    return shape_mod


def create_circular_duct_geom(start_point, end_point, diameter):
    """
    Create a cylindrical duct centered on the line between two points.

    start_point, end_point : (x,y,z)
    diameter : cross-section diameter

    Returns:
        Part.Shape
    """

    p1 = FreeCAD.Vector(*start_point)
    p2 = FreeCAD.Vector(*end_point)

    direction = p2 - p1
    length = direction.Length

    if length == 0:
        raise ValueError("Start and end points cannot be identical")

    direction_unit = FreeCAD.Vector(direction)
    direction_unit.normalize()

    # Convert diameter to radius for cylinder creation
    radius = float(diameter) / 2.0

    # Create cylinder with axis along Z of height = length
    cyl = Part.makeCylinder(radius, length)

    # Align cylinder Z-axis to direction vector
    rotation = FreeCAD.Rotation(FreeCAD.Vector(0, 0, 1), direction_unit)

    # Place base center at start point
    placement = FreeCAD.Placement(p1, rotation)

    cyl_mod = cyl.copy()
    cyl_mod.transformShape(placement.toMatrix(), True, False)

    return cyl_mod


#------------------------------------------------------------------------------
# Return paths...
#------------------------------------------------------------------------------


def get_module_path():
    """Function returns HVAC module path."""
    s_path = os.path.dirname(os.path.abspath(__file__))
    return s_path

def get_file_path(file_name):
    """Function returns HVAC module path."""
    s_path = os.path.join(get_module_path(), file_name)
    return s_path

def get_language_base_path():
    """Function return path for localization files."""
    s_path = os.path.join(get_module_path(), "translations")
    return s_path

def get_icon_base_path():
    """Function return path for icon files."""
    s_path = os.path.join(get_module_path(), "icons")
    return s_path

def get_icon_path(icon_name: str):
    """Function returns path for icon file."""
    s_path = os.path.join(get_icon_base_path(), icon_name)
    return s_path


#------------------------------------------------------------------------------
# Miscellaneous
#------------------------------------------------------------------------------


def get_version():
    """
    Function return A2Plus version for storing in assembly file
    """

    hvac_path = get_module_path()
    try:
        metadata = FreeCAD.Metadata(os.path.join(hvac_path, 'package.xml'))
        return metadata.Version
    except:
        tx = ' ?? '
        return tx
