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

"""
Implements DuctComponent: one physical fitting inside a DuctJunction's
component chain (e.g. a reducer, an elbow, an inline damper). A DuctJunction
is a purely logical/network node; each of its DuctComponent children owns
its own library type selection, type-specific properties, and generated
Shape. See DuctJunction.composeComponents() for how a junction assembles and
positions its children's local ports each sync.
"""

import json
import traceback

import FreeCAD
import FreeCADGui as Gui
import Part
from PySide import QtCore, QtWidgets
from PySide.QtCore import QT_TRANSLATE_NOOP

translate = FreeCAD.Qt.translate

from ..library.library_api import HVACLibraryAPI
from ..utils import hvaclib
from . import Construction as _construction
from . import (
    Equipment,
    _component_appearance,
    _component_results,
    _construction_schema,
    _custom_fitting,
    _custom_loss,
    _geometry_apply,
    _port_properties,
    _type_schema,
)


class DuctComponent:
    """One physical fitting belonging to a DuctJunction's ordered component chain."""

    TYPE = "DuctComponent"

    def __init__(
        self,
        obj,
        parent_junction=None,
        role="Primary",
        attached_edge_key="",
        port_sequence=0,
        library_id="",
        type_id="",
    ):
        obj.Proxy = self
        self.Object = obj
        self._allow_delete = False
        self._mirroring_design_flow_rate = False
        self._mirroring_flow_boundary = False
        self.setProperties(obj)
        self.updateMetadata(
            parent_junction=parent_junction,
            role=role,
            attached_edge_key=attached_edge_key,
            port_sequence=port_sequence,
            library_id=library_id,
            type_id=type_id,
        )

    def onDocumentRestored(self, obj):
        obj.Proxy = self
        self.Object = obj
        self._allow_delete = False
        self._mirroring_design_flow_rate = False
        self._mirroring_flow_boundary = False
        self.setProperties(obj)
        _construction_schema.normalize_material_properties(obj)

    def dumps(self):
        return None

    def loads(self, state):
        pass

    def execute(self, obj):
        # Values this rebuild writes back (computed sizes, narrowed choices)
        # are not user edits: onChanged must not re-sync the network for them.
        self._executing = True
        try:
            self._execute(obj)
        finally:
            self._executing = False

    def _execute(self, obj):
        # The junction composer (DuctJunction.composeComponents) is
        # responsible for working out this component's local inlet/outlet
        # ports and writing them into LocalPortsJson each sync -- execute()
        # only ever reads that, it never resolves its own parent or
        # recomputes placement, so it stays decoupled from FreeCAD's
        # automatic recompute ordering (same reasoning as DuctJunction/
        # DuctSegment not using Placement/Link-based dependencies).
        self._syncFlowBoundary(obj)

        library_id = getattr(obj, "LibraryId", "")
        type_id = getattr(obj, "TypeId", "")
        if not library_id or not type_id:
            return

        raw_ports = getattr(obj, "LocalPortsJson", "") or "[]"
        try:
            ports = json.loads(raw_ports)
        except Exception:
            return

        # Keep CustomLossCoefficients holding one K per applicable port
        # every time the port list itself changes -- see the property's own
        # comment in setProperties() for why this can't wait for a user edit.
        self._syncCustomLossCoefficients(obj, ports)

        # The 4 scalar Calc* properties can only show one unambiguous
        # airflow/loss path -- hide them once this Primary has grown past 2
        # ports (a tee/wye/cross/manifold), since the authoritative data at
        # that point is CalcPortResultsJson instead (see
        # core/_component_results.py's own module docstring).
        self._syncCalcPropertiesEditorMode(obj)

        # A Primary component standing in for a whole non-through junction
        # (a tee, cross, multiport, or end/terminal device) carries however
        # many real ports that node actually has -- 1, 3, 4, ... -- not
        # always 2 (only a through/2-port chain's own components are always
        # exactly 2-port). The type-def's own degree constraint validates
        # the count; this only guards against a not-yet-composed component.
        if not ports:
            return

        # A user-modelled fitting replaces the library geometry (ROADMAP 6.3);
        # the library type still provides the loss.
        if _custom_fitting.is_custom(obj) and getattr(obj, "ComponentRole", "") == "Primary":
            self._executeCustom(obj, ports)
            return
        if getattr(obj, "CustomLinkName", ""):
            _custom_fitting.remove_link(obj)

        try:
            reg = hvaclib.HVACLibraryService.get_hvac_library_registry()
            type_def = reg.resolve_type(library_id, type_id)
            if type_def is None:
                raise ValueError("Unknown component type '{}' in library '{}'".format(type_id, library_id))

            # Per-port properties hold one value per port: line them up
            # with this sync's ports before reading any of them.
            _port_properties.sync_port_property_lists(obj, type_def, [p.get("edge_key") for p in ports])

            params = reg.resolve_params(type_def, obj=obj)
            is_primary = getattr(obj, "ComponentRole", "") == "Primary"

            context = {
                "obj": obj,
                "center_point": HVACLibraryAPI.average_point([p["position"] for p in ports]),
                "properties": params,
                "connected_ports": ports,
                # Full node topology analysis (collinear_pairs,
                # orthogonal_pairs, edge_angles, edge_eccentricities,
                # is_coplanar, ...) -- see JunctionAnalysis in
                # NetworkParser.py. Real structural data about the parent
                # junction, not the component's own, but harmless/correct
                # to pass to every component (e.g. build_tee needs
                # collinear_pairs to identify which two ports form the
                # straight run).
                "analysis": self._parentAnalysis(obj),
                # Family has no meaning of its own on a component -- only a
                # Primary's family-driven dispatch (e.g. through_generic's
                # elbow-vs-transition switch) needs it, so read it straight
                # off the parent junction rather than duplicating it here.
                "family": self._parentAttr(obj, "Family") if is_primary else "",
                # Topology is likewise a junction-level fact for the Primary
                # -- validate_context checks it against the type-def's
                # declared topology (e.g. "branch" for a tee). An Inline
                # component is always a physically two-port device, no
                # matter what the parent junction's real topology is (a
                # damper on a tee's branch leg must still validate as
                # "through", not "branch"), so it always gets "through".
                "topology": self._parentAttr(obj, "Topology", "through") if is_primary else "through",
                "type_id": type_id,
                "library_id": library_id,
            }
            # An end on an equipment port: the port's own opening (the connection reaches it).
            equipment_port = Equipment.port_context(obj) if is_primary else None
            if equipment_port is not None:
                context["equipment_port"] = equipment_port

            result = reg.build_geometry(library_id, type_def, context)
            _geometry_apply.apply_geometry_result(obj, result)
            lengths = result.connection_lengths

            lengths_json = json.dumps(lengths)
            if getattr(obj, "ConnectionLengthsJson", "") != lengths_json:
                obj.ConnectionLengthsJson = lengths_json

            # Reactive, read-only "as-built" properties a geometry backend
            # may report alongside its shape -- same convention as
            # DuctSegment.execute().
            _geometry_apply.apply_computed_properties(obj, type_def, result)
            # Drop-downs offer only the choices that suit this geometry.
            _geometry_apply.apply_property_choices(obj, type_def, result)

            if getattr(obj, "GeometryError", ""):
                obj.GeometryError = ""

        except Exception as e:
            message = str(e) or e.__class__.__name__
            if "GeometryError" in getattr(obj, "PropertiesList", []):
                obj.GeometryError = message
            FreeCAD.Console.PrintError(
                "HVAC - DuctComponent - Execute Error generating component '{}': {}\n".format(obj.Label, message)
            )
            FreeCAD.Console.PrintMessage(traceback.format_exc())
            self._applyFallback(obj, ports)

    @staticmethod
    def _applyFallback(obj, ports):
        """
        Draw the fallback (library/fittings/markers.build_fallback: end-marker
        crosses, the ducts pulled back slightly) in place of a fitting whose
        geometry failed, and report its trims, so the ducts and the network
        stay whole instead of keeping a stale shape. GeometryError keeps why.
        """
        from types import SimpleNamespace

        from ..library import geometry_result
        from ..library.fittings import markers

        try:
            layer_ids = list(getattr(obj, "ConstructionLayerIds", []) or [])
            context = {
                "hvac_api": HVACLibraryAPI,
                "connected_ports": list(ports or []),
                "construction_layers": [SimpleNamespace(id=layer_ids[0])] if layer_ids else [],
                "properties": {},
            }
            result = geometry_result.normalize(markers.build_fallback(context))
            if layer_ids:
                _geometry_apply.apply_geometry_result(obj, result)
            else:
                obj.Shape = next(iter(result.layers.values())).shape
            lengths_json = json.dumps(result.connection_lengths or [])
            if getattr(obj, "ConnectionLengthsJson", "") != lengths_json:
                obj.ConnectionLengthsJson = lengths_json
        except Exception as e:
            FreeCAD.Console.PrintError("HVAC - Fallback for '{}' failed too: {}\n".format(obj.Label, e))

    def _executeCustom(self, obj, ports):
        """Place this component's custom fitting on the node; its own shape stays empty (the link is the geometry)."""
        try:
            _custom_fitting.apply(obj, ports)
            if not obj.Shape.isNull():
                obj.Shape = Part.Shape()
            if getattr(obj, "GeometryError", ""):
                obj.GeometryError = ""
        except Exception as e:
            message = str(e) or e.__class__.__name__
            if "GeometryError" in getattr(obj, "PropertiesList", []):
                obj.GeometryError = message
            FreeCAD.Console.PrintError(
                "HVAC - DuctComponent - Custom fitting '{}': {}\n".format(obj.Label, message)
            )
            # The custom shape no longer fits: show the fallback, not the link left where it was.
            if getattr(obj, "CustomLinkName", ""):
                _custom_fitting.remove_link(obj)
            self._applyFallback(obj, ports)

    @staticmethod
    def _parentAttr(obj, name, default=""):
        """Read a property off this component's parent DuctJunction, or `default` if unresolvable."""
        parent_name = getattr(obj, "ParentJunctionName", "")
        doc = getattr(obj, "Document", None)
        if not parent_name or doc is None:
            return default
        parent = doc.getObject(parent_name)
        return getattr(parent, name, default) if parent is not None else default

    def _parentObj(self, obj):
        """This component's parent DuctJunction document object, or None if unresolvable."""
        parent_name = getattr(obj, "ParentJunctionName", "")
        doc = getattr(obj, "Document", None)
        if not parent_name or doc is None:
            return None
        return doc.getObject(parent_name)

    def _resolveFlowBoundaryPolicy(self, obj):
        """
        (prescribed, locked) declared by this component's own selected
        library type -- ("", False) if it has none, no type selected, or
        the type can't be resolved. Never referenced by name -- only ever
        read off the type-def's own flow_boundary/flow_boundary_locked
        fields (see library/Library.py), so a duct-closure/end-cap type is
        just data, not a hardcoded case here.
        """
        library_id = getattr(obj, "LibraryId", "")
        type_id = getattr(obj, "TypeId", "")
        if not library_id or not type_id:
            return "", False
        reg = hvaclib.HVACLibraryService.get_hvac_library_registry()
        type_def = reg.resolve_type(library_id, type_id)
        if type_def is None:
            return "", False
        return str(getattr(type_def, "flow_boundary", "") or ""), bool(getattr(type_def, "flow_boundary_locked", False))

    def _syncFlowBoundary(self, obj):
        """
        Keep FlowBoundary/DesignFlowRate's editor modes and values in step
        with the parent junction every sync (see each property's own
        comment in setProperties()): editable only on a Primary component
        whose parent is an "end" (terminal) node -- DesignFlowRate further
        only when the current FlowBoundary is "Fixed" -- hidden everywhere
        else.

        If the selected library type locks FlowBoundary (flow_boundary_locked),
        its prescribed value is re-asserted here on *both* this component
        and the parent junction, every sync, so a user can never leave a
        locked terminal (e.g. a duct closure) in a different state -- even
        via a stale document or a direct Python edit. Otherwise, this pulls
        the parent's current value down onto this component, exactly like
        DesignFlowRate's own mirror: any edit made directly on this
        component was already pushed up to the parent by onChanged() before
        this runs, so that pulldown is a no-op in that case and only
        actually does something when the parent changed some other way (a
        fresh sync, a document restore, or an edit on the parent itself).
        """
        if "DesignFlowRate" not in obj.PropertiesList:
            return

        is_primary = getattr(obj, "ComponentRole", "") == "Primary"
        parent = self._parentObj(obj)
        topology = getattr(parent, "Topology", "") if (is_primary and parent is not None) else ""
        editable_context = is_primary and topology == "end"

        prescribed, locked = self._resolveFlowBoundaryPolicy(obj) if editable_context else ("", False)
        if "FlowBoundaryLocked" in obj.PropertiesList and bool(getattr(obj, "FlowBoundaryLocked", False)) != locked:
            obj.FlowBoundaryLocked = locked

        has_flow_boundary = "FlowBoundary" in obj.PropertiesList
        if has_flow_boundary and not self._mirroring_flow_boundary:
            if locked and prescribed:
                self._mirroring_flow_boundary = True
                try:
                    if str(getattr(obj, "FlowBoundary", "Auto") or "Auto") != prescribed:
                        obj.FlowBoundary = prescribed
                    if parent is not None and str(getattr(parent, "FlowBoundary", "Auto") or "Auto") != prescribed:
                        parent.FlowBoundary = prescribed
                    if prescribed == "Closed":
                        if float(getattr(obj, "DesignFlowRate", 0.0) or 0.0) != 0.0:
                            obj.DesignFlowRate = 0.0
                        if parent is not None and float(getattr(parent, "DesignFlowRate", 0.0) or 0.0) != 0.0:
                            parent.DesignFlowRate = 0.0
                finally:
                    self._mirroring_flow_boundary = False
            elif parent is not None:
                parent_boundary = str(getattr(parent, "FlowBoundary", "Auto") or "Auto")
                if str(getattr(obj, "FlowBoundary", "Auto") or "Auto") != parent_boundary:
                    self._mirroring_flow_boundary = True
                    try:
                        obj.FlowBoundary = parent_boundary
                    finally:
                        self._mirroring_flow_boundary = False

        current_boundary = str(getattr(obj, "FlowBoundary", "Auto") or "Auto") if has_flow_boundary else "Fixed"
        flow_boundary_editable = editable_context and not locked
        design_flow_editable = editable_context and not locked and current_boundary == "Fixed"
        try:
            if has_flow_boundary:
                obj.setEditorMode("FlowBoundary", 0 if flow_boundary_editable else (1 if editable_context else 2))
            obj.setEditorMode("DesignFlowRate", 0 if design_flow_editable else (1 if editable_context else 2))
        except Exception:
            pass

        if parent is None or self._mirroring_design_flow_rate:
            return
        parent_value = float(getattr(parent, "DesignFlowRate", 0.0) or 0.0)
        if float(getattr(obj, "DesignFlowRate", 0.0) or 0.0) == parent_value:
            return
        self._mirroring_design_flow_rate = True
        try:
            obj.DesignFlowRate = parent_value
        finally:
            self._mirroring_design_flow_rate = False

    @staticmethod
    def _syncCustomLossCoefficients(obj, ports):
        """
        Keep CustomLossCoefficients holding exactly one K per port that
        custom-loss evaluation can actually use -- see
        _custom_loss.custom_loss_applicable_ports(): a degree-1 component's
        own single port, or every port on whichever flow side is the
        "many" side of a fitting with a single common port on the other
        side (every outlet of a diverging tee, but every INLET of a
        converging tee -- unlike the old outlet-only convention, this
        supports both). A mixed multi-in/multi-out cross has no single
        common side, so it gets no slots at all -- unlike LocalPortsJson's
        own full port list, this is never sized to include a port whose
        value could never actually be applied.

        Values are carried over by edge_key, not position, whenever the
        set of applicable ports changes (e.g. a redrawn segment flips
        which port is now the outlet) -- CustomLossCoefficientEdgeKeys is
        the parallel list recording which edge_key each
        CustomLossCoefficients entry belongs to.
        """
        if "CustomLossCoefficients" not in obj.PropertiesList:
            return
        target_keys = [p.get("edge_key", "") for p in _custom_loss.custom_loss_applicable_ports(ports)]
        current_keys = list(getattr(obj, "CustomLossCoefficientEdgeKeys", None) or [])
        if current_keys == target_keys:
            return

        old_by_key = dict(zip(current_keys, getattr(obj, "CustomLossCoefficients", None) or []))
        obj.CustomLossCoefficientEdgeKeys = target_keys
        obj.CustomLossCoefficients = [old_by_key.get(key, 0.0) for key in target_keys]

    @staticmethod
    def _syncLossCoefficientEditorMode(obj):
        """CustomLossCoefficients is only editable while LossCoefficientSource == 'Custom' -- read-only otherwise."""
        if "CustomLossCoefficients" not in obj.PropertiesList:
            return
        source = str(getattr(obj, "LossCoefficientSource", "Library") or "Library")
        try:
            obj.setEditorMode("CustomLossCoefficients", 0 if source == "Custom" else 1)
        except Exception:
            pass

    @staticmethod
    def _syncCalcPropertiesEditorMode(obj):
        """
        CalcFlowRate/CalcVelocity/CalcLossCoefficient/CalcPressureDrop can
        only show one unambiguous result -- hide them (not just read-only)
        once this is a multiport Primary (see
        core/_component_results.is_multiport_primary), so a user is never
        shown a single number that's silently standing in for several
        different legs' worth of K/flow/pressure-drop. CalcPortResultsJson
        (always hidden, internal-only) is the authoritative data at that
        point instead.
        """
        multiport = _component_results.is_multiport_primary(obj)
        for prop in ("CalcFlowRate", "CalcVelocity", "CalcLossCoefficient", "CalcPressureDrop"):
            if prop not in obj.PropertiesList:
                continue
            try:
                obj.setEditorMode(prop, 2 if multiport else 1)
            except Exception:
                pass

    # Component properties outside the type schema that still change the
    # geometry, and so the neighbouring ducts' trims (see onChanged).
    _SYNC_ON_EDIT = ("GeometrySource", "CustomPlacement", "CustomFitting", "PortSequence")

    def onChanged(self, obj, prop):
        # A geometry input edited in the property editor: the network re-syncs
        # so the neighbouring ducts are re-trimmed to this fitting.
        _type_schema.request_sync_after_edit(obj, prop, self._SYNC_ON_EDIT)

        if prop == "LossCoefficientSource":
            self._syncLossCoefficientEditorMode(obj)
            return

        if prop == "FlowBoundary" and not self._mirroring_flow_boundary:
            if getattr(obj, "ComponentRole", "") != "Primary":
                return
            boundary = str(getattr(obj, "FlowBoundary", "Auto") or "Auto")
            if boundary == "Closed" and float(getattr(obj, "DesignFlowRate", 0.0) or 0.0) != 0.0:
                obj.DesignFlowRate = 0.0
            parent = self._parentObj(obj)
            if parent is None:
                return
            if str(getattr(parent, "FlowBoundary", "Auto") or "Auto") == boundary:
                return
            self._mirroring_flow_boundary = True
            try:
                parent.FlowBoundary = boundary
            finally:
                self._mirroring_flow_boundary = False
            return

        if prop != "DesignFlowRate" or self._mirroring_design_flow_rate:
            return
        if getattr(obj, "ComponentRole", "") != "Primary":
            return
        parent = self._parentObj(obj)
        if parent is None:
            return
        value = float(getattr(obj, "DesignFlowRate", 0.0) or 0.0)
        if float(getattr(parent, "DesignFlowRate", 0.0) or 0.0) == value:
            return
        self._mirroring_design_flow_rate = True
        try:
            parent.DesignFlowRate = value
        finally:
            self._mirroring_design_flow_rate = False

    @classmethod
    def _parentAnalysis(cls, obj):
        """This component's parent DuctJunction's full topology analysis dict (see NetworkParser.JunctionAnalysis), or {} if unresolvable."""
        raw = cls._parentAttr(obj, "AnalysisJson", "{}")
        try:
            return json.loads(raw) or {}
        except Exception:
            return {}

    def setProperties(self, obj):
        self._addProperty(obj, "App::PropertyString", "OwnerNetworkName", "HVAC", "Owning duct network")
        self._addProperty(obj, "App::PropertyString", "ParentJunctionName", "HVAC", "Owning DuctJunction object name")

        if "ComponentRole" not in obj.PropertiesList:
            obj.addProperty("App::PropertyEnumeration", "ComponentRole", "HVAC", "Primary fitting or an inline device")
            obj.ComponentRole = ["Primary", "Inline"]

        self._addProperty(
            obj,
            "App::PropertyString",
            "AttachedEdgeKey",
            "HVAC",
            "Real edge_key this Inline component's chain is attached to (empty for Primary)",
        )
        self._addProperty(
            obj,
            "App::PropertyInteger",
            "PortSequence",
            "HVAC",
            "Order from the Primary outward toward the attached edge (Inline only)",
        )
        # Prop_NoRecompute -- documentation only, never affects geometry.
        self._addProperty(
            obj,
            "App::PropertyString",
            "Number",
            "HVAC",
            "Documentation number assigned by Renumber Network (e.g. 'J007-P' or 'J007-01'), blank until first renumbered",
            attr=16,
        )
        self._addProperty(obj, "App::PropertyString", "LibraryId", "HVAC", "HVAC library id")
        self._addProperty(obj, "App::PropertyString", "TypeId", "HVAC", "Selected fitting type id")
        self._addProperty(
            obj, "App::PropertyString", "Profile", "HVAC", "Duct profile at this component's primary/outlet side"
        )
        self._addProperty(
            obj,
            "App::PropertyStringList",
            "TypeSchemaPropertyNames",
            "HVAC",
            "Internal: property names added by the last-applied type schema (for stale cleanup)",
        )
        self._addProperty(
            obj,
            "App::PropertyStringList",
            "ConstructionLayerIds",
            "HVAC",
            "Internal: construction layer ids of the last-applied type (see core/_construction_schema.py)",
        )
        self._addProperty(
            obj,
            "App::PropertyStringList",
            "ConstructionFeatureIds",
            "HVAC",
            "Internal: construction feature ids of the last-applied type (see core/_construction_schema.py)",
        )
        self._addProperty(
            obj,
            "App::PropertyString",
            "LocalPortsJson",
            "HVAC",
            "Internal: this component's local inlet/outlet port geometry, written by the parent junction's composer",
        )
        self._addProperty(
            obj,
            "App::PropertyString",
            "ConnectionLengthsJson",
            "HVAC",
            "This component's own per-port connection (trim) lengths",
        )
        self._addProperty(
            obj,
            "App::PropertyString",
            "GeometryError",
            "HVAC",
            "Last geometry-generation error; blank when the current geometry built successfully",
        )
        try:
            obj.setEditorMode("GeometryError", 1)
        except Exception:
            pass

        # Custom geometry (ROADMAP 6.3): a user-modelled fitting (an App::Part
        # with HVAC port markers) placed at the node instead of the library
        # geometry. Primary components only.
        if "GeometrySource" not in obj.PropertiesList:
            obj.addProperty(
                "App::PropertyEnumeration",
                "GeometrySource",
                "HVAC Custom Geometry",
                "Library: the selected type builds the geometry. Custom: the App::Part in CustomFitting is "
                "linked at the node and the ducts end at its port markers",
            )
            obj.GeometrySource = ["Library", "Custom"]
            obj.GeometrySource = "Library"
        self._addProperty(
            obj,
            "App::PropertyLink",
            "CustomFitting",
            "HVAC Custom Geometry",
            "App::Part holding the modelled fitting and one HVAC port marker per opening "
            "(see Create Custom Fitting and Edit Ports)",
        )
        # Fit to node: a link to the fitting is moved onto the node. In place:
        # the fitting stays where it was modelled and the ducts end on its
        # ports (how ducts drawn to a custom fitting's ports are attached).
        if "CustomPlacement" not in obj.PropertiesList:
            obj.addProperty(
                "App::PropertyEnumeration",
                "CustomPlacement",
                "HVAC Custom Geometry",
                "Fit to node: a link to CustomFitting is moved onto the node. In place: CustomFitting stays where "
                "it was modelled and the ducts end on its port markers",
            )
            obj.CustomPlacement = list(_custom_fitting.PLACEMENTS)
            obj.CustomPlacement = _custom_fitting.PLACEMENT_FIT
        self._addProperty(
            obj,
            "App::PropertyString",
            "AutoAttachedTo",
            "HVAC",
            "Internal: the custom fitting this component was attached to automatically, once",
        )
        self._addProperty(
            obj,
            "App::PropertyStringList",
            "CustomPortEdgeKeys",
            "HVAC Custom Geometry",
            "Optional: entry N is the edge key of the duct custom port N must go on (empty entry = automatic)",
        )
        self._addProperty(
            obj,
            "App::PropertyStringList",
            "CustomFitWarnings",
            "HVAC Custom Geometry",
            "Warnings from the last fit, e.g. a port whose size differs from its duct's",
        )
        self._addProperty(
            obj, "App::PropertyString", "CustomLinkName", "HVAC", "Internal: name of the App::Link this component owns"
        )
        self._addProperty(
            obj, "App::PropertyString", "CustomPortMapJson", "HVAC", "Internal: which custom port each duct meets"
        )
        for name, mode in (
            ("CustomFitWarnings", 1),
            ("CustomLinkName", 2),
            ("CustomPortMapJson", 2),
            ("AutoAttachedTo", 2),
        ):
            try:
                obj.setEditorMode(name, mode)
            except Exception:
                pass

        # Per-construction-layer Layer_<id>_Shape/Layer_<id>_Material
        # properties are added/removed by applyTypeSchema() (via
        # core/_construction_schema.py) to match the selected type's own
        # declared construction -- see the matching comment in Segment.py's
        # own setProperties().

        # Two-way proxy for the parent junction's own FlowBoundary/
        # DesignFlowRate (see Junction.py's onChanged) -- a junction has no
        # Shape and can't be picked in the 3D view, so a terminal's flow
        # condition needs to be settable from its visible Primary fitting
        # too. Editor mode/value are kept in sync with the parent every
        # sync, from execute()'s _syncFlowBoundary -- editable only for a
        # Primary component whose parent junction is an "end" (terminal)
        # node, hidden everywhere else since it has no meaning there. Starts
        # hidden (mode 2) here purely as each property's one-time initial
        # default when first added to an object; _syncFlowBoundary corrects
        # it on the very next sync.
        if "FlowBoundary" not in obj.PropertiesList:
            obj.addProperty(
                "App::PropertyEnumeration",
                "FlowBoundary",
                "Airflow",
                "Terminal flow condition, mirrored to/from the parent junction: Auto (solved by mass "
                "balance), Fixed (use Design Flow Rate as-is, 0 included), or Closed (sealed "
                "termination, always 0 flow)",
            )
            obj.FlowBoundary = ["Auto", "Fixed", "Closed"]
            obj.FlowBoundary = "Auto"
            try:
                obj.setEditorMode("FlowBoundary", 2)
            except Exception:
                pass

        self._addProperty(
            obj,
            "App::PropertyBool",
            "FlowBoundaryLocked",
            "Airflow",
            "Internal: true if the selected library type prescribes and locks this terminal's flow "
            "condition (e.g. a duct closure/end cap), so the user can't change it",
        )
        try:
            obj.setEditorMode("FlowBoundaryLocked", 2)
        except Exception:
            pass

        if "DesignFlowRate" not in obj.PropertiesList:
            obj.addProperty(
                "App::PropertyFloat",
                "DesignFlowRate",
                "Airflow",
                "User-specified design flow rate for this terminal (L/s), mirrored to/from the parent "
                "junction, used when Flow Boundary is 'Fixed' -- 0 is a valid value.",
            )
            try:
                obj.setEditorMode("DesignFlowRate", 2)
            except Exception:
                pass

        self._addProperty(
            obj,
            "App::PropertyFloat",
            "CalcFlowRate",
            "Airflow",
            "Computed flow rate through this component (L/s) -- meaningful only for a 1-port or 2-port component; see CalcPortResultsJson for a multiport Primary",
        )
        self._addProperty(
            obj,
            "App::PropertyFloat",
            "CalcVelocity",
            "Airflow",
            "Computed reference velocity used for this component's pressure drop (m/s) -- meaningful only for a 1-port or 2-port component; see CalcPortResultsJson for a multiport Primary",
        )
        self._addProperty(
            obj,
            "App::PropertyFloat",
            "CalcLossCoefficient",
            "Airflow",
            "Computed loss coefficient (K) from the last calculation -- meaningful only for a 1-port or 2-port component; see CalcPortResultsJson for a multiport Primary",
        )
        self._addProperty(
            obj,
            "App::PropertyFloat",
            "CalcPressureDrop",
            "Airflow",
            "Computed pressure drop across this component (Pa) -- meaningful only for a 1-port or 2-port component; see CalcPortResultsJson for a multiport Primary",
        )

        for prop in ("CalcFlowRate", "CalcVelocity", "CalcLossCoefficient", "CalcPressureDrop"):
            try:
                obj.setEditorMode(prop, 1)
            except Exception:
                pass

        # Internal: the authoritative per-port result data (one entry per
        # local port that received a fitting-loss contribution), keyed by
        # edge_key -- see core/_component_results.py for the (de)serializer
        # and core/AirflowSolver.py for where this gets written every
        # solve. Always hidden -- never meant for direct property-editor
        # viewing, same as LocalPortsJson.
        self._addProperty(
            obj,
            "App::PropertyString",
            "CalcPortResultsJson",
            "Airflow",
            "Internal: per-port calculated results (flow, velocity, K, pressure drop, static "
            "pressure) from the last calculation, keyed by edge_key",
        )
        if not getattr(obj, "CalcPortResultsJson", ""):
            obj.CalcPortResultsJson = "{}"
        try:
            obj.setEditorMode("CalcPortResultsJson", 2)
        except Exception:
            pass

        # Re-derive whether the 4 scalar Calc* properties above are
        # currently ambiguous (multiport Primary) every time setProperties()
        # runs, not just from execute() -- covers a document restore, where
        # LocalPortsJson is already populated but execute() may not have
        # run yet.
        self._syncCalcPropertiesEditorMode(obj)

        # Lets a user override the selected library type's own loss formula
        # with explicit per-port K values -- e.g. a manufacturer datasheet
        # gives a different K than the generic library formula. Analysis
        # only, never affects geometry, so both are Prop_NoRecompute (16).
        # Not named "LossCoefficient" -- some library types' own JSON
        # type-def properties already use that exact name (see
        # library/loss_api.py's terminal_component_loss/inline_device_loss),
        # and this is a distinct, core DuctComponent property.
        if "LossCoefficientSource" not in obj.PropertiesList:
            obj.addProperty(
                "App::PropertyEnumeration",
                "LossCoefficientSource",
                "Airflow",
                "Loss coefficient (K) source for this component: 'Library' uses the selected type's "
                "own loss formula, 'Custom' uses per-port K values from CustomLossCoefficients instead",
                16,
            )
            obj.LossCoefficientSource = ["Library", "Custom"]
            obj.LossCoefficientSource = "Library"

        # One K per port that can actually receive one -- a degree-1
        # component's own single port, or every port on a 2+-port
        # component's "many" flow side (see
        # _custom_loss.custom_loss_applicable_ports()); a mixed
        # multi-in/multi-out cross has no single common side, so it gets
        # no slots at all. CustomLossCoefficientEdgeKeys is the
        # parallel, explicit list of which edge_key each entry belongs to
        # -- not positional, so a later flow-direction change (which port
        # is now the outlet) can't silently scramble an existing value
        # onto the wrong leg. Both kept in sync with the port list by
        # _syncCustomLossCoefficients(), called every execute() alongside
        # LocalPortsJson itself.
        self._addProperty(
            obj,
            "App::PropertyFloatList",
            "CustomLossCoefficients",
            "Airflow",
            "Custom loss coefficients (K), one entry per port CustomLossCoefficientEdgeKeys names "
            "(same order). Used only when LossCoefficientSource is 'Custom'.",
            16,
        )
        self._addProperty(
            obj,
            "App::PropertyStringList",
            "CustomLossCoefficientEdgeKeys",
            "HVAC",
            "Internal: which local port (edge_key) each CustomLossCoefficients entry belongs to",
        )
        try:
            obj.setEditorMode("CustomLossCoefficientEdgeKeys", 2)
        except Exception:
            pass
        self._syncLossCoefficientEditorMode(obj)

        if not getattr(obj, "LibraryId", ""):
            lib = hvaclib.HVACLibraryService.get_active_hvac_library()
            if lib:
                obj.LibraryId = lib.id

        if not getattr(obj, "LocalPortsJson", ""):
            obj.LocalPortsJson = "[]"

        if not getattr(obj, "ConnectionLengthsJson", ""):
            obj.ConnectionLengthsJson = "[]"

        for prop in ("ComponentRole", "Profile"):
            try:
                obj.setEditorMode(prop, 1)
            except Exception:
                pass

        # Internal bookkeeping/JSON blobs -- kept (never removed) for the
        # addon's own use, just hidden from the property editor since a
        # user never needs to read or edit them directly. PortSequence is
        # deliberately NOT hidden here -- it's a documented user-facing
        # reordering mechanism for an edge's own Inline chain (see
        # Network.py's applyAddInlineComponent).
        for prop in (
            "OwnerNetworkName",
            "ParentJunctionName",
            "AttachedEdgeKey",
            "TypeSchemaPropertyNames",
            "ConstructionLayerIds",
            "ConstructionFeatureIds",
            "LocalPortsJson",
            "ConnectionLengthsJson",
        ):
            try:
                obj.setEditorMode(prop, 2)
            except Exception:
                pass

    def applyTypeSchema(self):
        obj = self.Object
        library_id = getattr(obj, "LibraryId", "")
        type_id = getattr(obj, "TypeId", "")
        changed = _type_schema.apply_type_schema(obj, library_id, type_id)
        changed = _construction_schema.apply_construction_schema(obj, library_id, type_id) or changed
        _construction_schema.apply_default_layer_materials(obj, library_id, type_id)
        changed = _construction_schema.apply_construction_features_schema(obj, library_id, type_id) or changed
        return changed

    def getConstruction(self):
        """This component's own construction layers, queryable by semantic role -- see core/Construction.py."""
        return _construction.construction_for(self.Object)

    def updateMetadata(
        self,
        parent_junction=None,
        role=None,
        attached_edge_key=None,
        port_sequence=None,
        library_id="",
        type_id="",
        profile="",
    ):
        obj = self.Object
        changed = False

        if parent_junction is not None and getattr(obj, "ParentJunctionName", "") != parent_junction.Name:
            obj.ParentJunctionName = parent_junction.Name
            changed = True

        owner = hvaclib.getOwnerNetwork(parent_junction) if parent_junction is not None else None
        if owner is not None and getattr(obj, "OwnerNetworkName", "") != owner.Name:
            obj.OwnerNetworkName = owner.Name
            changed = True

        if role and getattr(obj, "ComponentRole", "") != str(role):
            obj.ComponentRole = str(role)
            changed = True

        if attached_edge_key is not None and getattr(obj, "AttachedEdgeKey", "") != str(attached_edge_key):
            obj.AttachedEdgeKey = str(attached_edge_key)
            changed = True

        if port_sequence is not None and getattr(obj, "PortSequence", None) != int(port_sequence):
            obj.PortSequence = int(port_sequence)
            changed = True

        if library_id and getattr(obj, "LibraryId", "") != str(library_id):
            obj.LibraryId = str(library_id)
            changed = True

        if type_id and getattr(obj, "TypeId", "") != str(type_id):
            obj.TypeId = str(type_id)
            changed = True
            # This component just adopted a new type -- apply its
            # prescribed FlowBoundary (if any) once, as a starting point
            # (flow_boundary_locked types get re-asserted continuously by
            # _syncFlowBoundary instead; this covers the "prescribed but
            # not locked" case, applied only at the moment of selection so
            # a later user override isn't fought on every subsequent sync).
            effective_library_id = str(library_id) if library_id else getattr(obj, "LibraryId", "")
            reg = hvaclib.HVACLibraryService.get_hvac_library_registry()
            type_def = reg.resolve_type(effective_library_id, str(type_id))
            prescribed = str(getattr(type_def, "flow_boundary", "") or "") if type_def is not None else ""
            if prescribed and "FlowBoundary" in obj.PropertiesList:
                obj.FlowBoundary = prescribed
                if prescribed == "Closed":
                    obj.DesignFlowRate = 0.0

        if profile and getattr(obj, "Profile", "") != str(profile):
            obj.Profile = str(profile)
            changed = True

        return changed

    @classmethod
    def create(cls, doc, name, parent_junction, role, attached_edge_key="", port_sequence=0, owner_network=None):
        component = doc.addObject("Part::FeaturePython", name)
        cls(
            component,
            parent_junction=parent_junction,
            role=role,
            attached_edge_key=attached_edge_key,
            port_sequence=port_sequence,
        )
        DuctComponentViewProvider(component.ViewObject)
        return component

    @staticmethod
    def labelFor(role, type_label):
        label = str(type_label) if type_label else "Component"
        return "{} [{}]".format(label, role)

    @staticmethod
    def _addProperty(obj, prop_type, prop_name, group, description, attr=0):
        if prop_name not in obj.PropertiesList:
            obj.addProperty(prop_type, prop_name, group, description, attr)


