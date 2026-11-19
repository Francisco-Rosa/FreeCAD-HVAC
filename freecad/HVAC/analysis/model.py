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
Pure data model for the analysis/ package: plain dataclasses describing one
network's engineering-relevant state (sections, ports, components, nodes,
segments) and settings (air state, sizing settings). Nothing here knows about
FreeCAD -- every object is related back to a real FreeCAD document object by
a stable string id (an edge_key or node_id) rather than a direct reference,
so analysis/ never has to import core/, library/, or utils/hvaclib. Building
one of these from a real DuctNetwork is core/_analysis_adapter.py's job;
turning a solved/sized one back into FreeCAD property writes is the job of
the solver-specific adapter (core/AirflowSolver.py, core/DuctSizer.py).
"""

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple


@dataclass
class SectionModel:
    """
    A duct's cross-section, in mm. `profile` is one of "Circular" /
    "Rectangular" / "Oval" -- see physics.py's section_area_m2/
    section_hydraulic_diameter_m for how each profile turns this into an
    area/hydraulic diameter.
    """

    profile: str = ""
    diameter_mm: float = 0.0
    width_mm: float = 0.0
    height_mm: float = 0.0


@dataclass
class PortModel:
    """
    One local port of a NodeModel or a ComponentModel -- either a real
    network edge (its edge_key matches a SegmentModel, and is_real_edge is
    True) or, for a ComponentModel only, a synthetic internal seam with no
    segment of its own (an inline chain's interior connection point,
    is_real_edge False) -- see ComponentModel/NodeModel.inline_chains.

    flow_lps/velocity_ms/reynolds are set by the adapter for a NodeModel's
    own ports where already known (a real edge's already-solved flow); a
    solve never mutates a PortModel in place -- see analysis/pressure.py,
    which builds its own fresh per-port velocity data for a loss_evaluator
    call instead, so the same model can be re-solved (e.g. across
    PressureBalanceCoordinator's iterations) without stale leftovers.
    """

    edge_key: str
    node_id: str
    flow_into_node: Optional[bool]
    section: SectionModel
    is_real_edge: bool = True
    flow_lps: float = 0.0
    velocity_ms: float = 0.0
    reynolds: float = 0.0


# A loss evaluator is a plain callable, built by the FreeCAD adapter (it
# closes over whatever library type-def/properties it needs), so analysis/
# never resolves a library type itself. Input: {edge_key: {"velocity_ms":
# float, "flow_lps": float, "reynolds": float}} for this component's own
# local ports. Output is an analysis.loss.LossEvaluation (see that module),
# or None only when this component's type itself couldn't be resolved at
# all -- distinct from a resolved type's own loss function returning an
# UNSUPPORTED LossEvaluation for the current flow topology (see
# analysis/pressure.py's resolve_loss_evaluation(), which normalizes both
# into the same explicit FALLBACK policy).
LossEvaluator = Callable[[Dict[str, Dict[str, float]]], "Optional[object]"]


@dataclass
class ComponentModel:
    """
    One physical fitting -- a node's Primary component, or one Inline
    device in a through/2-port node's chain (see NodeModel). `ports` are
    this component's own LOCAL ports (mirrors DuctComponent.LocalPortsJson).
    `roughness_mm` is derived from this component's own flow-surface
    construction and is also exposed to its library loss evaluator.
    Solved per-component results (flow/velocity/K/pressure-drop) are never
    written back onto this object -- pressure.py returns a fresh
    ComponentResult per solve instead, so the same ComponentModel can be
    resolved repeatedly (e.g. across PressureBalanceCoordinator's
    iterations) without stale data from a previous solve leaking in.
    """

    component_id: str
    role: str  # "primary" | "inline"
    ports: List[PortModel] = field(default_factory=list)
    loss_evaluator: Optional[LossEvaluator] = None
    roughness_mm: float = 0.0


@dataclass
class NodeModel:
    """
    One junction. `ports` are this node's REAL ports (one per connected
    segment). `flow_boundary` mirrors DuctJunction.FlowBoundary exactly --
    one of "Auto" (this terminal's flow is solved by mass balance; exactly
    one per sub-network), "Fixed" (use `design_flow_lps` as-is, including
    0.0 -- a genuine zero flow, not "unset"), or "Closed" (a sealed
    termination; contributes zero flow regardless of `design_flow_lps`) --
    see analysis/flow.py for how each state is used.

    `inline_chains` holds, per real edge_key, that edge's own additional
    Inline devices in series with the Primary (only ever non-empty at a
    simple through/2-port node) -- each chain is evaluated against that
    edge's own flow only, independently of the Primary.
    """

    node_id: str
    topology: str
    degree: int
    ports: List[PortModel] = field(default_factory=list)
    design_flow_lps: float = 0.0
    flow_boundary: str = "Auto"
    primary_component: Optional[ComponentModel] = None
    inline_chains: Dict[str, List[ComponentModel]] = field(default_factory=dict)
    # Classifier family without the topology ("tee", "bend_90", "straight",
    # "transition", ...) and the edge_key pairs it found in line with each
    # other (a tee's run, a cross's two runs). Used to decide where a duct
    # may change size (see sizing.sizing_sections).
    family: str = ""
    run_edge_pairs: List[Tuple[str, str]] = field(default_factory=list)
    # False pins a straight through node: the ducts on both sides keep one size.
    allow_size_change: bool = True


@dataclass
class SegmentModel:
    """
    One duct segment. `section`/`length_mm`/`roughness_mm` are its current
    (or, during sizing, its previous pass's proposed) size. The three
    `*_override_*` fields mirror a segment's own Velocity/
    RectangularSizingMode/TargetAspectRatio FreeCAD properties -- when set,
    they override the network-wide SizingSettings for this segment only
    (see analysis/sizing.py).

    flow_lps/velocity_ms/reynolds/friction_loss_pa/junction_loss_pa/
    component_loss_pa start at 0 and are filled in during a solve.
    `friction_loss_pa` is straight-duct loss; `junction_loss_pa` is the
    node's own Primary contribution attributed onto this segment;
    `component_loss_pa` is this edge's own Inline chain contribution --
    kept separate (rather than one combined "fitting_loss_pa") so
    analysis/paths.py can report duct/fitting/component loss separately
    along a path. total_loss_pa is their sum.
    """

    edge_key: str
    section: SectionModel
    length_mm: float
    roughness_mm: float = 0.0
    velocity_override_ms: float = 0.0
    rectangular_mode_override: str = ""
    aspect_ratio_override: float = 0.0
    flow_lps: float = 0.0
    velocity_ms: float = 0.0
    reynolds: float = 0.0
    friction_loss_pa: float = 0.0
    junction_loss_pa: float = 0.0
    component_loss_pa: float = 0.0
    cumulative_pressure_pa: float = 0.0
    # An analysis.friction model (anything with rate_pa_per_m); None means
    # the default, Darcy-Weisbach with Altshul-Tsal. Built once by the
    # FreeCAD adapter from the segment type-def's "friction" entry or the
    # network's FrictionModel property.
    friction_model: Optional[object] = None

    @property
    def total_loss_pa(self):
        return self.friction_loss_pa + self.junction_loss_pa + self.component_loss_pa


@dataclass
class AirState:
    """Air properties used throughout a solve -- density for velocity pressure, viscosity for Reynolds number."""

    density_kg_m3: float = 1.204
    kinematic_viscosity_m2_s: float = 1.51e-5


@dataclass
class SizingSettings:
    """
    Network-wide sizing/boundary-condition settings -- one object standing
    in for the long parameter lists core/DuctSizer.py currently threads
    through every sizing call, mirroring DuctNetwork's own "HVAC Duct
    Sizing" property group.
    """

    method: str = "ConstantVelocity"
    rectangular_mode: str = "aspect_ratio"  # "aspect_ratio" | "fixed_height" | "fixed_width"
    aspect_ratio: float = 2.0
    target_velocity_ms: float = 5.0
    target_friction_rate_pa_per_m: float = 1.0
    regain_factor: float = 0.75
    min_velocity_ms: float = 2.5
    rounding_mm: float = 10.0
    default_roughness_mm: float = 0.09
    default_width_mm: float = 0.0
    default_height_mm: float = 0.0
    balance_tolerance_pa: float = 5.0
    balance_max_iterations: int = 10
    # Where a duct may change size (see sizing.sizing_sections):
    # "AtStraightJunctions": at every junction the air passes straight
    #   through -- in-line nodes (straight, transition, offset) and the run
    #   of a tee or cross; never through a bend.
    # "AtInlineNodesOnly": only at in-line two-port nodes; a tee or cross
    #   run keeps one size.
    # "EverySegment": every segment is sized for its own flow.
    size_change_policy: str = "AtStraightJunctions"
    # Suggest an extra reducer where a segment's shared size has at least
    # this many times the area its own flow would need.
    reducer_advice_area_ratio: float = 1.25


@dataclass
class NetworkModel:
    """
    One whole network's engineering-relevant state: every node/segment, plus
    the raw edge->node-pair topology (edges) flow.py needs to build its own
    working graph, plus air state. Settings (SizingSettings) are passed
    alongside a NetworkModel to whichever solver needs them, rather than
    stored on it, since the same network can be solved/sized under
    different settings without rebuilding it.
    """

    nodes: Dict[str, NodeModel] = field(default_factory=dict)
    segments: Dict[str, SegmentModel] = field(default_factory=dict)
    edges: Dict[str, Tuple[str, str]] = field(default_factory=dict)
    air: AirState = field(default_factory=AirState)

    def with_segment_sections(self, overrides: Dict[str, SectionModel]) -> "NetworkModel":
        """
        A shallow-copied NetworkModel with the given edge_keys' sections
        replaced -- used by PressureBalanceCoordinator to re-solve pressure
        against a proposed size without mutating the original model.
        """
        new_segments = dict(self.segments)
        for edge_key, section in overrides.items():
            seg = new_segments[edge_key]
            new_segments[edge_key] = SegmentModel(
                edge_key=seg.edge_key,
                section=section,
                length_mm=seg.length_mm,
                roughness_mm=seg.roughness_mm,
                velocity_override_ms=seg.velocity_override_ms,
                rectangular_mode_override=seg.rectangular_mode_override,
                aspect_ratio_override=seg.aspect_ratio_override,
            )
        return NetworkModel(nodes=self.nodes, segments=new_segments, edges=self.edges, air=self.air)
