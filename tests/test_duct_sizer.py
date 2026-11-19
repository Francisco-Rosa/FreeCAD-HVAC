"""
Tests for freecad.HVAC.core.DuctSizer against the same fake-object harness
used for AirflowSolver (see network_fixtures.py), verifying: constant-
velocity and constant-friction-rate sizing for all three profiles (circular,
rectangular, oval) and all three rectangular/oval modes, the preview-only
(non-mutating) solve()/apply() split, rounding, and the zero-flow and
missing-fixed-dimension edge cases.
"""

import pytest

import conftest  # noqa: F401 -- installs FreeCAD/FreeCADGui/Part/PySide stubs
from network_fixtures import (
    AIR_DENSITY,
    AIR_VISCOSITY,
    DEFAULT_ROUGHNESS_MM,
    FakeParser,
    base_tree,
    legacy_loss_result,
    make_junction,
    make_net,
    make_segment,
)

from freecad.HVAC.analysis import physics as airflow
from freecad.HVAC.analysis.balancing import BalancingRequirement, PressureBalanceCoordinator, PressureBalancedSizingResult
from freecad.HVAC.core import _analysis_adapter as duct_sizer_mod
from freecad.HVAC.core.DuctSizer import DuctSizer


class _NoLossTypeDef:
    pass


class _NoLossRegistry:
    """
    Registry stub: every junction resolves to a real (non-None) type, but
    its loss function always reports exactly 0.0 -- so StaticRegain's
    fitting-loss estimate is 0.0 everywhere (i.e. sizing behaves exactly
    like a plain regain-vs-friction solve), rather than falling back to
    K_DEFAULT the way an unresolved type would. This is the default for
    every test in this file (most of them are about other things --
    velocity propagation, overrides, error handling -- not fitting loss);
    tests that specifically exercise fitting-loss-aware sizing override
    this with their own monkeypatch.
    """

    def resolve_type(self, library_id, type_id):
        return _NoLossTypeDef()

    def call_loss(self, library_id, type_def, context):
        return legacy_loss_result(0.0, context)


@pytest.fixture(autouse=True)
def _no_fitting_loss_registry(monkeypatch):
    monkeypatch.setattr(
        duct_sizer_mod.hvaclib.HVACLibraryService,
        "get_hvac_library_registry",
        staticmethod(lambda: _NoLossRegistry()),
    )


def _two_node_tree(profile, diameter_mm=0.0, width_mm=0.0, height_mm=0.0,
                    length_mm=4000.0, roughness_mm=0.0, flow_lps=100.0, velocity_ms=0.0,
                    rectangular_sizing_mode="UseNetworkDefault", target_aspect_ratio=0.0,
                    net_extra_props=None):
    """Single segment A: J1 (balancing terminal) --A--> J2 (leaf, flow_lps)."""
    node_ports = {1: [("A", "start")], 2: [("A", "end")]}
    edge_endpoints = {"A": (1, 2)}
    parser = FakeParser(node_ports, edge_endpoints)
    segment_map = {
        "A": make_segment("A", diameter_mm, length_mm, roughness_mm=roughness_mm, profile=profile,
                           width_mm=width_mm, height_mm=height_mm, velocity_ms=velocity_ms,
                           rectangular_sizing_mode=rectangular_sizing_mode,
                           target_aspect_ratio=target_aspect_ratio),
    }
    junction_map = {
        "N1": make_junction("J1", design_flow=0.0, type_id="end_terminal_marker"),
        "N2": make_junction("J2", design_flow=flow_lps, type_id="end_terminal_marker"),
    }
    net = make_net(parser, segment_map, junction_map, **(net_extra_props or {}))
    return net, segment_map, junction_map


def _sizing_props(method="ConstantVelocity", target_velocity=5.0, target_friction_rate=1.0,
                   rect_mode="FixedAspectRatio", aspect_ratio=2.0, rounding_mm=10.0,
                   default_width=0.0, default_height=0.0,
                   regain_factor=0.75, min_velocity=3.0):
    return dict(
        SizingMethod=method,
        TargetVelocity=target_velocity,
        TargetFrictionRate=target_friction_rate,
        RectangularSizingMode=rect_mode,
        TargetAspectRatio=aspect_ratio,
        SizeRoundingIncrement=rounding_mm,
        DefaultWidth=default_width,
        DefaultHeight=default_height,
        StaticRegainFactor=regain_factor,
        MinimumVelocity=min_velocity,
    )


def _round_up(value_mm, increment_mm):
    import math
    return math.ceil(value_mm / increment_mm - 1e-9) * increment_mm


# ----------------------------------------------------------------------------
# Constant velocity
# ----------------------------------------------------------------------------

