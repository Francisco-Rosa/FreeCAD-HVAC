# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the HVAC addon.

"""
Losses of terminals, equipment and plenums: a device rated by a fixed
pressure drop, the plenum box, and the shared loss functions that pick
between them from a type's own properties.
"""

import pytest

import conftest  # noqa: F401 -- installs FreeCAD/FreeCADGui/Part/PySide stubs
from freecad.HVAC.library.fittings import losses
from freecad.HVAC.library.loss_api import HVACLossAPI as api

AIR_DENSITY = 1.2


def _port(edge_key, into_node, velocity_ms=5.0, flow_lps=100.0, diameter=200.0):
    return {
        "edge_key": edge_key,
        "position": [0.0, 0.0, 0.0],
        "direction": [1.0, 0.0, 0.0],
        "profile": "Circular",
        "section_params": {"Diameter": diameter},
        "flow_into_junction": into_node,
        "velocity_ms": velocity_ms,
        "flow_rate_lps": flow_lps,
    }


def _context(ports, properties=None):
    return {
        "connected_ports": list(ports),
        "properties": dict(properties or {}),
        "air_density": AIR_DENSITY,
        "loss_api": api,
    }


def _k(result):
    assert len(result.paths) == 1
    return result.paths[0].loss_coefficient


# ----------------------------------------------------------------------------
# fixed_pressure_drop_loss
# ----------------------------------------------------------------------------


def test_fixed_pressure_drop_gives_the_k_that_reproduces_it():
    result = api.fixed_pressure_drop_loss(_context([_port("D1", True, velocity_ms=4.0)], {"PressureDrop": 24.0}))
    assert result.status == api.EXACT
    # Velocity pressure = 1.2 * 4^2 / 2 = 9.6 Pa, so K = 24 / 9.6.
    assert _k(result) == pytest.approx(2.5)
    path = result.paths[0]
    assert (path.from_edge_key, path.to_edge_key, path.reference_edge_key) == ("D1", None, "D1")
    assert path.source == "fixed_pressure_drop"


def test_fixed_pressure_drop_of_an_inline_device_refers_to_its_outlet():
    ports = [_port("IN", True, velocity_ms=8.0), _port("OUT", False, velocity_ms=4.0)]
    result = api.fixed_pressure_drop_loss(_context(ports, {"PressureDrop": 48.0}))
    assert _k(result) == pytest.approx(5.0)
    path = result.paths[0]
    assert (path.from_edge_key, path.to_edge_key, path.reference_edge_key) == ("IN", "OUT", "OUT")


def test_fixed_pressure_drop_without_flow_is_no_loss():
    result = api.fixed_pressure_drop_loss(_context([_port("D1", True, velocity_ms=0.0)], {"PressureDrop": 24.0}))
    assert result.status == api.EXACT
    assert _k(result) == 0.0


@pytest.mark.parametrize("properties", [{}, {"PressureDrop": 0.0}])
def test_fixed_pressure_drop_needs_a_value(properties):
    result = api.fixed_pressure_drop_loss(_context([_port("D1", True)], properties))
    assert result.status == api.UNSUPPORTED


def test_fixed_pressure_drop_needs_the_air_density():
    context = _context([_port("D1", True)], {"PressureDrop": 24.0})
    del context["air_density"]
    assert api.fixed_pressure_drop_loss(context).status == api.UNSUPPORTED


def test_fixed_pressure_drop_is_not_for_a_junction():
    ports = [_port("A", True), _port("B", False), _port("C", False)]
    assert api.fixed_pressure_drop_loss(_context(ports, {"PressureDrop": 24.0})).status == api.UNSUPPORTED


# ----------------------------------------------------------------------------
# plenum_loss
# ----------------------------------------------------------------------------


def test_plenum_is_an_exit_into_the_box_and_an_entry_out_of_it():
    ports = [_port("IN", True, velocity_ms=6.0), _port("OUT", False, velocity_ms=3.0)]
    result = api.plenum_loss(_context(ports))
    assert result.status == api.APPROXIMATION
    # Entry 0.5 on the outlet, exit 1.0 on the inlet: 0.5 + 1.0 * (6 / 3)^2.
    assert _k(result) == pytest.approx(4.5)
    path = result.paths[0]
    assert (path.from_edge_key, path.to_edge_key, path.reference_edge_key) == ("IN", "OUT", "OUT")


def test_plenum_gives_one_path_per_inlet_and_outlet_pair():
    ports = [
        _port("IN1", True, velocity_ms=4.0),
        _port("IN2", True, velocity_ms=2.0),
        _port("OUT1", False, velocity_ms=4.0),
        _port("OUT2", False, velocity_ms=2.0),
        _port("OUT3", False, velocity_ms=1.0),
    ]
    result = api.plenum_loss(_context(ports))
    by_pair = {(p.from_edge_key, p.to_edge_key): p for p in result.paths}
    assert len(by_pair) == 6
    assert by_pair[("IN1", "OUT1")].loss_coefficient == pytest.approx(1.5)
    assert by_pair[("IN2", "OUT1")].loss_coefficient == pytest.approx(0.75)
    assert by_pair[("IN1", "OUT3")].loss_coefficient == pytest.approx(16.5)
    assert all(p.reference_edge_key == p.to_edge_key for p in result.paths)


