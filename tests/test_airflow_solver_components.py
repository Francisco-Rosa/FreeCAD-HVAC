"""
Focused tests for AirflowSolver's Phase E handling of a junction whose
DuctJunction carries a Primary plus one or more Inline devices attached to
individual real edges (see DuctJunction.getPortChains): the Primary is
evaluated once against its own full real multi-port context, and separately,
each real edge's own Inline chain is evaluated against THAT EDGE's own flow
-- each component's own K is converted to Pa immediately and summed, never
generically summed as raw K (spec: "do not sum K values unless they use the
same reference velocity").
"""

import json

import conftest  # noqa: F401 -- installs FreeCAD/FreeCADGui/Part/PySide stubs
import pytest

from freecad.HVAC.analysis import physics as airflow
from freecad.HVAC.analysis.pressure import ComponentPortResult, ComponentResult, ComponentTreeResult, JunctionResult, SegmentResult
from freecad.HVAC.core import _component_results
from freecad.HVAC.core.AirflowSolver import AirflowSolver
from freecad.HVAC.utils import hvaclib
from network_fixtures import FakeObj, FakeParser, legacy_loss_result, make_net, make_segment

AIR_DENSITY = 1.204


def _port(edge_key, segment_end, diameter_mm, flow_into_junction):
    return {
        "edge_key": edge_key,
        "segment_end": segment_end,
        "position": [0.0, 0.0, 0.0],
        "direction": [1.0, 0.0, 0.0],
        "profile": "Circular",
        "section_params": {"Diameter": diameter_mm},
        "attachment": "Center",
        "user_offset": [0.0, 0.0, 0.0],
        "profile_x_axis": None,
        "flow_role": "inlet" if flow_into_junction else "outlet",
        "flow_direction": [1.0, 0.0, 0.0],
        "flow_into_junction": flow_into_junction,
    }


class _FakeChainJunctionProxy:
    def __init__(self, components):
        self._components = components

    def getComponents(self):
        return list(self._components)

    def getPrimaryComponent(self):
        return next((c for c in self._components if c.ComponentRole == "Primary"), None)

    def getPortChains(self):
        chains = {}
        for c in self._components:
            if c.ComponentRole != "Inline":
                continue
            edge_key = getattr(c, "AttachedEdgeKey", "")
            if edge_key:
                chains.setdefault(edge_key, []).append(c)
        for lst in chains.values():
            lst.sort(key=lambda c: int(getattr(c, "PortSequence", 0)))
        return chains


class _FakeCallLossRegistry:
    """resolve_type/call_loss dispatch keyed purely by TypeId, so each
    component's own K (dict-result for a junction fitting -- matching real
    elbow_loss/transition_loss/branch_loss shapes -- or a float-result for a
    damper, matching inline_device_loss) is independent of the others'."""

    def __init__(self, results_by_type_id):
        self._results = results_by_type_id

    def resolve_type(self, library_id, type_id):
        return object() if type_id in self._results else None

    def call_loss(self, library_id, type_def, context):
        return legacy_loss_result(self._results[context["type_id"]], context)


def _single_component_junction(label, type_id, port):
    obj = FakeObj(Label=label, Topology="end")
    component = FakeObj(
        Label=label + "_Comp0", ComponentRole="Primary",
        LibraryId="testlib", TypeId=type_id, Family="",
        LocalPortsJson=json.dumps([port]),
    )
    obj.Proxy = _FakeChainJunctionProxy([component])
    return obj


