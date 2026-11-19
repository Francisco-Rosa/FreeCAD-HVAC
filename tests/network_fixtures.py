"""
Shared lightweight fake stand-ins for the FreeCAD DuctNetwork/DuctJunction/
DuctSegment objects and the DuctNetworkParser API surface that FlowNetwork.py
(and therefore both AirflowSolver and DuctSizer) depends on. Lets solver
tests run against a small synthetic tree network without a real FreeCAD
installation or real base geometry.
"""

import json
from dataclasses import asdict

import conftest  # noqa: F401 -- installs FreeCAD/FreeCADGui/Part/PySide stubs

from freecad.HVAC.analysis.loss import LossEvaluation, LossPath, LossStatus
from freecad.HVAC.core.NetworkParser import EdgeRef, JunctionAnalysis, JunctionPort
from freecad.HVAC.utils.hvaclib import nx


AIR_DENSITY = 1.204
AIR_VISCOSITY = 1.51e-5
DEFAULT_ROUGHNESS_MM = 0.09


def legacy_loss_result(raw, context):
    """
    Converts a pre-LossEvaluation-refactor-style call_loss() return value
    (dict{edge_key: K} / a single float K applied to every outlet port /
    None) into a real LossEvaluation, using context["connected_ports"]'s
    own flow_into_junction to resolve each path's direction -- lets a test
    registry stub's own call_loss() keep returning the same simple
    dict/float/None shape it always has (these fixtures are testing solver
    wiring, not the loss contract itself -- see tests/test_loss_api.py for
    that).
    """
    if raw is None:
        return LossEvaluation(paths=[], status=LossStatus.UNSUPPORTED)

    ports = context.get("connected_ports") or []
    outlets = [p for p in ports if p.get("flow_into_junction") is False]
    inlets = [p for p in ports if p.get("flow_into_junction") is True]
    common_edge_key = None
    if len(inlets) == 1:
        common_edge_key = inlets[0]["edge_key"]
    elif len(outlets) == 1:
        common_edge_key = outlets[0]["edge_key"]

    if isinstance(raw, dict):
        paths = [
            LossPath(common_edge_key, edge_key, edge_key, float(k), source="test")
            for edge_key, k in raw.items() if k is not None
        ]
    else:
        paths = [
            LossPath(common_edge_key, p["edge_key"], p["edge_key"], float(raw), source="test")
            for p in outlets
        ]
    return LossEvaluation(paths=paths, status=LossStatus.EXACT)


class FakeObj:
    """Minimal stand-in for a FreeCAD DocumentObject: free attribute get/set."""

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


def _edge(tag):
    return EdgeRef(obj_name="Line_{}".format(tag), local_index=0, tag=tag)


def _port(edge_key, segment_end, flow_into_junction):
    return JunctionPort(
        edge_key=edge_key,
        segment_end=segment_end,
        position=(0.0, 0.0, 0.0),
        direction=(1.0, 0.0, 0.0),
        profile="Circular",
        section_params={},
        attachment="Center",
        user_offset=(0.0, 0.0, 0.0),
        profile_x_axis=None,
        flow_role=("inlet" if flow_into_junction else "outlet"),
        flow_direction=(1.0, 0.0, 0.0),
        flow_into_junction=flow_into_junction,
    )


class FakeParser:
    """
    analysis_graph/node_key/build_junction_analysis, driven from a plain
    description of {node_id: [(edge_tag, "start"|"end"), ...]}.

    analysis_graph mirrors the real NetworkParser's: a plain networkx Graph
    with each edge's real EdgeRef stored under the "key" attribute, matching
    NetworkParser._rebuild_analysis_graph_from_groups exactly -- FlowNetwork.py
    consumes this attribute directly rather than any parser method call.
    """

    def __init__(self, node_ports, edge_endpoints):
        # node_ports: {node_id: [(edge_tag, segment_end), ...]}
        # edge_endpoints: {edge_tag: (u, v)}  (u = "start" node, v = "end" node)
        self._node_ports = node_ports

        self.analysis_graph = nx.Graph()
        for tag, (u, v) in edge_endpoints.items():
            edge_ref = _edge(tag)
            self.analysis_graph.add_edge(u, v, key=edge_ref, obj=edge_ref.obj_name, local_index=edge_ref.local_index)

    def node_key(self, node_id):
        return "N{}".format(node_id)

    def node_ids(self):
        return list(self._node_ports.keys())

    def build_junction_analysis(self, node_id, segment_map):
        ports = [
            _port(tag, end, flow_into_junction=(end == "end"))
            for tag, end in self._node_ports[node_id]
        ]
        degree = len(ports)
        if degree <= 0:
            return None
        return JunctionAnalysis(
            topology=("end" if degree == 1 else "branch"),
            family="",
            family_tags=[],
            family_key="",
            flow_class="unknown",
            qualifiers={},
            derived_values={},
            connected_ports=ports,
            point=(0.0, 0.0, 0.0),
            degree=degree,
            port_origins=[],
            edge_vectors=[],
            edge_angles={},
            edge_eccentricities={},
            collinear_pairs=[],
            orthogonal_pairs=[],
            is_coplanar=True,
        )


class FakeProxy:
    def __init__(self, parser, segment_map, junction_map):
        self._parser = parser
        self._segment_map = segment_map
        self._junction_map = junction_map

    def getParser(self, rebuild=False):
        return self._parser

    def collectSegmentObjects(self):
        return dict(self._segment_map)

    def collectJunctionObjects(self):
        return dict(self._junction_map)


