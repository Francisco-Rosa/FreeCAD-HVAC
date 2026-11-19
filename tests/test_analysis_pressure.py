"""
Pure tests for freecad.HVAC.analysis.pressure -- no FreeCAD/conftest
stubbing needed, since analysis/ has no FreeCAD dependency at all.
"""

import pytest

from analysis_fixtures import AIR_DENSITY, AIR_VISCOSITY, DEFAULT_ROUGHNESS_MM, base_tree, converging_tree

from freecad.HVAC.analysis import flow, physics
from freecad.HVAC.analysis.loss import LossEvaluation, LossPath, LossStatus
from freecad.HVAC.analysis.pressure import K_DEFAULT, PressureSolver

FITTING_K = 0.5


def _expected_segment(diameter_mm, length_mm, flow_lps):
    d_m = physics.mm_to_m(diameter_mm)
    area = physics.circular_area(d_m)
    dh = physics.hydraulic_diameter_circular(d_m)
    v = physics.velocity_from_flow(physics.lps_to_m3s(flow_lps), area)
    re = physics.reynolds_number(v, dh, AIR_VISCOSITY)
    rel_rough = physics.mm_to_m(DEFAULT_ROUGHNESS_MM) / dh
    f = physics.friction_factor_altshul_tsal(re, rel_rough)
    friction = physics.darcy_weisbach_pressure_loss(f, physics.mm_to_m(length_mm), dh, AIR_DENSITY, v)
    return v, re, friction


def _solve(net):
    components, flow_warnings = flow.solve_flow_components(net)
    assert flow_warnings == []
    trees, warnings = PressureSolver().solve(net, components)
    return trees[0], warnings


def test_flow_velocity_friction_match_independent_oracle():
    net = base_tree(loss_evaluator=lambda pv: FITTING_K)
    tree, warnings = _solve(net)
    assert warnings == []

    segA, segB, segC = tree.segments["A"], tree.segments["B"], tree.segments["C"]
    assert segA.flow_lps == 80.0 and segB.flow_lps == 50.0 and segC.flow_lps == 30.0

    vA, reA, frA = _expected_segment(200.0, 5000.0, 80.0)
    vB, reB, frB = _expected_segment(150.0, 3000.0, 50.0)
    vC, reC, frC = _expected_segment(150.0, 6000.0, 30.0)

    # Friction is rate x length now, so it may differ in the last bit from
    # Darcy-Weisbach evaluated with the length inside.
    assert segA.velocity_ms == vA and segA.reynolds == reA and segA.friction_loss_pa == pytest.approx(frA, rel=1e-12)
    assert segB.velocity_ms == vB and segB.friction_loss_pa == pytest.approx(frB, rel=1e-12)
    assert segC.velocity_ms == vC and segC.friction_loss_pa == pytest.approx(frC, rel=1e-12)

    # This particular fixture's tee is diverging (A common inlet, B/C
    # outlets), so its fixed K lands on the two outlet ports only -- a
    # converging tee's own distinct K's land on its INLET legs instead
    # (see test_converging_tee_* below), not "inlets never get a fitting
    # loss" as a general rule.
    assert segA.junction_loss_pa == 0.0
    assert segB.junction_loss_pa == FITTING_K * physics.velocity_pressure(AIR_DENSITY, vB)
    assert segC.junction_loss_pa == FITTING_K * physics.velocity_pressure(AIR_DENSITY, vC)
    assert tree.junctions["N2"].warning == ""  # a real K was found -- no fallback warning


def test_static_pressure_propagates_from_balancing_terminal():
    net = base_tree(loss_evaluator=lambda pv: FITTING_K)
    tree, _ = _solve(net)

    frA = tree.segments["A"].friction_loss_pa
    assert tree.junctions["N1"].static_pressure_pa == 0.0  # the reference point
    p_j2 = -frA
    assert tree.junctions["N2"].static_pressure_pa == p_j2
    p_j3 = p_j2 - tree.segments["B"].total_loss_pa
    p_j4 = p_j2 - tree.segments["C"].total_loss_pa
    assert tree.junctions["N3"].static_pressure_pa == p_j3
    assert tree.junctions["N4"].static_pressure_pa == p_j4


