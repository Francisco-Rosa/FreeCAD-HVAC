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

import FreeCADGui as Gui
import Part
from PySide import QtCore, QtWidgets
from PySide.QtCore import QT_TRANSLATE_NOOP

import FreeCAD

translate = FreeCAD.Qt.translate

from ..library.library_api import HVACLibraryAPI
from ..utils import hvaclib
from . import _custom_fitting, _terminal_function


def _set_if_changed(obj, name, value):
    """Write a property only when its value differs: every write marks the object for recompute."""
    if getattr(obj, name, None) != value:
        setattr(obj, name, value)


def _json_safe_port(port):
    """
    Return a copy of a port dict safe to json.dumps: any FreeCAD.Vector
    field (as produced by HVACLibraryAPI.copy_port) is converted back to a
    plain (x, y, z) tuple. Fields that already came straight out of
    AnalysisJson (parsed JSON) are plain lists/tuples already and pass
    through unchanged.
    """
    out = dict(port)
    for key in ("position", "direction", "profile_x_axis", "user_offset", "flow_direction"):
        value = out.get(key)
        if value is not None and hasattr(value, "x"):
            out[key] = HVACLibraryAPI.xyz(value)
    return out


class DuctJunction:
    """
    Derived per-node network junction: a purely logical/connectivity
    container. It holds no library type or geometry of its own -- each
    physical fitting it represents is a separate DuctComponent child (see
    core/Component.py), found via getComponents()/getPrimaryComponent()/
    getPortChains().

    A junction's only "compute" job is composing its component chain: one
    Primary component always gets every one of the junction's real ports
    unchanged, and independently, each real edge may additionally carry its
    own chain of zero-or-more Inline components between the Primary and
    that edge's own external segment. composeComponents() works out every
    component's local inlet/outlet ports and writes them to that
    component's LocalPortsJson (see below).
    """

    TYPE = "DuctJunction"

    def __init__(self, obj, owner=None, node_id=0, node_key="", center_point=None, degree=0, topology=""):
        obj.Proxy = self
        self.Object = obj
        self._allow_delete = False
        self._mirroring_design_flow_rate = False
        self._mirroring_flow_boundary = False
        self.setProperties(obj)
        self.updateMetadata(
            owner=owner, node_id=node_id, node_key=node_key, center_point=center_point, degree=degree, topology=topology
        )

    def onDocumentRestored(self, obj):
        obj.Proxy = self
        self.Object = obj
        self._allow_delete = False
        self._mirroring_design_flow_rate = False
        self._mirroring_flow_boundary = False
        self.setProperties(obj)

    def dumps(self):
        return None

    def loads(self, state):
        pass

    def execute(self, obj):
        # A DuctJunction has no geometry of its own -- every physical
        # fitting is generated independently by its DuctComponent children
        # (see Component.py's own execute()). Nothing to do here.
        pass

    def _requestOwnerSync(self, obj):
        """Re-classify after an edit that changes this terminal's function (6.5)."""
        doc = getattr(obj, "Document", None)
        if doc is None or getattr(doc, "Restoring", False) or getattr(obj, "Topology", "") != "end":
            return
        owner = hvaclib.getOwnerNetwork(obj)
        proxy = getattr(owner, "Proxy", None) if owner is not None else None
        # A sync already running (it is creating or updating this junction)
        # re-classifies it anyway.
        if proxy is None or getattr(proxy, "_sync_in_progress", False):
            return
        try:
            proxy.requestSync()
        except Exception:
            pass

    def onChanged(self, obj, prop):
        if prop == "TerminalFunction" or (
            prop == "FlowBoundary" and str(getattr(obj, "TerminalFunction", "Auto") or "Auto") == "Auto"
        ):
            self._requestOwnerSync(obj)
        # DesignFlowRate/FlowBoundary each have a two-way mirror onto the
        # Primary component's own copy (see Component.py's onChanged) -- a
        # junction has no Shape and can't be picked in the 3D view, so a
        # user needs to be able to set/see these from the visible terminal
        # fitting too. Each guard flag stops its own pair of onChanged
        # handlers from bouncing the same edit back and forth forever.
        if prop == "FlowBoundary" and not self._mirroring_flow_boundary:
            boundary = str(getattr(obj, "FlowBoundary", "Auto") or "Auto")

            # A terminal forced to "Closed" always carries zero flow (see
            # analysis/flow.py) -- snap DesignFlowRate to match so the
            # property state never shows a stale nonzero value for a
            # sealed terminal.
            if boundary == "Closed" and float(getattr(obj, "DesignFlowRate", 0.0) or 0.0) != 0.0:
                obj.DesignFlowRate = 0.0

            # DesignFlowRate is only meaningful (and editable) when Fixed.
            if getattr(obj, "Topology", "") == "end":
                try:
                    obj.setEditorMode("DesignFlowRate", 0 if boundary == "Fixed" else 1)
                except Exception:
                    pass

            primary = self.getPrimaryComponent()
            if primary is not None and "FlowBoundary" in primary.PropertiesList:
                value = str(getattr(obj, "FlowBoundary", "Auto") or "Auto")
                if str(getattr(primary, "FlowBoundary", "Auto") or "Auto") != value:
                    self._mirroring_flow_boundary = True
                    try:
                        primary.FlowBoundary = value
                    finally:
                        self._mirroring_flow_boundary = False
            return

        if prop != "DesignFlowRate" or self._mirroring_design_flow_rate:
            return
        primary = self.getPrimaryComponent()
        if primary is None or "DesignFlowRate" not in primary.PropertiesList:
            return
        value = float(getattr(obj, "DesignFlowRate", 0.0) or 0.0)
        if float(getattr(primary, "DesignFlowRate", 0.0) or 0.0) == value:
            return
        self._mirroring_design_flow_rate = True
        try:
            primary.DesignFlowRate = value
        finally:
            self._mirroring_design_flow_rate = False

    def setProperties(self, obj):
        self._addProperty(obj, "App::PropertyString", "OwnerNetworkName", "HVAC", "Owning duct network")
        self._addProperty(obj, "App::PropertyInteger", "NodeId", "HVAC", "Parser node id")
        self._addProperty(obj, "App::PropertyString", "NodeKey", "HVAC", "Persistent snapped node key")
        # Prop_NoRecompute -- documentation only, never affects geometry.
        self._addProperty(
            obj,
            "App::PropertyString",
            "Number",
            "HVAC",
            "Documentation number assigned by Renumber Network (e.g. 'J007'), blank until first renumbered",
            attr=16,
        )
        self._addProperty(obj, "App::PropertyVector", "CenterPoint", "HVAC", "Junction center point")
        self._addProperty(obj, "App::PropertyInteger", "Degree", "HVAC", "Node degree")
        self._addProperty(obj, "App::PropertyString", "Topology", "HVAC", "Junction topology")
        self._addProperty(obj, "App::PropertyString", "Family", "HVAC", "Classified fitting family")

        self._addProperty(obj, "App::PropertyStringList", "ConnectedEdgeKeys", "HVAC", "Connected segment keys")
        self._addProperty(
            obj,
            "App::PropertyString",
            "ConnectionLengthsJson",
            "HVAC",
            "Aggregate per-edge connection lengths (from the outermost component on each side)",
        )
        self._addProperty(obj, "App::PropertyString", "AnalysisJson", "HVAC", "Serialized topology analysis")

        if "FlowBoundary" not in obj.PropertiesList:
            obj.addProperty(
                "App::PropertyEnumeration",
                "FlowBoundary",
                "Airflow",
                "Terminal flow condition: Auto (solved by mass balance -- exactly one terminal per "
                "sub-network), Fixed (use Design Flow Rate as-is, 0 included), or Closed (sealed "
                "termination, always 0 flow)",
            )
            obj.FlowBoundary = ["Auto", "Fixed", "Closed"]
            obj.FlowBoundary = "Auto"
        if "TerminalFunction" not in obj.PropertiesList:
            obj.addProperty(
                "App::PropertyEnumeration",
                "TerminalFunction",
                "Airflow",
                "What this terminal does: Auto (from the network's SystemType; the balancing terminal is "
                "the Source), Supply outlet, Return / Exhaust inlet, OutdoorAir intake, Discharge to "
                "outside, or Source (where the system meets its fan or equipment)",
            )
            obj.TerminalFunction = list(_terminal_function.TERMINAL_FUNCTIONS)
            obj.TerminalFunction = "Auto"
        self._addProperty(
            obj,
            "App::PropertyFloat",
            "DesignFlowRate",
            "Airflow",
            "User-specified design flow rate for this terminal (L/s), used when Flow Boundary is 'Fixed' -- 0 is a valid value. Ignored when Flow Boundary is 'Auto' or 'Closed'.",
        )
        self._addProperty(
            obj,
            "App::PropertyFloat",
            "CalcTotalFlowRate",
            "Airflow",
            "Computed through-flow at this junction (L/s) -- max(total inflow, total outflow) across its connected ports, not the sum of every leg's own flow (see analysis/pressure.py's Phase G)",
        )
        self._addProperty(
            obj,
            "App::PropertyFloat",
            "CalcStaticPressure",
            "Airflow",
            "Computed relative static pressure (Pa), referenced to 0 Pa at this sub-network's balancing terminal",
        )
        self._addProperty(
            obj,
            "App::PropertyBool",
            "IsFlowSource",
            "Airflow",
            "True if flow physically leaves the system at this terminal (a supply/source opening) -- meaningless off a terminal, see updateMetadata()'s own topology-based editor mode",
        )
        self._addProperty(
            obj,
            "App::PropertyString",
            "CalcLossWarning",
            "Airflow",
            "Non-fatal warning from the last calculation (e.g. fallback loss coefficient used)",
        )
        if "AllowSizeChange" not in obj.PropertiesList:
            obj.addProperty(
                "App::PropertyBool",
                "AllowSizeChange",
                "HVAC Duct Sizing",
                "Whether Size Ducts may change the duct size where air passes straight through this junction "
                "(a reducer at an in-line node, a reducing run at a tee or cross). Off keeps them one size. "
                "Used by the network's SizeChangePolicy AtStraightJunctions (in-line nodes and runs) and "
                "AtInlineNodesOnly (in-line nodes)",
            )
            obj.AllowSizeChange = True

        for prop in ("CalcTotalFlowRate", "CalcStaticPressure", "CalcLossWarning"):
            try:
                obj.setEditorMode(prop, 1)
            except Exception:
                pass
        # IsFlowSource's own editor mode is topology-gated (terminal only) --
        # left unset here, corrected by the very next updateMetadata() call,
        # same as FlowBoundary/DesignFlowRate just below.

        if not getattr(obj, "ConnectionLengthsJson", ""):
            obj.ConnectionLengthsJson = "[]"

        if not getattr(obj, "AnalysisJson", ""):
            obj.AnalysisJson = "{}"

        for prop in ("NodeKey", "CenterPoint", "Degree", "Topology", "Family"):
            try:
                obj.setEditorMode(prop, 1)
            except Exception:
                pass

        # Internal bookkeeping/JSON blobs -- kept (never removed) for the
        # addon's own use, just hidden from the property editor since a
        # user never needs to read or edit them directly.
        for prop in ("OwnerNetworkName", "NodeId", "ConnectedEdgeKeys", "ConnectionLengthsJson", "AnalysisJson"):
            try:
                obj.setEditorMode(prop, 2)
            except Exception:
                pass

    def updateMetadata(
        self,
        owner=None,
        node_id=0,
        node_key="",
        center_point=None,
        degree=0,
        topology="",
        family="",
        connected_edge_keys=None,
        analysis_json="{}",
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
            changed = True

        try:
            # FlowBoundary/DesignFlowRate/IsFlowSource only have meaning on a
            # terminal ("end") node -- fully hidden (mode 2), not merely
            # read-only, everywhere else, so a through/branch/cross/
            # multiport junction's property editor doesn't show controls
            # that don't apply to it at all.
            is_terminal = getattr(obj, "Topology", "") == "end"
            boundary = str(getattr(obj, "FlowBoundary", "Auto") or "Auto")
            obj.setEditorMode("FlowBoundary", 0 if is_terminal else 2)
            if "TerminalFunction" in getattr(obj, "PropertiesList", []):
                obj.setEditorMode("TerminalFunction", 0 if is_terminal else 2)
            # DesignFlowRate is only meaningful (and editable) when Fixed;
            # still shown read-only for Auto/Closed on a terminal.
            if is_terminal:
                obj.setEditorMode("DesignFlowRate", 0 if boundary == "Fixed" else 1)
            else:
                obj.setEditorMode("DesignFlowRate", 2)
            obj.setEditorMode("IsFlowSource", 1 if is_terminal else 2)
            # Only a junction air passes straight through can change size: an in-line node or a tee/cross run.
            if "AllowSizeChange" in obj.PropertiesList:
                straight_through = getattr(obj, "Topology", "") in ("through", "branch", "cross")
                obj.setEditorMode("AllowSizeChange", 0 if straight_through else 2)
        except Exception:
            pass

        if family and getattr(obj, "Family", "") != str(family):
            obj.Family = str(family)
            changed = True

        if connected_edge_keys is not None:
            edge_keys = [str(k) for k in connected_edge_keys]
            if list(getattr(obj, "ConnectedEdgeKeys", []) or []) != edge_keys:
                obj.ConnectedEdgeKeys = edge_keys
                changed = True

        if analysis_json is not None and getattr(obj, "AnalysisJson", "") != str(analysis_json):
            obj.AnalysisJson = str(analysis_json)
            changed = True

        return changed

    # ------------------------------------------------------------------
    # Component chain: lookup, composition, trim aggregation
    # ------------------------------------------------------------------

    def getComponents(self):
        """
        This junction's DuctComponent children: Primary first, then Inline
        components grouped by their attached edge and PortSequence-ascending
        within each group. Convenience accessor only -- composeComponents()
        never relies on this ordering for correctness, it always groups by
        AttachedEdgeKey itself (see getPortChains()).
        """
        obj = self.Object
        net = hvaclib.getOwnerNetwork(obj)
        geometry = getattr(net, "Geometry", None) if net is not None else None
        if geometry is None:
            return []
        out = [
            c
            for c in geometry.OutList
            if hvaclib.isDuctComponent(c) and getattr(c, "ParentJunctionName", "") == obj.Name
        ]
        out.sort(
            key=lambda c: (
                0 if getattr(c, "ComponentRole", "") == "Primary" else 1,
                getattr(c, "AttachedEdgeKey", ""),
                int(getattr(c, "PortSequence", 0)),
                c.Name,
            )
        )
        return out

    def getPrimaryComponent(self):
        for c in self.getComponents():
            if getattr(c, "ComponentRole", "") == "Primary":
                return c
        return None

    def getPortChains(self):
        """
        {edge_key: [Inline components]}, each list Primary-outward (i.e.
        PortSequence-ascending) -- the independent chain of Inline devices
        attached to that one real edge. Edges with no Inline components are
        simply absent from this dict.
        """
        chains = {}
        for c in self.getComponents():
            if getattr(c, "ComponentRole", "") != "Inline":
                continue
            edge_key = getattr(c, "AttachedEdgeKey", "")
            if edge_key:
                chains.setdefault(edge_key, []).append(c)
        for lst in chains.values():
            lst.sort(key=lambda c: int(getattr(c, "PortSequence", 0)))
        return chains

    def getInlineComponents(self, edge_key=None):
        """All Inline components, or (if edge_key is given) just that edge's own chain."""
        if edge_key is None:
            return [c for c in self.getComponents() if getattr(c, "ComponentRole", "") == "Inline"]
        return self.getPortChains().get(edge_key, [])

    def composeComponents(self):
        """
        Work out every child component's local inlet/outlet ports and write
        them to each component's LocalPortsJson. Called once per sync
        (Network.syncJunctionComponents), before the recompute that runs
        each component's own execute().

        Everything stays in absolute world coordinates -- DuctJunction/
        DuctSegment never use Placement, and this keeps that convention
        rather than introducing a local frame.

        The Primary always gets every one of the junction's real ports
        unchanged, no matter the topology/degree -- exactly the context a
        single fitting always received. Independently of that, each real
        edge may additionally carry its own chain of zero-or-more Inline
        components between the Primary and that edge's own external
        segment (see getPortChains()) -- a tee's branch leg and one of its
        run legs can each grow a completely independent chain, evaluated
        with that leg's own geometry alone.

        Every 2-port geometry backend (elbow, transition, damper, VAV)
        treats its two given ports as coincident at one shared anchor point
        and independently pushes each one outward, in that port's own
        direction, by a trim length that depends only on the component's
        own properties/profile -- never on where that anchor happens to sit
        in space. That position-independence is what makes this
        composition possible: for a given edge, the Primary's own trim on
        that port (peeked once, from its real multi-port geometry) plus
        each chain component's own (inner trim, outer trim) (each peeked
        once too) are summed into a running anchor per component -- see
        _peekConnectionLengths.
        """
        obj = self.Object
        try:
            analysis = json.loads(getattr(obj, "AnalysisJson", "") or "{}")
        except Exception:
            analysis = {}
        ports = list(analysis.get("connected_ports", []) or [])
        ports_by_edge = {p.get("edge_key"): p for p in ports}
        node_key = getattr(obj, "NodeKey", "")

        primary = self.getPrimaryComponent()
        if primary is None or not ports:
            return

        # Primary always gets every real port, unchanged. (Written only when
        # different: writing a property marks the component for recompute.)
        _set_if_changed(primary, "LocalPortsJson", json.dumps([_json_safe_port(p) for p in ports]))
        _set_if_changed(primary, "Profile", hvaclib.HVACLibraryService.match_profile_from_ports(ports))

        chains = {
            edge_key: chain for edge_key, chain in self.getPortChains().items() if edge_key in ports_by_edge and chain
        }
        if not chains:
            return

        # Peek the Primary's own trim on every real port ONCE -- using the
        # junction's REAL topology/family, since the Primary can now be a
        # branch/cross tee with a chain on just one of its legs.
        primary_trims = self._peekConnectionLengths(
            primary,
            ports,
            topology=getattr(obj, "Topology", "through"),
            family=getattr(obj, "Family", ""),
            analysis=analysis,
        )

        chained_lengths = {}
        for edge_key, chain in chains.items():
            real_port = ports_by_edge[edge_key]
            pos = HVACLibraryAPI.vec(real_port["position"])
            dir_e = HVACLibraryAPI.unit(real_port["direction"])
            into_e = real_port.get("flow_into_junction")
            trim_primary = primary_trims.get((edge_key, real_port.get("segment_end")), 0.0)

            # Build each chain component's own coincident inner/outer
            # templates -- inner always faces the Primary (direction -d),
            # outer always faces the segment (direction +d), regardless of
            # where the component sits in the chain -- and peek its own
            # (trim_in, trim_out).
            k = len(chain)
            inner_tpls, outer_tpls, trims_in, trims_out = [], [], [], []
            for j, comp_obj in enumerate(chain):
                inner_tpl = HVACLibraryAPI.copy_port(
                    real_port,
                    direction=dir_e * -1.0,
                    edge_key="{}#{}_seam{}".format(node_key, edge_key, j),
                    segment_end="end",
                )
                inner_tpl["flow_into_junction"] = not into_e
                inner_tpl["flow_role"] = "inlet" if not into_e else "outlet"

                if j == k - 1:
                    outer_tpl = dict(real_port)  # outermost: the real external interface
                else:
                    outer_tpl = HVACLibraryAPI.copy_port(
                        real_port,
                        direction=dir_e,
                        edge_key="{}#{}_seam{}".format(node_key, edge_key, j + 1),
                        segment_end="start",
                    )
                outer_tpl["flow_into_junction"] = into_e
                outer_tpl["flow_role"] = "outlet" if not into_e else "inlet"

                inner_tpls.append(inner_tpl)
                outer_tpls.append(outer_tpl)
                trims = self._peekConnectionLengths(
                    comp_obj, [inner_tpl, outer_tpl], topology="through", family="", analysis=analysis
                )
                trims_in.append(trims.get((inner_tpl["edge_key"], inner_tpl["segment_end"]), 0.0))
                trims_out.append(trims.get((outer_tpl["edge_key"], outer_tpl["segment_end"]), 0.0))

            # Running-sum anchors, always stepping outward along dir_e: the
            # first chain component's anchor is where the Primary's own
            # face ends AND where the first component's own body begins
            # (primary_trim + trims_in[0]); every later anchor adds the
            # previous component's own outward push to this one's own
            # inward push.
            anchors = [pos + dir_e * (trim_primary + trims_in[0])]
            for j in range(1, k):
                anchors.append(anchors[j - 1] + dir_e * (trims_out[j - 1] + trims_in[j]))

            for j, comp_obj in enumerate(chain):
                local_ports = [
                    HVACLibraryAPI.copy_port(inner_tpls[j], position=anchors[j]),
                    HVACLibraryAPI.copy_port(outer_tpls[j], position=anchors[j]),
                ]
                _set_if_changed(comp_obj, "LocalPortsJson", json.dumps([_json_safe_port(p) for p in local_ports]))
                _set_if_changed(comp_obj, "Profile", str(local_ports[1].get("profile", "") or ""))

            last_face = anchors[-1] + dir_e * trims_out[-1]
            chained_lengths[edge_key] = max(0.0, (last_face - pos).dot(dir_e))

        # Write ConnectionLengthsJson, merging this pass's chained-edge
        # entries into whatever was already there -- non-chained edges are
        # left for aggregateConnectionLengths() to fill from the Primary's
        # own post-execute report.
        try:
            existing = {
                item["edge_key"]: item for item in json.loads(getattr(obj, "ConnectionLengthsJson", "") or "[]")
            }
        except Exception:
            existing = {}
        for edge_key, length in chained_lengths.items():
            real_port = ports_by_edge[edge_key]
            existing[edge_key] = {"edge_key": edge_key, "segment_end": real_port.get("segment_end"), "length": length}
        obj.ConnectionLengthsJson = json.dumps(list(existing.values()))

    def _peekConnectionLengths(self, comp_obj, local_ports, topology, family, analysis):
        """
        Ask this component's own type how far it pushes out past each of
        its given (coincident) ports, purely to learn its own per-port
        trims -- via the type's own independently-declared
        connection_lengths measurement function (HVACLibraryRegistry.
        measure_connection_lengths()) when it has one, which measures
        without building any Shape at all. execute() (run right after
        composeComponents, via touch() + recompute()) then builds the real
        Shape separately, using the exact same layout calculation its own
        build_geometry() shares with that measurement function -- see
        freecad/HVAC/libraries/README.md's "connection_lengths" section.

        TODO(migration): a type with no connection_lengths function
        declared yet falls back to the old peek-via-build_geometry() path
        (building and discarding a full Shape, exactly as this method
        always did) -- remove this fallback branch once every library type
        that produces non-zero trims has migrated to an independent
        measurement function.

        local_ports can be an N-port list (the Primary, given its real
        ports) or a 2-port list (an Inline component's own inner/outer
        templates) -- both are handled identically here, and both go
        through this one dispatch regardless.

        Returns {(edge_key, segment_end): trim_length}; empty if the
        component has no type selected yet, or its type's measurement/
        geometry backend fails/reports nothing.
        """
        if _custom_fitting.is_custom(comp_obj) and getattr(comp_obj, "ComponentRole", "") == "Primary":
            try:
                return _custom_fitting.measure(comp_obj, local_ports)
            except Exception:
                return {}

        library_id = getattr(comp_obj, "LibraryId", "")
        type_id = getattr(comp_obj, "TypeId", "")
        if not library_id or not type_id:
            return {}

        try:
            reg = hvaclib.HVACLibraryService.get_hvac_library_registry()
            type_def = reg.resolve_type(library_id, type_id)
            if type_def is None:
                return {}
            params = reg.resolve_params(type_def, obj=comp_obj)
            context = {
                "obj": comp_obj,
                "center_point": HVACLibraryAPI.average_point([p["position"] for p in local_ports]),
                "properties": params,
                "connected_ports": local_ports,
                # Real topology analysis of this junction (unaffected by
                # chain composition) -- harmless/correct to pass through
                # even though no current through-topology generator reads
                # it, for consistency with DuctComponent.execute()'s own
                # context (see there for why this matters, e.g. build_tee).
                "analysis": analysis,
                "family": family,
                "topology": topology,
                "type_id": type_id,
                "library_id": library_id,
            }
            records = reg.measure_connection_lengths(library_id, type_def, context)
            if records is None:
                # Migration fallback (see TODO above) -- no independent
                # measurement function declared, so build (and discard)
                # the full geometry the same way this method always did.
                result = reg.build_geometry(library_id, type_def, context)
                records = reg.normalize_connection_lengths(result.connection_lengths, type_id)
        except Exception:
            return {}

        return {(item["edge_key"], item.get("segment_end")): item["length"] for item in records}

    def aggregateConnectionLengths(self):
        """
        Build the external trim contract (spec: DuctJunction.
        ConnectionLengthsJson is the only network-facing trimming contact),
        independently per real edge:

        - A chained edge's value was already computed and written by
          composeComponents() (needs the exact cumulative chain anchor
          geometry, not recoverable from any single component's own
          post-execute ConnectionLengthsJson) -- left untouched here.
        - A non-chained edge's value is a straight passthrough of the
          Primary's own reported trim on that port.
        """
        obj = self.Object
        primary = self.getPrimaryComponent()
        if primary is None:
            return

        real_edge_keys = set(getattr(obj, "ConnectedEdgeKeys", []) or [])
        chained_edge_keys = set(self.getPortChains().keys())

        try:
            primary_lengths = {
                item["edge_key"]: item for item in json.loads(getattr(primary, "ConnectionLengthsJson", "") or "[]")
            }
        except Exception:
            primary_lengths = {}
        try:
            existing = {
                item["edge_key"]: item for item in json.loads(getattr(obj, "ConnectionLengthsJson", "") or "[]")
            }
        except Exception:
            existing = {}

        out = {}
        for edge_key in real_edge_keys:
            if edge_key in chained_edge_keys:
                if edge_key in existing:
                    out[edge_key] = existing[edge_key]
            elif edge_key in primary_lengths:
                out[edge_key] = primary_lengths[edge_key]

        lengths_json = json.dumps(list(out.values()))
        if getattr(obj, "ConnectionLengthsJson", "") != lengths_json:
            obj.ConnectionLengthsJson = lengths_json

    @classmethod
    def create(cls, doc, name, owner, node_id, node_key, center_point, degree, topology):
        junction = doc.addObject("App::FeaturePython", name)
        cls(
            junction,
            owner=owner,
            node_id=node_id,
            node_key=node_key,
            center_point=center_point,
            degree=degree,
            topology=topology,
        )
        DuctJunctionViewProvider(junction.ViewObject)
        return junction

    @staticmethod
    def labelFor(family, node_id):
        family_label = str(family).capitalize() if family else "Junction"
        return "{} [{}]".format(family_label, int(node_id))

    @staticmethod
    def _addProperty(obj, prop_type, prop_name, group, description, attr=0):
        if prop_name not in obj.PropertiesList:
            obj.addProperty(prop_type, prop_name, group, description, attr)


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
        # Permit direct deletion from the tree -- e.g. of a stale junction
        # left over from an older schema that the owning network's own
        # sync loop never picked up for cleanup. Remove this junction's own
        # DuctComponent children first (found by ParentJunctionName rather
        # than through the owner network, since a genuinely orphaned
        # junction may have no resolvable owner) so they aren't left behind
        # as their own dangling orphans; then, if a live network still owns
        # this junction, ask it to resync afterwards, so anything still
        # topologically required gets regenerated fresh from library
        # defaults (see DuctNetwork.syncJunctions/syncJunctionComponents).
        obj = vobj.Object
        owner = hvaclib.getOwnerNetwork(obj)
        doc = obj.Document
        for comp in list(doc.Objects):
            if hvaclib.isDuctComponent(comp) and getattr(comp, "ParentJunctionName", "") == obj.Name:
                if doc.getObject(comp.Name) is not None:
                    doc.removeObject(comp.Name)
        if owner and getattr(owner, "Proxy", None):
            owner.Proxy.requestSync(force_recompute=True)
        return True

    def claimChildren(self):
        try:
            return self.Object.Proxy.getComponents()
        except Exception:
            return []

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
        self.updateMetadata(owner=owner, member_node_keys=member_node_keys or [], member_points=member_points or [])

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

    def updateMetadata(self, owner=None, member_node_keys=None, member_points=None):
        member_node_keys = list(member_node_keys or [])
        member_points = list(member_points or [])
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
                hvaclib.set_label(obj, "Virtual Junction ({})".format(len(keys)))
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
        return hvaclib.get_icon_path("DuctsIcon.svg")

    def onDelete(self, vobj, subelements):
        # User must be able to delete these directly from the tree.
        return True
