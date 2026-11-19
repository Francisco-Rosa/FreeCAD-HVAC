"""Terminal function (ROADMAP 6.5): resolution, direction warnings, type filtering."""

import json
from types import SimpleNamespace

import pytest
from test_shipped_type_references import _load_registry

import conftest  # noqa: F401 -- installs FreeCAD stubs
from freecad.HVAC.core import _terminal_function as tf
from freecad.HVAC.core.FlowNetwork import terminal_direction_warnings


@pytest.mark.parametrize(
    "system, flow_class, expected",
    [
        ("Supply", "exit", "Supply"),
        ("Supply", "entry", "Source"),  # air comes in from the equipment
        ("Return", "entry", "Return"),
        ("Return", "exit", "Source"),  # air goes to the equipment
        ("Exhaust", "exit", "Source"),
        ("OutdoorAir", "entry", "OutdoorAir"),
    ],
)
def test_auto_follows_the_drawn_direction(system, flow_class, expected):
    # Whatever the boundary says: a fresh network leaves every terminal at FlowBoundary Auto.
    assert tf.resolve(system, "Auto", "Auto", flow_class) == expected
    assert tf.resolve(system, "Auto", "Fixed", flow_class) == expected


def test_balancing_warning():
    assert tf.balancing_warning("AHU", "Source", "Supply", "Auto") == ""
    assert tf.balancing_warning("D7", "Supply", "Supply", "Fixed") == ""
    assert "D7" in tf.balancing_warning("D7", "Supply", "Supply", "Auto")


@pytest.mark.parametrize(
    "system, setting, boundary, expected",
    [
        ("Supply", "Auto", "Fixed", "Supply"),
        ("Return", "Auto", "Fixed", "Return"),
        ("Exhaust", "Auto", "Closed", "Exhaust"),
        ("OutdoorAir", "Auto", "Fixed", "OutdoorAir"),
        ("Supply", "Auto", "Auto", "Source"),  # the balancing terminal
        ("Supply", "Discharge", "Auto", "Discharge"),  # an explicit setting wins
        ("Return", "Supply", "Fixed", "Supply"),
    ],
)
def test_resolve(system, setting, boundary, expected):
    assert tf.resolve(system, setting, boundary) == expected


@pytest.mark.parametrize(
    "function, system, flow_class",
    [
        ("Supply", "Supply", "exit"),
        ("Return", "Return", "entry"),
        ("Exhaust", "Exhaust", "entry"),
        ("OutdoorAir", "OutdoorAir", "entry"),
        ("Discharge", "Exhaust", "exit"),
        ("Source", "Supply", "entry"),
        ("Source", "Return", "exit"),
    ],
)
def test_expected_flow_class(function, system, flow_class):
    assert tf.expected_flow_class(function, system) == flow_class


def test_direction_warning_only_when_drawn_the_wrong_way():
    assert tf.direction_warning("T1", "Supply", "Supply", "exit") == ""
    assert tf.direction_warning("T1", "Supply", "Supply", "unknown") == ""
    message = tf.direction_warning("T1", "Supply", "Supply", "entry")
    assert "T1" in message and "inlet" in message and "outlet" in message


def _junction(label, flow_class, function, topology="end", boundary="Fixed"):
    return SimpleNamespace(
        Number="",
        Label=label,
        Name=label,
        Topology=topology,
        FlowBoundary=boundary,
        AnalysisJson=json.dumps({"flow_class": flow_class, "qualifiers": {"terminal_function": function}}),
    )


def test_network_warnings_name_each_wrong_terminal():
    net = SimpleNamespace(SystemType="Supply")
    junctions = {
        "a": _junction("Diffuser 1", "exit", "Supply"),
        "b": _junction("Diffuser 2", "entry", "Supply"),
        "c": _junction("AHU", "entry", "Source"),
        "d": _junction("Tee", "diverging", "", topology="branch"),
    }
    warnings = terminal_direction_warnings(net, junctions)
    assert len(warnings) == 1 and "Diffuser 2" in warnings[0]


_AIR_TERMINALS = {
    "end_diffuser_square",
    "end_diffuser_round",
    "end_diffuser_slot",
    "end_grille_generic",
    "end_register_generic",
}


