"""
Pure tests for freecad.HVAC.analysis.balancing -- no FreeCAD/conftest
stubbing needed, since analysis/ has no FreeCAD dependency at all.
"""

from analysis_fixtures import base_tree

from freecad.HVAC.analysis import flow
from freecad.HVAC.analysis.balancing import PressureBalanceCoordinator
from freecad.HVAC.analysis.model import SizingSettings
from freecad.HVAC.analysis.pressure import PressureSolver
from freecad.HVAC.analysis.sizing import LocalStaticRegainSizer


def _components(net):
    components, warnings = flow.solve_flow_components(net)
    assert warnings == []
    return components


def _max_deficit(net, sections):
    working_net = net.with_segment_sections(sections)
    trees, warnings = PressureSolver().solve(working_net, _components(working_net))
    assert warnings == []
    return max(p.pressure_deficit_pa for p in trees[0].paths)


def _imbalanced_tree(j3_flow=50.0, j4_flow=50.0):
    # B is short (little friction, so its path is naturally "too easy"
    # relative to the AHU's required total pressure) while C is very long
    # (naturally the critical path) -- classic static-regain imbalance.
    return base_tree(
        j3_flow=j3_flow, j4_flow=j4_flow, segB_dia=200.0, segC_dia=200.0,
        segA_dia=300.0, segB_len=500.0, segC_len=30000.0, loss_evaluator=lambda pv: 0.0,
    )


def test_balancing_reduces_the_worst_path_deficit():
    net = _imbalanced_tree()
    settings = SizingSettings(
        method="StaticRegain", target_velocity_ms=5.0, min_velocity_ms=2.5, regain_factor=0.75,
        rounding_mm=0.0, balance_tolerance_pa=5.0, balance_max_iterations=15,
    )
    components = _components(net)

    base = LocalStaticRegainSizer().size(net, components, settings)
    base_sections = {edge_key: r.new_section for edge_key, r in base.segments.items()}
    base_deficit = _max_deficit(net, base_sections)

    result = PressureBalanceCoordinator().size(net, components, settings)
    final_sections = {edge_key: r.new_section for edge_key, r in result.segments.items()}
    final_deficit = _max_deficit(net, final_sections)

    assert final_deficit < base_deficit
    # Balancing must only ever shrink the easy branch (B), never touch the
    # critical one (C) -- it has nothing to gain by making the worst path
    # worse.
    assert result.segments["B"].new_section.diameter_mm < base.segments["B"].new_section.diameter_mm
    assert result.segments["C"].new_section.diameter_mm == base.segments["C"].new_section.diameter_mm


def test_balancing_reports_a_requirement_when_it_cant_fully_close_the_gap():
    net = _imbalanced_tree()
    settings = SizingSettings(
        method="StaticRegain", target_velocity_ms=5.0, min_velocity_ms=2.5, regain_factor=0.75,
        rounding_mm=0.0, balance_tolerance_pa=0.01,  # near-zero tolerance -- forces the velocity ceiling to bind
        balance_max_iterations=15,
    )
    result = PressureBalanceCoordinator().size(net, _components(net), settings)

    assert len(result.balancing_requirements) == 1
    req = result.balancing_requirements[0]
    assert req.junction_id == "N2"
    assert req.branch_port == "B"
    assert req.pressure_deficit_pa > 0.0
    assert req.required_k > 0.0


def test_balanced_network_needs_no_requirement():
    # A generous tolerance means the base sizer's own result is already
    # "close enough" -- no adjustment, no requirement.
    net = base_tree(loss_evaluator=lambda pv: 0.0)
    settings = SizingSettings(
        method="StaticRegain", target_velocity_ms=5.0, min_velocity_ms=2.5, regain_factor=0.75,
        rounding_mm=0.0, balance_tolerance_pa=1e6, balance_max_iterations=5,
    )
    result = PressureBalanceCoordinator().size(net, _components(net), settings)

    assert result.balancing_requirements == []
    assert not any("Pressure balancing" in w for w in result.warnings)


# ----------------------------------------------------------------------------
# Sizing sections win over balancing (owner decision, 13 November 2026)
# ----------------------------------------------------------------------------


