# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the HVAC addon.

"""Focused tests for HVACLibraryAPI context and port-role helpers."""

import pytest

import conftest  # noqa: F401 -- installs FreeCAD/FreeCADGui/Part/PySide stubs
from freecad.HVAC.library.library_api import HVACLibraryAPI


def _context(pair=None, port_count=3):
    ports = [{"edge_key": chr(ord("A") + index)} for index in range(port_count)]
    analysis = {} if pair is None else {"collinear_pairs": [pair]}
    return {"connected_ports": ports, "analysis": analysis}, ports


def test_run_branch_ports_returns_classifier_order_and_remaining_port():
    context, ports = _context({"a": 2, "b": 0})

    run_a, run_b, branch = HVACLibraryAPI.run_branch_ports(context)

    assert (run_a, run_b, branch) == (ports[2], ports[0], ports[1])


def test_run_branch_ports_requires_three_connected_ports():
    context, _ = _context({"a": 0, "b": 1}, port_count=2)

    with pytest.raises(ValueError, match="exactly three connected ports"):
        HVACLibraryAPI.run_branch_ports(context)


def test_run_branch_ports_requires_classifier_pair():
    context, _ = _context()

    with pytest.raises(ValueError, match="collinear_pairs.*empty"):
        HVACLibraryAPI.run_branch_ports(context)


def test_run_branch_ports_rejects_invalid_pair_indices():
    context, _ = _context({"a": 0, "b": 3})

    with pytest.raises(ValueError, match="invalid connected-port indices"):
        HVACLibraryAPI.run_branch_ports(context)


# ----------------------------------------------------------------------------
# port_roles
# ----------------------------------------------------------------------------


def _role_port(edge_key, direction, into_node=None):
    return {
        "edge_key": edge_key,
        "position": [0.0, 0.0, 0.0],
        "direction": list(direction),
        "profile": "Circular",
        "section_params": {"Diameter": 200.0},
        "profile_x_axis": None,
        "segment_end": "start",
        "flow_into_junction": into_node,
    }


def _role_context(ports, pairs=()):
    return {"connected_ports": ports, "analysis": {"collinear_pairs": [{"a": a, "b": b} for a, b in pairs]}}


def _edge_keys(roles):
    return {role: port["edge_key"] for role, port in roles.items()}


def test_port_roles_single_port_is_the_neck():
    roles = HVACLibraryAPI.port_roles(_role_context([_role_port("A", (1, 0, 0))]))
    assert _edge_keys(roles) == {"neck": "A"}


def test_port_roles_two_ports_follow_flow_direction_not_port_order():
    ports = [_role_port("OUT", (1, 0, 0), into_node=False), _role_port("IN", (-1, 0, 0), into_node=True)]
    assert _edge_keys(HVACLibraryAPI.port_roles(_role_context(ports))) == {"inlet": "IN", "outlet": "OUT"}


def test_port_roles_two_ports_without_flow_fall_back_to_port_order():
    ports = [_role_port("A", (1, 0, 0)), _role_port("B", (-1, 0, 0))]
    assert _edge_keys(HVACLibraryAPI.port_roles(_role_context(ports))) == {"inlet": "A", "outlet": "B"}


def test_port_roles_tee_uses_the_classifiers_run_pair():
    ports = [_role_port("C", (0, 1, 0)), _role_port("A", (-1, 0, 0)), _role_port("B", (1, 0, 0))]
    roles = HVACLibraryAPI.port_roles(_role_context(ports, pairs=[(1, 2)]))
    assert _edge_keys(roles) == {"run_a": "A", "run_b": "B", "branch": "C"}


def test_port_roles_wye_has_a_main_and_two_branches():
    # The two legs closest in direction are the branches; the remaining one is the main.
    ports = [_role_port("B1", (0.7, 0.7, 0)), _role_port("M", (-1, 0, 0)), _role_port("B2", (0.7, -0.7, 0))]
    roles = HVACLibraryAPI.port_roles(_role_context(ports))
    assert roles["main"]["edge_key"] == "M"
    assert {roles["branch_a"]["edge_key"], roles["branch_b"]["edge_key"]} == {"B1", "B2"}


def test_port_roles_cross_has_a_run_and_two_branches():
    ports = [
        _role_port("N", (0, 1, 0)),
        _role_port("W", (-1, 0, 0)),
        _role_port("S", (0, -1, 0)),
        _role_port("E", (1, 0, 0)),
    ]
    roles = HVACLibraryAPI.port_roles(_role_context(ports, pairs=[(1, 3), (0, 2)]))
    assert _edge_keys(roles) == {"run_a": "W", "run_b": "E", "branch_a": "S", "branch_b": "N"}


def test_port_roles_five_or_more_ports_are_numbered_in_a_stable_geometric_order():
    directions = {"A": (1, 0, 0), "B": (0, 1, 0), "C": (-1, 0, 0), "D": (0, -1, 0), "E": (0, 0, 1), "F": (0, 0, -1)}
    ports = [_role_port(key, d) for key, d in directions.items()]
    roles = HVACLibraryAPI.port_roles(_role_context(ports))
    assert sorted(roles) == ["port_{}".format(i) for i in range(1, 7)]
    # Listing the same ports in another order gives the same roles.
    shuffled = HVACLibraryAPI.port_roles(_role_context(list(reversed(ports))))
    assert _edge_keys(shuffled) == _edge_keys(roles)
