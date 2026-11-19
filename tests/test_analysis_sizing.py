"""
Pure tests for freecad.HVAC.analysis.sizing -- no FreeCAD/conftest stubbing
needed, since analysis/ has no FreeCAD dependency at all.
"""

import pytest

from analysis_fixtures import AIR_DENSITY, AIR_VISCOSITY, DEFAULT_ROUGHNESS_MM, air_state, base_tree, circular_section

from freecad.HVAC.analysis import flow, physics
from freecad.HVAC.analysis.model import SegmentModel, SizingSettings
from freecad.HVAC.analysis.sizing import (
    ConstantFrictionRateSizer, ConstantVelocitySizer, LocalStaticRegainSizer, _size_one_segment, _sizes_converged,
)


def _components(net):
    components, warnings = flow.solve_flow_components(net)
    assert warnings == []
    return components


def test_constant_velocity_sizes_every_segment_to_the_target():
    net = base_tree()
    settings = SizingSettings(method="ConstantVelocity", target_velocity_ms=5.0, rounding_mm=0.0)
    result = ConstantVelocitySizer().size(net, _components(net), settings)

    assert result.warnings == []
    assert set(result.segments) == {"A", "B", "C"}
    for edge_key, flow_lps in (("A", 80.0), ("B", 50.0), ("C", 30.0)):
        sres = result.segments[edge_key]
        expected_d_m = physics.circular_diameter_for_velocity(physics.lps_to_m3s(flow_lps), 5.0)
        assert sres.new_section.diameter_mm == pytest.approx(expected_d_m * 1000.0)
        assert sres.velocity_ms == pytest.approx(5.0)


def test_constant_friction_rate_matches_independent_oracle():
    net = base_tree()
    settings = SizingSettings(
        method="ConstantFrictionRate", target_friction_rate_pa_per_m=1.0,
        default_roughness_mm=DEFAULT_ROUGHNESS_MM, rounding_mm=0.0,
    )
    result = ConstantFrictionRateSizer().size(net, _components(net), settings)

    expected_d_m = physics.circular_diameter_for_friction_rate(
        physics.lps_to_m3s(80.0), 1.0, physics.mm_to_m(DEFAULT_ROUGHNESS_MM), AIR_VISCOSITY, AIR_DENSITY,
    )
    assert result.segments["A"].new_section.diameter_mm == pytest.approx(expected_d_m * 1000.0)


def test_local_static_regain_first_segment_at_target_velocity():
    # Segment A leaves the source directly -- no upstream section exists
    # yet, so it's sized by plain constant-velocity sizing at the target,
    # not the regain-balance equation.
    net = base_tree(loss_evaluator=lambda pv: 0.0)
    settings = SizingSettings(
        method="StaticRegain", target_velocity_ms=5.0, min_velocity_ms=4.0, regain_factor=0.75, rounding_mm=0.0,
    )
    result = LocalStaticRegainSizer().size(net, _components(net), settings)

    segA = result.segments["A"]
    assert segA.velocity_ms == pytest.approx(5.0)
    expected_d_m = physics.circular_diameter_for_velocity(physics.lps_to_m3s(80.0), 5.0)
    assert segA.new_section.diameter_mm == pytest.approx(expected_d_m * 1000.0)


def test_local_static_regain_downstream_matches_independent_oracle():
    # Both B and C are children of the same node (N2), so both must be
    # sized against the SAME upstream velocity (A's own).
    net = base_tree(loss_evaluator=lambda pv: 0.0)
    settings = SizingSettings(
        method="StaticRegain", target_velocity_ms=5.0, min_velocity_ms=4.0, regain_factor=0.75, rounding_mm=0.0,
    )
    result = LocalStaticRegainSizer().size(net, _components(net), settings)

    segA, segC = result.segments["A"], result.segments["C"]
    upstream_vp = physics.velocity_pressure(AIR_DENSITY, segA.velocity_ms)
    expected_d_m, _balanced = physics.circular_diameter_for_static_regain(
        physics.lps_to_m3s(30.0), upstream_vp, 0.75, 6.0,
        physics.mm_to_m(DEFAULT_ROUGHNESS_MM), AIR_VISCOSITY, AIR_DENSITY, 4.0,
    )
    assert segC.new_section.diameter_mm == pytest.approx(expected_d_m * 1000.0)


