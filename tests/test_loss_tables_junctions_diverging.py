# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the HVAC addon.

"""SMACNA Table 14-14 (diverging junctions): spot values against the printed tables."""

import pytest

from freecad.HVAC.library.loss_tables import junctions_diverging as d
from freecad.HVAC.library.loss_tables import table as t


@pytest.mark.parametrize("vs_on_vc, c", [(0, 0.35), (0.4, 0.13), (0.7, 0.04), (1.0, 0.0)])
def test_14_14a_main(vs_on_vc, c):
    assert d.round_main(vs_on_vc).value == pytest.approx(c)


@pytest.mark.parametrize(
    "theta, ab_on_ac, qb_on_qc, c",
    [
        (30, 0.8, 0.1, 0.75),
        (30, 0.3, 0.7, 2.0),
        (45, 0.5, 0.5, 0.40),
        (45, 0.2, 0.4, 1.8),
        (60, 0.6, 0.9, 1.1),
        (60, 0.1, 0.2, 2.9),
        (90, 0.5, 0.5, 1.4),
        (90, 0.8, 0.9, 1.4),
        (90, 0.2, 0.3, 2.9),
    ],
)
def test_14_14a_branch(theta, ab_on_ac, qb_on_qc, c):
    branch, _ = d.round_tee_or_wye(theta, ab_on_ac, qb_on_qc, 0.5)
    assert branch.value == pytest.approx(c)
    assert branch.exact


def test_14_14a_branch_interpolates_between_angles():
    branch, _ = d.round_tee_or_wye(52.5, 0.5, 0.5, 0.5)
    assert branch.value == pytest.approx((0.40 + 0.68) / 2.0)


def test_14_14a_blank_cell_is_filled_and_flagged():
    branch, _ = d.round_tee_or_wye(90, 0.1, 0.5, 0.5)
    assert branch.value == pytest.approx(2.1)
    assert branch.filled


@pytest.mark.parametrize(
    "kind, vb_on_vc, c",
    [
        ("conical_tee_90", 0, 1.0),
        ("conical_tee_90", 1.0, 0.42),
        ("conical_wye_45", 1.2, 0.12),
        ("tee_90_rolled_45_elbow_45", 1.2, 1.87),
        ("tee_90_elbow_90", 2.0, 3.4),
        ("tee_90_rolled_45_elbow_60", 0.8, 1.45),
        ("conical_tee_90_rolled_45_elbow_45", 2.0, 1.02),
        ("conical_tee_90_rolled_45_elbow_60", 1.0, 0.79),
        ("wye_45_rolled_45_elbow_60", 1.6, 1.14),
        ("conical_wye_45_rolled_45_elbow_60", 1.4, 0.40),
        ("wye_45_rolled_45_elbow_30", 1.8, 1.22),
        ("conical_wye_45_rolled_45_elbow_30", 0.4, 0.71),
    ],
)
def test_14_14b_to_l_round_variants(kind, vb_on_vc, c):
    branch, main = d.round_variant(kind, vb_on_vc, 0.6)
    assert branch.value == pytest.approx(c)
    assert main.value == pytest.approx(0.06)


def test_14_14_every_letter_b_to_l_is_present():
    letters = sorted(table.table_id[-1] for table in d.ROUND_BRANCH_VARIANTS.values())
    assert letters == list("BCDEFGHIJKL")


def test_14_14_unknown_kinds_list_known_ones():
    with pytest.raises(ValueError) as excinfo:
        d.round_variant("square_tee", 1.0, 0.5)
    assert "conical_tee_90" in str(excinfo.value)
    with pytest.raises(ValueError):
        d.tee_rect_main("oval_branch", 1.0, 0.5, 0.5)


@pytest.mark.parametrize(
    "vb_on_vc, vs_on_vc, branch, main", [(0.2, 0.2, 0.76, 0.14), (1.0, 1.0, 0.56, 0.18), (3.0, 2.0, 4.2, 1.0)]
)
def test_14_14m(vb_on_vc, vs_on_vc, branch, main):
    got = d.wye_conical_main_and_branch(vb_on_vc, vs_on_vc)
    assert (got[0].value, got[1].value) == pytest.approx((branch, main))


@pytest.mark.parametrize(
    "kind, vb_on_vc, qb_on_qc, c",
    [
        ("rect_branch_45_entry", 0.2, 0.1, 0.91),
        ("rect_branch_45_entry", 1.8, 0.6, 2.24),
        ("rect_branch_45_entry_damper", 1.0, 0.3, 0.77),
        ("rect_branch_45_entry_damper", 1.8, 0.9, 1.92),
        ("rect_branch", 1.2, 0.4, 1.91),
        ("rect_branch", 1.8, 0.5, 3.72),
        ("rect_branch_damper", 1.6, 0.2, 3.30),
        ("rect_branch_damper", 0.8, 0.4, 1.01),
        ("rect_branch_extractor", 1.4, 0.7, 2.47),
        ("rect_branch_extractor", 1.0, 0.1, 1.48),
        ("round_branch", 1.8, 0.9, 2.07),
        ("round_branch", 0.6, 0.2, 1.10),
    ],
)
def test_14_14npqrst_triangular_tables(kind, vb_on_vc, qb_on_qc, c):
    branch, _ = d.tee_rect_main(kind, vb_on_vc, qb_on_qc, 0.5)
    assert branch.value == pytest.approx(c)
    assert branch.exact


