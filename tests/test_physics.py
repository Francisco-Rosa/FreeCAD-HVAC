import math

import pytest

from freecad.HVAC.analysis import physics as airflow

# ----------------------------------------------------------------------------
# Unit conversion
# ----------------------------------------------------------------------------


def test_mm_to_m():
    assert airflow.mm_to_m(1000.0) == pytest.approx(1.0)


def test_lps_to_m3s_roundtrip():
    assert airflow.lps_to_m3s(1000.0) == pytest.approx(1.0)
    assert airflow.m3s_to_lps(airflow.lps_to_m3s(250.0)) == pytest.approx(250.0)


# ----------------------------------------------------------------------------
# Area
# ----------------------------------------------------------------------------


def test_circular_area():
    # d=1m -> A = pi/4
    assert airflow.circular_area(1.0) == pytest.approx(math.pi / 4.0)


def test_rectangular_area():
    assert airflow.rectangular_area(0.4, 0.2) == pytest.approx(0.08)


def test_oval_area_degenerates_to_circle_when_square():
    # width == height -> pure circle of that diameter
    got = airflow.oval_area(0.3, 0.3)
    expected = airflow.circular_area(0.3)
    assert got == pytest.approx(expected)


def test_oval_area_rectangle_plus_circle():
    # width=0.5, height=0.2 -> straight rectangle (0.3 x 0.2) + full circle r=0.1
    got = airflow.oval_area(0.5, 0.2)
    expected = 0.3 * 0.2 + math.pi * (0.1**2)
    assert got == pytest.approx(expected)


def test_oval_area_rejects_non_positive_extent():
    with pytest.raises(ValueError):
        airflow.oval_area(0.2, 0.0)


# ----------------------------------------------------------------------------
# Hydraulic diameter
# ----------------------------------------------------------------------------


def test_hydraulic_diameter_circular_equals_diameter():
    assert airflow.hydraulic_diameter_circular(0.25) == pytest.approx(0.25)


def test_hydraulic_diameter_rectangular_square_duct_equals_side():
    # For a square duct, Dh == side length
    assert airflow.hydraulic_diameter_rectangular(0.3, 0.3) == pytest.approx(0.3)


def test_hydraulic_diameter_rectangular_known_value():
    # w=0.4, h=0.2 -> Dh = 2*0.4*0.2/(0.4+0.2) = 0.16/0.6
    assert airflow.hydraulic_diameter_rectangular(0.4, 0.2) == pytest.approx(0.16 / 0.6)


def test_hydraulic_diameter_oval_degenerates_to_circle_when_square():
    got = airflow.hydraulic_diameter_oval(0.3, 0.3)
    expected = airflow.hydraulic_diameter_circular(0.3)
    assert got == pytest.approx(expected)


# ----------------------------------------------------------------------------
# Velocity / Reynolds number
# ----------------------------------------------------------------------------


def test_velocity_from_flow():
    # 1 m3/s through 1 m2 -> 1 m/s
    assert airflow.velocity_from_flow(1.0, 1.0) == pytest.approx(1.0)
    assert airflow.velocity_from_flow(2.0, 0.5) == pytest.approx(4.0)


def test_reynolds_number_known_value():
    # Re = V*Dh/nu
    re = airflow.reynolds_number(velocity_m_s=10.0, hydraulic_diameter_m=0.2, kinematic_viscosity_m2_s=1.51e-5)
    assert re == pytest.approx(10.0 * 0.2 / 1.51e-5)


def test_reynolds_number_uses_absolute_velocity():
    re = airflow.reynolds_number(velocity_m_s=-10.0, hydraulic_diameter_m=0.2, kinematic_viscosity_m2_s=1.51e-5)
    assert re > 0.0


# ----------------------------------------------------------------------------
# Friction factor
# ----------------------------------------------------------------------------


def test_friction_factor_altshul_tsal_typical_duct_case():
    # Typical HVAC duct: Re ~ 1.3e5, smooth-ish galvanized steel relative roughness ~ 0.0005
    f = airflow.friction_factor_altshul_tsal(reynolds=1.3e5, relative_roughness=0.0005)
    # Should land in the normal Moody-chart range for this Re/roughness combination
    assert 0.017 < f < 0.03


