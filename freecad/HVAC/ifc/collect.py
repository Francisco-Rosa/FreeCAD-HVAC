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
Reads duct networks of a FreeCAD document into the plain data plan.py takes
(ROADMAP design 6.8), plus the shapes the export needs:

- each element's body: the layers that are not coverings, plus its features,
  whatever their visibility in the 3D view (design 6.8 A6);
- each covering layer's own shape;
- the storeys networks name in their Level property.

Ports sit on the element's real faces: a component's ports in LocalPortsJson
are at the node, so each is pushed out along its direction by the
component's own trim on that port (ConnectionLengthsJson).
"""

import json
from dataclasses import dataclass, field

import FreeCAD
import Part

from ..core import Equipment, _custom_fitting, _ifc_properties
from ..core.Construction import construction_for
from ..utils import hvaclib
from ..utils import materials as hvac_materials
from . import mapping
from .plan import ChainLink, ElementInput, EquipmentLink, LayerInput, NetworkInput, NodeInput, PortInput


@dataclass
class Collected:
    networks: list = field(default_factory=list)
    equipment: list = field(default_factory=list)
    objects: dict = field(default_factory=dict)  # element id -> FreeCAD object
    bodies: dict = field(default_factory=dict)  # element id -> Part.Shape
    coverings: dict = field(default_factory=dict)  # (element id, layer id) -> Part.Shape
    levels: dict = field(default_factory=dict)  # level id -> {"label", "elevation_mm", "guid", "object"}
    warnings: list = field(default_factory=list)


def _xyz(value):
    if hasattr(value, "x"):
        return (float(value.x), float(value.y), float(value.z))
    return tuple(float(c) for c in value)


def _shifted(position, direction, length):
    p, d = _xyz(position), _xyz(direction)
    return tuple(p[i] + d[i] * float(length) for i in range(3))


def _has_geometry(shape):
    return shape is not None and not shape.isNull() and bool(shape.Solids or shape.Faces)


# ----------------------------------------------------------------------------
# Shapes
# ----------------------------------------------------------------------------


def _custom_source(comp_obj):
    """What a custom fitting's geometry comes from: its App::Link at the node, or the model where it was made."""
    if _custom_fitting.is_in_place(comp_obj):
        return getattr(comp_obj, "CustomFitting", None)
    return comp_obj.Document.getObject(str(getattr(comp_obj, "CustomLinkName", "") or ""))


def _custom_shape(comp_obj):
    """The shape of a custom fitting (ROADMAP 6.3)."""
    source = _custom_source(comp_obj)
    if source is None:
        return None
    try:
        return Part.getShape(source, "", needSubElement=False, transform=True)
    except Exception:
        return None


def body_and_coverings(obj):
    """
    (body shape or None, {layer id: covering shape}) of a segment or
    component. Layer visibility is ignored: a layer hidden in the view is
    still part of the element.
    """
    if hvaclib.isDuctComponent(obj) and _custom_fitting.is_custom(obj):
        shape = _custom_shape(obj)
        return (shape if _has_geometry(shape) else None), {}

    construction = construction_for(obj)
    body_parts = []
    coverings = {}
    for layer in construction.layers():
        if not _has_geometry(layer.shape):
            continue
        if mapping.covering_for_roles(layer.roles) is None:
            body_parts.append(layer.shape)
        else:
            coverings[layer.id] = layer.shape
    for feature in construction.features():
        if feature.enabled and _has_geometry(feature.shape):
            body_parts.append(feature.shape)
    if not body_parts and not coverings and _has_geometry(getattr(obj, "Shape", None)):
        body_parts.append(obj.Shape)  # an object with no layer shapes at all
    return (Part.makeCompound(body_parts) if body_parts else None), coverings


# ----------------------------------------------------------------------------
# Elements
# ----------------------------------------------------------------------------


def _trims(comp_obj):
    try:
        entries = json.loads(getattr(comp_obj, "ConnectionLengthsJson", "") or "[]")
    except ValueError:
        return {}
    out = {}
    for entry in entries or []:
        out[(entry.get("edge_key"), entry.get("segment_end"))] = float(entry.get("length", 0.0) or 0.0)
    return out


def _local_ports(comp_obj):
    try:
        return json.loads(getattr(comp_obj, "LocalPortsJson", "") or "[]")
    except ValueError:
        return []


def _component_ports(comp_obj):
    trims = _trims(comp_obj)
    ports = []
    for port in _local_ports(comp_obj):
        key = str(port.get("edge_key", "") or "")
        if not key or port.get("position") is None or port.get("direction") is None:
            continue
        trim = trims.get((key, port.get("segment_end")), 0.0)
        ports.append(
            PortInput(
                key=key,
                position=_shifted(port["position"], port["direction"], trim),
                direction=_xyz(port["direction"]),
                flow_in=port.get("flow_into_junction"),
            )
        )
    return ports


