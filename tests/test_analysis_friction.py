"""
Pure tests for freecad.HVAC.analysis.friction and its use by the pressure
solver and the sizers -- no FreeCAD needed.
"""

import math

import pytest
from analysis_fixtures import AIR_DENSITY, AIR_VISCOSITY, air_state, base_tree, circular_section

from freecad.HVAC.analysis import flow, physics
from freecad.HVAC.analysis import friction as fr
from freecad.HVAC.analysis.model import SegmentModel, SizingSettings
from freecad.HVAC.analysis.pressure import PressureSolver
from freecad.HVAC.analysis.sizing import _size_one_segment

ROUGH_M = 0.09e-3


def _round(diameter_mm, flow_lps):
    d = diameter_mm / 1000.0
    return physics.lps_to_m3s(flow_lps), physics.circular_area(d), d


def _old_formula(flow_m3_s, area, dh, roughness_m=ROUGH_M):
    v = physics.velocity_from_flow(flow_m3_s, area)
    re = physics.reynolds_number(v, dh, AIR_VISCOSITY)
    f = physics.friction_factor_altshul_tsal(re, roughness_m / dh)
    return physics.darcy_weisbach_pressure_loss(f, 1.0, dh, AIR_DENSITY, v)


# ---------------------------------------------------------------- Darcy-Weisbach


def test_default_model_is_the_old_formula():
    q, a, dh = _round(250.0, 200.0)
    expected = _old_formula(q, a, dh)
    assert fr.rate_pa_per_m(None, q, a, dh, ROUGH_M, AIR_DENSITY, AIR_VISCOSITY) == pytest.approx(expected, rel=1e-12)
    assert fr.DEFAULT_MODEL.rate_pa_per_m(q, a, dh, ROUGH_M, AIR_DENSITY, AIR_VISCOSITY) == pytest.approx(expected)


def test_colebrook_solves_its_equation_and_is_close_to_altshul_tsal():
    re, eps_rel = 1.2e5, 3e-4
    f = fr.friction_factor_colebrook(re, eps_rel)
    rhs = -2.0 * math.log10(eps_rel / 3.7 + 2.51 / (re * math.sqrt(f)))
    assert 1.0 / math.sqrt(f) == pytest.approx(rhs, rel=1e-9)
    assert f == pytest.approx(physics.friction_factor_altshul_tsal(re, eps_rel), rel=0.05)


def test_colebrook_laminar_and_zero():
    assert fr.friction_factor_colebrook(1000.0, 0.001) == pytest.approx(0.064)
    assert fr.friction_factor_colebrook(0.0, 0.001) == 0.0


def test_colebrook_model_rate_close_to_default():
    q, a, dh = _round(300.0, 400.0)
    model = fr.DarcyWeisbach(fr.COLEBROOK)
    rate = model.rate_pa_per_m(q, a, dh, ROUGH_M, AIR_DENSITY, AIR_VISCOSITY)
    assert rate == pytest.approx(_old_formula(q, a, dh), rel=0.05)
    assert "Colebrook" in model.label


def test_unknown_friction_factor_rejected():
    with pytest.raises(ValueError):
        fr.DarcyWeisbach("moody")


# ---------------------------------------------------------------- rate_pa_per_m guard


def test_rate_is_zero_without_flow_or_section():
    q, a, dh = _round(200.0, 100.0)
    assert fr.rate_pa_per_m(None, 0.0, a, dh, ROUGH_M, AIR_DENSITY, AIR_VISCOSITY) == 0.0
    assert fr.rate_pa_per_m(None, q, 0.0, dh, ROUGH_M, AIR_DENSITY, AIR_VISCOSITY) == 0.0


@pytest.mark.parametrize("bad", [-1.0, float("nan"), float("inf")])
def test_rate_rejects_bad_model_output(bad):
    class Bad:
        label = "bad"

        def rate_pa_per_m(self, *args):
            return bad

    q, a, dh = _round(200.0, 100.0)
    with pytest.raises(ValueError, match="bad"):
        fr.rate_pa_per_m(Bad(), q, a, dh, ROUGH_M, AIR_DENSITY, AIR_VISCOSITY)


# ---------------------------------------------------------------- scaling and Fig. 14-4


