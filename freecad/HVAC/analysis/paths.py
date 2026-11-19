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
Builds one pressure-loss path per terminal (root/balancing-terminal ->
that terminal), and picks the critical one -- the terminal that sees the
most total loss, which is what a real fan/AHU has to be selected against.

Before this module existed, pressure.py only ever reported the critical
terminal's own key and its magnitude as two bare numbers
(critical_terminal_key/critical_pressure_pa). This exposes every terminal's
own path and a pressure_deficit_pa relative to the critical one, which
sizing/balancing.py needs to compare sibling branches against each other.
"""

from dataclasses import dataclass, field
from typing import List


@dataclass
class PathLossBreakdown:
    """
    One path's loss, split by source. duct_friction_pa/component_pa are
    summed over every segment on the path; junction_pa is every
    INTERMEDIATE node's own Primary contribution (the node the path passes
    through, not the terminal it ends at); terminal_pa is the terminal
    node's own Primary contribution (e.g. a modeled diffuser neck loss),
    kept separate since it's a dead end, not a junction the path continues
    past. total_pa is their sum.
    """
    duct_friction_pa: float = 0.0
    junction_pa: float = 0.0
    component_pa: float = 0.0
    terminal_pa: float = 0.0
    total_pa: float = 0.0


@dataclass
class FlowPathResult:
    """One terminal's own path from the balancing terminal, with its loss breakdown."""
    terminal_node_id: str
    node_ids: List[str] = field(default_factory=list)   # root -> terminal, in order
    edge_keys: List[str] = field(default_factory=list)   # root -> terminal, in order
    loss: PathLossBreakdown = field(default_factory=PathLossBreakdown)
    pressure_deficit_pa: float = 0.0  # filled in by find_critical_path relative to the critical path


@dataclass
class CriticalPathResult:
    """The terminal with the largest total path loss -- what a fan/AHU must be selected against."""
    terminal_node_id: str
    path: FlowPathResult


def _path_node_and_edge_ids(flow_component, terminal_node_id):
    """Walk parent_edge/parent_node from terminal_node_id back to the root, root-first."""
    node_ids = [terminal_node_id]
    edge_keys = []
    node_id = terminal_node_id
    while node_id != flow_component.root_node_id:
        edge_keys.append(flow_component.parent_edge[node_id])
        node_id = flow_component.parent_node[node_id]
        node_ids.append(node_id)
    node_ids.reverse()
    edge_keys.reverse()
    return node_ids, edge_keys


def build_terminal_paths(flow_component, tree_result) -> List[FlowPathResult]:
    """
    One FlowPathResult per non-root terminal in flow_component -- the
    balancing terminal itself has no path (zero edges) so is excluded.
    """
    paths = []
    for terminal_id in flow_component.terminal_ids:
        if terminal_id == flow_component.root_node_id:
            continue

        node_ids, edge_keys = _path_node_and_edge_ids(flow_component, terminal_id)

        duct_friction_pa = 0.0
        component_pa = 0.0
        junction_pa = 0.0
        for i, edge_key in enumerate(edge_keys):
            sres = tree_result.segments[edge_key]
            duct_friction_pa += sres.friction_loss_pa
            component_pa += sres.component_loss_pa
            if i < len(edge_keys) - 1:
                junction_pa += sres.junction_loss_pa

        terminal_pa = tree_result.segments[edge_keys[-1]].junction_loss_pa if edge_keys else 0.0
        total_pa = duct_friction_pa + junction_pa + component_pa + terminal_pa

        paths.append(FlowPathResult(
            terminal_node_id=terminal_id,
            node_ids=node_ids,
            edge_keys=edge_keys,
            loss=PathLossBreakdown(
                duct_friction_pa=duct_friction_pa, junction_pa=junction_pa,
                component_pa=component_pa, terminal_pa=terminal_pa, total_pa=total_pa,
            ),
        ))
    return paths


def find_critical_path(paths: List[FlowPathResult]):
    """
    The path with the largest total loss, plus every path's own
    pressure_deficit_pa relative to it (0.0 for the critical path itself).
    Returns None if `paths` is empty (a component with only the balancing
    terminal -- shouldn't happen given flow.py requires >=2 terminals).
    """
    if not paths:
        return None
    critical = max(paths, key=lambda p: p.loss.total_pa)
    for p in paths:
        p.pressure_deficit_pa = critical.loss.total_pa - p.loss.total_pa
    return CriticalPathResult(terminal_node_id=critical.terminal_node_id, path=critical)
