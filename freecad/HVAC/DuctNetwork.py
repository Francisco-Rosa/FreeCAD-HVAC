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
import FreeCAD
import FreeCADGui as Gui
from PySide import QtWidgets, QtCore
from PySide.QtCore import QT_TRANSLATE_NOOP
translate = FreeCAD.Qt.translate

from . import hvaclib
from . import Observer
from . import TaskPanel


class DuctManagedFolder:
    """Internal managed folder used by DuctNetwork."""

    def __init__(self, obj, owner=None, role=""):
        obj.Proxy = self
        if "OwnerNetworkName" not in obj.PropertiesList:
            # Store link as string to avoid cyclic dependency issue
            obj.addProperty("App::PropertyString", "OwnerNetworkName", "HVAC", "Owning duct network")
        if "FolderRole" not in obj.PropertiesList:
            obj.addProperty("App::PropertyString", "FolderRole", "HVAC", "Internal folder role")
        obj.OwnerNetworkName = owner.Name if owner else ""
        obj.FolderRole = role

    def onDocumentRestored(self, obj):
        obj.Proxy = self

    def execute(self, obj):
        """Required so the object can clear its touched state on recompute."""
        pass

    @staticmethod
    def getOwner(obj):
        return DuctNetwork.getOwnerNetwork(obj)

    @staticmethod
    def create(doc, name, owner, role):
        folder = doc.addObject("App::DocumentObjectGroupPython", name)
        DuctManagedFolder(folder, owner=owner, role=role)
        DuctManagedFolderViewProvider(folder.ViewObject)
        return folder


class DuctManagedFolderViewProvider:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object

    def __getstate__(self):
        state = self.__dict__.copy()
        state.pop("Object", None)
        return state

    def __setstate__(self, state):
        self.__dict__.update(state)

    def getIcon(self):
        return hvaclib.get_icon_path("Folder.svg")  # optional

    def onDelete(self, vobj, subelements):
        obj = vobj.Object
        owner = DuctNetwork.getOwnerNetwork(obj)
        # Allow deletion only when the owner network itself is being deleted
        if owner and getattr(owner.Proxy, "_allow_internal_delete", False):
            return True
        FreeCAD.Console.PrintWarning(
            "HVAC - Internal folder '{}' cannot be deleted directly.\n".format(obj.Label)
        )
        return False

    def claimChildren(self):
        try:
            return list(self.Object.OutList)
        except Exception:
            return []

    def canDropObjects(self):
        return False

    def canDragObjects(self):
        return False


class DuctSegment:
    """Derived per-edge duct segment created from network base geometry."""

    TYPE = "DuctSegment"

    def __init__(self, obj, owner=None, key="", source_obj=None, source_index=0):
        obj.Proxy = self
        self._allow_delete = False
        self.setProperties(obj)
        self.updateMetadata(
            obj,
            owner=owner,
            key=key,
            source_obj=source_obj,
            source_index=source_index,
        )

    def onDocumentRestored(self, obj):
        obj.Proxy = self
        self._allow_delete = False
        self.setProperties(obj)

    def __getstate__(self):
        return None

    def __setstate__(self, state):
        self._allow_delete = False

    def execute(self, obj):
        start_point = getattr(obj, "StartPoint", None)
        end_point = getattr(obj, "EndPoint", None)
        if start_point is None or end_point is None:
            return

        try:
            if start_point.sub(end_point).Length <= 0:
                return

            library_id = getattr(obj, "LibraryId", "")
            type_id = getattr(obj, "TypeId", "")
            if not library_id or not type_id:
                return

            reg = hvaclib.get_hvac_library_registry()
            type_def = reg.resolve_type(library_id, type_id)
            if type_def is None:
                raise ValueError(
                    "Unknown segment type '{}' in library '{}'".format(
                        type_id, library_id
                    )
                )

            props = {}
            for pdef in getattr(type_def, "properties", []) or []:
                if hasattr(obj, pdef.name):
                    props[pdef.name] = getattr(obj, pdef.name)
                else:
                    props[pdef.name] = getattr(pdef, "default", None)

            context = {
                "obj": obj,
                "start_point": start_point,
                "end_point": end_point,
                "properties": props,
                "family": getattr(obj, "Family", ""),
                "profile": getattr(obj, "Profile", ""),
                "type_id": type_id,
                "library_id": library_id,
                "segment_key": getattr(obj, "SegmentKey", ""),
                "source_object_name": getattr(obj, "SourceObjectName", ""),
                "source_index": int(getattr(obj, "SourceIndex", 0)),
            }

            result = reg.call_generator(library_id, type_def, context)
            shape = result.get("shape", None)
            if shape is not None:
                obj.Shape = shape

        except Exception as e:
            FreeCAD.Console.PrintError(
                "HVAC - Error generating segment '{}': {}\n".format(obj.Label, e)
            )

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

        self._addProperty(obj, "App::PropertyString", "LibraryId", "HVAC", "HVAC library id")
        self._addProperty(obj, "App::PropertyString", "Family", "HVAC", "Segment family")
        self._addProperty(obj, "App::PropertyString", "TypeId", "HVAC", "Selected segment type id")
        self._addProperty(obj, "App::PropertyBool", "AutoType", "HVAC", "Auto-select type from network defaults")
        self._addProperty(obj, "App::PropertyString", "Profile", "HVAC", "Segment profile")
        self._addProperty(obj, "App::PropertyString", "AnalysisJson", "HVAC", "Serialized segment analysis")

        # Keep these as generic dimensional parameters. The active type schema
        # decides whether they are used.
        self._addProperty(obj, "App::PropertyLength", "Diameter", "Dimensions", "Circular duct diameter")
        self._addProperty(obj, "App::PropertyLength", "Width", "Dimensions", "Rectangular duct width")
        self._addProperty(obj, "App::PropertyLength", "Height", "Dimensions", "Rectangular duct height")
        self._addProperty(obj, "App::PropertyLength", "InsulationThickness", "Parameters", "Insulation thickness")
        self._addProperty(obj, "App::PropertyLength", "Roughness", "Parameters", "Wall roughness")
        self._addProperty(obj, "App::PropertyFloat", "FlowRate", "Parameters", "Design flow rate")
        self._addProperty(obj, "App::PropertyFloat", "Velocity", "Parameters", "Design air velocity")

        if not obj.Diameter:
            obj.Diameter = 100.0
        if not obj.Width:
            obj.Width = 100.0
        if not obj.Height:
            obj.Height = 100.0

        if getattr(obj, "AutoType", None) is None:
            obj.AutoType = True

        if not getattr(obj, "LibraryId", ""):
            lib = hvaclib.get_active_hvac_library()
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

    def applyTypeSchema(self, obj):
        reg = hvaclib.get_hvac_library_registry()
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

            if pdef.name not in obj.PropertiesList:
                obj.addProperty(pdef.prop_type, pdef.name, pdef.group, pdef.description)
                changed = True

            try:
                current = getattr(obj, pdef.name)
            except Exception:
                current = None

            if current in (None, "") and getattr(pdef, "default", None) is not None:
                try:
                    setattr(obj, pdef.name, pdef.default)
                    changed = True
                except Exception:
                    pass

            try:
                obj.setEditorMode(pdef.name, 0)
            except Exception:
                pass

        # Hide known generic dimension fields that are not active for the current type
        for prop in ("Diameter", "Width", "Height"):
            if prop in obj.PropertiesList:
                try:
                    obj.setEditorMode(prop, 0 if prop in active_prop_names else 1)
                except Exception:
                    pass

        return changed

    def updateMetadata(
        self,
        obj,
        owner=None,
        key="",
        source_obj=None,
        source_index=0,
        start_node=0,
        end_node=0,
        start_point=None,
        end_point=None,
        family="",
        type_id="",
        library_id="",
        profile="",
        analysis_json=None,
    ):
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
            length = end_vec.sub(start_vec).Length
            if abs(float(obj.CenterlineLength) - float(length)) > 1e-9:
                obj.CenterlineLength = length
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
    def isDuctSegment(obj):
        return bool(obj) and hasattr(obj, "Proxy") and isinstance(obj.Proxy, DuctSegment)

    @staticmethod
    def makeKey(obj_name, source_index):
        return "{}:{}".format(obj_name, int(source_index))

    @staticmethod
    def labelFor(source_obj, source_index):
        return "{} [{}]".format(source_obj.Label if source_obj else "Segment", int(source_index))

    @staticmethod
    def _addProperty(obj, prop_type, prop_name, group, description):
        if prop_name not in obj.PropertiesList:
            obj.addProperty(prop_type, prop_name, group, description)
            
            
