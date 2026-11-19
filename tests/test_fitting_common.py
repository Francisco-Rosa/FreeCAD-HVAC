# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the HVAC addon.

"""
Property/port handling shared by the fitting modules in library/fittings/:
which property a port's trim and flange switch come from, and how a layer's
thickness is read. No shape construction is exercised here.
"""

from types import SimpleNamespace

import conftest  # noqa: F401 -- installs FreeCAD/FreeCADGui/Part/PySide stubs
from freecad.HVAC.library.fittings import _common, stars
from freecad.HVAC.library.library_api import HVACLibraryAPI
from freecad.HVAC.library.validation import PortValues


def _port(edge_key, direction):
    return {
        "edge_key": edge_key,
        "position": [0.0, 0.0, 0.0],
        "direction": list(direction),
        "profile": "Circular",
        "section_params": {"Diameter": 200.0},
        "profile_x_axis": None,
        "segment_end": "start",
    }


def _tee_context(params):
    # Port order on purpose is not run, run, branch: the branch comes first.
    ports = [_port("C", (0.0, 1.0, 0.0)), _port("A", (-1.0, 0.0, 0.0)), _port("B", (1.0, 0.0, 0.0))]
    return {
        "hvac_api": HVACLibraryAPI,
        "properties": params,
        "connected_ports": ports,
        "center_point": (0.0, 0.0, 0.0),
        "analysis": {"collinear_pairs": [{"a": 1, "b": 2}]},
    }


def test_layer_thickness_reads_the_property_the_layer_names():
    layer = SimpleNamespace(thickness_property="Thickness")
    assert _common._layer_thickness(layer, {"Thickness": 1.2}) == 1.2
    assert _common._layer_thickness(layer, {}) == 0.0
    assert _common._layer_thickness(SimpleNamespace(thickness_property=None), {"Thickness": 1.2}) == 0.0


def test_wall_thickness_sums_every_layer_that_names_a_thickness():
    layers = [
        SimpleNamespace(thickness_property="Thickness"),
        SimpleNamespace(thickness_property="InsulationThickness"),
        SimpleNamespace(thickness_property=None),
    ]
    context = {"properties": {"Thickness": 1.0, "InsulationThickness": 25.0}, "construction_layers": layers}
    assert _common._wall_thickness(context) == 26.0
    assert _common._wall_thickness({"properties": {}}) == 0.0


def test_min_bend_radius_adds_the_wall_and_a_clearance_to_half_the_size():
    # Small ducts get a 1 mm clearance, large ones 1 % of the size.
    assert _common._min_bend_radius(50.0) == 26.0
    assert _common._min_bend_radius(400.0, wall=26.0) == 200.0 + 26.0 + 4.0
    # A negative wall (never expected) does not lower the minimum below the bare duct's.
    assert _common._min_bend_radius(400.0, wall=-5.0) == 204.0


def test_flange_switch_prefers_role_then_number_then_shared():
    params = {"ShowFlangeBranch": False, "ShowFlange2": True, "ShowFlange": True}
    assert _common._flange_enabled(params, 1, "Branch") is False
    assert _common._flange_enabled({"ShowFlange2": False, "ShowFlange": True}, 1, "Branch") is False
    assert _common._flange_enabled({"ShowFlange": False}, 1, "Branch") is False


def test_flange_switch_defaults_to_on_when_nothing_is_declared():
    assert _common._flange_enabled({}, 0, None) is True
    assert _common._flange_enabled({"ShowFlangeRunA": False}, 0, "RunB") is True


def test_star_tee_uses_role_named_trims_matched_to_the_run_pair():
    context = _tee_context({"TrimRunA": 110.0, "TrimRunB": 120.0, "TrimBranch": 130.0})
    records = stars.measure_branch_generic(context)
    assert {rec["edge_key"]: rec["length"] for rec in records} == {"A": 110.0, "B": 120.0, "C": 130.0}


def test_star_tee_without_role_names_uses_the_per_port_trim():
    context = _tee_context({"TrimLength": PortValues({"C": 110.0, "A": 120.0, "B": 130.0}, default=100.0)})
    records = stars.measure_branch_generic(context)
    assert {rec["edge_key"]: rec["length"] for rec in records} == {"C": 110.0, "A": 120.0, "B": 130.0}


def test_per_port_flange_switch_is_read_for_that_port():
    switches = PortValues({"A": False}, default=True)
    assert _common._flange_enabled({"ShowFlange": switches}, 0, None, {"edge_key": "A"}) is False
    assert _common._flange_enabled({"ShowFlange": switches}, 1, None, {"edge_key": "B"}) is True


def test_star_layout_reports_each_ports_role_for_flange_switches():
    context = _tee_context({"TrimRunA": 110.0, "TrimRunB": 120.0, "TrimBranch": 130.0})
    _ports, _center, _trims, suffixes = stars._star_junction_layout(context, 0.6, align_branch=True)
    assert suffixes == {"A": "RunA", "B": "RunB", "C": "Branch"}


# ----------------------------------------------------------------------------
# Offsets read their own properties and reuse the transition geometry
# ----------------------------------------------------------------------------


def _offset_ports():
    a = _port("A", (-1.0, 0.0, 0.0))
    b = _port("B", (1.0, 0.0, 0.0))
    b["position"] = [0.0, 150.0, 0.0]
    return [a, b]


def test_offset_length_sets_the_trims_not_transition_length():
    from freecad.HVAC.library.fittings import offsets

    context = {
        "hvac_api": HVACLibraryAPI,
        "properties": {"OffsetLength": 400.0, "TransitionLength": 999.0},
        "connected_ports": _offset_ports(),
    }
    records = offsets.measure_offset_angled(context)
    assert [rec["length"] for rec in records] == [200.0, 200.0]


def test_offset_does_not_change_the_callers_params():
    from freecad.HVAC.library.fittings import offsets

    params = {"OffsetLength": 400.0}
    offsets.measure_offset_angled({"hvac_api": HVACLibraryAPI, "properties": params, "connected_ports": _offset_ports()})
    assert params == {"OffsetLength": 400.0}


# ----------------------------------------------------------------------------
# VAV box sizes
# ----------------------------------------------------------------------------


def _vav_context(params):
    ports = [_port("A", (-1.0, 0.0, 0.0)), _port("B", (1.0, 0.0, 0.0))]
    return {"hvac_api": HVACLibraryAPI, "properties": params, "connected_ports": ports}


def test_vav_box_sizes_default_from_the_duct_size():
    from freecad.HVAC.library.fittings import inline

    # Duct 200: casing 400 long (2 x), 300 x 300 (1.5 x), collars 50 (0.25 x).
    _ports, length, width, height, trim = inline._vav_box_layout(_vav_context({}))
    assert (length, width, height) == (400.0, 300.0, 300.0)
    assert trim == 250.0


def test_vav_box_trim_is_half_the_casing_plus_the_collar():
    from freecad.HVAC.library.fittings import inline

    params = {"BoxLength": 600.0, "BoxWidth": 500.0, "BoxHeight": 350.0, "CollarLength": 80.0}
    _ports, length, width, height, trim = inline._vav_box_layout(_vav_context(params))
    assert (length, width, height, trim) == (600.0, 500.0, 350.0, 380.0)
    records = inline.measure_vav_box(_vav_context(params))
    assert [rec["length"] for rec in records] == [380.0, 380.0]