def test_primary_and_chain_losses_on_the_same_edge_are_summed_as_pa(monkeypatch):
    """
    J1 (AHU, balancing terminal) --segA(200mm)--> J2 (Reducer[Primary] +
    Damper[Inline, attached to edge B]) --segB(180mm)--> J3 (leaf terminal).

    The reducer's Primary is always given the literal real ports (A, B)
    unchanged -- no synthetic intermediate size -- so both its own dict K
    (keyed to its own real outlet, B) and the damper's own K (attached to
    that same edge B) are converted to Pa using edge B's own real velocity
    and summed additively onto segB's fitting_loss_pa.
    """
    node_ports = {1: [("A", "start")], 2: [("A", "end"), ("B", "start")], 3: [("B", "end")]}
    edge_endpoints = {"A": (1, 2), "B": (2, 3)}
    parser = FakeParser(node_ports, edge_endpoints)

    segment_map = {
        "A": make_segment("A", 200.0, 5000.0),
        "B": make_segment("B", 180.0, 4000.0),
    }

    reducer = FakeObj(
        Label="Reducer", ComponentRole="Primary",
        LibraryId="testlib", TypeId="fake_reducer", Family="",
        LocalPortsJson=json.dumps([
            _port("A", "end", 200.0, True),
            _port("B", "start", 180.0, False),
        ]),
    )
    damper = FakeObj(
        Label="Damper", ComponentRole="Inline", AttachedEdgeKey="B", PortSequence=10,
        LibraryId="testlib", TypeId="fake_damper", Family="",
        LocalPortsJson=json.dumps([
            _port("N2#B_seam0", "end", 180.0, True),
            _port("B", "start", 180.0, False),
        ]),
    )

    junction_map = {
        "N1": _single_component_junction("J1", "end_terminal_marker", _port("A", "start", 200.0, False)),
        "N2": FakeObj(Label="J2", Topology="through"),
        "N3": _single_component_junction("J3", "end_terminal_marker", _port("B", "end", 180.0, True)),
    }
    junction_map["N1"].DesignFlowRate = 0.0
    junction_map["N1"].FlowBoundary = "Auto"
    junction_map["N3"].DesignFlowRate = 80.0
    junction_map["N3"].FlowBoundary = "Fixed"
    junction_map["N2"].Proxy = _FakeChainJunctionProxy([reducer, damper])

    net = make_net(parser, segment_map, junction_map)

    K_REDUCER = 0.4
    K_DAMPER = 0.25
    registry = _FakeCallLossRegistry({
        "end_terminal_marker": None,
        # elbow_loss/transition_loss shape: a dict keyed to the Primary's
        # own real outlet edge_key.
        "fake_reducer": {"B": K_REDUCER},
        # inline_device_loss shape: a bare float, applied to the outlet.
        "fake_damper": K_DAMPER,
    })
    monkeypatch.setattr(
        hvaclib.HVACLibraryService, "get_hvac_library_registry", staticmethod(lambda: registry),
    )

    result = AirflowSolver(net).solve()
    assert not result.warnings

    seg_by_key = {s.key: s for comp in result.components for s in comp.segments}
    seg_b = seg_by_key["B"]

    flow_m3s = airflow.lps_to_m3s(80.0)
    v_b = airflow.velocity_from_flow(flow_m3s, airflow.circular_area(airflow.mm_to_m(180.0)))
    assert seg_b.velocity_ms == pytest.approx(v_b)

    expected_reducer_pa = K_REDUCER * airflow.velocity_pressure(AIR_DENSITY, v_b)
    expected_damper_pa = K_DAMPER * airflow.velocity_pressure(AIR_DENSITY, v_b)
    expected_total_pa = expected_reducer_pa + expected_damper_pa

    # Both contributions land on segB, added together -- the Primary's own
    # per-edge loss (evaluated once, over its real multi-port context) and
    # that same edge's own Inline chain loss (evaluated separately, using
    # edge B's own flow) are independent and additive.
    assert seg_b.fitting_loss_pa == pytest.approx(expected_total_pa)

    # Per-component results are stored on each DuctComponent.
    assert damper.CalcLossCoefficient == K_DAMPER
    assert damper.CalcVelocity == pytest.approx(v_b)
    assert damper.CalcPressureDrop == pytest.approx(expected_damper_pa)


