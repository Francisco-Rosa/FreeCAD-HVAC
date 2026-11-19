# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the HVAC addon.

"""
IFC export plan (ROADMAP design 6.8 B1): ports, port connections, flow
directions, systems, type objects, coverings and storeys, from plain network
data. Pure code.
"""

from freecad.HVAC.ifc import plan as ifc_plan
from freecad.HVAC.ifc.plan import ChainLink, ElementInput, EquipmentLink, LayerInput, NetworkInput, NodeInput, PortInput

X = (1.0, 0.0, 0.0)
NX = (-1.0, 0.0, 0.0)


def _duct(element_id, start, end, type_key="lib:circular_straight"):
    return ElementInput(
        element_id,
        element_id,
        "IfcDuctSegment",
        "RIGIDSEGMENT",
        type_key=type_key,
        type_label="Round duct",
        ports=[PortInput("start", start, NX), PortInput("end", end, X)],
        layers=[LayerInput("casing", ("flow_surface", "structural_shell"), "Steel")],
    )


def _fitting(element_id, ports, ifc_class="IfcDuctFitting", predefined="BEND", has_body=True, type_key="lib:elbow"):
    return ElementInput(
        element_id,
        element_id,
        ifc_class,
        predefined,
        type_key=type_key,
        has_body=has_body,
        ports=[PortInput(key, pos, d, flow_in) for key, pos, d, flow_in in ports],
    )


def _two_duct_network(primary_has_body=True, chain=None):
    """
    Terminal T (N1) -- duct A -- elbow E (N2) -- duct B -- source S (N3).
    Air flows from N3 to N1, i.e. B runs into N2 and A runs out of it.
    Ducts are drawn N1 -> N2 -> N3, so A ends at N2 and B starts there.
    """
    elements = {
        "A": _duct("A", (0, 0, 0), (900, 0, 0)),
        "B": _duct("B", (1100, 0, 0), (2000, 0, 0)),
        "E": _fitting("E", [("eA", (900, 0, 0), NX, False), ("eB", (1100, 0, 0), X, True)], has_body=primary_has_body),
        "T": _fitting("T", [("eA", (0, 0, 0), X, True)], ifc_class="IfcAirTerminal", predefined="DIFFUSER"),
    }
    nodes = [
        NodeInput("N1", "T", ["eA"], {"eA": True}, {"eA": "start"}),
        NodeInput("N2", "E", ["eA", "eB"], {"eA": False, "eB": True}, {"eA": "end", "eB": "start"}, chain or {}),
        NodeInput("N3", "", ["eB"], {"eB": False}, {"eB": "end"}),
    ]
    return NetworkInput("Net1", "Supply 1", "Supply", elements=elements, segments={"eA": "A", "eB": "B"}, nodes=nodes)


def _pairs(plan):
    return {frozenset([(c.element_a, c.port_a), (c.element_b, c.port_b)]) for c in plan.connections}


def _port(plan, element_id, key):
    return next(p for p in plan.ports if p.element_id == element_id and p.key == key)


def test_ducts_connect_to_the_fittings_at_their_ends():
    plan = ifc_plan.build_plan([_two_duct_network()])
    assert _pairs(plan) == {
        frozenset([("T", "eA"), ("A", "start")]),
        frozenset([("E", "eA"), ("A", "end")]),
        frozenset([("E", "eB"), ("B", "start")]),
    }
    assert sorted(plan.element_ids) == ["A", "B", "E", "T"]
    assert plan.warnings == []


def test_flow_directions():
    plan = ifc_plan.build_plan([_two_duct_network()])
    # Air runs B -> E -> A -> T.
    assert _port(plan, "B", "start").flow_direction == "SOURCE"
    assert _port(plan, "B", "end").flow_direction == "SINK"
    assert _port(plan, "E", "eB").flow_direction == "SINK"
    assert _port(plan, "E", "eA").flow_direction == "SOURCE"
    assert _port(plan, "A", "end").flow_direction == "SINK"
    assert _port(plan, "A", "start").flow_direction == "SOURCE"
    assert _port(plan, "T", "eA").flow_direction == "SINK"