def test_circular_constant_velocity_sizing():
    net, segment_map, _ = _two_node_tree(
        "Circular", diameter_mm=100.0, flow_lps=200.0,
        net_extra_props=_sizing_props(method="ConstantVelocity", target_velocity=5.0, rounding_mm=10.0),
    )
    result = DuctSizer(net).solve()

    assert result.warnings == []
    assert len(result.segments) == 1
    sres = result.segments[0]

    expected_d_m = airflow.circular_diameter_for_velocity(airflow.lps_to_m3s(200.0), 5.0)
    expected_mm = _round_up(expected_d_m * 1000.0, 10.0)
    assert sres.new_diameter_mm == pytest.approx(expected_mm)
    assert sres.old_diameter_mm == pytest.approx(100.0)
    assert sres.changed is True

    # Resulting velocity at the (rounded) new size should be <= target (rounding up never increases velocity).
    assert sres.velocity_ms <= 5.0 + 1e-6
    # segment_map object itself must be untouched until apply() is called.
    assert segment_map["A"].Diameter == pytest.approx(100.0)


def test_apply_writes_new_size_and_solve_does_not():
    net, segment_map, _ = _two_node_tree(
        "Circular", diameter_mm=100.0, flow_lps=200.0,
        net_extra_props=_sizing_props(target_velocity=5.0, rounding_mm=10.0),
    )
    sizer = DuctSizer(net)
    result = sizer.solve()
    assert segment_map["A"].Diameter == pytest.approx(100.0)  # solve() must not mutate

    changed_count = sizer.apply(result)
    assert changed_count == 1
    assert segment_map["A"].Diameter == pytest.approx(result.segments[0].new_diameter_mm)


def test_apply_skips_unchanged_segments():
    # Pre-size the duct to already match the target exactly (after rounding),
    # so solve() reports changed=False and apply() should leave it untouched.
    target_v = 5.0
    flow_lps = 200.0
    exact_mm = _round_up(airflow.circular_diameter_for_velocity(airflow.lps_to_m3s(flow_lps), target_v) * 1000.0, 10.0)
    net, segment_map, _ = _two_node_tree(
        "Circular", diameter_mm=exact_mm, flow_lps=flow_lps,
        net_extra_props=_sizing_props(target_velocity=target_v, rounding_mm=10.0),
    )
    result = DuctSizer(net).solve()
    assert result.segments[0].changed is False

    sizer = DuctSizer(net)
    changed_count = sizer.apply(result)
    assert changed_count == 0


@pytest.mark.parametrize("mode,rect_props", [
    ("FixedAspectRatio", {}),
    ("FixedHeight", {"height_mm": 300.0}),
    ("FixedWidth", {"width_mm": 500.0}),
])
def test_rectangular_constant_velocity_sizing_all_modes(mode, rect_props):
    net, segment_map, _ = _two_node_tree(
        "Rectangular", flow_lps=300.0,
        net_extra_props=_sizing_props(method="ConstantVelocity", target_velocity=6.0,
                                       rect_mode=mode, aspect_ratio=2.0, rounding_mm=10.0),
        **rect_props,
    )
    result = DuctSizer(net).solve()

    assert result.warnings == []
    sres = result.segments[0]
    assert sres.new_width_mm > 0.0
    assert sres.new_height_mm > 0.0
    if mode == "FixedHeight":
        assert sres.new_height_mm == pytest.approx(300.0)
    if mode == "FixedWidth":
        assert sres.new_width_mm == pytest.approx(500.0)
    if mode == "FixedAspectRatio":
        # both dimensions independently rounded, so only approximately the target ratio
        assert sres.new_width_mm / sres.new_height_mm == pytest.approx(2.0, rel=0.15)

    got_v = airflow.velocity_from_flow(
        airflow.lps_to_m3s(300.0),
        airflow.rectangular_area(airflow.mm_to_m(sres.new_width_mm), airflow.mm_to_m(sres.new_height_mm)),
    )
    assert got_v <= 6.0 + 1e-6


def test_oval_constant_velocity_sizing_fixed_aspect_ratio():
    net, segment_map, _ = _two_node_tree(
        "Oval", flow_lps=250.0,
        net_extra_props=_sizing_props(method="ConstantVelocity", target_velocity=6.0,
                                       rect_mode="FixedAspectRatio", aspect_ratio=1.8, rounding_mm=10.0),
    )
    result = DuctSizer(net).solve()

    assert result.warnings == []
    sres = result.segments[0]
    assert sres.new_width_mm >= sres.new_height_mm > 0.0


# ----------------------------------------------------------------------------
# Constant friction rate
# ----------------------------------------------------------------------------

