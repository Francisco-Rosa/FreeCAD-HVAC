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
import json
import traceback

import FreeCAD, Part
import FreeCADGui as Gui
from PySide import QtWidgets, QtCore
from PySide.QtCore import QT_TRANSLATE_NOOP
translate = FreeCAD.Qt.translate

from ..utils import hvaclib


class DuctJunction:
    """Derived per-node duct junction created from network base geometry."""

    TYPE = "DuctJunction"

    def __init__(
        self,
        obj,
        owner=None,
        node_id=0,
        node_key="",
        center_point=None,
        degree=0,
        topology=""
    ):
        obj.Proxy = self
        self.Object = obj
        self._allow_delete = False
        self.setProperties(obj)
        self.updateMetadata(
            owner=owner,
            node_id=node_id,
            node_key=node_key,
            center_point=center_point,
            degree=degree,
            topology=topology
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
        center_point = getattr(obj, "CenterPoint", None)
        if center_point is None:
            return

        library_id = getattr(obj, "LibraryId", "")
        type_id = getattr(obj, "TypeId", "")
        if not library_id or not type_id:
            return

        try:
            reg = hvaclib.HVACLibraryService.get_hvac_library_registry()
            type_def = reg.resolve_type(library_id, type_id)
            if type_def is None:
                raise ValueError(
                    "Unknown junction type '{}' in library '{}'".format(
                        type_id, library_id
                    )
                )

            props = {}
            for pdef in getattr(type_def, "properties", []) or []:
                if hasattr(obj, pdef.name):
                    props[pdef.name] = getattr(obj, pdef.name)
                else:
                    props[pdef.name] = getattr(pdef, "default", None)

            connected_ports = []
            raw_analysis = getattr(obj, "AnalysisJson", "") or "{}"
            try:
                analysis = json.loads(raw_analysis)
                connected_ports = list(analysis.get("connected_ports", []) or [])
            except Exception:
                connected_ports = []
            
            context = {
                "obj": obj,
                "center_point": center_point,
                "properties": props,
                "connected_ports": connected_ports,
                "family": getattr(obj, "Family", ""),
                "type_id": type_id,
                "library_id": library_id,
            }

            result = reg.call_generator(library_id, type_def, context)
            shape = result.get("shape", None)
            lengths = result.get("connection_lengths", [])

            if shape is not None:
                obj.Shape = shape

            lengths_json = json.dumps(lengths)
            if getattr(obj, "ConnectionLengthsJson", "") != lengths_json:
                obj.ConnectionLengthsJson = lengths_json

        except Exception as e:
            FreeCAD.Console.PrintWarning(
                "HVAC - DuctJunction - Execute Error generating junction '{}': {}\n".format(obj.Label, e)
            )
            FreeCAD.Console.PrintMessage(traceback.format_exc())

    def setProperties(self, obj):
        self._addProperty(obj, "App::PropertyString", "OwnerNetworkName", "HVAC", "Owning duct network")
        self._addProperty(obj, "App::PropertyInteger", "NodeId", "HVAC", "Parser node id")
        self._addProperty(obj, "App::PropertyString", "NodeKey", "HVAC", "Persistent snapped node key")
        self._addProperty(obj, "App::PropertyVector", "CenterPoint", "HVAC", "Junction center point")
        self._addProperty(obj, "App::PropertyInteger", "Degree", "HVAC", "Node degree")
        self._addProperty(obj, "App::PropertyString", "Topology", "HVAC", "Junction topology")
        self._addProperty(obj, "App::PropertyString", "Family", "HVAC", "Classified fitting family")

        self._addProperty(obj, "App::PropertyString", "LibraryId", "HVAC", "HVAC library id")
        self._addProperty(obj, "App::PropertyString", "TypeId", "HVAC", "Selected fitting type id")
        self._addProperty(obj, "App::PropertyStringList", "ConnectedEdgeKeys", "HVAC", "Connected segment keys")
        self._addProperty(obj, "App::PropertyString", "ConnectionLengthsJson", "HVAC", "Per-edge connection lengths")
        self._addProperty(obj, "App::PropertyString", "AnalysisJson", "HVAC", "Serialized topology analysis")

        if not getattr(obj, "LibraryId", ""):
            lib = hvaclib.HVACLibraryService.get_active_hvac_library()
            if lib:
                obj.LibraryId = lib.id

        if not getattr(obj, "ConnectionLengthsJson", ""):
            obj.ConnectionLengthsJson = "[]"

        if not getattr(obj, "AnalysisJson", ""):
            obj.AnalysisJson = "{}"

        for prop in (
            "OwnerNetworkName",
            "NodeId",
            "NodeKey",
            "CenterPoint",
            "Degree",
            "Topology",
            "Family",
            "ConnectedEdgeKeys",
            "ConnectionLengthsJson",
            "AnalysisJson",
        ):
            try:
                obj.setEditorMode(prop, 1)
            except Exception:
                pass

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
        for pdef in getattr(type_def, "properties", []) or []:
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
    
        return changed

    def updateMetadata(
        self,
        owner=None,
        node_id=0,
        node_key="",
        center_point=None,
        degree=0,
        topology="",
        family="",
        type_id="",
        library_id="",
        connected_edge_keys=None,
        analysis_json="{}",
        connection_lengths_json=None,
    ):
        obj = self.Object
        changed = False

        if owner and getattr(obj, "OwnerNetworkName", "") != owner.Name:
            obj.OwnerNetworkName = owner.Name
            changed = True

        if getattr(obj, "NodeId", None) != int(node_id):
            obj.NodeId = int(node_id)
            changed = True

        if getattr(obj, "NodeKey", "") != str(node_key):
            obj.NodeKey = str(node_key)
            changed = True

        if center_point is not None:
            center_vec = FreeCAD.Vector(*center_point)
            if obj.CenterPoint != center_vec:
                obj.CenterPoint = center_vec
                changed = True
                
        if getattr(obj, "Degree", None) != int(degree):
            obj.Degree = int(degree)
            changed = True
            
        if getattr(obj, "Topology", "") != str(topology):
            obj.Topology = str(topology)
            # If topology changes, set TypeId to default for the topology
            obj.TypeId = hvaclib.HVACLibraryService.default_topology_type_id(obj.Topology)
            changed = True

        if family and getattr(obj, "Family", "") != str(family):
            obj.Family = str(family)
            # If family changes, set TypeId to default for the topology
            obj.TypeId = hvaclib.HVACLibraryService.default_topology_type_id(obj.Topology)
            changed = True
        
        if library_id and getattr(obj, "LibraryId", "") != str(library_id):
            obj.LibraryId = str(library_id)
            changed = True

        if type_id and getattr(obj, "TypeId", "") != str(type_id):
            _library = getattr(obj, "LibraryId", "")
            _family = getattr(obj, "Family", "")
            valid_type_ids = hvaclib.HVACLibraryService.all_junction_type_defs(library_id=_library, family=_family)
            if type_id in valid_type_ids:
                obj.TypeId = str(type_id)
                changed = True

        if connected_edge_keys is not None:
            edge_keys = [str(k) for k in connected_edge_keys]
            if list(getattr(obj, "ConnectedEdgeKeys", []) or []) != edge_keys:
                obj.ConnectedEdgeKeys = edge_keys
                changed = True

        if analysis_json is not None and getattr(obj, "AnalysisJson", "") != str(analysis_json):
            obj.AnalysisJson = str(analysis_json)
            changed = True

        if connection_lengths_json is not None:
            if getattr(obj, "ConnectionLengthsJson", "") != str(connection_lengths_json):
                obj.ConnectionLengthsJson = str(connection_lengths_json)
                changed = True

        return changed

    @classmethod
    def create(cls, doc, name, owner, node_id, node_key, center_point, degree, topology):
        junction = doc.addObject("Part::FeaturePython", name)
        cls(
            junction,
            owner=owner,
            node_id=node_id,
            node_key=node_key,
            center_point=center_point,
            degree=degree,
            topology=topology
        )
        DuctJunctionViewProvider(junction.ViewObject)
        return junction
    
    @staticmethod
    def labelFor(family, node_id):
        family_label = str(family).capitalize() if family else "Junction"
        return "{} [{}]".format(family_label, int(node_id))

    @staticmethod
    def _addProperty(obj, prop_type, prop_name, group, description):
        if prop_name not in obj.PropertiesList:
            obj.addProperty(prop_type, prop_name, group, description)


class DuctJunctionViewProvider:
    """View provider for derived duct junction objects."""

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
            "HVAC - Internal junction '{}' cannot be deleted directly.\n".format(obj.Label)
        )
        return False

    def canDropObjects(self):
        return False

    def canDragObjects(self):
        return False


