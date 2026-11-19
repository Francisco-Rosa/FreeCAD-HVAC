# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the HVAC addon.

"""SMACNA Table 14-13 (converging junctions): spot values against the printed tables."""

import pytest

from freecad.HVAC.library.loss_tables import junctions_converging as j
from freecad.HVAC.library.loss_tables import table as t


def _values(pair):
    return tuple(lookup.value for lookup in pair)


@pytest.mark.parametrize(
    "ab_on_ac, vb_on_vc, vs_on_vc, branch, main",
    [
        (0.1, 0.4, 0.1, -0.56, -8.6),
        (0.4, 0.8, 0.5, 0.12, -0.28),
        (1.0, 3.0, 1.0, 8.0, 0.05),
        (0.6, 1.5, 0.7, 1.7, 0.12),
    ],
)
def test_14_13a_wye_45_round(ab_on_ac, vb_on_vc, vs_on_vc, branch, main):
    assert _values(j.wye_45_round(ab_on_ac, vb_on_vc, vs_on_vc)) == pytest.approx((branch, main))


@pytest.mark.parametrize(
    "ab_on_ac, qb_on_qc, branch, main",
    [(0.1, 0.1, 0.40, 0.16), (0.4, 0.4, 0.94, 0.46), (0.1, 1.0, 101, 0.55), (1.0, 0.3, -0.08, 0.38)],
)
def test_14_13b_tee_90_round(ab_on_ac, qb_on_qc, branch, main):
    assert _values(j.tee_90_round(ab_on_ac, qb_on_qc)) == pytest.approx((branch, main))


@pytest.mark.parametrize(
    "kind, qb_on_qc, vc, branch",
    [
        ("round_branch", 0.1, 4.0, -0.63),
        ("round_branch", 1.0, 8.0, 5.95),
        ("rect_branch", 0.6, 4.0, 1.10),
        ("rect_branch", 0.6, 8.0, 1.66),
        ("rect_branch_45_entry", 0.4, 4.0, 0.28),
        ("rect_branch_45_entry", 1.0, 8.0, 3.63),
    ],
)
def test_14_13cdf_tees_into_rectangular_main(kind, qb_on_qc, vc, branch):
    got_branch, got_main = j.tee_rect_main(kind, qb_on_qc, vc)
    assert got_branch.value == pytest.approx(branch)
    # The main coefficient is the one printed under 14-13 B.
    assert got_main.value == pytest.approx(j.TEE_90_MAIN(qb_on_qc))


def test_14_13_unknown_rect_tee_lists_known_ones():
    with pytest.raises(ValueError) as excinfo:
        j.tee_rect_main("oval_branch", 0.5, 5.0)
    assert "rect_branch" in str(excinfo.value)


@pytest.mark.parametrize(
    "as_on_ac, ab_on_ac, qb_on_qs, branch, main",
    [
        (0.3, 0.2, 0.2, -2.4, 5.3),
        (0.4, 0.4, 1.0, 1.1, 0.39),
        (0.5, 0.3, 1.0, 2.7, -0.27),
        (0.6, 0.6, 2.0, 0.82, -0.25),
        (0.8, 0.7, 0.8, 0.18, 0.10),
        (1.0, 1.0, 2.0, 0.29, -0.03),
        (1.0, 0.8, 0.4, -0.10, 0.06),
    ],
)
def test_14_13e_wye_conical_round(as_on_ac, ab_on_ac, qb_on_qs, branch, main):
    result = j.wye_conical_round(as_on_ac, ab_on_ac, qb_on_qs)
    assert _values(result) == pytest.approx((branch, main))
    assert all(lookup.exact for lookup in result)


def test_14_13e_interpolates_between_area_blocks():
    # Halfway between the As/Ac = 0.4 and 0.5 blocks, at Ab/Ac = 0.3, Qb/Qs = 1.0.
    branch, _ = j.wye_conical_round(0.45, 0.3, 1.0)
    assert branch.value == pytest.approx((2.4 + 2.7) / 2.0)
    assert branch.exact


def test_14_13e_blank_cells_and_unprinted_rows_are_flagged():
    assert j.wye_conical_round(1.0, 0.5, 0.2)[0].filled
    # The As/Ac = 0.3 block only prints Ab/Ac = 0.2 and 0.3.
    assert j.wye_conical_round(0.3, 0.6, 1.0)[0].clamped


def test_14_13e_suspected_misprint_is_kept_as_printed():
    assert j.wye_conical_round(0.5, 0.2, 1.4)[1].value == pytest.approx(1.3)


@pytest.mark.parametrize("ab_on_ac, c", [(0.5, 0.23), (1.0, 0.07), (0.75, 0.15)])
def test_14_13g_dovetail(ab_on_ac, c):
    assert j.wye_dovetail_rect(ab_on_ac).value == pytest.approx(c)


@pytest.mark.parametrize(
    "ab_on_as, as_on_ac, ab_on_ac, qb_on_qc, branch, main",
    [
        (0.25, 0.75, 0.25, 0.1, -0.50, 0.30),
        (0.5, 1.0, 0.5, 0.4, 0.25, 0.0),
        (1.0, 0.5, 0.5, 0.9, 1.9, -1.3),
        (2.0, 0.5, 1.0, 0.5, -0.20, 0.55),
        (1.33, 0.75, 1.0, 0.1, -1.2, 0.75),
    ],
)
def test_14_13h_wye_rect_printed_rows(ab_on_as, as_on_ac, ab_on_ac, qb_on_qc, branch, main):
    result = j.wye_rect(ab_on_as, as_on_ac, ab_on_ac, qb_on_qc)
    assert _values(result) == pytest.approx((branch, main))
    assert all(lookup.exact for lookup in result)


def test_14_13h_other_proportions_use_nearest_row_and_are_flagged():
    branch, main = j.wye_rect(0.8, 0.9, 0.5, 0.4)
    assert branch.clamped and main.clamped
    # Nearest printed branch row to (0.8, 0.5) is (0.67, 0.5); nearest main row to (0.9, 0.5) is (1.0, 0.5).
    assert branch.value == pytest.approx(0.10)
    assert main.value == pytest.approx(0.0)


@pytest.mark.parametrize("theta, q, c", [(15, 0.0, -2.6), (30, 0.5, 0.28), (45, 1.0, 2.3), (45, 0.7, 1.26)])
def test_14_13i_symmetric_wye(theta, q, c):
    assert j.wye_symmetric(theta, q).value == pytest.approx(c)


def test_every_14_13_table_is_referenced_to_the_downstream_section():
    tables = [table for table_id, table in t.ALL_TABLES.items() if table_id.startswith("14-13")]
    assert len(tables) > 30
    assert all(table.reference == t.REF_DOWNSTREAM for table in tables)
