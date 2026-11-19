# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the HVAC addon.

"""
Sizing sections (roadmap Stage 8, item 1): which segments must share one
size because no reducer can sit between them, and how the sizers apply that.
Pure analysis code -- no FreeCAD stubs needed.
"""

import pytest
from analysis_fixtures import base_tree, circular_section, port

from freecad.HVAC.analysis import flow, physics
from freecad.HVAC.analysis.model import NetworkModel, NodeModel, SectionModel, SegmentModel, SizingSettings
from freecad.HVAC.analysis.sizing import (
    ConstantFrictionRateSizer,
    ConstantVelocitySizer,
    LocalStaticRegainSizer,
    sizing_sections,
)


def _chain(through_family, allow_size_change=True, profiles=("Circular", "Circular")):
    """A -- N2 (two-port node of `through_family`) -- B."""
    sections = [
        circular_section(200.0) if p == "Circular" else SectionModel(profile=p, width_mm=300.0, height_mm=200.0)
        for p in profiles
    ]
    nodes = {
        "N1": NodeModel("N1", "end", 1, [port("A", "N1", False)]),
        "N2": NodeModel(
            "N2",
            "through",
            2,
            [port("A", "N2", True), port("B", "N2", False)],
            family=through_family,
            allow_size_change=allow_size_change,
        ),
        "N3": NodeModel("N3", "end", 1, [port("B", "N3", True)]),
    }
    segments = {"A": SegmentModel("A", sections[0], 1000.0), "B": SegmentModel("B", sections[1], 1000.0)}
    return NetworkModel(nodes=nodes, segments=segments, edges={"A": ("N1", "N2"), "B": ("N2", "N3")})


def _tee_with_run_pair():
    net = base_tree()
    net.nodes["N2"].family = "tee"
    net.nodes["N2"].run_edge_pairs = [("A", "B")]
    return net


def _components(net):
    components, warnings = flow.solve_flow_components(net)
    assert warnings == []
    return components


# ----------------------------------------------------------------------------
# sizing_sections
# ----------------------------------------------------------------------------


@pytest.mark.parametrize("family", ["bend", "bend_90", "bend.3d", "bend_90.3d"])
def test_a_bend_keeps_its_size(family):
    assert sizing_sections(_chain(family)) == [["A", "B"]]


@pytest.mark.parametrize("family", ["straight", "offset", "transition", ""])
def test_an_in_line_node_is_where_a_reducer_can_go(family):
    assert sizing_sections(_chain(family)) == [["A"], ["B"]]


def test_a_pinned_straight_node_keeps_one_size():
    assert sizing_sections(_chain("straight", allow_size_change=False)) == [["A", "B"]]


def test_a_change_of_profile_always_ends_a_section():
    assert sizing_sections(_chain("bend_90", profiles=("Circular", "Rectangular"))) == [["A"], ["B"]]


def test_a_tee_run_may_step_down_at_the_takeoff_by_default():
    # AtStraightJunctions (the default): the run of a tee is a straight-through junction too.
    assert sizing_sections(_tee_with_run_pair()) == [["A"], ["B"], ["C"]]


def test_a_pinned_tee_keeps_one_size_along_its_run():
    net = _tee_with_run_pair()
    net.nodes["N2"].allow_size_change = False
    assert sizing_sections(net) == [["A", "B"], ["C"]]


def test_inline_nodes_only_keeps_the_tee_run_one_size_and_the_branch_starts_a_section():
    assert sizing_sections(_tee_with_run_pair(), "AtInlineNodesOnly") == [["A", "B"], ["C"]]


@pytest.mark.parametrize("policy", ["AtStraightJunctions", "AtInlineNodesOnly"])
def test_both_policies_split_at_an_in_line_node_and_keep_a_bend(policy):
    assert sizing_sections(_chain("straight"), policy) == [["A"], ["B"]]
    assert sizing_sections(_chain("bend_90"), policy) == [["A", "B"]]


def test_a_tee_without_run_pair_data_joins_nothing():
    assert sizing_sections(base_tree()) == [["A"], ["B"], ["C"]]