def _tee_network(k_tee, k_run_damper, k_branch_damper):
    """
    J1 (AHU, balancing terminal) --segA(300mm, trunk)--> J2 (tee)
                                        |--segB(300mm, run)--> J3 (leaf, 700 L/s)
                                        '--segC(200mm, branch)--> J4 (leaf, 300 L/s)

    J2's Primary is a tee with real ports A (inlet), B (run outlet), C
    (branch outlet). A damper is attached to the run leg (B) and a
    different damper to the branch leg (C) -- two independent Inline
    chains on two different edges of the same junction.
    """
    node_ports = {
        1: [("A", "start")],
        2: [("A", "end"), ("B", "start"), ("C", "start")],
        3: [("B", "end")],
        4: [("C", "end")],
    }
    edge_endpoints = {"A": (1, 2), "B": (2, 3), "C": (2, 4)}
    parser = FakeParser(node_ports, edge_endpoints)

    segment_map = {
        "A": make_segment("A", 300.0, 6000.0),
        "B": make_segment("B", 300.0, 4000.0),
        "C": make_segment("C", 200.0, 3000.0),
    }

    tee = FakeObj(
        Label="Tee", ComponentRole="Primary",
        LibraryId="testlib", TypeId="fake_tee", Family="branch.tee",
        LocalPortsJson=json.dumps([
            _port("A", "end", 300.0, True),
            _port("B", "start", 300.0, False),
            _port("C", "start", 200.0, False),
        ]),
    )
    run_damper = FakeObj(
        Label="RunDamper", ComponentRole="Inline", AttachedEdgeKey="B", PortSequence=10,
        LibraryId="testlib", TypeId="fake_run_damper", Family="",
        LocalPortsJson=json.dumps([
            _port("N2#B_seam0", "end", 300.0, True),
            _port("B", "start", 300.0, False),
        ]),
    )
    branch_damper = FakeObj(
        Label="BranchDamper", ComponentRole="Inline", AttachedEdgeKey="C", PortSequence=10,
        LibraryId="testlib", TypeId="fake_branch_damper", Family="",
        LocalPortsJson=json.dumps([
            _port("N2#C_seam0", "end", 200.0, True),
            _port("C", "start", 200.0, False),
        ]),
    )

    junction_map = {
        "N1": _single_component_junction("J1", "end_terminal_marker", _port("A", "start", 300.0, False)),
        "N2": FakeObj(Label="J2", Topology="branch"),
        "N3": _single_component_junction("J3", "end_terminal_marker", _port("B", "end", 300.0, True)),
        "N4": _single_component_junction("J4", "end_terminal_marker", _port("C", "end", 200.0, True)),
    }
    junction_map["N1"].DesignFlowRate = 0.0
    junction_map["N1"].FlowBoundary = "Auto"
    junction_map["N3"].DesignFlowRate = 700.0
    junction_map["N3"].FlowBoundary = "Fixed"
    junction_map["N4"].DesignFlowRate = 300.0
    junction_map["N4"].FlowBoundary = "Fixed"
    junction_map["N2"].Proxy = _FakeChainJunctionProxy([tee, run_damper, branch_damper])

    net = make_net(parser, segment_map, junction_map)

    registry = _FakeCallLossRegistry({
        "end_terminal_marker": None,
        # branch_loss shape: one K per real outlet port.
        "fake_tee": {"B": k_tee, "C": k_tee},
        "fake_run_damper": k_run_damper,
        "fake_branch_damper": k_branch_damper,
    })

    return net, registry, run_damper, branch_damper


def test_branch_leg_inline_component_uses_branch_flow_not_total_flow(monkeypatch):
    K_TEE = 0.2
    K_RUN_DAMPER = 0.15
    K_BRANCH_DAMPER = 0.3
    net, registry, run_damper, branch_damper = _tee_network(K_TEE, K_RUN_DAMPER, K_BRANCH_DAMPER)
    monkeypatch.setattr(
        hvaclib.HVACLibraryService, "get_hvac_library_registry", staticmethod(lambda: registry),
    )

    result = AirflowSolver(net).solve()
    assert not result.warnings

    seg_by_key = {s.key: s for comp in result.components for s in comp.segments}
    seg_b, seg_c = seg_by_key["B"], seg_by_key["C"]

    v_b = airflow.velocity_from_flow(airflow.lps_to_m3s(700.0), airflow.circular_area(airflow.mm_to_m(300.0)))
    v_c = airflow.velocity_from_flow(airflow.lps_to_m3s(300.0), airflow.circular_area(airflow.mm_to_m(200.0)))
    assert seg_b.velocity_ms == pytest.approx(v_b)
    assert seg_c.velocity_ms == pytest.approx(v_c)

    # The branch damper must be evaluated against edge C's OWN flow/velocity
    # (300 L/s through 200mm), never the trunk's total flow (1000 L/s) or
    # the run leg's own flow/size.
    assert branch_damper.CalcVelocity == pytest.approx(v_c)
    assert branch_damper.CalcVelocity != pytest.approx(v_b)

    expected_tee_b_pa = K_TEE * airflow.velocity_pressure(AIR_DENSITY, v_b)
    expected_tee_c_pa = K_TEE * airflow.velocity_pressure(AIR_DENSITY, v_c)
    expected_run_damper_pa = K_RUN_DAMPER * airflow.velocity_pressure(AIR_DENSITY, v_b)
    expected_branch_damper_pa = K_BRANCH_DAMPER * airflow.velocity_pressure(AIR_DENSITY, v_c)

    assert seg_b.fitting_loss_pa == pytest.approx(expected_tee_b_pa + expected_run_damper_pa)
    assert seg_c.fitting_loss_pa == pytest.approx(expected_tee_c_pa + expected_branch_damper_pa)

    # A naive implementation that (wrongly) evaluated the branch damper
    # against the trunk's total flow through the branch leg's own 200mm
    # size would give a different, wrong velocity/pressure-drop.
    naive_wrong_v_c = airflow.velocity_from_flow(airflow.lps_to_m3s(1000.0), airflow.circular_area(airflow.mm_to_m(200.0)))
    assert abs(branch_damper.CalcVelocity - naive_wrong_v_c) > 1e-6

    assert run_damper.CalcLossCoefficient == K_RUN_DAMPER
    assert branch_damper.CalcLossCoefficient == K_BRANCH_DAMPER


