# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the HVAC addon.

"""
HVACLossAPI.branch_loss and wye_loss on the SMACNA tables: which table each
tee reads (round, rectangular main, BranchStyle variants), how the branch
angle is measured, when the result is EXACT or APPROXIMATION, and the
symmetric wye tables.
"""

import math

import pytest

import conftest  # noqa: F401 -- installs FreeCAD/FreeCADGui/Part/PySide stubs
from freecad.HVAC.library.loss_api import HVACLossAPI as api
from freecad.HVAC.library.loss_tables import junctions_converging as conv
from freecad.HVAC.library.loss_tables import junctions_diverging as div


def _port(edge_key, direction, into_node, velocity_ms, **section):
    if "diameter" in section:
        profile, params = "Circular", {"Diameter": section["diameter"]}
    else:
        profile = section.get("profile", "Rectangular")
        params = {"Width": section["width"], "Height": section["height"]}
    return {
        "edge_key": edge_key,
        "position": [0.0, 0.0, 0.0],
        "direction": list(direction),
        "profile": profile,
        "section_params": params,
        "profile_x_axis": None,
        "flow_into_junction": into_node,
        "velocity_ms": velocity_ms,
    }


def _tee(main, branch, v=(5.0, 4.0, 3.0), diverging=True, branch_angle=90.0, properties=None, straight=None):
    """
    A tee along X with the branch at `branch_angle` to the main flow.
    `main` / `branch` / `straight` are section kwargs for _port.
    """
    a = math.radians(branch_angle)
    if diverging:
        common = _port("C", (-1, 0, 0), True, v[0], **main)
        run = _port("S", (1, 0, 0), False, v[1], **(straight or main))
        leg = _port("B", (math.cos(a), math.sin(a), 0), False, v[2], **branch)
    else:
        common = _port("C", (1, 0, 0), False, v[0], **main)
        run = _port("S", (-1, 0, 0), True, v[1], **(straight or main))
        leg = _port("B", (-math.cos(a), math.sin(a), 0), True, v[2], **branch)
    return {"connected_ports": [common, run, leg], "properties": dict(properties or {})}


def _by_edge(result):
    return {p.reference_edge_key: p.loss_coefficient for p in result.paths}


def _source(result):
    return result.paths[0].source


def _area(**section):
    if "diameter" in section:
        return math.pi * (section["diameter"] / 2000.0) ** 2
    return section["width"] * section["height"] / 1.0e6


ROUND_MAIN = dict(diameter=300.0)
ROUND_BRANCH = dict(diameter=200.0)
RECT_MAIN = dict(width=400.0, height=300.0)
RECT_BRANCH = dict(width=200.0, height=300.0)


# ----------------------------------------------------------------------------
# Branch angle
# ----------------------------------------------------------------------------


@pytest.mark.parametrize("angle", [30.0, 45.0, 60.0])
def test_diverging_round_branch_angle_is_measured_from_the_main_flow(angle):
    # A branch leaning forward at `angle` reads the `angle` table, not the one for 180 - angle.
    context = _tee(ROUND_MAIN, ROUND_BRANCH, branch_angle=angle)
    ab_on_ac = _area(**ROUND_BRANCH) / _area(**ROUND_MAIN)
    branch, _main = div.round_tee_or_wye(angle, ab_on_ac, 0.6 * ab_on_ac, 0.8)
    assert _by_edge(api.branch_loss(context))["B"] == pytest.approx(branch.value / 0.6**2)


def test_converging_45_degree_branch_reads_the_wye_table():
    context = _tee(ROUND_MAIN, ROUND_BRANCH, diverging=False, branch_angle=45.0)
    ab_on_ac = _area(**ROUND_BRANCH) / _area(**ROUND_MAIN)
    branch, main = conv.wye_45_round(ab_on_ac, 0.6, 0.8)
    result = api.branch_loss(context)
    assert result.status == api.EXACT
    assert _by_edge(result) == pytest.approx({"B": branch.value / 0.6**2, "S": main.value / 0.8**2})


