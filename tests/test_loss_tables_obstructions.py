# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the HVAC addon.

"""SMACNA Tables 14-9, 14-17 and 14-18: spot values against the printed tables."""

import pytest

from freecad.HVAC.library.loss_tables import obstructions as o
from freecad.HVAC.library.loss_tables import straight_through as st


@pytest.mark.parametrize("n, c", [(0.30, 6.2), (0.55, 1.3), (0.90, 0.14), (1.0, 0.0)])
def test_14_17a_screen(n, c):
    assert o.screen(n).value == pytest.approx(c)


@pytest.mark.parametrize("n, t_on_d, c", [(0.20, 0.015, 52), (0.50, 0.2, 3.8), (0.80, 0.4, 0.39), (0.30, 0.6, 15)])
def test_14_17b_perforated_plate(n, t_on_d, c):
    assert o.perforated_plate(n, t_on_d).value == pytest.approx(c)


@pytest.mark.parametrize(
    "kind, theta, c",
    [
        ("thin_plate_round", 0, 0.20),
        ("thin_plate_round", 60, 108),
        ("thin_plate_rect", 30, 3.3),
        ("airfoil_rect", 0, 0.50),
        ("airfoil_rect", 50, 24),
    ],
)
def test_14_18abg_butterfly(kind, theta, c):
    assert o.butterfly_damper(kind, theta).value == pytest.approx(c)


def test_14_18_unknown_damper_lists_known_ones():
    with pytest.raises(ValueError) as excinfo:
        o.butterfly_damper("iris", 10)
    assert "airfoil_rect" in str(excinfo.value)


@pytest.mark.parametrize("h_on_d, c", [(0.2, 35), (0.5, 2.1), (0.9, 0.06)])
def test_14_18c_gate_round(h_on_d, c):
    assert o.gate_damper_round(h_on_d).value == pytest.approx(c)


@pytest.mark.parametrize("h_on_w, opening, c", [(0.5, 0.3, 14), (1.0, 0.6, 2.4), (1.5, 0.8, 0.47), (2.0, 0.9, 0.13)])
def test_14_18d_gate_rect(h_on_w, opening, c):
    assert o.gate_damper_rect(h_on_w, opening).value == pytest.approx(c)


def test_14_18ef_blade_ratio():
    # 4 blades, each 600 long, in a 600 wide x 400 high duct: 4 * 600 / (2 * 1000) = 1.2
    assert o.blade_l_on_r(4, 600.0, 600.0, 400.0) == pytest.approx(1.2)


@pytest.mark.parametrize(
    "opposed, l_on_r, theta, c",
    [
        (False, 0.3, 80, 116),
        (False, 0.6, 40, 5.4),
        (False, 1.5, 0, 0.52),
        (True, 0.3, 80, 807),
        (True, 1.0, 50, 65),
        (True, 1.5, 10, 1.4),
    ],
)
def test_14_18ef_multi_blade(opposed, l_on_r, theta, c):
    assert o.multi_blade_damper(opposed, l_on_r, theta).value == pytest.approx(c)


@pytest.mark.parametrize(
    "re, sm_on_a, co",
    [(0.1, 0.05, 3.9), (1.0, 0.20, 3.2), (100, 0.10, 0.24), (1e4, 0.15, 0.24), (3e5, 0.20, 0.35), (8e5, 0.10, 0.05)],
)
def test_14_18h_cylinder_base_coefficient(re, sm_on_a, co):
    result = o.cylinder(re, sm_on_a)
    assert result.value == pytest.approx(co)
    assert result.exact


def test_14_18h_offset_factor_and_limits():
    assert o.cylinder(1e4, 0.10, y_on_d=0.20).value == pytest.approx(0.15 * 0.84)
    assert o.cylinder(1e4, 0.10, y_on_d=-0.20).value == pytest.approx(0.15 * 0.84)
    # Beyond Sm/A = 0.20 the table has no data.
    assert o.cylinder(1e4, 0.28).clamped
    with pytest.raises(ValueError):
        o.cylinder(0.0, 0.1)


def test_14_18i_single_point():
    assert o.depressed_round(0.33).value == 0.24
    assert o.depressed_round(0.33).exact
    assert o.depressed_round(0.6).clamped


@pytest.mark.parametrize("w_on_h, l_on_h, c", [(1.0, 0.125, 0.26), (4.0, 0.25, 0.22), (2.5, 0.30, 0.325)])
def test_14_18j_depressed_rect(w_on_h, l_on_h, c):
    assert o.depressed_rect(w_on_h, l_on_h).value == pytest.approx(c)


@pytest.mark.parametrize("v, c", [(4, 0.18), (8, 0.24), (12, 0.26)])
def test_14_18k_four_radius_ells(v, c):
    assert o.four_radius_ells_rect(v).value == pytest.approx(c)


@pytest.mark.parametrize(
    "vanes, l_on_h, v, c",
    [
        ("single_blade_vanes", 1.0, None, 0.86),
        ("double_blade_vanes", 2.0, None, 2.91),
        ("s_splitter_vanes", 0.5, None, 0.61),
        ("no_vanes", 1.5, 5.0, 6.92),
        ("no_vanes", 1.5, 9.0, 8.82),
    ],
)
def test_14_18l_four_mitered_ells(vanes, l_on_h, v, c):
    assert o.four_mitered_ells_rect(vanes, l_on_h, v).value == pytest.approx(c)


def test_14_18l_blank_cells_and_bad_input():
    assert o.four_mitered_ells_rect("single_blade_vanes", 0.5).filled
    assert o.four_mitered_ells_rect("s_splitter_vanes", 2.0).filled
    with pytest.raises(ValueError):
        o.four_mitered_ells_rect("no_vanes", 1.0)
    with pytest.raises(ValueError):
        o.four_mitered_ells_rect("zigzag_vanes", 1.0)


@pytest.mark.parametrize(
    "vs_on_vc, regain, c", [(0.95, 75, 0.03), (0.50, 75, 0.19), (0.77, 90, 0.04), (0.50, 90, 0.08), (0.65, 82.5, 0.105)]
)
def test_14_9_straight_through(vs_on_vc, regain, c):
    assert st.straight_through(vs_on_vc, regain).value == pytest.approx(c)


@pytest.mark.parametrize(
    "a, b, de", [(100, 100, 109), (200, 100, 152), (600, 400, 533), (1000, 1000, 1093), (2900, 2900, 3170)]
)
def test_circular_equivalent_matches_table_14_3(a, b, de):
    assert st.circular_equivalent_of_rectangular(a, b) == pytest.approx(de, abs=0.6)
    assert st.circular_equivalent_of_rectangular(b, a) == pytest.approx(de, abs=0.6)