def _standalone_tee_network(k_straight, k_branch):
    """
    Same J1 --A--> J2(tee) --B--> J3 / --C--> J4 topology as _tee_network(),
    but with no Inline chains at all and independently-controllable K per
    leg on the tee itself -- isolates the Primary's own retained
    per-port results from any Inline-chain contribution.
    """
    node_ports = {
        1: [("A", "start")],
        2: [("A", "end"), ("B", "start"), ("C", "start")],
        3: [("B", "end")],
        4: [("C", "end")],
    }
    edge_endpoints = {"A": (1, 2), "B": (2, 3), "C": (2, 4)}
    parser = FakeParser(node_ports, edge_endpoints)

    segment_map = {
        "A": make_segment("A", 300.0, 6000.0),
        "B": make_segment("B", 300.0, 4000.0),
        "C": make_segment("C", 200.0, 3000.0),
    }

    tee = FakeObj(
        Label="Tee", ComponentRole="Primary",
        LibraryId="testlib", TypeId="fake_tee", Family="branch.tee",
        LocalPortsJson=json.dumps([
            _port("A", "end", 300.0, True),
            _port("B", "start", 300.0, False),
            _port("C", "start", 200.0, False),
        ]),
        CalcPortResultsJson="{}", CalcFlowRate=0.0, CalcVelocity=0.0,
        CalcLossCoefficient=0.0, CalcPressureDrop=0.0,
    )

    junction_map = {
        "N1": _single_component_junction("J1", "end_terminal_marker", _port("A", "start", 300.0, False)),
        "N2": FakeObj(Label="J2", Topology="branch"),
        "N3": _single_component_junction("J3", "end_terminal_marker", _port("B", "end", 300.0, True)),
        "N4": _single_component_junction("J4", "end_terminal_marker", _port("C", "end", 200.0, True)),
    }
    junction_map["N1"].DesignFlowRate = 0.0
    junction_map["N1"].FlowBoundary = "Auto"
    junction_map["N3"].DesignFlowRate = 700.0
    junction_map["N3"].FlowBoundary = "Fixed"
    junction_map["N4"].DesignFlowRate = 300.0
    junction_map["N4"].FlowBoundary = "Fixed"
    junction_map["N2"].Proxy = _FakeChainJunctionProxy([tee])

    net = make_net(parser, segment_map, junction_map)
    registry = _FakeCallLossRegistry({
        "end_terminal_marker": None,
        "fake_tee": {"B": k_straight, "C": k_branch},
    })
    return net, registry, tee


