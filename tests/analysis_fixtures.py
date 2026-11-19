"""
Shared pure-Python builders for freecad.HVAC.analysis package tests. No
FreeCAD/conftest stubbing anywhere in this file or its callers -- proving
analysis/ genuinely has no such dependency (unlike every other test file in
this directory, which needs conftest's FreeCAD/Part/PySide stubs).
"""

from freecad.HVAC.analysis.loss import LossEvaluation, LossPath, LossStatus
from freecad.HVAC.analysis.model import (
    AirState, ComponentModel, NetworkModel, NodeModel, PortModel, SectionModel, SegmentModel,
)

AIR_DENSITY = 1.204
AIR_VISCOSITY = 1.51e-5
DEFAULT_ROUGHNESS_MM = 0.09


def circular_section(diameter_mm):
    return SectionModel(profile="Circular", diameter_mm=diameter_mm)


def port(edge_key, node_id, flow_into_node, section=None):
    return PortModel(edge_key=edge_key, node_id=node_id, flow_into_node=flow_into_node,
                      section=section or circular_section(0.0))


def primary(node_id, ports, loss_evaluator=None):
    return ComponentModel(component_id=node_id + "_Primary", role="primary", ports=ports,
                           loss_evaluator=loss_evaluator)


def air_state(density=AIR_DENSITY, viscosity=AIR_VISCOSITY):
    return AirState(density_kg_m3=density, kinematic_viscosity_m2_s=viscosity)


def wrap_legacy_loss_evaluator(raw_evaluator, ports):
    """
    Adapts a pre-LossEvaluation-refactor-style loss_evaluator (returning
    dict{edge_key: K} / a single float K applied to every outlet port /
    None) into the current LossEvaluator contract, so most fixture callers
    across this test suite can keep writing the same simple
    `lambda pv: K` / `lambda pv: {edge_key: K}` they always have -- those
    tests are exercising loss ATTRIBUTION/PROPAGATION through the solver,
    not the loss contract itself (see test_analysis_pressure.py for that).

    A raw_evaluator that already returns a real LossEvaluation (or None) is
    passed through unchanged -- lets a caller opt into building its own
    LossPaths directly (e.g. to test a converging tee, a FALLBACK/
    UNSUPPORTED status, or a custom `source`) without needing a second
    wrapping mechanism.
    """
    if raw_evaluator is None:
        return None

    outlets = [p for p in ports if p.flow_into_node is False]
    inlets = [p for p in ports if p.flow_into_node is True]
    # The "other side" every synthesized LossPath is referenced against --
    # only meaningful when there's a single port on the opposite flow side
    # (the shape every one of these legacy-style fixtures assumes).
    common_edge_key = None
    if len(inlets) == 1:
        common_edge_key = inlets[0].edge_key
    elif len(outlets) == 1:
        common_edge_key = outlets[0].edge_key

    def evaluate(port_velocities):
        raw = raw_evaluator(port_velocities)
        if raw is None or isinstance(raw, LossEvaluation):
            return raw
        if isinstance(raw, dict):
            paths = [
                LossPath(common_edge_key, edge_key, edge_key, float(k), source="test")
                for edge_key, k in raw.items() if k is not None
            ]
        else:
            paths = [
                LossPath(common_edge_key, p.edge_key, p.edge_key, float(raw), source="test")
                for p in outlets
            ]
        return LossEvaluation(paths=paths, status=LossStatus.EXACT)

    return evaluate


