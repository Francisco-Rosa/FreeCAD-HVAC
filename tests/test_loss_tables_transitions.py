# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the HVAC addon.

"""SMACNA Tables 14-11 and 14-12 (transitions): spot values against the printed tables."""

import pytest

from freecad.HVAC.library.loss_tables import transitions as tr


@pytest.mark.parametrize(
    "re, area, theta, c",
    [
        (0.5e5, 2, 16, 0.14),
        (0.5e5, 16, 180, 0.88),
        (2e5, 6, 45, 0.90),
        (2e5, 10, 20, 0.24),
        (6e5, 4, 30, 0.38),
        (6e5, 16, 180, 0.89),
    ],
)
def test_14_11a_round_conical(re, area, theta, c):
    assert tr.expansion_round(theta, area, re).value == pytest.approx(c)


def test_14_11a_high_reynolds_and_large_ratio_read_last_block_without_flag():
    result = tr.expansion_round(60, 30, 2e6)
    assert result.value == pytest.approx(0.79)
    assert result.exact


def test_14_11a_low_reynolds_is_flagged():
    assert tr.expansion_round(60, 4, 1e4).clamped


@pytest.mark.parametrize("area, theta, c", [(2, 16, 0.18), (4, 45, 0.56), (6, 120, 0.76), (10, 180, 0.86)])
def test_14_11b_rect_pyramidal(area, theta, c):
    assert tr.expansion_rect_pyramidal(theta, area).value == pytest.approx(c)


def test_14_11cd_equivalent_angle():
    # tan(theta/2) = (1.13 * sqrt(H W) - D) / (2 L)
    theta = tr.round_rect_equivalent_angle(diameter=200.0, width=400.0, height=400.0, length=300.0)
    assert theta == pytest.approx(45.57, abs=0.01)
    # The same transition seen from the other end gives the same angle.
    assert tr.round_rect_equivalent_angle(452.0, 100.0, 100.0, 300.0) == pytest.approx(58.94, abs=0.01)
    assert tr.round_rect_equivalent_angle(200.0, 400.0, 400.0, 0.0) == 180.0


@pytest.mark.parametrize("area, theta, c", [(2, 14, 0.09), (4, 45, 0.60), (6, 180, 0.80)])
def test_14_11e_sides_straight(area, theta, c):
    assert tr.expansion_rect_sides_straight(theta, area).value == pytest.approx(c)


@pytest.mark.parametrize(
    "kind, theta, area, c",
    [
        ("symmetric_sides_straight", 10, 1.5, 0.05),
        ("symmetric_sides_straight", 35, 4.0, 0.50),
        ("asymmetric_top_level", 25, 3.0, 0.23),
        ("asymmetric_top_10_down", 20, 2.5, 0.24),
        ("asymmetric_top_10_down", 35, 3.5, 0.66),
        ("asymmetric_top_10_up", 30, 2.0, 0.18),
        ("pyramidal", 15, 1.5, 0.23),
        ("pyramidal", 30, 4.0, 0.69),
    ],
)
def test_14_11f_to_j_fan_transitions(kind, theta, area, c):
    assert tr.expansion_at_fan(kind, theta, area).value == pytest.approx(c)


def test_14_11_unknown_fan_transition_lists_known_ones():
    with pytest.raises(ValueError) as excinfo:
        tr.expansion_at_fan("sideways", 10, 2)
    assert "pyramidal" in str(excinfo.value)


@pytest.mark.parametrize(
    "area, theta, c", [(2, 10, 0.05), (4, 15, 0.04), (4, 30, 0.04), (4, 40, 0.04), (6, 55, 0.07), (10, 180, 0.43)]
)
def test_14_12a_contraction(area, theta, c):
    assert tr.contraction(theta, area).value == pytest.approx(c)


def test_14_12b_conical_contraction_is_k_times_co():
    assert tr.conical_contraction(theta_deg=30, l_on_d=0.10, a_on_a1=0.4).value == pytest.approx(0.68 * 0.25)
    assert tr.conical_contraction(theta_deg=180, l_on_d=0.60, a_on_a1=0.0).value == pytest.approx(0.50)
    assert tr.conical_contraction(theta_deg=60, l_on_d=0.15, a_on_a1=1.0).value == pytest.approx(0.0)


@pytest.mark.parametrize("re, c", [(1e4, 0.27), (6e4, 0.17), (20e4, 0.04), (40e4, 0.0), (9e5, 0.0)])
def test_14_12c_slot_to_round(re, c):
    assert tr.slot_to_round(re).value == pytest.approx(c)