def test_circular_constant_friction_rate_sizing():
    net, segment_map, _ = _two_node_tree(
        "Circular", diameter_mm=100.0, flow_lps=200.0,
        net_extra_props=_sizing_props(method="ConstantFrictionRate", target_friction_rate=1.0, rounding_mm=10.0),
    )
    result = DuctSizer(net).solve()

    assert result.warnings == []
    sres = result.segments[0]
    expected_d_m = airflow.circular_diameter_for_friction_rate(
        airflow.lps_to_m3s(200.0), 1.0, airflow.mm_to_m(DEFAULT_ROUGHNESS_MM), AIR_VISCOSITY, AIR_DENSITY
    )
    expected_mm = _round_up(expected_d_m * 1000.0, 10.0)
    assert sres.new_diameter_mm == pytest.approx(expected_mm)
    assert sres.friction_rate_pa_per_m <= 1.0 + 1e-3


@pytest.mark.parametrize("mode,rect_props", [
    ("FixedAspectRatio", {}),
    ("FixedHeight", {"height_mm": 250.0}),
    ("FixedWidth", {"width_mm": 400.0}),
])
def test_rectangular_constant_friction_rate_sizing_all_modes(mode, rect_props):
    net, segment_map, _ = _two_node_tree(
        "Rectangular", flow_lps=300.0,
        net_extra_props=_sizing_props(method="ConstantFrictionRate", target_friction_rate=1.0,
                                       rect_mode=mode, aspect_ratio=2.0, rounding_mm=10.0),
        **rect_props,
    )
    result = DuctSizer(net).solve()

    assert result.warnings == []
    sres = result.segments[0]
    assert sres.new_width_mm > 0.0
    assert sres.new_height_mm > 0.0
    if mode == "FixedHeight":
        assert sres.new_height_mm == pytest.approx(250.0)
    if mode == "FixedWidth":
        assert sres.new_width_mm == pytest.approx(400.0)


# ----------------------------------------------------------------------------
# Edge cases
# ----------------------------------------------------------------------------

# test_zero_flow_segment_is_left_unchanged used to call DuctSizer's own
# internal _size_segment directly -- that per-segment sizing logic moved to
# analysis.sizing._size_one_segment (a pure function of SegmentModel/
# SizingSettings/AirState) -- see tests/test_analysis_sizing.py.


def test_fixed_height_mode_without_existing_or_default_height_warns():
    net, segment_map, _ = _two_node_tree(
        "Rectangular", flow_lps=300.0,
        net_extra_props=_sizing_props(rect_mode="FixedHeight", default_height=0.0),
        # no height_mm passed -> segment's own Height is 0, and DefaultHeight is 0 too
    )
    result = DuctSizer(net).solve()

    assert result.segments == []
    assert len(result.warnings) == 1
    assert "Height" in result.warnings[0]


def test_fixed_height_mode_falls_back_to_network_default_height():
    net, segment_map, _ = _two_node_tree(
        "Rectangular", flow_lps=300.0,
        net_extra_props=_sizing_props(rect_mode="FixedHeight", default_height=350.0),
    )
    result = DuctSizer(net).solve()

    assert result.warnings == []
    assert result.segments[0].new_height_mm == pytest.approx(350.0)


def test_unsupported_profile_warns_without_crashing():
    net, segment_map, _ = _two_node_tree("", flow_lps=300.0, net_extra_props=_sizing_props())
    result = DuctSizer(net).solve()

    assert result.segments == []
    assert len(result.warnings) == 1


def test_base_tree_all_segments_sized():
    # Sanity check against the shared 3-segment tee tree used by AirflowSolver tests.
    net, segment_map, _ = base_tree(net_extra_props=_sizing_props(target_velocity=5.0))
    result = DuctSizer(net).solve()

    assert result.warnings == []
    assert {s.key for s in result.segments} == {"A", "B", "C"}
    assert all(s.new_diameter_mm > 0.0 for s in result.segments)


def test_pressure_balanced_static_regain_wiring():
    # Wiring-only check that SizingMethod=PressureBalancedStaticRegain routes
    # through the real adapter to analysis.balancing.PressureBalanceCoordinator
    # end-to-end (the balancing algorithm itself is exercised directly, and
    # more thoroughly, in tests/test_analysis_balancing.py). An intentionally
    # short/large branch (B) vs. a long/high-friction one (C) gives the
    # coordinator something to actually balance.
    net, segment_map, _ = base_tree(
        segB_len=500.0, segC_len=20000.0,
        net_extra_props=_sizing_props(method="PressureBalancedStaticRegain", target_velocity=5.0, min_velocity=2.5),
    )
    result = DuctSizer(net).solve()

    assert {s.key for s in result.segments} == {"A", "B", "C"}
    assert all(s.new_diameter_mm > 0.0 for s in result.segments)
    # balancing_requirements (if any) must always be mirrored into warnings
    # too, so they're visible without any extra UI work.
    for req in result.balancing_requirements:
        assert any(req.branch_key in w for w in result.warnings)


