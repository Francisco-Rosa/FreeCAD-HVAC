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

import os
import platform
import sys
import traceback
import math

import FreeCAD, Part
import FreeCADGui as Gui
from PySide import QtGui, QtCore
translate = FreeCAD.Qt.translate
preferences = FreeCAD.ParamGet("User parameter:BaseApp/Preferences/Mod/HVAC")

from .Library import HVACLibraryRegistry

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
# Library management
#------------------------------------------------------------------------------

class HVACLibraryService:

    _registry: HVACLibraryRegistry = HVACLibraryRegistry()

    @classmethod
    def _get_registry(cls) -> HVACLibraryRegistry:
        if not getattr(cls._registry, "_search_paths", None):
            cls._registry.set_search_paths(get_default_library_search_paths())
        cls._registry.ensure_loaded()
        return cls._registry

    @classmethod
    def get_hvac_library_registry(cls) -> HVACLibraryRegistry:
        return cls._get_registry()

    @classmethod
    def get_active_hvac_library(cls):
        return cls._get_registry().get_active_library()

    @classmethod
    def reload_hvac_libraries(cls) -> HVACLibraryRegistry:
        cls._get_registry().reload()
        return cls._registry

    @classmethod
    def segment_profiles_for_library(cls, library_id: str) -> list:
        lib = cls._get_registry().get_library(library_id)
        if lib is None:
            return []
        return lib.list_profiles(category="segment", family="straight_segment")

    @classmethod
    def default_segment_profile_for_library(cls, library_id: str) -> str:
        lib = cls._get_registry().get_library(library_id)
        if lib is None:
            return ""
        return lib.default_profile(category="segment", family="straight_segment")

    @classmethod
    def default_segment_type_id_for_profile(cls, library_id: str, profile: str) -> str:
        lib = cls._get_registry().get_library(library_id)
        if lib is None:
            return ""

        type_defs = lib.list_types(
            category="segment",
            family="straight_segment",
            profile=profile if profile else None,
        )
        if not type_defs:
            return ""
        return type_defs[0].id

    @staticmethod
    def classify_junction_family(node_analysis: dict) -> str:
        degree = int(node_analysis.get("degree", 0))
        collinear_pairs = node_analysis.get("collinear_pairs", [])
        orthogonal_pairs = node_analysis.get("orthogonal_pairs", [])

        if degree <= 0:
            return "invalid"

        if degree == 1:
            return "terminal"

        if degree == 2:
            if collinear_pairs:
                return "transition"
            return "elbow"

        if degree == 3:
            if collinear_pairs:
                return "tee"
            return "wye"

        if degree == 4:
            if len(collinear_pairs) >= 2 and orthogonal_pairs:
                return "cross"
            return "manifold"

        return "manifold"

    @staticmethod
    def default_junction_type_id(family: str) -> str:
        mapping = {
            "terminal": "terminal_marker",
            "transition": "transition_generic",
            "elbow": "elbow_generic",
            "tee": "tee_generic",
            "wye": "wye_generic",
            "cross": "cross_generic",
            "manifold": "manifold_generic",
        }
        return mapping.get(family, "manifold_marker")

    @classmethod
    def all_junction_type_defs(cls, library_id: str | None = None, family: str | None = None) -> list:
        reg = cls._get_registry()
        lib = reg.get_library(library_id) if library_id else reg.get_active_library()
        if lib is None:
            return []
        return lib.list_types(category="junction", family=family)

    @classmethod
    def all_type_defs_for_object(cls, obj) -> list:
        reg = cls._get_registry()
        library_id = getattr(obj, "LibraryId", "")
        family = getattr(obj, "Family", "")
        profile = getattr(obj, "Profile", "")

        lib = reg.get_library(library_id) if library_id else reg.get_active_library()
        if lib is None:
            return []

        if isDuctSegment(obj):
            return lib.list_types(category="segment")

        if isDuctJunction(obj):
            return lib.list_types(
                category="junction",
                family=family or None,
                profile=profile or None,
            )

        return []

    @classmethod
    def type_labels_for_object(cls, obj) -> list:
        out = []
        for tdef in cls.all_type_defs_for_object(obj):
            out.append((tdef.label, tdef.id))
        return out

    @classmethod
    def debug_print_loaded_libraries(cls) -> None:
        libs = cls._get_registry().list_libraries()
        if not libs:
            FreeCAD.Console.PrintWarning("HVAC - No libraries loaded.\n")
            return

        for lib in libs:
            FreeCAD.Console.PrintMessage(
                "HVAC - Library loaded: {} ({}) with {} types\n".format(
                    lib.label, lib.id, len(lib.types_by_id)
                )
            )


