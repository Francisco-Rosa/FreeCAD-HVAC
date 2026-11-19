# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the HVAC addon.

"""
Box fittings (plenum, AHU connection): where the box sits, which face each
duct leaves through and the trim each duct gets. Shape construction is out
of scope (see AGENTS.md); these tests stop at the numbers.
"""

import pytest

import conftest  # noqa: F401 -- installs FreeCAD/FreeCADGui/Part/PySide stubs
from freecad.HVAC.library.fittings import boxes
from freecad.HVAC.library.library_api import HVACLibraryAPI


def _port(edge_key, direction, diameter=200.0, position=(0.0, 0.0, 0.0)):
    return {
        "edge_key": edge_key,
        "position": list(position),
        "direction": list(direction),
        "profile": "Circular",
        "section_params": {"Diameter": diameter},
        "profile_x_axis": None,
        "segment_end": "start",
    }


def _ctx(ports, params=None):
    return {
        "hvac_api": HVACLibraryAPI,
        "properties": dict(params or {}),
        "connected_ports": list(ports),
        "center_point": (0.0, 0.0, 0.0),
    }


def _trims(records):
    return {record["edge_key"]: record["length"] for record in records}


_STRAIGHT = [_port("A", (-1.0, 0.0, 0.0)), _port("B", (1.0, 0.0, 0.0))]
_TEE = _STRAIGHT + [_port("C", (0.0, 1.0, 0.0), diameter=100.0)]


# ----------------------------------------------------------------------------
# Plenum
# ----------------------------------------------------------------------------


def test_plenum_defaults_to_a_box_of_twice_the_largest_duct():
    layout = boxes._box_layout(_ctx(_TEE), "plenum")
    assert layout["dims"] == (400.0, 400.0, 400.0)


def test_plenum_trim_is_the_way_to_the_face_plus_the_collar():
    params = {"BoxLength": 600.0, "BoxWidth": 500.0, "BoxHeight": 400.0, "TrimLength": 80.0}
    trims = _trims(boxes.measure_plenum(_ctx(_TEE, params)))
    # The box length lies along the largest duct; the side branch leaves through a width or height face.
    assert trims["A"] == pytest.approx(300.0 + 80.0)
    assert trims["B"] == pytest.approx(300.0 + 80.0)
    assert trims["C"] in (pytest.approx(250.0 + 80.0), pytest.approx(200.0 + 80.0))


def test_plenum_collar_defaults_to_a_quarter_of_each_duct():
    trims = _trims(boxes.measure_plenum(_ctx(_TEE, {"BoxLength": 600.0, "BoxWidth": 600.0, "BoxHeight": 600.0})))
    assert trims["A"] == pytest.approx(300.0 + 50.0)
    assert trims["C"] == pytest.approx(300.0 + 25.0)


def test_plenum_collar_can_differ_per_port():
    params = {"BoxLength": 600.0, "TrimLength": {"A": 10.0, "B": 90.0}}
    trims = _trims(boxes.measure_plenum(_ctx(_STRAIGHT, params)))
    assert trims == {"A": pytest.approx(310.0), "B": pytest.approx(390.0)}


def test_moving_the_box_along_its_length_shifts_the_two_ends():
    params = {"BoxLength": 600.0, "TrimLength": 50.0, "CentreOffsetX": 100.0}
    layout = boxes._box_layout(_ctx(_STRAIGHT, params), "plenum")
    # The box moves towards whichever port its length axis points along.
    assert sorted(layout["exits"]) == [pytest.approx(200.0), pytest.approx(400.0)]


def test_plenum_takes_any_number_of_ports():
    ports = _TEE + [_port("D", (0.0, -1.0, 0.0), 100.0), _port("E", (0.0, 0.0, 1.0), 100.0)]
    ports.append(_port("F", (0.0, 0.0, -1.0), 100.0))
    trims = _trims(boxes.measure_plenum(_ctx(ports, {"TrimLength": 20.0})))
    assert set(trims) == {"A", "B", "C", "D", "E", "F"}
    assert all(value == pytest.approx(220.0) for value in trims.values())


def test_a_duct_through_a_box_corner_does_not_fit_a_box_of_set_size():
    # With the sizes set by the user the box cannot grow (an automatic one does, see below).
    ports = _STRAIGHT + [_port("C", (0.70710678, 0.70710678, 0.0), 100.0)]
    params = {"BoxLength": 400.0, "BoxWidth": 400.0, "BoxHeight": 400.0}
    with pytest.raises(ValueError, match="does not fit on the box face"):
        boxes.measure_plenum(_ctx(ports, params))


def test_a_duct_that_passes_beside_the_box_is_an_error():
    ports = [_port("A", (-1.0, 0.0, 0.0)), _port("B", (1.0, 0.0, 0.0), position=(0.0, 900.0, 0.0))]
    with pytest.raises(ValueError, match="beside the box"):
        boxes.measure_plenum(_ctx(ports))


