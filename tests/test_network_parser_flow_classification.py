# SPDX-License-Identifier: LGPL-2.1-or-later
"""
Focused tests for DuctNetworkParser's flow classification layer
(classify_flow / classify_junction_family's degree-2 family split) -- see
freecad/HVAC/core/NetworkParser.py and TOPOLOGY_CLASSIFICATION.md.

These call the parser's own pure classification helpers directly against
hand-built JunctionPort/EdgePair data, rather than driving the full
geometric-graph pipeline -- the geometric graph (collinear_pairs/
edge_eccentricities/...) is already covered by the existing family
classification behavior; only the new flow_class/qualifiers/derived_values
logic layered on top of it is under test here.
"""
import math

import conftest  # noqa: F401 -- installs FreeCAD/FreeCADGui/Part/PySide stubs
import pytest

from freecad.HVAC.core.NetworkParser import DuctNetworkParser, EdgePair, JunctionPort


def _parser():
    p = DuctNetworkParser.__new__(DuctNetworkParser)
    p.tol = 1e-6
    p.angle_tol_degree = 2.0
    return p


def _port(profile, w=None, h=None, d=None, position=(0.0, 0.0, 0.0), direction=(0.0, 0.0, 1.0),
          profile_x_axis=(1.0, 0.0, 0.0), flow_role="unknown", edge_key="A"):
    section = {"Diameter": d} if profile == "Circular" else {"Width": w, "Height": h}
    return JunctionPort(
        edge_key=edge_key, segment_end="end", position=position, direction=direction,
        profile=profile, section_params=section, attachment="Center",
        user_offset=(0.0, 0.0, 0.0), profile_x_axis=profile_x_axis,
        flow_role=flow_role, flow_direction=direction, flow_into_junction=None,
    )


class _NodeAnalysis:
    """Minimal duck-typed stand-in -- only the attributes the classifiers
    under test actually read (classify_junction_family reads several
    geometric fields unconditionally before branching on degree)."""

    def __init__(self, connected_ports, collinear_pairs=(), edge_eccentricities=None, degree=None):
        self.connected_ports = connected_ports
        self.collinear_pairs = list(collinear_pairs)
        self.edge_eccentricities = dict(edge_eccentricities or {})
        self.degree = degree if degree is not None else len(connected_ports)
        self.port_origins = [p.position for p in connected_ports]
        self.edge_vectors = [p.direction for p in connected_ports]
        # Derived the same way node_analysis()/_edge_angles() do in
        # production -- pairwise angle between each two ports' own
        # `direction`, keyed by the sorted index pair -- so tests exercise
        # the same precomputed lookup _pair_angle_lookup()/branch_angle
        # actually read from, rather than a hand-picked stand-in.
        self.edge_angles = {
            str((i, j)): DuctNetworkParser._angle_bw_vectors(self.edge_vectors[i], self.edge_vectors[j])
            for i in range(len(connected_ports))
            for j in range(i + 1, len(connected_ports))
        }
        self.orthogonal_pairs = []
        self.is_coplanar = True


# ----------------------------------------------------------------------
# classify_junction_family: degree-2 straight/offset/transition split
# ----------------------------------------------------------------------

def test_degree2_same_section_zero_eccentricity_is_straight():
    parser = _parser()
    ports = [_port("Circular", d=300.0), _port("Circular", d=300.0)]
    analysis = _NodeAnalysis(
        ports, collinear_pairs=[EdgePair(a=0, b=1, angle=180.0, eccentricity=0.0)],
        edge_eccentricities={str((0, 1)): 0.0},
    )
    family, tags = parser.classify_junction_family(analysis)
    assert (family, tags) == ("straight", [])


def test_degree2_same_section_nonzero_eccentricity_is_offset():
    parser = _parser()
    ports = [_port("Circular", d=300.0), _port("Circular", d=300.0)]
    analysis = _NodeAnalysis(
        ports, collinear_pairs=[EdgePair(a=0, b=1, angle=180.0, eccentricity=5.0)],
        edge_eccentricities={str((0, 1)): 5.0},
    )
    family, tags = parser.classify_junction_family(analysis)
    assert (family, tags) == ("offset", [])