def _segment_ports(seg_obj):
    start_dir = _xyz(seg_obj.StartDirection)
    return [
        PortInput("start", _xyz(seg_obj.EffectiveStartPoint), tuple(-c for c in start_dir)),
        PortInput("end", _xyz(seg_obj.EffectiveEndPoint), _xyz(seg_obj.EndDirection)),
    ]


def _appearance(material):
    """(colour (r, g, b) in 0..1 or None, transparency 0..1) of a layer material, as the 3D view draws it."""
    try:
        appearance = hvac_materials.get_view_appearance(material)
    except Exception:
        appearance = None
    if appearance is None:
        return None, 0.0
    color = tuple(float(c) for c in tuple(appearance.DiffuseColor)[:3])
    return color, float(getattr(appearance, "Transparency", 0.0) or 0.0)


def _model_layer(source):
    """
    A single body "layer" for a user model (equipment, a custom fitting):
    the material and look of its first solid. The solid's ShapeMaterial
    when one is assigned; otherwise only the colour it is drawn with (GUI
    only). None when neither is known.
    """
    if source is None:
        return None
    linked = getattr(source, "LinkedObject", None) or source
    members = [linked] + list(getattr(linked, "OutListRecursive", []) or [])
    for member in members:
        shape = getattr(member, "Shape", None)
        if not (member.isDerivedFrom("Part::Feature") and shape is not None and shape.Solids):
            continue
        material = getattr(member, "ShapeMaterial", None)
        if material is not None and hvac_materials.is_material_assigned(material):
            color, transparency = _appearance(material)
            return LayerInput("body", ("structural_shell",), str(material.Name), True, color, transparency)
        try:
            appearance = member.ViewObject.ShapeAppearance[0]
            color = tuple(float(c) for c in tuple(appearance.DiffuseColor)[:3])
            transparency = float(appearance.Transparency or 0.0)
        except Exception:
            return None
        return LayerInput("body", ("structural_shell",), "", True, color, transparency)
    return None


def _layer_inputs(obj, coverings):
    out = []
    for layer in construction_for(obj).layers():
        assigned = layer.material is not None and hvac_materials.is_material_assigned(layer.material)
        material = str(getattr(layer.material, "Name", "") or "") if assigned else ""
        color, transparency = _appearance(layer.material) if assigned else (None, 0.0)
        has_shape = layer.id in coverings or mapping.covering_for_roles(layer.roles) is None
        out.append(LayerInput(layer.id, tuple(layer.roles), material, has_shape, color, transparency))
    return out


def _type_label(obj):
    library_id, type_id = getattr(obj, "LibraryId", ""), getattr(obj, "TypeId", "")
    if not (library_id and type_id):
        return ""
    reg = hvaclib.HVACLibraryService.get_hvac_library_registry()
    type_def = reg.resolve_type(library_id, type_id)
    return str(getattr(type_def, "label", "") or type_id) if type_def else type_id


def _element(collected, obj, ports, custom=False):
    """An ElementInput for a segment or component, recording its shapes on `collected`."""
    body, coverings = body_and_coverings(obj)
    library_id, type_id = getattr(obj, "LibraryId", ""), getattr(obj, "TypeId", "")
    element = ElementInput(
        element_id=obj.Name,
        label=str(obj.Label),
        ifc_class=mapping.ifc_class_from_bim_name(getattr(obj, "IfcType", "")) or mapping.DUCT_FITTING,
        predefined_type=str(getattr(obj, "PredefinedType", "") or "NOTDEFINED"),
        object_type=str(getattr(obj, "ObjectType", "") or ""),
        type_key="" if custom or not (library_id and type_id) else "{}:{}".format(library_id, type_id),
        type_label="" if custom else _type_label(obj),
        has_body=body is not None,
        ports=ports,
        layers=[layer for layer in [_model_layer(_custom_source(obj))] if layer]
        if custom
        else _layer_inputs(obj, coverings),
    )
    collected.objects[obj.Name] = obj
    if body is not None:
        collected.bodies[obj.Name] = body
    for layer_id, shape in coverings.items():
        collected.coverings[(obj.Name, layer_id)] = shape
    return element


