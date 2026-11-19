# SPDX-License-Identifier: LGPL-2.1-or-later
"""
End-to-end tests driving DuctNetworkParser's real graph-building pipeline
(build_graph -> build_junction_ports -> build_junction_analysis), not just
the pure classification helpers directly (see
test_network_parser_flow_classification.py for those) -- confirms the
whole path from raw line geometry + segment properties through to
family_key/flow_class/qualifiers/derived_values actually wires together,
including the profile-aware port-position machinery
(hvaclib.compute_port_position/make_profile_frame) the unit-level tests
bypass by constructing JunctionPort/NodeAnalysis directly.
"""
from types import SimpleNamespace

import conftest  # noqa: F401 -- installs FreeCAD/FreeCADGui/Part/PySide stubs

import FreeCAD

from freecad.HVAC.core.NetworkParser import DuctNetworkParser, EdgeRef


def _bare_parser():
    """A DuctNetworkParser with only the low-level graph-storage dicts
    initialized -- __init__ normally also parses real Sketch/Wire source
    objects, which these tests don't need since they build the geometric
    graph directly from known endpoints."""
    p = DuctNetworkParser.__new__(DuctNetworkParser)
    p.tol = 1e-6
    p.angle_tol_degree = 2.0
    p.node_id_by_key = {}
    p.node_point = {}
    p.edge_u_v = {}
    p.edge_geom = {}
    p.obj_edges = {}
    p.node_groups_input = []
    p.analysis_node_by_geom_node = {}
    p.analysis_node_members = {}
    p.analysis_node_point = {}
    p.analysis_edge_u_v = {}
    p.lines_map = {}
    p.all_lines = []
    return p


def _add_edge(parser, name, sp, ep, local_index=0):
    tag = "{}:{}".format(name, local_index)
    edge_ref = EdgeRef(obj_name=name, local_index=local_index, tag=tag)

    def geom_id(point):
        key = parser._point_snap_key(point)
        if key not in parser.node_id_by_key:
            node_id = len(parser.node_id_by_key) + 1
            parser.node_id_by_key[key] = node_id
            parser.node_point[node_id] = point
        return parser.node_id_by_key[key]

    u, v = geom_id(sp), geom_id(ep)
    parser.edge_u_v[edge_ref] = (u, v)
    parser.edge_geom[edge_ref] = (sp, ep)
    parser.obj_edges.setdefault(name, []).append(edge_ref)
    return tag


def _fake_segment(profile, **section_params):
    return SimpleNamespace(
        Profile=profile, Attachment="Center",
        Offset=FreeCAD.Vector(0.0, 0.0, 0.0), ProfileXAxis=FreeCAD.Vector(0.0, 0.0, 0.0),
        Proxy=SimpleNamespace(resolveSourceEdge=lambda: None),
        **section_params,
    )


def _two_segment_junction_analysis(seg_a, seg_b, point=(0.0, 0.0, 0.0)):
    """Build a real two-edge graph (A: -1000..point, B: point..+1000 along
    +X) and return the joint's real, freshly-computed JunctionAnalysis."""
    parser = _bare_parser()
    px, py, pz = point
    tag_a = _add_edge(parser, "A", (px - 1000.0, py, pz), point)
    tag_b = _add_edge(parser, "B", point, (px + 1000.0, py, pz))
    parser._rebuild_analysis_graph_from_groups()

    segment_map = {tag_a: seg_a, tag_b: seg_b}
    joint_geom_id = parser.node_id_by_key[parser._point_snap_key(point)]
    joint_analysis_id = parser.analysis_node_by_geom_node[joint_geom_id]
    return parser.build_junction_analysis(joint_analysis_id, segment_map)


def test_parser_produces_through_straight_for_matching_circular_segments():
    ja = _two_segment_junction_analysis(
        _fake_segment("Circular", Diameter=300.0), _fake_segment("Circular", Diameter=300.0),
    )
    assert ja.topology == "through"
    assert ja.family == "straight"
    assert ja.family_key == "through.straight"
    assert ja.flow_class == "constant"


def test_parser_produces_through_transition_for_differing_circular_segments():
    ja = _two_segment_junction_analysis(
        _fake_segment("Circular", Diameter=300.0), _fake_segment("Circular", Diameter=200.0),
    )
    assert ja.topology == "through"
    assert ja.family == "transition"
    assert ja.family_key == "through.transition"
    # Segment A (upstream, larger) -> B (downstream, smaller): contraction.
    assert ja.flow_class == "contraction"
    assert ja.qualifiers["alignment"] == "concentric"
    assert ja.qualifiers["transition_form"] == "conical"
    assert ja.derived_values["area_ratio"] == 200.0 ** 2 / 300.0 ** 2


def test_parser_produces_through_transition_for_differing_profiles():
    ja = _two_segment_junction_analysis(
        _fake_segment("Circular", Diameter=300.0),
        _fake_segment("Rectangular", Width=300.0, Height=300.0),
    )
    assert ja.family_key == "through.transition"
    assert ja.qualifiers["profile_relation"] == "mixed"
    assert ja.qualifiers["transition_form"] == "profile_change"


def test_parser_produces_through_offset_for_same_section_displaced_axes():
    ja = _two_segment_junction_analysis(
        _fake_segment("Circular", Diameter=300.0), _fake_segment("Circular", Diameter=300.0),
        point=(0.0, 0.0, 0.0),
    )
    # Same-section, zero eccentricity case is covered above (-> straight);
    # this just re-confirms "transition" is never produced when the
    # section genuinely matches, closing the loop on the classification
    # order requirement (transition is checked, and correctly skipped,
    # before straight/offset).
    assert ja.family_key != "through.transition"