def test_a_duct_too_large_for_its_face_overhangs():
    params = {"BoxLength": 600.0, "BoxWidth": 150.0, "BoxHeight": 150.0}
    with pytest.raises(ValueError, match="overhangs by 25.0 mm"):
        boxes.measure_plenum(_ctx(_STRAIGHT, params))


def test_build_and_measure_report_the_same_trims():
    context = _ctx(_TEE, {"BoxLength": 600.0, "TrimLength": 30.0})
    assert boxes.build_plenum(dict(context))["connection_lengths"] == boxes.measure_plenum(dict(context))


# ----------------------------------------------------------------------------
# Rectangular ducts on a face
# ----------------------------------------------------------------------------


def test_section_half_extent_follows_the_ducts_own_axes():
    port = _port("A", (1.0, 0.0, 0.0))
    port.update(profile="Rectangular", section_params={"Width": 400.0, "Height": 200.0})
    _placement, x_axis, y_axis, _z = HVACLibraryAPI.make_profile_frame(port["direction"], None)
    assert boxes._section_half_extent(HVACLibraryAPI, port, x_axis) == pytest.approx(200.0)
    assert boxes._section_half_extent(HVACLibraryAPI, port, y_axis) == pytest.approx(100.0)


# ----------------------------------------------------------------------------
# AHU connection
# ----------------------------------------------------------------------------


def test_ahu_casing_stands_behind_the_node():
    layout = boxes._box_layout(_ctx([_port("A", (1.0, 0.0, 0.0))]), "ahu")
    assert layout["dims"] == (600.0, 400.0, 400.0)
    # The duct points along +x, so the casing is centred half a length the other way.
    centre = layout["centre"]
    assert (centre.x, centre.y, centre.z) == pytest.approx((-300.0, 0.0, 0.0))


def test_ahu_trim_is_the_neck_alone():
    context = _ctx([_port("A", (1.0, 0.0, 0.0))], {"TrimNeck": 120.0})
    assert _trims(boxes.measure_ahu(context)) == {"A": pytest.approx(120.0)}


def test_ahu_neck_defaults_to_a_quarter_of_the_duct():
    assert _trims(boxes.measure_ahu(_ctx([_port("A", (1.0, 0.0, 0.0))]))) == {"A": pytest.approx(50.0)}


def test_ahu_connection_can_sit_off_centre_on_the_face():
    params = {"BoxWidth": 1000.0, "BoxHeight": 1000.0, "ConnectionOffsetY": 300.0, "ConnectionOffsetZ": -300.0}
    context = _ctx([_port("A", (1.0, 0.0, 0.0))], params)
    assert _trims(boxes.measure_ahu(context)) == {"A": pytest.approx(50.0)}


def test_ahu_connection_pushed_off_the_face_is_an_error():
    params = {"BoxWidth": 400.0, "BoxHeight": 400.0, "ConnectionOffsetY": 150.0}
    with pytest.raises(ValueError, match="overhangs by 50.0 mm"):
        boxes.measure_ahu(_ctx([_port("A", (1.0, 0.0, 0.0))], params))


def test_ahu_takes_exactly_one_port():
    with pytest.raises(ValueError):
        boxes.measure_ahu(_ctx(_STRAIGHT))


# ----------------------------------------------------------------------------
# Automatic plenum size: grows so every duct fits on its face
# ----------------------------------------------------------------------------


_DIAGONAL = 0.7071067811865476


def test_automatic_plenum_grows_so_a_diagonal_duct_fits_on_its_face():
    # A 200 mm duct leaving at 45 degrees hits the default 400 mm box at its corner.
    ports = [_port("A", (-1.0, 0.0, 0.0)), _port("B", (_DIAGONAL, _DIAGONAL, 0.0))]
    layout = boxes._box_layout(_ctx(ports), "plenum")
    for port in ports:
        _leave, _chord, needed = boxes._port_fit(
            HVACLibraryAPI, port, layout["centre"], layout["axes"], [d / 2.0 for d in layout["dims"]]
        )
        assert all(needed[i] <= layout["dims"][i] / 2.0 + 1e-6 for i in needed)
    assert max(layout["dims"]) > 400.0
    # Build and measure agree on the grown box.
    context = _ctx(ports)
    assert boxes.build_plenum(dict(context))["connection_lengths"] == boxes.measure_plenum(dict(context))


def test_a_size_the_user_set_is_never_grown():
    ports = [_port("A", (-1.0, 0.0, 0.0)), _port("B", (_DIAGONAL, _DIAGONAL, 0.0))]
    with pytest.raises(ValueError, match="overhangs"):
        boxes.measure_plenum(_ctx(ports, {"BoxLength": 400.0, "BoxWidth": 400.0, "BoxHeight": 400.0}))


def test_a_box_that_already_fits_keeps_its_default_size():
    assert boxes._box_layout(_ctx(_TEE), "plenum")["dims"] == (400.0, 400.0, 400.0)