def test_missing_loss_data_falls_back_to_k_default_with_warning():
    # No loss_evaluator on J2's Primary at all -- a real branch (degree 3)
    # always has SOME physical loss, so K_DEFAULT applies with a warning
    # (unlike a degree-1 terminal, where "no loss" is the normal case).
    net = base_tree(loss_evaluator=None)
    tree, warnings = _solve(net)

    vB = tree.segments["B"].velocity_ms
    vC = tree.segments["C"].velocity_ms
    assert tree.segments["B"].junction_loss_pa == K_DEFAULT * physics.velocity_pressure(AIR_DENSITY, vB)
    assert tree.segments["C"].junction_loss_pa == K_DEFAULT * physics.velocity_pressure(AIR_DENSITY, vC)
    assert len(warnings) == 1
    assert "K_DEFAULT" not in warnings[0]  # human-readable message, not the raw constant name
    assert "N2" in warnings[0]
    assert tree.junctions["N2"].warning == warnings[0]


def test_terminal_with_no_loss_evaluator_gets_no_fallback_warning():
    # Degree-1 terminals (J1/J3/J4) never get a loss_evaluator in base_tree()
    # -- confirm they produce NO warning (matching a real, un-modeled
    # end_terminal_marker), unlike a real branch node.
    net = base_tree(loss_evaluator=lambda pv: FITTING_K)
    tree, warnings = _solve(net)

    assert warnings == []
    assert tree.junctions["N1"].warning == ""
    assert tree.junctions["N3"].warning == ""
    assert tree.junctions["N4"].warning == ""


def test_per_port_dict_loss_result_attributes_distinct_coefficients():
    # A dict loss result (one K per outlet port) lets sibling branches carry
    # different coefficients, unlike a single uniform float.
    k_by_edge = {"B": 0.2, "C": 0.6}
    net = base_tree(loss_evaluator=lambda pv: dict(k_by_edge))
    tree, warnings = _solve(net)
    assert warnings == []

    vB = tree.segments["B"].velocity_ms
    vC = tree.segments["C"].velocity_ms
    assert tree.segments["B"].junction_loss_pa == 0.2 * physics.velocity_pressure(AIR_DENSITY, vB)
    assert tree.segments["C"].junction_loss_pa == 0.6 * physics.velocity_pressure(AIR_DENSITY, vC)


def test_component_result_retains_distinct_per_leg_k_for_a_multiport_tee():
    # N2's tee has 3 real ports (A inlet, B/C outlets) -- its own retained
    # ComponentResult must carry one entry per outlet, each with its own K,
    # never a single collapsed scalar (see analysis/pressure.py's
    # ComponentPortResult/ComponentResult docstrings).
    k_by_edge = {"B": 0.18, "C": 1.05}
    net = base_tree(loss_evaluator=lambda pv: dict(k_by_edge))
    tree, warnings = _solve(net)
    assert warnings == []

    cres = tree.components["N2_Primary"]
    assert set(cres.port_results.keys()) == {"B", "C"}
    assert cres.port_results["B"].loss_coefficient == 0.18
    assert cres.port_results["C"].loss_coefficient == 1.05
    # This dict-of-legacy-K result only ever references B/C (this
    # fixture's diverging tee's own two outlets) -- A has no entry because
    # nothing referenced it, not because an inlet is structurally
    # forbidden from receiving one (see test_converging_tee_* below, where
    # the inlet legs are exactly the ones that get an entry).
    assert "A" not in cres.port_results


def test_component_port_result_static_pressure_derived_per_leg_not_copied_from_node():
    # Each outlet leg's own static pressure = the node's single common
    # value minus that SAME leg's own already-retained pressure_drop_pa --
    # a real per-leg derivation, not the node's value blindly copied onto
    # every port (which would show the same number for both legs).
    k_by_edge = {"B": 0.2, "C": 0.6}
    net = base_tree(loss_evaluator=lambda pv: dict(k_by_edge))
    tree, _ = _solve(net)

    node_static = tree.junctions["N2"].static_pressure_pa
    cres = tree.components["N2_Primary"]
    assert cres.port_results["B"].static_pressure_pa == node_static - cres.port_results["B"].pressure_drop_pa
    assert cres.port_results["C"].static_pressure_pa == node_static - cres.port_results["C"].pressure_drop_pa
    # Different K on each leg -> different pressure_drop_pa -> genuinely
    # different static pressure per leg, not the same value at both.
    assert cres.port_results["B"].static_pressure_pa != cres.port_results["C"].static_pressure_pa


