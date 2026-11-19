"""
Pure tests for freecad.HVAC.analysis.paths -- no FreeCAD/conftest stubbing
needed, since analysis/ has no FreeCAD dependency at all.
"""

import pytest

from analysis_fixtures import base_tree

from freecad.HVAC.analysis import flow
from freecad.HVAC.analysis.pressure import PressureSolver

FITTING_K = 0.5


def _solve(net):
    components, flow_warnings = flow.solve_flow_components(net)
    assert flow_warnings == []
    trees, warnings = PressureSolver().solve(net, components)
    assert warnings == []
    return trees[0]


def test_every_non_root_terminal_gets_its_own_path():
    tree = _solve(base_tree(loss_evaluator=lambda pv: FITTING_K))
    terminal_ids = {p.terminal_node_id for p in tree.paths}
    assert terminal_ids == {"N3", "N4"}  # N1 (the balancing terminal itself) is excluded


def test_path_edges_and_nodes_are_root_to_terminal_ordered():
    tree = _solve(base_tree(loss_evaluator=lambda pv: FITTING_K))
    path_b = next(p for p in tree.paths if p.terminal_node_id == "N3")
    assert path_b.node_ids == ["N1", "N2", "N3"]
    assert path_b.edge_keys == ["A", "B"]


def test_path_loss_breakdown_matches_segment_totals():
    tree = _solve(base_tree(loss_evaluator=lambda pv: FITTING_K))
    path_c = next(p for p in tree.paths if p.terminal_node_id == "N4")

    segA, segC = tree.segments["A"], tree.segments["C"]
    assert path_c.loss.duct_friction_pa == pytest.approx(segA.friction_loss_pa + segC.friction_loss_pa)
    # A is the only intermediate (non-terminal) segment on this path.
    assert path_c.loss.junction_pa == pytest.approx(segA.junction_loss_pa)
    # C is the terminal segment -- its own junction contribution is
    # reported separately as terminal_pa, not folded into junction_pa.
    assert path_c.loss.terminal_pa == pytest.approx(segC.junction_loss_pa)
    assert path_c.loss.total_pa == pytest.approx(segA.total_loss_pa + segC.total_loss_pa)


def test_critical_path_is_the_largest_loss_and_deficits_are_relative_to_it():
    # A much longer branch C means more friction there, making it critical.
    net = base_tree(segB_len=1000.0, segC_len=20000.0, loss_evaluator=lambda pv: FITTING_K)
    tree = _solve(net)

    assert tree.critical_path.terminal_node_id == "N4"
    critical_total = tree.critical_path.path.loss.total_pa

    path_b = next(p for p in tree.paths if p.terminal_node_id == "N3")
    path_c = next(p for p in tree.paths if p.terminal_node_id == "N4")
    assert path_c.pressure_deficit_pa == 0.0
    assert path_b.pressure_deficit_pa == critical_total - path_b.loss.total_pa
    assert path_b.pressure_deficit_pa > 0.0