def _equipment_element(collected, equipment):
    _ifc_properties.ensure_equipment(equipment)
    ports = []
    for marker in Equipment.equipment_ports(equipment):
        placement = marker.getGlobalPlacement()
        ports.append(
            PortInput(marker.Name, _xyz(placement.Base), _xyz(placement.Rotation.multVec(FreeCAD.Vector(0, 0, 1))))
        )
    try:
        body = Part.getShape(Equipment.model_of(equipment), "", needSubElement=False, transform=True)
    except Exception:
        body = None
    body = body if _has_geometry(body) else None
    collected.objects[equipment.Name] = equipment
    if body is not None:
        collected.bodies[equipment.Name] = body
    else:
        collected.warnings.append("Equipment '{}' has no solid; it is left out".format(equipment.Label))
    return ElementInput(
        element_id=equipment.Name,
        label=str(equipment.Label),
        ifc_class=mapping.ifc_class_from_bim_name(equipment.IfcType) or mapping.EQUIPMENT_DEFAULT[0],
        predefined_type=str(equipment.PredefinedType or "NOTDEFINED"),
        object_type=str(getattr(equipment, "ObjectType", "") or ""),
        has_body=body is not None,
        ports=ports,
        layers=[layer for layer in [_model_layer(Equipment.model_of(equipment))] if layer],
    )


# ----------------------------------------------------------------------------
# Networks
# ----------------------------------------------------------------------------


def _global_placement(obj):
    """getGlobalPlacement() where the object has it (older Arch floors do not), else its Placement."""
    try:
        return obj.getGlobalPlacement()
    except AttributeError:
        return getattr(obj, "Placement", FreeCAD.Placement())


def _level(collected, net):
    """The level id of a network's Level, recording the storey on `collected`; "" when none is set."""
    level = getattr(net, "Level", None)
    if level is None:
        return ""
    if str(getattr(level, "IfcType", "") or "") != "Building Storey":
        # Left out of collected.levels on purpose: the plan then warns.
        return level.Name
    data = dict(getattr(level, "IfcData", {}) or {})
    collected.levels[level.Name] = {
        "label": str(level.Label),
        "elevation_mm": float(_global_placement(level).Base.z),
        "guid": str(data.get("IfcUID", "") or getattr(level, "GlobalId", "") or ""),
        "object": level,
    }
    return level.Name


def _node_input(collected, net_input, junction, equipment_inputs):
    try:
        analysis = json.loads(getattr(junction, "AnalysisJson", "") or "{}")
    except ValueError:
        analysis = {}
    node = NodeInput(node_key=str(junction.NodeKey))
    for port in analysis.get("connected_ports", []) or []:
        edge_key = str(port.get("edge_key", "") or "")
        if not edge_key:
            continue
        node.edges.append(edge_key)
        node.flow_into_node[edge_key] = port.get("flow_into_junction")
        node.segment_end[edge_key] = port.get("segment_end")

    # The Primary fitting.
    primary = junction.Proxy.getPrimaryComponent()
    if primary is not None:
        net_input.elements[primary.Name] = _element(
            collected, primary, _component_ports(primary), custom=_custom_fitting.is_custom(primary)
        )
        node.primary_id = primary.Name

    # Inline components, leg by leg.
    for edge_key, chain in (junction.Proxy.getPortChains() or {}).items():
        links = []
        for comp_obj in chain:
            ports = _local_ports(comp_obj)
            if len(ports) != 2:
                continue
            net_input.elements[comp_obj.Name] = _element(collected, comp_obj, _component_ports(comp_obj))
            links.append(ChainLink(comp_obj.Name, str(ports[0].get("edge_key", "")), str(ports[1].get("edge_key", ""))))
        node.chains[edge_key] = links

    # An equipment port this end is connected to.
    marker = Equipment.connected_port(junction) if getattr(junction, "Topology", "") == "end" else None
    equipment = Equipment.equipment_of_marker(marker) if marker is not None else None
    if equipment is not None:
        if equipment.Name not in equipment_inputs:
            equipment_inputs[equipment.Name] = _equipment_element(collected, equipment)
        placement = marker.getGlobalPlacement()
        node.equipment = EquipmentLink(
            equipment.Name, marker.Name, _xyz(placement.Base), _xyz(placement.Rotation.multVec(FreeCAD.Vector(0, 0, 1)))
        )
    return node


def collect(networks):
    """Read `networks` (DuctNetwork objects) into a Collected."""
    collected = Collected()
    equipment_inputs = {}
    for net in networks:
        _ifc_properties.refresh_network(net)
        net_input = NetworkInput(
            network_id=net.Name,
            label=str(net.Label),
            system_type=str(getattr(net, "SystemType", "Supply") or "Supply"),
            ifc_system_override=str(getattr(net, "IfcSystemType", "Auto") or "Auto"),
            level_id=_level(collected, net),
        )
        for edge_key, seg_obj in net.Proxy.collectSegmentObjects().items():
            net_input.elements[seg_obj.Name] = _element(collected, seg_obj, _segment_ports(seg_obj))
            net_input.segments[edge_key] = seg_obj.Name
        for junction in net.Proxy.collectJunctionObjects().values():
            net_input.nodes.append(_node_input(collected, net_input, junction, equipment_inputs))
        collected.networks.append(net_input)
    collected.equipment = [equipment_inputs[k] for k in sorted(equipment_inputs)]
    return collected
