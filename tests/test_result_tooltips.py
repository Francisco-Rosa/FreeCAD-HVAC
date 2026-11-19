"""Stage 9 item 1: result tooltip text builders (core/_component_results.py)."""

from types import SimpleNamespace

import conftest  # noqa: F401 -- installs FreeCAD stubs
from freecad.HVAC.core import _component_results as cr


def _seg(**kw):
    base = dict(
        flow_lps=120.0,
        velocity_ms=3.82,
        friction_loss_pa=4.0,
        fitting_loss_pa=1.5,
        total_loss_pa=5.5,
        cumulative_pressure_pa=42.0,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _row(**kw):
    base = dict(
        leg_label="D02",
        path_label="D01 → D02",
        status="exact",
        flow_lps=80.0,
        velocity_ms=4.1,
        loss_coefficient=0.35,
        pressure_drop_pa=3.2,
        static_pressure_pa=20.0,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_segment_tooltip_has_rate_from_length():
    text = cr.segment_tooltip("D01", _seg(), length_mm=2000.0)
    assert text.splitlines()[0] == "Duct D01"
    assert "Length: 2.00 m" in text and "Friction rate: 2.00 Pa/m" in text
    assert "Velocity: 3.82 m/s" in text and "Cumulative pressure: 42.0 Pa" in text


def test_segment_tooltip_without_length_has_no_rate():
    text = cr.segment_tooltip("D01", _seg(), length_mm=0.0)
    assert "Friction rate: -" in text and "Length" not in text


def test_port_tooltip_with_and_without_a_fitting_result():
    bare = cr.port_tooltip("Node J1, leg D02", 80.0, 20.0)
    assert bare.splitlines() == ["Node J1, leg D02", "Flow: 80.0 L/s", "Static pressure: 20.0 Pa"]
    full = cr.port_tooltip("Node J1, leg D02", 80.0, 20.0, _row())
    assert "K: 0.350" in full and "Loss: exact (D01 → D02)" in full
    assert "K: -" in cr.port_tooltip("x", 1.0, None, _row(loss_coefficient=None))


def test_component_tooltip_lists_every_leg():
    text = cr.component_tooltip("Tee [Primary]", [_row(), _row(path_label="D01 → D03", status="approximation")])
    assert text.count("\n") == 2 and "approximation" in text
    assert "No fitting loss" in cr.component_tooltip("Cap", [])
