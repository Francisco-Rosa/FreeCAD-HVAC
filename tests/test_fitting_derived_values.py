"""
Fitting-derived values (ROADMAP 6.1): the pure helpers in
fittings/transitions.py that both the geometry (as read-only computed
properties) and the loss functions use.
"""

import math

import pytest

import conftest  # noqa: F401 -- installs FreeCAD/Part stubs
from freecad.HVAC.library.fittings import transitions as tr
from freecad.HVAC.library.library_api import HVACLibraryAPI as api
from freecad.HVAC.library.loss_tables import transitions as transition_tables


def _port(edge_key, direction, position=(0.0, 0.0, 0.0), profile="Circular", **section):
    return {
        "edge_key": edge_key,
        "direction": direction,
        "position": position,
        "profile": profile,
        "section_params": dict(section),
    }


def test_round_transition_angle_and_default_length():
    ports = [_port("a", (-1, 0, 0), Diameter=200.0), _port("b", (1, 0, 0), Diameter=400.0)]
    dims = tr.transition_dimensions(api, ports, {"TransitionLength": 0.0})
    assert dims["body_length"] == pytest.approx(400.0)  # the larger duct size
    assert dims["included_angle"] == pytest.approx(math.degrees(2 * math.atan(100.0 / 400.0)))
    # Same answer whichever end comes first: it does not depend on flow direction.
    assert tr.transition_dimensions(api, ports[::-1], {"TransitionLength": 0.0}) == dims


def test_rectangular_transition_takes_the_major_angle_and_flags_one_plane():
    ports = [
        _port("a", (-1, 0, 0), profile="Rectangular", Width=400.0, Height=200.0),
        _port("b", (1, 0, 0), profile="Rectangular", Width=800.0, Height=200.0),
    ]
    dims = tr.transition_dimensions(api, ports, {"TransitionLength": 500.0})
    assert dims["included_angle"] == pytest.approx(math.degrees(2 * math.atan(400.0 / 1000.0)))
    assert dims["single_plane"] is True


def test_round_to_rectangular_uses_the_14_11c_equivalent_angle():
    ports = [
        _port("a", (-1, 0, 0), Diameter=300.0),
        _port("b", (1, 0, 0), profile="Rectangular", Width=600.0, Height=400.0),
    ]
    dims = tr.transition_dimensions(api, ports, {"TransitionLength": 600.0})
    assert dims["included_angle"] == pytest.approx(
        transition_tables.round_rect_equivalent_angle(300.0, 600.0, 400.0, 600.0)
    )


def test_unknown_profile_has_no_angle():
    ports = [_port("a", (-1, 0, 0), profile="Custom", Size=200.0), _port("b", (1, 0, 0), Diameter=300.0)]
    assert tr.transition_dimensions(api, ports, {})["included_angle"] is None


def test_transition_needs_two_ports():
    with pytest.raises(ValueError):
        tr.transition_dimensions(api, [_port("a", (1, 0, 0), Diameter=200.0)], {})


def _offset_ports(jog, size=200.0):
    return [
        _port("a", (-1, 0, 0), (0.0, 0.0, 0.0), Diameter=size),
        _port("b", (1, 0, 0), (1000.0, jog, 0.0), Diameter=size),
    ]


def test_offset_angle_matches_the_offset_axis():
    ports = _offset_ports(150.0)
    dims = tr.offset_dimensions(api, ports, {"TransitionLength": 600.0})
    axis = api.offset_transition_axis(ports[0], ports[1], 600.0)
    assert dims["body_length"] == pytest.approx(600.0)
    assert dims["offset_angle"] == pytest.approx(math.degrees(axis["turn_angle"]))
    assert dims["offset_angle"] > 0.0
    assert "actual_radius" not in dims


def test_offset_without_jog_has_no_angle():
    assert tr.offset_dimensions(api, _offset_ports(0.0), {"TransitionLength": 600.0})["offset_angle"] == pytest.approx(
        0.0
    )


def test_radiussed_offset_reports_the_radius_it_can_fit():
    ports = _offset_ports(100.0)
    roomy = tr.offset_dimensions(api, ports, {"TransitionLength": 2000.0, "TransitionRadius": 300.0}, radiussed=True)
    assert roomy["actual_radius"] == pytest.approx(300.0)
    tight = tr.offset_dimensions(api, ports, {"TransitionLength": 800.0, "TransitionRadius": 5000.0}, radiussed=True)
    assert 100.0 <= tight["actual_radius"] < 5000.0


def test_radiussed_offset_too_steep_raises():
    with pytest.raises(ValueError, match="too steep"):
        tr.offset_dimensions(api, _offset_ports(600.0, size=400.0), {"TransitionLength": 300.0}, radiussed=True)


def test_radiussed_offset_without_a_length_grows_until_its_arcs_fit():
    # The case the explicit 300 mm length refuses (see above) builds at length 0,
    # with the arcs at the default radius (the duct size) and only just longer than they need.
    ports = _offset_ports(600.0, size=400.0)
    dims = tr.offset_dimensions(api, ports, {"TransitionLength": 0.0}, radiussed=True)
    assert dims["actual_radius"] == pytest.approx(400.0, rel=2.0e-3)
    assert dims["body_length"] > 400.0
    shorter = tr.offset_dimensions(api, ports, {"TransitionLength": 0.99 * dims["body_length"]}, radiussed=True)
    assert shorter["actual_radius"] < 400.0


def test_radiussed_offset_without_a_length_keeps_the_default_when_it_already_fits():
    ports = _offset_ports(10.0)
    assert tr.radiussed_body_length(api, ports, {"TransitionLength": 0.0}) == pytest.approx(200.0)
    assert tr.radiussed_body_length(api, ports, {"TransitionLength": 150.0}) == pytest.approx(150.0)