def test_friction_factor_altshul_tsal_low_f_branch_applies_correction():
    # Very smooth duct, very high Re -> raw formula would go below 0.018,
    # triggering the low-f correction branch (f = 0.85*f + 0.0028)
    raw = 0.11 * (0.0 + 68.0 / 1e7) ** 0.25
    assert raw < 0.018
    f = airflow.friction_factor_altshul_tsal(reynolds=1e7, relative_roughness=0.0)
    assert f == pytest.approx(0.85 * raw + 0.0028)


def test_friction_factor_altshul_tsal_increases_with_roughness():
    f_smooth = airflow.friction_factor_altshul_tsal(reynolds=1e5, relative_roughness=0.0001)
    f_rough = airflow.friction_factor_altshul_tsal(reynolds=1e5, relative_roughness=0.01)
    assert f_rough > f_smooth


def test_friction_factor_rejects_nonpositive_reynolds():
    with pytest.raises(ValueError):
        airflow.friction_factor_altshul_tsal(reynolds=0.0, relative_roughness=0.001)


# ----------------------------------------------------------------------------
# Pressure loss
# ----------------------------------------------------------------------------


def test_velocity_pressure_known_value():
    # rho=1.204, V=10 -> Pv = 1.204*100/2 = 60.2
    assert airflow.velocity_pressure(1.204, 10.0) == pytest.approx(60.2)


def test_darcy_weisbach_pressure_loss_known_value():
    # f=0.02, L=10m, Dh=0.2m, rho=1.2, V=5m/s
    # dP = f*(L/Dh)*(rho*V^2/2) = 0.02*(10/0.2)*(1.2*25/2) = 0.02*50*15 = 15
    dp = airflow.darcy_weisbach_pressure_loss(
        friction_factor=0.02, length_m=10.0, hydraulic_diameter_m=0.2, air_density_kg_m3=1.2, velocity_m_s=5.0
    )
    assert dp == pytest.approx(15.0)


def test_darcy_weisbach_pressure_loss_zero_length_is_zero():
    dp = airflow.darcy_weisbach_pressure_loss(
        friction_factor=0.02, length_m=0.0, hydraulic_diameter_m=0.2, air_density_kg_m3=1.2, velocity_m_s=5.0
    )
    assert dp == pytest.approx(0.0)


# ----------------------------------------------------------------------------
# Duct sizing: constant velocity
# ----------------------------------------------------------------------------


def test_circular_diameter_for_velocity_round_trip():
    flow, v = 0.5, 6.0
    d = airflow.circular_diameter_for_velocity(flow, v)
    got_v = airflow.velocity_from_flow(flow, airflow.circular_area(d))
    assert got_v == pytest.approx(v)


def test_circular_diameter_for_velocity_rejects_nonpositive_velocity():
    with pytest.raises(ValueError):
        airflow.circular_diameter_for_velocity(0.5, 0.0)


@pytest.mark.parametrize(
    "mode,kwargs",
    [
        ("aspect_ratio", {"aspect_ratio": 2.0}),
        ("fixed_height", {"fixed_dim_m": 0.3}),
        ("fixed_width", {"fixed_dim_m": 0.5}),
    ],
)
def test_rect_dims_for_velocity_round_trip(mode, kwargs):
    flow, v = 0.5, 6.0
    w, h = airflow.rect_dims_for_velocity(flow, v, mode, **kwargs)
    got_v = airflow.velocity_from_flow(flow, airflow.rectangular_area(w, h))
    assert got_v == pytest.approx(v)


def test_rect_dims_for_velocity_aspect_ratio_is_honored():
    w, h = airflow.rect_dims_for_velocity(0.5, 6.0, "aspect_ratio", aspect_ratio=2.5)
    assert w / h == pytest.approx(2.5)


def test_rect_dims_for_velocity_fixed_height_keeps_height():
    w, h = airflow.rect_dims_for_velocity(0.5, 6.0, "fixed_height", fixed_dim_m=0.3)
    assert h == pytest.approx(0.3)


def test_rect_dims_for_velocity_fixed_width_keeps_width():
    w, h = airflow.rect_dims_for_velocity(0.5, 6.0, "fixed_width", fixed_dim_m=0.5)
    assert w == pytest.approx(0.5)


