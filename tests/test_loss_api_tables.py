# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the HVAC addon.

"""
HVACLossAPI's table-driven entry points: entry, exit, screen, damper and
obstruction losses. Checks the property contract, the path each returns and
when a result is downgraded from EXACT to APPROXIMATION.
"""

import math

import pytest

import conftest  # noqa: F401 -- installs FreeCAD/FreeCADGui/Part/PySide stubs
from freecad.HVAC.library.loss_api import HVACLossAPI as api


def _port(edge_key, into_node, profile="Circular", velocity_ms=5.0, **section):
    if not section:
        section = {"Diameter": 200.0}
    return {
        "edge_key": edge_key,
        "position": [0.0, 0.0, 0.0],
        "direction": [1.0, 0.0, 0.0],
        "profile": profile,
        "section_params": dict(section),
        "flow_into_junction": into_node,
        "velocity_ms": velocity_ms,
    }


def _terminal(properties, entering=True, **port_kwargs):
    # Air entering the system flows OUT of the terminal node into its duct.
    return {"connected_ports": [_port("D1", not entering, **port_kwargs)], "properties": properties}


def _inline(properties, **port_kwargs):
    ports = [_port("IN", True, **port_kwargs), _port("OUT", False, **port_kwargs)]
    return {"connected_ports": ports, "properties": properties, "air_kinematic_viscosity": 1.5e-5}


def _k(result):
    assert len(result.paths) == 1
    return result.paths[0].loss_coefficient


# ----------------------------------------------------------------------------
# entry_loss
# ----------------------------------------------------------------------------


def test_entry_defaults_to_a_flush_plain_duct_end():
    result = api.entry_loss(_terminal({}))
    assert result.status == api.EXACT
    assert _k(result) == pytest.approx(0.50)
    path = result.paths[0]
    assert (path.from_edge_key, path.to_edge_key, path.reference_edge_key) == (None, "D1", "D1")


def test_entry_duct_in_wall_uses_thickness_and_projection_over_diameter():
    # t/D = 0, L/D = 40/200 = 0.2 -> 0.92
    result = api.entry_loss(_terminal({"EntryType": "duct_in_wall", "ProjectionLength": 40.0}))
    assert _k(result) == pytest.approx(0.92)


@pytest.mark.parametrize("end_wall, k", [(False, 0.40), (True, 0.22)])
def test_entry_bellmouth(end_wall, k):
    # R/D = 10/200 = 0.05
    result = api.entry_loss(_terminal({"EntryType": "bellmouth", "LipRadius": 10.0, "EndWall": end_wall}))
    assert result.status == api.EXACT
    assert _k(result) == pytest.approx(k)


def test_entry_conical():
    # L/D = 50/200 = 0.25, 30 deg, no wall -> 0.30
    result = api.entry_loss(_terminal({"EntryType": "conical", "ConeAngle": 30.0, "ConeLength": 50.0}))
    assert _k(result) == pytest.approx(0.30)


def test_entry_rectangular_duct_uses_2hw_over_h_plus_w():
    # D = 2*300*600/900 = 400; L/D = 100/400 = 0.25, 30 deg -> 0.30
    result = api.entry_loss(
        _terminal(
            {"EntryType": "conical", "ConeAngle": 30.0, "ConeLength": 100.0},
            profile="Rectangular",
            Width=600.0,
            Height=300.0,
        )
    )
    assert result.status == api.EXACT
    assert _k(result) == pytest.approx(0.30)


def test_entry_hoods():
    assert _k(
        api.entry_loss(_terminal({"EntryType": "intake_hood", "HoodAngle": 15.0, "HoodHeight": 40.0}))
    ) == pytest.approx(0.77)
    assert _k(api.entry_loss(_terminal({"EntryType": "tapered_hood", "HoodAngle": 40.0}))) == pytest.approx(0.06)
    assert _k(api.entry_loss(_terminal({"EntryType": "canopy_hood"}))) == pytest.approx(0.5)


def test_entry_screen_is_added_at_the_opening_velocity():
    # Screen n = 0.5 -> 1.7; opening twice the duct area -> 1.7 / 4.
    plain = api.entry_loss(_terminal({"ScreenFreeArea": 0.5}))
    assert _k(plain) == pytest.approx(0.50 + 1.7)
    wide = api.entry_loss(_terminal({"ScreenFreeArea": 0.5, "OpeningAreaRatio": 2.0}))
    assert _k(wide) == pytest.approx(0.50 + 1.7 / 4.0)


