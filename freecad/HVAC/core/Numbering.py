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
Renumber Network: assigns documentation-only D.../J.../J...-P/J...-NN
numbers to a DuctNetwork's segments/junctions/components and rewrites their
Label to match. This is a presentation layer only -- internal identities
(SegmentKey/NodeKey/Name/AttachedEdgeKey/...) are never touched, and normal
network sync never calls into this module. Numbers only change when
HVAC_RenumberNetwork (ui/Command.py) explicitly runs this module's
renumber_network().

Reuses the same DuctNetworkParser analysis graph and DuctNetwork.collect*
helpers every other core/ adapter (FlowNetwork.py, _analysis_adapter.py)
already reads from, rather than re-deriving topology of its own.
"""

from dataclasses import dataclass, field

from ..utils import hvaclib


@dataclass
class RenumberResult:
    """Summary returned to the GUI command for its console message."""
    segment_count: int = 0
    junction_count: int = 0
    component_count: int = 0
    changed: bool = False
    warnings: list = field(default_factory=list)


@dataclass(frozen=True)
class _Step:
    """One stop along the traversal order: either a node (junction) or an
    edge (segment) reached while walking outward from a sub-network's
    source terminal."""
    kind: str  # "node" or "edge"
    ref: str   # node_key for "node", edge_key (EdgeRef.tag) for "edge"


def renumber_network(net_obj):
    """
    Walk every connected sub-network of net_obj outward from a deterministic
    source terminal, assigning sequential D001/J001/... numbers and writing
    matching Labels. Returns a RenumberResult.
    """
    parser = net_obj.Proxy.getParser(rebuild=True)
    segment_map = net_obj.Proxy.collectSegmentObjects()
    junction_map = net_obj.Proxy.collectJunctionObjects()
    component_map = net_obj.Proxy.collectComponentObjects()
    reg = hvaclib.HVACLibraryService.get_hvac_library_registry()

    result = RenumberResult()
    order = _traversal_order(parser, junction_map, result.warnings)

    d_index = 0
    j_index = 0
    for step in order:
        if step.kind == "node":
            junction_obj = junction_map.get(step.ref)
            if junction_obj is None:
                result.warnings.append(
                    "Junction node '{}' has no synced DuctJunction object -- skipped.".format(step.ref)
                )
                continue
            j_index += 1
            number = "J{:03d}".format(j_index)
            if _apply_junction_number(junction_obj, number):
                result.changed = True
            result.junction_count += 1

            comp_changed, comp_count = _renumber_components(
                junction_obj, number, component_map.get(junction_obj.Name, []), reg
            )
            result.changed = result.changed or comp_changed
            result.component_count += comp_count
        else:
            segment_obj = segment_map.get(step.ref)
            if segment_obj is None:
                result.warnings.append(
                    "Segment edge '{}' has no synced DuctSegment object -- skipped.".format(step.ref)
                )
                continue
            d_index += 1
            number = "D{:03d}".format(d_index)
            if _apply_segment_number(segment_obj, number, reg):
                result.changed = True
            result.segment_count += 1

    return result


# ------------------------------------------------------------------
# Traversal order: source-outward walk of every connected sub-network
# ------------------------------------------------------------------

def _traversal_order(parser, junction_map, warnings):
    """
    One combined, deterministic node/edge visit order across every
    connected sub-network of the parser's analysis graph -- each
    sub-network is walked depth-first from its own source terminal (see
    _choose_root), branch order at each node is broken by the neighboring
    node's own point (falling back to edge_key), and sub-networks
    themselves are ordered by their chosen root's point. Re-running this
    over an unchanged topology always produces the same order.
    """
    node_ids = parser.nodes()
    node_point = {n: parser.node_xyz(n) for n in node_ids}
    node_key = {n: parser.node_key(n) for n in node_ids}
    adjacency = _build_adjacency(parser, node_ids)

    components = [comp for comp in parser.connected_components() if comp]
    roots = []
    for comp_nodes in components:
        root = _choose_root(comp_nodes, node_point, node_key, junction_map, warnings)
        roots.append((node_point[root], node_key[root], comp_nodes, root))
    roots.sort(key=lambda entry: (entry[0], entry[1]))

    order = []
    for _point, _key, comp_nodes, root in roots:
        order.extend(_dfs_order(root, adjacency, node_point, node_key))
    return order


def _build_adjacency(parser, node_ids):
    """{analysis_node_id: [(EdgeRef, other_analysis_node_id), ...]} -- built
    from node_edges()/edge_analysis_nodes() rather than parser.analysis_graph
    directly, since the graph collapses parallel edges between the same two
    nodes onto a single edge attribute (see NetworkParser._rebuild_analysis_
    graph_from_groups) and every real segment still needs its own number."""
    adjacency = {}
    for node_id in node_ids:
        pairs = []
        for edge_ref in parser.node_edges(node_id):
            u, v = parser.edge_analysis_nodes(edge_ref)
            other = v if u == node_id else u
            pairs.append((edge_ref, other))
        adjacency[node_id] = pairs
    return adjacency


def _choose_root(comp_nodes, node_point, node_key, junction_map, warnings):
    """
    Pick this sub-network's traversal source, preferring (in order):
      1. a node whose junction was solved as the flow source last time
         AirflowSolver ran (IsFlowSource) -- if exactly one such node,
      2. else, a topology="end" terminal whose Flow Condition is "Auto" --
         the same "balancing terminal" heuristic analysis/flow.py itself
         uses to find a network's source before a solve even runs,
      3. else, the geometrically-lowest "end" (degree-1) terminal,
      4. else (a closed loop with no terminal at all), the geometrically-
         lowest node in the sub-network.
    """
    def sort_key(node_id):
        return (node_point[node_id], node_key[node_id])

    def junction_for(node_id):
        return junction_map.get(node_key[node_id])

    terminals = [n for n in comp_nodes if getattr(junction_for(n), "Topology", "") == "end"]

    flow_sources = [n for n in terminals if bool(getattr(junction_for(n), "IsFlowSource", False))]
    if len(flow_sources) == 1:
        return flow_sources[0]

    unset_flow = [n for n in terminals if str(getattr(junction_for(n), "FlowBoundary", "Auto") or "Auto") == "Auto"]
    if len(unset_flow) == 1:
        return unset_flow[0]

    if terminals:
        return min(terminals, key=sort_key)

    warnings.append(
        "Sub-network containing node '{}' has no terminal (a closed loop) -- "
        "numbering starts at its geometrically-lowest node instead of a "
        "flow source.".format(node_key[min(comp_nodes, key=sort_key)])
    )
    return min(comp_nodes, key=sort_key)


def _dfs_order(root, adjacency, node_point, node_key):
    """
    Iterative depth-first walk from root: at each node, branch into
    not-yet-visited edges in ascending (neighbor point, edge_key) order,
    walking each branch fully before returning to try the next one --
    this reads like "follow the ductwork from the source, run by run"
    rather than fanning out breadth-first. An edge whose far node was
    already visited (a loop-closing edge) is still numbered but not
    descended into again, so this also tolerates non-tree topology.
    """
    def sorted_candidates(node_id):
        pairs = adjacency.get(node_id, [])
        return sorted(pairs, key=lambda item: (node_point.get(item[1], (0.0, 0.0, 0.0)), item[0].tag))

    visited_nodes = {root}
    visited_edges = set()
    steps = [_Step(kind="node", ref=node_key[root])]
    stack = [(root, sorted_candidates(root))]

    while stack:
        node_id, candidates = stack[-1]
        descended = False
        while candidates:
            edge_ref, other = candidates.pop(0)
            if edge_ref.tag in visited_edges:
                continue
            visited_edges.add(edge_ref.tag)
            steps.append(_Step(kind="edge", ref=edge_ref.tag))
            if other not in visited_nodes:
                visited_nodes.add(other)
                steps.append(_Step(kind="node", ref=node_key[other]))
                stack.append((other, sorted_candidates(other)))
                descended = True
                break
        if not descended:
            stack.pop()

    return steps


# ------------------------------------------------------------------
# Number/Label writers
# ------------------------------------------------------------------

def _type_label(reg, library_id, type_id, fallback):
    type_def = reg.resolve_type(library_id, type_id) if library_id and type_id else None
    label = getattr(type_def, "label", "") if type_def is not None else ""
    return label or fallback


def _set_number_and_label(obj, number, description):
    changed = False
    if getattr(obj, "Number", "") != number:
        obj.Number = number
        changed = True
    new_label = "{} — {}".format(number, description)
    if hvaclib.set_label(obj, new_label):
        changed = True
    return changed


def _apply_segment_number(segment_obj, number, reg):
    description = _type_label(reg, getattr(segment_obj, "LibraryId", ""), getattr(segment_obj, "TypeId", ""), "Duct")
    return _set_number_and_label(segment_obj, number, description)


def _apply_junction_number(junction_obj, number):
    family = str(getattr(junction_obj, "Family", "") or "")
    description = family.capitalize() if family else "Junction"
    return _set_number_and_label(junction_obj, number, description)


def _renumber_components(junction_obj, junction_number, components, reg):
    """Primary gets '{junction_number}-P'; Inline components get
    '{junction_number}-01', '-02', ... in the junction's existing
    Primary-first/AttachedEdgeKey/PortSequence order (collectComponentObjects()
    already sorts this way) -- flat across every edge's own chain, matching
    the documentation numbering scheme rather than a per-edge one."""
    changed = False
    inline_index = 0
    for comp_obj in components:
        role = getattr(comp_obj, "ComponentRole", "")
        if role == "Primary":
            number = "{}-P".format(junction_number)
            fallback = str(getattr(junction_obj, "Family", "") or "").capitalize() or "Component"
        else:
            inline_index += 1
            number = "{}-{:02d}".format(junction_number, inline_index)
            fallback = "Component"
        description = _type_label(reg, getattr(comp_obj, "LibraryId", ""), getattr(comp_obj, "TypeId", ""), fallback)
        if _set_number_and_label(comp_obj, number, description):
            changed = True
    return changed, len(components)