class DuctSegmentViewProvider:
    """View provider for derived duct segment objects."""

    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object

    def __getstate__(self):
        state = self.__dict__.copy()
        state.pop("Object", None)
        return state

    def __setstate__(self, state):
        self.__dict__.update(state)

    def getIcon(self):
        return hvaclib.get_icon_path("DuctsIcon.svg")

    def onDelete(self, vobj, subelements):
        obj = vobj.Object
        owner = DuctNetwork.getOwnerNetwork(obj)
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


class DuctJunction:
    """Derived per-node duct junction created from network base geometry."""

    TYPE = "DuctJunction"

    def __init__(
        self,
        obj,
        owner=None,
        node_id=0,
        node_key="",
        node_kind="",
        center_point=None,
        degree=0,
    ):
        obj.Proxy = self
        self._allow_delete = False
        self.setProperties(obj)
        self.updateMetadata(
            obj,
            owner=owner,
            node_id=node_id,
            node_key=node_key,
            node_kind=node_kind,
            center_point=center_point,
            degree=degree,
        )

    def onDocumentRestored(self, obj):
        obj.Proxy = self
        self._allow_delete = False
        self.setProperties(obj)

    def __getstate__(self):
        return None

    def __setstate__(self, state):
        self._allow_delete = False

    def execute(self, obj):
        center_point = getattr(obj, "CenterPoint", None)
        if center_point is None:
            return

        library_id = getattr(obj, "LibraryId", "")
        type_id = getattr(obj, "TypeId", "")
        if not library_id or not type_id:
            return

        try:
            reg = hvaclib.get_hvac_library_registry()
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

            edge_keys = list(getattr(obj, "ConnectedEdgeKeys", []) or [])

            context = {
                "obj": obj,
                "center_point": center_point,
                "properties": props,
                "edge_keys": edge_keys,
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
            FreeCAD.Console.PrintError(
                "HVAC - Error generating junction '{}': {}\n".format(obj.Label, e)
            )

    def setProperties(self, obj):
        self._addProperty(obj, "App::PropertyString", "OwnerNetworkName", "HVAC", "Owning duct network")
        self._addProperty(obj, "App::PropertyInteger", "NodeId", "HVAC", "Parser node id")
        self._addProperty(obj, "App::PropertyString", "NodeKey", "HVAC", "Persistent snapped node key")
        self._addProperty(obj, "App::PropertyString", "NodeKind", "HVAC", "Junction classification")
        self._addProperty(obj, "App::PropertyInteger", "Degree", "HVAC", "Node degree")
        self._addProperty(obj, "App::PropertyVector", "CenterPoint", "HVAC", "Junction center point")

        self._addProperty(obj, "App::PropertyString", "LibraryId", "HVAC", "HVAC library id")
        self._addProperty(obj, "App::PropertyString", "Family", "HVAC", "Classified fitting family")
        self._addProperty(obj, "App::PropertyString", "TypeId", "HVAC", "Selected fitting type id")
        self._addProperty(obj, "App::PropertyBool", "AutoType", "HVAC", "Auto-select type from topology")
        self._addProperty(obj, "App::PropertyStringList", "ConnectedEdgeKeys", "HVAC", "Connected segment keys")
        self._addProperty(obj, "App::PropertyString", "ConnectionLengthsJson", "HVAC", "Per-edge connection lengths")
        self._addProperty(obj, "App::PropertyString", "AnalysisJson", "HVAC", "Serialized topology analysis")

        # Keep this generic marker parameter for the built-in marker library.
        self._addProperty(obj, "App::PropertyLength", "MarkerDiameter", "Dimensions", "Display marker diameter")

        if getattr(obj, "AutoType", None) is None:
            obj.AutoType = True

        if not getattr(obj, "LibraryId", ""):
            lib = hvaclib.get_active_hvac_library()
            if lib:
                obj.LibraryId = lib.id

        if not getattr(obj, "MarkerDiameter", 0):
            obj.MarkerDiameter = 200.0

        if not getattr(obj, "ConnectionLengthsJson", ""):
            obj.ConnectionLengthsJson = "[]"

        if not getattr(obj, "AnalysisJson", ""):
            obj.AnalysisJson = "{}"

        for prop in (
            "OwnerNetworkName",
            "NodeId",
            "NodeKey",
            "NodeKind",
            "Degree",
            "CenterPoint",
            "Family",
            "ConnectedEdgeKeys",
            "ConnectionLengthsJson",
            "AnalysisJson",
        ):
            try:
                obj.setEditorMode(prop, 1)
            except Exception:
                pass

    def applyTypeSchema(self, obj):
        reg = hvaclib.get_hvac_library_registry()
        lib_id = getattr(obj, "LibraryId", "")
        type_id = getattr(obj, "TypeId", "")
        if not lib_id or not type_id:
            return False

        type_def = reg.resolve_type(lib_id, type_id)
        if type_def is None:
            return False

        changed = False
        for pdef in getattr(type_def, "properties", []) or []:
            if pdef.name not in obj.PropertiesList:
                obj.addProperty(pdef.prop_type, pdef.name, pdef.group, pdef.description)
                changed = True

            try:
                current = getattr(obj, pdef.name)
            except Exception:
                current = None

            if current in (None, "") and getattr(pdef, "default", None) is not None:
                try:
                    setattr(obj, pdef.name, pdef.default)
                    changed = True
                except Exception:
                    pass

        return changed

    def updateMetadata(
        self,
        obj,
        owner=None,
        node_id=0,
        node_key="",
        node_kind="",
        center_point=None,
        degree=0,
        family="",
        type_id="",
        library_id="",
        connected_edge_keys=None,
        analysis_json="{}",
        connection_lengths_json=None,
    ):
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

        if getattr(obj, "NodeKind", "") != str(node_kind):
            obj.NodeKind = str(node_kind)
            changed = True

        if getattr(obj, "Degree", None) != int(degree):
            obj.Degree = int(degree)
            changed = True

        if center_point is not None:
            center_vec = FreeCAD.Vector(*center_point)
            if obj.CenterPoint != center_vec:
                obj.CenterPoint = center_vec
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
    def create(cls, doc, name, owner, node_id, node_key, node_kind, center_point, degree):
        junction = doc.addObject("Part::FeaturePython", name)
        cls(
            junction,
            owner=owner,
            node_id=node_id,
            node_key=node_key,
            node_kind=node_kind,
            center_point=center_point,
            degree=degree,
        )
        DuctJunctionViewProvider(junction.ViewObject)
        return junction

    @staticmethod
    def isDuctJunction(obj):
        return bool(obj) and hasattr(obj, "Proxy") and isinstance(obj.Proxy, DuctJunction)

    @staticmethod
    def makeKey(node_key):
        return "NODE:{}_{}_{}".format(node_key[0], node_key[1], node_key[2])

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

    def __getstate__(self):
        state = self.__dict__.copy()
        state.pop("Object", None)
        return state

    def __setstate__(self, state):
        self.__dict__.update(state)

    def getIcon(self):
        return hvaclib.get_icon_path("DuctsIcon.svg")

    def onDelete(self, vobj, subelements):
        obj = vobj.Object
        owner = DuctNetwork.getOwnerNetwork(obj)
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


class DuctNetwork:
    """Visualize and configure HVAC duct network in FreeCAD's 3D view."""

    CONTEXT_KEY = hvaclib.DUCT_NETWORK_CONTEXT_KEY
    FOLDER_BASE_NAME = "Base"
    FOLDER_GEOMETRY_NAME = "Geometry"

    def __init__(self, obj):
        obj.Proxy = self
        self._runtime_param_cache = {}
        self._allow_internal_delete = False
        self._initial_sync = True
        self._sync_in_progress = False
        self._sync_scheduled = False
        self._sync_reason = None
        self._hidden_source_names = set()
        self.setProperties(obj)
        
    def __getstate__(self):
        state = self.__dict__.copy()
        state.pop("_hidden_source_names", None)
        return state

    def __setstate__(self, state):
        self.__dict__.update(state)

    def onDocumentRestored(self, obj):
        obj.Proxy = self
        self._runtime_param_cache = {}
        self._allow_internal_delete = False
        self._initial_sync = True
        self._sync_in_progress = False
        self._sync_scheduled = False
        self._sync_reason = None
        self._hidden_source_names = set()
        self.setProperties(obj)
        self.requestSync(obj, initial_sync=True, reason="restore")
        
    def execute(self, obj):
        """Manual recompute of the network triggers deferred synchronization."""
        if self._sync_in_progress:
            return
        self.requestSync(obj, reason="execute")

    def setProperties(self, obj):
        """Gives the object properties to HVAC ducts."""
        doc = obj.Document

        # Base folder
        if "Base" not in obj.PropertiesList:
            obj.addProperty("App::PropertyLink", "Base", "HVAC", "Base (internal)")
        if getattr(obj, "Base", None) is None and doc is not None:
            folder_base = DuctManagedFolder.create(
                doc,
                f"{obj.Name}_{self.FOLDER_BASE_NAME}",
                owner=obj,
                role=self.FOLDER_BASE_NAME,
            )
            folder_base.Label = self.FOLDER_BASE_NAME
            obj.Base = folder_base
        elif obj.Base:
            if getattr(obj.Base, "OwnerNetworkName", "") != obj.Name:
                obj.Base.OwnerNetworkName = obj.Name
            if getattr(obj.Base, "FolderRole", "") != self.FOLDER_BASE_NAME:
                obj.Base.FolderRole = self.FOLDER_BASE_NAME

        # Geometry folder
        if "Geometry" not in obj.PropertiesList:
            obj.addProperty("App::PropertyLink", "Geometry", "HVAC", "Geometry (internal)")
        if getattr(obj, "Geometry", None) is None and doc is not None:
            folder_geometry = DuctManagedFolder.create(
                doc,
                f"{obj.Name}_{self.FOLDER_GEOMETRY_NAME}",
                owner=obj,
                role=self.FOLDER_GEOMETRY_NAME,
            )
            folder_geometry.Label = self.FOLDER_GEOMETRY_NAME
            obj.Geometry = folder_geometry
        elif obj.Geometry:
            if getattr(obj.Geometry, "OwnerNetworkName", "") != obj.Name:
                obj.Geometry.OwnerNetworkName = obj.Name
            if getattr(obj.Geometry, "FolderRole", "") != self.FOLDER_GEOMETRY_NAME:
                obj.Geometry.FolderRole = self.FOLDER_GEOMETRY_NAME
                
        # -------------------------------------------------
        # Library/type defaults for this network
        # -------------------------------------------------
        
        if "DefaultLibraryId" not in obj.PropertiesList:
            obj.addProperty(
                "App::PropertyString",
                "DefaultLibraryId",
                "HVAC Types",
                "Default HVAC library for derived geometry"
            )

        if "DefaultSegmentProfile" not in obj.PropertiesList:
            obj.addProperty(
                "App::PropertyString",
                "DefaultSegmentProfile",
                "HVAC Types",
                "Default segment profile from selected library"
            )

        if "DefaultSegmentAutoType" not in obj.PropertiesList:
            obj.addProperty(
                "App::PropertyBool",
                "DefaultSegmentAutoType",
                "HVAC Types",
                "Default auto-type behavior for new duct segments"
            )

        if not getattr(obj, "DefaultLibraryId", ""):
            lib = hvaclib.get_active_hvac_library()
            if lib:
                obj.DefaultLibraryId = lib.id

        if not getattr(obj, "DefaultSegmentProfile", ""):
            obj.DefaultSegmentProfile = hvaclib.default_segment_profile_for_library(
                getattr(obj, "DefaultLibraryId", "")
            )

        if getattr(obj, "DefaultSegmentAutoType", None) is None:
            obj.DefaultSegmentAutoType = True
    
    @staticmethod
    def getDefaultLibraryId(net):
        lib_id = getattr(net, "DefaultLibraryId", "")
        if lib_id:
            return lib_id

        lib = hvaclib.get_active_hvac_library()
        if lib:
            return lib.id
        return ""

    @staticmethod
    def getDefaultLibrary(net):
        lib_id = DuctNetwork.getDefaultLibraryId(net)
        if not lib_id:
            return None
        reg = hvaclib.get_hvac_library_registry()
        return reg.get_library(lib_id)

    @staticmethod
    def getDefaultSegmentProfile(net):
        profile = getattr(net, "DefaultSegmentProfile", "")
        if profile:
            return profile

        lib_id = DuctNetwork.getDefaultLibraryId(net)
        return hvaclib.default_segment_profile_for_library(lib_id)

    @staticmethod
    def getDefaultSegmentAutoType(net):
        return bool(getattr(net, "DefaultSegmentAutoType", True))
    
    ## Library defaults management
    
    @staticmethod
    def resolveSegmentTypeDefaults(net, segment_obj=None, profile="rectangular"):
        """
        Resolve library/type defaults for a segment.

        Priority:
        object manual override > object auto/default state > network defaults > global fallback
        """
        library_id = DuctNetwork.getDefaultLibraryId(net)
        auto_type = bool(getattr(net, "DefaultSegmentAutoType", True))
        default_type_id = getattr(net, "DefaultSegmentTypeId", "") or ""

        if segment_obj is not None:
            if getattr(segment_obj, "LibraryId", ""):
                library_id = segment_obj.LibraryId
            if hasattr(segment_obj, "AutoType"):
                auto_type = bool(segment_obj.AutoType)
            if getattr(segment_obj, "TypeId", ""):
                default_type_id = segment_obj.TypeId

        suggested_type_id = DuctSegment.defaultTypeIdForProfile(profile)

        if auto_type:
            effective_type_id = suggested_type_id
        else:
            effective_type_id = default_type_id or suggested_type_id

        return {
            "library_id": library_id,
            "auto_type": auto_type,
            "type_id": effective_type_id,
            "suggested_type_id": suggested_type_id,
        }

    @staticmethod
    def resolveJunctionTypeDefaults(net, family="", junction_obj=None):
        """
        Resolve library/type defaults for a junction.

        Priority:
        object manual override > object auto/default state > network defaults > global fallback
        """
        library_id = DuctNetwork.getDefaultLibraryId(net)
        auto_type = bool(getattr(net, "DefaultJunctionAutoType", True))
        default_type_id = getattr(net, "DefaultJunctionTypeId", "") or ""

        if junction_obj is not None:
            if getattr(junction_obj, "LibraryId", ""):
                library_id = junction_obj.LibraryId
            if hasattr(junction_obj, "AutoType"):
                auto_type = bool(junction_obj.AutoType)
            if getattr(junction_obj, "TypeId", ""):
                default_type_id = junction_obj.TypeId

        suggested_type_id = hvaclib.default_junction_type_id(family)

        if auto_type:
            effective_type_id = suggested_type_id
        else:
            effective_type_id = default_type_id or suggested_type_id

        return {
            "library_id": library_id,
            "auto_type": auto_type,
            "type_id": effective_type_id,
            "suggested_type_id": suggested_type_id,
        }

    @staticmethod
    def applyNetworkTypeDefaults(net, library_id="", segment_profile="", default_segment_auto=True):
        """
        Apply network-level default type settings.
        """
        if net is None:
            return

        changed = False

        if library_id and getattr(net, "DefaultLibraryId", "") != library_id:
            net.DefaultLibraryId = library_id
            changed = True

        effective_library_id = library_id or getattr(net, "DefaultLibraryId", "")

        valid_profiles = hvaclib.segment_profiles_for_library(effective_library_id)

        if segment_profile and segment_profile in valid_profiles:
            if getattr(net, "DefaultSegmentProfile", "") != segment_profile:
                net.DefaultSegmentProfile = segment_profile
                changed = True
        else:
            fallback_profile = valid_profiles[0] if valid_profiles else ""
            if getattr(net, "DefaultSegmentProfile", "") not in valid_profiles:
                if getattr(net, "DefaultSegmentProfile", "") != fallback_profile:
                    net.DefaultSegmentProfile = fallback_profile
                    changed = True

        if bool(getattr(net, "DefaultSegmentAutoType", True)) != bool(default_segment_auto):
            net.DefaultSegmentAutoType = bool(default_segment_auto)
            changed = True

        if changed and net.Document:
            try:
                net.touch()
            except Exception:
                pass
            net.Document.recompute()

    @staticmethod
    def resetObjectsToNetworkDefaults(objects):
        """
        Reset selected segment/junction objects to their owner network defaults.
        """
        doc = FreeCAD.ActiveDocument
        if doc is None:
            return

        changed = False

        for obj in objects or []:
            if obj is None:
                continue

            net = DuctNetwork.getOwnerNetwork(obj)
            if net is None:
                continue

            default_lib = DuctNetwork.getDefaultLibrary(net)
            if default_lib is None:
                continue

            proxy = getattr(obj, "Proxy", None)

            if DuctSegment.isDuctSegment(obj):
                default_profile = DuctNetwork.getDefaultSegmentProfile(net)
                if not default_profile:
                    default_profile = hvaclib.default_segment_profile_for_library(default_lib.id)

                default_type_id = hvaclib.default_segment_type_id_for_profile(
                    default_lib.id,
                    default_profile,
                )

                if hasattr(obj, "LibraryId") and obj.LibraryId != default_lib.id:
                    obj.LibraryId = default_lib.id
                    changed = True

                if hasattr(obj, "Profile") and obj.Profile != default_profile:
                    obj.Profile = default_profile
                    changed = True

                if hasattr(obj, "AutoType") and obj.AutoType is not True:
                    obj.AutoType = True
                    changed = True

                if hasattr(obj, "TypeId") and obj.TypeId != default_type_id:
                    obj.TypeId = default_type_id
                    changed = True

                analysis_json = json.dumps(
                    {
                        "profile": default_profile,
                        "default_type_id": default_type_id,
                        "start_node": int(getattr(obj, "StartNode", 0)),
                        "end_node": int(getattr(obj, "EndNode", 0)),
                    }
                )
                if hasattr(obj, "AnalysisJson") and obj.AnalysisJson != analysis_json:
                    obj.AnalysisJson = analysis_json
                    changed = True

            elif DuctJunction.isDuctJunction(obj):
                family = getattr(obj, "Family", "")
                default_type_id = hvaclib.default_junction_type_id(family)

                if hasattr(obj, "LibraryId") and obj.LibraryId != default_lib.id:
                    obj.LibraryId = default_lib.id
                    changed = True

                if hasattr(obj, "AutoType") and obj.AutoType is not True:
                    obj.AutoType = True
                    changed = True

                if hasattr(obj, "TypeId") and obj.TypeId != default_type_id:
                    obj.TypeId = default_type_id
                    changed = True

            if proxy and hasattr(proxy, "applyTypeSchema"):
                try:
                    changed = proxy.applyTypeSchema(obj) or changed
                except Exception:
                    pass

            try:
                obj.touch()
            except Exception:
                pass

        if changed:
            doc.recompute()
    
    ## Object Management
    
    @staticmethod
    def createObject(name):
        net = FreeCAD.ActiveDocument.addObject('App::DocumentObjectGroupPython', name)
        DuctNetwork(net)
        DuctNetworkViewProvider(net.ViewObject)
        return net

    @staticmethod
    def createSketchInteractive(obj):
        """
        Open the standard FreeCAD sketch creation panel and,
        after the sketch is created, move it under obj.Base.
        """
        if not obj or not DuctNetwork.isDuctNetwork(obj):
            return
        if FreeCAD.ActiveDocument is None or Gui.ActiveDocument is None:
            return

        # Make this network active in the 3D view context
        DuctNetwork.setActive(obj)
        
        # Install observer before running the command
        def callback(obj, sketch):
            if sketch:
                DuctNetwork.addBaseObject(obj, sketch)
                DuctNetwork.showAllJunctionGeometry(obj)
                
        obs = Observer.NewSketchObserver(obj, callback)
        FreeCAD.addDocumentObserver(obs)
        
        # Launch the built-in sketch creation command
        DuctNetwork.hideAllJunctionGeometry(obj)
        Gui.runCommand("Sketcher_NewSketch")

    @staticmethod
    def createDraftLineInteractive(obj):
        """
        Open the standard Draft Line command and, after the user exits the tool,
        move all newly created Draft line objects under obj.Base.
        """
        if not obj or not DuctNetwork.isDuctNetwork(obj):
            return
        if FreeCAD.ActiveDocument is None or Gui.ActiveDocument is None:
            return

        # Make this network active in the 3D view context
        DuctNetwork.setActive(obj)
        
        # Install observer before running the command
        def callback(net, objs):
            for obj in objs:
                if hvaclib.obj_is_wire(obj):
                    DuctNetwork.addBaseObject(net, obj)
            DuctNetwork.showAllJunctionGeometry(obj)
                
        obs = Observer.NewDraftLineObserver(obj, callback)
        FreeCAD.addDocumentObserver(obs)
        
        # Launch the built-in Draft line creation command
        DuctNetwork.hideAllJunctionGeometry(obj)
        Gui.activateWorkbench("DraftWorkbench")
        Gui.runCommand("Draft_Line")

    @staticmethod
    def addBaseObject(net, obj):
        if not net or not obj:
            return False
        if not DuctNetwork.isDuctNetwork(net):
            return False
        if not hasattr(net, "Base") or net.Base is None:
            return False
        if not hasattr(obj, "Document") or obj.Document is None:
            return False
        if net.Document != obj.Document:
            return False
        if not (hvaclib.obj_is_sketch(obj) or hvaclib.obj_is_wire(obj)):
            return False
        if obj in net.Base.OutList:
            return False
        
        net.Base.addObject(obj)
        if getattr(net, "Proxy", None):
            net.Proxy.requestSync(net)
        net.Document.recompute()
        return True

    @staticmethod
    def removeBaseObject(net, obj):
        if not net or not obj:
            return False
        if not DuctNetwork.isDuctNetwork(net):
            return False
        if not hasattr(net, "Base") or net.Base is None:
            return False
        if net.Document != getattr(obj, "Document", None):
            return False
        if obj not in net.Base.OutList:
            return False
    
        net.Base.removeObject(obj)
        if getattr(net, "Proxy", None):
            net.Proxy.requestSync(net)
        net.Document.recompute()
        return True

    @staticmethod
    def removeGeometryObject(net, obj):
        """Remove a derived geometry object from the Geometry folder and document."""
        if not net or not obj or not DuctNetwork.isDuctNetwork(net):
            return False
        if getattr(obj, "Document", None) != net.Document:
            return False
        if (DuctSegment.isDuctSegment(obj) or DuctJunction.isDuctJunction(obj)) and getattr(obj, "Proxy", None):
            obj.Proxy._allow_delete = True
        if hasattr(net, "Geometry") and net.Geometry and obj in net.Geometry.OutList:
            net.Geometry.removeObject(obj)
        net.Document.removeObject(obj.Name)
        return True

    @staticmethod
    def collectSegmentObjects(net):
        segments = {}
        geometry = getattr(net, "Geometry", None)
        if geometry is None:
            return segments
        for child in list(geometry.OutList):
            if not DuctSegment.isDuctSegment(child):
                continue
            key = getattr(child, "SegmentKey", "")
            if not key and getattr(child, "SourceObjectName", ""):
                key = DuctSegment.makeKey(child.SourceObjectName, child.SourceIndex)
            if key:
                segments[key] = child
        return segments
        
    @staticmethod
    def collectJunctionObjects(net):
        junctions = {}
        geometry = getattr(net, "Geometry", None)
        if geometry is None:
            return junctions
        for child in list(geometry.OutList):
            if not DuctJunction.isDuctJunction(child):
                continue
            key = getattr(child, "NodeKey", "")
            if key:
                junctions[key] = child
        return junctions

    @staticmethod
    def setActive(obj):
        """Set this DuctNetwork as the active container in the 3D view."""
        Gui.ActiveDocument.ActiveView.setActiveObject(DuctNetwork.CONTEXT_KEY, obj)

    @staticmethod
    def getActive(doc=None):
        """Get the active DuctNetwork container from the 3D view."""
        if not FreeCAD.GuiUp:
            return None
        if doc is None:
            doc = FreeCAD.ActiveDocument
        if doc is None or Gui.ActiveDocument is None:
            return None
        return Gui.ActiveDocument.ActiveView.getActiveObject(DuctNetwork.CONTEXT_KEY)
        
    @staticmethod
    def _setGeometryVisibilityDeferred(obj, visible):
        if not FreeCAD.GuiUp:
            return

        def apply():
            try:
                if obj is None or getattr(obj, "Document", None) is None:
                    return
                vobj = getattr(obj, "ViewObject", None)
                if vobj is None:
                    return
                vobj.Visibility = bool(visible)
            except Exception:
                pass

        QtCore.QTimer.singleShot(0, apply)

    def showAllGeometry(self, net):
        geometry = getattr(net, "Geometry", None)
        if geometry is None:
            return

        if getattr(geometry, "ViewObject", None):
            try:
                geometry.ViewObject.Visibility = True
            except Exception:
                pass

        for obj in list(geometry.OutList):
            if DuctSegment.isDuctSegment(obj) or DuctJunction.isDuctJunction(obj):
                DuctNetwork._setGeometryVisibilityDeferred(obj, True)
                
    def _segmentFromBaseObject(self, seg, base_obj):
        return (
            seg is not None
            and base_obj is not None
            and DuctSegment.isDuctSegment(seg)
            and getattr(seg, "SourceObjectName", "") == base_obj.Name
        )
    
    def hideGeometryForBaseObject(self, net, base_obj):
        geometry = getattr(net, "Geometry", None)
        if geometry is None or base_obj is None:
            return
        for seg in list(geometry.OutList):
            if self._segmentFromBaseObject(seg, base_obj):
                DuctNetwork._setGeometryVisibilityDeferred(seg, False)
                
    @staticmethod
    def hideAllJunctionGeometry(net):
        geometry = getattr(net, "Geometry", None)
        if geometry is None:
            return

        for obj in list(geometry.OutList):
            if DuctNetwork._isJunctionObject(obj):
                DuctNetwork._setGeometryVisibilityDeferred(obj, False)

    @staticmethod
    def showAllJunctionGeometry(net):
        geometry = getattr(net, "Geometry", None)
        if geometry is None:
            return

        for obj in list(geometry.OutList):
            if DuctNetwork._isJunctionObject(obj):
                DuctNetwork._setGeometryVisibilityDeferred(obj, True)
    
    def showGeometryForBaseObject(self, net, base_obj):
        geometry = getattr(net, "Geometry", None)
        if geometry is None or base_obj is None:
            return
        for seg in list(geometry.OutList):
            if self._segmentFromBaseObject(seg, base_obj):
                DuctNetwork._setGeometryVisibilityDeferred(seg, True)
    
    def setBaseObjectEditing(self, net, base_obj, editing):
        if net is None or base_obj is None:
            return
        if editing:
            self._hidden_source_names.add(base_obj.Name)
            self.hideGeometryForBaseObject(net, base_obj)
            self.hideAllJunctionGeometry(net)
        else:
            self._hidden_source_names.discard(base_obj.Name)
            self.showGeometryForBaseObject(net, base_obj)
            self.showAllJunctionGeometry(net)

    @staticmethod
    def isDuctNetwork(obj):
        """Test whether obj is a DuctNetwork FeaturePython object."""
        return bool(obj) and hasattr(obj, "Proxy") and isinstance(obj.Proxy, DuctNetwork)
        
    @staticmethod
    def isBaseObject(obj):
        if obj is None:
            return False
        if not (hvaclib.obj_is_sketch(obj) or hvaclib.obj_is_wire(obj)):
            return False
            
        for net in hvaclib.allHVACNetworks(obj.Document):
            base = getattr(net, "Base", None)
            if base and obj in base.OutList:
                return True
        return False
        
    @staticmethod
    def isGeometryObject(obj):
        return (
            bool(obj)
            and hasattr(obj, "Proxy")
            and (
                isinstance(obj.Proxy, DuctSegment)
                or isinstance(obj.Proxy, DuctJunction)
            )
        )
        
    @staticmethod
    def _isJunctionObject(obj):
        try:
            return DuctJunction.isDuctJunction(obj)
        except Exception:
            return False
        
    @staticmethod
    def getOwnerNetwork(obj):
        """Return the owning duct network document object for an internal object."""
        if DuctNetwork.isGeometryObject(obj):
            owner_name = getattr(obj, "OwnerNetworkName", "")
            doc = getattr(obj, "Document", None)
            if owner_name and doc:
                return doc.getObject(owner_name)
            return None
        elif DuctNetwork.isBaseObject(obj):
            for net in hvaclib.allHVACNetworks(obj.Document):
                base = getattr(net, "Base", None)
                if base and obj in base.OutList:
                    return net
        return None
        
    @staticmethod
    def getOwnerBaseObject(obj):
        """Return the base object for a given geometry object."""
        if DuctNetwork.isGeometryObject(obj):
            owner_name = getattr(obj, "SourceObjectName", "")
            doc = getattr(obj, "Document", None)
            if owner_name and doc:
                return doc.getObject(owner_name)
        return None
    
    # Functions for syncing object data with the network parser

    def syncSegments(self, net, parser, initial_sync=False):
        """
        Synchronize derived DuctSegment objects with the base geometry.

        Segment profile and default type come from network defaults and library
        definitions. SectionShape is no longer used.
        """
        doc = net.Document
        geometry = getattr(net, "Geometry", None)
        if doc is None or geometry is None:
            return False

        default_lib = self.getDefaultLibrary(net)
        if default_lib is None:
            return False

        default_segment_auto = self.getDefaultSegmentAutoType(net)
        default_segment_profile = self.getDefaultSegmentProfile(net)
        if not default_segment_profile:
            default_segment_profile = hvaclib.default_segment_profile_for_library(default_lib.id)

        changed = False
        existing_segments = self.collectSegmentObjects(net)
        live_objs = set()

        for edge_ref in parser.edges():
            key = edge_ref.tag

            source_obj = doc.getObject(edge_ref.obj_name)
            if source_obj is None:
                continue

            if initial_sync:
                segment_obj = None
                matched_old_key = None
                for old_key, seg in existing_segments.items():
                    if seg.SourceObjectName == source_obj.Name and seg.SourceIndex == edge_ref.local_index:
                        segment_obj = seg
                        matched_old_key = old_key
                        break

                if matched_old_key is not None and matched_old_key != key:
                    existing_segments.pop(matched_old_key, None)
                    existing_segments[key] = segment_obj
            else:
                segment_obj = existing_segments.get(key)

            if segment_obj is None:
                segment_obj = DuctSegment.create(
                    doc,
                    "{}_Seg_{}_{}".format(net.Name, source_obj.Name, edge_ref.local_index),
                    owner=net,
                    key=key,
                    source_obj=source_obj,
                    source_index=edge_ref.local_index,
                )

                if hasattr(segment_obj, "LibraryId") and default_lib:
                    segment_obj.LibraryId = default_lib.id
                if hasattr(segment_obj, "Profile"):
                    segment_obj.Profile = default_segment_profile
                if hasattr(segment_obj, "AutoType"):
                    segment_obj.AutoType = default_segment_auto

                changed = True

                if source_obj.Name in self._hidden_source_names:
                    DuctNetwork._setGeometryVisibilityDeferred(segment_obj, False)
                else:
                    DuctNetwork._setGeometryVisibilityDeferred(segment_obj, True)

            if segment_obj not in geometry.OutList:
                geometry.addObject(segment_obj)
                changed = True

            live_objs.add(segment_obj)

            start_node, end_node = parser.edge_nodes(edge_ref)
            start_point, end_point = parser.edge_line(edge_ref)

            profile = default_segment_profile
            default_type_id = hvaclib.default_segment_type_id_for_profile(
                default_lib.id,
                profile,
            )

            effective_type_id = getattr(segment_obj, "TypeId", "")
            if not effective_type_id or getattr(segment_obj, "AutoType", True):
                effective_type_id = default_type_id

            analysis_json = json.dumps(
                {
                    "profile": profile,
                    "default_type_id": default_type_id,
                    "start_node": int(start_node),
                    "end_node": int(end_node),
                }
            )

            meta_changed = segment_obj.Proxy.updateMetadata(
                segment_obj,
                owner=net,
                key=key,
                source_obj=source_obj,
                source_index=edge_ref.local_index,
                start_node=start_node,
                end_node=end_node,
                start_point=start_point,
                end_point=end_point,
                family="straight_segment",
                type_id=effective_type_id,
                library_id=default_lib.id,
                profile=profile,
                analysis_json=analysis_json,
            )
            changed = changed or meta_changed

            schema_changed = segment_obj.Proxy.applyTypeSchema(segment_obj)
            changed = changed or schema_changed

            cached_params = self._runtime_param_cache.pop(key, None)
            if cached_params:
                restored = self._restoreSegmentUserParams(segment_obj, cached_params)
                changed = changed or restored

            new_label = DuctSegment.labelFor(source_obj, edge_ref.local_index)
            if segment_obj.Label != new_label:
                segment_obj.Label = new_label
                changed = True

        for segment_obj in list(existing_segments.values()):
            if segment_obj not in live_objs:
                seg_key = getattr(segment_obj, "SegmentKey", "")
                if seg_key:
                    self._runtime_param_cache[seg_key] = self._segmentUserParams(segment_obj)
                self.removeGeometryObject(net, segment_obj)
                changed = True

        return changed
            
    def syncJunctions(self, net, parser):
        """
        Synchronize derived DuctJunction objects with parser nodes.

        Junction family and default type are inferred from topology.
        Geometry generation is delegated to the active HVAC library.
        """
        doc = net.Document
        geometry = getattr(net, "Geometry", None)
        if doc is None or geometry is None:
            return False

        default_lib = self.getDefaultLibrary(net)
        if default_lib is None:
            return False

        changed = False
        existing_junctions = self.collectJunctionObjects(net)
        live_objs = set()

        for node_id in parser.nodes():
            analysis = parser.node_analysis(node_id)
            degree = int(analysis.get("degree", 0))
            if degree <= 0:
                continue

            family = hvaclib.classify_junction_family(analysis)
            default_type_id = hvaclib.default_junction_type_id(family)

            point = analysis["point"]
            node_key_tuple = analysis["node_key"]
            node_key = DuctJunction.makeKey(node_key_tuple)

            connected_edge_keys = [
                DuctSegment.makeKey(edge_ref.obj_name, edge_ref.local_index)
                for edge_ref in analysis["edge_refs"]
            ]

            analysis_json = json.dumps(
                {
                    "degree": degree,
                    "family": family,
                    "collinear_pairs": [
                        [
                            DuctSegment.makeKey(a.obj_name, a.local_index),
                            DuctSegment.makeKey(b.obj_name, b.local_index),
                            float(ang),
                        ]
                        for a, b, ang in analysis.get("collinear_pairs", [])
                    ],
                    "orthogonal_pairs": [
                        [
                            DuctSegment.makeKey(a.obj_name, a.local_index),
                            DuctSegment.makeKey(b.obj_name, b.local_index),
                            float(ang),
                        ]
                        for a, b, ang in analysis.get("orthogonal_pairs", [])
                    ],
                }
            )

            junction_obj = existing_junctions.get(node_key)

            if junction_obj is None:
                junction_obj = DuctJunction.create(
                    doc,
                    "{}_Junc_{}".format(net.Name, node_id),
                    owner=net,
                    node_id=node_id,
                    node_key=node_key,
                    node_kind=family,
                    center_point=point,
                    degree=degree,
                )

                if hasattr(junction_obj, "LibraryId") and default_lib:
                    junction_obj.LibraryId = default_lib.id

                changed = True
                if self._hidden_source_names:
                    DuctNetwork._setGeometryVisibilityDeferred(junction_obj, False)
                else:
                    DuctNetwork._setGeometryVisibilityDeferred(junction_obj, True)

            if junction_obj not in geometry.OutList:
                geometry.addObject(junction_obj)
                changed = True

            live_objs.add(junction_obj)

            effective_type_id = getattr(junction_obj, "TypeId", "")
            if not effective_type_id or getattr(junction_obj, "AutoType", True):
                effective_type_id = default_type_id

            meta_changed = junction_obj.Proxy.updateMetadata(
                junction_obj,
                owner=net,
                node_id=node_id,
                node_key=node_key,
                node_kind=family,
                center_point=point,
                degree=degree,
                family=family,
                type_id=effective_type_id,
                library_id=default_lib.id,
                connected_edge_keys=connected_edge_keys,
                analysis_json=analysis_json,
            )
            changed = changed or meta_changed

            schema_changed = junction_obj.Proxy.applyTypeSchema(junction_obj)
            changed = changed or schema_changed

            new_label = DuctJunction.labelFor(family, node_id)
            if junction_obj.Label != new_label:
                junction_obj.Label = new_label
                changed = True

        for junction_obj in list(existing_junctions.values()):
            if junction_obj not in live_objs:
                self.removeGeometryObject(net, junction_obj)
                changed = True

        return changed
                
    def requestSync(self, obj, initial_sync=None, reason="unknown"):
        if initial_sync is not None:
            self._initial_sync = bool(initial_sync)
        
        if self._sync_scheduled:
            self._sync_reason = reason
            return
        
        self._sync_scheduled = True
        self._sync_reason = reason
        QtCore.QTimer.singleShot(0, lambda o=obj: self._runDeferredSync(o))
    
    def _runDeferredSync(self, obj):
        self._sync_scheduled = False
        self._sync_reason = None

        if obj is None or obj.Document is None:
            return
        if self._sync_in_progress:
            return
    
        base_folder = getattr(obj, "Base", None)
        geometry_folder = getattr(obj, "Geometry", None)
        if base_folder is None or geometry_folder is None:
            return
    
        self._sync_in_progress = True
        try:
            parser = hvaclib.DuctNetworkParser(list(base_folder.OutList))
            changed_segments = self.syncSegments(obj, parser, initial_sync=self._initial_sync)
            changed_junctions = self.syncJunctions(obj, parser)
            changed = changed_segments or changed_junctions
            self._initial_sync = False
            if changed:
                obj.Document.recompute()
        except Exception as err:
            FreeCAD.Console.PrintError(
                "HVAC - Failed to update segments for '{}': {}\n".format(obj.Label, err)
            )
        finally:
            self._sync_in_progress = False
    
    @staticmethod
    def _segmentUserParams(obj):
        return {
            "SectionShape": str(getattr(obj, "SectionShape", "")),
            "Diameter": float(getattr(obj, "Diameter", 0.0)),
            "Width": float(getattr(obj, "Width", 0.0)),
            "Height": float(getattr(obj, "Height", 0.0)),
            "InsulationThickness": float(getattr(obj, "InsulationThickness", 0.0)),
            "Roughness": float(getattr(obj, "Roughness", 0.0)),
            "FlowRate": float(getattr(obj, "FlowRate", 0.0)),
            "Velocity": float(getattr(obj, "Velocity", 0.0)),
        }
    
    @staticmethod
    def applyTypeSelection(objects, library_id="", type_id="", auto_type=True):
        """
        Apply library/type selection to selected segment/junction objects.
        """
        doc = FreeCAD.ActiveDocument
        if doc is None:
            return

        reg = hvaclib.get_hvac_library_registry()
        changed = False

        for obj in objects or []:
            if obj is None:
                continue

            if hasattr(obj, "LibraryId") and library_id:
                if obj.LibraryId != library_id:
                    obj.LibraryId = library_id
                    changed = True

            if hasattr(obj, "AutoType"):
                if bool(obj.AutoType) != bool(auto_type):
                    obj.AutoType = bool(auto_type)
                    changed = True

            if not auto_type and type_id and hasattr(obj, "TypeId"):
                if obj.TypeId != type_id:
                    obj.TypeId = type_id
                    changed = True

                # Keep Profile aligned with the selected segment type
                if hvaclib.isDuctSegment(obj):
                    tdef = reg.resolve_type(obj.LibraryId, type_id)
                    if tdef and getattr(tdef, "profiles", None):
                        new_profile = tdef.profiles[0]
                        if hasattr(obj, "Profile") and obj.Profile != new_profile:
                            obj.Profile = new_profile
                            changed = True

            proxy = getattr(obj, "Proxy", None)
            if proxy and hasattr(proxy, "applyTypeSchema"):
                try:
                    changed = proxy.applyTypeSchema(obj) or changed
                except Exception:
                    pass

            try:
                obj.touch()
            except Exception:
                pass

        if changed:
            doc.recompute()
    
    @staticmethod
    def _restoreSegmentUserParams(obj, params):
        if not isinstance(params, dict):
            return False
    
        changed = False
    
        def set_if_needed(prop, value):
            nonlocal changed
            try:
                if getattr(obj, prop) != value:
                    setattr(obj, prop, value)
                    changed = True
            except Exception:
                pass
    
        if "SectionShape" in params:
            set_if_needed("SectionShape", params["SectionShape"])
        if "Diameter" in params:
            set_if_needed("Diameter", params["Diameter"])
        if "Width" in params:
            set_if_needed("Width", params["Width"])
        if "Height" in params:
            set_if_needed("Height", params["Height"])
        if "InsulationThickness" in params:
            set_if_needed("InsulationThickness", params["InsulationThickness"])
        if "Roughness" in params:
            set_if_needed("Roughness", params["Roughness"])
        if "FlowRate" in params:
            set_if_needed("FlowRate", params["FlowRate"])
        if "Velocity" in params:
            set_if_needed("Velocity", params["Velocity"])
    
        return changed


class DuctNetworkViewProvider:
    """A View Provider for the HVAC duct network object"""

    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object

    def __getstate__(self):
        # Create a copy of the state and remove the non-serializable object
        state = self.__dict__.copy()
        if 'Object' in state:
            del state['Object']
        return state

    def __setstate__(self, state):
        # Restore the state
        self.__dict__.update(state)
        # self.Object will be restored later in attach()

    def getIcon(self):
        return hvaclib.get_icon_path("DuctsIcon.svg")

    def setEdit(self, vobj, mode):
        panel = TaskPanel.TaskPanelEditDuctNetwork(vobj.Object,
            callback_add_base_object = DuctNetwork.addBaseObject,
            callback_remove_base_object = DuctNetwork.removeBaseObject
        )
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

    def claimChildren(self):
        obj = self.Object
        kids = []
        try:
            if obj.Base: kids.append(obj.Base)
            if obj.Geometry: kids.append(obj.Geometry)
        except Exception:
            pass
        return kids

    def canDropObjects(self):
        # Returning False prevents users from dragging items into this group via the Tree View
        return False

    def canDragObjects(self):
        # Prevents users from dragging the managed folders OUT of the group
        return False
        
    def onDelete(self, vobj, subelements):
        net = vobj.Object
        delete_duct_networks([net], remove_internal_only=True)
        return True


#=================================================
# General functions
#=================================================


def create_new_duct_network(name="DuctNetwork", set_active=True):
    """Create new duct network"""
    # Create new duct netowork and create default folders
    net = DuctNetwork.createObject(name)
    print("HVAC - New DuctNetwork created")
    if set_active:
        # Set as active network and enable edit mode
        activate_duct_network(net, set_edit=False)

def activate_duct_network(net, set_edit=False):
    DuctNetwork.setActive(net)
    # Set network to edit mode
    if set_edit:
        Gui.ActiveDocument.setEdit(net.Name)
    else:
      pass
    hvaclib.refreshState()

def modify_duct_network(net):
    """Modify the selected HVAC duct network object"""
    # Set as active network and enable edit mode
    activate_duct_network(net, set_edit=True)
    print("HVAC - Edit DuctNetwork completed")

def delete_duct_networks(nets, remove_internal_only=False):
    """Delete the selected HVAC duct network object"""
    doc = FreeCAD.ActiveDocument
    for net in nets:
        if net.Document != doc:
            continue
            
        if hasattr(net, "Proxy") and net.Proxy:
            net.Proxy._allow_internal_delete = True
            
        if hasattr(net, "Geometry") and net.Geometry:
            for obj in list(net.Geometry.OutList):
                DuctNetwork.removeGeometryObject(net, obj)
            doc.removeObject(net.Geometry.Name)
            
        if hasattr(net, "Base") and net.Base:
            for obj in list(net.Base.OutList):
                net.Base.removeObject(obj)
            doc.removeObject(net.Base.Name)
            
        if not remove_internal_only:
            doc.removeObject(net.Name)
    hvaclib.refreshState()
    print("HVAC - Deleted selected {} DuctNetwork(s)".format(len(nets)))
