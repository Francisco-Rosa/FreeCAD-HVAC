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
import FreeCAD, Part
import FreeCADGui as Gui
from PySide import QtWidgets, QtCore
from PySide.QtCore import QT_TRANSLATE_NOOP
translate = FreeCAD.Qt.translate

from ..utils import hvaclib


class DuctSegment:
    """Derived per-edge duct segment created from network base geometry."""

    TYPE = "DuctSegment"

    def __init__(self, obj, owner=None, key="", source_obj=None, source_index=0):
        obj.Proxy = self
        self.Object = obj
        self._allow_delete = False
        self.setProperties(obj)
        self.applyOwnerDefaults(obj, owner)
        self.updateMetadata(
            owner=owner,
            key=key,
            source_obj=source_obj,
            source_index=source_index,
        )

    def onDocumentRestored(self, obj):
        obj.Proxy = self
        self.Object = obj
        self._allow_delete = False
        self.setProperties(obj)

    def dumps(self):
        return None

    def loads(self, state):
        pass

    def execute(self, obj):
        edge = self.resolveSourceEdge()

        start_point = getattr(obj, "EffectiveStartPoint", None) or getattr(obj, "StartPoint", None)
        end_point = getattr(obj, "EffectiveEndPoint", None) or getattr(obj, "EndPoint", None)
        if start_point is None or end_point is None:
            return
    
        try:
            if (start_point - end_point).Length <= 0:
                return

            library_id = getattr(obj, "LibraryId", "")
            type_id = getattr(obj, "TypeId", "")
            if not library_id or not type_id:
                return
    
            reg = hvaclib.HVACLibraryService.get_hvac_library_registry()
            type_def = reg.resolve_type(library_id, type_id)
            if type_def is None:
                raise ValueError(
                    "Unknown segment type '{}' in library '{}'".format(type_id, library_id)
                )
    
            props = {}
            for pdef in getattr(type_def, "properties", []) or []:
                if hasattr(obj, pdef.name):
                    props[pdef.name] = getattr(obj, pdef.name)
                else:
                    props[pdef.name] = getattr(pdef, "default", None)
                    
            profile = getattr(obj, "Profile", "")
            attachment = getattr(obj, "Attachment", "Center")
            user_offset = getattr(obj, "Offset", FreeCAD.Vector(0, 0, 0))
            profile_x_axis = getattr(obj, "ProfileXAxis", None)
        
            path_edge = None
            path_kind = "Unknown"
            start_dir = getattr(obj, "StartDirection", None)
            end_dir = getattr(obj, "EndDirection", None)
        
            if edge is not None:
                routed_edge, rsp, rep, rsd, red = self.makeTrimmedShiftedEdge(
                    edge=edge,
                    trim_start=getattr(obj, "TrimStart", 0.0),
                    trim_end=getattr(obj, "TrimEnd", 0.0),
                    profile=profile,
                    section_params=props,
                    attachment=attachment,
                    user_offset=user_offset,
                    profile_x_axis=profile_x_axis,
                )
        
                if routed_edge is not None:
                    path_edge = routed_edge
                    path_kind = hvaclib.EdgeKind(routed_edge)
                    start_point = rsp
                    end_point = rep
                    start_dir = rsd
                    end_dir = red
                else:
                    path_kind = hvaclib.EdgeKind(edge)
    
            context = {
                "obj": obj,
                "start_point": start_point,
                "end_point": end_point,
                "properties": props,
                "family": getattr(obj, "Family", ""),
                "profile": getattr(obj, "Profile", ""),
                "profile_x_axis": getattr(obj, "ProfileXAxis", None),
                "type_id": type_id,
                "library_id": library_id,
                "segment_key": getattr(obj, "SegmentKey", ""),
                "source_object_name": getattr(obj, "SourceObjectName", ""),
                "source_index": int(getattr(obj, "SourceIndex", 0)),
                "path_kind": path_kind,
                "path_edge": path_edge,
                "start_direction": start_dir,
                "end_direction": end_dir,
            }
    
            result = reg.call_generator(library_id, type_def, context)
            shape = result.get("shape", None)
            if shape is not None:
                obj.Shape = shape
    
            # Optional trim plane overrides from generator
            if "start_trim_plane_json" in result:
                obj.StartTrimPlaneJson = result["start_trim_plane_json"] or ""
            if "end_trim_plane_json" in result:
                obj.EndTrimPlaneJson = result["end_trim_plane_json"] or ""
    
        except Exception as e:
            FreeCAD.Console.PrintWarning(
                "HVAC - DuctSegment - Execute - Error generating segment '{}': {}\n".format(obj.Label, e)
            )
            FreeCAD.Console.PrintMessage(traceback.format_exc())

    def setProperties(self, obj):
        self._addProperty(obj, "App::PropertyString", "OwnerNetworkName", "HVAC", "Owning duct network")
        self._addProperty(obj, "App::PropertyString", "SegmentKey", "HVAC", "Runtime segment key")
        self._addProperty(obj, "App::PropertyString", "SourceObjectName", "HVAC", "Internal source object name")
        self._addProperty(obj, "App::PropertyInteger", "SourceIndex", "HVAC", "Zero-based line segment index in the source object")
        self._addProperty(obj, "App::PropertyInteger", "StartNode", "HVAC", "Graph start node id")
        self._addProperty(obj, "App::PropertyInteger", "EndNode", "HVAC", "Graph end node id")
        self._addProperty(obj, "App::PropertyVector", "StartPoint", "HVAC", "Segment start point")
        self._addProperty(obj, "App::PropertyVector", "EndPoint", "HVAC", "Segment end point")
        self._addProperty(obj, "App::PropertyLength", "CenterlineLength", "HVAC", "Computed centerline length")
        
        self._addProperty(obj, "App::PropertyLength", "TrimStart", "HVAC", "Trim length at start node")
        self._addProperty(obj, "App::PropertyLength", "TrimEnd", "HVAC", "Trim length at end node")
        self._addProperty(obj, "App::PropertyVector", "EffectiveStartPoint", "HVAC", "Trimmed segment start point")
        self._addProperty(obj, "App::PropertyVector", "EffectiveEndPoint", "HVAC", "Trimmed segment end point")
        self._addProperty(obj, "App::PropertyLength", "EffectiveLength", "HVAC", "Trimmed centerline length")
        self._addProperty(obj, "App::PropertyVector", "StartDirection", "HVAC", "Unit tangent direction at start")
        self._addProperty(obj, "App::PropertyVector", "EndDirection", "HVAC", "Unit tangent direction at end")
        self._addProperty(obj, "App::PropertyString", "PathKind", "HVAC", "Resolved source path kind")
        self._addProperty(obj, "App::PropertyString", "StartTrimPlaneJson", "HVAC", "Optional generator trim plane at start")
        self._addProperty(obj, "App::PropertyString", "EndTrimPlaneJson", "HVAC", "Optional generator trim plane at end")

        self._addProperty(obj, "App::PropertyString", "LibraryId", "HVAC", "HVAC library id")
        self._addProperty(obj, "App::PropertyString", "Family", "HVAC", "Segment family")
        self._addProperty(obj, "App::PropertyString", "TypeId", "HVAC", "Selected segment type id")
        self._addProperty(obj, "App::PropertyString", "Profile", "HVAC", "Segment profile")
        self._addProperty(obj, "App::PropertyString", "AnalysisJson", "HVAC", "Serialized segment analysis")
        
        self._addProperty(obj, "App::PropertyEnumeration", "Attachment", "Placement", "Section attachment relative to route")
        self._addProperty(obj, "App::PropertyVector", "Offset", "Placement", "Global user offset")
        self._addProperty(obj, "App::PropertyVector", "ProfileXAxis", "Placement", "Preferred local X axis for section/profile orientation; zero vector = auto")

        # Keep these as generic dimensional parameters. The active type schema
        # decides whether they are used.
        self._addProperty(obj, "App::PropertyLength", "Diameter", "Dimensions", "Circular duct diameter")
        self._addProperty(obj, "App::PropertyLength", "Width", "Dimensions", "Rectangular duct width")
        self._addProperty(obj, "App::PropertyLength", "Height", "Dimensions", "Rectangular duct height")
        self._addProperty(obj, "App::PropertyLength", "InsulationThickness", "Parameters", "Insulation thickness")
        self._addProperty(obj, "App::PropertyLength", "Roughness", "Parameters", "Wall roughness")
        self._addProperty(obj, "App::PropertyFloat", "FlowRate", "Parameters", "Design flow rate")
        self._addProperty(obj, "App::PropertyFloat", "Velocity", "Parameters", "Design air velocity")

        for prop in (
            "TrimStart",
            "TrimEnd",
            "EffectiveStartPoint",
            "EffectiveEndPoint",
            "EffectiveLength",
        ):
            try:
                obj.setEditorMode(prop, 1)
            except Exception:
                pass
                
        if not obj.TrimStart:
            obj.TrimStart = 0.0
        if not obj.TrimEnd:
            obj.TrimEnd = 0.0

        if not getattr(obj, "LibraryId", ""):
            lib = hvaclib.HVACLibraryService.get_active_hvac_library()
            if lib:
                obj.LibraryId = lib.id

        if not getattr(obj, "AnalysisJson", ""):
            obj.AnalysisJson = "{}"

        for prop in (
            "OwnerNetworkName",
            "SegmentKey",
            "SourceObjectName",
            "SourceIndex",
            "StartNode",
            "EndNode",
            "StartPoint",
            "EndPoint",
            "CenterlineLength",
            "Family",
            "Profile",
            "AnalysisJson",
        ):
            try:
                obj.setEditorMode(prop, 1)
            except Exception:
                pass
                
    def applyOwnerDefaults(self, obj, owner):
        if owner is None:
            return
    
        try:
            obj.Attachment = list(hvaclib.ATTACH_MAP.keys())
            obj.Attachment = str(getattr(owner, "DefaultAttachment", "Center"))
        except Exception:
            obj.Attachment = list(hvaclib.ATTACH_MAP.keys())
            obj.Attachment = "Center"
    
        try:
            obj.Offset = FreeCAD.Vector(getattr(owner, "DefaultOffset", FreeCAD.Vector(0, 0, 0)))
        except Exception:
            obj.Offset = FreeCAD.Vector(0, 0, 0)
    
        if not getattr(obj, "Diameter", 0):
            obj.Diameter = float(getattr(owner, "DefaultDiameter", 100.0))
    
        if not getattr(obj, "Width", 0):
            obj.Width = float(getattr(owner, "DefaultWidth", 100.0))
    
        if not getattr(obj, "Height", 0):
            obj.Height = float(getattr(owner, "DefaultHeight", 100.0))
    
        if not getattr(obj, "ProfileXAxis", None):
            obj.ProfileXAxis = FreeCAD.Vector(0, 0, 0)
                
    def applyTypeSchema(self):
        obj = self.Object
        reg = hvaclib.HVACLibraryService.get_hvac_library_registry()
        lib_id = getattr(obj, "LibraryId", "")
        type_id = getattr(obj, "TypeId", "")
        if not lib_id or not type_id:
            return False
    
        type_def = reg.resolve_type(lib_id, type_id)
        if type_def is None:
            return False
    
        changed = False
    
        active_prop_names = set()
        for pdef in getattr(type_def, "properties", []) or []:
            active_prop_names.add(pdef.name)
            prop_added = False
    
            if pdef.name not in obj.PropertiesList:
                obj.addProperty(pdef.prop_type, pdef.name, pdef.group, pdef.description)
                changed = True
                prop_added = True
    
            try:
                current = getattr(obj, pdef.name)
            except Exception:
                current = None
    
            if getattr(pdef, "default", None) is not None:
                should_apply_default = prop_added or current in (None, "")
                if should_apply_default:
                    try:
                        setattr(obj, pdef.name, pdef.default)
                        changed = True
                    except Exception:
                        pass
    
            try:
                obj.setEditorMode(pdef.name, 0)
            except Exception:
                pass
    
        for prop in ("Diameter", "Width", "Height"):
            if prop in obj.PropertiesList:
                try:
                    obj.setEditorMode(prop, 0 if prop in active_prop_names else 1)
                except Exception:
                    pass
    
        return changed
    
    def resolveSourceEdge(self):
        """
        Resolve the live source edge for this segment using:
            - owning network
            - SourceObjectName
            - SourceIndex

        Supports:
            - Sketch geometry: line / arc / bspline / bezier
            - Shape edges: line / arc / bspline
        """
        obj = self.Object
        owner = hvaclib.getOwnerNetwork(obj)
        if owner is None or owner.Document is None:
            return None

        source_name = getattr(obj, "SourceObjectName", "") or ""
        source_index = int(getattr(obj, "SourceIndex", -1))
        
        if not source_name or source_index < 0:
            return None

        src = owner.Document.getObject(source_name)
        if src is None:
            return None

        # Case 1: Sketch source : Resolve source edge, create an edge based on it and return it
        if hvaclib.isSketch(src):
            geos = list(getattr(src, "Geometry", []) or [])
            if source_index >= len(geos):
                return None
                
            geo = geos[source_index]

            # Skip construction geometry
            try:
                if src.getConstruction(source_index):
                    return None
            except Exception:
                pass

            # Create an edge based on the sketch geometry
            try:
                return Part.Edge(geo)
            except Exception:
                return None

        # Case 2: Generic shape source : Resolve source edge and return it
        elif hvaclib.isWire(src):
            shape = getattr(src, "Shape", None)
            if shape is None:
                return None

            edges = list(getattr(shape, "Edges", []) or [])
            if source_index >= len(edges):
                return None
    
            edge = edges[source_index]        
            return edge
    
    def computeEdgeTrimData(self, edge, trim_start, trim_end):
        """
        Compute effective trim lengths and corresponding curve parameters.

        Returns:
            raw_length, ts, te, fp, lp, p1, p2

        where:
            raw_length : original edge length
            ts, te     : effective trim lengths from start/end
            fp, lp     : first/last parameters of original edge
            p1, p2     : parameter interval after trimming
        """
        if edge is None:
            return 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0

        raw_length = float(edge.Length)
        fp = float(edge.FirstParameter)
        lp = float(edge.LastParameter)

        if raw_length <= 1e-9:
            return raw_length, 0.0, 0.0, fp, lp, fp, lp

        ts = max(0.0, float(trim_start or 0.0))
        te = max(0.0, float(trim_end or 0.0))

        # Prevent over-trimming
        max_total = max(0.0, raw_length - 1e-9)
        total_trim = ts + te
        if total_trim > max_total:
            scale = max_total / total_trim if total_trim > 0.0 else 0.0
            ts *= scale
            te *= scale

        # Convert trim lengths to edge parameters
        try:
            p1 = edge.getParameterByLength(ts) if ts > 0.0 else fp
            p2 = edge.getParameterByLength(raw_length - te) if te > 0.0 else lp
            eff_sp = edge.valueAt(p1)
            eff_ep = edge.valueAt(p2)
        except Exception:
            # Fallback approximation for curves where getParameterByLength fails
            r1 = ts / raw_length if raw_length > 1e-12 else 0.0
            r2 = te / raw_length if raw_length > 1e-12 else 0.0
            p1 = fp + (lp - fp) * r1
            p2 = lp - (lp - fp) * r2
            
        # Get edge directions
        try:
            d1 = edge.tangentAt(p1)
        except Exception:
            d1 = eff_ep - eff_sp
        try:
            d2 = edge.tangentAt(p2)
        except Exception:
            d2 = eff_ep - eff_sp
            
        # Get path length
        trim_path_length = raw_length - (ts + te)

        return ts, te, fp, lp, p1, p2, eff_sp, eff_ep, d1, d2, trim_path_length

    def makeTrimmedEdge(self, edge, trim_start, trim_end):
        """
        Return a trimmed copy of the given edge based on length trimmed
        from the start and end.

        Returns:
            trimmed_edge, ts, te
        """
        if edge is None:
            return 0.0, 0.0, None, None, None, None, 0.0, None

        ts, te, fp, lp, p1, p2, eff_sp, eff_ep, d1, d2, raw_length = self.computeEdgeTrimData(
            edge, 
            trim_start,
            trim_end
        )

        if raw_length <= 1e-9:
            return 0.0, 0.0, None, None, None, None, 0.0, edge.copy()

        if p2 <= p1:
            return ts, te, None, None, None, None, 0.0, None

        try:
            trimmed = edge.Curve.toShape(p1, p2)
        except Exception:
            try:
                trimmed = edge.trim(p1, p2)
            except Exception:
                trimmed = None

        return ts, te, eff_sp, eff_ep, d1, d2, raw_length, trimmed
        
    def makeTrimmedShiftedEdge(self, edge, trim_start, trim_end,
                               profile, section_params,
                               attachment="Center",
                               user_offset=None,
                               profile_x_axis=None):
        """
        Build the routed path to be used for geometry generation.
    
        Returns:
            trimmed_center_edge,
            routed_edge,
            routed_start_point,
            routed_end_point,
            routed_start_dir,
            routed_end_dir
        """
        if user_offset is None:
            user_offset = FreeCAD.Vector(0, 0, 0)
        else:
            user_offset = FreeCAD.Vector(user_offset)
    
        # ----------------------------------------------------------
        # Step 1: trim original edge
        # ----------------------------------------------------------
        ts, te, sp, ep, sd, ed, raw_length, trimmed_edge = self.makeTrimmedEdge(edge, trim_start, trim_end)
        if trimmed_edge is None:
            return None, None, None, None, None, None
    
        # ----------------------------------------------------------
        # Step 2: compute attachment/user offset shift at start/end
        # ----------------------------------------------------------
        shift = hvaclib.compute_port_position(
            base_point=FreeCAD.Vector(0, 0, 0),
            direction=sd,
            section_params=section_params,
            attachment=attachment,
            user_offset_vec=user_offset,
            profile_x_axis=profile_x_axis,
        )
    
        rsp = sp + shift
        rep = ep + shift
    
        # ----------------------------------------------------------
        # Step 3: build shifted curve copy
        # ----------------------------------------------------------
        routed_edge = trimmed_edge.translate(shift)
    
        if routed_edge is None:
            routed_edge = trimmed_edge
    
        rfp = float(routed_edge.FirstParameter)
        rlp = float(routed_edge.LastParameter)
    
        try:
            rsd = routed_edge.tangentAt(rfp)
        except Exception:
            rsd = rep - rsp
        try:
            red = routed_edge.tangentAt(rlp)
        except Exception:
            red = rep - rsp
    
        rsd = self._unit(rsd, rep - rsp)
        red = self._unit(red, rep - rsp)
    
        return routed_edge, rsp, rep, rsd, red
    
    def computeTrimDataBasic(self, start_point, end_point, trim_start, trim_end):
        """Compute trim parameters for a segment defined by start_point and end_point, returning trimmed start/end points and lengths."""
        
        sp = FreeCAD.Vector(*start_point) if not hasattr(start_point, "x") else FreeCAD.Vector(start_point)
        ep = FreeCAD.Vector(*end_point) if not hasattr(end_point, "x") else FreeCAD.Vector(end_point)
    
        vec = ep - sp
        raw_length = vec.Length
    
        if raw_length <= 1e-9:
            return sp, ep, 0.0, 0.0, 0.0
    
        direction = FreeCAD.Vector(vec)
        direction.normalize()
    
        ts = max(0.0, float(trim_start or 0.0))
        te = max(0.0, float(trim_end or 0.0))
    
        max_total = max(0.0, raw_length - 1e-9)
        if ts + te > max_total:
            scale = max_total / (ts + te) if (ts + te) > 0 else 0.0
            ts *= scale
            te *= scale
    
        eff_sp = sp + direction * ts
        eff_ep = ep - direction * te
        eff_len = (eff_ep - eff_sp).Length
    
        return ts, te, eff_sp, eff_ep, direction, direction, eff_len

    def updateMetadata(
        self,
        owner=None,
        key="",
        source_obj=None,
        source_index=0,
        start_node=0,
        end_node=0,
        start_point=None,
        end_point=None,
        trim_start=None,
        trim_end=None,
        family="",
        type_id="",
        library_id="",
        profile="",
        analysis_json=None,
    ):
        obj = self.Object
        changed = False

        if owner and getattr(obj, "OwnerNetworkName", "") != owner.Name:
            obj.OwnerNetworkName = owner.Name
            changed = True

        if key and getattr(obj, "SegmentKey", "") != key:
            obj.SegmentKey = key
            changed = True

        source_name = source_obj.Name if source_obj else ""
        if getattr(obj, "SourceObjectName", "") != source_name:
            obj.SourceObjectName = source_name
            changed = True

        if getattr(obj, "SourceIndex", None) != int(source_index):
            obj.SourceIndex = int(source_index)
            changed = True

        if getattr(obj, "StartNode", None) != int(start_node):
            obj.StartNode = int(start_node)
            changed = True

        if getattr(obj, "EndNode", None) != int(end_node):
            obj.EndNode = int(end_node)
            changed = True
            
        if trim_start is not None and abs(float(getattr(obj, "TrimStart", 0.0)) - float(trim_start)) > 1e-9:
            obj.TrimStart = trim_start
            changed = True
            
        if trim_end is not None and abs(float(getattr(obj, "TrimEnd", 0.0)) - float(trim_end)) > 1e-9:
            obj.TrimEnd = trim_end
            changed = True
            
        # Compute start/end vectors
        start_vec = None
        end_vec = None
        
        if start_point is not None:
            start_vec = FreeCAD.Vector(*start_point)
            if obj.StartPoint != start_vec:
                obj.StartPoint = start_vec
                changed = True
        
        if end_point is not None:
            end_vec = FreeCAD.Vector(*end_point)
            if obj.EndPoint != end_vec:
                obj.EndPoint = end_vec
                changed = True
            
        if start_vec is not None and end_vec is not None:
            length = (end_vec - start_vec).Length
            if abs(float(obj.CenterlineLength) - float(length)) > 1e-9:
                obj.CenterlineLength = length
                changed = True

        edge = self.resolveSourceEdge()
        
        if start_point is not None and end_point is not None and trim_start is not None and trim_end is not None:
            if edge:
                ts, te, fp, lp, p1, p2, eff_sp, eff_ep, eff_sd, eff_ed, eff_len = self.computeEdgeTrimData(
                    edge, 
                    trim_start if trim_start is not None else getattr(obj, "TrimStart", 0.0),
                    trim_end if trim_end is not None else getattr(obj, "TrimEnd", 0.0)
                )
                path_kind = hvaclib.EdgeKind(edge)
            else:
                trim_start, trim_end, eff_sp, eff_ep, eff_sd, eff_ed, eff_len = self.computeTrimDataBasic(
                    start_point,
                    end_point,
                    trim_start,
                    trim_end,
                )
                path_kind = "straight"
                
            if eff_sp is not None and getattr(obj, "EffectiveStartPoint", None) != eff_sp:
                obj.EffectiveStartPoint = eff_sp
                changed = True
                
            if eff_ep is not None and getattr(obj, "EffectiveEndPoint", None) != eff_ep:
                obj.EffectiveEndPoint = eff_ep
                changed = True
                
            if abs(float(getattr(obj, "EffectiveLength", 0.0)) - float(eff_len)) > 1e-9:
                obj.EffectiveLength = eff_len
                changed = True
                
            if eff_sd is not None and getattr(obj, "StartDirection", None) != eff_sd:
                obj.StartDirection = eff_sd
                changed = True
                
            if eff_ed is not None and getattr(obj, "EndDirection", None) != eff_ed:
                obj.EndDirection = eff_ed
                changed = True
                
            if getattr(obj, "PathKind", "") != path_kind:
                obj.PathKind = path_kind
                changed = True

        if library_id and getattr(obj, "LibraryId", "") != str(library_id):
            obj.LibraryId = str(library_id)
            changed = True
            
        if family and getattr(obj, "Family", "") != str(family):
            obj.Family = str(family)
            changed = True
            
        if type_id and getattr(obj, "TypeId", "") != str(type_id):
            obj.TypeId = str(type_id)
            changed = True
            
        if profile and getattr(obj, "Profile", "") != str(profile):
            obj.Profile = str(profile)
            changed = True

        if analysis_json is not None and getattr(obj, "AnalysisJson", "") != str(analysis_json):
            obj.AnalysisJson = str(analysis_json)
            changed = True

        return changed

    @classmethod
    def create(cls, doc, name, owner, key, source_obj, source_index):
        segment = doc.addObject("Part::FeaturePython", name)
        cls(
            segment,
            owner=owner,
            key=key,
            source_obj=source_obj,
            source_index=source_index,
        )
        DuctSegmentViewProvider(segment.ViewObject)
        return segment

    @staticmethod
    def labelFor(source_obj, source_index):
        return "{} [{}]".format(source_obj.Label if source_obj else "Segment", int(source_index))

    @staticmethod
    def _addProperty(obj, prop_type, prop_name, group, description):
        if prop_name not in obj.PropertiesList:
            obj.addProperty(prop_type, prop_name, group, description)

    def _unit(self, v, fallback=None):
        vv = hvaclib.vec(v)
        if vv is None or vv.Length <= 1e-9:
            if fallback is None:
                return FreeCAD.Vector(1, 0, 0)
            ff = FreeCAD.Vector(fallback)
            if ff.Length <= 1e-9:
                return FreeCAD.Vector(1, 0, 0)
            ff.normalize()
            return ff
        vv.normalize()
        return vv
            
            
class DuctSegmentViewProvider:
    """View provider for derived duct segment objects."""

    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object

    def dumps(self):
        return None

    def loads(self, state):
        pass

    def getIcon(self):
        return hvaclib.get_icon_path("DuctsIcon.svg")

    def onDelete(self, vobj, subelements):
        obj = vobj.Object
        owner = hvaclib.getOwnerNetwork(obj)
        if getattr(obj.Proxy, "_allow_delete", False):
            return True
        if owner and getattr(owner.Proxy, "_allow_internal_delete", False):
            return True
        FreeCAD.Console.PrintWarning(
            "HVAC - Internal segment '{}' cannot be deleted directly.\n".format(obj.Label)
        )
        return False

    def canDropObjects(self):
        return False

    def canDragObjects(self):
        return False
