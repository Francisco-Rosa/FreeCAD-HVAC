"""
Integration-style tests for freecad.HVAC.core.AirflowSolver against a small
synthetic tree network, using lightweight fake stand-ins for the FreeCAD
DuctNetwork/DuctJunction/DuctSegment objects and the DuctNetworkParser API
surface the solver depends on (nodes/node_edges/edge_analysis_nodes/node_key/
build_junction_analysis). This avoids needing a real FreeCAD installation or
real base geometry while still exercising the actual solver algorithm
end-to-end (flow conservation, friction+fitting loss, pressure propagation,
and the error paths).

Network under test (a simple supply tree):

    J1 (AHU, balancing terminal) --segA(5m,200mm dia)--> J2 (tee)
                                                              |--segB(3m,150mm dia)--> J3 (leaf, 50 L/s)
                                                              '--segC(6m,150mm dia)--> J4 (leaf, 30 L/s)

Base-geometry direction convention: every segment's "start" is its upstream
(AHU-facing) end, "end" is its downstream end -- matching flow_into_junction
semantics in NetworkParser.build_junction_ports.
"""

import pytest

import conftest  # noqa: F401 -- installs FreeCAD/FreeCADGui/Part/PySide stubs
from network_fixtures import (
    AIR_DENSITY,
    AIR_VISCOSITY,
    DEFAULT_ROUGHNESS_MM,
    FakeParser,
    FakeProxy,
    base_tree as _base_tree,
    legacy_loss_result,
    make_junction as _make_junction,
    make_net as _make_net,
    make_segment as _make_segment,
)

from freecad.HVAC.analysis import physics as airflow
from freecad.HVAC.core.AirflowSolver import AirflowSolver, AirflowSolveError, K_DEFAULT


FITTING_K = 0.5


class _FakeTypeDef:
    pass


class _FakeRegistry:
    """Registry stub: branch_tee_generic resolves to a fixed K; everything else -> None (fallback)."""

    def resolve_type(self, library_id, type_id):
        if type_id == "branch_tee_generic":
            return _FakeTypeDef()
        return None

    def call_loss(self, library_id, type_def, context):
        return legacy_loss_result(FITTING_K, context)


@pytest.fixture(autouse=True)
def _patch_registry(monkeypatch):
    from freecad.HVAC.core import _analysis_adapter as solver_mod

    monkeypatch.setattr(
        solver_mod.hvaclib.HVACLibraryService,
        "get_hvac_library_registry",
        staticmethod(lambda: _FakeRegistry()),
    )


def _expected_segment(diameter_mm, length_mm, flow_lps):
    d_m = airflow.mm_to_m(diameter_mm)
    area = airflow.circular_area(d_m)
    dh = airflow.hydraulic_diameter_circular(d_m)
    v = airflow.velocity_from_flow(airflow.lps_to_m3s(flow_lps), area)
    re = airflow.reynolds_number(v, dh, AIR_VISCOSITY)
    rel_rough = airflow.mm_to_m(DEFAULT_ROUGHNESS_MM) / dh
    f = airflow.friction_factor_altshul_tsal(re, rel_rough)
    friction = airflow.darcy_weisbach_pressure_loss(f, airflow.mm_to_m(length_mm), dh, AIR_DENSITY, v)
    return v, re, friction