def test_scaled_friction_multiplies_its_base():
    q, a, dh = _round(200.0, 100.0)
    base = _old_formula(q, a, dh)
    assert fr.ScaledFriction(None, 2.5).rate_pa_per_m(q, a, dh, ROUGH_M, AIR_DENSITY, AIR_VISCOSITY) == pytest.approx(
        2.5 * base
    )
    inner = fr.ScaledFriction(None, 2.0)
    assert fr.ScaledFriction(inner, 1.5).rate_pa_per_m(q, a, dh, ROUGH_M, AIR_DENSITY, AIR_VISCOSITY) == pytest.approx(
        3.0 * base
    )


@pytest.mark.parametrize("factor", [0.0, -1.0, float("nan")])
def test_scaled_friction_rejects_bad_factor(factor):
    with pytest.raises(ValueError):
        fr.ScaledFriction(None, factor)


def test_flex_compression_factor_follows_the_chart():
    assert fr.flex_compression_factor(0.0) == pytest.approx(1.0)
    assert fr.flex_compression_factor(10.0) == pytest.approx(1.95)
    assert fr.flex_compression_factor(30.0) == pytest.approx(4.0)
    values = [fr.flex_compression_factor(x) for x in range(0, 31)]
    assert all(b > a for a, b in zip(values, values[1:]))
    # Clamped outside the printed range.
    assert fr.flex_compression_factor(-5.0) == pytest.approx(1.0)
    assert fr.flex_compression_factor(50.0) == pytest.approx(4.0)


# ---------------------------------------------------------------- table


def _power_law(d_mm, v):
    return 0.02 * v**1.9 / (d_mm / 1000.0) ** 1.2


def _power_law_rows(basis):
    rows = []
    for d in (100.0, 200.0, 400.0):
        for v in (2.0, 5.0, 10.0):
            x = v if basis == fr.BASIS_VELOCITY else physics.m3s_to_lps(v * physics.circular_area(d / 1000.0))
            rows.append((d, x, _power_law(d, v)))
    return rows


@pytest.mark.parametrize("d_mm,flow_lps", [(200.0, 100.0), (150.0, 60.0), (500.0, 2500.0), (80.0, 10.0)])
def test_table_reproduces_a_power_law_inside_and_outside(d_mm, flow_lps):
    # Log-log interpolation and extrapolation are exact for a power law in V and D.
    model = fr.TableFriction(_power_law_rows(fr.BASIS_VELOCITY))
    q, a, dh = _round(d_mm, flow_lps)
    v = physics.velocity_from_flow(q, a)
    assert model.rate_pa_per_m(q, a, dh, 0.0, AIR_DENSITY, AIR_VISCOSITY) == pytest.approx(
        _power_law(d_mm, v), rel=1e-9
    )


def test_table_on_flow_basis_matches_at_its_own_diameters():
    model = fr.TableFriction(_power_law_rows(fr.BASIS_FLOW), basis=fr.BASIS_FLOW)
    q, a, dh = _round(200.0, 150.0)
    v = physics.velocity_from_flow(q, a)
    assert model.rate_pa_per_m(q, a, dh, 0.0, AIR_DENSITY, AIR_VISCOSITY) == pytest.approx(
        _power_law(200.0, v), rel=1e-9
    )


def test_table_from_csv():
    text = "# my chart\ndiameter_mm, velocity_ms, pa_per_m\n\n100, 2, 0.5\n100, 4, 1.8\n200,2,0.2\n200,4,0.75\n"
    model = fr.TableFriction.from_csv(text, label="chart")
    assert model.basis == fr.BASIS_VELOCITY and model.diameters_mm == [100.0, 200.0]
    q, a, dh = _round(100.0, physics.m3s_to_lps(2.0 * physics.circular_area(0.1)))
    assert model.rate_pa_per_m(q, a, dh, 0.0, AIR_DENSITY, AIR_VISCOSITY) == pytest.approx(0.5)
    flow_model = fr.TableFriction.from_csv("diameter_mm,flow_lps,pa_per_m\n100,20,1\n100,40,3.5\n")
    assert flow_model.basis == fr.BASIS_FLOW


@pytest.mark.parametrize(
    "text,match",
    [
        ("", "empty"),
        ("diameter,velocity_ms,pa_per_m\n100,2,1\n", "diameter_mm"),
        ("diameter_mm,speed,pa_per_m\n100,2,1\n", "velocity_ms"),
        ("diameter_mm,velocity_ms,pa_per_m\n100,two,1\n", "row 2"),
        ("diameter_mm,velocity_ms,pa_per_m\n", "no rows"),
        ("diameter_mm,velocity_ms,pa_per_m\n100,0,1\n", "positive"),
    ],
)
def test_table_csv_errors(text, match):
    with pytest.raises(ValueError, match=match):
        fr.TableFriction.from_csv(text)