def _imbalanced_tree_with_bent_branch():
    """_imbalanced_tree() with the easy branch B drawn as B1 -- bend N5 -- B2 (one sizing section)."""
    from analysis_fixtures import circular_section, port, primary

    from freecad.HVAC.analysis.model import NodeModel, SegmentModel

    net = _imbalanced_tree()
    seg_b = net.segments.pop("B")
    del net.edges["B"]
    net.segments["B1"] = SegmentModel("B1", circular_section(200.0), seg_b.length_mm / 2.0, seg_b.roughness_mm)
    net.segments["B2"] = SegmentModel("B2", circular_section(200.0), seg_b.length_mm / 2.0, seg_b.roughness_mm)
    net.edges["B1"] = ("N2", "N5")
    net.edges["B2"] = ("N5", "N3")
    n2_ports = [port("A", "N2", True), port("B1", "N2", False), port("C", "N2", False)]
    net.nodes["N2"].ports = n2_ports
    net.nodes["N2"].primary_component = primary("N2", n2_ports)
    n5_ports = [port("B1", "N5", True), port("B2", "N5", False)]
    net.nodes["N5"] = NodeModel(
        "N5", "through", 2, n5_ports, 0.0, family="bend", primary_component=primary("N5", n5_ports)
    )
    n3_ports = [port("B2", "N3", True)]
    net.nodes["N3"].ports = n3_ports
    net.nodes["N3"].primary_component = primary("N3", n3_ports)
    return net


def _balancing_settings(**extra):
    values = dict(
        method="StaticRegain", target_velocity_ms=5.0, min_velocity_ms=2.5, regain_factor=0.75,
        rounding_mm=0.0, balance_tolerance_pa=5.0, balance_max_iterations=15,
    )
    values.update(extra)
    return SizingSettings(**values)


def test_balancing_shrinks_a_whole_sizing_section_never_one_member():
    net = _imbalanced_tree_with_bent_branch()
    components = _components(net)
    base = LocalStaticRegainSizer().size(net, components, _balancing_settings())
    assert ["B1", "B2"] in base.sections

    result = PressureBalanceCoordinator().size(net, components, _balancing_settings())
    b1 = result.segments["B1"].new_section.diameter_mm
    assert b1 < base.segments["B1"].new_section.diameter_mm
    assert result.segments["B2"].new_section.diameter_mm == b1
    assert result.segments["C"].new_section.diameter_mm == base.segments["C"].new_section.diameter_mm
    assert ["B1", "B2"] in result.sections


def test_a_section_shared_with_the_critical_path_is_not_shrunk_but_reported():
    # The tee's run (A -> B) is one section when the main keeps its size through the takeoff,
    # and A carries the critical path to C: shrinking B would mean shrinking A too.
    net = _imbalanced_tree()
    net.nodes["N2"].family = "tee"
    net.nodes["N2"].run_edge_pairs = [("A", "B")]
    settings = _balancing_settings(size_change_policy="AtInlineNodesOnly")
    components = _components(net)
    base = LocalStaticRegainSizer().size(net, components, settings)
    assert ["A", "B"] in base.sections

    result = PressureBalanceCoordinator().size(net, components, settings)
    for edge_key in ("A", "B", "C"):
        assert result.segments[edge_key].new_section == base.segments[edge_key].new_section
    assert [req.branch_port for req in result.balancing_requirements] == ["B"]


def test_balancing_keeps_the_base_sizers_reducer_advice():
    net = _imbalanced_tree()
    net.nodes["N2"].family = "tee"
    net.nodes["N2"].run_edge_pairs = [("A", "B")]
    settings = _balancing_settings(size_change_policy="AtInlineNodesOnly", reducer_advice_area_ratio=1.25)
    components = _components(net)
    base = LocalStaticRegainSizer().size(net, components, settings)
    assert base.reducer_suggestions  # B carries 50 of A's 100 L/s on A's size
    result = PressureBalanceCoordinator().size(net, components, settings)
    assert result.reducer_suggestions == base.reducer_suggestions
