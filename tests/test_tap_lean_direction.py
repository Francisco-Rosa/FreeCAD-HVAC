"""
Taps and tees follow the flow (user report, 12 November 2026): on a square
branch the shoe's toe / the branch bend points at the run leg the branch
exchanges air with -- upstream for a supply (diverging) tee, downstream for
a return (converging) one.
"""

import pytest

import conftest  # noqa: F401 -- installs FreeCAD/Part stubs
from freecad.HVAC.library.fittings._common import _lean_port
from freecad.HVAC.library.library_api import HVACLibraryAPI as api


def _port(key, direction, into, x_axis=(0.0, 0.0, 1.0)):
    return {
        "edge_key": key,
        "segment_end": "start",
        "position": (0.0, 0.0, 0.0),
        "direction": direction,
        "flow_into_junction": into,
        "profile": "Circular",
        "section_params": {"Diameter": 200.0},
        "profile_x_axis": x_axis,
    }


def _tee(a_in, b_in, branch_in, branch_dir=(0.0, 1.0, 0.0)):
    return _port("A", (-1.0, 0.0, 0.0), a_in), _port("B", (1.0, 0.0, 0.0), b_in), _port("C", branch_dir, branch_in)


@pytest.mark.parametrize("swap", [False, True])
def test_supply_tee_leans_upstream(swap):
    # Air comes in on A and leaves through B and the branch.
    a, b, c = _tee(True, False, False)
    run_a, run_b = (b, a) if swap else (a, b)
    assert _lean_port(api, run_a, run_b, c)["edge_key"] == "A"


@pytest.mark.parametrize("swap", [False, True])
def test_return_tee_leans_downstream(swap):
    # Air comes in on A and the branch, leaves through B.
    a, b, c = _tee(True, False, True)
    run_a, run_b = (b, a) if swap else (a, b)
    assert _lean_port(api, run_a, run_b, c)["edge_key"] == "B"


def test_reversing_the_flow_flips_the_lean():
    a, b, c = _tee(False, True, False)
    assert _lean_port(api, a, b, c)["edge_key"] == "B"


def test_reverse_branch_bend_still_flips():
    a, b, c = _tee(True, False, False)
    assert _lean_port(api, a, b, c, reverse=True)["edge_key"] == "B"


def test_without_flow_the_choice_is_still_deterministic():
    a, b, c = _tee(None, None, None)
    assert _lean_port(api, a, b, c)["edge_key"] == _lean_port(api, b, a, c)["edge_key"]


def test_bullhead_falls_back_to_geometry():
    a, b, c = _tee(False, False, True)  # air in through the branch, out both run legs
    assert _lean_port(api, a, b, c)["edge_key"] == _lean_port(api, b, a, c)["edge_key"]


def test_an_inclined_branch_keeps_its_geometric_lean():
    # Branch pointing downstream toward B: it leans from A, whatever the flow says.
    a, b, c = _tee(False, True, False, branch_dir=(0.7071, 0.7071, 0.0))
    assert _lean_port(api, a, b, c)["edge_key"] == "A"