def test_rect_dims_for_velocity_unknown_mode_raises():
    with pytest.raises(ValueError):
        airflow.rect_dims_for_velocity(0.5, 6.0, "bogus")


@pytest.mark.parametrize(
    "mode,kwargs",
    [
        ("aspect_ratio", {"aspect_ratio": 2.0}),
        ("fixed_height", {"fixed_dim_m": 0.25}),
        ("fixed_width", {"fixed_dim_m": 0.6}),
    ],
)
def test_oval_dims_for_velocity_round_trip(mode, kwargs):
    flow, v = 0.4, 6.0
    w, h = airflow.oval_dims_for_velocity(flow, v, mode, **kwargs)
    assert w >= h > 0.0
    got_v = airflow.velocity_from_flow(flow, airflow.oval_area(w, h))
    assert got_v == pytest.approx(v)


def test_oval_dims_for_velocity_aspect_ratio_is_honored():
    w, h = airflow.oval_dims_for_velocity(0.4, 6.0, "aspect_ratio", aspect_ratio=1.8)
    assert w / h == pytest.approx(1.8)


def test_oval_dims_for_velocity_aspect_ratio_one_matches_circle():
    # At aspect_ratio=1 an oval degenerates to a circle.
    flow, v = 0.4, 6.0
    w, h = airflow.oval_dims_for_velocity(flow, v, "aspect_ratio", aspect_ratio=1.0)
    d = airflow.circular_diameter_for_velocity(flow, v)
    assert w == pytest.approx(d)
    assert h == pytest.approx(d)


def test_oval_dims_for_velocity_aspect_ratio_below_one_gives_tall_oval():
    # aspect_ratio = width / height, so 0.5 is the 2.0 oval turned 90 degrees.
    w, h = airflow.oval_dims_for_velocity(0.4, 6.0, "aspect_ratio", aspect_ratio=0.5)
    wide_w, wide_h = airflow.oval_dims_for_velocity(0.4, 6.0, "aspect_ratio", aspect_ratio=2.0)
    assert (w, h) == pytest.approx((wide_h, wide_w))
    assert w / h == pytest.approx(0.5)


def test_oval_dims_for_velocity_non_positive_aspect_ratio_rejected():
    with pytest.raises(ValueError):
        airflow.oval_dims_for_velocity(0.4, 6.0, "aspect_ratio", aspect_ratio=0.0)


def test_oval_area_and_hydraulic_diameter_do_not_depend_on_orientation():
    assert airflow.oval_area(0.2, 0.5) == pytest.approx(airflow.oval_area(0.5, 0.2))
    assert airflow.hydraulic_diameter_oval(0.2, 0.5) == pytest.approx(airflow.hydraulic_diameter_oval(0.5, 0.2))


@pytest.mark.parametrize("mode, fixed", [("fixed_height", 0.6), ("fixed_width", 0.6)])
def test_oval_dims_for_velocity_fixed_dim_longer_than_free_dim(mode, fixed):
    # A small flow against a large fixed side: the free side ends up the
    # shorter one, and the result must still hit the target area exactly.
    flow, v = 0.4, 6.0
    w, h = airflow.oval_dims_for_velocity(flow, v, mode, fixed_dim_m=fixed)
    assert min(w, h) < fixed
    assert max(w, h) == pytest.approx(fixed)
    assert airflow.oval_area(w, h) == pytest.approx(flow / v)


def test_oval_dims_for_friction_rate_tall_fixed_height():
    # Fixed height larger than the solved width used to be clamped to width == height.
    args = (0.2, 1.0, 0.00009, 1.5e-5, 1.2)
    w, h = airflow.oval_dims_for_friction_rate(*args, "fixed_height", fixed_dim_m=0.6)
    assert h == pytest.approx(0.6)
    assert w < h
    rate = airflow._friction_rate_pa_per_m(
        airflow.oval_area(w, h), airflow.hydraulic_diameter_oval(w, h), *args[:1], *args[2:]
    )
    assert rate == pytest.approx(1.0, rel=1e-3)


