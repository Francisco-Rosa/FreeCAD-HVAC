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
PressureBalanceCoordinator: sits on top of a base sizing strategy (default
LocalStaticRegainSizer -- but any SizingStrategy-shaped object with a
.size(network, components, settings) method works, so a future
EqualFrictionSizer/ConstantVelocitySizer could reuse this same layer) and
iteratively narrows the pressure-loss gap between sibling branch paths.

Deliberately compact, not a general optimizer: each iteration re-solves the
whole network's pressure/paths (analysis.pressure/paths), finds the
terminal whose path has the largest pressure_deficit_pa relative to the
critical path, and shrinks the single most-upstream segment unique to that
path (the one right where it branches off the critical path) by a fixed
step, which adds friction and so reduces the deficit. Repeats until every
path is within settings.balance_tolerance_pa of the critical one, a fixed
iteration cap is hit, or a path can't be shrunk any further (its velocity
would exceed a practical ceiling) -- at which point its remaining deficit
is reported as an explicit BalancingRequirement (e.g. "fit a damper here"),
rather than forcing an unrealistic duct size to close it.

Sizing sections win over balancing (owner decision, 13 November 2026): the
base sizer gives every sizing section one size (see
analysis.sizing.apply_sizing_sections), and balancing never splits one
again. A shrink step resizes the whole section the divergence segment
belongs to; a section that also carries the critical path cannot be shrunk
(it would slow the critical path down too), so its deficit is reported as a
BalancingRequirement instead.
"""

from dataclasses import dataclass, field
from typing import List

from . import friction as friction_models
from . import physics
from .model import NetworkModel, SectionModel, SizingSettings
from .pressure import PressureSolver
from .sizing import DuctSizingResult, LocalStaticRegainSizer, SegmentSizeResult

# Shrink step per balancing iteration -- a fixed percentage (rather than a
# fixed mm step) so it works uniformly across profiles/sizes and doesn't
# need SizingSettings.rounding_mm to be non-zero.
_SHRINK_FACTOR = 0.95

# Never shrink a segment past this multiple of the larger of the network's
# target/minimum velocity -- SizingSettings has no dedicated "maximum
# velocity" of its own, so this stands in for "a practical ceiling on how
# fast a balancing adjustment is allowed to push a duct".
_MAX_VELOCITY_FACTOR = 2.0


@dataclass
class BalancingRequirement:
    """
    A branch leg whose pressure deficit couldn't be resolved by sizing
    alone -- e.g. "fit a damper here with this loss coefficient". Doesn't
    require an actual damper FreeCAD object to exist.
    """
    junction_id: str
    branch_port: str
    pressure_deficit_pa: float
    required_k: float


@dataclass
class PressureBalancedSizingResult(DuctSizingResult):
    balancing_requirements: List[BalancingRequirement] = field(default_factory=list)


class PressureBalanceCoordinator:
    def __init__(self, base_sizer=None):
        self.base_sizer = base_sizer if base_sizer is not None else LocalStaticRegainSizer()

    def size(self, network: NetworkModel, components, settings: SizingSettings) -> PressureBalancedSizingResult:
        result = PressureBalancedSizingResult()
        for comp in components:
            self._solve_component(network, comp, settings, result)
        return result

    def _solve_component(self, network, comp, settings, result):
        base = self.base_sizer.size(network, [comp], settings)
        result.warnings.extend(base.warnings)
        # The sections and reducer advice come from the base sizing (balancing keeps sections whole).
        result.sections.extend(base.sections)
        result.reducer_suggestions.extend(base.reducer_suggestions)
        if not base.segments:
            return

        sections = {edge_key: sres.new_section for edge_key, sres in base.segments.items()}
        # Which sizing section each segment belongs to (a lone segment is its own section).
        section_of = {}
        for group in base.sections:
            members = [edge_key for edge_key in group if edge_key in sections]
            for edge_key in members:
                section_of[edge_key] = members
        solver = PressureSolver()
        exhausted = set()
        tree = None

        for _ in range(settings.balance_max_iterations):
            working_net = network.with_segment_sections(sections)
            trees, p_warnings = solver.solve(working_net, [comp])
            result.warnings.extend(p_warnings)
            if not trees:
                break
            tree = trees[0]
            critical = tree.critical_path
            if critical is None or not tree.paths:
                break

            candidates = [
                p for p in tree.paths
                if p.terminal_node_id != critical.terminal_node_id
                and p.terminal_node_id not in exhausted
                and p.pressure_deficit_pa > settings.balance_tolerance_pa
            ]
            if not candidates:
                break  # every remaining path is within tolerance (or already reported)

            worst = max(candidates, key=lambda p: p.pressure_deficit_pa)
            divergence_edge = self._divergence_edge(worst, critical.path)

            # Step: shrink the whole sizing section of the divergence segment
            # one step, unless that section also carries the critical path.
            shrunk, members = None, []
            if divergence_edge is not None:
                members = section_of.get(divergence_edge, [divergence_edge])
                if not set(members) & set(critical.path.edge_keys):
                    # The member with the most flow hits the velocity ceiling first.
                    flow_lps = max(comp.edge_flow_lps.get(edge_key, 0.0) for edge_key in members)
                    shrunk = self._shrink(sections[divergence_edge], flow_lps, settings)
            if shrunk is None:
                exhausted.add(worst.terminal_node_id)
                self._emit_requirement(result, worst, divergence_edge, tree, network.air)
                continue
            for edge_key in members:
                sections[edge_key] = shrunk
        else:
            result.warnings.append(
                "Pressure balancing for terminal '{}' did not settle after {} iterations; sizes shown "
                "are from the last pass.".format(comp.root_node_id, settings.balance_max_iterations)
            )

        self._assemble_results(result, network, comp, base, sections, tree)

    @staticmethod
    def _divergence_edge(worst_path, critical_path):
        """First edge_key on worst_path not also on critical_path -- i.e. where the two paths branch apart."""
        critical_edges = set(critical_path.edge_keys)
        for edge_key in worst_path.edge_keys:
            if edge_key not in critical_edges:
                return edge_key
        return None

    @staticmethod
    def _shrink(section: SectionModel, flow_lps: float, settings: SizingSettings):
        """One shrink step smaller, or None if that would exceed the practical velocity ceiling."""
        if section.profile == "Circular":
            candidate = SectionModel(profile="Circular", diameter_mm=section.diameter_mm * _SHRINK_FACTOR)
        else:
            # Scale both dimensions together -- simplest uniform shrink,
            # and preserves aspect ratio for a fixed-aspect-ratio network.
            candidate = SectionModel(
                profile=section.profile,
                width_mm=section.width_mm * _SHRINK_FACTOR,
                height_mm=section.height_mm * _SHRINK_FACTOR,
            )

        area_m2 = physics.section_area_m2(candidate)
        if area_m2 <= 0.0 or flow_lps <= 1e-9:
            return None

        ceiling_velocity_ms = _MAX_VELOCITY_FACTOR * max(settings.target_velocity_ms, settings.min_velocity_ms)
        velocity_ms = physics.velocity_from_flow(physics.lps_to_m3s(flow_lps), area_m2)
        if velocity_ms > ceiling_velocity_ms:
            return None
        return candidate

    @staticmethod
    def _emit_requirement(result, worst_path, divergence_edge, tree, air):
        if divergence_edge is None:
            # Shouldn't happen (two distinct terminal paths always diverge
            # somewhere before the terminal itself) -- report against the
            # path's own terminal rather than dropping the deficit silently.
            junction_id = worst_path.terminal_node_id
            velocity_ms = 0.0
        else:
            idx = worst_path.edge_keys.index(divergence_edge)
            junction_id = worst_path.node_ids[idx]
            sres = tree.segments.get(divergence_edge)
            velocity_ms = sres.velocity_ms if sres is not None else 0.0

        vp = physics.velocity_pressure(air.density_kg_m3, velocity_ms)
        required_k = (worst_path.pressure_deficit_pa / vp) if vp > 1e-9 else 0.0
        result.balancing_requirements.append(BalancingRequirement(
            junction_id=junction_id,
            branch_port=divergence_edge or "",
            pressure_deficit_pa=worst_path.pressure_deficit_pa,
            required_k=required_k,
        ))

    @staticmethod
    def _friction_rate_pa_per_m(section, seg, air, flow_lps):
        if flow_lps <= 1e-9:
            return 0.0
        area_m2 = physics.section_area_m2(section)
        dh_m = physics.section_hydraulic_diameter_m(section)
        if area_m2 <= 0.0 or dh_m <= 0.0:
            return 0.0
        return friction_models.rate_pa_per_m(
            seg.friction_model,
            physics.lps_to_m3s(flow_lps),
            area_m2,
            dh_m,
            physics.mm_to_m(seg.roughness_mm),
            air.density_kg_m3,
            air.kinematic_viscosity_m2_s,
        )

    def _assemble_results(self, result, network, comp, base, sections, tree):
        """Final SegmentSizeResult per edge, using the last successfully-solved pressure pass for velocity/Reynolds."""
        for edge_key in comp.edge_keys:
            base_sres = base.segments.get(edge_key)
            if base_sres is None:
                continue
            new_section = sections[edge_key]
            old_section = network.segments[edge_key].section
            pressure_sres = tree.segments.get(edge_key) if tree is not None else None

            velocity_ms = pressure_sres.velocity_ms if pressure_sres is not None else base_sres.velocity_ms
            reynolds = pressure_sres.reynolds if pressure_sres is not None else base_sres.reynolds
            friction_rate = self._friction_rate_pa_per_m(new_section, network.segments[edge_key], network.air, base_sres.flow_lps)

            changed = (
                abs(new_section.diameter_mm - old_section.diameter_mm) > 1e-6
                or abs(new_section.width_mm - old_section.width_mm) > 1e-6
                or abs(new_section.height_mm - old_section.height_mm) > 1e-6
            )

            result.segments[edge_key] = SegmentSizeResult(
                edge_key=edge_key, profile=base_sres.profile, flow_lps=base_sres.flow_lps,
                old_section=old_section, new_section=new_section, velocity_ms=velocity_ms, reynolds=reynolds,
                friction_rate_pa_per_m=friction_rate, regain_balanced=base_sres.regain_balanced, changed=changed,
            )
