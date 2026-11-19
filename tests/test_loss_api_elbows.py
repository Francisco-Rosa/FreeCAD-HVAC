# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the HVAC addon.

"""
HVACLossAPI.elbow_loss by construction (smooth, gored, mitered, turning
vanes), the rule that W is the section dimension in the plane of the bend,
when a result is downgraded to APPROXIMATION, and the two shared loss
functions that fix the construction.
"""

import pytest

import conftest  # noqa: F401 -- installs FreeCAD/FreeCADGui/Part/PySide stubs
from freecad.HVAC.library.fittings import losses
from freecad.HVAC.library.loss_api import HVACLossAPI as api


def _port(edge_key, direction, into_node, profile, section, velocity_ms=10.0, reynolds=1.0e6, x_axis=None):
    return {
        "edge_key": edge_key,
        "position": [0.0, 0.0, 0.0],
        "direction": list(direction),
        "profile": profile,
        "section_params": dict(section),
        "profile_x_axis": list(x_axis) if x_axis is not None else None,
        "flow_into_junction": into_node,
        "velocity_ms": velocity_ms,
        "reynolds": reynolds,
    }


def _elbow(properties, profile="Circular", section=None, turn_deg=90, **port_kwargs):
    """An elbow in the XY plane: air comes in along +X and turns by `turn_deg` toward +Y."""
    import math

    section = section or {"Diameter": 200.0}
    a = math.radians(turn_deg)
    inlet = _port("IN", (-1.0, 0.0, 0.0), True, profile, section, **port_kwargs)
    outlet = _port("OUT", (math.cos(a), math.sin(a), 0.0), False, profile, section, **port_kwargs)
    return {"connected_ports": [inlet, outlet], "properties": dict(properties)}


def _k(result):
    assert len(result.paths) == 1
    return result.paths[0].loss_coefficient


def _rect(width, height):
    return {"Width": width, "Height": height}


# ----------------------------------------------------------------------------
# Smooth radius
# ----------------------------------------------------------------------------


def test_smooth_round_is_the_default_construction():
    result = api.elbow_loss(_elbow({"CenterlineRadius": 200.0}))
    assert result.status == api.EXACT
    assert _k(result) == pytest.approx(0.22)
    assert result.paths[0].source == "smacna_elbow"


def test_smooth_round_outside_the_table_is_an_approximation():
    result = api.elbow_loss(_elbow({"CenterlineRadius": 1000.0}))
    assert result.status == api.APPROXIMATION
    assert _k(result) == pytest.approx(0.12)
    assert "printed range" in result.warning


def test_smooth_rectangular_needs_a_reynolds_number():
    context = _elbow({"CenterlineRadius": 400.0}, "Rectangular", _rect(400.0, 400.0), reynolds=0.0)
    assert api.elbow_loss(context).status == api.UNSUPPORTED


def test_smooth_rectangular_reads_14_10f():
    # W 400 in the plane of the bend, H/W = 1, R/W = 1 -> 0.21 at high Re.
    result = api.elbow_loss(_elbow({"CenterlineRadius": 400.0}, "Rectangular", _rect(400.0, 400.0)))
    assert result.status == api.EXACT
    assert _k(result) == pytest.approx(0.21)


@pytest.mark.parametrize("vanes, k", [(1, 0.11), (2, 0.04), (3, 0.02)])
def test_splitter_vanes_read_14_10g_with_the_throat_radius(vanes, k):
    # W = H = 400, centreline R 300 -> throat 100, R/W = 0.25, H/W = 1.0.
    context = _elbow({"CenterlineRadius": 300.0, "SplitterVanes": vanes}, "Rectangular", _rect(400.0, 400.0))
    result = api.elbow_loss(context)
    assert result.status == api.EXACT
    assert _k(result) == pytest.approx(k)


def test_more_than_three_splitter_vanes_reads_three_and_says_so():
    context = _elbow({"CenterlineRadius": 300.0, "SplitterVanes": 5}, "Rectangular", _rect(400.0, 400.0))
    result = api.elbow_loss(context)
    assert result.status == api.APPROXIMATION
    assert _k(result) == pytest.approx(0.02)
    assert "3 splitter vanes" in result.warning