def test_oval_dims_for_static_regain_accepts_tall_aspect_ratio():
    kwargs = dict(
        flow_m3_s=0.3,
        upstream_velocity_pressure_pa=40.0,
        regain_factor=0.75,
        length_m=5.0,
        roughness_m=0.00009,
        kinematic_viscosity_m2_s=1.5e-5,
        air_density_kg_m3=1.2,
        min_velocity_m_s=2.0,
    )
    tall = airflow.oval_dims_for_static_regain(mode="aspect_ratio", aspect_ratio=0.5, **kwargs)
    wide = airflow.oval_dims_for_static_regain(mode="aspect_ratio", aspect_ratio=2.0, **kwargs)
    assert tall[0] == pytest.approx(wide[1])
    assert tall[1] == pytest.approx(wide[0])
    assert tall[2] == wide[2]


def test_oval_dims_for_velocity_fixed_height_keeps_height():
    w, h = airflow.oval_dims_for_velocity(0.4, 6.0, "fixed_height", fixed_dim_m=0.25)
    assert h == pytest.approx(0.25)


def test_oval_dims_for_velocity_fixed_width_keeps_width():
    w, h = airflow.oval_dims_for_velocity(0.4, 6.0, "fixed_width", fixed_dim_m=0.6)
    assert w == pytest.approx(0.6)


# ----------------------------------------------------------------------------
# Duct sizing: constant friction rate
# ----------------------------------------------------------------------------

ROUGHNESS_M = airflow.mm_to_m(0.09)
VISCOSITY = 1.51e-5
DENSITY = 1.204


def _actual_friction_rate(flow_m3_s, area_m2, dh_m):
    v = airflow.velocity_from_flow(flow_m3_s, area_m2)
    re = airflow.reynolds_number(v, dh_m, VISCOSITY)
    f = airflow.friction_factor_altshul_tsal(re, ROUGHNESS_M / dh_m)
    return airflow.darcy_weisbach_pressure_loss(f, 1.0, dh_m, DENSITY, v)


def test_circular_diameter_for_friction_rate_round_trip():
    flow, target = 0.5, 1.0
    d = airflow.circular_diameter_for_friction_rate(flow, target, ROUGHNESS_M, VISCOSITY, DENSITY)
    got_rate = _actual_friction_rate(flow, airflow.circular_area(d), airflow.hydraulic_diameter_circular(d))
    assert got_rate == pytest.approx(target, rel=1e-3)


@pytest.mark.parametrize(
    "mode,kwargs",
    [
        ("aspect_ratio", {"aspect_ratio": 2.0}),
        ("fixed_height", {"fixed_dim_m": 0.3}),
        ("fixed_width", {"fixed_dim_m": 0.5}),
    ],
)
def test_rect_dims_for_friction_rate_round_trip(mode, kwargs):
    flow, target = 0.5, 1.0
    w, h = airflow.rect_dims_for_friction_rate(flow, target, ROUGHNESS_M, VISCOSITY, DENSITY, mode, **kwargs)
    got_rate = _actual_friction_rate(flow, airflow.rectangular_area(w, h), airflow.hydraulic_diameter_rectangular(w, h))
    assert got_rate == pytest.approx(target, rel=1e-3)


@pytest.mark.parametrize(
    "mode,kwargs",
    [
        ("aspect_ratio", {"aspect_ratio": 2.0}),
        ("fixed_height", {"fixed_dim_m": 0.25}),
        ("fixed_width", {"fixed_dim_m": 0.6}),
    ],
)
def test_oval_dims_for_friction_rate_round_trip(mode, kwargs):
    flow, target = 0.4, 1.0
    w, h = airflow.oval_dims_for_friction_rate(flow, target, ROUGHNESS_M, VISCOSITY, DENSITY, mode, **kwargs)
    assert w >= h > 0.0
    got_rate = _actual_friction_rate(flow, airflow.oval_area(w, h), airflow.hydraulic_diameter_oval(w, h))
    assert got_rate == pytest.approx(target, rel=1e-3)