def test_entry_outside_the_table_is_an_approximation_with_a_reason():
    result = api.entry_loss(_terminal({"EntryType": "conical", "ConeAngle": 30.0, "ConeLength": 1000.0}))
    assert result.status == api.APPROXIMATION
    assert "printed range" in result.warning


def test_entry_bellmouth_on_a_rectangular_duct_is_an_approximation():
    result = api.entry_loss(
        _terminal({"EntryType": "bellmouth", "LipRadius": 10.0}, profile="Rectangular", Width=300.0, Height=300.0)
    )
    assert result.status == api.APPROXIMATION
    assert "round" in result.warning


def test_entry_rejects_wrong_flow_direction_unknown_type_and_bad_topology():
    wrong_way = api.entry_loss(_terminal({}, entering=False))
    assert wrong_way.status == api.UNSUPPORTED
    assert "other way" in wrong_way.warning
    assert api.entry_loss(_terminal({"EntryType": "trumpet"})).status == api.UNSUPPORTED
    assert api.entry_loss(_inline({})).status == api.UNSUPPORTED


# ----------------------------------------------------------------------------
# exit_loss
# ----------------------------------------------------------------------------


def test_exit_defaults_to_an_abrupt_exit():
    result = api.exit_loss(_terminal({}, entering=False))
    assert result.status == api.EXACT
    assert _k(result) == pytest.approx(1.0)
    path = result.paths[0]
    assert (path.from_edge_key, path.to_edge_key, path.reference_edge_key) == ("D1", None, "D1")


def test_exit_conical_and_rectangular_diffusers():
    conical = api.exit_loss(_terminal({"ExitType": "conical", "ConeAngle": 30.0, "AreaRatio": 4.0}, entering=False))
    assert _k(conical) == pytest.approx(0.54)
    rect = dict(profile="Rectangular", Width=400.0, Height=300.0)
    plane = api.exit_loss(
        _terminal({"ExitType": "plane_diffuser", "ConeAngle": 45.0, "AreaRatio": 4.0}, entering=False, **rect)
    )
    assert _k(plane) == pytest.approx(0.82)
    pyramid = api.exit_loss(
        _terminal({"ExitType": "pyramidal_diffuser", "ConeAngle": 30.0, "AreaRatio": 6.0}, entering=False, **rect)
    )
    assert _k(pyramid) == pytest.approx(0.74)
    assert plane.status == pyramid.status == api.EXACT


def test_exit_exhaust_hood():
    # L/D = 50/200 = 0.25, 15 deg -> 1.0
    result = api.exit_loss(
        _terminal({"ExitType": "exhaust_hood", "HoodAngle": 15.0, "HoodHeight": 50.0}, entering=False)
    )
    assert _k(result) == pytest.approx(1.0)


def test_exit_screen_scales_with_the_diffuser_area_ratio():
    # Abrupt: Cs = 1 + C_screen.
    assert _k(api.exit_loss(_terminal({"ScreenFreeArea": 0.5}, entering=False))) == pytest.approx(1.0 + 1.7)
    # Conical, As/A = 4: C + C_screen / 16.
    result = api.exit_loss(
        _terminal({"ExitType": "conical", "ConeAngle": 30.0, "AreaRatio": 4.0, "ScreenFreeArea": 0.5}, entering=False)
    )
    assert _k(result) == pytest.approx(0.54 + 1.7 / 16.0)


def test_exit_rejects_wrong_flow_direction_and_unknown_type():
    assert api.exit_loss(_terminal({}, entering=True)).status == api.UNSUPPORTED
    assert api.exit_loss(_terminal({"ExitType": "nozzle"}, entering=False)).status == api.UNSUPPORTED


# ----------------------------------------------------------------------------
# screen_loss
# ----------------------------------------------------------------------------


def test_screen_and_perforated_plate():
    screen = api.screen_loss(_inline({"FreeAreaRatio": 0.6}))
    assert screen.status == api.EXACT
    assert _k(screen) == pytest.approx(0.97)
    path = screen.paths[0]
    assert (path.from_edge_key, path.to_edge_key, path.reference_edge_key) == ("IN", "OUT", "OUT")
    # t/d = 2/10 = 0.2, n = 0.5 -> 3.8
    plate = api.screen_loss(_inline({"FreeAreaRatio": 0.5, "PlateThickness": 2.0, "HoleDiameter": 10.0}))
    assert _k(plate) == pytest.approx(3.8)
    assert plate.paths[0].source == "smacna_perforated_plate"