def test_flow_conservation_and_sizing():
    net, segment_map, junction_map = _base_tree()
    result = AirflowSolver(net).solve()

    assert result.warnings == []
    assert len(result.components) == 1
    comp = result.components[0]

    segA, segB, segC = (segment_map["A"], segment_map["B"], segment_map["C"])

    # Flow magnitudes: leaves specify design flow, internal/root edges solved by conservation.
    assert segC.CalcFlowRate == pytest.approx(30.0)
    assert segB.CalcFlowRate == pytest.approx(50.0)
    assert segA.CalcFlowRate == pytest.approx(80.0)  # root/balancing terminal = sum of leaves

    # Junction totals.
    j1, j2, j3, j4 = (junction_map["N1"], junction_map["N2"], junction_map["N3"], junction_map["N4"])
    assert j1.CalcTotalFlowRate == pytest.approx(80.0)
    assert j1.IsFlowSource is True  # AHU: flow leaves the system at this terminal
    assert j2.CalcTotalFlowRate == pytest.approx(80.0)
    assert j3.CalcTotalFlowRate == pytest.approx(50.0)
    assert j3.IsFlowSource is False
    assert j4.CalcTotalFlowRate == pytest.approx(30.0)

    # Per-segment velocity/Reynolds/friction match an independently computed oracle.
    vA, reA, frictionA = _expected_segment(200.0, 5000.0, 80.0)
    vB, reB, frictionB = _expected_segment(150.0, 3000.0, 50.0)
    vC, reC, frictionC = _expected_segment(150.0, 6000.0, 30.0)

    assert segA.CalcVelocity == pytest.approx(vA)
    assert segA.CalcReynoldsNumber == pytest.approx(reA)
    assert segA.CalcFrictionLoss == pytest.approx(frictionA)
    assert segB.CalcVelocity == pytest.approx(vB)
    assert segB.CalcFrictionLoss == pytest.approx(frictionB)
    assert segC.CalcVelocity == pytest.approx(vC)
    assert segC.CalcFrictionLoss == pytest.approx(frictionC)

    # Fitting loss: J2 is a resolved branch_tee_generic (K=FITTING_K), applied to its
    # two outlet ports (segB, segC) but not its inlet port (segA).
    assert segA.CalcFittingLoss == pytest.approx(0.0)
    assert segB.CalcFittingLoss == pytest.approx(FITTING_K * airflow.velocity_pressure(AIR_DENSITY, vB))
    assert segC.CalcFittingLoss == pytest.approx(FITTING_K * airflow.velocity_pressure(AIR_DENSITY, vC))
    assert j2.CalcLossWarning == ""  # a real K was found, no fallback warning

    # Pressure propagation: 0 Pa at the balancing terminal (J1), dropping downstream.
    assert j1.CalcStaticPressure == pytest.approx(0.0)
    p_j2 = -(frictionA + 0.0)
    assert j2.CalcStaticPressure == pytest.approx(p_j2)
    p_j3 = p_j2 - segB.CalcFittingLoss - frictionB
    p_j4 = p_j2 - segC.CalcFittingLoss - frictionC
    assert j3.CalcStaticPressure == pytest.approx(p_j3)
    assert j4.CalcStaticPressure == pytest.approx(p_j4)

    # Critical path: whichever terminal has the larger magnitude static pressure.
    expected_critical = "N4" if abs(p_j4) > abs(p_j3) else "N3"
    assert comp.critical_terminal_key == expected_critical
    assert comp.critical_pressure_pa == pytest.approx(max(abs(p_j3), abs(p_j4)))
    assert comp.reference_terminal_key == "N1"


def test_per_port_dict_loss_contract_attributes_distinct_coefficients(monkeypatch):
    from freecad.HVAC.core import _analysis_adapter as solver_mod

    class _DictRegistry:
        def resolve_type(self, library_id, type_id):
            return _FakeTypeDef() if type_id == "branch_tee_generic" else None

        def call_loss(self, library_id, type_def, context):
            # Distinct per-edge coefficients -- exercises the dict-of-paths
            # contract, which Phase E must NOT collapse into a single
            # uniform K like the legacy float/None contract does.
            return legacy_loss_result({"B": 0.9, "C": 0.1}, context)

    monkeypatch.setattr(
        solver_mod.hvaclib.HVACLibraryService,
        "get_hvac_library_registry",
        staticmethod(lambda: _DictRegistry()),
    )

    net, segment_map, junction_map = _base_tree()
    result = AirflowSolver(net).solve()

    assert result.warnings == []  # a dict return is real data, not a fallback
    segB, segC = segment_map["B"], segment_map["C"]
    vB, _re, _f = _expected_segment(150.0, 3000.0, 50.0)
    vC, _re, _f = _expected_segment(150.0, 6000.0, 30.0)
    assert segB.CalcFittingLoss == pytest.approx(0.9 * airflow.velocity_pressure(AIR_DENSITY, vB))
    assert segC.CalcFittingLoss == pytest.approx(0.1 * airflow.velocity_pressure(AIR_DENSITY, vC))
    assert junction_map["N2"].CalcLossWarning == ""