def test_friction_rate_sizing_monotonic_with_target():
    # A looser (smaller) target friction rate should always require a bigger duct.
    flow = 0.5
    d_tight = airflow.circular_diameter_for_friction_rate(flow, 2.0, ROUGHNESS_M, VISCOSITY, DENSITY)
    d_loose = airflow.circular_diameter_for_friction_rate(flow, 0.5, ROUGHNESS_M, VISCOSITY, DENSITY)
    assert d_loose > d_tight


def test_friction_rate_sizing_clamps_to_bracket_when_unreachable():
    # An absurdly tight target (unreachable within the bracket) clamps to the
    # largest bracketed diameter rather than raising or looping forever.
    d = airflow.circular_diameter_for_friction_rate(0.5, 1e-6, ROUGHNESS_M, VISCOSITY, DENSITY)
    assert d == pytest.approx(5.0)


# ----------------------------------------------------------------------------
# Duct sizing: static regain
# ----------------------------------------------------------------------------

REGAIN_FACTOR = 0.75
MIN_VELOCITY = 3.0

# Chosen (and verified numerically) so the regain-vs-friction crossing point
# falls strictly between zero and the minimum-velocity-floor ceiling -- i.e.
# this scenario is NOT floor-clamped, so the round-trip balance equation is
# the thing actually being exercised.
ROUND_TRIP_UPSTREAM_V = 5.0
ROUND_TRIP_LENGTH = 10.0


def _regain_balance(area_m2, dh_m, flow_m3_s, upstream_vp_pa, regain_factor, length_m):
    v = airflow.velocity_from_flow(flow_m3_s, area_m2)
    vp = airflow.velocity_pressure(DENSITY, v)
    re = airflow.reynolds_number(v, dh_m, VISCOSITY)
    f = airflow.friction_factor_altshul_tsal(re, ROUGHNESS_M / dh_m)
    friction = airflow.darcy_weisbach_pressure_loss(f, length_m, dh_m, DENSITY, v)
    regain = regain_factor * (upstream_vp_pa - vp)
    return regain, friction, v


def test_circular_static_regain_round_trip_balances_when_not_floor_clamped():
    flow = 0.3
    upstream_vp = airflow.velocity_pressure(DENSITY, ROUND_TRIP_UPSTREAM_V)
    d, balanced = airflow.circular_diameter_for_static_regain(
        flow, upstream_vp, REGAIN_FACTOR, ROUND_TRIP_LENGTH, ROUGHNESS_M, VISCOSITY, DENSITY, MIN_VELOCITY
    )
    assert balanced is True
    floor_d = airflow.circular_diameter_for_velocity(flow, MIN_VELOCITY)
    assert d < floor_d - 1e-9  # sanity: this case must not be floor-clamped

    regain, friction, _v = _regain_balance(
        airflow.circular_area(d),
        airflow.hydraulic_diameter_circular(d),
        flow,
        upstream_vp,
        REGAIN_FACTOR,
        ROUND_TRIP_LENGTH,
    )
    assert regain == pytest.approx(friction, rel=1e-3)


def test_circular_static_regain_not_clamped_when_faster_than_floor():
    # A fast upstream section (8 m/s) feeding a short, low-friction run: the
    # unconstrained balance point comes out faster than the minimum-velocity
    # floor. That's not a problem -- the floor is a minimum, not a maximum --
    # so sizing should return that faster/smaller duct as a normal balanced
    # solution rather than clamping down to the floor.
    flow, length = 0.05, 0.5
    upstream_vp = airflow.velocity_pressure(DENSITY, 8.0)
    d, balanced = airflow.circular_diameter_for_static_regain(
        flow, upstream_vp, REGAIN_FACTOR, length, ROUGHNESS_M, VISCOSITY, DENSITY, MIN_VELOCITY
    )
    assert balanced is True
    floor_d = airflow.circular_diameter_for_velocity(flow, MIN_VELOCITY)
    assert d < floor_d - 1e-9

    regain, friction, _v = _regain_balance(
        airflow.circular_area(d), airflow.hydraulic_diameter_circular(d), flow, upstream_vp, REGAIN_FACTOR, length
    )
    assert regain == pytest.approx(friction, rel=1e-3)