def test_multiport_tee_retains_distinct_branch_and_straight_k_and_pressure_drop(monkeypatch):
    """
    A 3-port tee's own scalar CalcLossCoefficient/CalcPressureDrop can't
    represent two different legs' worth of K/pressure-drop -- they must
    stay at 0 (Component.py's own editor-mode sync hides them from the
    property editor) while CalcPortResultsJson -- and the new per-leg UI
    rows built alongside it -- retain each leg's own distinct value. No
    fitting loss is double counted: each segment's own fitting_loss_pa must
    equal exactly its own leg's retained pressure_drop_pa.
    """
    K_STRAIGHT = 0.18
    K_BRANCH = 1.05
    net, registry, tee = _standalone_tee_network(K_STRAIGHT, K_BRANCH)
    monkeypatch.setattr(
        hvaclib.HVACLibraryService, "get_hvac_library_registry", staticmethod(lambda: registry),
    )

    result = AirflowSolver(net).solve()
    assert not result.warnings

    # Do NOT use max/average/sum-of-K or a maximum/total-flow substitute --
    # left at 0 and hidden instead.
    assert tee.CalcLossCoefficient == 0.0
    assert tee.CalcPressureDrop == 0.0
    assert tee.CalcFlowRate == 0.0
    assert tee.CalcVelocity == 0.0

    port_results = _component_results.deserialize_port_results(tee.CalcPortResultsJson)
    assert set(port_results.keys()) == {"B", "C"}
    assert port_results["B"].loss_coefficient == K_STRAIGHT
    assert port_results["C"].loss_coefficient == K_BRANCH
    assert port_results["B"].pressure_drop_pa != port_results["C"].pressure_drop_pa

    seg_by_key = {s.key: s for comp in result.components for s in comp.segments}
    assert seg_by_key["B"].fitting_loss_pa == pytest.approx(port_results["B"].pressure_drop_pa)
    assert seg_by_key["C"].fitting_loss_pa == pytest.approx(port_results["C"].pressure_drop_pa)

    # New per-leg UI rows: one per outlet, each with its own K -- never one
    # collapsed scalar row for a multiport fitting.
    rows = {row.edge_key: row for comp in result.components for row in comp.component_ports}
    assert set(rows.keys()) == {"B", "C"}
    assert rows["B"].loss_coefficient == K_STRAIGHT
    assert rows["C"].loss_coefficient == K_BRANCH
    assert rows["B"].component_obj is tee

    # Each leg's own static pressure is a real, distinct derivation
    # (node's shared value minus THAT leg's own pressure_drop_pa) -- never
    # a blind copy of the junction's one value onto both legs.
    junc_by_key = {j.key: j for comp in result.components for j in comp.junctions}
    node_static = junc_by_key["N2"].static_pressure_pa
    assert rows["B"].static_pressure_pa == pytest.approx(node_static - rows["B"].pressure_drop_pa)
    assert rows["C"].static_pressure_pa == pytest.approx(node_static - rows["C"].pressure_drop_pa)
    assert rows["B"].static_pressure_pa != pytest.approx(rows["C"].static_pressure_pa)


def test_recalculation_fully_replaces_stale_calc_port_results_json(monkeypatch):
    """A second "Run Revised Calculation" must fully replace the first
    solve's CalcPortResultsJson, never merge stale entries into it."""
    net, registry, tee = _standalone_tee_network(0.2, 0.2)
    monkeypatch.setattr(
        hvaclib.HVACLibraryService, "get_hvac_library_registry", staticmethod(lambda: registry),
    )
    AirflowSolver(net).solve()
    first = _component_results.deserialize_port_results(tee.CalcPortResultsJson)
    assert set(first.keys()) == {"B", "C"}

    # A second solve with a materially different K -- the previous run's
    # numbers must be gone, not merged with the new ones.
    registry._results["fake_tee"] = {"B": 0.9}
    AirflowSolver(net).solve()
    second = _component_results.deserialize_port_results(tee.CalcPortResultsJson)

    assert set(second.keys()) == {"B"}
    assert second["B"].loss_coefficient == 0.9


def test_failed_tree_leaves_calc_port_results_json_untouched(monkeypatch):
    """
    An unsized segment makes PressureSolver raise FlowSolveError for that
    whole tree (caught internally, reported as a warning) -- that tree's
    components must never get a partial/corrupted CalcPortResultsJson
    write; whatever they held before this solve must be left exactly as-is.
    """
    net, registry, tee = _standalone_tee_network(0.2, 0.6)
    monkeypatch.setattr(
        hvaclib.HVACLibraryService, "get_hvac_library_registry", staticmethod(lambda: registry),
    )
    tee.CalcPortResultsJson = '{"stale": {"flow_lps": 1.0, "velocity_ms": 1.0, "loss_coefficient": 1.0, "pressure_drop_pa": 1.0, "static_pressure_pa": null}}'

    # Segment B has no valid duct size -- makes the whole tree fail to solve.
    net.Proxy._segment_map["B"].Diameter = 0.0

    result = AirflowSolver(net).solve()

    assert result.components == []
    assert len(result.warnings) == 1
    # Untouched -- not cleared, not partially overwritten with new data.
    assert tee.CalcPortResultsJson == (
        '{"stale": {"flow_lps": 1.0, "velocity_ms": 1.0, "loss_coefficient": 1.0, '
        '"pressure_drop_pa": 1.0, "static_pressure_pa": null}}'
    )