def test_converging_angle_far_from_45_and_90_is_an_approximation():
    result = api.branch_loss(_tee(ROUND_MAIN, ROUND_BRANCH, diverging=False, branch_angle=70.0))
    assert result.status == api.APPROXIMATION
    assert "45 and 90" in result.warning


# ----------------------------------------------------------------------------
# Round tees
# ----------------------------------------------------------------------------


def test_round_diverging_tee_inside_the_table_is_exact():
    result = api.branch_loss(_tee(ROUND_MAIN, ROUND_BRANCH))
    assert result.status == api.EXACT
    assert _source(result) == "smacna_branch_diverging"


def test_round_diverging_tee_in_a_blank_cell_is_an_approximation():
    # Small branch carrying a lot of flow: past the triangle the table prints.
    result = api.branch_loss(_tee(ROUND_MAIN, dict(diameter=100.0), v=(5.0, 1.0, 30.0)))
    assert result.status == api.APPROXIMATION
    assert "blank" in result.warning


@pytest.mark.parametrize("angle, variant", [(90.0, "conical_tee_90"), (45.0, "conical_wye_45")])
def test_conical_round_branch_reads_14_14_b_or_c(angle, variant):
    context = _tee(ROUND_MAIN, ROUND_BRANCH, branch_angle=angle, properties={"BranchStyle": "Conical"})
    branch, main = div.round_variant(variant, 0.6, 0.8)
    result = api.branch_loss(context)
    assert result.status == api.EXACT
    assert _by_edge(result) == pytest.approx({"B": branch.value / 0.6**2, "S": main.value / 0.8**2})
    assert _source(result) == "smacna_tee_" + variant


def test_converging_conical_has_no_table_and_uses_the_plain_one():
    context = _tee(ROUND_MAIN, ROUND_BRANCH, diverging=False, properties={"BranchStyle": "conical"})
    result = api.branch_loss(context)
    assert result.status == api.APPROXIMATION
    assert "conical" in result.warning


def test_unknown_branch_style_is_unsupported():
    assert api.branch_loss(_tee(ROUND_MAIN, ROUND_BRANCH, properties={"BranchStyle": "Bellmouth"})).status == (
        api.UNSUPPORTED
    )


# ----------------------------------------------------------------------------
# Rectangular main
# ----------------------------------------------------------------------------


def _rect_ratios(branch=RECT_BRANCH, v=(5.0, 4.0, 6.0)):
    ab_on_ac = _area(**branch) / _area(**RECT_MAIN)
    vb_on_vc, vs_on_vc = v[2] / v[0], v[1] / v[0]
    return vb_on_vc, vb_on_vc * ab_on_ac, vs_on_vc


@pytest.mark.parametrize(
    "style, branch, kind",
    [
        ("straight", RECT_BRANCH, "rect_branch"),
        ("straight", ROUND_BRANCH, "round_branch"),
        ("45 entry", RECT_BRANCH, "rect_branch_45_entry"),
        ("Damper", RECT_BRANCH, "rect_branch_damper"),
        ("45 entry damper", RECT_BRANCH, "rect_branch_45_entry_damper"),
        ("extractor", RECT_BRANCH, "rect_branch_extractor"),
    ],
)
def test_diverging_rectangular_main_reads_the_rectangular_tables(style, branch, kind):
    context = _tee(RECT_MAIN, branch, v=(5.0, 4.0, 6.0), properties={"BranchStyle": style})
    vb_on_vc, qb_on_qc, vs_on_vc = _rect_ratios(branch)
    branch_l, main_l = div.tee_rect_main(kind, vb_on_vc, qb_on_qc, vs_on_vc)
    result = api.branch_loss(context)
    assert _by_edge(result) == pytest.approx({"B": branch_l.value / vb_on_vc**2, "S": main_l.value / vs_on_vc**2})
    assert _source(result) == "smacna_tee_rect_" + kind