def test_circular_static_regain_clamps_to_minimum_velocity_floor():
    # A long, rough run fed by an upstream section only just above the
    # floor itself: even at the slowest/largest allowed duct (the floor),
    # regain still can't offset this section's own friction -- the classic
    # static-regain failure mode -- so sizing clamps to the floor (and
    # reports balanced=False) rather than proposing something even slower.
    flow, length = 0.3, 40.0
    upstream_vp = airflow.velocity_pressure(DENSITY, 3.5)
    d, balanced = airflow.circular_diameter_for_static_regain(
        flow, upstream_vp, REGAIN_FACTOR, length, ROUGHNESS_M, VISCOSITY, DENSITY, MIN_VELOCITY
    )
    assert balanced is False
    floor_d = airflow.circular_diameter_for_velocity(flow, MIN_VELOCITY)
    assert d == pytest.approx(floor_d)


def test_static_regain_higher_regain_factor_gives_smaller_duct():
    flow = 0.3
    upstream_vp = airflow.velocity_pressure(DENSITY, ROUND_TRIP_UPSTREAM_V)
    d_low_r, _balanced = airflow.circular_diameter_for_static_regain(
        flow, upstream_vp, 0.5, ROUND_TRIP_LENGTH, ROUGHNESS_M, VISCOSITY, DENSITY, MIN_VELOCITY
    )
    d_high_r, _balanced = airflow.circular_diameter_for_static_regain(
        flow, upstream_vp, 1.0, ROUND_TRIP_LENGTH, ROUGHNESS_M, VISCOSITY, DENSITY, MIN_VELOCITY
    )
    assert d_high_r < d_low_r


def test_circular_static_regain_fitting_loss_pa_round_trip_balances():
    # With a nonzero fitting_loss_pa, the balance equation becomes
    # regain == friction + fitting_loss_pa -- check the returned size
    # actually satisfies that (not just the plain friction-only version).
    flow = 0.3
    upstream_vp = airflow.velocity_pressure(DENSITY, ROUND_TRIP_UPSTREAM_V)
    fitting_loss_pa = 2.0
    d, balanced = airflow.circular_diameter_for_static_regain(
        flow,
        upstream_vp,
        REGAIN_FACTOR,
        ROUND_TRIP_LENGTH,
        ROUGHNESS_M,
        VISCOSITY,
        DENSITY,
        MIN_VELOCITY,
        fitting_loss_pa=fitting_loss_pa,
    )
    assert balanced is True
    regain, friction, _v = _regain_balance(
        airflow.circular_area(d),
        airflow.hydraulic_diameter_circular(d),
        flow,
        upstream_vp,
        REGAIN_FACTOR,
        ROUND_TRIP_LENGTH,
    )
    assert regain == pytest.approx(friction + fitting_loss_pa, rel=1e-3)


def test_circular_static_regain_fitting_loss_pa_gives_bigger_duct():
    # More to overcome (friction + fitting loss, instead of just friction)
    # needs more regain, which only comes from slowing down further --
    # i.e. a bigger duct than the plain friction-only balance.
    flow = 0.3
    upstream_vp = airflow.velocity_pressure(DENSITY, ROUND_TRIP_UPSTREAM_V)
    d_no_loss, _balanced = airflow.circular_diameter_for_static_regain(
        flow, upstream_vp, REGAIN_FACTOR, ROUND_TRIP_LENGTH, ROUGHNESS_M, VISCOSITY, DENSITY, MIN_VELOCITY
    )
    d_with_loss, _balanced = airflow.circular_diameter_for_static_regain(
        flow,
        upstream_vp,
        REGAIN_FACTOR,
        ROUND_TRIP_LENGTH,
        ROUGHNESS_M,
        VISCOSITY,
        DENSITY,
        MIN_VELOCITY,
        fitting_loss_pa=2.0,
    )
    assert d_with_loss > d_no_loss