def test_screen_needs_a_valid_free_area():
    assert api.screen_loss(_inline({})).status == api.UNSUPPORTED
    assert api.screen_loss(_inline({"FreeAreaRatio": 1.2})).status == api.UNSUPPORTED
    # Denser than the table covers: still a number, flagged.
    assert api.screen_loss(_inline({"FreeAreaRatio": 0.1})).status == api.APPROXIMATION


# ----------------------------------------------------------------------------
# damper_loss
# ----------------------------------------------------------------------------


def test_butterfly_damper_picks_the_table_for_the_duct_profile():
    assert _k(api.damper_loss(_inline({"BladeAngle": 30.0}))) == pytest.approx(4.5)
    rect = dict(profile="Rectangular", Width=400.0, Height=300.0)
    assert _k(api.damper_loss(_inline({"BladeAngle": 30.0}, **rect))) == pytest.approx(3.3)
    assert _k(
        api.damper_loss(_inline({"DamperType": "butterfly_airfoil", "BladeAngle": 0.0}, **rect))
    ) == pytest.approx(0.50)


def test_gate_damper():
    assert _k(api.damper_loss(_inline({"DamperType": "gate", "GateOpening": 0.5}))) == pytest.approx(2.1)
    # H/W = 1.0, h/H = 0.6 -> 2.4
    rect = dict(profile="Rectangular", Width=300.0, Height=300.0)
    assert _k(api.damper_loss(_inline({"DamperType": "gate", "GateOpening": 0.6}, **rect))) == pytest.approx(2.4)
    assert api.damper_loss(_inline({"DamperType": "gate", "GateOpening": 0.0})).status == api.UNSUPPORTED


def test_multi_blade_dampers():
    # 4 blades along a 500 wide x 500 high duct: L/R = 4 * 500 / (2 * 1000) = 1.0
    rect = dict(profile="Rectangular", Width=500.0, Height=500.0)
    parallel = api.damper_loss(_inline({"DamperType": "parallel_blade", "BladeAngle": 30.0, "BladeCount": 4}, **rect))
    opposed = api.damper_loss(_inline({"DamperType": "opposed_blade", "BladeAngle": 30.0, "BladeCount": 4}, **rect))
    assert _k(parallel) == pytest.approx(2.6)
    assert _k(opposed) == pytest.approx(7.3)
    assert (
        api.damper_loss(_inline({"DamperType": "opposed_blade", "BladeAngle": 30.0}, **rect)).status == api.UNSUPPORTED
    )
    assert api.damper_loss(_inline({"DamperType": "opposed_blade", "BladeCount": 4})).status == api.UNSUPPORTED


def test_damper_beyond_the_table_and_unknown_type():
    assert api.damper_loss(_inline({"BladeAngle": 75.0})).status == api.APPROXIMATION
    assert api.damper_loss(_inline({"DamperType": "iris"})).status == api.UNSUPPORTED


# ----------------------------------------------------------------------------
# obstruction_loss
# ----------------------------------------------------------------------------


def test_obstruction_in_a_rectangular_duct():
    # 20 mm rod across a 400 wide x 200 high duct: Sm/A = 20 * 400 / 80000 = 0.10.
    # Re = 5 * 0.02 / 1.5e-5 = 6667 -> the (0.5 to 200)e3 row -> Co = 0.15.
    rect = dict(profile="Rectangular", Width=400.0, Height=200.0)
    result = api.obstruction_loss(_inline({"ObstructionDiameter": 20.0}, **rect))
    assert result.status == api.EXACT
    assert _k(result) == pytest.approx(0.15)
    # Offset y/H = 40/200 = 0.20 -> K = 0.84
    offset = api.obstruction_loss(_inline({"ObstructionDiameter": 20.0, "OffsetFromCentre": 40.0}, **rect))
    assert _k(offset) == pytest.approx(0.15 * 0.84)


def test_obstruction_in_a_round_duct_uses_the_chord_length():
    # Centred in a 200 round duct: L = 200, A = pi * 100^2, Sm/A = 10 * 200 / 31416 = 0.0637
    result = api.obstruction_loss(_inline({"ObstructionDiameter": 10.0}))
    sm_on_a = 10.0 * 200.0 / (math.pi * 100.0**2)
    expected = 0.07 + (sm_on_a - 0.05) / 0.05 * (0.15 - 0.07)
    assert result.status == api.EXACT
    assert _k(result) == pytest.approx(expected)