def test_component_port_result_pressure_drop_matches_segment_loss_exactly():
    # The retained ComponentPortResult must be a record of exactly what was
    # already added onto the segment's own junction_loss_pa -- never a
    # second, independently-computed value (which could silently drift or
    # double count).
    k_by_edge = {"B": 0.2, "C": 0.6}
    net = base_tree(loss_evaluator=lambda pv: dict(k_by_edge))
    tree, _ = _solve(net)

    cres = tree.components["N2_Primary"]
    assert cres.port_results["B"].pressure_drop_pa == tree.segments["B"].junction_loss_pa
    assert cres.port_results["C"].pressure_drop_pa == tree.segments["C"].junction_loss_pa
    assert cres.port_results["B"].velocity_ms == tree.segments["B"].velocity_ms
    assert cres.port_results["B"].flow_lps == tree.segments["B"].flow_lps


def test_component_result_records_each_outlet_for_a_uniform_float_k():
    # A uniform (non-dict) K is applied identically to every outlet port by
    # the solver -- the retained ComponentResult must still carry one
    # ComponentPortResult per outlet (not one merged value), migrating the
    # old scalar-only Inline-component representation onto the same
    # per-port architecture a dict result already used.
    net = base_tree(loss_evaluator=lambda pv: FITTING_K)
    tree, warnings = _solve(net)
    assert warnings == []

    cres = tree.components["N2_Primary"]
    assert set(cres.port_results.keys()) == {"B", "C"}
    assert cres.port_results["B"].loss_coefficient == FITTING_K
    assert cres.port_results["C"].loss_coefficient == FITTING_K
    assert cres.port_results["B"].pressure_drop_pa == tree.segments["B"].junction_loss_pa


def test_component_result_is_always_present_but_empty_when_no_loss_applies():
    # N1 is a degree-1 terminal with no loss_evaluator at all -- "no loss" is
    # the expected, normal case there. Its ComponentResult must still exist
    # (not be omitted), with an empty port_results, so a caller can always
    # rely on every component's own result being freshly replaced each
    # solve (see ComponentResult's own docstring on why this matters for
    # clearing stale data).
    net = base_tree(loss_evaluator=lambda pv: FITTING_K)
    tree, _ = _solve(net)

    assert "N1_Primary" in tree.components
    assert tree.components["N1_Primary"].port_results == {}


def _converging_evaluator(k_branch, k_straight, status=LossStatus.EXACT, warning=None):
    """A LossEvaluation directly, with each inlet leg (B, C) referenced to
    its own velocity and directed into the common outlet (A) -- exactly
    what a real converging-tee library formula (loss_api.branch_loss)
    returns, see LossPath's own from/to semantics."""
    def evaluate(pv):
        return LossEvaluation(
            paths=[
                LossPath(from_edge_key="B", to_edge_key="A", reference_edge_key="B", loss_coefficient=k_branch),
                LossPath(from_edge_key="C", to_edge_key="A", reference_edge_key="C", loss_coefficient=k_straight),
            ],
            status=status, warning=warning,
        )
    return evaluate


def test_converging_tee_attributes_distinct_k_to_each_inlet_leg():
    # The two physically distinct coefficients of a converging (merging)
    # tee belong to its INLET legs (B, C), not its single outlet (A) -- the
    # exact shape the old outlet-only convention couldn't represent.
    net = converging_tree(loss_evaluator=_converging_evaluator(0.2, 0.6))
    tree, warnings = _solve(net)
    assert warnings == []

    vB = tree.segments["B"].velocity_ms
    vC = tree.segments["C"].velocity_ms
    assert tree.segments["A"].junction_loss_pa == 0.0
    assert tree.segments["B"].junction_loss_pa == 0.2 * physics.velocity_pressure(AIR_DENSITY, vB)
    assert tree.segments["C"].junction_loss_pa == 0.6 * physics.velocity_pressure(AIR_DENSITY, vC)

    cres = tree.components["N2_Primary"]
    assert set(cres.port_results.keys()) == {"B", "C"}
    assert cres.port_results["B"].from_edge_key == "B" and cres.port_results["B"].to_edge_key == "A"
    assert cres.port_results["C"].from_edge_key == "C" and cres.port_results["C"].to_edge_key == "A"
    assert cres.port_results["B"].status == "exact"


