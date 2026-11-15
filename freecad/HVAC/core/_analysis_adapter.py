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
The one place a real FreeCAD DuctNetwork gets read into the pure
analysis/model.py dataclasses -- shared by FlowNetwork.py/AirflowSolver.py/
DuctSizer.py, so the "resolve a library type, build a properties dict, call
its loss formula" logic (previously copy-pasted between AirflowSolver.py's
and DuctSizer.py's own junction-loss code) lives in exactly one place.

Everything downstream of build_network_model() (analysis/flow.py,
pressure.py, sizing.py, paths.py, balancing.py) only ever sees plain
dataclasses/strings/callables -- never a FreeCAD object, a Proxy, a Shape,
or a library type-def.
"""

import json
import os
import re

from ..analysis import friction as friction_models
from ..analysis.model import AirState, ComponentModel, NetworkModel, NodeModel, PortModel, SectionModel, SegmentModel
from ..library.library_api import HVACLibraryAPI
from ..utils import hvaclib
from . import _custom_loss
from .Construction import construction_for

# A segment's own RectangularSizingMode enum value ("UseNetworkDefault" means
# "no override") -> the plain mode string SegmentModel/SizingSettings use.
RECT_MODE_MAP = {"FixedAspectRatio": "aspect_ratio", "FixedHeight": "fixed_height", "FixedWidth": "fixed_width"}


def element_identifier(obj):
    """User-facing element reference: documentation Number, then Label/Name."""
    number = str(getattr(obj, "Number", "") or "").strip()
    label = str(getattr(obj, "Label", "") or "").strip()
    name = str(getattr(obj, "Name", "") or "").strip()
    return number or label or name


def humanize_diagnostics(messages, segment_map, junction_map, component_map=None):
    """Replace internal edge/node/component keys in diagnostics with element IDs."""
    aliases = {}
    for mapping in (segment_map, junction_map, component_map or {}):
        for internal, obj in mapping.items():
            display = element_identifier(obj)
            if display and display != str(internal):
                aliases[str(internal)] = display
    patterns = [
        (re.compile(r"(?<![A-Za-z0-9_]){}(?![A-Za-z0-9_])".format(re.escape(key))), value)
        for key, value in sorted(aliases.items(), key=lambda item: len(item[0]), reverse=True)
    ]
    out = []
    for message in messages:
        text = str(message)
        for pattern, value in patterns:
            text = pattern.sub(value, text)
        out.append(text)
    return out


def network_element_index(objects):
    """
    {display identifier: object} for every segment, junction and component
    a warning may name. Each object is reachable by its element_identifier()
    (what humanize_diagnostics writes), its Label and its internal Name, so
    a message written either way can still be linked back to the object.
    The first object to claim an identifier keeps it.
    """
    index = {}
    for obj in objects:
        if obj is None:
            continue
        for ident in (element_identifier(obj), getattr(obj, "Label", ""), getattr(obj, "Name", "")):
            ident = str(ident or "").strip()
            if ident and ident not in index:
                index[ident] = obj
    return index


def link_spans(text, index):
    """
    Split a warning into [(piece, obj_or_None), ...] so a panel can show
    every element it names as a clickable link. An identifier only counts
    as a whole word (never inside a longer name), and longer identifiers win
    over shorter ones they contain. Joining the pieces gives `text` back.
    """
    text = str(text)
    keys = sorted((k for k in index if k), key=len, reverse=True)
    if not keys:
        return [(text, None)]
    pattern = re.compile(
        r"(?<![A-Za-z0-9_.-])(" + "|".join(re.escape(k) for k in keys) + r")(?![A-Za-z0-9_])(?!\.[A-Za-z0-9])"
    )
    spans = []
    last = 0
    for match in pattern.finditer(text):
        if match.start() > last:
            spans.append((text[last : match.start()], None))
        spans.append((match.group(1), index[match.group(1)]))
        last = match.end()
    if last < len(text):
        spans.append((text[last:], None))
    return spans or [(text, None)]


def build_network_model(net_obj):
    """
    Returns (network_model, segment_map, junction_map, component_map) --
    segment_map/junction_map/component_map keyed exactly like
    network_model's own edge_key/node_id/ComponentModel.component_id, so a
    caller can look up the real FreeCAD object for any pure result directly
    (e.g. to write Calc* properties back onto it). component_map covers
    every node's Primary and every edge's own Inline chain components.
    """
    parser = net_obj.Proxy.getParser(rebuild=True)
    segment_map = net_obj.Proxy.collectSegmentObjects()
    junction_map = net_obj.Proxy.collectJunctionObjects()
    reg = hvaclib.HVACLibraryService.get_hvac_library_registry()

    air = AirState(
        density_kg_m3=float(getattr(net_obj, "AirDensity", 1.204) or 1.204),
        kinematic_viscosity_m2_s=float(getattr(net_obj, "AirKinematicViscosity", 1.51e-5) or 1.51e-5),
    )
    default_roughness_mm = float(getattr(net_obj, "DefaultRoughness", 0.09) or 0.0)
    base_friction = network_friction_model(net_obj)

    edges = {}
    for u, v, edge_ref in parser.analysis_graph.edges(data="key"):
        edges[edge_ref.tag] = (parser.node_key(u), parser.node_key(v))

    segments = {}
    for edge_key, seg_obj in segment_map.items():
        segments[edge_key] = _build_segment_model(seg_obj, default_roughness_mm)
        segments[edge_key].friction_model = segment_friction_model(reg, seg_obj, base_friction, segments[edge_key])

    nodes = {}
    component_map = {}
    for node_id in parser.analysis_graph.nodes():
        if parser.analysis_graph.degree[node_id] == 0:
            continue  # isolated node, never reachable from any edge -- see flow.py
        node_key = parser.node_key(node_id)
        junction_obj = junction_map.get(node_key)
        if junction_obj is None:
            continue  # missing junction data -- analysis.flow reports this per-component, not fatal here
        ja = parser.build_junction_analysis(node_id, segment_map)
        if ja is None:
            continue
        nodes[node_key] = _build_node_model(
            node_key, junction_obj, ja, segment_map, reg, air, component_map, default_roughness_mm
        )

    network = NetworkModel(nodes=nodes, segments=segments, edges=edges, air=air)
    return network, segment_map, junction_map, component_map


# ----------------------------------------------------------------------------
# FreeCAD object -> pure dataclass
# ----------------------------------------------------------------------------


def _section_from_params(profile, section_params):
    section_params = section_params or {}
    return SectionModel(
        profile=str(profile or ""),
        diameter_mm=float(section_params.get("Diameter", 0.0) or 0.0),
        width_mm=float(section_params.get("Width", 0.0) or 0.0),
        height_mm=float(section_params.get("Height", 0.0) or 0.0),
    )


def _build_segment_model(seg_obj, default_roughness_mm):
    section = _section_from_params(getattr(seg_obj, "Profile", ""), hvaclib.get_segment_section_params(seg_obj))

    # The material on the flow-surface layer is authoritative. The network
    # default exists only for an unassigned material or an older card that
    # does not expose HydraulicRoughness.
    roughness_mm = float(construction_for(seg_obj).hydraulic_roughness(default_roughness_mm))

    rect_mode_raw = str(getattr(seg_obj, "RectangularSizingMode", "UseNetworkDefault") or "UseNetworkDefault")
    rect_mode_override = RECT_MODE_MAP.get(rect_mode_raw, "") if rect_mode_raw != "UseNetworkDefault" else ""

    edge_key = getattr(seg_obj, "SegmentKey", "") or seg_obj.Name
    return SegmentModel(
        edge_key=edge_key,
        section=section,
        length_mm=float(getattr(seg_obj, "EffectiveLength", 0.0) or 0.0),
        roughness_mm=roughness_mm,
        velocity_override_ms=float(getattr(seg_obj, "Velocity", 0.0) or 0.0),
        rectangular_mode_override=rect_mode_override,
        aspect_ratio_override=float(getattr(seg_obj, "TargetAspectRatio", 0.0) or 0.0),
    )


def _junction_ports_to_models(connected_ports, node_key):
    return [
        PortModel(
            edge_key=jp.edge_key,
            node_id=node_key,
            flow_into_node=jp.flow_into_junction,
            section=_section_from_params(jp.profile, jp.section_params),
            is_real_edge=True,
        )
        for jp in connected_ports
    ]


def _local_ports_to_models(local_ports_json, node_key, segment_map):
    ports = json.loads(local_ports_json or "[]")
    return [
        PortModel(
            edge_key=p.get("edge_key", ""),
            node_id=node_key,
            flow_into_node=p.get("flow_into_junction"),
            section=_section_from_params(p.get("profile", ""), p.get("section_params", {})),
            is_real_edge=p.get("edge_key", "") in segment_map,
        )
        for p in ports
    ]


def _stable_component_id(comp_obj):
    """
    A real DuctComponent always has a unique .Name -- fall back to Python's
    own object identity for anything that doesn't (e.g. a lightweight test
    double), so two distinct components can never collide onto the same
    key in component_map/analysis.pressure's per-component results.
    """
    name = getattr(comp_obj, "Name", "")
    return name if name else "id:{}".format(id(comp_obj))


def _build_node_model(node_key, junction_obj, ja, segment_map, reg, air, component_map, default_roughness_mm):
    ports = _junction_ports_to_models(ja.connected_ports, node_key)
    # The run pairs the classifier found, as edge_keys (its pairs index connected_ports).
    run_edge_pairs = []
    for pair in getattr(ja, "collinear_pairs", None) or []:
        try:
            run_edge_pairs.append((ja.connected_ports[pair.a].edge_key, ja.connected_ports[pair.b].edge_key))
        except (IndexError, AttributeError):
            continue
    design_flow_lps = float(getattr(junction_obj, "DesignFlowRate", 0.0) or 0.0)
    flow_boundary = str(getattr(junction_obj, "FlowBoundary", "Auto") or "Auto")

    primary_obj = junction_obj.Proxy.getPrimaryComponent()
    primary_component = None
    if primary_obj is not None:
        component_id = _stable_component_id(primary_obj)
        construction = construction_for(primary_obj)
        roughness_mm = float(construction.hydraulic_roughness(default_roughness_mm))
        primary_component = ComponentModel(
            component_id=component_id,
            role="primary",
            ports=_local_ports_to_models(getattr(primary_obj, "LocalPortsJson", "[]"), node_key, segment_map),
            loss_evaluator=build_loss_evaluator(
                reg,
                primary_obj,
                air,
                family=getattr(junction_obj, "Family", ""),
                construction=construction,
                hydraulic_roughness_mm=roughness_mm,
                flow_class=ja.flow_class,
                qualifiers=ja.qualifiers,
                derived_values=ja.derived_values,
            ),
            roughness_mm=roughness_mm,
        )
        component_map[component_id] = primary_obj

    inline_chains = {}
    for edge_key, chain in (junction_obj.Proxy.getPortChains() or {}).items():
        models = []
        for comp_obj in chain:
            component_id = _stable_component_id(comp_obj)
            construction = construction_for(comp_obj)
            roughness_mm = float(construction.hydraulic_roughness(default_roughness_mm))
            models.append(
                ComponentModel(
                    component_id=component_id,
                    role="inline",
                    ports=_local_ports_to_models(getattr(comp_obj, "LocalPortsJson", "[]"), node_key, segment_map),
                    # An Inline component has no Family of its own.
                    loss_evaluator=build_loss_evaluator(
                        reg, comp_obj, air, family="", construction=construction, hydraulic_roughness_mm=roughness_mm
                    ),
                    roughness_mm=roughness_mm,
                )
            )
            component_map[component_id] = comp_obj
        inline_chains[edge_key] = models

    return NodeModel(
        node_id=node_key,
        topology=ja.topology,
        degree=ja.degree,
        ports=ports,
        design_flow_lps=design_flow_lps,
        flow_boundary=flow_boundary,
        primary_component=primary_component,
        inline_chains=inline_chains,
        family=str(getattr(ja, "family", "") or ""),
        run_edge_pairs=run_edge_pairs,
        allow_size_change=bool(getattr(junction_obj, "AllowSizeChange", True)),
    )


def network_friction_model(net_obj):
    """
    The network-wide friction model from its FrictionModel property, or None
    for the default (Darcy-Weisbach with Altshul-Tsal). Raises ValueError
    with a readable message when the table file or the expression is bad.
    """
    choice = str(getattr(net_obj, "FrictionModel", "DarcyAltshulTsal") or "DarcyAltshulTsal")
    if choice == "DarcyAltshulTsal":
        return None
    if choice == "DarcyColebrook":
        return friction_models.DarcyWeisbach(friction_models.COLEBROOK)
    if choice == "Table":
        path = str(getattr(net_obj, "FrictionTableFile", "") or "")
        if not path:
            raise ValueError("FrictionModel is Table but FrictionTableFile is empty")
        try:
            with open(path, encoding="utf-8") as handle:
                text = handle.read()
        except OSError as exc:
            raise ValueError("Cannot read FrictionTableFile '{}': {}".format(path, exc)) from None
        return friction_models.TableFriction.from_csv(text, label="friction table {}".format(os.path.basename(path)))
    if choice == "Expression":
        return friction_models.ExpressionFriction(getattr(net_obj, "FrictionExpression", ""))
    raise ValueError("Unknown FrictionModel '{}'".format(choice))


def segment_friction_model(reg, seg_obj, base_model, seg_model):
    """
    The segment's friction model: its type-def's own "friction" factory
    (given the network's model to wrap) when it declares one, else the
    network's model.
    """
    library_id = getattr(seg_obj, "LibraryId", "")
    type_id = getattr(seg_obj, "TypeId", "")
    type_def = reg.resolve_type(library_id, type_id) if library_id and type_id else None
    if type_def is None or not getattr(type_def, "friction_module", ""):
        return base_model
    properties = {}
    for pdef in getattr(type_def, "properties", []) or []:
        properties[pdef.name] = getattr(seg_obj, pdef.name, getattr(pdef, "default", None))
    context = {
        "obj": seg_obj,
        "properties": properties,
        "roughness_mm": seg_model.roughness_mm,
        "base_model": base_model,
        "type_id": type_id,
        "library_id": library_id,
    }
    return reg.call_friction(library_id, type_def, context)


def custom_port_sections(comp_obj, local_ports):
    """
    A custom fitting's ports (ROADMAP 6.3) with each duct's profile and size
    replaced by the custom port it meets (CustomPortMapJson, written by the
    last fit), so the loss sees the fitting's own openings. Unchanged for a
    library component or before the first successful fit.
    """
    if str(getattr(comp_obj, "GeometrySource", "Library") or "Library") != "Custom":
        return local_ports
    try:
        port_map = json.loads(getattr(comp_obj, "CustomPortMapJson", "") or "{}")
    except ValueError:
        return local_ports
    out = []
    for port in local_ports:
        entry = port_map.get(port.get("edge_key"))
        if entry and entry.get("profile"):
            port = dict(port, profile=entry["profile"], section_params=dict(entry.get("section_params") or {}))
        out.append(port)
    return out


def build_loss_evaluator(
    reg,
    comp_obj,
    air,
    family="",
    construction=None,
    hydraulic_roughness_mm=0.0,
    flow_class="",
    qualifiers=None,
    derived_values=None,
):
    """
    A pure callable closing over everything FreeCAD/library-specific this
    component needs to evaluate its own loss -- see analysis/model.py's
    LossEvaluator type. Returns a LossEvaluation (see analysis/loss.py), or
    None only when this component's type itself can't be resolved at all
    (analysis/pressure.py's generic-K fallback then applies, exactly like
    an unresolved type did before this refactor) -- distinct from a
    resolved type's own loss function returning an UNSUPPORTED
    LossEvaluation for the current flow topology.

    flow_class/qualifiers/derived_values (NetworkParser.JunctionAnalysis --
    see TOPOLOGY_CLASSIFICATION.md) are only ever meaningful for a node's
    Primary component (an Inline component has no flow classification of
    its own, same reasoning as `family` above), and drive
    HVACLibraryRegistry.call_loss()'s own resolve_loss_variant() so one
    physical fitting TypeId can carry several flow-dependent loss formulas
    (e.g. an ordinary vs. bullhead tee) without a separate TypeId per case.

    If the component's own LossCoefficientSource is "Custom", the library's
    loss formula is bypassed entirely in favor of user-supplied per-port K
    values -- see _custom_loss.build_custom_loss_evaluator().
    """
    if str(getattr(comp_obj, "LossCoefficientSource", "Library") or "Library") == "Custom":
        return _custom_loss.build_custom_loss_evaluator(comp_obj)

    library_id = getattr(comp_obj, "LibraryId", "")
    type_id = getattr(comp_obj, "TypeId", "")
    type_def = reg.resolve_type(library_id, type_id) if library_id and type_id else None
    if type_def is None:
        return None

    properties = {}
    for pdef in getattr(type_def, "properties", []) or []:
        if hasattr(comp_obj, pdef.name):
            properties[pdef.name] = getattr(comp_obj, pdef.name)
        else:
            properties[pdef.name] = getattr(pdef, "default", None)

    local_ports = json.loads(getattr(comp_obj, "LocalPortsJson", "") or "[]")
    local_ports = custom_port_sections(comp_obj, local_ports)
    try:
        from . import Equipment

        equipment_port = Equipment.port_context(comp_obj)
    except Exception:
        equipment_port = None
    center_point = (
        HVACLibraryAPI.average_point([p["position"] for p in local_ports]) if local_ports else (0.0, 0.0, 0.0)
    )

    def evaluate(port_velocities):
        connected_ports_ctx = []
        for p in local_ports:
            p = dict(p)
            v = port_velocities.get(p.get("edge_key"), {})
            p["velocity_ms"] = v.get("velocity_ms", 0.0)
            p["flow_rate_lps"] = v.get("flow_lps", 0.0)
            p["reynolds"] = v.get("reynolds", 0.0)
            connected_ports_ctx.append(p)

        context = {
            "obj": comp_obj,
            "construction": construction,
            "hydraulic_roughness_mm": float(hydraulic_roughness_mm),
            "center_point": center_point,
            "properties": properties,
            "connected_ports": connected_ports_ctx,
            "family": family,
            "flow_class": flow_class,
            "qualifiers": dict(qualifiers or {}),
            "derived_values": dict(derived_values or {}),
            "type_id": type_id,
            "library_id": library_id,
            "air_density": air.density_kg_m3,
            "air_kinematic_viscosity": air.kinematic_viscosity_m2_s,
        }
        if equipment_port is not None:
            context["equipment_port"] = equipment_port
        return reg.call_loss(library_id, type_def, context)

    return evaluate
