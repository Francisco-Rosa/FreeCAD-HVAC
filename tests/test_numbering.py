"""
Tests for core/Numbering.py's renumber_network(): the deterministic
source-outward traversal that assigns documentation-only D.../J.../
J...-P/J...-NN numbers and Labels.

Uses small self-contained fakes for the DuctNetworkParser/DuctNetwork
Proxy API surface renumber_network() actually calls (nodes()/node_xyz()/
node_key()/node_edges()/edge_analysis_nodes()/connected_components() on the
parser; getParser()/collectSegmentObjects()/collectJunctionObjects()/
collectComponentObjects() on the Proxy) -- the same style network_fixtures.py
already uses for FlowNetwork.py tests, but tailored to this module's own
(smaller) API surface.
"""

import conftest  # noqa: F401 -- installs FreeCAD/FreeCADGui/Part/PySide stubs

from freecad.HVAC.core.Numbering import renumber_network
from freecad.HVAC.core.NetworkParser import EdgeRef
from freecad.HVAC.utils import hvaclib


class FakeObj:
    """Free attribute get/set stand-in for a FreeCAD DocumentObject."""

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


def _edge(tag):
    return EdgeRef(obj_name="Line_{}".format(tag), local_index=0, tag=tag)


class FakeParser:
    """
    edges: {tag: (node_u, node_v)}
    points: {node_id: (x, y, z)}
    groups: optional list of connected-component node-id lists (defaults to
    one component covering every point).
    """

    def __init__(self, edges, points, groups=None):
        self._edge_refs = {tag: _edge(tag) for tag in edges}
        self._endpoints = dict(edges)
        self._points = dict(points)
        self._groups = groups if groups is not None else [sorted(points.keys())]

    def nodes(self):
        return sorted(self._points.keys())

    def node_xyz(self, node_id):
        return self._points[node_id]

    def node_key(self, node_id):
        return "N{}".format(node_id)

    def node_edges(self, node_id):
        return [
            self._edge_refs[tag] for tag, (u, v) in self._endpoints.items()
            if u == node_id or v == node_id
        ]

    def edge_analysis_nodes(self, edge_ref):
        return self._endpoints[edge_ref.tag]

    def connected_components(self):
        return [list(g) for g in self._groups]


def make_junction(name, topology="through", family="", design_flow=0.0, flow_boundary=None,
                   is_flow_source=False, library_id="", type_id=""):
    # flow_boundary=None mirrors network_fixtures.make_junction's own
    # backward-compatible default: a 0.0 design_flow means "Auto" (the
    # old "blank DesignFlowRate" balancing-terminal heuristic), any other
    # value means "Fixed".
    if flow_boundary is None:
        flow_boundary = "Auto" if design_flow == 0.0 else "Fixed"
    return FakeObj(
        Name=name, Label=name, Number="", Topology=topology, Family=family,
        DesignFlowRate=design_flow, FlowBoundary=flow_boundary, IsFlowSource=is_flow_source,
        LibraryId=library_id, TypeId=type_id,
    )


def make_segment(name, library_id="", type_id=""):
    return FakeObj(Name=name, Label=name, Number="", LibraryId=library_id, TypeId=type_id)


def make_component(name, parent_name, role, library_id="", type_id=""):
    return FakeObj(
        Name=name, Label=name, Number="", ParentJunctionName=parent_name,
        ComponentRole=role, LibraryId=library_id, TypeId=type_id,
    )


class FakeProxy:
    def __init__(self, parser, segment_map, junction_map, component_map):
        self._parser = parser
        self._segment_map = segment_map
        self._junction_map = junction_map
        self._component_map = component_map

    def getParser(self, rebuild=False):
        return self._parser

    def collectSegmentObjects(self):
        return dict(self._segment_map)

    def collectJunctionObjects(self):
        return dict(self._junction_map)

    def collectComponentObjects(self):
        return dict(self._component_map)


def make_net(parser, segment_map, junction_map, component_map=None):
    net = FakeObj()
    net.Proxy = FakeProxy(parser, segment_map, junction_map, component_map or {})
    return net


# ----------------------------------------------------------------------
# Straight run: N1 --A--> N2 --B--> N3, both ends flow-unset -> geometry
# fallback picks the lower-x terminal as the source.
# ----------------------------------------------------------------------