class DuctComponentViewProvider:
    """View provider for derived duct component objects."""

    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object
        self.ViewObject = vobj

    def dumps(self):
        return None

    def loads(self, state):
        pass

    def updateData(self, obj, prop):
        # Re-render every construction layer's own shape from its own
        # linked material whenever a layer's shape or material link
        # changes -- see core/_component_appearance.py.
        if _component_appearance.is_trigger_property(obj, prop):
            vobj = getattr(self, "ViewObject", None)
            if vobj is not None:
                _component_appearance.apply_component_appearance(vobj, from_view_update=True)

    def getIcon(self):
        return hvaclib.get_icon_path("DuctsIcon.svg")

    def claimChildren(self):
        # A custom fitting's link shows under its component.
        obj = getattr(self, "Object", None)
        link = _custom_fitting.owned_link(obj) if obj is not None else None
        return [link] if link is not None else []

    def onDelete(self, vobj, subelements):
        _custom_fitting.remove_link(vobj.Object)
        # Permit direct deletion from the tree -- e.g. of a stale component
        # left over from an older schema that the owning network's own
        # sync loop never picked up for cleanup. If a live network still
        # owns it, ask that network to resync afterwards, so anything
        # still topologically required (e.g. a junction's own Primary
        # component) gets regenerated fresh from library defaults (see
        # DuctNetwork.syncJunctionComponents).
        obj = vobj.Object
        owner = hvaclib.getOwnerNetwork(obj)
        if owner and getattr(owner, "Proxy", None):
            owner.Proxy.requestSync(force_recompute=True)
        return True

    def canDropObjects(self):
        return False

    def canDragObjects(self):
        return False
