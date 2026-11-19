"""HVAC equipment (ROADMAP 6.5): summary arithmetic and result collection."""

import json
from types import SimpleNamespace

import pytest

import conftest  # noqa: F401 -- installs FreeCAD stubs
from freecad.HVAC.core import Equipment as eq


def _port(function, flow, worst, port="P", network="N"):
    return {"port": port, "function": function, "network": network, "flow_lps": flow, "worst_path_pa": worst}


def test_summary_adds_flows_and_fan_duties():
    ports = [
        _port("SupplyOutlet", 1000.0, 250.0),
        _port("SupplyOutlet", 500.0, 300.0),
        _port("ReturnInlet", 1200.0, 120.0),
        _port("OutdoorAirInlet", 300.0, 40.0),
    ]
    s = eq.equipment_summary(ports, internal_pressure_drop_pa=350.0)
    assert s["supply_lps"] == 1500.0 and s["return_lps"] == 1200.0
    assert s["outdoor_air_lps"] == 300.0 and not s["outdoor_air_is_estimate"]
    assert s["supply_fan_pa"] == pytest.approx(350.0 + 300.0 + 40.0)
    assert s["return_fan_pa"] == pytest.approx(120.0)


def test_outdoor_air_estimated_as_supply_minus_return():
    s = eq.equipment_summary([_port("SupplyOutlet", 1000.0, 200.0), _port("ReturnInlet", 800.0, 90.0)])
    assert s["outdoor_air_lps"] == pytest.approx(200.0) and s["outdoor_air_is_estimate"]


def test_uncalculated_networks_give_no_figures():
    s = eq.equipment_summary([_port("SupplyOutlet", None, None)])
    assert s["supply_lps"] is None and s["supply_fan_pa"] is None and s["return_fan_pa"] is None
    lines = eq.report_lines([_port("SupplyOutlet", None, None)], s)
    assert "-" in lines[0] and len(lines) == 3


class _Obj(SimpleNamespace):
    pass


def test_update_from_airflow_collects_this_network_and_keeps_the_others():
    doc = SimpleNamespace()
    supply_marker = _Obj(
        Name="PortS",
        Label="Supply",
        PropertiesList=["PortProfile", "EquipmentPortFunction"],
        EquipmentPortFunction="SupplyOutlet",
    )
    return_marker = _Obj(
        Name="PortR",
        Label="Return",
        PropertiesList=["PortProfile", "EquipmentPortFunction"],
        EquipmentPortFunction="ReturnInlet",
    )
    objects = {"PortS": supply_marker, "PortR": return_marker}
    doc.getObject = objects.get
    previous = {"PortR": _port("ReturnInlet", 900.0, 110.0, port="Return", network="RetNet")}
    equipment = _Obj(
        EquipmentType=eq.HVACEquipment.TYPE,
        Document=doc,
        Connections=["PortS|SupNet|node-1", "PortR|RetNet|node-9"],
        PortResultsJson=json.dumps(previous),
        InternalPressureDrop=300.0,
    )
    doc.Objects = [equipment]
    terminal = object()
    net = SimpleNamespace(
        Name="SupNet", Document=doc, Proxy=SimpleNamespace(collectJunctionObjects=lambda: {"node-1": terminal})
    )
    result = SimpleNamespace(
        components=[
            SimpleNamespace(
                junctions=[SimpleNamespace(obj=terminal, total_flow_lps=1000.0)], critical_pressure_pa=220.0
            )
        ]
    )
    eq.update_from_airflow(net, result)
    assert equipment.SupplyAirflow == 1000.0 and equipment.ReturnAirflow == 900.0
    assert equipment.OutdoorAirflow == pytest.approx(100.0)
    assert equipment.SupplyFanStatic == pytest.approx(520.0)
    assert equipment.ReturnFanStatic == pytest.approx(110.0)
    assert any("supply minus return" in line for line in equipment.Report)


def _marker(name, label):
    return _Obj(Name=name, Label=label, PropertiesList=["PortProfile"])


def test_equipment_ports_are_the_markers_inside_the_part_itself():
    # New equipment is the App::Part: its own members are its ports.
    port_b, port_a = _marker("P2", "B"), _marker("P1", "A")
    body = _Obj(Name="Body", Label="Body", PropertiesList=["Shape"])
    part = _Obj(Name="Part", Label="AHU", OutListRecursive=[body, port_b, port_a], EquipmentType=eq.HVACEquipment.TYPE)
    assert eq.model_of(part) is part
    assert eq.equipment_ports(part) == [port_a, port_b]


def test_an_older_equipment_object_reads_its_ports_through_model():
    port = _marker("P1", "A")
    model = _Obj(Name="Part", Label="AHU", OutListRecursive=[port])
    legacy = _Obj(Name="Equipment", Label="Equipment", Model=model, EquipmentType=eq.HVACEquipment.TYPE)
    assert eq.model_of(legacy) is model
    assert eq.equipment_ports(legacy) == [port]


def test_equipment_of_marker_finds_the_owning_equipment():
    port = _marker("P1", "A")
    stray = _marker("P9", "Z")
    part = _Obj(Name="Part", Label="AHU", OutListRecursive=[port], EquipmentType=eq.HVACEquipment.TYPE)
    other = _Obj(Name="Box", Label="Box", OutListRecursive=[stray])
    doc = SimpleNamespace(Objects=[other, part])
    port.Document = doc
    stray.Document = doc
    assert eq.equipment_of_marker(port) is part
    assert eq.equipment_of_marker(stray) is None