def test_degree2_different_size_is_transition_even_with_zero_eccentricity():
    parser = _parser()
    ports = [_port("Circular", d=300.0), _port("Circular", d=200.0)]
    analysis = _NodeAnalysis(
        ports, collinear_pairs=[EdgePair(a=0, b=1, angle=180.0, eccentricity=0.0)],
        edge_eccentricities={str((0, 1)): 0.0},
    )
    family, tags = parser.classify_junction_family(analysis)
    assert (family, tags) == ("transition", [])


def test_degree2_different_profile_is_transition():
    parser = _parser()
    ports = [_port("Circular", d=300.0), _port("Rectangular", w=300.0, h=300.0)]
    analysis = _NodeAnalysis(
        ports, collinear_pairs=[EdgePair(a=0, b=1, angle=180.0, eccentricity=0.0)],
        edge_eccentricities={str((0, 1)): 0.0},
    )
    family, tags = parser.classify_junction_family(analysis)
    assert (family, tags) == ("transition", [])


# ----------------------------------------------------------------------
# classify_flow (through, degree 2): expansion/contraction/constant + area_ratio
# ----------------------------------------------------------------------

def test_through_flow_expansion_area_ratio():
    parser = _parser()
    inlet = _port("Circular", d=200.0, flow_role="inlet")
    outlet = _port("Circular", d=300.0, flow_role="outlet")
    flow_class, qualifiers, derived = parser._classify_through_flow(inlet, outlet)
    assert flow_class == "expansion"
    assert derived["area_ratio"] == pytest.approx((300.0 ** 2) / (200.0 ** 2))
    assert qualifiers["profile_relation"] == "same"


def test_through_flow_contraction():
    parser = _parser()
    inlet = _port("Circular", d=300.0, flow_role="inlet")
    outlet = _port("Circular", d=200.0, flow_role="outlet")
    flow_class, _, derived = parser._classify_through_flow(inlet, outlet)
    assert flow_class == "contraction"
    assert derived["area_ratio"] == pytest.approx((200.0 ** 2) / (300.0 ** 2))


def test_through_flow_constant_same_area():
    parser = _parser()
    inlet = _port("Circular", d=300.0, flow_role="inlet")
    outlet = _port("Circular", d=300.0, flow_role="outlet")
    flow_class, _, derived = parser._classify_through_flow(inlet, outlet)
    assert flow_class == "constant"
    assert derived["area_ratio"] == pytest.approx(1.0)


def test_through_flow_mixed_profile_relation_and_transition_form():
    parser = _parser()
    inlet = _port("Rectangular", w=300.0, h=200.0, flow_role="inlet")
    outlet = _port("Circular", d=250.0, flow_role="outlet")
    _, qualifiers, _ = parser._classify_through_flow(inlet, outlet)
    assert qualifiers["profile_relation"] == "mixed"
    assert qualifiers["transition_form"] == "profile_change"


# ----------------------------------------------------------------------
# Rectangular transition alignment (concentric/eccentric/double_eccentric/offset)
# ----------------------------------------------------------------------
# inlet is a 400x300 rectangle with its local frame pinned by profile_x_axis
# so local_x == world +X ("left") and local_y == world +Y ("top") -- see
# hvaclib.compute_port_position's own "X -> Left, Y -> Top" convention.
# outlet is a smaller 200x150 rectangle offset in the inlet's local frame.

def _rect_ports(dx, dy, w_out=200.0, h_out=150.0):
    inlet = _port(
        "Rectangular", w=400.0, h=300.0, position=(0.0, 0.0, 0.0),
        direction=(0.0, 0.0, 1.0), profile_x_axis=(1.0, 0.0, 0.0), flow_role="inlet",
    )
    outlet = _port(
        "Rectangular", w=w_out, h=h_out, position=(dx, dy, 0.0),
        direction=(0.0, 0.0, -1.0), flow_role="outlet",
    )
    return inlet, outlet


