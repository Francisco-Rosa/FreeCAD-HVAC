# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the HVAC addon.

"""
Terminal fittings (entries, exits, hoods, diffusers, grilles): the sizes each
one is laid out with, and the trim it reports. Shape construction is out of
scope (see AGENTS.md); these tests stop at the numbers.
"""

import math

import pytest

import conftest  # noqa: F401 -- installs FreeCAD/FreeCADGui/Part/PySide stubs
from freecad.HVAC.library.fittings import terminals
from freecad.HVAC.library.library_api import HVACLibraryAPI


def _port(profile="Circular", **section):
    if not section:
        section = {"Diameter": 200.0}
    return {
        "edge_key": "A",
        "position": [0.0, 0.0, 0.0],
        "direction": [1.0, 0.0, 0.0],
        "profile": profile,
        "section_params": dict(section),
        "profile_x_axis": None,
        "segment_end": "start",
    }


def _ctx(params, port=None):
    return {"hvac_api": HVACLibraryAPI, "properties": dict(params), "connected_ports": [port or _port()]}


def _layout(kind, params, port=None):
    return terminals._terminal_layout(_ctx(params, port), kind)


def _trim(measure, params, port=None):
    records = measure(_ctx(params, port))
    assert len(records) == 1 and records[0]["edge_key"] == "A"
    return records[0]["length"]


# ----------------------------------------------------------------------------
# The neck
# ----------------------------------------------------------------------------


def test_generic_body_adds_the_neck_to_its_body_length():
    assert _trim(terminals.measure_terminal_body_generic, {"BodyLength": 150.0, "TrimNeck": 40.0}) == 190.0


def test_generic_body_without_a_neck_is_unchanged():
    assert _trim(terminals.measure_terminal_body_generic, {"BodyLength": 150.0}) == 150.0


@pytest.mark.parametrize("kind", ["plain", "hood", "frame"])
def test_a_fitting_that_is_only_a_neck_gets_a_default_length(kind):
    # A quarter of the 200 mm duct.
    assert _layout(kind, {"TrimNeck": 0.0})["neck"] == pytest.approx(50.0)
    assert _layout(kind, {"TrimNeck": 80.0})["neck"] == pytest.approx(80.0)


def test_a_fitting_with_a_body_may_have_no_neck():
    layout = _layout("square", {"TrimNeck": 0.0, "FaceSize": 600.0, "BodyLength": 150.0})
    assert layout["neck"] == 0.0
    assert terminals._terminal_trim(layout) == 150.0


def test_more_than_one_port_is_rejected():
    context = _ctx({})
    context["connected_ports"].append(_port())
    with pytest.raises(ValueError):
        terminals._terminal_layout(context, "plain")


def test_unknown_kind_is_rejected():
    with pytest.raises(ValueError):
        _layout("no_such_kind", {})


# ----------------------------------------------------------------------------
# Entries and exits
# ----------------------------------------------------------------------------


def test_bellmouth_grows_by_its_lip_radius_over_a_body_of_the_same_length():
    layout = _layout("bellmouth", {"LipRadius": 30.0, "TrimNeck": 50.0})
    assert layout["curved"] is True
    assert layout["body"] == 30.0
    assert layout["face"] == ("Circular", {"Diameter": 260.0})
    assert terminals._terminal_trim(layout) == 80.0


def test_bellmouth_without_a_lip_is_a_plain_duct_end():
    layout = _layout("bellmouth", {"LipRadius": 0.0, "TrimNeck": 0.0})
    assert layout["face"] is None and layout["body"] == 0.0
    assert layout["neck"] == pytest.approx(50.0)


def test_cone_opens_by_length_times_tan_of_half_the_angle():
    layout = _layout("cone", {"ConeAngle": 60.0, "ConeLength": 100.0, "TrimNeck": 25.0})
    growth = 100.0 * math.tan(math.radians(30.0))
    assert layout["body"] == 100.0
    assert layout["face"][1]["Diameter"] == pytest.approx(200.0 + 2.0 * growth)
    assert terminals._terminal_trim(layout) == 125.0


def test_cone_reads_the_hood_names_of_a_tapered_hood():
    layout = _layout("cone", {"HoodAngle": 90.0, "HoodLength": 50.0})
    assert layout["body"] == 50.0
    assert layout["face"][1]["Diameter"] == pytest.approx(300.0)


def test_cone_with_no_angle_is_a_straight_piece():
    layout = _layout("cone", {"ConeAngle": 0.0, "ConeLength": 100.0, "TrimNeck": 25.0})
    assert layout["face"] is None
    assert terminals._terminal_trim(layout) == 125.0


def test_cone_opening_is_capped_for_very_flat_angles():
    layout = _layout("cone", {"ConeAngle": 180.0, "ConeLength": 500.0})
    # Never more than three duct sizes per side.
    assert layout["face"][1]["Diameter"] == pytest.approx(200.0 + 2.0 * 600.0)


