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
FreeCAD-facing adapter over analysis/pressure.py's pure PressureSolver --
see that module (and analysis/flow.py, analysis/paths.py) for the actual
airflow/pressure-drop algorithm. This module's job is only: build a
NetworkModel from the real DuctNetwork (via FlowNetwork.solve_flow_components,
which itself delegates to core/_analysis_adapter.py), run PressureSolver,
write the results back onto the real segment/junction/component Calc*
properties, and hand back the same FreeCAD-facing result dataclasses this
module has always had (SegmentResult/JunctionResult/ComponentResult/
AirflowSolveResult) so existing callers (ui/TaskPanel.py, ui/Observer.py)
don't need to change.
"""

from dataclasses import dataclass, field

from .FlowNetwork import FlowSolveError as AirflowSolveError
from .FlowNetwork import solve_flow_components
from ..analysis.pressure import K_DEFAULT, PressureSolver
from . import _analysis_adapter
from . import _component_results


@dataclass
class SegmentResult:
    """One segment's solved flow, velocity, and pressure loss."""
    key: str
    obj: object
    flow_lps: float = 0.0
    velocity_ms: float = 0.0
    reynolds: float = 0.0
    friction_loss_pa: float = 0.0
    fitting_loss_pa: float = 0.0
    total_loss_pa: float = 0.0
    cumulative_pressure_pa: float = 0.0


@dataclass
class JunctionResult:
    """One junction's solved total flow and static pressure."""
    key: str
    obj: object
    total_flow_lps: float = 0.0
    static_pressure_pa: float = 0.0
    is_source: bool = False
    warning: str = ""


@dataclass
class ComponentPortRow:
    """
    One display-ready row for the Calculate Airflow results UI: one
    component's own solved result at one of its local ports/edges, with its
    real FreeCAD object and human-readable labels already resolved (the
    connected segment's own Number/Label, falling back to the raw edge_key
    for a synthetic/internal one, or "Open" for a None atmosphere/open
    side -- see LossPath's own from_edge_key/to_edge_key semantics) -- see
    core/_component_results.ComponentPortResult for the underlying
    persisted data this is built from. Kept here, not in ui/TaskPanel.py, so
    no per-fitting engineering knowledge (which leg is "the branch", etc.,
    or which side of a path is upstream) needs to live in the UI layer --
    the UI only ever sees an already-directed path_label plus a plain
    status string, never edge keys or LossPath's from/to fields directly.

    path_label reads "<from> → <to>" from the same LossPath this
    result's own K/ΔP came from (analysis/pressure.py's
    resolve_loss_evaluation()) -- it's the SAME reference leg edge_key is
    already keyed by, just presented with its direction made explicit,
    e.g. "D01 → D02" for a diverging outlet leg or "D02 → D01" for
    a converging inlet leg. status is pr.status verbatim (an
    analysis.loss.LossStatus value's own .value string) -- never
    reconstructed from loss_coefficient/warnings, so a numeric fallback K
    stays visibly distinguishable from a real library/custom coefficient.
    """
    component_obj: object
    component_role: str  # "Primary" | "Inline"
    edge_key: str
    leg_label: str
    path_label: str
    status: str
    flow_lps: float = 0.0
    velocity_ms: float = 0.0
    loss_coefficient: float = None
    pressure_drop_pa: float = 0.0
    static_pressure_pa: float = None


@dataclass
class ComponentResult:
    """Solved results for one independently-solvable tree (one balancing terminal)."""
    reference_terminal_key: str
    segments: list = field(default_factory=list)
    junctions: list = field(default_factory=list)
    component_ports: list = field(default_factory=list)
    critical_terminal_key: str = ""
    critical_pressure_pa: float = 0.0


@dataclass
class AirflowSolveResult:
    """Whole-network result: one ComponentResult per tree, plus any warnings."""
    components: list = field(default_factory=list)
    warnings: list = field(default_factory=list)