def test_balancing_requirement_mapped_to_display_ready_row(monkeypatch):
    """
    DuctSizer.solve() must map each pure analysis.balancing.BalancingRequirement
    onto a BalancingRequirementRow carrying the real junction/branch FreeCAD
    objects (from junction_map/segment_map) alongside the exact same
    pressure_deficit_pa/required_k -- not just mirror it into the warnings
    text (already covered above). PressureBalanceCoordinator.size() itself
    is stubbed out so this test is about the adapter's own mapping, not the
    balancing algorithm (already covered by tests/test_analysis_balancing.py).
    """
    net, segment_map, junction_map = base_tree(
        net_extra_props=_sizing_props(method="PressureBalancedStaticRegain", target_velocity=5.0),
    )

    fake_result = PressureBalancedSizingResult(
        balancing_requirements=[
            BalancingRequirement(junction_id="N2", branch_port="B", pressure_deficit_pa=37.2, required_k=2.16),
        ],
    )
    monkeypatch.setattr(PressureBalanceCoordinator, "size", lambda self, *a, **k: fake_result)

    result = DuctSizer(net).solve()

    assert len(result.balancing_requirements) == 1
    row = result.balancing_requirements[0]
    assert row.junction_obj is junction_map["N2"]
    assert row.branch_obj is segment_map["B"]
    assert row.junction_key == "N2"
    assert row.branch_key == "B"
    assert row.pressure_deficit_pa == 37.2
    assert row.required_k == 2.16


# ----------------------------------------------------------------------------
# Per-segment Velocity override
# ----------------------------------------------------------------------------

def test_segment_velocity_override_ignores_network_target_velocity():
    net, segment_map, _ = _two_node_tree(
        "Circular", diameter_mm=100.0, flow_lps=200.0, velocity_ms=8.0,
        net_extra_props=_sizing_props(method="ConstantVelocity", target_velocity=5.0, rounding_mm=10.0),
    )
    result = DuctSizer(net).solve()

    assert result.warnings == []
    sres = result.segments[0]
    expected_d_m = airflow.circular_diameter_for_velocity(airflow.lps_to_m3s(200.0), 8.0)
    expected_mm = _round_up(expected_d_m * 1000.0, 10.0)
    assert sres.new_diameter_mm == pytest.approx(expected_mm)
    # Sanity: the override diameter must differ from what the network's own 5.0 m/s target would give.
    unoverridden_d_m = airflow.circular_diameter_for_velocity(airflow.lps_to_m3s(200.0), 5.0)
    assert sres.new_diameter_mm != pytest.approx(_round_up(unoverridden_d_m * 1000.0, 10.0))


def test_segment_velocity_override_forces_constant_velocity_even_under_friction_rate_method():
    net, segment_map, _ = _two_node_tree(
        "Circular", diameter_mm=100.0, flow_lps=200.0, velocity_ms=8.0,
        net_extra_props=_sizing_props(method="ConstantFrictionRate", target_friction_rate=1.0, rounding_mm=10.0),
    )
    result = DuctSizer(net).solve()

    assert result.warnings == []
    sres = result.segments[0]
    expected_d_m = airflow.circular_diameter_for_velocity(airflow.lps_to_m3s(200.0), 8.0)
    expected_mm = _round_up(expected_d_m * 1000.0, 10.0)
    assert sres.new_diameter_mm == pytest.approx(expected_mm)


def test_no_segment_velocity_override_uses_network_default():
    net, segment_map, _ = _two_node_tree(
        "Circular", diameter_mm=100.0, flow_lps=200.0, velocity_ms=0.0,
        net_extra_props=_sizing_props(method="ConstantVelocity", target_velocity=5.0, rounding_mm=10.0),
    )
    result = DuctSizer(net).solve()

    sres = result.segments[0]
    expected_d_m = airflow.circular_diameter_for_velocity(airflow.lps_to_m3s(200.0), 5.0)
    expected_mm = _round_up(expected_d_m * 1000.0, 10.0)
    assert sres.new_diameter_mm == pytest.approx(expected_mm)


# ----------------------------------------------------------------------------
# Per-segment RectangularSizingMode / TargetAspectRatio override
# ----------------------------------------------------------------------------

def test_segment_mode_override_switches_from_network_aspect_ratio_to_fixed_height():
    # Network default is FixedAspectRatio, but this one segment is height-constrained
    # (e.g. a beam or ceiling) and overrides to FixedHeight with its own existing Height.
    net, segment_map, _ = _two_node_tree(
        "Rectangular", height_mm=280.0, flow_lps=300.0,
        rectangular_sizing_mode="FixedHeight",
        net_extra_props=_sizing_props(method="ConstantVelocity", target_velocity=6.0,
                                       rect_mode="FixedAspectRatio", aspect_ratio=2.0, rounding_mm=10.0),
    )
    result = DuctSizer(net).solve()

    assert result.warnings == []
    sres = result.segments[0]
    assert sres.new_height_mm == pytest.approx(280.0)  # held fixed, per the segment's own override