def test_sections_chain_through_several_nodes():
    # A -tee(run A,B)- B -bend- D: with tee runs kept one size, A, B and D share one size.
    net = _tee_with_run_pair()
    net.nodes["N3"] = NodeModel("N3", "through", 2, [port("B", "N3", True), port("D", "N3", False)], family="bend_90")
    net.nodes["N5"] = NodeModel("N5", "end", 1, [port("D", "N5", True)], 50.0, flow_boundary="Fixed")
    net.segments["D"] = SegmentModel("D", circular_section(150.0), 1000.0)
    net.edges["D"] = ("N3", "N5")
    assert sizing_sections(net, "AtInlineNodesOnly") == [["A", "B", "D"], ["C"]]
    assert sizing_sections(net) == [["A"], ["B", "D"], ["C"]]


# ----------------------------------------------------------------------------
# The sizers
# ----------------------------------------------------------------------------


def test_constant_velocity_run_takes_the_size_of_its_upstream_end():
    net = _tee_with_run_pair()
    settings = SizingSettings(
        method="ConstantVelocity", target_velocity_ms=5.0, rounding_mm=0.0, size_change_policy="AtInlineNodesOnly"
    )
    result = ConstantVelocitySizer().size(net, _components(net), settings)

    a, b, c = (result.segments[k] for k in "ABC")
    expected_a = physics.circular_diameter_for_velocity(physics.lps_to_m3s(80.0), 5.0) * 1000.0
    assert a.new_section.diameter_mm == pytest.approx(expected_a)
    # B (50 L/s) shares A's size, so its velocity drops to 5 * 50 / 80.
    assert b.new_section.diameter_mm == pytest.approx(expected_a)
    assert b.velocity_ms == pytest.approx(5.0 * 50.0 / 80.0)
    assert b.friction_rate_pa_per_m > 0.0
    # The branch is sized for its own flow.
    assert c.velocity_ms == pytest.approx(5.0)
    assert result.sections == [["A", "B"], ["C"]]


def test_every_segment_policy_keeps_the_old_behaviour():
    net = _tee_with_run_pair()
    settings = SizingSettings(
        method="ConstantVelocity", target_velocity_ms=5.0, rounding_mm=0.0, size_change_policy="EverySegment"
    )
    result = ConstantVelocitySizer().size(net, _components(net), settings)
    assert result.segments["B"].velocity_ms == pytest.approx(5.0)
    assert result.sections == []


def test_friction_rate_and_static_regain_sizers_also_share_the_run_size():
    net = _tee_with_run_pair()
    for sizer, method in (
        (ConstantFrictionRateSizer(), "ConstantFrictionRate"),
        (LocalStaticRegainSizer(), "StaticRegain"),
    ):
        settings = SizingSettings(
            method=method, target_velocity_ms=5.0, rounding_mm=0.0, size_change_policy="AtInlineNodesOnly"
        )
        result = sizer.size(net, _components(net), settings)
        assert result.segments["B"].new_section == result.segments["A"].new_section, method


def test_reducer_is_suggested_where_the_shared_size_is_much_too_big():
    # B carries 20 of 80 L/s: at A's size it has 4 times the area it needs.
    net = base_tree(j3_flow=20.0, j4_flow=60.0)
    net.nodes["N2"].run_edge_pairs = [("A", "B")]
    settings = SizingSettings(
        method="ConstantVelocity", target_velocity_ms=5.0, rounding_mm=0.0, size_change_policy="AtInlineNodesOnly"
    )
    result = ConstantVelocitySizer().size(net, _components(net), settings)
    assert [s.edge_key for s in result.reducer_suggestions] == ["B"]
    assert result.reducer_suggestions[0].area_ratio == pytest.approx(4.0)


def test_a_tee_run_is_sized_for_its_own_flow_by_default():
    # AtStraightJunctions: B (50 of 80 L/s) may step down at the tee, so it keeps the target velocity.
    net = _tee_with_run_pair()
    settings = SizingSettings(method="ConstantVelocity", target_velocity_ms=5.0, rounding_mm=0.0)
    result = ConstantVelocitySizer().size(net, _components(net), settings)
    assert result.segments["B"].velocity_ms == pytest.approx(5.0)
    assert result.reducer_suggestions == []


def test_no_reducer_is_suggested_below_the_threshold():
    net = _tee_with_run_pair()  # B carries 50 of 80 L/s: 1.6 times the area.
    settings = SizingSettings(
        method="ConstantVelocity", target_velocity_ms=5.0, rounding_mm=0.0, reducer_advice_area_ratio=2.0
    )
    assert ConstantVelocitySizer().size(net, _components(net), settings).reducer_suggestions == []