def test_alignment_concentric():
    parser = _parser()
    inlet, outlet = _rect_ports(0.0, 0.0)
    _, qualifiers, _ = parser._classify_through_flow(inlet, outlet)
    assert qualifiers["alignment"] == "concentric"


def test_alignment_eccentric_top():
    parser = _parser()
    # half_dh = (150-300)/2 = -75; top alignment needs delta_y = -half_dh = 75.
    inlet, outlet = _rect_ports(0.0, 75.0)
    _, qualifiers, _ = parser._classify_through_flow(inlet, outlet)
    assert qualifiers["alignment"] == "eccentric"
    assert qualifiers["aligned_side"] == "top"


def test_alignment_eccentric_right():
    parser = _parser()
    # half_dw = (200-400)/2 = -100; right alignment needs delta_x = half_dw = -100.
    inlet, outlet = _rect_ports(-100.0, 0.0)
    _, qualifiers, _ = parser._classify_through_flow(inlet, outlet)
    assert qualifiers["alignment"] == "eccentric"
    assert qualifiers["aligned_side"] == "right"


def test_alignment_double_eccentric_top_left():
    parser = _parser()
    inlet, outlet = _rect_ports(100.0, 75.0)
    _, qualifiers, _ = parser._classify_through_flow(inlet, outlet)
    assert qualifiers["alignment"] == "double_eccentric"
    assert qualifiers["aligned_corner"] == "top_left"


def test_alignment_offset_when_no_edges_line_up():
    parser = _parser()
    inlet, outlet = _rect_ports(50.0, 20.0)
    _, qualifiers, _ = parser._classify_through_flow(inlet, outlet)
    assert qualifiers["alignment"] == "offset"
    assert "aligned_side" not in qualifiers
    assert "aligned_corner" not in qualifiers


def test_alignment_eccentric_bottom():
    parser = _parser()
    # half_dh = -75; bottom alignment needs delta_y = half_dh = -75.
    inlet, outlet = _rect_ports(0.0, -75.0)
    _, qualifiers, _ = parser._classify_through_flow(inlet, outlet)
    assert qualifiers["alignment"] == "eccentric"
    assert qualifiers["aligned_side"] == "bottom"


def test_alignment_eccentric_left():
    parser = _parser()
    # half_dw = -100; left alignment needs delta_x = -half_dw = 100.
    inlet, outlet = _rect_ports(100.0, 0.0)
    _, qualifiers, _ = parser._classify_through_flow(inlet, outlet)
    assert qualifiers["alignment"] == "eccentric"
    assert qualifiers["aligned_side"] == "left"


def test_alignment_double_eccentric_top_right():
    parser = _parser()
    inlet, outlet = _rect_ports(-100.0, 75.0)
    _, qualifiers, _ = parser._classify_through_flow(inlet, outlet)
    assert qualifiers["alignment"] == "double_eccentric"
    assert qualifiers["aligned_corner"] == "top_right"


def test_alignment_double_eccentric_bottom_left():
    parser = _parser()
    inlet, outlet = _rect_ports(100.0, -75.0)
    _, qualifiers, _ = parser._classify_through_flow(inlet, outlet)
    assert qualifiers["alignment"] == "double_eccentric"
    assert qualifiers["aligned_corner"] == "bottom_left"


def test_alignment_double_eccentric_bottom_right():
    parser = _parser()
    inlet, outlet = _rect_ports(-100.0, -75.0)
    _, qualifiers, _ = parser._classify_through_flow(inlet, outlet)
    assert qualifiers["alignment"] == "double_eccentric"
    assert qualifiers["aligned_corner"] == "bottom_right"