def _straight_run_net():
    parser = FakeParser(
        edges={"A": (1, 2), "B": (2, 3)},
        points={1: (0.0, 0.0, 0.0), 2: (5.0, 0.0, 0.0), 3: (10.0, 0.0, 0.0)},
    )
    junction_map = {
        "N1": make_junction("J_N1", topology="end"),
        "N2": make_junction("J_N2", topology="through"),
        "N3": make_junction("J_N3", topology="end"),
    }
    segment_map = {"A": make_segment("Seg_A"), "B": make_segment("Seg_B")}
    net = make_net(parser, segment_map, junction_map)
    return net, segment_map, junction_map


def test_straight_run_numbers_sequentially_from_lower_point_terminal():
    net, segment_map, junction_map = _straight_run_net()

    result = renumber_network(net)

    assert junction_map["N1"].Number == "J001"
    assert segment_map["A"].Number == "D001"
    assert junction_map["N2"].Number == "J002"
    assert segment_map["B"].Number == "D002"
    assert junction_map["N3"].Number == "J003"
    assert result.segment_count == 2
    assert result.junction_count == 3
    assert result.changed is True


def test_labels_use_family_and_type_label_with_generic_fallbacks():
    net, segment_map, junction_map = _straight_run_net()
    junction_map["N2"].Family = "tee"

    renumber_network(net)

    assert junction_map["N1"].Label == "J001 — Junction"  # no Family set -> generic fallback
    assert junction_map["N2"].Label == "J002 — Tee"
    assert segment_map["A"].Label == "D001 — Duct"  # no LibraryId/TypeId -> generic fallback


def test_labels_use_resolved_library_type_when_available():
    net, segment_map, junction_map = _straight_run_net()
    junction_map["N2"].LibraryId = None  # junctions never carry a type of their own
    segment_map["A"].LibraryId = "smacna"
    segment_map["A"].TypeId = "through_transition_concentric"

    renumber_network(net)

    reg = hvaclib.HVACLibraryService.get_hvac_library_registry()
    type_def = reg.resolve_type("smacna", "through_transition_concentric")
    assert segment_map["A"].Label == "D001 — {}".format(type_def.label)


def test_repeated_renumber_without_topology_change_is_idempotent():
    net, segment_map, junction_map = _straight_run_net()

    renumber_network(net)
    numbers_first = {k: v.Number for k, v in {**segment_map, **junction_map}.items()}

    result_second = renumber_network(net)
    numbers_second = {k: v.Number for k, v in {**segment_map, **junction_map}.items()}

    assert numbers_first == numbers_second
    assert result_second.changed is False


# ----------------------------------------------------------------------
# Branching tee: J1 (unset flow, the source) -- A --> J2 -- B --> J3 (leaf)
#                                                    '-- C --> J4 (leaf)
# J3 sits at a lower point than J4, so it must be visited (and numbered)
# first regardless of which order the fixture lists them in.
# ----------------------------------------------------------------------

def _tee_net(j1_point=(0.0, 0.0, 0.0)):
    parser = FakeParser(
        edges={"A": (1, 2), "B": (2, 3), "C": (2, 4)},
        points={
            1: j1_point,
            2: (5.0, 0.0, 0.0),
            3: (10.0, -1.0, 0.0),  # lower point -> visited first
            4: (10.0, 1.0, 0.0),
        },
    )
    junction_map = {
        "N1": make_junction("J1", topology="end", design_flow=0.0),
        "N2": make_junction("J2", topology="branch"),
        "N3": make_junction("J3", topology="end", design_flow=50.0),
        "N4": make_junction("J4", topology="end", design_flow=30.0),
    }
    segment_map = {"A": make_segment("Seg_A"), "B": make_segment("Seg_B"), "C": make_segment("Seg_C")}
    net = make_net(parser, segment_map, junction_map)
    return net, segment_map, junction_map


def test_branch_order_is_broken_by_neighbor_point():
    net, segment_map, junction_map = _tee_net()

    renumber_network(net)

    # J1 (only terminal with no design flow rate) is the source.
    assert junction_map["N1"].Number == "J001"
    assert segment_map["A"].Number == "D001"
    assert junction_map["N2"].Number == "J002"
    # J3 has the lower point at the branch -> walked before J4.
    assert segment_map["B"].Number == "D002"
    assert junction_map["N3"].Number == "J003"
    assert segment_map["C"].Number == "D003"
    assert junction_map["N4"].Number == "J004"


def test_unset_flow_terminal_is_chosen_as_source_over_geometry_fallback():
    # Put J1 at a higher x than the leaves so pure geometry would NOT pick
    # it -- the blank-DesignFlowRate heuristic must still win.
    net, segment_map, junction_map = _tee_net(j1_point=(20.0, 0.0, 0.0))

    renumber_network(net)

    assert junction_map["N1"].Number == "J001"