class AirflowSolver:
    """Solves flow rate, velocity and pressure drop for a DuctNetwork's segments/junctions."""

    def __init__(self, net_obj):
        self.net_obj = net_obj

    def solve(self):
        network_model, segment_map, junction_map, component_map, components, flow_warnings = (
            solve_flow_components(self.net_obj)
        )

        result = AirflowSolveResult(warnings=list(flow_warnings))
        trees, pressure_warnings = PressureSolver().solve(network_model, components)
        result.warnings.extend(_analysis_adapter.humanize_diagnostics(
            pressure_warnings, segment_map, junction_map, component_map
        ))

        for tree in trees:
            result.components.append(
                self._map_component_result(tree, segment_map, junction_map, component_map)
            )

        # Equipment joining this network to others collects its port flows
        # and this network's worst path (ROADMAP 6.5).
        try:
            from . import Equipment

            Equipment.update_from_airflow(self.net_obj, result)
        except Exception as e:
            result.warnings.append("Could not update the connected equipment: {}".format(e))
        return result

    # ------------------------------------------------------------------
    # Map a pure ComponentTreeResult back onto real FreeCAD objects
    # ------------------------------------------------------------------

    @staticmethod
    def _edge_label(edge_key, segment_map):
        """
        Human-readable label for one side of a LossPath: a real edge_key's
        own connected segment Number/Label (falling back to the raw
        edge_key for a synthetic/internal one segment_map has no entry
        for), or "Open" for a None atmosphere/open side (a 1-port
        terminal device's other "side" -- see LossPath's own
        from_edge_key/to_edge_key docstring). Shared by leg_label and
        path_label so both use exactly the same resolution.
        """
        if edge_key is None:
            return "Open"
        leg_obj = segment_map.get(edge_key)
        return ((getattr(leg_obj, "Number", "") or getattr(leg_obj, "Label", "")) if leg_obj is not None else "") or edge_key

    @staticmethod
    def _map_component_result(tree, segment_map, junction_map, component_map):
        seg_results = []
        for edge_key, sres in tree.segments.items():
            obj = segment_map[edge_key]
            # fitting_loss_pa keeps its historical meaning here: everything
            # except straight-duct friction -- a node's own Primary
            # contribution plus that edge's own Inline chain, kept as two
            # separate fields in the pure layer (see SegmentModel) so
            # analysis.paths can report them separately, but combined again
            # for this FreeCAD-facing result since existing callers
            # (ui/TaskPanel.py) only ever show the combined figure.
            fitting_loss_pa = sres.junction_loss_pa + sres.component_loss_pa

            obj.CalcFlowRate = sres.flow_lps
            obj.CalcVelocity = sres.velocity_ms
            obj.CalcReynoldsNumber = sres.reynolds
            obj.CalcFrictionLoss = sres.friction_loss_pa
            obj.CalcFittingLoss = fitting_loss_pa
            obj.CalcTotalLoss = sres.total_loss_pa
            obj.CalcCumulativePressure = sres.cumulative_pressure_pa

            seg_results.append(SegmentResult(
                key=edge_key, obj=obj, flow_lps=sres.flow_lps, velocity_ms=sres.velocity_ms,
                reynolds=sres.reynolds, friction_loss_pa=sres.friction_loss_pa,
                fitting_loss_pa=fitting_loss_pa, total_loss_pa=sres.total_loss_pa,
                cumulative_pressure_pa=sres.cumulative_pressure_pa,
            ))

        junc_results = []
        for node_id, jres in tree.junctions.items():
            obj = junction_map[node_id]
            obj.CalcTotalFlowRate = jres.total_flow_lps
            obj.CalcStaticPressure = jres.static_pressure_pa
            obj.IsFlowSource = jres.is_source
            warning = _analysis_adapter.humanize_diagnostics(
                [jres.warning], segment_map, junction_map, component_map
            )[0] if jres.warning else ""
            obj.CalcLossWarning = warning

            junc_results.append(JunctionResult(
                key=node_id, obj=obj, total_flow_lps=jres.total_flow_lps,
                static_pressure_pa=jres.static_pressure_pa, is_source=jres.is_source, warning=warning,
            ))

        # Per-component (Primary AND Inline) port-level results -- written
        # onto each component's own CalcPortResultsJson (always) plus its
        # legacy scalar Calc* properties (only when unambiguous) -- see
        # _component_results.write_port_results(). This is purely a
        # *retained record* of the loss each component already contributed
        # above (segment loop, junction_loss_pa/component_loss_pa) -- never
        # a second application of it.
        component_ports = []
        for component_id, cres in tree.components.items():
            comp_obj = component_map.get(component_id)
            if comp_obj is None:
                continue
            _component_results.write_port_results(comp_obj, cres.port_results)

            role = str(getattr(comp_obj, "ComponentRole", "") or "")
            for edge_key, pr in cres.port_results.items():
                leg_label = AirflowSolver._edge_label(edge_key, segment_map)
                path_label = "{} → {}".format(
                    AirflowSolver._edge_label(pr.from_edge_key, segment_map),
                    AirflowSolver._edge_label(pr.to_edge_key, segment_map),
                )
                component_ports.append(ComponentPortRow(
                    component_obj=comp_obj, component_role=role, edge_key=edge_key, leg_label=leg_label,
                    path_label=path_label, status=pr.status,
                    flow_lps=pr.flow_lps, velocity_ms=pr.velocity_ms, loss_coefficient=pr.loss_coefficient,
                    pressure_drop_pa=pr.pressure_drop_pa, static_pressure_pa=pr.static_pressure_pa,
                ))

        critical = tree.critical_path
        return ComponentResult(
            reference_terminal_key=tree.reference_terminal_id,
            segments=seg_results,
            junctions=junc_results,
            component_ports=component_ports,
            critical_terminal_key=critical.terminal_node_id if critical is not None else "",
            critical_pressure_pa=critical.path.loss.total_pa if critical is not None else 0.0,
        )