def test_alignment_uses_inlet_flow_direction_not_outward_direction():
    # inlet.direction points opposite to inlet.flow_direction, exactly like
    # a real inlet port (see build_junction_ports()): `direction` points
    # away from the junction/upstream, `flow_direction` points downstream.
    # Alignment must be computed from flow_direction (the same vector
    # compute_port_position() used against ProfileXAxis when placing this
    # port), not from `direction` -- using the wrong one would silently
    # flip the local frame's Y axis and mislabel top<->bottom.
    parser = _parser()
    inlet = JunctionPort(
        edge_key="A", segment_end="end", position=(0.0, 0.0, 0.0), direction=(0.0, 0.0, -1.0),
        profile="Rectangular", section_params={"Width": 400.0, "Height": 300.0}, attachment="Center",
        user_offset=(0.0, 0.0, 0.0), profile_x_axis=(1.0, 0.0, 0.0),
        flow_role="inlet", flow_direction=(0.0, 0.0, 1.0), flow_into_junction=True,
    )
    outlet = _port(
        "Rectangular", w=200.0, h=150.0, position=(0.0, 75.0, 0.0),
        direction=(0.0, 0.0, -1.0), flow_role="outlet",
    )
    _, qualifiers, _ = parser._classify_through_flow(inlet, outlet)
    assert qualifiers["alignment"] == "eccentric"
    assert qualifiers["aligned_side"] == "top"


def test_transition_form_single_plane_vs_pyramidal():
    parser = _parser()
    single_plane_in, single_plane_out = _rect_ports(0.0, 0.0, w_out=200.0, h_out=300.0)
    _, q1, _ = parser._classify_through_flow(single_plane_in, single_plane_out)
    assert q1["transition_form"] == "single_plane"

    pyramidal_in, pyramidal_out = _rect_ports(0.0, 0.0, w_out=200.0, h_out=150.0)
    _, q2, _ = parser._classify_through_flow(pyramidal_in, pyramidal_out)
    assert q2["transition_form"] == "pyramidal"


def test_transition_form_conical():
    parser = _parser()
    inlet = _port("Circular", d=300.0, flow_role="inlet")
    outlet = _port("Circular", d=200.0, flow_role="outlet")
    _, qualifiers, _ = parser._classify_through_flow(inlet, outlet)
    assert qualifiers["transition_form"] == "conical"


def test_transition_form_profile_change():
    parser = _parser()
    inlet = _port("Rectangular", w=300.0, h=200.0, flow_role="inlet")
    outlet = _port("Circular", d=250.0, flow_role="outlet")
    _, qualifiers, _ = parser._classify_through_flow(inlet, outlet)
    assert qualifiers["transition_form"] == "profile_change"


def test_transition_form_unknown_for_oval_size_change():
    # A real change occurred, but Oval isn't reliably classifiable into
    # conical/pyramidal/single_plane -- never silently forced into either.
    parser = _parser()
    inlet = _port("Oval", w=400.0, h=200.0, flow_role="inlet")
    outlet = _port("Oval", w=300.0, h=150.0, flow_role="outlet")
    _, qualifiers, _ = parser._classify_through_flow(inlet, outlet)
    assert qualifiers["transition_form"] == "unknown"


# ----------------------------------------------------------------------
# Circular / Oval transition alignment (concentric / eccentric only --
# no side/corner concept for a round or oval section)
# ----------------------------------------------------------------------

def _round_ports(profile, dx, dy, dz=0.0, w_in=None, h_in=None, d_in=None, w_out=None, h_out=None, d_out=None):
    inlet = _port(
        profile, w=w_in, h=h_in, d=d_in, position=(0.0, 0.0, 0.0),
        direction=(0.0, 0.0, 1.0), profile_x_axis=(1.0, 0.0, 0.0), flow_role="inlet",
    )
    outlet = _port(
        profile, w=w_out, h=h_out, d=d_out, position=(dx, dy, dz),
        direction=(0.0, 0.0, -1.0), flow_role="outlet",
    )
    return inlet, outlet


def test_alignment_circular_concentric():
    parser = _parser()
    inlet, outlet = _round_ports("Circular", 0.0, 0.0, d_in=300.0, d_out=200.0)
    _, qualifiers, _ = parser._classify_through_flow(inlet, outlet)
    assert qualifiers["alignment"] == "concentric"