#------------------------------------------------------------------------------
# State management
#------------------------------------------------------------------------------

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
        except Exception as e:
            FreeCAD.Console.PrintError(traceback.format_exc())
            FreeCAD.Console.PrintWarning("HVAC - refreshState: {}".format(e))
    
    QtCore.QTimer.singleShot(0, _do_refresh)
    
    
#------------------------------------------------------------------------------
# Object query
#------------------------------------------------------------------------------

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
    from .DuctNetwork import DuctSegment, DuctJunction
    objs = Gui.Selection.getSelection()
    if objs:
        filtered = [
            o for o in objs
            if DuctSegment.isDuctSegment(o) or DuctJunction.isDuctJunction(o)
        ]
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
    
def isDuctNetwork(obj):
    from .DuctNetwork import DuctNetwork
    return hasattr(obj, "Proxy") and isinstance(obj.Proxy, DuctNetwork)
    
def isDuctSegment(obj):
    from .DuctNetwork import DuctSegment
    return hasattr(obj, "Proxy") and isinstance(obj.Proxy, DuctSegment)
    
def isDuctJunction(obj):
    from .DuctNetwork import DuctJunction
    return hasattr(obj, "Proxy") and isinstance(obj.Proxy, DuctJunction)
    
def isDuctManagedFolder(obj):
    from .DuctNetwork import DuctManagedFolder
    return hasattr(obj, "Proxy") and isinstance(obj.Proxy, DuctManagedFolder)

def isSketch(obj):
    # Robust check for Sketcher objects
    try:
        return hasattr(obj, "TypeId") and (
            obj.TypeId.startswith("Sketcher::SketchObject")
            or obj.TypeId.startswith("Sketcher::SketchObjectPython")
        )
    except:
        return None

def isWire(obj):
    # Draft Wire is usually Part::Feature (or FeaturePython) with Draft properties
    try:
        return (
            obj.TypeId == "Part::FeaturePython"
            and hasattr(obj, "Proxy")
            and hasattr(obj.Proxy, "Type")
            and getattr(obj.Proxy, "Type") in ["Wire", "BSpline", "Circle", "BezCurve"]
        )
    except:
        return None
        
def SketchGeomType(obj):
    try:
        if hasattr(obj, "TypeId"):
            geomtype = getattr(obj, "TypeId")
            if geomtype in ['Part::GeomLineSegment', 'Part::GeomLine', 'Part::GeomBSplineCurve', 
                'Part::GeomCircle', 'Part::GeomArcOfCircle']:
                return geomtype
            else:
                return "Unknown"
    except:
        return None
        
def EdgeType(obj):
    try:
        if obj.TypeId == "Part::FeaturePython" \
        and hasattr(obj, "Proxy") \
        and hasattr(obj.Proxy, "Type"):
            edgetype = getattr(obj.Proxy, "Type")
            if edgetype in ["Wire", "BSpline", "Circle", "BezCurve"]:
                return edgetype
            else:
                return "Unknown"
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
    
def makeLineKey(obj_name, source_index):
    """Make a unique line key from an object name and source index."""
    source_index = int(source_index)
    obj = FreeCAD.ActiveDocument.getObject(obj_name)
    if (obj and len(getattr(obj, "Geometry", [])) > source_index and \
                hasattr(obj.Geometry[source_index], "Tag") and 
                obj.Geometry[source_index].Tag):
        if isSketch(obj):
            return obj.Geometry[source_index].Tag
        elif isWire(obj):
            return "{}_{}".format(getattr(obj, "Name", ""), 
                                getattr(obj.Geometry[source_index], "Tag", ""))
    return '{}_{}'.format(obj_name, source_index)


#------------------------------------------------------------------------------
# Object data manipulation
#------------------------------------------------------------------------------

def vec_quant(p):
    """
    Collapse points by tolerance using quantization.
    Points within ~tol map to the same key.
    """
    t = 1e-6
    return (
        int(round(p[0] / t)),
        int(round(p[1] / t)),
        int(round(p[2] / t)),
    )

def vec_to_xyz(v):
    """Return (x,y,z) tuple from a FreeCAD.Vector-like object."""
    return (float(v.x), float(v.y), float(v.z))

# Attachment offset with duct direction along Z axis +ve direction
# Viewed from start of duct, X axis -> To Left, Y axis -> To Top
ATTACH_MAP = {
    "TopLeft": (1, 1), "TopCenter": (0, 1), "TopRight": (-1, 1),
    "CenterLeft": (1, 0), "Center": (0, 0), "CenterRight": (-1, 0),
    "BottomLeft": (1, -1), "BottomCenter": (0, -1), "BottomRight": (-1, -1),
}