@pytest.mark.parametrize(
    "mode,kwargs",
    [
        ("aspect_ratio", {"aspect_ratio": 2.0}),
        ("fixed_height", {"fixed_dim_m": 0.3}),
        ("fixed_width", {"fixed_dim_m": 0.5}),
    ],
)
def test_rect_dims_for_static_regain_round_trip(mode, kwargs):
    flow = 0.3
    upstream_vp = airflow.velocity_pressure(DENSITY, ROUND_TRIP_UPSTREAM_V)
    w, h, balanced = airflow.rect_dims_for_static_regain(
        flow,
        upstream_vp,
        REGAIN_FACTOR,
        ROUND_TRIP_LENGTH,
        ROUGHNESS_M,
        VISCOSITY,
        DENSITY,
        MIN_VELOCITY,
        mode,
        **kwargs,
    )
    assert balanced is True
    assert w > 0.0 and h > 0.0
    regain, friction, _v = _regain_balance(
        airflow.rectangular_area(w, h),
        airflow.hydraulic_diameter_rectangular(w, h),
        flow,
        upstream_vp,
        REGAIN_FACTOR,
        ROUND_TRIP_LENGTH,
    )
    assert regain == pytest.approx(friction, rel=1e-3)


@pytest.mark.parametrize(
    "mode,kwargs",
    [
        ("aspect_ratio", {"aspect_ratio": 2.0}),
        ("fixed_height", {"fixed_dim_m": 0.25}),
        ("fixed_width", {"fixed_dim_m": 0.6}),
    ],
)
def test_oval_dims_for_static_regain_round_trip(mode, kwargs):
    flow = 0.3
    upstream_vp = airflow.velocity_pressure(DENSITY, ROUND_TRIP_UPSTREAM_V)
    w, h, balanced = airflow.oval_dims_for_static_regain(
        flow,
        upstream_vp,
        REGAIN_FACTOR,
        ROUND_TRIP_LENGTH,
        ROUGHNESS_M,
        VISCOSITY,
        DENSITY,
        MIN_VELOCITY,
        mode,
        **kwargs,
    )
    assert balanced is True
    assert w >= h > 0.0
    regain, friction, _v = _regain_balance(
        airflow.oval_area(w, h),
        airflow.hydraulic_diameter_oval(w, h),
        flow,
        upstream_vp,
        REGAIN_FACTOR,
        ROUND_TRIP_LENGTH,
    )
    assert regain == pytest.approx(friction, rel=1e-3)


def test_rect_dims_for_static_regain_fixed_height_keeps_height_exact():
    flow, length = 0.3, 10.0
    upstream_vp = airflow.velocity_pressure(DENSITY, 8.0)
    w, h, _balanced = airflow.rect_dims_for_static_regain(
        flow,
        upstream_vp,
        REGAIN_FACTOR,
        length,
        ROUGHNESS_M,
        VISCOSITY,
        DENSITY,
        MIN_VELOCITY,
        "fixed_height",
        fixed_dim_m=0.3,
    )
    assert h == pytest.approx(0.3)


def test_rect_dims_for_static_regain_not_clamped_when_faster_than_floor():
    flow, length = 0.05, 0.5
    upstream_vp = airflow.velocity_pressure(DENSITY, 8.0)
    w, h, balanced = airflow.rect_dims_for_static_regain(
        flow,
        upstream_vp,
        REGAIN_FACTOR,
        length,
        ROUGHNESS_M,
        VISCOSITY,
        DENSITY,
        MIN_VELOCITY,
        "aspect_ratio",
        aspect_ratio=2.0,
    )
    assert balanced is True
    floor_w, floor_h = airflow.rect_dims_for_velocity(flow, MIN_VELOCITY, "aspect_ratio", aspect_ratio=2.0)
    assert w < floor_w - 1e-9
    assert h < floor_h - 1e-9


def test_rect_dims_for_static_regain_reports_unbalanced_when_floor_clamped():
    flow, length = 0.3, 40.0
    upstream_vp = airflow.velocity_pressure(DENSITY, 3.5)
    w, h, balanced = airflow.rect_dims_for_static_regain(
        flow,
        upstream_vp,
        REGAIN_FACTOR,
        length,
        ROUGHNESS_M,
        VISCOSITY,
        DENSITY,
        MIN_VELOCITY,
        "aspect_ratio",
        aspect_ratio=2.0,
    )
    assert balanced is False
    floor_w, floor_h = airflow.rect_dims_for_velocity(flow, MIN_VELOCITY, "aspect_ratio", aspect_ratio=2.0)
    assert (w, h) == pytest.approx((floor_w, floor_h))