def test_alignment_circular_eccentric_when_edges_are_tangent():
    # A classic round eccentric reducer: the smaller duct's edge is
    # exactly tangent to the larger duct's edge on one side -- offset
    # magnitude equals the radius difference (here along the local X
    # axis, but any single axis works since a circle has no preferred
    # side of its own).
    parser = _parser()
    inlet, outlet = _round_ports("Circular", 50.0, 0.0, d_in=300.0, d_out=200.0)
    _, qualifiers, _ = parser._classify_through_flow(inlet, outlet)
    assert qualifiers["alignment"] == "eccentric"
    assert "aligned_side" not in qualifiers
    assert "aligned_corner" not in qualifiers


def test_alignment_circular_offset_when_edges_are_not_tangent():
    # Same duct sizes, but an arbitrary offset that doesn't bring the
    # edges tangent on either local axis -- not a "sides aligned" case,
    # so this must read "offset", not "eccentric".
    parser = _parser()
    inlet, outlet = _round_ports("Circular", 30.0, 0.0, d_in=300.0, d_out=200.0)
    _, qualifiers, _ = parser._classify_through_flow(inlet, outlet)
    assert qualifiers["alignment"] == "offset"


def test_alignment_oval_concentric():
    parser = _parser()
    inlet, outlet = _round_ports("Oval", 0.0, 0.0, w_in=400.0, h_in=200.0, w_out=300.0, h_out=150.0)
    _, qualifiers, _ = parser._classify_through_flow(inlet, outlet)
    assert qualifiers["alignment"] == "concentric"


def test_alignment_oval_eccentric_when_a_side_is_aligned():
    parser = _parser()
    # half_dh = (150-200)/2 = -25 -- top alignment needs delta_y = -half_dh = 25.
    inlet, outlet = _round_ports("Oval", 0.0, 25.0, w_in=400.0, h_in=200.0, w_out=300.0, h_out=150.0)
    _, qualifiers, _ = parser._classify_through_flow(inlet, outlet)
    assert qualifiers["alignment"] == "eccentric"
    assert "aligned_side" not in qualifiers
    assert "aligned_corner" not in qualifiers


def test_alignment_oval_offset_when_no_side_is_aligned():
    parser = _parser()
    inlet, outlet = _round_ports("Oval", 10.0, 10.0, w_in=400.0, h_in=200.0, w_out=300.0, h_out=150.0)
    _, qualifiers, _ = parser._classify_through_flow(inlet, outlet)
    assert qualifiers["alignment"] == "offset"


def test_alignment_unknown_for_mixed_profile_family():
    # Rectangular <-> Circular: alignment isn't well-defined across
    # different section-shape families.
    parser = _parser()
    inlet = _port("Rectangular", w=300.0, h=200.0, flow_role="inlet")
    outlet = _port("Circular", d=250.0, flow_role="outlet")
    _, qualifiers, _ = parser._classify_through_flow(inlet, outlet)
    assert qualifiers["alignment"] == "unknown"


# ----------------------------------------------------------------------
# expansion/contraction flips with base-segment orientation, never with
# argument order (requirement: base-segment orientation is authoritative,
# resolved purely from flow_role)
# ----------------------------------------------------------------------

def test_flow_class_independent_of_port_argument_order():
    parser = _parser()
    small = _port("Circular", d=200.0, flow_role="inlet")
    large = _port("Circular", d=300.0, flow_role="outlet")
    assert parser._classify_through_flow(small, large)[0] == "expansion"
    assert parser._classify_through_flow(large, small)[0] == "expansion"


def test_flow_class_reverses_with_base_segment_orientation():
    parser = _parser()
    forward_in = _port("Circular", d=200.0, flow_role="inlet")
    forward_out = _port("Circular", d=300.0, flow_role="outlet")
    assert parser._classify_through_flow(forward_in, forward_out)[0] == "expansion"

    # Same two duct sizes, but base-segment orientation (flow_role) is
    # reversed -- flow_class must flip to contraction accordingly.
    reversed_in = _port("Circular", d=300.0, flow_role="inlet")
    reversed_out = _port("Circular", d=200.0, flow_role="outlet")
    assert parser._classify_through_flow(reversed_in, reversed_out)[0] == "contraction"


