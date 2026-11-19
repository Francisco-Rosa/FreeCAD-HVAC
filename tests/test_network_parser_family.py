"""
Junction family classification for 3, 4 and 5+ ports (classify_junction_family),
driven through the parser's own geometric helpers (angles, eccentricities,
collinear pairs) as node_analysis() computes them.
"""

import math

import conftest  # noqa: F401 -- installs FreeCAD stubs
import pytest

from freecad.HVAC.core.NetworkParser import DuctNetworkParser, JunctionPort


def _parser():
    p = DuctNetworkParser.__new__(DuctNetworkParser)
    p.tol = 1e-6
    p.angle_tol_degree = 2.0
    return p


def _dir(deg, z=0.0):
    a = math.radians(deg)
    v = (math.cos(a), math.sin(a), z)
    n = math.sqrt(sum(c * c for c in v))
    return tuple(c / n for c in v)


def _port(direction, key):
    return JunctionPort(
        edge_key=key, segment_end="end", position=(0.0, 0.0, 0.0), direction=direction, profile="Circular",
        section_params={"Diameter": 200.0}, attachment="Center", user_offset=(0.0, 0.0, 0.0),
        profile_x_axis=(0.0, 0.0, 1.0), flow_role="unknown", flow_direction=direction, flow_into_junction=None,
    )


class _Analysis:
    def __init__(self, parser, directions):
        self.connected_ports = [_port(d, "E{}".format(i)) for i, d in enumerate(directions)]
        self.degree = len(directions)
        self.port_origins = [(0.0, 0.0, 0.0)] * len(directions)
        self.edge_vectors = list(directions)
        self.edge_angles = parser._edge_angles(self.edge_vectors)
        self.edge_eccentricities = parser._edge_eccentricities(self.port_origins, self.edge_vectors)
        self.is_coplanar = all(e < parser.tol for e in self.edge_eccentricities.values())
        self.collinear_pairs = parser._collinear_pairs(self.port_origins, self.edge_vectors)


@pytest.mark.parametrize(
    "angles, z, expected",
    [
        ((0, 180, 90), (0, 0, 0), ("tee", [])),
        ((0, 180, 45), (0, 0, 0), ("lateral_tee", [])),
        ((0, 120, 240), (0, 0, 0), ("wye", [])),
        ((0, 90, 180, 270), (0, 0, 0, 0), ("cross", [])),
        ((0, 180, 135, 225), (0, 0, 0, 0), ("double_wye", [])),
        ((0, 180, 60, 200), (0, 0, 0, 0), ("generic", [])),  # one run, unequal branches
        ((0, 72, 144, 216, 288), (0, 0, 0, 0, 0), ("multiport", [])),
    ],
)
def test_family(angles, z, expected):
    parser = _parser()
    directions = [_dir(a, zz) for a, zz in zip(angles, z)]
    family, tags = parser.classify_junction_family(_Analysis(parser, directions))
    assert (family, list(tags)) == expected