def test_plenum_outlet_without_flow_has_no_loss():
    ports = [_port("IN", True, velocity_ms=6.0), _port("OUT", False, velocity_ms=0.0)]
    assert _k(api.plenum_loss(_context(ports))) == 0.0


def test_plenum_needs_an_inlet_and_an_outlet():
    assert api.plenum_loss(_context([_port("A", False), _port("B", False)])).status == api.UNSUPPORTED
    assert api.plenum_loss(_context([_port("A", True), _port("B", True)])).status == api.UNSUPPORTED


def test_loss_plenum_calls_the_plenum_loss():
    ports = [_port("IN", True, velocity_ms=3.0), _port("OUT", False, velocity_ms=3.0)]
    assert _k(losses.loss_plenum(_context(ports))) == pytest.approx(1.5)


# ----------------------------------------------------------------------------
# LossMode: coefficient or fixed pressure drop
# ----------------------------------------------------------------------------


def test_diffuser_uses_its_coefficient_by_default():
    # A 200 mm neck on a 200 mm duct: K at the neck is K at the duct.
    port = _port("D1", True, velocity_ms=airspeed(100.0, 200.0))
    result = losses.loss_diffuser_generic(_context([port], {"LossCoefficient": 1.5, "NeckSize": 200.0}))
    assert result.paths[0].source == "terminal_device"
    assert _k(result) == pytest.approx(1.5)


def airspeed(flow_lps, diameter_mm):
    """Velocity in a round duct, so a test port's flow and velocity agree."""
    area = 3.141592653589793 * (diameter_mm / 1000.0) ** 2 / 4.0
    return (flow_lps / 1000.0) / area


@pytest.mark.parametrize("mode", ["Fixed pressure drop", "fixed_pressure_drop"])
def test_diffuser_in_fixed_pressure_drop_mode_ignores_its_coefficient(mode):
    properties = {"LossMode": mode, "PressureDrop": 24.0, "LossCoefficient": 99.0, "NeckSize": 200.0}
    result = losses.loss_diffuser_generic(_context([_port("D1", True, velocity_ms=4.0)], properties))
    assert result.paths[0].source == "fixed_pressure_drop"
    assert _k(result) == pytest.approx(2.5)


def test_register_adds_its_damper_to_the_grille():
    port = _port("D1", True, velocity_ms=airspeed(100.0, 200.0))
    properties = {"LossCoefficient": 1.5, "DamperLossCoefficient": 0.5, "NeckSize": 200.0}
    context = _context([port], properties)
    assert _k(losses.loss_register_generic(context)) == pytest.approx(2.0)
    # The caller's own properties are left as they were.
    assert context["properties"]["LossCoefficient"] == 1.5


def test_register_in_fixed_pressure_drop_mode():
    properties = {"LossMode": "Fixed pressure drop", "PressureDrop": 9.6, "DamperLossCoefficient": 0.5}
    result = losses.loss_register_generic(_context([_port("D1", True, velocity_ms=4.0)], properties))
    assert _k(result) == pytest.approx(1.0)


def test_vav_box_coefficient_and_fixed_pressure_drop():
    ports = [_port("IN", True, velocity_ms=4.0), _port("OUT", False, velocity_ms=4.0)]
    assert _k(losses.loss_vav_generic(_context(ports, {"LossCoefficient": 1.5}))) == pytest.approx(1.5)
    fixed = {"LossMode": "Fixed pressure drop", "PressureDrop": 48.0, "LossCoefficient": 1.5}
    assert _k(losses.loss_vav_generic(_context(ports, fixed))) == pytest.approx(5.0)


# ----------------------------------------------------------------------------
# Inline devices: silencer, filter, coil, fire damper, access door, flex connector
# ----------------------------------------------------------------------------


def _inline_ports():
    # Velocity pressure at 4 m/s: 1.2 * 16 / 2 = 9.6 Pa.
    out = _port("OUT", False, velocity_ms=4.0)
    out["direction"] = [1.0, 0.0, 0.0]
    inlet = _port("IN", True, velocity_ms=4.0)
    inlet["direction"] = [-1.0, 0.0, 0.0]
    return [inlet, out]