# ----------------------------------------------------------------------
# classify_flow (branch, degree 3): diverging/converging + common_leg
# ----------------------------------------------------------------------

def test_branch_ordinary_dividing_tee_common_leg_is_run():
    parser = _parser()
    ports = [
        _port("Circular", d=300.0, flow_role="inlet", edge_key="run_a"),
        _port("Circular", d=300.0, flow_role="outlet", edge_key="run_b"),
        _port("Circular", d=200.0, flow_role="outlet", edge_key="branch"),
    ]
    analysis = _NodeAnalysis(ports, collinear_pairs=[EdgePair(a=0, b=1, angle=180.0, eccentricity=0.0)])
    flow_class, qualifiers, derived = parser._classify_branch_flow(ports, analysis)
    assert flow_class == "diverging"
    assert qualifiers["common_leg"] == "run"
    assert derived["area_ratio"] == pytest.approx((200.0 ** 2) / (300.0 ** 2))


def test_branch_bullhead_dividing_tee_common_leg_is_branch():
    parser = _parser()
    ports = [
        _port("Circular", d=300.0, flow_role="outlet", edge_key="run_a"),
        _port("Circular", d=300.0, flow_role="outlet", edge_key="run_b"),
        _port("Circular", d=200.0, flow_role="inlet", edge_key="branch"),
    ]
    analysis = _NodeAnalysis(ports, collinear_pairs=[EdgePair(a=0, b=1, angle=180.0, eccentricity=0.0)])
    flow_class, qualifiers, derived = parser._classify_branch_flow(ports, analysis)
    assert flow_class == "diverging"
    assert qualifiers["common_leg"] == "branch"


def test_branch_converging_tee_common_leg_is_run():
    parser = _parser()
    ports = [
        _port("Circular", d=300.0, flow_role="inlet", edge_key="run_a"),
        _port("Circular", d=300.0, flow_role="outlet", edge_key="run_b"),
        _port("Circular", d=200.0, flow_role="inlet", edge_key="branch"),
    ]
    analysis = _NodeAnalysis(ports, collinear_pairs=[EdgePair(a=0, b=1, angle=180.0, eccentricity=0.0)])
    flow_class, qualifiers, _ = parser._classify_branch_flow(ports, analysis)
    assert flow_class == "converging"
    assert qualifiers["common_leg"] == "run"


def test_branch_wye_has_no_common_leg():
    # No collinear pair at all -- a symmetric wye has no geometrically
    # identified run, so common_leg is never set.
    parser = _parser()
    ports = [
        _port("Circular", d=200.0, flow_role="inlet"),
        _port("Circular", d=200.0, flow_role="outlet"),
        _port("Circular", d=200.0, flow_role="outlet"),
    ]
    analysis = _NodeAnalysis(ports, collinear_pairs=[])
    flow_class, qualifiers, derived = parser._classify_branch_flow(ports, analysis)
    assert flow_class == "diverging"
    assert "common_leg" not in qualifiers
    assert "area_ratio" not in derived


# ----------------------------------------------------------------------
# _resolve_inlet_outlet: unresolved direction must never fall back to an
# arbitrary port order -- flow_class stays "unknown" and nothing
# direction-dependent gets computed.
# ----------------------------------------------------------------------

def test_resolve_inlet_outlet_returns_none_when_both_ports_are_inlets():
    parser = _parser()
    port_a = _port("Circular", d=300.0, flow_role="inlet")
    port_b = _port("Circular", d=300.0, flow_role="inlet")
    assert parser._resolve_inlet_outlet(port_a, port_b) == (None, None)