class DuctJunctionVirtual:
    """User-authored logical junction definition used to group parser nodes."""

    TYPE = "DuctJunctionVirtual"

    def __init__(self, obj, owner=None, member_node_keys=None, member_points=None):
        obj.Proxy = self
        self.Object = obj
        self.setProperties(obj)
        self.updateMetadata(
            owner=owner, 
            member_node_keys=member_node_keys or [],
            member_points=member_points or [] )

    def onDocumentRestored(self, obj):
        obj.Proxy = self
        self.Object = obj
        self.setProperties(obj)

    def dumps(self):
        return None

    def loads(self, state):
        pass

    def execute(self, obj):
        # No generated geometry yet. Keep empty.
        pass

    def setProperties(self, obj):
        self._addProperty(obj, "App::PropertyString", "OwnerNetworkName", "HVAC", "Owning duct network")
        self._addProperty(obj, "App::PropertyStringList", "MemberNodeKeys", "HVAC", "Array of member node keys")
        self._addProperty(obj, "App::PropertyVectorList", "MemberPoints", "HVAC", "Array of junction points")

        # Read-only internal metadata
        for prop in ("OwnerNetworkName", "MemberNodeKeys", "MemberPoints"):
            try:
                obj.setEditorMode(prop, 1)
            except Exception:
                pass

        if not getattr(obj, "MemberNodeKeys", []):
            obj.MemberNodeKeys = []
            
        if not getattr(obj, "MemberPoints", []):
            obj.MemberPoints = []
            

    def updateMetadata(self, owner=None, member_node_keys=[], member_points=[]):
        obj = self.Object
        changed = False
        
        def compare_vector_lists(list1, list2, tol=1e-6):
            if len(list1) != len(list2):
                return False
            for v1, v2 in zip(list1, list2):
                if (v1 - v2).Length > tol:
                    return False
            return True

        owner_name = owner.Name if owner else getattr(obj, "OwnerNetworkName", "")
        if getattr(obj, "OwnerNetworkName", "") != owner_name:
            obj.OwnerNetworkName = owner_name
            changed = True

        if getattr(obj, "MemberNodeKeys", []) != member_node_keys:
            obj.MemberNodeKeys = member_node_keys
            changed = True
                
        member_points_vecs = [FreeCAD.Vector(t) for t in member_points]
        if compare_vector_lists(getattr(obj, "MemberPoints", []), member_points_vecs) is False:
            obj.MemberPoints = member_points_vecs
            changed = True

        # Friendly label
        try:
            keys = list(member_node_keys or [])
            if keys:
                obj.Label = "Virtual Junction ({})".format(len(keys))
        except Exception:
            pass

        return changed

    @classmethod
    def create(cls, doc, name, owner, member_node_keys, member_points):
        vj = doc.addObject("App::FeaturePython", name)
        cls(vj, owner=owner, member_node_keys=member_node_keys, member_points=member_points)
        DuctJunctionVirtualViewProvider(vj.ViewObject)
        return vj

    def getMemberNodeKeys(self):
        return getattr(self.Object, "MemberNodeKeys", [])
        
    def getMemberPoints(self):
        points = getattr(self.Object, "MemberPoints", "")
        return [tuple(x) for x in points]

    @staticmethod
    def _addProperty(obj, prop_type, prop_name, group, description):
        if prop_name not in obj.PropertiesList:
            obj.addProperty(prop_type, prop_name, group, description)
            

class DuctJunctionVirtualViewProvider:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object

    def dumps(self):
        return None

    def loads(self, state):
        pass

    def getIcon(self):
        return hvaclib.get_icon_path("Junction.svg")

    def onDelete(self, vobj, subelements):
        # User must be able to delete these directly from the tree.
        return True