def test_ports_are_named_per_element_and_keep_their_geometry():
    plan = ifc_plan.build_plan([_two_duct_network()])
    assert [p.name for p in plan.ports_of("A")] == ["P1", "P2"]
    assert _port(plan, "B", "start").position == (1100, 0, 0)
    assert _port(plan, "B", "start").direction == NX
    assert {p.system_type for p in plan.ports} == {"VENTILATION"}


def test_bodiless_primary_on_two_ducts_joins_them():
    plan = ifc_plan.build_plan([_two_duct_network(primary_has_body=False)])
    assert "E" not in plan.element_ids
    assert frozenset([("A", "end"), ("B", "start")]) in _pairs(plan)
    assert not plan.ports_of("E")


def test_bodiless_primary_on_three_ducts_warns():
    network = _two_duct_network(primary_has_body=False)
    network.elements["C"] = _duct("C", (1000, 100, 0), (1000, 900, 0))
    network.segments["eC"] = "C"
    node = network.nodes[1]
    node.edges.append("eC")
    node.flow_into_node["eC"] = False
    node.segment_end["eC"] = "start"
    plan = ifc_plan.build_plan([network])
    assert any("N2" in w and "3 ducts" in w for w in plan.warnings)
    assert not any(("C", "start") in pair for pair in _pairs(plan))


def test_inline_chain_sits_between_the_primary_and_the_duct():
    network = _two_duct_network(chain={"eB": [ChainLink("D1", "s0", "s1"), ChainLink("D2", "s1", "eB")]})
    network.elements["D1"] = _fitting(
        "D1",
        [("s0", (1100, 0, 0), NX, False), ("s1", (1150, 0, 0), X, True)],
        ifc_class="IfcDamper",
        predefined="BALANCINGDAMPER",
        type_key="lib:damper",
    )
    network.elements["D2"] = _fitting(
        "D2",
        [("s1", (1150, 0, 0), NX, False), ("eB", (1200, 0, 0), X, True)],
        ifc_class="IfcDuctSilencer",
        predefined="ROUND",
        type_key="lib:silencer",
    )
    pairs = _pairs(ifc_plan.build_plan([network]))
    assert frozenset([("E", "eB"), ("D1", "s0")]) in pairs
    assert frozenset([("D1", "s1"), ("D2", "s1")]) in pairs
    assert frozenset([("D2", "eB"), ("B", "start")]) in pairs
    assert frozenset([("E", "eB"), ("B", "start")]) not in pairs


def test_bodiless_inline_component_is_skipped():
    network = _two_duct_network(chain={"eB": [ChainLink("M", "s0", "eB")]})
    network.elements["M"] = _fitting(
        "M", [("s0", (1100, 0, 0), NX, None), ("eB", (1100, 0, 0), X, None)], has_body=False
    )
    plan = ifc_plan.build_plan([network])
    assert frozenset([("E", "eB"), ("B", "start")]) in _pairs(plan)
    assert "M" not in plan.element_ids


def test_equipment_connection():
    network = _two_duct_network()
    collar = _fitting(
        "C",
        [("eB", (2000, 0, 0), NX, False)],
        ifc_class="IfcDuctFitting",
        predefined="USERDEFINED",
        type_key="lib:end_equipment_connection",
    )
    network.elements["C"] = collar
    network.nodes[2].primary_id = "C"
    network.nodes[2].equipment = EquipmentLink("AHU", "SupplyPort", (2100, 0, 0), X)
    ahu = ElementInput(
        "AHU",
        "AHU-1",
        "IfcUnitaryEquipment",
        "AIRHANDLER",
        ports=[PortInput("SupplyPort", (2100, 0, 0), X), PortInput("ReturnPort", (2100, 500, 0), X)],
    )
    plan = ifc_plan.build_plan([network], equipment=[ahu])
    pairs = _pairs(plan)
    assert frozenset([("C", "eB"), ("B", "end")]) in pairs
    assert frozenset([("C", ifc_plan.EQUIPMENT_SIDE_PORT), ("AHU", "SupplyPort")]) in pairs
    # Air leaves the unit into the collar, then into the duct.
    assert _port(plan, "AHU", "SupplyPort").flow_direction == "SOURCE"
    assert _port(plan, "C", ifc_plan.EQUIPMENT_SIDE_PORT).flow_direction == "SINK"
    assert _port(plan, "C", ifc_plan.EQUIPMENT_SIDE_PORT).direction == NX
    assert _port(plan, "AHU", "ReturnPort").flow_direction == "NOTDEFINED"
    assert "AHU" in plan.systems[0].member_ids
    assert plan.element_ids.count("AHU") == 1