def test_resolve_inlet_outlet_returns_none_when_role_unresolved():
    parser = _parser()
    port_a = _port("Circular", d=300.0, flow_role="unknown")
    port_b = _port("Circular", d=200.0, flow_role="unknown")
    assert parser._resolve_inlet_outlet(port_a, port_b) == (None, None)


def test_through_flow_unresolved_direction_is_unknown_not_a_guess():
    # Different sizes (200 vs 300) would read as a clear expansion/
    # contraction if direction were guessed from an arbitrary port order --
    # must instead come back fully unknown/empty since neither port
    # resolves to a role.
    parser = _parser()
    port_a = _port("Circular", d=200.0, flow_role="unknown", edge_key="A")
    port_b = _port("Circular", d=300.0, flow_role="unknown", edge_key="B")
    flow_class, qualifiers, derived = parser._classify_through_flow(port_a, port_b)
    assert flow_class == "unknown"
    assert qualifiers == {}
    assert derived == {}


# ----------------------------------------------------------------------
# offset_ratio: transverse offset only (perpendicular to flow), never
# including longitudinal port separation along the flow axis.
# ----------------------------------------------------------------------

def test_offset_ratio_ignores_purely_longitudinal_separation():
    # Ports are perfectly centred on each other (no transverse offset) but
    # separated by a large longitudinal distance along the flow axis (+z) --
    # offset_ratio must read ~0, not something derived from that distance.
    parser = _parser()
    inlet = _port(
        "Rectangular", w=400.0, h=300.0, position=(0.0, 0.0, 0.0),
        direction=(0.0, 0.0, 1.0), profile_x_axis=(1.0, 0.0, 0.0), flow_role="inlet",
    )
    outlet = _port(
        "Rectangular", w=200.0, h=150.0, position=(0.0, 0.0, 1000.0),
        direction=(0.0, 0.0, -1.0), flow_role="outlet",
    )
    _, qualifiers, derived = parser._classify_through_flow(inlet, outlet)
    assert qualifiers["alignment"] == "concentric"
    assert derived["offset_ratio"] == pytest.approx(0.0, abs=1e-9)


def test_offset_ratio_uses_transverse_component_only():
    # Same transverse offset (dx=50) as test_alignment_offset_when_no_edges_
    # line_up's dx, but with a large longitudinal separation (dz) added on
    # top -- offset_ratio must match the transverse-only reading, unaffected
    # by dz.
    parser = _parser()
    ref_dim = ((400.0 + 300.0) + (200.0 + 150.0)) / 4.0
    inlet = _port(
        "Rectangular", w=400.0, h=300.0, position=(0.0, 0.0, 0.0),
        direction=(0.0, 0.0, 1.0), profile_x_axis=(1.0, 0.0, 0.0), flow_role="inlet",
    )
    outlet = _port(
        "Rectangular", w=200.0, h=150.0, position=(50.0, 0.0, 1000.0),
        direction=(0.0, 0.0, -1.0), flow_role="outlet",
    )
    _, _, derived = parser._classify_through_flow(inlet, outlet)
    assert derived["offset_ratio"] == pytest.approx(50.0 / ref_dim)


# ----------------------------------------------------------------------
# branch_angle: geometric angle between the branch leg and the trunk,
# derived from each port's own geometric `direction`, never flow_role/
# flow_direction.
# ----------------------------------------------------------------------

def test_branch_angle_tee_is_90_degrees():
    parser = _parser()
    ports = [
        _port("Circular", d=300.0, flow_role="inlet", direction=(1.0, 0.0, 0.0), edge_key="run_a"),
        _port("Circular", d=300.0, flow_role="outlet", direction=(-1.0, 0.0, 0.0), edge_key="run_b"),
        _port("Circular", d=200.0, flow_role="outlet", direction=(0.0, 1.0, 0.0), edge_key="branch"),
    ]
    analysis = _NodeAnalysis(ports, collinear_pairs=[EdgePair(a=0, b=1, angle=180.0, eccentricity=0.0)])
    _, _, derived = parser._classify_branch_flow(ports, analysis)
    assert derived["branch_angle"] == pytest.approx(90.0)