def test_round_diffusing_exit_reaches_its_area_ratio():
    layout = _layout("diffusing", {"ConeAngle": 20.0, "AreaRatio": 4.0, "TrimNeck": 50.0})
    # Four times the area is twice the diameter.
    assert layout["face"] == ("Circular", {"Diameter": pytest.approx(400.0)})
    assert layout["body"] == pytest.approx(100.0 / math.tan(math.radians(10.0)))


def test_pyramidal_exit_scales_both_sides():
    port = _port("Rectangular", Width=400.0, Height=200.0)
    layout = _layout("diffusing", {"ConeAngle": 20.0, "AreaRatio": 4.0, "DiffuserType": "Pyramidal"}, port)
    assert layout["face"][1]["Width"] == pytest.approx(800.0)
    assert layout["face"][1]["Height"] == pytest.approx(400.0)


def test_plane_exit_scales_the_width_only():
    port = _port("Rectangular", Width=400.0, Height=200.0)
    layout = _layout("diffusing", {"ConeAngle": 20.0, "AreaRatio": 2.0, "DiffuserType": "Plane"}, port)
    assert layout["face"][1]["Width"] == pytest.approx(800.0)
    assert layout["face"][1]["Height"] == pytest.approx(200.0)
    assert layout["body"] == pytest.approx(200.0 / math.tan(math.radians(10.0)))


def test_diffusing_exit_with_no_widening_is_a_plain_duct_end():
    layout = _layout("diffusing", {"ConeAngle": 20.0, "AreaRatio": 1.0})
    assert layout["face"] is None and layout["body"] == 0.0
    assert layout["neck"] == pytest.approx(50.0)


def test_hood_plate_stands_clear_of_the_opening():
    layout = _layout("hood", {"HoodHeight": 120.0, "TrimNeck": 60.0})
    assert layout["cap"]["distance"] == 120.0
    # Twice the duct size across: half a size more on every side.
    assert layout["cap"]["growth"] == pytest.approx(100.0)
    # The plate is outside the node, so it does not add to the trim.
    assert terminals._terminal_trim(layout) == 60.0


# ----------------------------------------------------------------------------
# Air terminals
# ----------------------------------------------------------------------------


def test_square_diffuser_face():
    layout = _layout("square", {"FaceSize": 600.0, "BodyLength": 150.0, "TrimNeck": 50.0})
    assert layout["face"] == ("Rectangular", {"Width": 600.0, "Height": 600.0})
    assert terminals._terminal_trim(layout) == 200.0


def test_round_diffuser_face():
    layout = _layout("round", {"FaceDiameter": 500.0, "BodyLength": 150.0})
    assert layout["face"] == ("Circular", {"Diameter": 500.0})


def test_slot_diffuser_face():
    layout = _layout("slot", {"SlotLength": 1200.0, "SlotWidth": 100.0, "BodyLength": 250.0})
    assert layout["face"] == ("Rectangular", {"Width": 1200.0, "Height": 100.0})


def test_face_sizes_left_at_zero_follow_the_duct():
    assert _layout("square", {})["face"][1]["Width"] == pytest.approx(400.0)
    assert _layout("round", {})["face"][1]["Diameter"] == pytest.approx(400.0)
    assert _layout("slot", {})["face"][1] == {"Width": pytest.approx(800.0), "Height": pytest.approx(100.0)}


def test_grille_frame_is_a_lip_around_the_duct_section():
    port = _port("Rectangular", Width=400.0, Height=200.0)
    layout = _layout("frame", {"FrameWidth": 25.0, "FrameDepth": 20.0, "TrimNeck": 60.0}, port)
    assert layout["lip"] == 20.0
    assert layout["face"][1] == {"Width": 450.0, "Height": 250.0}
    assert terminals._terminal_trim(layout) == 80.0


def test_grille_without_a_frame_has_no_lip():
    layout = _layout("frame", {"FrameWidth": 0.0, "FrameDepth": 20.0, "TrimNeck": 60.0})
    assert layout["lip"] == 0.0 and layout["face"] is None


# ----------------------------------------------------------------------------
# Every kind: the measured trim is the sum of the three parts
# ----------------------------------------------------------------------------

_KINDS = {
    "plain": terminals.measure_terminal_plain,
    "bellmouth": terminals.measure_terminal_bellmouth,
    "cone": terminals.measure_terminal_cone,
    "diffusing": terminals.measure_terminal_diffusing,
    "hood": terminals.measure_terminal_hood,
    "square": terminals.measure_terminal_square,
    "round": terminals.measure_terminal_round,
    "slot": terminals.measure_terminal_slot,
    "frame": terminals.measure_terminal_frame,
    "generic": terminals.measure_terminal_body_generic,
}


