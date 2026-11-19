# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the HVAC addon.

################################################################################
#                                                                              #
#   Copyright (c) 2026 Francisco Rosa                                          #
#                                                                              #
#   This addon is free software; you can redistribute it and/or modify it      #
#   under the terms of the GNU Lesser General Public License as published      #
#   by the Free Software Foundation; either version 2.1 of the License, or     #
#   (at your option) any later version.                                        #
#                                                                              #
#   This addon is distributed in the hope that it will be useful,              #
#   but WITHOUT ANY WARRANTY; without even the implied warranty of             #
#   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.                       #
#                                                                              #
#   See the GNU Lesser General Public License for more details.                #
#                                                                              #
#   You should have received a copy of the GNU Lesser General Public           #
#   License along with this addon. If not, see https://www.gnu.org/licenses    #
#                                                                              #
################################################################################

"""
Works out how much air flows through every segment of a NetworkModel. Both
pressure.py (pressure/loss) and sizing.py (duct dimensions) need this same
answer before they can do their own, separate calculation, so it's solved
once here and shared -- a pure port of core/FlowNetwork.py's algorithm,
operating on NetworkModel instead of a live FreeCAD document.

How it works: each connected sub-network must be a tree (no loops). Every
terminal has a FlowBoundary of "Auto", "Fixed", or "Closed" (see
analysis/model.py's NodeModel). Exactly one terminal is left "Auto" -- the
balancing terminal (e.g. the fan/AHU connection) -- and its flow is
whatever makes everything else balance. Every other terminal is either
"Fixed" (a user-set design flow rate, e.g. a diffuser -- 0 L/s is a
perfectly valid fixed flow) or "Closed" (a sealed/capped terminal, which
always contributes exactly 0 flow regardless of its own DesignFlowRate).
Starting from the terminals and working inward towards the balancing
terminal, each segment's flow is just conservation of mass: flow out of a
junction equals flow into it. A segment's own fixed flow direction is read
from its ports (flow_into_node).

A sub-network that isn't a tree (has a loop) is reported as an error rather
than solved.
"""

import os
import sys
from dataclasses import dataclass, field

# networkx is vendored under HVAC/ext_libs for users without it pip-installed
# -- same lookup utils/hvaclib.py does, duplicated here (rather than
# imported from hvaclib) since analysis/ must not depend on it.
_vendor_path = os.path.join(os.path.dirname(__file__), "..", "ext_libs")
if _vendor_path not in sys.path:
    sys.path.append(_vendor_path)

import networkx as nx

from .model import NetworkModel


class FlowSolveError(Exception):
    """Raised when a sub-network's flow distribution cannot be solved (loop, bad boundary conditions, missing data)."""
    pass


@dataclass
class FlowComponent:
    """
    One connected, successfully-solved sub-network: its topology (as a
    rooted tree from the balancing terminal) plus the solved flow magnitude
    through every segment. Callers (pressure.py, sizing.py) do their own
    size- or pressure-specific work per segment/node from here.
    """
    node_ids: set
    edge_keys: set
    root_node_id: str
    order: list               # BFS order from root (root first)
    parent_node: dict         # node_id -> parent node_id (root excluded)
    parent_edge: dict         # node_id -> edge_key connecting to parent (root excluded)
    edge_flow_lps: dict       # edge_key -> solved flow magnitude (L/s)
    terminal_ids: list = field(default_factory=list)  # node_ids with degree == 1


def solve_flow_components(network: NetworkModel):
    """
    Resolve every connected sub-network of `network` into a FlowComponent.

    Returns (components, warnings):
      - components: list of FlowComponent, one per successfully-solved
        sub-network.
      - warnings: human-readable messages for any sub-network that could NOT
        be solved (loop, bad boundary conditions, missing data) -- these are
        skipped, not raised, so one bad sub-network doesn't block others in
        the same network.
    """
    graph = nx.Graph()
    graph.add_nodes_from(network.nodes.keys())
    for edge_key, (u, v) in network.edges.items():
        graph.add_edge(u, v, key=edge_key)

    warnings = []
    components = []
    for comp_nodes in nx.connected_components(graph):
        subgraph = graph.subgraph(comp_nodes)
        if subgraph.number_of_edges() == 0:
            continue
        try:
            components.append(_solve_component_flow(network, comp_nodes, subgraph))
        except FlowSolveError as exc:
            warnings.append(str(exc))

    return components, warnings


# ----------------------------------------------------------------------------
# Per-component flow solve
# ----------------------------------------------------------------------------