def test_local_static_regain_accounts_for_junction_fitting_loss():
    # With a real (non-zero) fitting loss at the branch, sections must
    # settle to a DIFFERENT (larger, since more loss needs less regain-vs-
    # friction help) size than the zero-loss case above. min_velocity_ms is
    # kept low here so neither case is floor-clamped (see the dedicated
    # clamped-floor test below) -- the difference must come from the
    # regain-balance equation itself, not both sides hitting the same clamp.
    net_no_loss = base_tree(loss_evaluator=lambda pv: 0.0)
    net_with_loss = base_tree(loss_evaluator=lambda pv: 0.5)
    settings = SizingSettings(
        method="StaticRegain", target_velocity_ms=5.0, min_velocity_ms=1.0, regain_factor=0.75, rounding_mm=0.0,
    )

    result_no_loss = LocalStaticRegainSizer().size(net_no_loss, _components(net_no_loss), settings)
    result_with_loss = LocalStaticRegainSizer().size(net_with_loss, _components(net_with_loss), settings)

    assert result_with_loss.segments["C"].new_section.diameter_mm != pytest.approx(
        result_no_loss.segments["C"].new_section.diameter_mm
    )


def test_local_static_regain_reports_unbalanced_when_floor_clamped():
    # A minimum velocity close to the target leaves little room to regain
    # into -- friction still beats regain even at the smallest allowed duct
    # (the min_velocity ceiling), so sizing clamps there and reports the
    # section as unbalanced (not an error -- a size is still returned).
    net = base_tree(loss_evaluator=lambda pv: 0.0)
    settings = SizingSettings(
        method="StaticRegain", target_velocity_ms=5.0, min_velocity_ms=3.0, regain_factor=0.75, rounding_mm=0.0,
    )
    result = LocalStaticRegainSizer().size(net, _components(net), settings)

    assert result.segments["C"].regain_balanced is False
    assert any("balancing damper" in w for w in result.warnings)


def test_segment_velocity_override_forces_constant_velocity():
    net = base_tree()
    net.segments["A"].velocity_override_ms = 6.0
    settings = SizingSettings(method="StaticRegain", target_velocity_ms=5.0, rounding_mm=0.0)
    result = LocalStaticRegainSizer().size(net, _components(net), settings)

    assert result.segments["A"].velocity_ms == pytest.approx(6.0)


def test_zero_flow_segment_is_left_unchanged():
    seg = SegmentModel(edge_key="A", section=circular_section(150.0), length_mm=4000.0,
                        roughness_mm=DEFAULT_ROUGHNESS_MM)
    settings = SizingSettings(method="ConstantVelocity", target_velocity_ms=5.0, rounding_mm=10.0)

    sres = _size_one_segment(seg, 0.0, settings, air_state(), "ConstantVelocity")

    assert sres.changed is False
    assert sres.new_section.diameter_mm == pytest.approx(150.0)


def test_unsupported_profile_raises():
    seg = SegmentModel(edge_key="A", section=circular_section(0.0), length_mm=1000.0)
    seg.section.profile = ""
    settings = SizingSettings(method="ConstantVelocity", target_velocity_ms=5.0)

    with pytest.raises(ValueError):
        _size_one_segment(seg, 100.0, settings, air_state(), "ConstantVelocity")


def test_sizes_converged_helper():
    prev = {"A": (100.0, 0.0, 0.0)}
    assert _sizes_converged(prev, {"A": (100.4, 0.0, 0.0)}, tolerance_mm=0.5) is True
    assert _sizes_converged(prev, {"A": (101.0, 0.0, 0.0)}, tolerance_mm=0.5) is False
    assert _sizes_converged(prev, {"B": (100.0, 0.0, 0.0)}, tolerance_mm=0.5) is False
