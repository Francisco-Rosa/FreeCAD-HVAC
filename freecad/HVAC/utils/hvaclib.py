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

import json
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

from ..library.Library import HVACLibraryRegistry, HVACTypeMatchRequest

# Enable loading external libraries from the ext_libs directory
path = os.path.dirname(__file__)
vendor_path = os.path.join(path, "..", "ext_libs")
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

    # ------------------------------------------------------------------
    # Registry-driven type selection (see freecad/HVAC/library/Library.py:
    # HVACLibraryRegistry.select_type / matches_type / resolve_sticky_type).
    #
    # select_*        -- fresh automatic selection (used for explicit
    #                     "reset to network defaults").
    # resolve_*        -- sticky: retains a current, still-compatible,
    #                     non-placeholder selection; otherwise selects.
    # matches_*        -- compatibility check only, no selection.
    # ------------------------------------------------------------------

    @staticmethod
    def _segment_request(
        profile: str, curved: bool, context: dict | None = None, flex: bool = False
    ) -> HVACTypeMatchRequest:
        family = "curved_segment" if curved else "straight_segment"
        if flex:
            family += ".flex"
        ctx = dict(context or {})
        ctx.setdefault("profile", profile or "")
        return HVACTypeMatchRequest(
            category="segment", topology="generic", family=family, profile=profile or "", context=ctx
        )

    @staticmethod
    def _junction_request(
        topology: str, family_key: str, profile: str, connected_ports=None, context: dict | None = None
    ) -> HVACTypeMatchRequest:
        ctx = dict(context or {})
        ctx.setdefault("connected_ports", list(connected_ports or []))
        ctx.setdefault("topology", topology or "")
        return HVACTypeMatchRequest(
            category="junction", topology=topology or "", family=family_key or "", profile=profile or "", context=ctx
        )

    @staticmethod
    def _is_real_model(selection) -> bool:
        """Whether a selection found a type that is not a placeholder."""
        type_def = getattr(selection, "type_def", None)
        return type_def is not None and getattr(type_def.selection, "kind", "") != "placeholder"

    @classmethod
    def select_segment_type(
        cls, library_id: str, profile: str, curved: bool = False, context: dict | None = None, flex: bool = False
    ):
        """
        Fresh automatic segment-type selection (non-sticky).

        `flex` (a curved route drawn as a spline, see BaseCurveIsSpline) asks
        for a flexible duct first ("curved_segment.flex") and falls back to
        the plain curved type when the library has none for this profile.
        """
        if flex and curved:
            selection = cls._get_registry().select_type(library_id, cls._segment_request(profile, curved, context, True))
            if cls._is_real_model(selection):
                return selection
        request = cls._segment_request(profile, curved, context)
        return cls._get_registry().select_type(library_id, request)

    @classmethod
    def resolve_segment_type(
        cls,
        library_id: str,
        current_type_id: str,
        profile: str,
        curved: bool = False,
        context: dict | None = None,
        flex: bool = False,
    ):
        """
        Sticky segment-type resolution used by normal network sync. With
        `flex`, see select_segment_type(); a type the user chose stays either
        way (a flexible and a plain curved duct are compatible with both requests).
        """
        if flex and curved:
            selection = cls._get_registry().resolve_sticky_type(
                library_id, current_type_id, cls._segment_request(profile, curved, context, True)
            )
            if cls._is_real_model(selection):
                return selection
        request = cls._segment_request(profile, curved, context)
        return cls._get_registry().resolve_sticky_type(library_id, current_type_id, request)

    @classmethod
    def select_junction_type(
        cls, library_id: str, topology: str, family_key: str, profile: str, connected_ports=None, context: dict | None = None
    ):
        """Fresh automatic junction-type selection (non-sticky)."""
        request = cls._junction_request(topology, family_key, profile, connected_ports, context)
        return cls._get_registry().select_type(library_id, request)

    @classmethod
    def resolve_junction_type(
        cls,
        library_id: str,
        current_type_id: str,
        topology: str,
        family_key: str,
        profile: str,
        connected_ports=None,
        context: dict | None = None,
    ):
        """Sticky junction-type resolution used by normal network sync."""
        request = cls._junction_request(topology, family_key, profile, connected_ports, context)
        return cls._get_registry().resolve_sticky_type(library_id, current_type_id, request)

    @classmethod
    def default_segment_type_id(cls, library_id: str, profile: str, curved: bool = False) -> str:
        """
        Deprecated compatibility wrapper: prefer select_segment_type(), which
        returns full HVACTypeSelection diagnostics instead of a bare id.
        """
        selection = cls.select_segment_type(library_id, profile, curved=curved)
        return selection.type_def.id if selection.type_def else ""

    @classmethod
    def match_profile_from_ports(cls, connected_ports) -> str:
        """
        Derive a junction match profile from its connected ports'
        (already-known) duct profiles:
            all ports share one known profile -> that profile
            multiple distinct known profiles  -> "Mixed"
            no known profiles                 -> "" (unknown)
        """
        profiles = set()
        for port in connected_ports or []:
            profile = str((port.get("profile", "") if isinstance(port, dict) else getattr(port, "profile", "")) or "")
            if profile:
                profiles.add(profile)

        if not profiles:
            return ""
        if len(profiles) == 1:
            return next(iter(profiles))
        return "Mixed"

    @classmethod
    def all_junction_type_defs(cls, library_id: str | None = None, family: str | None = None) -> list:
        reg = cls._get_registry()
        lib = reg.get_library(library_id) if library_id else reg.get_active_library()
        if lib is None:
            return []
        return lib.list_types(category="junction", family=family)

    @classmethod
    def list_inline_types(cls, library_id: str | None = None, topology: str | None = None, profile: str | None = None) -> list:
        """selection.kind=="inline" junction types, for the Add Inline Component UI."""
        reg = cls._get_registry()
        lib = reg.get_library(library_id) if library_id else reg.get_active_library()
        if lib is None:
            return []
        return lib.list_inline_types(topology=topology, profile=profile)

    @classmethod
    def all_type_defs_for_object(cls, obj) -> list:
        reg = cls._get_registry()
        library_id = getattr(obj, "LibraryId", "")

        lib = reg.get_library(library_id) if library_id else reg.get_active_library()
        if lib is None:
            return []

        if isDuctSegment(obj):
            return lib.list_types(category="segment")

        if isDuctComponent(obj):
            # Topology is a junction-level concept -- read it off the
            # parent. A component's own Profile can collapse several
            # distinct connected-port profiles into a single "Mixed" label
            # (see match_profile_from_ports), which can never correctly
            # filter a type by plain membership (no type declares a
            # literal "Mixed" profile) -- pass the parent's own
            # connected_ports instead, so list_types() checks each port's
            # real profile individually, the same way select_type() does.
            parent_name = getattr(obj, "ParentJunctionName", "")
            parent = obj.Document.getObject(parent_name) if parent_name else None
            topology = getattr(parent, "Topology", "") if parent is not None else ""
            connected_ports = None
            if parent is not None:
                try:
                    analysis = json.loads(getattr(parent, "AnalysisJson", "") or "{}")
                except Exception:
                    analysis = {}
                connected_ports = list(analysis.get("connected_ports", []) or [])
            return lib.list_types(
                category="junction",
                topology=topology or None,
                connected_ports=connected_ports,
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
    from ..core.Network import DuctNetwork
    doc = FreeCAD.ActiveDocument if doc is None else doc
    if doc is None:
        return None
    hvac_networks = []
    if hasattr(doc, "Objects"):
        hvac_networks = [
            n for n in doc.Objects 
            if isDuctNetwork(n)
        ]
    return hvac_networks

def selectedHVACNetworks():
    from ..core.Network import DuctNetwork
    objs = Gui.Selection.getSelection()
    if objs:
        filtered = [o for o in objs if isDuctNetwork(o)]
        return filtered
    return None

def selectedGeometryObjects():
    from ..core.Network import DuctSegment, DuctJunction
    objs = Gui.Selection.getSelection()
    if objs:
        filtered = [
            o for o in objs
            if isDuctSegment(o) or isDuctJunction(o) or isDuctComponent(o)
        ]
        return filtered
    return None
    
def selectedBaseObjects():
    from ..core.Network import DuctNetwork
    objs = Gui.Selection.getSelection()
    if objs:
        filtered = [o for o in objs if DuctNetwork.isBaseObject(o)]
        return filtered
    return None
    
def getOwnerNetwork(obj):
    from ..core.Network import DuctNetwork
    return DuctNetwork.getOwnerNetwork(obj)
    
def isDuctNetwork(obj):
    from ..core.Network import DuctNetwork
    return bool(obj) and hasattr(obj, "Proxy") and isinstance(obj.Proxy, DuctNetwork)
    
def isDuctSegment(obj):
    from ..core.Segment import DuctSegment
    return bool(obj) and hasattr(obj, "Proxy") and isinstance(obj.Proxy, DuctSegment)
    
def isDuctJunction(obj):
    from ..core.Junction import DuctJunction
    return bool(obj) and hasattr(obj, "Proxy") and isinstance(obj.Proxy, DuctJunction)

def isDuctComponent(obj):
    from ..core.Component import DuctComponent
    return bool(obj) and hasattr(obj, "Proxy") and isinstance(obj.Proxy, DuctComponent)

def isDuctJunctionVirtual(obj):
    from ..core.Junction import DuctJunctionVirtual
    return bool(obj) and hasattr(obj, "Proxy") and isinstance(obj.Proxy, DuctJunctionVirtual)
    
def isDuctManagedFolder(obj):
    from ..core.Network import DuctManagedFolder
    return bool(obj) and hasattr(obj, "Proxy") and isinstance(obj.Proxy, DuctManagedFolder)

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
        
def GeomType(obj):
    try:
        if hasattr(obj, "TypeId"):
            geomtype = getattr(obj, "TypeId")
            if geomtype in ['Part::GeomLineSegment', 'Part::GeomLine', 
                'Part::GeomBSplineCurve', 'Part::GeomBezierCurve',
                'Part::GeomCircle', 'Part::GeomArcOfCircle']:
                return geomtype
            else:
                return "Unknown"
    except:
        return None
        
def CurveKind(curve):
    """
    Returns type of curve
    """
    if curve:
        kind = GeomType(curve)
    else:
        kind = "Unknown"
        
    if kind in ['Part::GeomLineSegment', 'Part::GeomLine']:
        return "straight"
    elif kind in ['Part::GeomBSplineCurve', 'Part::GeomBezierCurve', 
                  'Part::GeomCircle', 'Part::GeomArcOfCircle']:
        return "curved"
        
    return "Unknown"
        
def EdgeKind(edge):
    """
    Returns type of curve
    """
    if edge and hasattr(edge, 'Curve'):
        kind = CurveKind(edge.Curve)
    else:
        kind = "Unknown"
    return kind

def BaseCurveKind(base_obj_name, local_index):
    """
    Returns base type of curve
    """
    base_obj = get_obj_by_name(base_obj_name)
    # Case 1: Sketch object
    if base_obj and isSketch(base_obj):
        if len(base_obj.Geometry) > local_index:
            return CurveKind(base_obj.Geometry[local_index])
    elif base_obj and isWire(base_obj):
        if len(base_obj.Shape.Edges) > local_index:
            return EdgeKind(base_obj.Shape.Edges[local_index])
    return "Unknown"

def BaseCurveIsSpline(base_obj_name, local_index):
    """
    Whether a base edge is a spline (B-spline or Bezier): what the "New
    Curved" tool draws. Such a route defaults to a flexible duct; an arc
    stays a plain curved duct.
    """
    base_obj = get_obj_by_name(base_obj_name)
    curve = None
    if base_obj and isSketch(base_obj):
        if len(base_obj.Geometry) > local_index:
            curve = base_obj.Geometry[local_index]
    elif base_obj and isWire(base_obj):
        if len(base_obj.Shape.Edges) > local_index:
            curve = getattr(base_obj.Shape.Edges[local_index], "Curve", None)
    return bool(curve) and GeomType(curve) in ("Part::GeomBSplineCurve", "Part::GeomBezierCurve")


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
    """
    The stable key of one base-geometry edge, the same before and after a
    save and reload (ROADMAP 6.4 a):

    - a sketch edge: "<sketch Name>:g<geometry id>". The sketch's own
      geometry id is saved with the document and stays with its geometry
      when other geometry is deleted and the indices shift; new geometry
      gets a new id. (A geometry Tag would not do: tags are regenerated on
      every reload.)
    - any other edge (a Draft wire, a Part shape): "<object Name>:e<index>".
      Its points are saved, so the index only changes when the shape does.
    """
    source_index = int(source_index)
    obj = FreeCAD.ActiveDocument.getObject(obj_name) if FreeCAD.ActiveDocument else None
    if obj is not None and isSketch(obj) and hasattr(obj, "getGeometryId"):
        try:
            return "{}:g{}".format(obj_name, int(obj.getGeometryId(source_index)))
        except Exception:
            pass
    return "{}:e{}".format(obj_name, source_index)


#------------------------------------------------------------------------------
# Object data manipulation
#------------------------------------------------------------------------------

def label_matches(current, wanted):
    """
    True when an object's Label already is `wanted`, allowing for the digits
    FreeCAD appends to keep labels unique ("Tee [Primary]" -> "Tee [Primary]015").
    """
    current, wanted = str(current), str(wanted)
    return current == wanted or (current.startswith(wanted) and current[len(wanted) :].isdigit())


def set_label(obj, wanted):
    """
    Give `obj` the label `wanted` unless it has it already (see
    label_matches); returns True when it was written. A sync must not write
    a label it already has: FreeCAD renames duplicates, so a plain
    comparison never holds, and every write marks the object for recompute.
    """
    if label_matches(obj.Label, wanted):
        return False
    obj.Label = wanted
    return True


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
    
def vec(v):
    if v is None:
        return None
    if hasattr(v, "x") and hasattr(v, "y") and hasattr(v, "z"):
        return FreeCAD.Vector(v)
    if isinstance(v, (list, tuple)) and len(v) == 3:
        return FreeCAD.Vector(float(v[0]), float(v[1]), float(v[2]))
    return None

def vec_to_xyz(v):
    """Return (x,y,z) tuple from a FreeCAD.Vector-like object."""
    return (float(v.x), float(v.y), float(v.z))
    
def vec_in_list(p, p_list):
    """Return True if points are within tolerance."""
    t = 1e-6
    for p2 in p_list:
        if all(abs(p[i] - p2[i]) < t for i in range(3)):
            return True
    return False

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

def profile_area(profile, section_params):
    """
    Return a duct cross-section's area from its profile-dependent section
    parameters, or None when the profile/parameters aren't known well
    enough to compute one (e.g. a "Generic"/custom profile) -- used by
    NetworkParser to derive flow_class/derived_values from base-segment
    geometry, never from the hydraulic solver.
    """
    profile = str(profile or "")
    params = section_params or {}

    if profile == "Circular":
        d = float(params.get("Diameter", 0.0) or 0.0)
        if d <= 0.0:
            return None
        return math.pi / 4.0 * d * d

    if profile in ("Rectangular", "Oval"):
        w = float(params.get("Width", 0.0) or 0.0)
        h = float(params.get("Height", 0.0) or 0.0)
        if w <= 0.0 or h <= 0.0:
            return None
        if profile == "Rectangular":
            return w * h
        # Oval "stadium" section: a rectangle capped by two semicircles,
        # using the shorter side as the semicircle diameter.
        major, minor = (w, h) if w >= h else (h, w)
        return (major - minor) * minor + math.pi / 4.0 * minor * minor

    return None


def _circular_profile_signature(params):
    return (round(float(params.get("Diameter", 0.0) or 0.0), 6),)


def _rect_oval_profile_signature(params):
    return (
        round(float(params.get("Width", 0.0) or 0.0), 6),
        round(float(params.get("Height", 0.0) or 0.0), 6),
    )


def _generic_profile_signature(params):
    # No fixed Width/Height/Diameter schema assumed -- every numeric
    # section parameter, sorted by name so the result is deterministic.
    return tuple(
        (k, round(float(v), 6))
        for k, v in sorted((params or {}).items())
        if isinstance(v, (int, float)) and not isinstance(v, bool)
    )


# Profile name -> builder(params) -> tuple of canonical, tolerance-rounded
# dimensions. A future custom-profile implementation registers its own
# entry here instead of falling into the generic (sorted numeric params)
# fallback -- see profile_signature().
PROFILE_SIGNATURE_BUILDERS = {
    "Circular": _circular_profile_signature,
    "Rectangular": _rect_oval_profile_signature,
    "Oval": _rect_oval_profile_signature,
}


def profile_signature(profile, section_params):
    """
    Return a canonical, comparable signature for a duct cross-section --
    used to decide whether two ports share "the same section" (e.g.
    NetworkParser's through.straight/offset vs. through.transition split)
    without relying on area equality alone, since two differently-shaped
    sections can share an area. Always starts with the profile name, so
    two ports of different profiles never compare equal regardless of
    numeric coincidence.
    """
    profile = str(profile or "")
    params = dict(section_params or {})
    builder = PROFILE_SIGNATURE_BUILDERS.get(profile, _generic_profile_signature)
    return (profile,) + tuple(builder(params))


def translated_port_position(junction_obj, port):
    """
    A connected_ports entry's own "position" is the raw, pre-fitting
    shared anchor point every port on a junction shares before any
    geometry backend independently pushes its own port outward (see
    core/Junction.py's composeComponents() docstring). junction_obj's own
    ConnectionLengthsJson (kept current every sync by composeComponents()/
    aggregateConnectionLengths()) holds each real edge's current total
    push-out length, so this translates the port that far along its own
    direction to get where it actually, physically ends -- used wherever
    a port needs to be drawn/highlighted at its real location rather than
    the shared anchor (e.g. TaskPanelEditInlineComponents' port highlight,
    TerminalFlowRateObserver's outlet plane).

    Returns a copy of port with "position" replaced; the input is never
    mutated. Falls back to returning an unchanged copy if position/
    direction can't be resolved.
    """
    edge_key = port.get("edge_key", "")
    try:
        lengths = json.loads(getattr(junction_obj, "ConnectionLengthsJson", "") or "[]")
    except Exception:
        lengths = []
    length = 0.0
    for item in lengths:
        if item.get("edge_key") == edge_key:
            length = float(item.get("length", 0.0) or 0.0)
            break

    position = vec(port.get("position"))
    direction = vec(port.get("direction"))
    if position is None or direction is None:
        return dict(port)

    translated = dict(port)
    translated["position"] = vec_to_xyz(position + direction * length)
    return translated


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
        "path_kind": EdgeKind(edge),
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
    s_path = os.path.join(s_path, "..")
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

def get_materials_base_path():
    """
    Path to this addon's shipped native FreeCAD material cards (.FCMat) --
    see utils/materials.py. Resolved (no "..") before being registered as a
    Material subsystem ModuleDir, since that value is echoed back verbatim
    in a few places (e.g. Materials.Material.LibraryRoot) and an unresolved
    path is needlessly harder to read there.
    """
    return os.path.realpath(get_file_path(os.path.join("Resources", "Materials")))


def get_material_models_base_path():
    """Path to the native FreeCAD material models shipped by this addon."""
    return os.path.realpath(get_file_path(os.path.join("Resources", "Models")))


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