def test_segment_mode_override_switches_from_network_fixed_height_to_fixed_width():
    net, segment_map, _ = _two_node_tree(
        "Rectangular", width_mm=450.0, flow_lps=300.0,
        rectangular_sizing_mode="FixedWidth",
        net_extra_props=_sizing_props(method="ConstantVelocity", target_velocity=6.0,
                                       rect_mode="FixedHeight", default_height=300.0, rounding_mm=10.0),
    )
    result = DuctSizer(net).solve()

    assert result.warnings == []
    sres = result.segments[0]
    assert sres.new_width_mm == pytest.approx(450.0)  # held fixed, per the segment's own override


def test_segment_aspect_ratio_override_used_within_fixed_aspect_ratio_mode():
    net_default, _, _ = _two_node_tree(
        "Rectangular", flow_lps=300.0,
        net_extra_props=_sizing_props(method="ConstantVelocity", target_velocity=6.0,
                                       rect_mode="FixedAspectRatio", aspect_ratio=2.0, rounding_mm=10.0),
    )
    result_default = DuctSizer(net_default).solve()
    ratio_default = result_default.segments[0].new_width_mm / result_default.segments[0].new_height_mm

    net_override, _, _ = _two_node_tree(
        "Rectangular", flow_lps=300.0, target_aspect_ratio=3.5,
        net_extra_props=_sizing_props(method="ConstantVelocity", target_velocity=6.0,
                                       rect_mode="FixedAspectRatio", aspect_ratio=2.0, rounding_mm=10.0),
    )
    result_override = DuctSizer(net_override).solve()
    ratio_override = result_override.segments[0].new_width_mm / result_override.segments[0].new_height_mm

    assert ratio_default == pytest.approx(2.0, rel=0.15)
    assert ratio_override == pytest.approx(3.5, rel=0.15)


def test_no_segment_mode_override_uses_network_default():
    net, segment_map, _ = _two_node_tree(
        "Rectangular", height_mm=999.0, flow_lps=300.0,
        rectangular_sizing_mode="UseNetworkDefault",  # explicit, but same as default
        net_extra_props=_sizing_props(method="ConstantVelocity", target_velocity=6.0,
                                       rect_mode="FixedAspectRatio", aspect_ratio=2.0, rounding_mm=10.0),
    )
    result = DuctSizer(net).solve()

    sres = result.segments[0]
    # FixedAspectRatio mode solves both dimensions -- the segment's pre-existing
    # Height (999mm) must NOT be held fixed, since no per-segment override was set.
    assert sres.new_height_mm != pytest.approx(999.0)
    assert sres.new_width_mm / sres.new_height_mm == pytest.approx(2.0, rel=0.15)


# ----------------------------------------------------------------------------
# Static regain: sequential (parent-before-child) sizing
# ----------------------------------------------------------------------------
# Reuses the shared 3-segment tee tree: J1(root) --A(80 L/s)--> J2(tee)
#   J2 --B(50 L/s, 3m)--> J3(leaf)      J2 --C(30 L/s, 6m)--> J4(leaf)

def test_static_regain_first_segment_sized_directly_at_target_velocity():
    # Segment A leaves the source directly (its parent is the root/balancing
    # terminal) -- no upstream section exists yet, so it must be sized by
    # plain constant-velocity sizing at the network's TargetVelocity, not run
    # through the regain-balance equation.
    net, segment_map, _ = base_tree(
        net_extra_props=_sizing_props(method="StaticRegain", target_velocity=5.0,
                                       min_velocity=4.0, regain_factor=0.75, rounding_mm=0.0),
    )
    result = DuctSizer(net).solve()

    seg_a_result = next(s for s in result.segments if s.key == "A")
    assert seg_a_result.velocity_ms == pytest.approx(5.0)
    expected_d_m = airflow.circular_diameter_for_velocity(airflow.lps_to_m3s(80.0), 5.0)
    assert seg_a_result.new_diameter_mm == pytest.approx(expected_d_m * 1000.0)