def test_diverging_rectangular_main_with_conical_branch_reads_14_14v():
    context = _tee(RECT_MAIN, ROUND_BRANCH, v=(5.0, 4.0, 5.0), properties={"BranchStyle": "conical"})
    branch_l, main_l = div.tee_rect_main_conical_branch(1.0, 0.8)
    result = api.branch_loss(context)
    assert result.status == api.EXACT
    assert _by_edge(result) == pytest.approx({"B": branch_l.value, "S": main_l.value / 0.8**2})


def test_diverging_rectangular_main_that_changes_size_falls_back_to_round_tables():
    context = _tee(RECT_MAIN, RECT_BRANCH, v=(5.0, 4.0, 6.0), straight=dict(width=300.0, height=300.0))
    result = api.branch_loss(context)
    assert result.status == api.APPROXIMATION
    assert "keeps its size" in result.warning
    assert _source(result) == "smacna_branch_diverging"


def test_rectangular_main_with_an_inclined_branch_falls_back_to_round_tables():
    result = api.branch_loss(_tee(RECT_MAIN, RECT_BRANCH, v=(5.0, 4.0, 6.0), branch_angle=45.0))
    assert result.status == api.APPROXIMATION
    assert "round tee tables" in result.warning


def test_converging_rectangular_tee_at_its_printed_proportions_reads_14_13d():
    # Ab/As = 0.5, As/Ac = 1.0, Ab/Ac = 0.5: main 400 x 300, branch 200 x 300.
    vc = 5.0
    context = _tee(RECT_MAIN, RECT_BRANCH, v=(vc, 4.0, 6.0), diverging=False)
    _vb, qb_on_qc, _vs = _rect_ratios()
    branch_l, main_l = conv.tee_rect_main("rect_branch", qb_on_qc, vc)
    result = api.branch_loss(context)
    assert _by_edge(result) == pytest.approx(
        {"B": branch_l.value / (6.0 / vc) ** 2, "S": main_l.value / (4.0 / vc) ** 2}
    )
    assert _source(result) == "smacna_tee_rect_rect_branch"


def test_converging_rectangular_tee_with_45_entry_reads_14_13f():
    context = _tee(RECT_MAIN, RECT_BRANCH, v=(8.0, 4.0, 6.0), diverging=False, properties={"BranchStyle": "45_entry"})
    assert _source(api.branch_loss(context)) == "smacna_tee_rect_rect_branch_45_entry"


def test_converging_rectangular_tee_at_other_proportions_is_an_approximation():
    context = _tee(RECT_MAIN, dict(width=100.0, height=300.0), v=(5.0, 4.0, 6.0), diverging=False)
    result = api.branch_loss(context)
    assert result.status == api.APPROXIMATION
    assert "Ab/As 0.5" in result.warning


def test_converging_rectangular_damper_has_no_table():
    context = _tee(RECT_MAIN, RECT_BRANCH, v=(5.0, 4.0, 6.0), diverging=False, properties={"BranchStyle": "damper"})
    result = api.branch_loss(context)
    assert result.status == api.APPROXIMATION
    assert "no converging table for a damper" in result.warning


def test_oval_tee_uses_round_tables_and_says_so():
    oval = dict(profile="Oval", width=400.0, height=200.0)
    result = api.branch_loss(_tee(oval, dict(profile="Oval", width=200.0, height=100.0)))
    assert result.status == api.APPROXIMATION
    assert "Oval" in result.warning


# ----------------------------------------------------------------------------
# Symmetric wye
# ----------------------------------------------------------------------------


def _wye(angle, leg_section, common_section, v=(5.0, 4.0, 4.0), diverging=True):
    a = math.radians(angle)
    if diverging:
        common = _port("C", (-1, 0, 0), True, v[0], **common_section)
        legs = [
            _port("L1", (math.cos(a), math.sin(a), 0), False, v[1], **leg_section),
            _port("L2", (math.cos(a), -math.sin(a), 0), False, v[2], **leg_section),
        ]
    else:
        common = _port("C", (1, 0, 0), False, v[0], **common_section)
        legs = [
            _port("L1", (-math.cos(a), math.sin(a), 0), True, v[1], **leg_section),
            _port("L2", (-math.cos(a), -math.sin(a), 0), True, v[2], **leg_section),
        ]
    return {"connected_ports": [common] + legs, "properties": {}}