def test_inline_component_on_inlet_edge_derives_velocity_from_that_edges_own_flow(monkeypatch):
    """
    Merge/split direction check: an Inline component attached to a real
    INLET edge (flow_into_junction=True -- Segment -> Inline -> Primary)
    has its own OUTLET port on the synthetic, Primary-facing side, not on
    the real segment side -- _fillPortFlow must still resolve that
    synthetic port's velocity from the real edge's own flow (there's no
    matching real segment for a synthetic edge_key, so it falls to the
    "derive locally from this edge's own flow" branch), not silently drop
    it or use the wrong edge's flow.
    """
    node_ports = {1: [("A", "start")], 2: [("A", "end"), ("B", "start")], 3: [("B", "end")]}
    edge_endpoints = {"A": (1, 2), "B": (2, 3)}
    parser = FakeParser(node_ports, edge_endpoints)

    segment_map = {
        "A": make_segment("A", 250.0, 5000.0),
        "B": make_segment("B", 250.0, 4000.0),
    }

    primary = FakeObj(
        Label="Primary", ComponentRole="Primary",
        LibraryId="testlib", TypeId="fake_through", Family="",
        LocalPortsJson=json.dumps([
            _port("A", "end", 250.0, True),
            _port("B", "start", 250.0, False),
        ]),
    )
    # Damper attached to the INLET edge A: flow goes Segment(A) -> Damper ->
    # Primary, so the damper's own OUTLET (flow_into_junction=False) is its
    # inner, synthetic seam port -- not a real segment.
    inlet_damper = FakeObj(
        Label="InletDamper", ComponentRole="Inline", AttachedEdgeKey="A", PortSequence=10,
        LibraryId="testlib", TypeId="fake_inlet_damper", Family="",
        LocalPortsJson=json.dumps([
            _port("N2#A_seam0", "end", 250.0, False),  # inner: this component's own outlet
            _port("A", "start", 250.0, True),           # outer: real edge A, this component's own inlet
        ]),
    )

    junction_map = {
        "N1": _single_component_junction("J1", "end_terminal_marker", _port("A", "start", 250.0, False)),
        "N2": FakeObj(Label="J2", Topology="through"),
        "N3": _single_component_junction("J3", "end_terminal_marker", _port("B", "end", 250.0, True)),
    }
    junction_map["N1"].DesignFlowRate = 0.0
    junction_map["N1"].FlowBoundary = "Auto"
    junction_map["N3"].DesignFlowRate = 60.0
    junction_map["N3"].FlowBoundary = "Fixed"
    junction_map["N2"].Proxy = _FakeChainJunctionProxy([primary, inlet_damper])

    net = make_net(parser, segment_map, junction_map)

    K_INLET_DAMPER = 0.2
    registry = _FakeCallLossRegistry({
        "end_terminal_marker": None,
        # A real (degree >= 2) Primary with no loss data would otherwise
        # trigger the K_DEFAULT-fallback warning path -- give it an
        # explicit zero so this test stays focused on the inlet damper.
        "fake_through": {"B": 0.0},
        "fake_inlet_damper": K_INLET_DAMPER,
    })
    monkeypatch.setattr(
        hvaclib.HVACLibraryService, "get_hvac_library_registry", staticmethod(lambda: registry),
    )

    result = AirflowSolver(net).solve()
    assert not result.warnings

    seg_by_key = {s.key: s for comp in result.components for s in comp.segments}
    seg_a = seg_by_key["A"]

    v_a = airflow.velocity_from_flow(airflow.lps_to_m3s(60.0), airflow.circular_area(airflow.mm_to_m(250.0)))
    assert seg_a.velocity_ms == pytest.approx(v_a)

    # The damper's own outlet (the synthetic inner port) must resolve to
    # edge A's own velocity, derived locally since there's no real segment
    # matching its synthetic edge_key.
    assert inlet_damper.CalcVelocity == pytest.approx(v_a)
    expected_pa = K_INLET_DAMPER * airflow.velocity_pressure(AIR_DENSITY, v_a)
    assert inlet_damper.CalcPressureDrop == pytest.approx(expected_pa)