def test_fallback_loss_coefficient_and_warning():
    net, segment_map, junction_map = _base_tree()
    junction_map["N2"].TypeId = "unknown_type_not_wired"
    result = AirflowSolver(net).solve()

    assert result.warnings  # fallback warning recorded globally
    assert "K={}".format(K_DEFAULT) in result.warnings[0]
    assert junction_map["N2"].CalcLossWarning != ""

    segB = segment_map["B"]
    vB, _re, _f = _expected_segment(150.0, 3000.0, 50.0)
    assert segB.CalcFittingLoss == pytest.approx(K_DEFAULT * airflow.velocity_pressure(AIR_DENSITY, vB))


def test_loop_detected_and_reported_as_warning_not_exception():
    # A 3-node cycle -> a loop (not a tree: 3 nodes, 3 edges, needs exactly 2).
    # Duct networks never have two segments directly between the same pair of
    # junctions, so a real loop always involves 3+ distinct nodes like this.
    node_ports = {
        1: [("A", "start"), ("C", "end")],
        2: [("A", "end"), ("B", "start")],
        3: [("B", "end"), ("C", "start")],
    }
    edge_endpoints = {"A": (1, 2), "B": (2, 3), "C": (3, 1)}
    parser = FakeParser(node_ports, edge_endpoints)
    segment_map = {
        "A": _make_segment("A", 200.0, 5000.0),
        "B": _make_segment("B", 200.0, 5000.0),
        "C": _make_segment("C", 200.0, 5000.0),
    }
    junction_map = {
        "N1": _make_junction("J1", type_id="end_terminal_marker"),
        "N2": _make_junction("J2", type_id="end_terminal_marker"),
        "N3": _make_junction("J3", type_id="end_terminal_marker"),
    }
    net = _make_net(parser, segment_map, junction_map)

    result = AirflowSolver(net).solve()

    assert result.components == []
    assert len(result.warnings) == 1
    assert "Loop detected" in result.warnings[0]


def test_all_terminals_specified_is_an_error():
    net, segment_map, junction_map = _base_tree()
    junction_map["N1"].FlowBoundary = "Fixed"
    junction_map["N1"].DesignFlowRate = 80.0  # no terminal left as the Auto balancing candidate

    result = AirflowSolver(net).solve()

    assert result.components == []
    assert len(result.warnings) == 1
    assert "Flow Condition" in result.warnings[0]


def test_closed_terminal_is_excluded_from_balancing_and_carries_zero_flow():
    """A Closed terminal contributes zero flow and is never the balancing
    candidate, even though it's just as "unspecified" as an Auto terminal
    would look under the old float-only convention."""
    net, segment_map, junction_map = _base_tree(j4_flow=999.0)
    junction_map["N4"].FlowBoundary = "Closed"
    junction_map["N4"].DesignFlowRate = 999.0  # must be ignored -- Closed always means 0 flow

    result = AirflowSolver(net).solve()

    assert not result.warnings
    seg_by_key = {s.key: s for comp in result.components for s in comp.segments}
    assert seg_by_key["C"].flow_lps == pytest.approx(0.0)