def test_converging_tee_static_pressure_sign_is_correct_for_inlet_legs():
    # This is the actual bug this refactor fixes: Phase G used to do
    # `static_pressure[node] - pressure_drop_pa` for EVERY port result,
    # which is only correct for a downstream/outlet leg. An inlet leg's
    # own static pressure must be HIGHER than the node's shared reference
    # (pressure is lost crossing the fitting toward the node), so the sign
    # must flip to `+` there instead.
    net = converging_tree(loss_evaluator=_converging_evaluator(0.2, 0.6))
    tree, _ = _solve(net)

    node_static = tree.junctions["N2"].static_pressure_pa
    cres = tree.components["N2_Primary"]
    b_result = cres.port_results["B"]
    c_result = cres.port_results["C"]

    assert b_result.static_pressure_pa == node_static + b_result.pressure_drop_pa
    assert c_result.static_pressure_pa == node_static + c_result.pressure_drop_pa
    # Different K on each inlet leg -> different pressure_drop_pa ->
    # genuinely different static pressure per leg.
    assert b_result.static_pressure_pa != c_result.static_pressure_pa

    # Cross-check against the independent, already-tested Phase F node
    # walk: N3 (upstream of B) must equal N2's static pressure plus B's
    # OWN full segment loss (friction + this same fitting loss) -- exactly
    # what a `+` sign at the port level should be consistent with.
    assert tree.junctions["N3"].static_pressure_pa == node_static + tree.segments["B"].total_loss_pa


def test_unsupported_loss_topology_falls_back_with_explicit_fallback_status():
    # UNSUPPORTED (a real LossEvaluation the library returned, e.g. for a
    # true mixed cross) must trigger the same generic-K policy as a
    # missing evaluator entirely -- but the per-port result must be
    # tagged FALLBACK, never silently indistinguishable from a real
    # library value (status == "exact"/"approximation").
    net = converging_tree(loss_evaluator=lambda pv: LossEvaluation(paths=[], status=LossStatus.UNSUPPORTED))
    tree, warnings = _solve(net)

    assert len(warnings) == 1
    assert "N2" in warnings[0]
    # UNSUPPORTED has no real paths to consult for direction, so the
    # solver's own synthesized fallback keeps applying to outlet legs
    # (see resolve_loss_evaluation) -- here that's just A.
    cres = tree.components["N2_Primary"]
    assert set(cres.port_results.keys()) == {"A"}
    assert cres.port_results["A"].status == "fallback"
    assert cres.port_results["A"].loss_coefficient == K_DEFAULT


def test_explicit_fallback_status_from_a_resolved_evaluation_is_preserved():
    # A type-declared fallback (e.g. loss_cross_generic's own
    # uniform_fallback_loss) is a RESOLVED LossEvaluation, not None/
    # UNSUPPORTED -- resolve_loss_evaluation must pass its FALLBACK status
    # straight through without re-synthesizing K_DEFAULT on top of it, and
    # without raising a second "no fitting-loss data" warning (it already
    # has real paths).
    net = converging_tree(loss_evaluator=_converging_evaluator(0.75, 0.75, status=LossStatus.FALLBACK))
    tree, warnings = _solve(net)

    assert warnings == []
    cres = tree.components["N2_Primary"]
    assert cres.port_results["B"].status == "fallback"
    assert cres.port_results["B"].loss_coefficient == 0.75
    assert tree.junctions["N2"].warning == ""


def test_missing_duct_size_is_reported_as_a_warning_not_raised():
    net = base_tree()
    net.segments["A"].section.diameter_mm = 0.0

    components, flow_warnings = flow.solve_flow_components(net)
    assert flow_warnings == []
    trees, warnings = PressureSolver().solve(net, components)

    assert trees == []
    assert len(warnings) == 1
    assert "duct dimensions" in warnings[0]