def test_obstruction_limits():
    assert api.obstruction_loss(_inline({})).status == api.UNSUPPORTED
    assert (
        api.obstruction_loss(_inline({"ObstructionDiameter": 10.0, "OffsetFromCentre": 150.0})).status
        == api.UNSUPPORTED
    )
    # Blocks more than the table covers.
    big = api.obstruction_loss(_inline({"ObstructionDiameter": 80.0}, profile="Rectangular", Width=400.0, Height=200.0))
    assert big.status == api.APPROXIMATION


def test_obstruction_with_no_flow_is_a_zero_loss():
    result = api.obstruction_loss(_inline({"ObstructionDiameter": 20.0}, velocity_ms=0.0))
    assert result.status == api.EXACT
    assert _k(result) == 0.0


# ----------------------------------------------------------------------------
# Drop-down display names, and the shared damper loss function
# ----------------------------------------------------------------------------


def test_choice_turns_a_display_name_into_the_method_key():
    assert api._choice("Opposed blade", "butterfly") == "opposed_blade"
    assert api._choice("Butterfly airfoil", "butterfly") == "butterfly_airfoil"
    assert api._choice("", "butterfly") == "butterfly"
    assert api._choice(None, "abrupt") == "abrupt"


def test_damper_loss_accepts_the_drop_down_display_names():
    rect = dict(profile="Rectangular", Width=500.0, Height=500.0)
    result = api.damper_loss(_inline({"DamperType": "Opposed blade", "BladeAngle": 30.0, "BladeCount": 4}, **rect))
    assert _k(result) == pytest.approx(7.3)


def _shared_damper_loss(properties, **port_kwargs):
    from freecad.HVAC.library.fittings import losses

    context = _inline(properties, **port_kwargs)
    context["loss_api"] = api
    return losses.loss_damper_generic(context)


def test_shared_damper_loss_uses_the_users_coefficient_by_default():
    for properties in (
        {"LossCoefficient": 0.35},
        {"DamperType": "Coefficient", "LossCoefficient": 0.35, "BladeAngle": 40.0},
    ):
        result = _shared_damper_loss(properties)
        assert _k(result) == pytest.approx(0.35)
        assert result.paths[0].source == "inline_device"


def test_shared_damper_loss_reads_the_table_for_a_real_damper_type():
    result = _shared_damper_loss({"DamperType": "Butterfly", "LossCoefficient": 0.35, "BladeAngle": 30.0})
    assert _k(result) == pytest.approx(4.5)
    assert result.paths[0].source == "smacna_damper_butterfly"


# ----------------------------------------------------------------------------
# fan_connection_loss and the AHU loss
# ----------------------------------------------------------------------------

# A 600 x 400 duct leaving a 400 x 300 fan outlet: A1/A = 0.24 / 0.12 = 2.0,
# and a coefficient printed at the outlet velocity is (2.0)^2 = 4 times larger at the duct's.
_AHU_DUCT = dict(profile="Rectangular", Width=600.0, Height=400.0)
_FAN = {"FanOutletWidth": 400.0, "FanOutletHeight": 300.0}


def _supply(properties):
    context = _terminal(dict(_FAN, **properties), entering=True, **_AHU_DUCT)
    context["loss_api"] = api
    context["air_density"] = 1.2
    return context


@pytest.mark.parametrize(
    "choice, table_c",
    [
        ("Transition symmetric", 0.10),
        ("Transition asymmetric top level", 0.14),
        ("Transition asymmetric top 10 down", 0.22),
        ("Transition asymmetric top 10 up", 0.11),
        ("Transition pyramidal", 0.43),
    ],
)
def test_fan_transition_reads_14_11_f_to_j(choice, table_c):
    result = api.fan_connection_loss(_supply({"FanConnection": choice, "TransitionAngle": 20.0}))
    assert result.status == api.EXACT
    assert _k(result) == pytest.approx(table_c * 4.0)


@pytest.mark.parametrize("wheel, table_c", [("Airfoil", 1.0), ("Backward inclined", 1.5), ("Forward curved", 1.8)])
def test_fan_discharge_into_casing_reads_14_16i(wheel, table_c):
    result = api.fan_connection_loss(_supply({"FanConnection": "Discharge into casing", "FanWheel": wheel}))
    assert _k(result) == pytest.approx(table_c * 4.0)