def test_closed_terminal_is_not_treated_as_the_auto_balancing_candidate():
    # J1 (the geometrically-lowest terminal, so it would win any fallback
    # tie) is Closed instead of Auto; J4 is the genuine Auto candidate.
    # Under the old "0 means unset" convention a Closed terminal at 0 L/s
    # would have looked identical to a real balancing terminal -- it must
    # not be picked here.
    net, segment_map, junction_map = _tee_net()
    junction_map["N1"].FlowBoundary = "Closed"
    junction_map["N4"].FlowBoundary = "Auto"

    renumber_network(net)

    assert junction_map["N4"].Number == "J001"


def test_flow_source_flag_is_preferred_over_blank_flow_heuristic():
    net, segment_map, junction_map = _tee_net()
    # Simulate a stale/edited Flow Condition on J1 alongside a previously
    # solved IsFlowSource -- the solved flag should win.
    junction_map["N1"].FlowBoundary = "Fixed"
    junction_map["N1"].DesignFlowRate = 5.0
    junction_map["N1"].IsFlowSource = True

    renumber_network(net)

    assert junction_map["N1"].Number == "J001"


# ----------------------------------------------------------------------
# Component numbering: Primary + Inline chain on one junction.
# ----------------------------------------------------------------------

def test_component_numbering_primary_then_inline_sequence():
    net, segment_map, junction_map = _straight_run_net()
    junction_map["N2"].Family = "straight"

    primary = make_component("N2_Comp0", "J_N2", "Primary", library_id="smacna", type_id="through_transition_concentric")
    inline1 = make_component("N2_Comp1", "J_N2", "Inline")
    inline2 = make_component("N2_Comp2", "J_N2", "Inline")
    net.Proxy._component_map = {"J_N2": [primary, inline1, inline2]}

    result = renumber_network(net)

    assert primary.Number == "J002-P"
    assert inline1.Number == "J002-01"
    assert inline2.Number == "J002-02"
    assert inline1.Label == "J002-01 — Component"
    assert result.component_count == 3


# ----------------------------------------------------------------------
# Non-tree (loop) sub-network: no terminal exists, but every edge/node
# must still get a number, and a warning should flag the ambiguity.
# ----------------------------------------------------------------------

def test_loop_network_still_numbers_everything_and_warns():
    parser = FakeParser(
        edges={"A": (1, 2), "B": (2, 3), "C": (3, 1)},
        points={1: (0.0, 0.0, 0.0), 2: (5.0, 0.0, 0.0), 3: (5.0, 5.0, 0.0)},
    )
    junction_map = {
        "N1": make_junction("J1", topology="branch"),
        "N2": make_junction("J2", topology="branch"),
        "N3": make_junction("J3", topology="branch"),
    }
    segment_map = {"A": make_segment("Seg_A"), "B": make_segment("Seg_B"), "C": make_segment("Seg_C")}
    net = make_net(parser, segment_map, junction_map)

    result = renumber_network(net)

    assert result.junction_count == 3
    assert result.segment_count == 3
    assert any("loop" in w.lower() for w in result.warnings)
    # Lowest point (N1) still deterministically wins as the walk's start.
    assert junction_map["N1"].Number == "J001"


# ----------------------------------------------------------------------
# Multiple disjoint sub-networks: numbered continuously, ordered by each
# sub-network's own chosen root point.
# ----------------------------------------------------------------------

def test_multiple_subnetworks_are_numbered_in_root_point_order():
    parser = FakeParser(
        edges={"A": (1, 2), "B": (10, 20)},
        points={1: (100.0, 0.0, 0.0), 2: (105.0, 0.0, 0.0), 10: (0.0, 0.0, 0.0), 20: (5.0, 0.0, 0.0)},
        groups=[[1, 2], [10, 20]],
    )
    junction_map = {
        "N1": make_junction("J_far_a", topology="end"),
        "N2": make_junction("J_far_b", topology="end"),
        "N10": make_junction("J_near_a", topology="end"),
        "N20": make_junction("J_near_b", topology="end"),
    }
    segment_map = {"A": make_segment("Seg_A"), "B": make_segment("Seg_B")}
    net = make_net(parser, segment_map, junction_map)

    renumber_network(net)

    # The sub-network whose chosen root has the lower point (N10/N20,
    # x=0..5) must be numbered entirely before the other one (N1/N2, x=100+).
    assert junction_map["N10"].Number == "J001"
    assert segment_map["B"].Number == "D001"
    assert junction_map["N20"].Number == "J002"
    assert junction_map["N1"].Number == "J003"
    assert segment_map["A"].Number == "D002"
    assert junction_map["N2"].Number == "J004"