# ---------------------------------------------------------------- expression


def test_expression_evaluates_in_si_variables():
    model = fr.ExpressionFriction("0.02 / Dh * rho * V**2 / 2")
    q, a, dh = _round(200.0, 100.0)
    v = physics.velocity_from_flow(q, a)
    expected = 0.02 / dh * AIR_DENSITY * v**2 / 2
    assert model.rate_pa_per_m(q, a, dh, ROUGH_M, AIR_DENSITY, AIR_VISCOSITY) == pytest.approx(expected)


def test_expression_functions_and_constants():
    model = fr.ExpressionFriction("max(sqrt(Q), -abs(-2)) + log10(100) + exp(0) + pi*0 + Re*0 + eps*0 + nu*0 + A*0")
    assert model.evaluate(Q=4.0, V=1.0, Dh=1.0, A=1.0, eps=0.0, rho=1.2, nu=1e-5, Re=1.0) == pytest.approx(5.0)


@pytest.mark.parametrize(
    "text",
    [
        "__import__('os').system('true')",
        "Q.real",
        "(lambda: 1)()",
        "open('x')",
        "[Q][0]",
        "Q if V else Dh",
        "Q < V",
        "'abc'",
        "True",
        "foo * 2",
        "max(Q, key=V)",
        "Q // 2",
    ],
)
def test_expression_rejects_anything_not_whitelisted(text):
    with pytest.raises(ValueError):
        fr.ExpressionFriction(text)


def test_expression_rejects_empty_long_and_bad_syntax():
    for text in ("", "   ", "Q * (", "Q" + " + Q" * 300):
        with pytest.raises(ValueError):
            fr.ExpressionFriction(text)


def test_expression_runtime_errors_become_value_errors():
    model = fr.ExpressionFriction("1 / (V - V)")
    q, a, dh = _round(200.0, 100.0)
    with pytest.raises(ValueError, match="failed"):
        model.rate_pa_per_m(q, a, dh, ROUGH_M, AIR_DENSITY, AIR_VISCOSITY)
    with pytest.raises(ValueError):
        fr.ExpressionFriction("10.0 ** 10.0 ** 10.0").evaluate(Q=0, V=0, Dh=1, A=1, eps=0, rho=1, nu=1, Re=0)


# ---------------------------------------------------------------- solvers use the segment's model


def _solve(net):
    components, warnings = flow.solve_flow_components(net)
    assert warnings == []
    trees, _ = PressureSolver().solve(net, components)
    return trees[0]


def test_pressure_solver_uses_the_segment_friction_model():
    plain = _solve(base_tree(loss_evaluator=lambda pv: 0.5))
    net = base_tree(loss_evaluator=lambda pv: 0.5)
    net.segments["A"].friction_model = fr.ScaledFriction(None, 3.0)
    scaled = _solve(net)
    assert scaled.segments["A"].friction_loss_pa == pytest.approx(3.0 * plain.segments["A"].friction_loss_pa)
    assert scaled.segments["B"].friction_loss_pa == pytest.approx(plain.segments["B"].friction_loss_pa)


@pytest.mark.parametrize("method", ["ConstantFrictionRate", "StaticRegain"])
def test_sizing_with_more_friction_needs_a_bigger_duct(method):
    settings = SizingSettings(
        method=method, target_friction_rate_pa_per_m=1.0, rounding_mm=0.0, regain_factor=0.75, min_velocity_ms=1.0
    )
    plain = SegmentModel(edge_key="A", section=circular_section(200.0), length_mm=5000.0, roughness_mm=0.09)
    rough = SegmentModel(
        edge_key="A",
        section=circular_section(200.0),
        length_mm=5000.0,
        roughness_mm=0.09,
        friction_model=fr.ScaledFriction(None, 3.0),
    )
    kwargs = {"upstream_velocity_pressure_pa": 40.0} if method == "StaticRegain" else {}
    small = _size_one_segment(plain, 200.0, settings, air_state(), method, **kwargs)
    big = _size_one_segment(rough, 200.0, settings, air_state(), method, **kwargs)
    assert big.new_section.diameter_mm > small.new_section.diameter_mm
    if method == "ConstantFrictionRate":
        assert big.friction_rate_pa_per_m == pytest.approx(1.0, rel=1e-3)