def test_fan_connection_none_or_missing_outlet_or_return_duct_is_unsupported():
    assert api.fan_connection_loss(_supply({"FanConnection": "None"})).status == api.UNSUPPORTED
    no_outlet = _supply({"FanConnection": "Transition pyramidal", "FanOutletWidth": 0.0})
    assert api.fan_connection_loss(no_outlet).status == api.UNSUPPORTED
    ret = _terminal(dict(_FAN, FanConnection="Transition pyramidal"), entering=False, **_AHU_DUCT)
    assert api.fan_connection_loss(ret).status == api.UNSUPPORTED


def test_fan_outlet_is_the_connected_equipment_port():
    # The equipment port the end sits on is the outlet; a size left in
    # FanOutletWidth / FanOutletHeight (now only a display) does not override it.
    context = _supply({"FanConnection": "Transition symmetric", "TransitionAngle": 20.0})
    context["properties"].update(FanOutletWidth=600.0, FanOutletHeight=400.0)
    context["equipment_port"] = {"profile": "Rectangular", "section_params": {"Width": 400.0, "Height": 300.0}}
    result = api.fan_connection_loss(context)
    assert result.status == api.EXACT
    assert _k(result) == pytest.approx(0.10 * 4.0)


def test_round_fan_outlet_uses_the_port_area_not_its_diameter_squared():
    # A 400 mm round port: area pi/4 x 0.16 m2, not 0.4 x 0.4.
    context = _supply({"FanConnection": "Discharge into casing", "FanWheel": "Airfoil"})
    context["properties"].update(FanOutletWidth=400.0, FanOutletHeight=400.0)
    context["equipment_port"] = {"profile": "Circular", "section_params": {"Diameter": 400.0}}
    ratio = 0.24 / (math.pi / 4.0 * 0.16)
    assert _k(api.fan_connection_loss(context)) == pytest.approx(1.0 * ratio**2)


def test_fan_transition_outside_the_table_is_an_approximation():
    result = api.fan_connection_loss(_supply({"FanConnection": "Transition symmetric", "TransitionAngle": 60.0}))
    assert result.status == api.APPROXIMATION


def test_ahu_loss_adds_the_unit_and_the_fan_connection():
    from freecad.HVAC.library.fittings import losses

    # Unit: 60 Pa at 5 m/s with rho 1.2 -> K = 60 / 15 = 4.0. Fan: airfoil wheel, 1.0 x 4.
    context = _supply(
        {
            "FanConnection": "Discharge into casing",
            "FanWheel": "Airfoil",
            "LossMode": "Fixed pressure drop",
            "PressureDrop": 60.0,
        }
    )
    result = losses.loss_ahu(context)
    assert result.status == api.EXACT
    assert _k(result) == pytest.approx(4.0 + 1.0 * 4.0)


def test_ahu_loss_without_a_fan_connection_is_the_unit_alone():
    from freecad.HVAC.library.fittings import losses

    context = _supply({"FanConnection": "None", "LossMode": "Fixed pressure drop", "PressureDrop": 60.0})
    assert _k(losses.loss_ahu(context)) == pytest.approx(4.0)


def test_ahu_loss_with_only_a_fan_connection():
    from freecad.HVAC.library.fittings import losses

    context = _supply({"FanConnection": "Discharge into casing", "FanWheel": "Airfoil", "LossCoefficient": 0.0})
    assert _k(losses.loss_ahu(context)) == pytest.approx(4.0)


def test_sum_losses_takes_the_weaker_status_and_joins_warnings():
    from freecad.HVAC.analysis.loss import LossEvaluation, LossPath, LossStatus

    a = LossEvaluation([LossPath(None, "D", "D", 1.0, source="a")], LossStatus.EXACT)
    b = LossEvaluation([LossPath(None, "D", "D", 0.5, source="b")], LossStatus.APPROXIMATION, warning="clamped")
    total = api.sum_losses(a, b)
    assert total.paths[0].loss_coefficient == pytest.approx(1.5)
    assert total.status == LossStatus.APPROXIMATION
    assert total.warning == "clamped"
    unsupported = LossEvaluation([], LossStatus.UNSUPPORTED, warning="no")
    assert api.sum_losses(a, unsupported) is a
