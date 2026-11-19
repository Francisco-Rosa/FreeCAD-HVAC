# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the HVAC addon.

"""
Automatic attachment of equipment and custom fittings to a network.

The user models a unit (equipment) or a fitting (custom fitting) as an
App::Part with HVAC port markers, then draws the network's base geometry so
that duct ends sit on those ports. This module works out, from plain points,
which open duct end sits on which port; DuctNetwork.autoAttach() then acts
on it:

- every open end on a custom fitting's ports joins one junction (a node
  group, like a virtual junction), whose fitting takes the custom geometry
  in place;
- an open end on an equipment port is connected to that port
  (Equipment.connect).

Pure Python, no FreeCAD, so it can be unit tested.
"""

import math
from dataclasses import dataclass
from typing import Dict, List, Tuple

KIND_EQUIPMENT = "equipment"
KIND_FITTING = "fitting"

# A duct end this close to a port's centre sits on it (mm).
POSITION_TOLERANCE_MM = 1.0


@dataclass(frozen=True)
class PortSpot:
    """One port marker: the container it belongs to (by name), its kind, its own name and its world position."""

    owner: str
    kind: str
    marker: str
    position: Tuple[float, float, float]


def match_open_ends(open_ends, ports, tolerance=POSITION_TOLERANCE_MM):
    """
    Pair open duct ends with the ports they sit on.

    open_ends: {node_id: (x, y, z)}, the points where exactly one duct ends.
    ports: [PortSpot, ...].
    Returns [(node_id, PortSpot), ...], sorted by node id: each end on at
    most one port and each port with at most one end, the closest pairs
    taken first, none further apart than `tolerance`.
    """
    # Step 1: every end/port pair close enough, closest first (ties by id, for a stable result).
    pairs = []
    for node_id, point in open_ends.items():
        for index, port in enumerate(ports):
            distance = math.dist(point, port.position)
            if distance <= tolerance:
                pairs.append((distance, node_id, index))
    pairs.sort(key=lambda pair: (pair[0], str(pair[1]), pair[2]))

    # Step 2: take them greedily, so no end or port is used twice.
    used_ends, used_ports, matches = set(), set(), []
    for _distance, node_id, index in pairs:
        if node_id in used_ends or index in used_ports:
            continue
        used_ends.add(node_id)
        used_ports.add(index)
        matches.append((node_id, ports[index]))
    return sorted(matches, key=lambda match: str(match[0]))


def fitting_groups(matches) -> Dict[str, List]:
    """{custom fitting name: [node_id, ...]}: the open ends sitting on each custom fitting's ports."""
    groups = {}
    for node_id, port in matches:
        if port.kind == KIND_FITTING:
            groups.setdefault(port.owner, []).append(node_id)
    return {owner: sorted(nodes, key=str) for owner, nodes in groups.items()}


def equipment_matches(matches):
    """[(node_id, PortSpot), ...]: the open ends sitting on equipment ports."""
    return [(node_id, port) for node_id, port in matches if port.kind == KIND_EQUIPMENT]


def parse_connection(entry):
    """One Equipment.Connections entry 'port|network|node key' as a dict, or None when malformed."""
    parts = str(entry).split("|")
    if len(parts) != 3:
        return None
    return {"port": parts[0], "network": parts[1], "node_key": parts[2]}


def live_connections(entries, network, live_node_keys):
    """
    The Equipment.Connections entries to keep after `network` was synced:
    every entry of another network, and this network's entries whose node
    still exists (a duct end moved off a port leaves a node that is gone).
    Malformed entries are dropped.
    """
    keep = []
    for entry in entries:
        connection = parse_connection(entry)
        if connection is None:
            continue
        if connection["network"] == network and connection["node_key"] not in live_node_keys:
            continue
        keep.append(entry)
    return keep