def make_segment(tag, diameter_mm, length_mm, roughness_mm=0.0, profile="Circular",
                  width_mm=0.0, height_mm=0.0, velocity_ms=0.0,
                  rectangular_sizing_mode="UseNetworkDefault", target_aspect_ratio=0.0):
    return FakeObj(
        Label=tag,
        SegmentKey=tag,
        Name=tag,
        Profile=profile,
        Diameter=diameter_mm,
        Width=width_mm,
        Height=height_mm,
        Roughness=roughness_mm,
        EffectiveLength=length_mm,
        Velocity=velocity_ms,
        RectangularSizingMode=rectangular_sizing_mode,
        TargetAspectRatio=target_aspect_ratio,
    )


class FakeJunctionProxy:
    """
    Stand-in for DuctJunction.Proxy: these solver tests only ever build
    single-component (Primary-only) junctions, so getComponents() always
    returns exactly that one fake DuctComponent and there are never any
    Inline chains.
    """

    def __init__(self, component):
        self.component = component

    def getComponents(self):
        return [self.component]

    def getPrimaryComponent(self):
        return self.component

    def getPortChains(self):
        return {}

    def getInlineComponents(self, edge_key=None):
        return []


class FakeJunctionObj(FakeObj):
    """
    Stand-in for a DuctJunction FreeCAD object. LibraryId/TypeId are
    convenience passthroughs to the junction's own (single, Primary) fake
    DuctComponent (self._component), so existing test code that pokes
    junction.TypeId/LibraryId directly (mirroring how these tests were
    written before physical-fitting ownership moved onto DuctComponent)
    keeps working unchanged.
    """

    def __init__(self, **kwargs):
        self._component = FakeObj(
            Label="", Name="", ComponentRole="Primary", AttachedEdgeKey="", PortSequence=0,
            LocalPortsJson="[]", ConnectionLengthsJson="[]", Family="",
            CalcFlowRate=0.0, CalcVelocity=0.0, CalcLossCoefficient=0.0, CalcPressureDrop=0.0,
        )
        self.Proxy = FakeJunctionProxy(self._component)
        super().__init__(**kwargs)
        if not self._component.Label:
            label = getattr(self, "Label", "Junction")
            self._component.Label = "{}_Comp0".format(label)
            self._component.Name = self._component.Label

    @property
    def LibraryId(self):
        return self._component.LibraryId

    @LibraryId.setter
    def LibraryId(self, value):
        self._component.LibraryId = value

    @property
    def TypeId(self):
        return self._component.TypeId

    @TypeId.setter
    def TypeId(self, value):
        self._component.TypeId = value


def make_junction(label, design_flow=0.0, flow_boundary=None, library_id="testlib", type_id="branch_tee_generic"):
    # flow_boundary=None keeps every existing caller's behavior unchanged:
    # a 0.0 design_flow defaults to "Auto" (the balancing terminal), any
    # other value defaults to "Fixed" -- exactly the old "0 means unset"
    # convention this fixture used to hardcode via DesignFlowRate alone.
    if flow_boundary is None:
        flow_boundary = "Auto" if design_flow == 0.0 else "Fixed"
    return FakeJunctionObj(
        Label=label,
        Name=label,
        Family="",
        DesignFlowRate=design_flow,
        FlowBoundary=flow_boundary,
        Topology="branch",
        LibraryId=library_id,
        TypeId=type_id,
    )


def make_net(parser, segment_map, junction_map, **extra_props):
    props = dict(
        AirDensity=AIR_DENSITY,
        AirKinematicViscosity=AIR_VISCOSITY,
        DefaultRoughness=DEFAULT_ROUGHNESS_MM,
    )
    props.update(extra_props)
    net = FakeObj(**props)
    net.Proxy = FakeProxy(parser, segment_map, junction_map)

    # Populate each junction's (single, Primary) fake component's
    # LocalPortsJson/Topology from the parser's own analysis, mirroring
    # what DuctJunction.composeComponents() does for a single-component
    # junction in the real system: a straight passthrough of the real
    # connected ports.
    for node_id in parser.node_ids():
        junction = junction_map.get(parser.node_key(node_id))
        if junction is None or not hasattr(junction, "_component"):
            continue
        ja = parser.build_junction_analysis(node_id, segment_map)
        junction.Topology = ja.topology
        junction._component.LocalPortsJson = json.dumps([asdict(p) for p in ja.connected_ports])

    return net


def base_tree(j3_flow=50.0, j4_flow=30.0, segA_len=5000.0, segB_len=3000.0, segC_len=6000.0,
              segA_dia=200.0, segB_dia=150.0, segC_dia=150.0,
              segA_kwargs=None, segB_kwargs=None, segC_kwargs=None, net_extra_props=None):
    """
    A simple supply tree, reused across solver tests:

        J1 (AHU, balancing terminal) --segA--> J2 (tee)
                                                    |--segB--> J3 (leaf, j3_flow L/s)
                                                    '--segC--> J4 (leaf, j4_flow L/s)
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
        "A": make_segment("A", segA_dia, segA_len, **(segA_kwargs or {})),
        "B": make_segment("B", segB_dia, segB_len, **(segB_kwargs or {})),
        "C": make_segment("C", segC_dia, segC_len, **(segC_kwargs or {})),
    }
    junction_map = {
        "N1": make_junction("J1", design_flow=0.0, type_id="end_terminal_marker"),
        "N2": make_junction("J2", design_flow=0.0, type_id="branch_tee_generic"),
        "N3": make_junction("J3", design_flow=j3_flow, type_id="end_terminal_marker"),
        "N4": make_junction("J4", design_flow=j4_flow, type_id="end_terminal_marker"),
    }
    net = make_net(parser, segment_map, junction_map, **(net_extra_props or {}))
    return net, segment_map, junction_map