@pytest.mark.parametrize("kind", sorted(_KINDS))
def test_measured_trim_is_lip_plus_body_plus_neck(kind):
    params = {"TrimNeck": 35.0, "LipRadius": 20.0, "ConeAngle": 30.0, "AreaRatio": 2.0, "FrameWidth": 10.0}
    params["FrameDepth"] = 15.0
    layout = _layout(kind, params)
    assert _trim(_KINDS[kind], params) == pytest.approx(layout["lip"] + layout["body"] + layout["neck"])


# ----------------------------------------------------------------------------
# Equipment connection: the fan outlet is the equipment port, and only the
# FanConnection choices that suit the connection are offered
# ----------------------------------------------------------------------------

_ALL_FAN_CHOICES = [
    "None",
    "Transition symmetric",
    "Transition asymmetric top level",
    "Transition asymmetric top 10 down",
    "Transition asymmetric top 10 up",
    "Transition pyramidal",
    "Discharge into casing",
]


def _fan_layout(duct, outlet, flow_into_junction=False, choice="None"):
    port = dict(_port(**duct), flow_into_junction=flow_into_junction)
    context = _ctx({"FanConnection": choice, "TransitionAngle": 20.0}, port)
    if outlet is not None:
        profile, section = outlet
        context["equipment_port"] = {"profile": profile, "section_params": section, "profile_x_axis": None}
    return terminals._terminal_layout(context, "fan")


def _offered(duct, outlet, flow_into_junction=False):
    return _fan_layout(duct, outlet, flow_into_junction)["choices"]["FanConnection"]


_RECT_DUCT = {"profile": "Rectangular", "Width": 600.0, "Height": 400.0}


def test_fan_choices_follow_the_type_def_order():
    offered = _offered(_RECT_DUCT, ("Rectangular", {"Width": 600.0, "Height": 300.0}))
    assert offered == [choice for choice in _ALL_FAN_CHOICES if choice in offered]


def test_no_equipment_port_offers_none_only_and_reports_no_outlet():
    layout = _fan_layout(_RECT_DUCT, None)
    assert layout["choices"]["FanConnection"] == ["None"]
    assert layout["computed"] is None


def test_air_flowing_into_the_unit_offers_none_only():
    assert _offered(_RECT_DUCT, ("Rectangular", {"Width": 400.0, "Height": 300.0}), flow_into_junction=True) == ["None"]


def test_outlet_the_size_of_the_duct_offers_no_transition():
    assert _offered(_RECT_DUCT, ("Rectangular", {"Width": 600.0, "Height": 400.0})) == ["None", "Discharge into casing"]


def test_only_the_height_changing_offers_sides_straight_and_asymmetric():
    assert _offered(_RECT_DUCT, ("Rectangular", {"Width": 600.0, "Height": 300.0})) == [
        "None",
        "Transition symmetric",
        "Transition asymmetric top level",
        "Transition asymmetric top 10 down",
        "Transition asymmetric top 10 up",
        "Discharge into casing",
    ]


def test_only_the_width_changing_offers_sides_straight():
    assert _offered(_RECT_DUCT, ("Rectangular", {"Width": 400.0, "Height": 400.0})) == [
        "None",
        "Transition symmetric",
        "Discharge into casing",
    ]


@pytest.mark.parametrize(
    "outlet",
    [("Rectangular", {"Width": 400.0, "Height": 300.0}), ("Circular", {"Diameter": 400.0})],
    ids=["both sides", "round to rectangular"],
)
def test_both_sides_or_the_shape_changing_offers_pyramidal(outlet):
    assert _offered(_RECT_DUCT, outlet) == ["None", "Transition pyramidal", "Discharge into casing"]


def test_fan_outlet_size_is_reported_from_the_port():
    layout = _fan_layout(_RECT_DUCT, ("Rectangular", {"Width": 400.0, "Height": 300.0}))
    assert layout["computed"] == {"FanOutletWidth": 400.0, "FanOutletHeight": 300.0}
    round_layout = _fan_layout(_RECT_DUCT, ("Circular", {"Diameter": 350.0}))
    assert round_layout["computed"] == {"FanOutletWidth": 350.0, "FanOutletHeight": 350.0}


def test_a_choice_that_no_longer_suits_builds_as_none():
    # Air flowing into the unit: no transition is offered, so the asymmetric choice builds centred.
    outlet = ("Rectangular", {"Width": 600.0, "Height": 300.0})
    asymmetric = _fan_layout(_RECT_DUCT, outlet, choice="Transition asymmetric top level")
    assert asymmetric["face_shift"][1] != pytest.approx(0.0)
    unsuited = _fan_layout(_RECT_DUCT, outlet, flow_into_junction=True, choice="Transition asymmetric top level")
    assert unsuited["face_shift"][1] == pytest.approx(0.0)