@pytest.mark.parametrize("library_id", ["builtin_basic", "smacna"])
def test_air_terminals_are_offered_for_every_terminal_but_the_source(library_id):
    lib = _load_registry().get_library(library_id)
    ports = [{"profile": "Circular", "section_params": {"Diameter": 200.0}}]
    flow_classes = {"Supply": "exit", "Discharge": "exit", "Return": "entry", "Exhaust": "entry", "OutdoorAir": "entry"}

    def ids(function, flow_class):
        classification = {"flow_class": flow_class, "qualifiers": {"terminal_function": function}, "derived_values": {}}
        types = lib.list_types(
            category="junction",
            family="end.terminal",
            connected_ports=ports,
            classification=classification,
            include_placeholders=False,
        )
        return {t.id for t in types}

    for function, flow_class in flow_classes.items():
        assert _AIR_TERMINALS <= ids(function, flow_class), function
    assert not (_AIR_TERMINALS & ids("Source", "entry"))


def test_type_list_follows_the_terminal_function():
    lib = _load_registry().get_library("builtin_basic")

    def ids(function):
        classification = {"flow_class": "", "qualifiers": {"terminal_function": function}, "derived_values": {}}
        ports = [{"profile": "Circular", "section_params": {"Diameter": 200.0}}]
        types = lib.list_types(
            category="junction",
            family="end.terminal",
            connected_ports=ports,
            classification=classification,
            include_placeholders=False,
        )
        return {t.id for t in types}

    supply, outdoor = ids("Supply"), ids("OutdoorAir")
    assert "end_diffuser_round" in supply and "end_diffuser_round" in outdoor
    assert "end_diffuser_round" not in ids("Source")
    assert "end_hood_intake" in outdoor and "end_hood_intake" not in supply
    assert "end_entry_plain" in supply and "end_entry_plain" in outdoor  # unconstrained


def test_balancing_terminal_drawn_the_wrong_way_is_named_once_it_is_the_only_one():
    net = SimpleNamespace(SystemType="Supply")
    wrong = {"a": _junction("AHU", "exit", "Supply", boundary="Auto"), "b": _junction("D1", "exit", "Supply")}
    warnings = terminal_direction_warnings(net, wrong)
    assert len(warnings) == 1 and "AHU" in warnings[0] and "balances" in warnings[0]
    unconfigured = {k: _junction(k, "exit", "Supply", boundary="Auto") for k in ("D1", "D2", "D3")}
    assert terminal_direction_warnings(net, unconfigured) == []


# ----------------------------------------------------------------------------
# Which way the Source moves air: from the connected equipment port
# ----------------------------------------------------------------------------


def test_source_feeds_air_follows_the_equipment_port_else_the_system():
    assert tf.source_feeds_air("Supply") is True
    assert tf.source_feeds_air("Exhaust") is False
    assert tf.source_feeds_air("Exhaust", ["ExhaustOutlet"]) is True
    assert tf.source_feeds_air("Supply", ["ReturnInlet"]) is False
    assert tf.source_feeds_air("OutdoorAir", ["", "OutdoorAirInlet"]) is False


def test_an_exhaust_outlet_duct_has_a_feeding_source_and_discharge_terminals():
    # A duct from the AHU's exhaust outlet to outside: air comes in at the equipment end.
    assert tf.resolve("Exhaust", "Auto", "Auto", "entry", feeds=True) == "Source"
    assert tf.resolve("Exhaust", "Auto", "Fixed", "exit", feeds=True) == "Discharge"
    assert tf.expected_flow_class("Source", "Exhaust", feeds=True) == "entry"
    assert tf.direction_warning("T1", "Source", "Exhaust", "entry", feeds=True) == ""
    assert tf.direction_warning("T2", "Discharge", "Exhaust", "exit", feeds=True) == ""
    # Without the equipment it stays an ordinary exhaust system, drawn toward its fan.
    assert tf.resolve("Exhaust", "Auto", "Fixed", "entry") == "Exhaust"
    assert tf.direction_warning("T1", "Source", "Exhaust", "entry") != ""


def test_system_terminal_defaults():
    assert tf.system_terminal("Supply") == "Supply"
    assert tf.system_terminal("Return") == "Return"
    assert tf.system_terminal("Return", feeds=True) == "Discharge"
    assert tf.system_terminal("Supply", feeds=False) == "Supply"
