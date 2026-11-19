"""
Focused tests for core/_component_results.py: serializing/deserializing
CalcPortResultsJson, deciding whether a component is a multiport Primary
(the case where its scalar Calc* properties are ambiguous), and the
combined write_port_results() helper AirflowSolver.py uses to persist a
solved ComponentResult onto a real DuctComponent object.
"""

from types import SimpleNamespace

import conftest  # noqa: F401 -- installs FreeCAD/FreeCADGui/Part/PySide stubs

from freecad.HVAC.core import _component_results
from freecad.HVAC.analysis.pressure import ComponentPortResult


def _obj(**kwargs):
    return SimpleNamespace(**kwargs)


# ----------------------------------------------------------------------
# serialize_port_results / deserialize_port_results
# ----------------------------------------------------------------------

def test_serialize_deserialize_round_trips_all_fields():
    port_results = {
        "B": ComponentPortResult(
            edge_key="B", flow_lps=850.0, velocity_ms=5.2, loss_coefficient=0.21,
            pressure_drop_pa=3.4, static_pressure_pa=187.2,
            from_edge_key="A", to_edge_key="B", status="exact",
        ),
        "C": ComponentPortResult(
            edge_key="C", flow_lps=350.0, velocity_ms=4.1, loss_coefficient=1.08,
            pressure_drop_pa=10.9, static_pressure_pa=None,
            from_edge_key="C", to_edge_key=None, status="custom",
        ),
    }
    raw = _component_results.serialize_port_results(port_results)
    restored = _component_results.deserialize_port_results(raw)

    assert restored["B"] == port_results["B"]
    assert restored["C"] == port_results["C"]


def test_deserialize_empty_or_missing_json_returns_empty_dict():
    assert _component_results.deserialize_port_results("") == {}
    assert _component_results.deserialize_port_results(None) == {}


def test_deserialize_invalid_json_returns_empty_dict_instead_of_raising():
    assert _component_results.deserialize_port_results("{not valid json") == {}


# ----------------------------------------------------------------------
# is_multiport_primary
# ----------------------------------------------------------------------

def test_is_multiport_primary_true_only_for_a_primary_with_more_than_two_ports():
    tee = _obj(ComponentRole="Primary", LocalPortsJson='[{"edge_key":"A"},{"edge_key":"B"},{"edge_key":"C"}]')
    elbow = _obj(ComponentRole="Primary", LocalPortsJson='[{"edge_key":"A"},{"edge_key":"B"}]')
    terminal = _obj(ComponentRole="Primary", LocalPortsJson='[{"edge_key":"A"}]')
    inline = _obj(ComponentRole="Inline", LocalPortsJson='[{"edge_key":"A"},{"edge_key":"B"}]')
    not_yet_composed = _obj(ComponentRole="Primary", LocalPortsJson="[]")

    assert _component_results.is_multiport_primary(tee) is True
    assert _component_results.is_multiport_primary(elbow) is False
    assert _component_results.is_multiport_primary(terminal) is False
    assert _component_results.is_multiport_primary(inline) is False
    assert _component_results.is_multiport_primary(not_yet_composed) is False


# ----------------------------------------------------------------------
# write_port_results
# ----------------------------------------------------------------------

class FakeComponentObj:
    def __init__(self, component_role="Primary", local_ports_json="[]"):
        self.ComponentRole = component_role
        self.LocalPortsJson = local_ports_json
        self.CalcPortResultsJson = "{}"
        self.CalcFlowRate = 0.0
        self.CalcVelocity = 0.0
        self.CalcLossCoefficient = 0.0
        self.CalcPressureDrop = 0.0


def test_write_port_results_populates_scalars_for_a_single_unambiguous_result():
    obj = FakeComponentObj(local_ports_json='[{"edge_key":"A"},{"edge_key":"B"}]')
    port_results = {
        "B": ComponentPortResult(edge_key="B", flow_lps=80.0, velocity_ms=5.0, loss_coefficient=0.4, pressure_drop_pa=6.0),
    }
    _component_results.write_port_results(obj, port_results)

    assert obj.CalcFlowRate == 80.0
    assert obj.CalcVelocity == 5.0
    assert obj.CalcLossCoefficient == 0.4
    assert obj.CalcPressureDrop == 6.0
    assert _component_results.deserialize_port_results(obj.CalcPortResultsJson) == port_results


def test_write_port_results_resets_scalars_to_zero_for_a_multiport_primary():
    obj = FakeComponentObj(local_ports_json='[{"edge_key":"A"},{"edge_key":"B"},{"edge_key":"C"}]')
    obj.CalcFlowRate = 999.0  # stale value from a previous, different solve
    port_results = {
        "B": ComponentPortResult(edge_key="B", flow_lps=700.0, velocity_ms=5.0, loss_coefficient=0.18, pressure_drop_pa=3.0),
        "C": ComponentPortResult(edge_key="C", flow_lps=300.0, velocity_ms=4.0, loss_coefficient=1.05, pressure_drop_pa=9.0),
    }
    _component_results.write_port_results(obj, port_results)

    # Do NOT use max/average/sum-of-K as a substitute -- reset to 0 and hide
    # (editor mode is Component.py's own job) instead of showing anything
    # potentially misleading for a multiport fitting.
    assert obj.CalcFlowRate == 0.0
    assert obj.CalcVelocity == 0.0
    assert obj.CalcLossCoefficient == 0.0
    assert obj.CalcPressureDrop == 0.0
    # The authoritative data is still fully retained in CalcPortResultsJson.
    assert _component_results.deserialize_port_results(obj.CalcPortResultsJson) == port_results


def test_write_port_results_resets_scalars_when_there_is_no_result_at_all():
    obj = FakeComponentObj(local_ports_json='[{"edge_key":"A"},{"edge_key":"B"}]')
    obj.CalcFlowRate = 42.0  # stale from a previous solve
    _component_results.write_port_results(obj, {})

    assert obj.CalcFlowRate == 0.0
    assert obj.CalcPortResultsJson == "{}"


def test_write_port_results_recalculation_fully_replaces_stale_data_not_merges():
    obj = FakeComponentObj(local_ports_json='[{"edge_key":"A"},{"edge_key":"B"}]')
    first = {"B": ComponentPortResult(edge_key="B", flow_lps=80.0, velocity_ms=5.0, loss_coefficient=0.4, pressure_drop_pa=6.0)}
    _component_results.write_port_results(obj, first)

    second = {"B": ComponentPortResult(edge_key="B", flow_lps=40.0, velocity_ms=2.5, loss_coefficient=0.4, pressure_drop_pa=1.5)}
    _component_results.write_port_results(obj, second)

    assert _component_results.deserialize_port_results(obj.CalcPortResultsJson) == second
    assert obj.CalcFlowRate == 40.0
    assert obj.CalcPressureDrop == 1.5