def test_splitter_vanes_need_a_throat():
    context = _elbow({"CenterlineRadius": 150.0, "SplitterVanes": 1}, "Rectangular", _rect(400.0, 400.0))
    result = api.elbow_loss(context)
    assert result.status == api.UNSUPPORTED
    assert "throat" in result.warning


# ----------------------------------------------------------------------------
# Gored (made of straight pieces)
# ----------------------------------------------------------------------------


def test_gored_round_reads_14_10b_with_cuts_plus_one_pieces():
    # 3 cuts -> 4 pieces, R/D = 1.0 -> 0.37.
    result = api.elbow_loss(_elbow({"ElbowConstruction": "gored", "NumberOfCuts": 3, "CenterlineRadius": 200.0}))
    assert result.status == api.EXACT
    assert _k(result) == pytest.approx(0.37)
    assert result.paths[0].source == "smacna_elbow_gored"


def test_gored_round_in_a_blank_cell_is_an_approximation():
    # 5 pieces have no printed value at R/D = 0.5.
    result = api.elbow_loss(_elbow({"ElbowConstruction": "gored", "NumberOfCuts": 4, "CenterlineRadius": 100.0}))
    assert result.status == api.APPROXIMATION
    assert "blank" in result.warning


def test_gored_round_with_more_than_five_pieces_reads_five():
    result = api.elbow_loss(_elbow({"ElbowConstruction": "gored", "NumberOfCuts": 7, "CenterlineRadius": 200.0}))
    assert result.status == api.APPROXIMATION
    assert _k(result) == pytest.approx(0.33)
    assert "5 pieces" in result.warning


def test_gored_with_one_cut_is_a_plain_mitered_elbow():
    result = api.elbow_loss(_elbow({"ElbowConstruction": "gored", "NumberOfCuts": 1, "CenterlineRadius": 200.0}))
    assert _k(result) == pytest.approx(1.2)
    assert result.paths[0].source == "smacna_elbow_mitered"


def test_gored_rectangular_has_no_table_and_uses_the_smooth_one():
    properties = {"ElbowConstruction": "gored", "NumberOfCuts": 3, "CenterlineRadius": 400.0}
    result = api.elbow_loss(_elbow(properties, "Rectangular", _rect(400.0, 400.0)))
    assert result.status == api.APPROXIMATION
    assert _k(result) == pytest.approx(0.21)
    assert "gored rectangular" in result.warning


def test_smooth_and_gored_need_a_radius():
    assert api.elbow_loss(_elbow({})).status == api.UNSUPPORTED
    assert api.elbow_loss(_elbow({"ElbowConstruction": "gored", "NumberOfCuts": 3})).status == api.UNSUPPORTED


# ----------------------------------------------------------------------------
# Mitered, and which side is W
# ----------------------------------------------------------------------------


def test_mitered_round_with_and_without_reynolds_correction():
    assert _k(api.elbow_loss(_elbow({"ElbowConstruction": "mitered"}))) == pytest.approx(1.2)
    low_re = api.elbow_loss(_elbow({"ElbowConstruction": "mitered"}, reynolds=2.0e4))
    assert _k(low_re) == pytest.approx(1.2 * 1.26)


def test_mitered_round_at_45_degrees():
    assert _k(api.elbow_loss(_elbow({"ElbowConstruction": "mitered"}, turn_deg=45))) == pytest.approx(0.34)


def test_mitered_rectangular_takes_w_in_the_plane_of_the_bend():
    section = _rect(400.0, 200.0)
    # Default section frame: the duct's Width lies in the plane of the bend -> H/W = 0.5 -> 1.3.
    in_plane = api.elbow_loss(_elbow({"ElbowConstruction": "mitered"}, "Rectangular", section))
    assert _k(in_plane) == pytest.approx(1.3)
    # Width turned out of the plane (along Z): the tables' W is the duct's Height -> H/W = 2.0 -> 1.1.
    turned = api.elbow_loss(_elbow({"ElbowConstruction": "mitered"}, "Rectangular", section, x_axis=(0.0, 0.0, 1.0)))
    assert _k(turned) == pytest.approx(1.1)


