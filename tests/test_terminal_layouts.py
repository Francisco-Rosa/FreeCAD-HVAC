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
# Equipment connection: the fan outlet is the equipment port, where it really
# is; the transition follows the duct's placement, and only the FanConnection
# choice that describes it is offered
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

# The duct end port sits at the origin, pointing along +X; its frame's width
# axis is the port's profile X axis (+Y) and its height axis is +Z.
_RECT_DUCT = {"profile": "Rectangular", "Width": 600.0, "Height": 400.0}


def _fan_layout(duct, outlet, offset=(0.0, 0.0), flow_into_junction=False, angle=20.0):
    port = dict(_port(**duct), flow_into_junction=flow_into_junction, profile_x_axis=[0.0, 1.0, 0.0])
    context = _ctx({"FanConnection": "None", "TransitionAngle": angle}, port)
    if outlet is not None:
        profile, section = outlet
        context["equipment_port"] = {
            "profile": profile,
            "section_params": section,
            "profile_x_axis": (0.0, 1.0, 0.0),
            "position": (0.0, offset[0], offset[1]),
        }
    return terminals._terminal_layout(context, "fan")


def _offered(duct, outlet, offset=(0.0, 0.0), flow_into_junction=False, angle=20.0):
    return _fan_layout(duct, outlet, offset, flow_into_junction, angle)["choices"]["FanConnection"]


def _with_transition(name):
    return ["None", name, "Discharge into casing"]


def test_no_equipment_port_offers_none_only_and_reports_no_outlet():
    layout = _fan_layout(_RECT_DUCT, None)
    assert layout["choices"]["FanConnection"] == ["None"]
    assert layout["computed"] is None


def test_air_flowing_into_the_unit_offers_none_only():
    outlet = ("Rectangular", {"Width": 400.0, "Height": 300.0})
    assert _offered(_RECT_DUCT, outlet, flow_into_junction=True) == ["None"]


def test_outlet_the_size_of_the_duct_and_in_line_offers_no_transition():
    layout = _fan_layout(_RECT_DUCT, ("Rectangular", {"Width": 600.0, "Height": 400.0}))
    assert layout["choices"]["FanConnection"] == ["None", "Discharge into casing"]
    assert layout["body"] == 0.0


def test_centred_height_change_is_symmetric_sides_straight():
    assert _offered(_RECT_DUCT, ("Rectangular", {"Width": 600.0, "Height": 300.0})) == _with_transition(
        "Transition symmetric"
    )


def test_centred_width_change_is_symmetric_sides_straight():
    assert _offered(_RECT_DUCT, ("Rectangular", {"Width": 400.0, "Height": 400.0})) == _with_transition(
        "Transition symmetric"
    )


def test_duct_flush_with_the_outlet_top_is_asymmetric_top_level():
    # A 300 high outlet whose top is level with the 400 high duct's: its centre 50 above the duct's.
    outlet = ("Rectangular", {"Width": 600.0, "Height": 300.0})
    layout = _fan_layout(_RECT_DUCT, outlet, offset=(0.0, 50.0))
    assert layout["choices"]["FanConnection"] == _with_transition("Transition asymmetric top level")
    # The whole included angle opens at the bottom: 100 over the length.
    assert layout["body"] == pytest.approx(100.0 / math.tan(math.radians(20.0)))
    assert layout["face_shift"] == pytest.approx((0.0, 50.0))


@pytest.mark.parametrize("slope, name", [(-10.0, "down"), (10.0, "up")])
def test_top_sloping_ten_degrees_is_asymmetric_top_10(slope, name):
    # The top slopes `slope`, the bottom opens the whole 30 degrees against it, over the 100 mm height change:
    # the outlet is placed where that puts it.
    angle = 30.0
    rise = 100.0
    top, bottom = math.radians(slope), math.radians(slope) - math.radians(angle)
    length = rise / (math.tan(top) - math.tan(bottom))
    shift = 200.0 - length * math.tan(top) - 150.0
    outlet = ("Rectangular", {"Width": 600.0, "Height": 300.0})
    offered = _offered(_RECT_DUCT, outlet, offset=(0.0, shift), angle=angle)
    assert offered == _with_transition("Transition asymmetric top 10 {}".format(name))


@pytest.mark.parametrize(
    "outlet, offset",
    [
        (("Rectangular", {"Width": 400.0, "Height": 300.0}), (0.0, 0.0)),
        (("Circular", {"Diameter": 400.0}), (0.0, 0.0)),
        (("Rectangular", {"Width": 600.0, "Height": 300.0}), (60.0, 0.0)),
    ],
    ids=["both sides", "round to rectangular", "height change but off to the side"],
)
def test_other_transitions_are_pyramidal(outlet, offset):
    assert _offered(_RECT_DUCT, outlet, offset) == _with_transition("Transition pyramidal")


def test_fan_outlet_size_is_reported_from_the_port():
    layout = _fan_layout(_RECT_DUCT, ("Rectangular", {"Width": 400.0, "Height": 300.0}))
    assert layout["computed"] == {"FanOutletWidth": 400.0, "FanOutletHeight": 300.0}
    round_layout = _fan_layout(_RECT_DUCT, ("Circular", {"Diameter": 350.0}))
    assert round_layout["computed"] == {"FanOutletWidth": 350.0, "FanOutletHeight": 350.0}


def test_centred_transition_length_opens_half_the_angle_each_side():
    layout = _fan_layout(_RECT_DUCT, ("Rectangular", {"Width": 600.0, "Height": 300.0}))
    assert layout["body"] == pytest.approx(50.0 / math.tan(math.radians(10.0)), rel=1e-6)


def test_fan_choices_follow_the_type_def_order():
    for outlet, offset in (
        (("Rectangular", {"Width": 600.0, "Height": 300.0}), (0.0, 50.0)),
        (("Rectangular", {"Width": 400.0, "Height": 300.0}), (0.0, 0.0)),
    ):
        offered = _offered(_RECT_DUCT, outlet, offset)
        assert offered == [choice for choice in _ALL_FAN_CHOICES if choice in offered]