def test_static_regain_propagates_actual_upstream_velocity_not_target_velocity():
    # Segment B's parent (J2) is downstream of segment A, so B must be sized
    # against segment A's own ACTUAL resolved velocity -- which is only the
    # same as TargetVelocity here because segment A isn't rounded/floor-
    # clamped; in general they can differ, and B must track the real value.
    # segB_len is shortened from the base_tree default so B's own regain
    # balance point isn't floor-clamped (a clamped result depends only on
    # flow/MinimumVelocity, not on the upstream velocity being propagated,
    # which would make this test unable to tell "actual" from "target").
    net, segment_map, _ = base_tree(
        segB_len=1000.0,
        net_extra_props=_sizing_props(method="StaticRegain", target_velocity=5.0,
                                       min_velocity=4.0, regain_factor=0.75, rounding_mm=0.0),
    )
    result = DuctSizer(net).solve()

    seg_a_result = next(s for s in result.segments if s.key == "A")
    seg_b_result = next(s for s in result.segments if s.key == "B")

    upstream_vp = airflow.velocity_pressure(AIR_DENSITY, seg_a_result.velocity_ms)
    expected_d_m, _balanced = airflow.circular_diameter_for_static_regain(
        airflow.lps_to_m3s(50.0), upstream_vp, 0.75, 1.0,
        airflow.mm_to_m(DEFAULT_ROUGHNESS_MM), AIR_VISCOSITY, AIR_DENSITY, 4.0
    )
    assert seg_b_result.new_diameter_mm == pytest.approx(expected_d_m * 1000.0)
    # Sanity: not floor-clamped, so this is actually exercising the regain balance.
    floor_d_m = airflow.circular_diameter_for_velocity(airflow.lps_to_m3s(50.0), 4.0)
    assert seg_b_result.new_diameter_mm < floor_d_m * 1000.0 - 1e-6


def test_static_regain_two_downstream_branches_use_same_upstream_reference():
    # B and C are both children of the same node (J2), so both must be
    # sized against the SAME upstream velocity (segment A's), even though
    # they carry different flows/lengths and end up different sizes.
    net, segment_map, _ = base_tree(
        net_extra_props=_sizing_props(method="StaticRegain", target_velocity=5.0,
                                       min_velocity=4.0, regain_factor=0.75, rounding_mm=0.0),
    )
    result = DuctSizer(net).solve()

    seg_a_result = next(s for s in result.segments if s.key == "A")
    seg_c_result = next(s for s in result.segments if s.key == "C")
    upstream_vp = airflow.velocity_pressure(AIR_DENSITY, seg_a_result.velocity_ms)
    expected_d_m, _balanced = airflow.circular_diameter_for_static_regain(
        airflow.lps_to_m3s(30.0), upstream_vp, 0.75, 6.0,
        airflow.mm_to_m(DEFAULT_ROUGHNESS_MM), AIR_VISCOSITY, AIR_DENSITY, 4.0
    )
    assert seg_c_result.new_diameter_mm == pytest.approx(expected_d_m * 1000.0)


def test_static_regain_segment_velocity_override_on_first_segment_propagates():
    # If segment A has its own Velocity override, it's sized at that value
    # instead of the network's TargetVelocity, and B/C must pick up A's
    # OVERRIDDEN resulting velocity as their own upstream reference.
    net, segment_map, _ = base_tree(
        net_extra_props=_sizing_props(method="StaticRegain", target_velocity=5.0,
                                       min_velocity=4.0, regain_factor=0.75, rounding_mm=0.0),
    )
    segment_map["A"].Velocity = 6.0  # override, different from network TargetVelocity
    result = DuctSizer(net).solve()

    seg_a_result = next(s for s in result.segments if s.key == "A")
    seg_b_result = next(s for s in result.segments if s.key == "B")
    assert seg_a_result.velocity_ms == pytest.approx(6.0)

    upstream_vp = airflow.velocity_pressure(AIR_DENSITY, 6.0)
    expected_d_m, _balanced = airflow.circular_diameter_for_static_regain(
        airflow.lps_to_m3s(50.0), upstream_vp, 0.75, 3.0,
        airflow.mm_to_m(DEFAULT_ROUGHNESS_MM), AIR_VISCOSITY, AIR_DENSITY, 4.0
    )
    assert seg_b_result.new_diameter_mm == pytest.approx(expected_d_m * 1000.0)


def test_static_regain_error_on_one_segment_does_not_crash_downstream():
    # Force an error on segment A (rectangular, FixedHeight mode, no
    # existing/default Height to hold fixed) and confirm B/C still get sized
    # (using the fallback TargetVelocity reference) instead of the whole
    # component aborting.
    net, segment_map, _ = base_tree(
        segA_kwargs={"profile": "Rectangular"},
        net_extra_props=_sizing_props(method="StaticRegain", target_velocity=5.0,
                                       min_velocity=4.0, regain_factor=0.75, rounding_mm=0.0,
                                       rect_mode="FixedHeight", default_height=0.0),
    )
    result = DuctSizer(net).solve()

    assert any("A" in w or "Height" in w for w in result.warnings)
    keys_sized = {s.key for s in result.segments}
    assert keys_sized == {"B", "C"}  # A failed and was skipped; B/C still solved


