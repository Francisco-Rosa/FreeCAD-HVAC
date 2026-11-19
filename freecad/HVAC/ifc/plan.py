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
The MEP part of an IFC export, worked out as plain data (ROADMAP design 6.8
B1): every element's ports, which ports connect, one system per network, one
type object per library type, the covering layers and the storeys.

Pure: the input is the dataclasses below (filled from a real document by
collect.py), the output an `IfcExportPlan` that writer.py turns into IFC
entities. Elements are named by an `element_id` (the FreeCAD object name);
the writer finds each one in the file by the GUID the exporter gave it.

How elements meet at a node. Along each duct leaving a node, the pieces sit
in this order, from the node outward:

    Primary fitting  ->  inline devices (Primary-outward)  ->  the duct

Each neighbour pair is connected through the ports that face each other.
Pieces with no solid (markers, placeholders) are not exported, so they are
skipped and their neighbours connect straight through. A node whose Primary
has no solid joins its ducts directly only when there are exactly two; with
more there is no single partner, and the plan says so in its warnings.
"""

from dataclasses import dataclass, field
from typing import Optional

from . import mapping

# Key of the extra port an equipment connection collar gets on its
# equipment side: its library ports only face the duct.
EQUIPMENT_SIDE_PORT = "equipment"

# ----------------------------------------------------------------------------
# Input
# ----------------------------------------------------------------------------


@dataclass
class PortInput:
    """
    One port of an element. `position` (mm) is where the element's face is,
    `direction` the unit vector pointing out of the element there. `flow_in`
    is True when air enters the element through this port, False when it
    leaves, None when unknown. Duct ports leave it None: the plan works it
    out from the node they meet.
    """

    key: str
    position: tuple
    direction: tuple
    flow_in: Optional[bool] = None


@dataclass
class LayerInput:
    """
    One construction layer: its roles and material, whether it has a shape
    to export, and the material's colour (r, g, b in 0..1, or None when the
    material has no appearance) and transparency (0..1).
    """

    layer_id: str
    roles: tuple = ()
    material: str = ""
    has_shape: bool = True
    color: Optional[tuple] = None
    transparency: float = 0.0


@dataclass
class ElementInput:
    """
    One exportable object: a duct, a fitting or device, or equipment.
    `type_key` groups elements under one IFC type object ("library:type"),
    empty for elements without a library type (equipment, custom models).
    Duct ports are keyed "start" and "end"; component ports by their edge
    key (LocalPortsJson); equipment ports by their marker name.
    """

    element_id: str
    label: str
    ifc_class: str
    predefined_type: str
    object_type: str = ""
    type_key: str = ""
    type_label: str = ""
    has_body: bool = True
    ports: list = field(default_factory=list)
    layers: list = field(default_factory=list)


@dataclass
class ChainLink:
    """One inline component on a duct leg: its port toward the Primary and its port toward the duct."""

    element_id: str
    inner_port: str
    outer_port: str


@dataclass
class EquipmentLink:
    """The equipment port an end node is connected to."""

    element_id: str
    port_key: str
    position: tuple
    direction: tuple  # out of the equipment


@dataclass
class NodeInput:
    """
    One node of a network. Per real edge (duct) at the node:
      flow_into_node[edge]  True when air flows from that duct into the node
      segment_end[edge]     which end of the duct is at the node ("start"/"end")
      chains[edge]          the inline components on that leg, Primary-outward
    The Primary's port toward each duct is keyed by the edge key itself.
    """

    node_key: str
    primary_id: str = ""
    edges: list = field(default_factory=list)
    flow_into_node: dict = field(default_factory=dict)
    segment_end: dict = field(default_factory=dict)
    chains: dict = field(default_factory=dict)
    equipment: Optional[EquipmentLink] = None


@dataclass
class NetworkInput:
    """
    One duct network. `segments` maps edge key -> element id of its duct.
    `level_id` names the storey (a key of build_plan's `levels`), or "".
    """

    network_id: str
    label: str
    system_type: str
    ifc_system_override: str = "Auto"
    level_id: str = ""
    elements: dict = field(default_factory=dict)
    segments: dict = field(default_factory=dict)
    nodes: list = field(default_factory=list)


# ----------------------------------------------------------------------------
# Output
# ----------------------------------------------------------------------------


@dataclass
class PortPlan:
    element_id: str
    key: str
    name: str
    position: tuple
    direction: tuple
    flow_direction: str
    system_type: str = ""


@dataclass
class ConnectionPlan:
    element_a: str
    port_a: str
    element_b: str
    port_b: str


@dataclass
class SystemPlan:
    system_id: str
    name: str
    long_name: str
    predefined_type: str
    member_ids: list = field(default_factory=list)


@dataclass
class TypePlan:
    type_id: str
    ifc_class: str  # the type class, e.g. "IfcDuctFittingType"
    predefined_type: str
    element_type: str
    name: str
    element_ids: list = field(default_factory=list)


@dataclass
class CoveringPlan:
    element_id: str
    layer_id: str
    predefined_type: str
    object_type: str
    material: str = ""
    color: Optional[tuple] = None
    transparency: float = 0.0


@dataclass
class MaterialPlan:
    """One body layer's material, for the element's IFC material and surface style."""

    layer_id: str
    material: str
    color: Optional[tuple] = None
    transparency: float = 0.0


@dataclass
class BodyMaterialPlan:
    """
    The materials of an element's body, in build order. The first one with a
    colour styles the whole body: features such as flanges take their host
    layer's look, which is the duct wall's.
    """

    element_id: str
    layers: list = field(default_factory=list)  # [MaterialPlan]


@dataclass
class IfcExportPlan:
    element_ids: list = field(default_factory=list)
    ports: list = field(default_factory=list)
    connections: list = field(default_factory=list)
    systems: list = field(default_factory=list)
    types: list = field(default_factory=list)
    coverings: list = field(default_factory=list)
    body_materials: list = field(default_factory=list)
    containment: dict = field(default_factory=dict)  # level id -> [element ids]
    warnings: list = field(default_factory=list)

    def ports_of(self, element_id):
        return [p for p in self.ports if p.element_id == element_id]


# ----------------------------------------------------------------------------
# Building the plan
# ----------------------------------------------------------------------------


def _negate(vector):
    return tuple(-float(c) for c in vector)


def _not_or_none(value):
    return None if value is None else (not value)


class _PlanBuilder:
    """Collects ports and connections, keeping each port once and naming ports per element."""

    def __init__(self):
        self.plan = IfcExportPlan()
        self._ports = {}  # (element id, key) -> PortPlan
        self._flow = {}  # (element id, key) -> flow_in override
        self._connected = set()

    def set_flow(self, element_id, key, flow_in):
        if flow_in is not None:
            self._flow[(element_id, key)] = flow_in

    def add_port(self, element, port, system_type):
        ident = (element.element_id, port.key)
        if ident in self._ports:
            return
        flow_in = self._flow.get(ident, port.flow_in)
        plan_port = PortPlan(
            element_id=element.element_id,
            key=port.key,
            name="",
            position=tuple(port.position),
            direction=tuple(port.direction),
            flow_direction=mapping.flow_direction(flow_in),
            system_type=system_type,
        )
        self._ports[ident] = plan_port
        self.plan.ports.append(plan_port)

    def connect(self, a, port_a, b, port_b):
        pair = frozenset([(a, port_a), (b, port_b)])
        if a == b or pair in self._connected:
            return
        self._connected.add(pair)
        self.plan.connections.append(ConnectionPlan(a, port_a, b, port_b))

    def finish(self):
        # Ports are named P1, P2, ... per element, in the order they were added.
        counts = {}
        for port in self.plan.ports:
            counts[port.element_id] = counts.get(port.element_id, 0) + 1
            port.name = "P{}".format(counts[port.element_id])
        # Drop connections to a port that was never emitted (an element
        # without that port, e.g. a duct missing its end data).
        self.plan.connections = [
            c
            for c in self.plan.connections
            if (c.element_a, c.port_a) in self._ports and (c.element_b, c.port_b) in self._ports
        ]
        return self.plan


def _with_body(elements, element_id):
    element = elements.get(element_id)
    return element if (element is not None and element.has_body) else None


def _leg_slots(network, node, edge_key):
    """
    The pieces along one duct leg at a node, from the node outward, as
    (element id, port facing the node, port facing away). The duct comes
    last; its far end is not part of this node.
    """
    slots = [(link.element_id, link.inner_port, link.outer_port) for link in node.chains.get(edge_key, [])]
    segment_id = network.segments.get(edge_key)
    end = node.segment_end.get(edge_key)
    if segment_id and end in ("start", "end"):
        slots.append((segment_id, end, None))
    return slots


def _plan_node(builder, network, node):
    """Step 2 of build_plan(): flow directions and connections at one node."""
    elements = network.elements
    primary = _with_body(elements, node.primary_id)
    innermost = {}  # edge key -> (element id, port facing the node)

    for edge_key in node.edges:
        into_node = node.flow_into_node.get(edge_key)

        # A duct's end at the node: air flowing into the node leaves the duct.
        segment_id = network.segments.get(edge_key)
        end = node.segment_end.get(edge_key)
        if segment_id and end in ("start", "end"):
            builder.set_flow(segment_id, end, _not_or_none(into_node))

        # Connect neighbours along the leg, skipping pieces without a body.
        bodied = [slot for slot in _leg_slots(network, node, edge_key) if _with_body(elements, slot[0])]
        for (a_id, _a_in, a_out), (b_id, b_in, _b_out) in zip(bodied, bodied[1:]):
            builder.connect(a_id, a_out, b_id, b_in)
        if bodied:
            innermost[edge_key] = (bodied[0][0], bodied[0][1])

    # The Primary to the innermost piece of each leg.
    if primary is not None:
        for edge_key, (element_id, port_key) in innermost.items():
            builder.connect(primary.element_id, edge_key, element_id, port_key)
    elif len(innermost) == 2:
        (a_id, a_port), (b_id, b_port) = innermost.values()
        builder.connect(a_id, a_port, b_id, b_port)
    elif len(innermost) > 2:
        builder.plan.warnings.append(
            "Node {} has no fitting body; its {} ducts are not connected in the IFC file".format(
                node.node_key, len(innermost)
            )
        )

    # An equipment connection: the collar's equipment side meets the equipment port.
    link = node.equipment
    if link is None or _with_body(elements, link.element_id) is None:
        return
    into_collar = node.flow_into_node.get(node.edges[0]) if node.edges else None
    builder.set_flow(link.element_id, link.port_key, into_collar)
    if primary is not None:
        collar_port = PortInput(EQUIPMENT_SIDE_PORT, link.position, _negate(link.direction), _not_or_none(into_collar))
        primary.ports.append(collar_port)
        builder.connect(primary.element_id, EQUIPMENT_SIDE_PORT, link.element_id, link.port_key)
    elif len(innermost) == 1:
        element_id, port_key = next(iter(innermost.values()))
        builder.connect(element_id, port_key, link.element_id, link.port_key)


def _type_id(element):
    return "{}|{}|{}|{}".format(element.type_key, element.ifc_class, element.predefined_type, element.object_type)


def build_plan(networks, equipment=(), levels=None):
    """
    Work out the MEP plan of an export.

    networks   [NetworkInput, ...]
    equipment  [ElementInput, ...]: equipment shared between networks
    levels     {level id: anything}: the storeys networks may name; a
               network naming an unknown level is left in the default one

    Returns an IfcExportPlan. Only elements with a body appear in it.
    """
    builder = _PlanBuilder()
    plan = builder.plan
    levels = levels or {}
    equipment_by_id = {e.element_id: e for e in equipment or ()}
    equipment_systems = {}  # equipment id -> [system ids]
    equipment_level = {}

    for network in networks:
        # Equipment is reachable from every network it serves.
        for element_id, element in equipment_by_id.items():
            network.elements.setdefault(element_id, element)
        system_enum, long_name = mapping.system_classification(network.system_type, network.ifc_system_override)

        # Step 1: which elements are exported.
        own_ids = sorted(
            element_id
            for element_id, element in network.elements.items()
            if element.has_body and element_id not in equipment_by_id
        )

        # Step 2: flow directions and connections, node by node.
        for node in sorted(network.nodes, key=lambda n: n.node_key):
            _plan_node(builder, network, node)
            if node.equipment is not None and node.equipment.element_id in equipment_by_id:
                equipment_systems.setdefault(node.equipment.element_id, []).append(network.network_id)
                if network.level_id in levels:
                    equipment_level.setdefault(node.equipment.element_id, network.level_id)

        # Step 3: ports of every exported element.
        for element_id in own_ids:
            element = network.elements[element_id]
            for port in element.ports:
                builder.add_port(element, port, system_enum)

        # Step 4: the network's system.
        plan.systems.append(
            SystemPlan(
                system_id=network.network_id,
                name=network.label,
                long_name=long_name,
                predefined_type=system_enum,
                member_ids=list(own_ids),
            )
        )
        if network.level_id in levels:
            plan.containment.setdefault(network.level_id, []).extend(own_ids)
        elif network.level_id:
            plan.warnings.append(
                "Network {}: its Level is not a building storey; left in the default storey".format(network.label)
            )
        plan.element_ids.extend(own_ids)

    # Step 5: equipment, in each system it serves.
    systems = {s.system_id: s for s in plan.systems}
    for element_id in sorted(equipment_by_id):
        element = equipment_by_id[element_id]
        if not element.has_body:
            continue
        plan.element_ids.append(element_id)
        served = equipment_systems.get(element_id, [])
        system_type = systems[served[0]].predefined_type if served else ""
        for port in element.ports:
            builder.add_port(element, port, system_type)
        for system_id in served:
            if element_id not in systems[system_id].member_ids:
                systems[system_id].member_ids.append(element_id)
        if element_id in equipment_level:
            plan.containment.setdefault(equipment_level[element_id], []).append(element_id)

    # Step 6: type objects, coverings and body materials of every exported element.
    all_elements = {}
    for network in networks:
        all_elements.update(network.elements)
    types = {}
    for element_id in plan.element_ids:
        element = all_elements[element_id]
        if element.type_key:
            type_id = _type_id(element)
            if type_id not in types:
                types[type_id] = TypePlan(
                    type_id=type_id,
                    ifc_class=element.ifc_class + "Type",
                    predefined_type=element.predefined_type,
                    element_type=element.object_type,
                    name=element.type_label or element.type_key,
                )
            types[type_id].element_ids.append(element_id)
        body = BodyMaterialPlan(element_id)
        for layer in element.layers:
            if not layer.has_shape:
                continue
            covering = mapping.covering_for_roles(layer.roles)
            if covering is None:
                if layer.material or layer.color is not None:
                    body.layers.append(MaterialPlan(layer.layer_id, layer.material, layer.color, layer.transparency))
                continue
            plan.coverings.append(
                CoveringPlan(
                    element_id=element_id,
                    layer_id=layer.layer_id,
                    predefined_type=covering[0],
                    object_type=covering[1],
                    material=layer.material,
                    color=layer.color,
                    transparency=layer.transparency,
                )
            )
        if body.layers:
            plan.body_materials.append(body)
    plan.types = [types[k] for k in sorted(types)]
    return builder.finish()