def get_segment_section_params(seg):
    """
    Return generic section parameters for a segment.
    This is profile-dependent.
    """
    profile = str(getattr(seg, "Profile", "") or "")

    if profile == "Circular":
        return {
            "Diameter": float(getattr(seg, "Diameter", 0.0) or 0.0),
        }
    if profile == "Rectangular":
        return {
            "Width": float(getattr(seg, "Width", 0.0) or 0.0),
            "Height": float(getattr(seg, "Height", 0.0) or 0.0),
        }
    if profile == "Oval":
        return {
            "Width": float(getattr(seg, "Width", 0.0) or 0.0),
            "Height": float(getattr(seg, "Height", 0.0) or 0.0),
        }
    # Generic fallback for future profiles
    out = {}
    for name in ("Diameter", "Width", "Height"):
        if hasattr(seg, name):
            try:
                out[name] = float(getattr(seg, name) or 0.0)
            except Exception:
                pass
    return out
    
def get_section_extents(section_params):
    # rectangular
    if "Width" in section_params and "Height" in section_params:
        return float(section_params["Width"]), float(section_params["Height"])
    # circular (use diameter as box)
    if "Diameter" in section_params:
        d = float(section_params["Diameter"])
        return d, d
    # fallback
    return 0.0, 0.0
    
def curve_kind(curve):
    """
    Returns type of curve
    """
    # Case 1: Draft object
    if getattr(curve, "Proxy", "") and hasattr(curve.Proxy, "Type"):
        return EdgeType(curve)
        
    # Case 2: Part object/ Sketch object
    elif getattr(curve, "TypeID", ""):
        return SketchGeomType(curve)
        
    return "Unknown"
    
def parse_edge_info(edge):
    """
    Parse edge information into a dictionary.
    """
    if edge is None:
        return None
        
    v1 = FreeCAD.Vector(edge.Vertexes[0].Point)
    v2 = FreeCAD.Vector(edge.Vertexes[-1].Point)
    fp = float(edge.FirstParameter)
    lp = float(edge.LastParameter)

    try:
        d1 = edge.tangentAt(fp)
    except Exception:
        d1 = v2 - v1
    try:
        d2 = edge.tangentAt(lp)
    except Exception:
        d2 = v2 - v1

    d1.normalize()
    d2.normalize()

    return {
        "path_kind": curve_kind(edge),
        "edge": edge,
        "start_point": v1,
        "end_point": v2,
        "start_direction": d1,
        "end_direction": d2,
        "length": float(edge.Length),
    }
    
def make_profile_frame(direction, preferred_x=None, origin=None):
    """
    Build a right-handed frame with:
      z_dir = normalized(direction)
      x_dir = preferred cross-section X axis projected onto the normal plane
      y_dir = z_dir cross x_dir

    preferred_x:
      - None or zero-length => automatic stable frame
      - otherwise projected to plane normal to z_dir
    """
    z_dir = FreeCAD.Vector(direction)
    if z_dir.Length <= 1e-12:
        raise ValueError("Direction vector too small")
    z_dir.normalize()

    x_dir = None
    if preferred_x is not None:
        px = FreeCAD.Vector(preferred_x)
        if px.Length > 1e-12:
            # Remove tangent component so X stays in section plane
            px = px - z_dir * px.dot(z_dir)
            if px.Length > 1e-12:
                px.normalize()
                x_dir = px
    
    if x_dir is None:
        ref = FreeCAD.Vector(0, 0, 1)
        if abs(z_dir.dot(ref)) > 0.99:
            ref = FreeCAD.Vector(1, 0, 0)
        x_dir = ref.cross(z_dir)
        if x_dir.Length <= 1e-12:
            raise ValueError("Failed to compute X axis")
        x_dir.normalize()

    y_dir = z_dir.cross(x_dir)
    if y_dir.Length <= 1e-12:
        raise ValueError("Failed to compute Y axis")
    y_dir.normalize()

    # Re-orthogonalize X for numerical cleanliness
    x_dir = y_dir.cross(z_dir)
    x_dir.normalize()

    mat = FreeCAD.Matrix()
    mat.A11, mat.A12, mat.A13 = x_dir.x, y_dir.x, z_dir.x
    mat.A21, mat.A22, mat.A23 = x_dir.y, y_dir.y, z_dir.y
    mat.A31, mat.A32, mat.A33 = x_dir.z, y_dir.z, z_dir.z

    placement = FreeCAD.Placement(mat)
    if origin is not None:
        placement.Base = origin

    return placement, x_dir, y_dir, z_dir

def compute_port_position(base_point, direction, section_params, attachment, user_offset_vec, profile_x_axis):
    ax, ay = ATTACH_MAP.get(str(attachment or "Center"), (0, 0))
    W, H = get_section_extents(section_params)
    _, local_x, local_y, local_z = make_profile_frame(direction, preferred_x=profile_x_axis)
    attach_offset = (-ax * W * 0.5) * local_x + (-ay * H * 0.5) * local_y
    return base_point + attach_offset + user_offset_vec
      
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
    
def get_default_library_search_paths():
    return [
        get_file_path("libraries"),
    ]


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