def base_tree(j3_flow=50.0, j4_flow=30.0, segA_len=5000.0, segB_len=3000.0, segC_len=6000.0,
              segA_dia=200.0, segB_dia=150.0, segC_dia=150.0, loss_evaluator=None,
              air=None, roughness_mm=DEFAULT_ROUGHNESS_MM,
              j1_flow_boundary="Auto", j3_flow_boundary="Fixed", j4_flow_boundary="Fixed"):
    """
    Same supply-tree topology as tests/network_fixtures.py's base_tree(),
    built directly as pure analysis.model dataclasses instead of FreeCAD
    fakes:

        J1 (AHU, balancing terminal) --A--> J2 (tee)
                                                |--B--> J3 (leaf, j3_flow L/s)
                                                '--C--> J4 (leaf, j4_flow L/s)

    loss_evaluator, if given, is J2's Primary's own loss_evaluator (e.g. a
    fixed-K tee) -- J1/J3/J4 never have one (matching end_terminal_marker's
    "no loss data" default).
    """
    n2_ports = [port("A", "N2", True), port("B", "N2", False), port("C", "N2", False)]
    nodes = {
        "N1": NodeModel("N1", "end", 1, [port("A", "N1", False)], 0.0,
                         flow_boundary=j1_flow_boundary,
                         primary_component=primary("N1", [port("A", "N1", False)])),
        "N2": NodeModel("N2", "branch", 3, n2_ports, 0.0,
                         primary_component=primary(
                             "N2", n2_ports, wrap_legacy_loss_evaluator(loss_evaluator, n2_ports))),
        "N3": NodeModel("N3", "end", 1, [port("B", "N3", True)], j3_flow,
                         flow_boundary=j3_flow_boundary,
                         primary_component=primary("N3", [port("B", "N3", True)])),
        "N4": NodeModel("N4", "end", 1, [port("C", "N4", True)], j4_flow,
                         flow_boundary=j4_flow_boundary,
                         primary_component=primary("N4", [port("C", "N4", True)])),
    }
    segments = {
        "A": SegmentModel("A", circular_section(segA_dia), segA_len, roughness_mm),
        "B": SegmentModel("B", circular_section(segB_dia), segB_len, roughness_mm),
        "C": SegmentModel("C", circular_section(segC_dia), segC_len, roughness_mm),
    }
    edges = {"A": ("N1", "N2"), "B": ("N2", "N3"), "C": ("N2", "N4")}
    return NetworkModel(nodes=nodes, segments=segments, edges=edges, air=air or air_state())


def converging_tree(j3_flow=50.0, j4_flow=30.0, segA_len=5000.0, segB_len=3000.0, segC_len=6000.0,
                     segA_dia=200.0, segB_dia=150.0, segC_dia=150.0, loss_evaluator=None,
                     air=None, roughness_mm=DEFAULT_ROUGHNESS_MM,
                     j1_flow_boundary="Auto", j3_flow_boundary="Fixed", j4_flow_boundary="Fixed"):
    """
    Converging-tee mirror of base_tree(): two sources merge into one sink,
    so the tee's own physically distinct loss coefficients belong to its
    two INLET legs (B, C) rather than its outlet (A) -- the shape
    base_tree()'s diverging tee can never exercise, and exactly the case
    the old outlet-only convention couldn't represent at all.

        J3 (leaf, source, j3_flow L/s) --B--\\
                                              >--A--> J1 (sink, balancing terminal)
        J4 (leaf, source, j4_flow L/s) --C--/

    loss_evaluator, if given, must return a real LossEvaluation with its
    own correctly-directed LossPaths (see wrap_legacy_loss_evaluator's own
    docstring) -- a converging tee's dict-shaped legacy result would be
    ambiguous about which side is "from"/"to", so this fixture doesn't try
    to guess it the way base_tree()'s wrapping does for a diverging shape.
    """
    n2_ports = [port("A", "N2", False), port("B", "N2", True), port("C", "N2", True)]
    nodes = {
        "N1": NodeModel("N1", "end", 1, [port("A", "N1", True)], 0.0,
                         flow_boundary=j1_flow_boundary,
                         primary_component=primary("N1", [port("A", "N1", True)])),
        "N2": NodeModel("N2", "branch", 3, n2_ports, 0.0,
                         primary_component=primary(
                             "N2", n2_ports, wrap_legacy_loss_evaluator(loss_evaluator, n2_ports))),
        "N3": NodeModel("N3", "end", 1, [port("B", "N3", False)], j3_flow,
                         flow_boundary=j3_flow_boundary,
                         primary_component=primary("N3", [port("B", "N3", False)])),
        "N4": NodeModel("N4", "end", 1, [port("C", "N4", False)], j4_flow,
                         flow_boundary=j4_flow_boundary,
                         primary_component=primary("N4", [port("C", "N4", False)])),
    }
    segments = {
        "A": SegmentModel("A", circular_section(segA_dia), segA_len, roughness_mm),
        "B": SegmentModel("B", circular_section(segB_dia), segB_len, roughness_mm),
        "C": SegmentModel("C", circular_section(segC_dia), segC_len, roughness_mm),
    }
    edges = {"A": ("N2", "N1"), "B": ("N3", "N2"), "C": ("N4", "N2")}
    return NetworkModel(nodes=nodes, segments=segments, edges=edges, air=air or air_state())