def test_mitered_rectangular_at_another_angle():
    # H/W = 1.0 at 60 degrees -> 0.55.
    result = api.elbow_loss(_elbow({"ElbowConstruction": "mitered"}, "Rectangular", _rect(300.0, 300.0), turn_deg=60))
    assert _k(result) == pytest.approx(0.55)


# ----------------------------------------------------------------------------
# Turning vanes
# ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "design, velocity, k",
    [("single_r50_s38", 10.0, 0.22), ("Double R50 S56", 7.5, 0.52), ("double_r114_s83", 12.5, 0.23)],
)
def test_turning_vanes_read_14_10h(design, velocity, k):
    properties = {"ElbowConstruction": "Turning vanes", "VaneDesign": design}
    result = api.elbow_loss(_elbow(properties, "Rectangular", _rect(400.0, 300.0), velocity_ms=velocity))
    assert result.status == api.EXACT
    assert _k(result) == pytest.approx(k)
    assert result.paths[0].source == "smacna_elbow_turning_vanes"


def test_turning_vanes_default_design():
    result = api.elbow_loss(_elbow({"ElbowConstruction": "turning_vanes"}, "Rectangular", _rect(400.0, 300.0)))
    assert _k(result) == pytest.approx(0.22)


def test_turning_vanes_off_90_degrees_is_an_approximation():
    context = _elbow({"ElbowConstruction": "turning_vanes"}, "Rectangular", _rect(400.0, 300.0), turn_deg=60)
    result = api.elbow_loss(context)
    assert result.status == api.APPROXIMATION
    assert "90 degree" in result.warning


def test_turning_vanes_are_rectangular_only():
    assert api.elbow_loss(_elbow({"ElbowConstruction": "turning_vanes"})).status == api.UNSUPPORTED


def test_turning_vanes_unknown_design_is_unsupported():
    context = _elbow({"ElbowConstruction": "turning_vanes", "VaneDesign": "triple"}, "Rectangular", _rect(400.0, 300.0))
    assert api.elbow_loss(context).status == api.UNSUPPORTED


# ----------------------------------------------------------------------------
# Other cases
# ----------------------------------------------------------------------------


def test_unknown_construction_is_unsupported():
    result = api.elbow_loss(_elbow({"ElbowConstruction": "spiral", "CenterlineRadius": 200.0}))
    assert result.status == api.UNSUPPORTED
    assert "spiral" in result.warning


def test_oval_is_read_as_rectangular_and_flagged():
    result = api.elbow_loss(_elbow({"ElbowConstruction": "mitered"}, "Oval", _rect(400.0, 200.0)))
    assert result.status == api.APPROXIMATION
    assert _k(result) == pytest.approx(1.3)
    assert "Oval" in result.warning


def test_path_runs_from_inlet_to_outlet_referenced_to_the_outlet():
    path = api.elbow_loss(_elbow({"CenterlineRadius": 200.0})).paths[0]
    assert (path.from_edge_key, path.to_edge_key, path.reference_edge_key) == ("IN", "OUT", "OUT")


# ----------------------------------------------------------------------------
# Shared loss functions that fix the construction
# ----------------------------------------------------------------------------


def _with_api(context):
    context["loss_api"] = api
    return context


def test_loss_elbow_mitered_forces_the_gored_construction():
    context = _with_api(_elbow({"ElbowConstruction": "smooth", "NumberOfCuts": 3, "CenterlineRadius": 200.0}))
    result = losses.loss_elbow_mitered(context)
    assert _k(result) == pytest.approx(0.37)
    # The caller's own properties are left alone.
    assert context["properties"]["ElbowConstruction"] == "smooth"


def test_loss_elbow_mitered_with_one_cut_is_mitered():
    context = _with_api(_elbow({"NumberOfCuts": 1, "CenterlineRadius": 200.0}))
    assert _k(losses.loss_elbow_mitered(context)) == pytest.approx(1.2)


def test_loss_elbow_vaned_forces_turning_vanes():
    context = _with_api(_elbow({"VaneDesign": "double_r50_s38"}, "Rectangular", _rect(400.0, 300.0), velocity_ms=5.0))
    result = losses.loss_elbow_vaned(context)
    assert _k(result) == pytest.approx(0.43)
    assert result.paths[0].source == "smacna_elbow_turning_vanes"