def test_14_14_triangular_table_outside_the_triangle_is_flagged():
    # Vb/Vc = 0.4 only prints Qb/Qc = 0.1 and 0.2.
    branch, _ = d.tee_rect_main("rect_branch", 0.4, 0.6, 0.5)
    assert branch.value == pytest.approx(1.01)
    assert branch.filled


def test_14_14_damper_and_extractor_tees_use_the_extractor_main_coefficient():
    for kind in ("rect_branch_45_entry_damper", "rect_branch_damper", "rect_branch_extractor"):
        assert d.tee_rect_main(kind, 1.4, 0.5, 0.5)[1].value == pytest.approx(0.27)
    for kind in ("rect_branch_45_entry", "rect_branch", "round_branch"):
        assert d.tee_rect_main(kind, 1.4, 0.5, 0.5)[1].value == pytest.approx(0.09)


@pytest.mark.parametrize(
    "theta, vb_on_vc, c", [(15, 1.0, 0.06), (30, 0.4, 0.44), (60, 0.3, 0.79), (90, 0.8, 1.0), (45, 2.0, 1.0)]
)
def test_14_14u_branch(theta, vb_on_vc, c):
    assert d.wye_rect_angled(theta, vb_on_vc, 0.5, 0.5)[0].value == pytest.approx(c)


def test_14_14u_main_below_60_deg_ignores_area_ratio():
    for as_on_ac in (0.2, 0.5, 0.9):
        assert d.wye_rect_angled(45, 0.5, 1.4, as_on_ac)[1].value == pytest.approx(0.39)


@pytest.mark.parametrize(
    "as_on_ac, vs_on_vc, c", [(0.2, 1.4, 0.39), (0.5, 1.4, 0.79), (0.6, 1.0, 0.10), (0.7, 1.2, 0.14), (0.95, 0.8, 0.04)]
)
def test_14_14u_main_at_90_deg(as_on_ac, vs_on_vc, c):
    main = d.wye_rect_angled(90, 0.5, vs_on_vc, as_on_ac)[1]
    assert main.value == pytest.approx(c)
    assert not main.clamped


def test_14_14u_main_between_60_and_90_deg_is_interpolated():
    main = d.wye_rect_angled(75, 0.5, 1.4, 0.5)[1]
    assert main.value == pytest.approx((0.39 + 0.79) / 2.0)


@pytest.mark.parametrize("vb_on_vc, c", [(0.40, 0.80), (1.0, 1.0), (1.5, 1.4)])
def test_14_14v(vb_on_vc, c):
    assert d.tee_rect_main_conical_branch(vb_on_vc, 0.5)[0].value == pytest.approx(c)


@pytest.mark.parametrize(
    "ab_on_as, ab_on_ac, qb_on_qc, branch, main",
    [
        (0.25, 0.25, 0.9, 6.0, 0.46),
        (0.5, 0.5, 0.4, 0.40, 0.0),
        (1.0, 0.5, 0.1, 0.44, 0.72),
        (1.0, 1.0, 0.5, 0.32, 0.06),
        (2.0, 1.0, 0.7, 0.15, 0.06),
    ],
)
def test_14_14w_printed_rows(ab_on_as, ab_on_ac, qb_on_qc, branch, main):
    got = d.wye_rect_radius(ab_on_as, ab_on_ac, qb_on_qc)
    assert (got[0].value, got[1].value) == pytest.approx((branch, main))
    assert got[0].exact and got[1].exact


def test_14_14w_other_proportions_are_flagged():
    assert d.wye_rect_radius(0.8, 0.7, 0.5)[0].clamped


@pytest.mark.parametrize("ab_on_ac, c", [(0.5, 0.30), (1.0, 0.25)])
def test_14_14x(ab_on_ac, c):
    assert d.wye_dovetail_rect(ab_on_ac).value == pytest.approx(c)


@pytest.mark.parametrize("theta, v, c", [(15, 0.8, 0.11), (45, 1.0, 0.24), (60, 1.2, 0.33), (90, 0.1, 1.0)])
def test_14_14y(theta, v, c):
    assert d.wye_symmetric(theta, v).value == pytest.approx(c)


@pytest.mark.parametrize(
    "qb, qs, branch, main", [(0.1, 0.9, 1.16, 0.35), (0.7, 0.3, 0.47, 0.20), (1.0, 1.0, 0.54, 0.53)]
)
def test_14_14z(qb, qs, branch, main):
    got = d.tee_rect_reducing(qb, qs)
    assert (got[0].value, got[1].value) == pytest.approx((branch, main))


def test_every_14_14_table_is_referenced_to_the_upstream_section():
    tables = [table for table_id, table in t.ALL_TABLES.items() if table_id.startswith("14-14")]
    assert len(tables) > 40
    assert all(table.reference == t.REF_UPSTREAM for table in tables)