def test_static_regain_balanced_flag_true_and_no_warning_when_regain_achieved():
    # Both branches short enough that their own regain balance point comes
    # out faster than MinimumVelocity (i.e. not floor-clamped) -- the
    # base_tree defaults (3-6m branches) are long enough to hit the floor
    # (see test_static_regain_balanced_flag_false_and_warning_when_floor_clamped),
    # so both are shortened here to actually exercise a clean balance.
    net, segment_map, _ = base_tree(
        segB_len=1000.0, segC_len=1000.0,
        net_extra_props=_sizing_props(method="StaticRegain", target_velocity=5.0,
                                       min_velocity=4.0, regain_factor=0.75, rounding_mm=0.0),
    )
    result = DuctSizer(net).solve()

    assert all(s.regain_balanced for s in result.segments)
    assert not any("balanc" in w.lower() for w in result.warnings)


def test_static_regain_balanced_flag_false_and_warning_when_floor_clamped():
    # The classic static-regain failure mode (see the module docstring in
    # airflow.py): even at the slowest/largest duct MinimumVelocity allows,
    # regain still can't offset this section's own friction -- the
    # base_tree defaults (a 30 L/s, 6m branch off a 5 m/s trunk) already
    # land in this regime.
    net, segment_map, _ = base_tree(
        net_extra_props=_sizing_props(method="StaticRegain", target_velocity=5.0,
                                       min_velocity=4.0, regain_factor=0.75, rounding_mm=0.0),
    )
    result = DuctSizer(net).solve()

    seg_c_result = next(s for s in result.segments if s.key == "C")
    assert seg_c_result.regain_balanced is False
    assert seg_c_result.velocity_ms == pytest.approx(4.0)  # clamped to MinimumVelocity

    assert any("C" in w and "balanc" in w.lower() for w in result.warnings)

    # Segment A (the first section) is sized by plain constant velocity, not
    # regain -- it's trivially "balanced" (not applicable) regardless.
    seg_a_result = next(s for s in result.segments if s.key == "A")
    assert seg_a_result.regain_balanced is True


# ----------------------------------------------------------------------------
# Static regain: junction fitting-loss iteration
# ----------------------------------------------------------------------------

def test_static_regain_accounts_for_junction_fitting_loss_from_proposed_sizes(monkeypatch):
    # A tee with a nonzero fitting-loss coefficient: the downstream branch's
    # regain must now offset both its own friction AND the tee's own
    # takeoff loss, so it comes out sized bigger (slower) than with no
    # fitting loss at all.
    fitting_k = 0.1

    class _FixedKTypeDef:
        pass

    class _FixedKRegistry:
        def resolve_type(self, library_id, type_id):
            return _FixedKTypeDef() if type_id == "branch_tee_generic" else None

        def call_loss(self, library_id, type_def, context):
            return legacy_loss_result(fitting_k, context)

    monkeypatch.setattr(
        duct_sizer_mod.hvaclib.HVACLibraryService,
        "get_hvac_library_registry",
        staticmethod(lambda: _FixedKRegistry()),
    )

    net, segment_map, _ = base_tree(
        segB_len=1000.0,
        net_extra_props=_sizing_props(method="StaticRegain", target_velocity=5.0,
                                       min_velocity=4.0, regain_factor=0.75, rounding_mm=0.0),
    )
    result = DuctSizer(net).solve()
    seg_b_result = next(s for s in result.segments if s.key == "B")

    # Self-consistency: the final size must (closely) satisfy the balance
    # equation using the fitting loss computed from its OWN final velocity
    # -- i.e. the iteration actually converged, not just ran once.
    upstream_vp = airflow.velocity_pressure(AIR_DENSITY, 5.0)  # segment A: ConstantVelocity at TargetVelocity
    fitting_loss_pa = fitting_k * airflow.velocity_pressure(AIR_DENSITY, seg_b_result.velocity_ms)
    expected_d_m, balanced = airflow.circular_diameter_for_static_regain(
        airflow.lps_to_m3s(50.0), upstream_vp, 0.75, 1.0,
        airflow.mm_to_m(DEFAULT_ROUGHNESS_MM), AIR_VISCOSITY, AIR_DENSITY, 4.0,
        fitting_loss_pa=fitting_loss_pa,
    )
    assert balanced is True
    assert seg_b_result.new_diameter_mm == pytest.approx(expected_d_m * 1000.0, abs=1.0)

    # Bigger than the equivalent solve with no fitting loss at all.
    d_no_loss_m, _balanced = airflow.circular_diameter_for_static_regain(
        airflow.lps_to_m3s(50.0), upstream_vp, 0.75, 1.0,
        airflow.mm_to_m(DEFAULT_ROUGHNESS_MM), AIR_VISCOSITY, AIR_DENSITY, 4.0,
    )
    assert seg_b_result.new_diameter_mm > d_no_loss_m * 1000.0