def _solve_component_flow(network, comp_nodes, graph):
    # Step 1: a tree with N nodes always has exactly N-1 edges -- if this
    # sub-network has more edges than that, it must contain a loop.
    comp_edges = {edge_key for _u, _v, edge_key in graph.edges(data="key")}
    n_nodes = len(comp_nodes)
    n_edges = len(comp_edges)
    if n_edges != n_nodes - 1:
        raise FlowSolveError(
            "Loop detected: a sub-network with {} junction(s) has {} duct segment(s); "
            "a tree requires exactly {}. Loops are not supported.".format(
                n_nodes, n_edges, n_nodes - 1
            )
        )

    # Step 2: every node/segment referenced by this sub-network must exist
    # in the model -- an incompletely-built NetworkModel is a data problem,
    # not a topology one, so it's reported the same way as any other
    # unsolvable sub-network rather than raised as a hard error.
    for node_id in comp_nodes:
        if node_id not in network.nodes:
            raise FlowSolveError("Node data missing for '{}'.".format(node_id))
    for edge_key in comp_edges:
        if edge_key not in network.segments:
            raise FlowSolveError("Segment data missing for edge '{}'.".format(edge_key))

    port_lookup = {}
    for node_id in comp_nodes:
        node = network.nodes[node_id]
        for port in node.ports:
            port_lookup[(node_id, port.edge_key)] = port

    # Step 3: find every open end (terminal), and check exactly one of them
    # is the balancing terminal (FlowBoundary == "Auto").
    terminal_ids = [n for n in comp_nodes if graph.degree[n] == 1]
    if len(terminal_ids) < 2:
        raise FlowSolveError(
            "Sub-network containing node '{}' has fewer than 2 terminals; "
            "nothing to solve.".format(next(iter(comp_nodes)))
        )

    specified = []
    unspecified = []
    closed = []
    for node_id in terminal_ids:
        boundary = network.nodes[node_id].flow_boundary
        if boundary == "Auto":
            unspecified.append(node_id)
        elif boundary == "Closed":
            closed.append(node_id)
        else:
            specified.append(node_id)

    if len(unspecified) == 0:
        raise FlowSolveError(
            "All terminals in this sub-network have a Flow Condition of Fixed or Closed ({}). "
            "Leave exactly one terminal's Flow Condition set to Auto to act as the "
            "balancing terminal.".format(", ".join(specified + closed))
        )
    if len(unspecified) > 1:
        raise FlowSolveError(
            "Multiple terminals have a Flow Condition of Auto ({}). Set Flow Condition to "
            "Fixed or Closed on all terminals except exactly one.".format(", ".join(unspecified))
        )

    root_node_id = unspecified[0]

    # Step 4: walk the tree breadth-first from the balancing terminal, so we
    # know each node's parent and which edge connects them. This also fixes
    # the order flow gets solved in, in the next step.
    parent_node = {}
    parent_edge = {}
    order = [root_node_id]
    for u, v in nx.bfs_edges(graph, root_node_id):
        parent_node[v] = u
        parent_edge[v] = graph[u][v]["key"]
        order.append(v)

    # Step 5: solve each segment's flow, working from the leaves back to the
    # root (reversed BFS order) so a node's other edges are always already
    # solved by the time we need them for the one going to its parent.
    edge_flow_lps = {}
    for node_id in reversed(order[1:]):
        edge = parent_edge[node_id]

        if graph.degree[node_id] == 1:
            # A leaf's own edge carries its design flow rate -- except a
            # Closed terminal, which always contributes exactly zero flow
            # regardless of whatever DesignFlowRate happens to hold.
            node = network.nodes[node_id]
            if node.flow_boundary == "Closed":
                edge_flow_lps[edge] = 0.0
            else:
                edge_flow_lps[edge] = abs(node.design_flow_lps)
            continue

        # Add up the flow on every OTHER edge at this node (already solved),
        # split into what's flowing in vs. out.
        known_in = 0.0
        known_out = 0.0
        for _u, _v, edge_key in graph.edges(node_id, data="key"):
            if edge_key == edge:
                continue
            port = port_lookup[(node_id, edge_key)]
            mag = edge_flow_lps[edge_key]
            if port.flow_into_node:
                known_in += mag
            else:
                known_out += mag

        # Mass conservation: total in == total out, so whatever's missing on
        # the "parent" edge must make up the difference. Which side it's
        # missing from depends on which way that edge itself points.
        p_port = port_lookup[(node_id, edge)]
        if p_port.flow_into_node:
            p_mag = known_out - known_in
        else:
            p_mag = known_in - known_out

        if p_mag < -1e-6:
            raise FlowSolveError(
                "Inconsistent flow direction at node '{}': incoming and outgoing design "
                "flows don't balance given the current segment directions. Check base geometry "
                "direction (HVAC_ReverseGeometryDirection / Edit Duct Directions).".format(node_id)
            )
        edge_flow_lps[edge] = max(p_mag, 0.0)

    return FlowComponent(
        node_ids=set(comp_nodes),
        edge_keys=comp_edges,
        root_node_id=root_node_id,
        order=order,
        parent_node=parent_node,
        parent_edge=parent_edge,
        edge_flow_lps=edge_flow_lps,
        terminal_ids=terminal_ids,
    )