def test_fixed_terminal_at_zero_flow_is_not_treated_as_balancing_candidate():
    """0 L/s is now a perfectly valid Fixed flow rate -- it must not be
    confused with the Auto balancing candidate."""
    net, segment_map, junction_map = _base_tree(j4_flow=0.0)
    junction_map["N4"].FlowBoundary = "Fixed"
    junction_map["N4"].DesignFlowRate = 0.0

    result = AirflowSolver(net).solve()

    assert not result.warnings
    seg_by_key = {s.key: s for comp in result.components for s in comp.segments}
    assert seg_by_key["C"].flow_lps == pytest.approx(0.0)
    assert seg_by_key["A"].flow_lps == pytest.approx(50.0)  # J1 (Auto) balances J3's 50 L/s alone


def test_missing_duct_size_is_an_error():
    net, segment_map, junction_map = _base_tree()
    segment_map["A"].Diameter = 0.0

    result = AirflowSolver(net).solve()

    assert result.components == []
    assert len(result.warnings) == 1
    assert "duct dimensions" in result.warnings[0]


# ----------------------------------------------------------------------------
# Terminal (degree-1) fitting loss -- e.g. a diffuser/grille component
# ----------------------------------------------------------------------------

def test_terminal_component_loss_wired_contributes_to_connecting_segment(monkeypatch):
    from freecad.HVAC.core import _analysis_adapter as solver_mod

    # branch_tee_generic (J2) still resolves normally (K=0.5, same as the
    # default fixture) so this test isolates the NEW behavior (the diffuser
    # at J3) rather than also triggering an unrelated K_DEFAULT fallback at J2.
    tee_k = 0.5

    class _DiffuserRegistry:
        def resolve_type(self, library_id, type_id):
            if type_id in ("branch_tee_generic", "end_diffuser_generic"):
                return _FakeTypeDef()
            return None

        def call_loss(self, library_id, type_def, context):
            if context["type_id"] == "end_diffuser_generic":
                return legacy_loss_result({"B": 0.8}, context)
            return legacy_loss_result(tee_k, context)

    monkeypatch.setattr(
        solver_mod.hvaclib.HVACLibraryService,
        "get_hvac_library_registry",
        staticmethod(lambda: _DiffuserRegistry()),
    )

    net, segment_map, junction_map = _base_tree()
    junction_map["N3"].TypeId = "end_diffuser_generic"  # J3 is a sink terminal (inlet port)

    result = AirflowSolver(net).solve()

    assert result.warnings == []
    segB = segment_map["B"]
    vB, _re, _f = _expected_segment(150.0, 3000.0, 50.0)
    # Both contributions must be present -- the tee's (upstream, J2) AND the
    # diffuser's (downstream, J3) -- summed, not one clobbering the other.
    expected = (tee_k + 0.8) * airflow.velocity_pressure(AIR_DENSITY, vB)
    assert segB.CalcFittingLoss == pytest.approx(expected)
    assert junction_map["N3"].CalcLossWarning == ""


def test_unwired_terminal_marker_adds_nothing_beyond_its_upstream_fitting():
    # Default end_terminal_marker (or any type the registry doesn't
    # recognize) at a degree-1 node must NOT trigger the K_DEFAULT fallback
    # or a warning the way an unresolved degree>=2 fitting would -- most
    # terminals are intentionally non-physical placeholders. The segment's
    # fitting loss should still reflect its upstream fitting (J2, a real
    # tee) alone, unchanged by the fact that J3/J4 are unwired terminals.
    net, segment_map, junction_map = _base_tree()

    result = AirflowSolver(net).solve()

    assert result.warnings == []
    vB, _re, _f = _expected_segment(150.0, 3000.0, 50.0)
    vC, _re, _f = _expected_segment(150.0, 6000.0, 30.0)
    assert segment_map["B"].CalcFittingLoss == pytest.approx(FITTING_K * airflow.velocity_pressure(AIR_DENSITY, vB))
    assert segment_map["C"].CalcFittingLoss == pytest.approx(FITTING_K * airflow.velocity_pressure(AIR_DENSITY, vC))
    assert junction_map["N1"].CalcLossWarning == ""
    assert junction_map["N3"].CalcLossWarning == ""
    assert junction_map["N4"].CalcLossWarning == ""
