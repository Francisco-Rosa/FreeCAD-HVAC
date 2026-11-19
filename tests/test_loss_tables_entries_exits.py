# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the HVAC addon.

"""SMACNA Tables 14-15 (entries) and 14-16 (exits): spot values against the printed tables."""

import pytest

from freecad.HVAC.library.loss_tables import entries_exits as x
from freecad.HVAC.library.loss_tables import table as t


@pytest.mark.parametrize(
    "t_on_d, l_on_d, c", [(0, 0, 0.50), (0, 0.05, 0.80), (0.02, 0.2, 0.66), (0.05, 0.5, 0.50), (0, 1.0, 1.0)]
)
def test_14_15a_duct_in_wall(t_on_d, l_on_d, c):
    assert x.entry_duct_in_wall(t_on_d, l_on_d).value == pytest.approx(c)


def test_14_15a_thick_wall_and_long_projection_read_last_cells_without_flag():
    result = x.entry_duct_in_wall(0.2, 3.0)
    assert result.value == pytest.approx(0.50)
    assert result.exact


@pytest.mark.parametrize(
    "r_on_d, wall, c", [(0, False, 1.0), (0.05, False, 0.40), (0.5, False, 0.03), (0, True, 0.50), (0.10, True, 0.12)]
)
def test_14_15bc_bellmouth(r_on_d, wall, c):
    assert x.entry_bellmouth(r_on_d, wall).value == pytest.approx(c)


@pytest.mark.parametrize(
    "theta, l_on_d, wall, c",
    [
        (0, 0.025, False, 1.0),
        (30, 0.25, False, 0.30),
        (60, 1.0, False, 0.10),
        (180, 0.60, False, 0.50),
        (30, 0.10, True, 0.25),
        (60, 0.15, True, 0.15),
        (0, 0.60, True, 0.50),
    ],
)
def test_14_15de_conical(theta, l_on_d, wall, c):
    assert x.entry_conical(theta, l_on_d, wall).value == pytest.approx(c)


@pytest.mark.parametrize("theta, l_on_d, c", [(0, 0.1, 2.6), (0, 0.9, 1.1), (15, 0.2, 0.77), (15, 2.0, 0.25)])
def test_14_15f_intake_hood(theta, l_on_d, c):
    assert x.entry_intake_hood(theta, l_on_d).value == pytest.approx(c)


@pytest.mark.parametrize(
    "theta, rect, c", [(0, False, 1.0), (40, False, 0.06), (180, False, 0.50), (40, True, 0.13), (180, True, 0.62)]
)
def test_14_15g_tapered_hood(theta, rect, c):
    assert x.entry_hood_tapered(theta, rect).value == pytest.approx(c)


def test_14_15h_canopy_hood_constants():
    assert x.ENTRY_CANOPY_HOOD_C == 0.5
    assert x.ENTRY_CANOPY_HOOD_EXTRA_PA == 25.0


@pytest.mark.parametrize("theta, l_on_d, c", [(0, 0.1, 4.0), (0, 0.35, 1.4), (15, 0.25, 1.0), (15, 1.0, 0.60)])
def test_14_16a_exhaust_hood(theta, l_on_d, c):
    assert x.exit_exhaust_hood(theta, l_on_d).value == pytest.approx(c)


@pytest.mark.parametrize("theta, area, c", [(14, 2, 0.33), (30, 4, 0.54), (60, 10, 0.72), (120, 16, 1.0)])
def test_14_16b_conical_round(theta, area, c):
    assert x.exit_conical_round(theta, area).value == pytest.approx(c)


@pytest.mark.parametrize("theta, area, c", [(14, 2, 0.37), (45, 4, 0.82), (150, 6, 1.1)])
def test_14_16c_plane_diffuser(theta, area, c):
    assert x.exit_plane_diffuser_rect(theta, area).value == pytest.approx(c)


@pytest.mark.parametrize("theta, area, c", [(10, 2, 0.44), (30, 6, 0.74), (90, 10, 1.0)])
def test_14_16d_pyramidal_diffuser(theta, area, c):
    assert x.exit_pyramidal_diffuser_rect(theta, area).value == pytest.approx(c)


@pytest.mark.parametrize("r_on_w, l_on_w, c", [(0, 1.0, 3.2), (0.75, 2.0, 1.7), (1.5, 0, 1.5), (2.5, 12.0, 1.0)])
def test_14_16e_from_elbow_rect(r_on_w, l_on_w, c):
    assert x.exit_from_elbow_rect(r_on_w, l_on_w).value == pytest.approx(c)


def test_14_16e_from_elbow_round_is_only_printed_for_one_radius():
    assert x.exit_from_elbow_round(0.9).value == pytest.approx(1.5)
    assert x.exit_from_elbow_round(1.3).exact
    assert x.exit_from_elbow_round(1.3, r_on_d=1.5).clamped


@pytest.mark.parametrize(
    "h_on_w, theta, v, c",
    [
        (0.15, 60, 1.0, 1.2),
        (0.15, 150, 0.5, 0.75),
        (1.0, 40, 1.5, 1.3),
        (1.0, 150, 2.0, 1.3),
        (7.0, 120, 2.0, 0.98),
        (7.0, 45, 0.5, 0.92),
    ],
)
def test_14_16f_crossflow_rect_bands(h_on_w, theta, v, c):
    result = x.exit_crossflow_rect(h_on_w, theta, v)
    assert result.value == pytest.approx(c)
    assert result.exact


def test_14_16f_aspect_ratio_between_bands_is_flagged():
    assert x.exit_crossflow_rect(3.0, 60, 1.0).clamped


def test_14_16f_round_matches_the_middle_rectangular_band():
    assert x.exit_crossflow_round(90, 1.0).value == pytest.approx(0.95)


@pytest.mark.parametrize(
    "pyramidal, theta, area, c",
    [(False, 10, 1.5, 0.51), (False, 35, 4.0, 0.50), (True, 20, 2.5, 0.65), (True, 30, 1.5, 0.85)],
)
def test_14_16gh_fan_diffusers(pyramidal, theta, area, c):
    assert x.exit_fan_diffuser(pyramidal, theta, area).value == pytest.approx(c)


def test_14_16ij_constants():
    assert x.exit_fan_into_plenum("forward_curved").value == 1.8
    assert x.EXIT_ABRUPT_C == 1.0
    with pytest.raises(ValueError):
        x.exit_fan_into_plenum("propeller")


def test_screen_is_added_at_the_opening_velocity():
    base = t.Lookup(0.5)
    screen = t.Lookup(1.7, clamped=True)
    # Opening twice the duct area: the screen sees half the velocity, a quarter of the velocity pressure.
    result = x.with_screen(base, screen, opening_area_ratio=2.0)
    assert result.value == pytest.approx(0.5 + 1.7 / 4.0)
    assert result.clamped
    assert x.with_screen(base, t.Lookup(1.7)).value == pytest.approx(2.2)
    with pytest.raises(ValueError):
        x.with_screen(base, screen, 0.0)


def test_entries_use_downstream_and_exits_upstream_velocity_pressure():
    entries = [table for table_id, table in t.ALL_TABLES.items() if table_id.startswith("14-15")]
    exits = [table for table_id, table in t.ALL_TABLES.items() if table_id.startswith("14-16")]
    assert entries and all(table.reference == t.REF_DOWNSTREAM for table in entries)
    assert exits and all(table.reference == t.REF_UPSTREAM for table in exits)