def test_branch_angle_lateral_tee_uses_nearest_trunk_leg():
    parser = _parser()
    cos45 = math.cos(math.radians(45.0))
    sin45 = math.sin(math.radians(45.0))
    ports = [
        _port("Circular", d=300.0, flow_role="inlet", direction=(1.0, 0.0, 0.0), edge_key="run_a"),
        _port("Circular", d=300.0, flow_role="outlet", direction=(-1.0, 0.0, 0.0), edge_key="run_b"),
        _port("Circular", d=200.0, flow_role="outlet", direction=(cos45, sin45, 0.0), edge_key="branch"),
    ]
    analysis = _NodeAnalysis(ports, collinear_pairs=[EdgePair(a=0, b=1, angle=180.0, eccentricity=0.0)])
    _, _, derived = parser._classify_branch_flow(ports, analysis)
    assert derived["branch_angle"] == pytest.approx(45.0)


def test_branch_angle_absent_for_wye_with_no_trunk_pair():
    parser = _parser()
    ports = [
        _port("Circular", d=200.0, flow_role="inlet", direction=(1.0, 0.0, 0.0)),
        _port("Circular", d=200.0, flow_role="outlet", direction=(0.0, 1.0, 0.0)),
        _port("Circular", d=200.0, flow_role="outlet", direction=(0.0, -1.0, 0.0)),
    ]
    analysis = _NodeAnalysis(ports, collinear_pairs=[])
    _, _, derived = parser._classify_branch_flow(ports, analysis)
    assert "branch_angle" not in derived


# ----------------------------------------------------------------------
# _geom_tol: shared size-relative geometry tolerance helper.
# ----------------------------------------------------------------------

def test_geom_tol_uses_absolute_floor_for_small_sizes():
    parser = _parser()
    assert parser._geom_tol(0.0) == parser.tol
    assert parser._geom_tol(1.0, rel_tol=1e-6) == parser.tol


def test_geom_tol_scales_with_characteristic_size():
    parser = _parser()
    size = 1000.0
    rel_tol = 1e-3
    assert parser._geom_tol(size, rel_tol=rel_tol) == pytest.approx(size * rel_tol)


# ----------------------------------------------------------------------------
# classify_flow (end, degree 1): entry / exit
# ----------------------------------------------------------------------------


@pytest.mark.parametrize("flow_role, expected", [("outlet", "entry"), ("inlet", "exit"), ("unknown", "unknown")])
def test_end_flow_class_follows_the_way_air_passes_the_open_end(flow_role, expected):
    # A port that brings air to an open end ("inlet", seen from the node) is where air leaves the system.
    parser = _parser()
    port = _port("Circular", d=200.0, flow_role=flow_role)
    assert parser._classify_end_flow(port) == expected
    flow_class, qualifiers, derived = parser.classify_flow(_NodeAnalysis([port]), "end")
    assert (flow_class, qualifiers, derived) == (expected, {}, {})


# ----------------------------------------------------------------------------
# classify_flow (cross / multiport): diverging / converging
# ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "roles, expected",
    [
        (["inlet", "outlet", "outlet", "outlet"], "diverging"),
        (["inlet", "inlet", "inlet", "outlet"], "converging"),
        (["inlet", "inlet", "outlet", "outlet"], "unknown"),
        (["inlet", "outlet", "outlet", "unknown"], "unknown"),
        (["inlet", "outlet", "outlet", "outlet", "outlet"], "diverging"),
        (["outlet", "inlet", "inlet", "inlet", "inlet", "inlet"], "converging"),
    ],
)
def test_manifold_flow_class_counts_inlets_and_outlets(roles, expected):
    parser = _parser()
    ports = [_port("Circular", d=200.0, flow_role=role, edge_key="E{}".format(i)) for i, role in enumerate(roles)]
    assert parser._classify_manifold_flow(ports) == expected
    topology = "cross" if len(ports) == 4 else "multiport"
    assert parser.classify_flow(_NodeAnalysis(ports), topology) == (expected, {}, {})