def test_equipment_shared_by_two_networks_joins_both_systems():
    supply = _two_duct_network()
    supply.nodes[2].equipment = EquipmentLink("AHU", "S", (2000, 0, 0), X)
    ret = _two_duct_network()
    ret.network_id, ret.label, ret.system_type = "Net2", "Return 1", "Return"
    ret.nodes[2].equipment = EquipmentLink("AHU", "R", (2000, 0, 0), X)
    ahu = ElementInput(
        "AHU",
        "AHU-1",
        "IfcUnitaryEquipment",
        "AIRHANDLER",
        ports=[PortInput("S", (2000, 0, 0), X), PortInput("R", (2000, 500, 0), X)],
    )
    plan = ifc_plan.build_plan([supply, ret], equipment=[ahu])
    assert [s.system_id for s in plan.systems] == ["Net1", "Net2"]
    assert all("AHU" in s.member_ids for s in plan.systems)
    # No primary at N3: the duct end meets the equipment port directly.
    assert frozenset([("B", "end"), ("AHU", "S")]) in _pairs(plan)


def test_system():
    network = _two_duct_network()
    network.ifc_system_override = "AIRCONDITIONING"
    system = ifc_plan.build_plan([network]).systems[0]
    assert (system.system_id, system.name, system.long_name) == ("Net1", "Supply 1", "Supply air")
    assert system.predefined_type == "AIRCONDITIONING"
    assert sorted(system.member_ids) == ["A", "B", "E", "T"]


def test_type_objects_group_by_library_type_and_class():
    network = _two_duct_network()
    network.elements["T2"] = _fitting(
        "T2", [("x", (0, 0, 0), X, True)], ifc_class="IfcDuctFitting", predefined="EXIT", type_key="lib:hood"
    )
    network.elements["T3"] = _fitting(
        "T3", [("y", (0, 0, 0), X, False)], ifc_class="IfcDuctFitting", predefined="ENTRY", type_key="lib:hood"
    )
    network.elements["X"] = _fitting("X", [], type_key="")
    plan = ifc_plan.build_plan([network])
    by_name = {}
    for t in plan.types:
        by_name.setdefault(t.name, []).append(t)
    ducts = by_name["Round duct"]
    assert len(ducts) == 1 and ducts[0].ifc_class == "IfcDuctSegmentType"
    assert sorted(ducts[0].element_ids) == ["A", "B"]
    # One library type exported as two predefined types gets two type objects.
    assert sorted(t.predefined_type for t in by_name["lib:hood"]) == ["ENTRY", "EXIT"]
    assert not any("X" in t.element_ids for t in plan.types)


def test_coverings_from_layer_roles():
    network = _two_duct_network()
    network.elements["A"].layers.append(LayerInput("insulation", ("thermal_insulation",), "Mineral wool"))
    network.elements["A"].layers.append(LayerInput("liner", ("flow_surface", "acoustic_absorber"), "", has_shape=False))
    coverings = ifc_plan.build_plan([network]).coverings
    assert len(coverings) == 1
    covering = coverings[0]
    assert (covering.element_id, covering.layer_id) == ("A", "insulation")
    assert (covering.predefined_type, covering.object_type, covering.material) == (
        "INSULATION",
        "Thermal insulation",
        "Mineral wool",
    )


def test_containment_by_level():
    network = _two_duct_network()
    network.level_id = "Level1"
    plan = ifc_plan.build_plan([network], levels={"Level1": None})
    assert sorted(plan.containment["Level1"]) == ["A", "B", "E", "T"]

    unknown = _two_duct_network()
    unknown.level_id = "Nowhere"
    plan = ifc_plan.build_plan([unknown], levels={})
    assert plan.containment == {}
    assert any("Level" in w for w in plan.warnings)