def test_static_regain_falls_back_to_k_default_for_unresolved_junction_type(monkeypatch):
    # Mirrors AirflowSolver.py: a real fitting (degree >= 2) whose type
    # can't even be resolved still gets the generic K_DEFAULT fallback,
    # rather than being treated as zero loss.
    from freecad.HVAC.core.AirflowSolver import K_DEFAULT

    class _UnresolvedRegistry:
        def resolve_type(self, library_id, type_id):
            return None

        def call_loss(self, library_id, type_def, context):
            return None

    monkeypatch.setattr(
        duct_sizer_mod.hvaclib.HVACLibraryService,
        "get_hvac_library_registry",
        staticmethod(lambda: _UnresolvedRegistry()),
    )

    net, segment_map, _ = base_tree(
        segB_len=1000.0,
        net_extra_props=_sizing_props(method="StaticRegain", target_velocity=5.0,
                                       min_velocity=4.0, regain_factor=0.75, rounding_mm=0.0),
    )
    result = DuctSizer(net).solve()
    seg_b_result = next(s for s in result.segments if s.key == "B")

    upstream_vp = airflow.velocity_pressure(AIR_DENSITY, 5.0)
    fitting_loss_pa = K_DEFAULT * airflow.velocity_pressure(AIR_DENSITY, seg_b_result.velocity_ms)
    expected_d_m, _balanced = airflow.circular_diameter_for_static_regain(
        airflow.lps_to_m3s(50.0), upstream_vp, 0.75, 1.0,
        airflow.mm_to_m(DEFAULT_ROUGHNESS_MM), AIR_VISCOSITY, AIR_DENSITY, 4.0,
        fitting_loss_pa=fitting_loss_pa,
    )
    assert seg_b_result.new_diameter_mm == pytest.approx(expected_d_m * 1000.0, abs=1.0)


def _three_node_chain(segB_len=1000.0, net_extra_props=None):
    """J1 (balancing terminal) --A(5000mm)--> J2 (degree-2, e.g. an elbow) --B(segB_len)--> J3 (leaf, 50 L/s)."""
    node_ports = {
        1: [("A", "start")],
        2: [("A", "end"), ("B", "start")],
        3: [("B", "end")],
    }
    edge_endpoints = {"A": (1, 2), "B": (2, 3)}
    parser = FakeParser(node_ports, edge_endpoints)
    segment_map = {
        "A": make_segment("A", 200.0, 5000.0),
        "B": make_segment("B", 150.0, segB_len),
    }
    junction_map = {
        "N1": make_junction("J1", design_flow=0.0, type_id="end_terminal_marker"),
        "N2": make_junction("J2", design_flow=0.0, type_id="through_elbow_generic"),
        "N3": make_junction("J3", design_flow=50.0, type_id="end_terminal_marker"),
    }
    net = make_net(parser, segment_map, junction_map, **(net_extra_props or {}))
    return net, segment_map, junction_map


def test_static_regain_ignores_fitting_loss_at_inline_degree_two_node(monkeypatch):
    # A degree-2 node (e.g. an elbow) is not a branch -- there's no sibling
    # to balance against, so its own fitting loss must NOT be folded into
    # segment B's regain target, even if the registry reports a large K.
    class _BigKTypeDef:
        pass

    class _BigKRegistry:
        def resolve_type(self, library_id, type_id):
            return _BigKTypeDef()

        def call_loss(self, library_id, type_def, context):
            return legacy_loss_result(5.0, context)  # deliberately large -- would clamp/inflate sizing if it were included

    monkeypatch.setattr(
        duct_sizer_mod.hvaclib.HVACLibraryService,
        "get_hvac_library_registry",
        staticmethod(lambda: _BigKRegistry()),
    )

    net, segment_map, _ = _three_node_chain(
        segB_len=1000.0,
        net_extra_props=_sizing_props(method="StaticRegain", target_velocity=5.0,
                                       min_velocity=4.0, regain_factor=0.75, rounding_mm=0.0),
    )
    result = DuctSizer(net).solve()
    seg_b_result = next(s for s in result.segments if s.key == "B")

    upstream_vp = airflow.velocity_pressure(AIR_DENSITY, 5.0)
    expected_d_m, balanced = airflow.circular_diameter_for_static_regain(
        airflow.lps_to_m3s(50.0), upstream_vp, 0.75, 1.0,
        airflow.mm_to_m(DEFAULT_ROUGHNESS_MM), AIR_VISCOSITY, AIR_DENSITY, 4.0,
    )
    assert balanced is True
    assert seg_b_result.new_diameter_mm == pytest.approx(expected_d_m * 1000.0)



# test_sizes_converged_helper/test_section_params_from_result_helper used to
# live here as white-box tests of DuctSizer.py's own internal helpers --
# both moved (as analysis.sizing._sizes_converged, and, for the section
# case, simply SegmentSizeResult.new_section's own SectionModel fields, with
# no separate dict-conversion helper needed anymore) -- see
# tests/test_analysis_sizing.py.
