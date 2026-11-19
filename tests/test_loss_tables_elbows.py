# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the HVAC addon.

"""SMACNA Table 14-10 (elbows): spot values against the printed tables."""

import pytest

from freecad.HVAC.library.loss_tables import elbows as e


@pytest.mark.parametrize("r_on_d, c", [(0.5, 0.71), (1.0, 0.22), (2.5, 0.12), (1.25, 0.185)])
def test_14_10a_smooth_round(r_on_d, c):
    assert e.smooth_round(r_on_d).value == pytest.approx(c)


def test_14_10a_angle_factor_applies():
    assert e.smooth_round(1.0, theta_deg=45.0).value == pytest.approx(0.22 * 0.60)


def test_14_10a_outside_range_is_flagged():
    assert e.smooth_round(4.0).clamped
    assert e.smooth_round(1.0).exact


@pytest.mark.parametrize("pieces, r_on_d, c", [(5, 0.75, 0.46), (4, 1.5, 0.27), (3, 0.5, 0.98), (3, 2.0, 0.33)])
def test_14_10b_gored_round(pieces, r_on_d, c):
    result = e.gored_round(pieces, r_on_d)
    assert result.value == pytest.approx(c)
    assert result.exact


def test_14_10b_blank_cell_is_flagged():
    # 4 and 5 piece elbows have no printed value at R/D = 0.5.
    result = e.gored_round(5, 0.5)
    assert result.value == pytest.approx(0.46)
    assert result.filled


def test_14_10b_other_angle_is_an_approximation():
    result = e.gored_round(5, 1.0, theta_deg=45.0)
    assert result.value == pytest.approx(0.33 * 0.60)
    assert result.clamped


@pytest.mark.parametrize("theta, c", [(20, 0.08), (45, 0.34), (90, 1.2)])
def test_14_10c_mitered_round(theta, c):
    assert e.mitered_round(theta).value == pytest.approx(c)


def test_14_10c_reynolds_correction():
    assert e.mitered_round(90, reynolds=1e4).value == pytest.approx(1.2 * 1.40)
    assert e.mitered_round(90, reynolds=14e4).value == pytest.approx(1.2)
    high = e.mitered_round(90, reynolds=5e5)
    assert high.value == pytest.approx(1.2)
    assert high.exact


@pytest.mark.parametrize("h_on_w, theta, c", [(0.25, 20, 0.08), (3.0, 45, 0.28), (5.0, 90, 0.89), (8.0, 75, 0.57)])
def test_14_10d_mitered_rect(h_on_w, theta, c):
    assert e.mitered_rect(h_on_w, theta).value == pytest.approx(c)


@pytest.mark.parametrize("h_on_w, w1_on_w, c", [(0.25, 0.6, 1.8), (1.0, 1.4, 0.95), (4.0, 2.0, 0.66)])
def test_14_10e_mitered_rect_size_change(h_on_w, w1_on_w, c):
    assert e.mitered_rect_size_change(h_on_w, w1_on_w).value == pytest.approx(c)


def test_14_10e_tall_ducts_read_the_last_finite_row():
    # Between H/W = 4 and the printed "infinity" row a real ratio stays at the 4.0 row.
    assert e.mitered_rect_size_change(10.0, 2.0).value == pytest.approx(0.66, abs=1e-6)


@pytest.mark.parametrize("h_on_w, r_on_w, c", [(0.25, 0.5, 1.5), (1.0, 1.0, 0.21), (6.0, 1.0, 0.27), (8.0, 2.0, 0.15)])
def test_14_10f_smooth_rect_at_high_reynolds(h_on_w, r_on_w, c):
    assert e.smooth_rect(h_on_w, r_on_w, reynolds=1e6).value == pytest.approx(c)


def test_14_10f_reynolds_correction_rows():
    assert e.reynolds_factor_smooth_rect(0.5, 1e4).value == pytest.approx(1.40)
    assert e.reynolds_factor_smooth_rect(1.5, 1e4).value == pytest.approx(2.0)
    assert e.reynolds_factor_smooth_rect(1.5, 17e4).value == pytest.approx(1.075)
    assert e.reynolds_factor_smooth_rect(1.5, 9e5).value == pytest.approx(1.0)
    assert e.reynolds_factor_smooth_rect(1.5, 9e5).exact


@pytest.mark.parametrize(
    "vanes, r_on_w, h_on_w, c",
    [
        (1, 0.05, 0.25, 0.52),
        (1, 0.50, 8.0, 0.05),
        (2, 0.20, 1.5, 0.05),
        (2, 0.05, 7.0, 0.48),
        (3, 0.10, 8.0, 0.09),
        (3, 0.30, 0.25, 0.03),
    ],
)
def test_14_10g_splitter_vanes(vanes, r_on_w, h_on_w, c):
    assert e.smooth_rect_splitter_vanes(vanes, r_on_w, h_on_w).value == pytest.approx(c)


@pytest.mark.parametrize(
    "design, velocity, c",
    [
        ("single_r50_s38", 5.0, 0.24),
        ("single_r114_s83", 12.5, 0.22),
        ("double_r50_s56", 7.5, 0.52),
        ("double_r114_s83", 10.0, 0.24),
    ],
)
def test_14_10h_turning_vanes(design, velocity, c):
    assert e.mitered_rect_turning_vanes(design, velocity).value == pytest.approx(c)


def test_14_10h_unknown_design_lists_known_ones():
    with pytest.raises(ValueError) as excinfo:
        e.mitered_rect_turning_vanes("triple", 5.0)
    assert "single_r50_s38" in str(excinfo.value)


@pytest.mark.parametrize("l_on_h, c", [(0, 0.0), (1.0, 2.6), (2.0, 4.2), (2.4, 3.7), (10.0, 2.5)])
def test_14_10i_z_shaped(l_on_h, c):
    assert e.z_shaped_rect(l_on_h).value == pytest.approx(c)


def test_14_10i_aspect_and_reynolds_factors_multiply():
    assert e.z_shaped_rect(1.0, w_on_h=4.0, reynolds=2e4).value == pytest.approx(2.6 * 0.78 * 1.26)


@pytest.mark.parametrize("l_on_w, c", [(0, 1.2), (1.0, 3.4), (2.0, 3.1), (2.4, 3.2), (9.0, 2.5)])
def test_14_10j_different_planes(l_on_w, c):
    assert e.different_planes_rect(l_on_w).value == pytest.approx(c)


@pytest.mark.parametrize("l_on_d, c", [(0, 0.0), (0.5, 0.15), (1.5, 0.16), (3.0, 0.16)])
def test_14_10k_offset_30_round(l_on_d, c):
    assert e.offset_30_round(l_on_d).value == pytest.approx(c)