# Two 300 x 200 legs adding up to a 600 x 200 common duct.
LEG = dict(width=300.0, height=200.0)
COMMON = dict(width=600.0, height=200.0)


def test_symmetric_diverging_wye_reads_14_14y():
    result = api.wye_loss(_wye(30.0, LEG, COMMON))
    expected = div.wye_symmetric(30.0, 0.8).value / 0.8**2
    assert result.status == api.EXACT
    assert _by_edge(result) == pytest.approx({"L1": expected, "L2": expected})
    assert _source(result) == "smacna_wye_symmetric"


def test_symmetric_converging_wye_reads_14_13i_by_flow_share():
    # Each leg: V 4, area half of the common's, common V 5 -> carries 0.4 of the flow.
    result = api.wye_loss(_wye(45.0, LEG, COMMON, diverging=False))
    expected = conv.wye_symmetric(45.0, 0.4).value / 0.8**2
    assert result.status == api.EXACT
    assert _by_edge(result) == pytest.approx({"L1": expected, "L2": expected})


def test_symmetric_wye_beyond_the_printed_angles_is_an_approximation():
    result = api.wye_loss(_wye(60.0, LEG, COMMON, diverging=False))
    assert result.status == api.APPROXIMATION
    assert _source(result) == "smacna_wye_symmetric"


def test_wye_whose_legs_do_not_add_up_uses_the_general_approximation():
    result = api.wye_loss(_wye(30.0, LEG, dict(width=800.0, height=200.0)))
    assert result.status == api.APPROXIMATION
    assert _source(result) != "smacna_wye_symmetric"


def test_unequal_wye_uses_the_general_approximation():
    context = _wye(30.0, LEG, COMMON)
    context["connected_ports"][2]["section_params"] = {"Width": 200.0, "Height": 200.0}
    assert api.wye_loss(context).paths[0].source != "smacna_wye_symmetric"


# ----------------------------------------------------------------------------
# Shared loss functions that fix the branch style
# ----------------------------------------------------------------------------


def test_loss_tee_conical_and_45_entry_force_their_branch_style():
    from freecad.HVAC.library.fittings import losses

    conical = _tee(ROUND_MAIN, ROUND_BRANCH)
    conical["loss_api"] = api
    assert _source(losses.loss_tee_conical(conical)) == "smacna_tee_conical_tee_90"
    assert "BranchStyle" not in conical["properties"]

    shoe = _tee(RECT_MAIN, RECT_BRANCH, v=(5.0, 4.0, 6.0))
    shoe["loss_api"] = api
    assert _source(losses.loss_tee_45_entry(shoe)) == "smacna_tee_rect_rect_branch_45_entry"


# ----------------------------------------------------------------------------
# Round branch tables used by the manifold and no-straight-leg breakdowns
# (moved from the old smacna_loss tests)
# ----------------------------------------------------------------------------


def test_diverging_branch_tee90_exact_grid_point():
    # Table 14-14 A (90 deg) is keyed by Ab/Ac and the FLOW ratio Qb/Qc.
    # Ab/Ac = 0.5 with Vb/Vc = 1.0 gives Qb/Qc = 0.5 -> printed C = 1.4.
    zeta_branch, _ = api._round_branch_zetas(True, angle_deg=90.0, ab_on_ac=0.5, vb_on_vc=1.0, vs_on_vc=0.4)
    assert zeta_branch == pytest.approx(1.40 / (1.0**2))