# ----------------------------------------------------------------------
# AirflowSolver._map_component_result -- ComponentPortRow's path_label/
# status mapping (Milestone A: propagate existing LossPath metadata --
# from_edge_key/to_edge_key/status, already on the pure ComponentPortResult
# -- into the FreeCAD-facing display row). Called directly against
# hand-built pure ComponentTreeResult dataclasses rather than through the
# whole network-sync stack, since this is purely an adapter/mapping
# concern -- the loss-path/pressure math itself is already covered
# elsewhere (tests/test_analysis_pressure.py).
# ----------------------------------------------------------------------

def _fake_tree(port_results_by_component):
    """A minimal ComponentTreeResult with 3 real segments (A, B, C) and one
    junction, and one Primary component per port_results dict given."""
    segments = {key: SegmentResult(edge_key=key) for key in ("A", "B", "C")}
    junctions = {"N1": JunctionResult(node_id="N1")}
    components = {
        comp_id: ComponentResult(component_id=comp_id, port_results=port_results)
        for comp_id, port_results in port_results_by_component.items()
    }
    return ComponentTreeResult(
        reference_terminal_id="N1", segments=segments, junctions=junctions, components=components,
    )


def _fake_maps(component_roles):
    segment_map = {
        "A": FakeObj(Number="D01", Label="Seg A"),
        "B": FakeObj(Number="D02", Label="Seg B"),
        "C": FakeObj(Number="D03", Label="Seg C"),
    }
    junction_map = {"N1": FakeObj(Number="J01", Label="Junc 1")}
    component_map = {
        comp_id: FakeObj(ComponentRole=role, Number="J04", Label="Tee")
        for comp_id, role in component_roles.items()
    }
    return segment_map, junction_map, component_map


def test_component_port_row_path_label_and_status_for_diverging_leg():
    # 1:N (diverging): the common inlet (A) splits into this outlet (B) --
    # the reference leg is the OUTLET, matching LossPath's own convention.
    tree = _fake_tree({
        "DivTee": {
            "B": ComponentPortResult(
                edge_key="B", flow_lps=10.0, velocity_ms=5.0, loss_coefficient=0.3,
                pressure_drop_pa=4.5, static_pressure_pa=100.0,
                from_edge_key="A", to_edge_key="B", status="fallback",
            ),
        },
    })
    segment_map, junction_map, component_map = _fake_maps({"DivTee": "Primary"})

    cres = AirflowSolver._map_component_result(tree, segment_map, junction_map, component_map)

    (row,) = cres.component_ports
    assert row.path_label == "D01 → D02"
    assert row.leg_label == "D02"
    assert row.status == "fallback"


def test_component_port_row_path_label_and_status_for_converging_leg():
    # N:1 (converging): this inlet (C) merges into the common outlet (A) --
    # the reference leg is the INLET here, the opposite side from the
    # diverging case above, so a direction-flipping bug in the label
    # mapping would silently swap "from"/"to" without either test alone
    # catching it.
    tree = _fake_tree({
        "ConvTee": {
            "C": ComponentPortResult(
                edge_key="C", flow_lps=8.0, velocity_ms=4.0, loss_coefficient=0.6,
                pressure_drop_pa=6.0, static_pressure_pa=90.0,
                from_edge_key="C", to_edge_key="A", status="exact",
            ),
        },
    })
    segment_map, junction_map, component_map = _fake_maps({"ConvTee": "Primary"})

    cres = AirflowSolver._map_component_result(tree, segment_map, junction_map, component_map)

    (row,) = cres.component_ports
    assert row.path_label == "D03 → D01"
    assert row.leg_label == "D03"
    assert row.status == "exact"


def test_component_port_row_uses_open_for_a_1port_devices_atmosphere_side():
    # A terminal device's path has no real duct on one side (see LossPath's
    # own from_edge_key/to_edge_key docstring) -- must render as "Open",
    # not a blank cell or a raw None.
    tree = _fake_tree({
        "Diffuser": {
            "A": ComponentPortResult(
                edge_key="A", flow_lps=5.0, velocity_ms=3.0, loss_coefficient=0.1,
                pressure_drop_pa=1.0, static_pressure_pa=0.0,
                from_edge_key="A", to_edge_key=None, status="exact",
            ),
        },
    })
    segment_map, junction_map, component_map = _fake_maps({"Diffuser": "Primary"})

    cres = AirflowSolver._map_component_result(tree, segment_map, junction_map, component_map)

    (row,) = cres.component_ports
    assert row.path_label == "D01 → Open"