@pytest.mark.parametrize("condition, drop", [("Clean", 80.0), ("Mid-life", 165.0), ("Final", 250.0)])
def test_filter_pressure_drop_follows_its_condition(condition, drop):
    properties = {"CleanPressureDrop": 80.0, "FinalPressureDrop": 250.0, "FilterCondition": condition}
    assert losses.filter_pressure_drop(properties) == pytest.approx(drop)
    result = losses.loss_inline_device(_context(_inline_ports(), properties))
    assert result.status == api.EXACT
    assert _k(result) == pytest.approx(drop / 9.6)
    assert result.paths[0].source == "fixed_pressure_drop"


def test_filter_final_drop_below_the_clean_one_is_taken_as_the_clean_one():
    properties = {"CleanPressureDrop": 100.0, "FinalPressureDrop": 50.0, "FilterCondition": "Final"}
    assert losses.filter_pressure_drop(properties) == pytest.approx(100.0)


def test_filter_condition_must_be_known():
    with pytest.raises(ValueError):
        losses.filter_pressure_drop({"CleanPressureDrop": 80.0, "FilterCondition": "Dusty"})


def test_inline_device_in_fixed_pressure_drop_mode_ignores_its_coefficient():
    properties = {"LossMode": "Fixed pressure drop", "PressureDrop": 48.0, "LossCoefficient": 3.0}
    assert _k(losses.loss_inline_device(_context(_inline_ports(), properties))) == pytest.approx(5.0)


def test_inline_device_uses_its_coefficient():
    properties = {"LossMode": "Coefficient", "PressureDrop": 48.0, "LossCoefficient": 0.2}
    result = losses.loss_inline_device(_context(_inline_ports(), properties))
    assert result.status == api.EXACT
    assert _k(result) == pytest.approx(0.2)
    assert result.paths[0].source == "inline_device"


def test_inline_device_with_no_coefficient_has_no_loss_of_its_own():
    result = losses.loss_inline_device(_context(_inline_ports(), {"LossCoefficient": 0.0}))
    assert result.status != api.UNSUPPORTED
    assert sum(path.loss_coefficient for path in result.paths) == pytest.approx(0.0)


# ----------------------------------------------------------------------------
# Entry and exit types: each loss function fixes the shape the table is read for
# ----------------------------------------------------------------------------


def _entry(properties=None):
    # Air entering the system flows OUT of the terminal node into its duct.
    return _context([_port("D1", False)], properties)


def _exit(properties=None):
    return _context([_port("D1", True)], properties)


@pytest.mark.parametrize(
    "function, source",
    [
        (losses.loss_entry_plain, "smacna_entry_duct_in_wall"),
        (losses.loss_entry_bellmouth, "smacna_entry_bellmouth"),
        (losses.loss_entry_conical, "smacna_entry_conical"),
        (losses.loss_hood_intake, "smacna_entry_intake_hood"),
        (losses.loss_hood_tapered, "smacna_entry_tapered_hood"),
    ],
)
def test_entry_functions_read_their_own_table(function, source):
    properties = {"LipRadius": 10.0, "ConeAngle": 30.0, "ConeLength": 50.0, "HoodAngle": 0.0, "HoodHeight": 100.0}
    result = function(_entry(properties))
    assert result.status != api.UNSUPPORTED
    assert result.paths[0].source == source


@pytest.mark.parametrize(
    "function, source",
    [
        (losses.loss_exit_plain, "smacna_exit_abrupt"),
        (losses.loss_exit_conical, "smacna_exit_conical"),
        (losses.loss_exit_pyramidal, "smacna_exit_pyramidal_diffuser"),
        (losses.loss_hood_exhaust, "smacna_exit_exhaust_hood"),
    ],
)
def test_exit_functions_read_their_own_table(function, source):
    properties = {"ConeAngle": 14.0, "AreaRatio": 2.0, "HoodAngle": 0.0, "HoodHeight": 100.0}
    result = function(_exit(properties))
    assert result.status != api.UNSUPPORTED
    assert result.paths[0].source == source


def test_plain_entry_and_exit_values():
    assert _k(losses.loss_entry_plain(_entry())) == pytest.approx(0.50)
    assert _k(losses.loss_exit_plain(_exit())) == pytest.approx(1.0)


def test_a_type_fixes_its_shape_whatever_the_properties_say():
    # A stray EntryType on the object must not turn a bellmouth into something else.
    result = losses.loss_entry_bellmouth(_entry({"EntryType": "conical", "LipRadius": 10.0}))
    assert result.paths[0].source == "smacna_entry_bellmouth"


def test_pyramidal_exit_type_can_be_a_plane_diffuser():
    properties = {"DiffuserType": "Plane", "ConeAngle": 14.0, "AreaRatio": 2.0}
    assert losses.loss_exit_pyramidal(_exit(properties)).paths[0].source == "smacna_exit_plane_diffuser"


def test_an_entry_type_on_air_that_leaves_is_unsupported():
    assert losses.loss_entry_plain(_exit()).status == api.UNSUPPORTED
    assert losses.loss_exit_plain(_entry()).status == api.UNSUPPORTED