def test_diverging_branch_lookup_uses_flow_ratio_not_velocity_ratio():
    # Ab/Ac = 0.5, Vb/Vc = 0.4 -> Qb/Qc = 0.2 -> printed C = 1.0 (not the
    # 1.2 printed under 0.4, which is what a velocity-ratio lookup would hit).
    zeta_branch, _ = api._round_branch_zetas(True, angle_deg=90.0, ab_on_ac=0.5, vb_on_vc=0.4, vs_on_vc=0.4)
    assert zeta_branch == pytest.approx(1.0 / (0.4**2))


def test_diverging_branch_tee90_straight_leg_exact_grid_point():
    # vs_on_vc=0.4 (index4 of [0,0.1,...,1.0]) -> raw zeta_c=0.13
    _, zeta_straight = api._round_branch_zetas(True, angle_deg=90.0, ab_on_ac=0.5, vb_on_vc=0.5, vs_on_vc=0.4)
    assert zeta_straight == pytest.approx(0.13 / (0.4**2))


def test_diverging_branch_selects_wye_vs_tee_table():
    wye_branch, _ = api._round_branch_zetas(True, angle_deg=45.0, ab_on_ac=0.5, vb_on_vc=0.5, vs_on_vc=0.4)
    tee_branch, _ = api._round_branch_zetas(True, angle_deg=90.0, ab_on_ac=0.5, vb_on_vc=0.5, vs_on_vc=0.4)
    assert wye_branch != tee_branch


def test_converging_branch_tee90_exact_grid_point():
    # Table 14-13 B is keyed by Ab/Ac and the FLOW ratio Qb/Qc.
    # Ab/Ac = 0.4 with Vb/Vc = 1.0 gives Qb/Qc = 0.4 -> printed branch C = 0.94.
    zeta_branch, _ = api._round_branch_zetas(False, angle_deg=90.0, ab_on_ac=0.4, vb_on_vc=1.0, vs_on_vc=0.6)
    assert zeta_branch == pytest.approx(0.94 / (1.0**2))


def test_converging_branch_tee90_main_uses_flow_ratio():
    # Main coefficient is printed against Qb/Qc: 0.4 -> 0.46.
    _, zeta_straight = api._round_branch_zetas(False, angle_deg=90.0, ab_on_ac=0.4, vb_on_vc=1.0, vs_on_vc=0.5)
    assert zeta_straight == pytest.approx(0.46 / (0.5**2))


def test_converging_branch_wye45_stays_velocity_keyed():
    # Table 14-13 A really is keyed by Vb/Vc: Ab/Ac = 0.4, Vb/Vc = 0.5 -> -0.21.
    zeta_branch, _ = api._round_branch_zetas(False, angle_deg=45.0, ab_on_ac=0.4, vb_on_vc=0.5, vs_on_vc=0.5)
    assert zeta_branch == pytest.approx(-0.21 / (0.5**2))


def test_converging_branch_wye_vs_tee_differ():
    wye_branch, _ = api._round_branch_zetas(False, angle_deg=45.0, ab_on_ac=0.4, vb_on_vc=0.7, vs_on_vc=0.6)
    tee_branch, _ = api._round_branch_zetas(False, angle_deg=90.0, ab_on_ac=0.4, vb_on_vc=0.7, vs_on_vc=0.6)
    assert wye_branch != tee_branch


@pytest.mark.parametrize(
    "function, style",
    [
        ("loss_tee_damper", "damper"),
        ("loss_tee_45_entry_damper", "45_entry_damper"),
        ("loss_tee_extractor", "extractor"),
    ],
)
def test_smacna_branch_style_wrappers_pass_their_style(function, style):
    # The SMACNA-only branch types (Stage 7 c) read their table through branch_loss with a fixed BranchStyle.
    from freecad.HVAC.library.fittings import losses

    seen = {}

    class LossApi:
        @staticmethod
        def branch_loss(context):
            seen["style"] = context["properties"]["BranchStyle"]
            return "result"

    assert getattr(losses, function)({"loss_api": LossApi, "properties": {"Other": 1}}) == "result"
    assert seen["style"] == style
