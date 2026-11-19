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
FreeCAD-facing adapter over analysis/sizing.py and analysis/balancing.py --
see those modules for the actual sizing algorithms. This module's job is
only: build a NetworkModel from the real DuctNetwork (via
FlowNetwork.solve_flow_components), pick the sizing strategy for the
network's SizingMethod, map the pure result back onto the FreeCAD-facing
SegmentSizeResult/DuctSizingResult dataclasses this module has always had
(so ui/TaskPanel.py doesn't need to change), and apply accepted sizes.

Nothing here touches the real segment objects: solve() only computes and
returns proposed sizes (a preview). apply(result) is a separate step that
writes the proposed Diameter/Width/Height onto the real objects -- the Size
Ducts command shows the preview first and lets the user confirm before
calling apply().
"""

from dataclasses import dataclass, field

from ..analysis.balancing import PressureBalanceCoordinator
from ..analysis.model import SizingSettings
from ..analysis.sizing import ConstantFrictionRateSizer, ConstantVelocitySizer, LocalStaticRegainSizer
from . import _analysis_adapter
from .FlowNetwork import solve_flow_components

_RECT_MODE_MAP = {"FixedAspectRatio": "aspect_ratio", "FixedHeight": "fixed_height", "FixedWidth": "fixed_width"}

_SIZERS = {
    "ConstantVelocity": ConstantVelocitySizer,
    "ConstantFrictionRate": ConstantFrictionRateSizer,
    "StaticRegain": LocalStaticRegainSizer,
    "PressureBalancedStaticRegain": PressureBalanceCoordinator,
}


@dataclass
class SegmentSizeResult:
    """Proposed new size for one segment, plus its old size for comparison."""

    key: str
    obj: object
    profile: str
    flow_lps: float = 0.0
    old_diameter_mm: float = 0.0
    old_width_mm: float = 0.0
    old_height_mm: float = 0.0
    new_diameter_mm: float = 0.0
    new_width_mm: float = 0.0
    new_height_mm: float = 0.0
    velocity_ms: float = 0.0
    reynolds: float = 0.0
    friction_rate_pa_per_m: float = 0.0
    regain_balanced: bool = True  # only meaningful for a StaticRegain-family SizingMethod
    changed: bool = False


@dataclass
class BalancingRequirementRow:
    """
    Display-ready mapping of one analysis.balancing.BalancingRequirement
    onto its real FreeCAD objects, so ui/TaskPanel.py can show a
    "Balancing Requirements" table the same way it already shows the
    segment-sizing table (Number/Label straight off a real object) without
    needing to understand junction_id/branch_port graph keys itself. Either
    *_obj may be None if the pure result's own key doesn't resolve to a
    live object (kept alongside its own raw key so the UI still has
    something to show in that case).
    """

    junction_obj: object
    branch_obj: object
    junction_key: str
    branch_key: str
    pressure_deficit_pa: float
    required_k: float


@dataclass
class DuctSizingResult:
    """Whole-network sizing result: one SegmentSizeResult per segment, plus any warnings."""

    segments: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    # Only ever populated when SizingMethod is PressureBalancedStaticRegain
    # and some branch's pressure deficit couldn't be closed by sizing alone
    # -- see analysis.balancing.BalancingRequirement, mapped onto
    # BalancingRequirementRow above. Each one is also mirrored into
    # `warnings` as a human-readable line (explaining WHY the path isn't
    # balanced), so it's visible in the existing Size Ducts warnings box
    # even without reading the structured table ui/TaskPanel.py builds
    # from this list.
    balancing_requirements: list = field(default_factory=list)


class DuctSizer:
    """Computes proposed duct dimensions for a DuctNetwork's segments (preview-only; see apply())."""

    def __init__(self, net_obj):
        self.net_obj = net_obj

    def solve(self):
        net = self.net_obj
        network_model, segment_map, junction_map, component_map, components, flow_warnings = solve_flow_components(net)

        settings = self._build_settings(net)
        sizer_cls = _SIZERS.get(settings.method, ConstantVelocitySizer)
        pure_result = sizer_cls().size(network_model, components, settings)

        result = DuctSizingResult(
            warnings=list(flow_warnings)
            + _analysis_adapter.humanize_diagnostics(pure_result.warnings, segment_map, junction_map, component_map)
        )
        for edge_key, sres in pure_result.segments.items():
            obj = segment_map[edge_key]
            result.segments.append(
                SegmentSizeResult(
                    key=edge_key,
                    obj=obj,
                    profile=sres.profile,
                    flow_lps=sres.flow_lps,
                    old_diameter_mm=sres.old_section.diameter_mm,
                    old_width_mm=sres.old_section.width_mm,
                    old_height_mm=sres.old_section.height_mm,
                    new_diameter_mm=sres.new_section.diameter_mm,
                    new_width_mm=sres.new_section.width_mm,
                    new_height_mm=sres.new_section.height_mm,
                    velocity_ms=sres.velocity_ms,
                    reynolds=sres.reynolds,
                    friction_rate_pa_per_m=sres.friction_rate_pa_per_m,
                    regain_balanced=sres.regain_balanced,
                    changed=sres.changed,
                )
            )

        # Advice only: where a duct's shared section size is far larger than
        # its own flow needs, a reducer (a new straight node) would save material.
        for suggestion in getattr(pure_result, "reducer_suggestions", []) or []:
            label = _analysis_adapter.element_identifier(segment_map.get(suggestion.edge_key)) or suggestion.edge_key
            result.warnings.append(
                "Size change: duct '{}' keeps the size of the duct upstream of it, which has {:.1f} times the "
                "area its own flow needs -- a reducer at its upstream end would allow a smaller size.".format(
                    label, suggestion.area_ratio
                )
            )

        requirements = getattr(pure_result, "balancing_requirements", [])
        if requirements:
            for req in requirements:
                junction_obj = junction_map.get(req.junction_id)
                branch_obj = segment_map.get(req.branch_port)
                result.balancing_requirements.append(
                    BalancingRequirementRow(
                        junction_obj=junction_obj,
                        branch_obj=branch_obj,
                        junction_key=req.junction_id,
                        branch_key=req.branch_port,
                        pressure_deficit_pa=req.pressure_deficit_pa,
                        required_k=req.required_k,
                    )
                )
                result.warnings.append(
                    "Pressure balancing: node '{}' branch '{}' has an unresolved deficit of {:.1f} Pa "
                    "-- consider a balancing damper here (required loss coefficient K ≈ {:.2f}).".format(
                        _analysis_adapter.element_identifier(junction_obj) or req.junction_id,
                        _analysis_adapter.element_identifier(branch_obj) or req.branch_port,
                        req.pressure_deficit_pa,
                        req.required_k,
                    )
                )

        return result

    @staticmethod
    def _build_settings(net):
        rect_mode_raw = str(getattr(net, "RectangularSizingMode", "FixedAspectRatio") or "FixedAspectRatio")
        return SizingSettings(
            method=str(getattr(net, "SizingMethod", "ConstantVelocity") or "ConstantVelocity"),
            rectangular_mode=_RECT_MODE_MAP.get(rect_mode_raw, "aspect_ratio"),
            aspect_ratio=float(getattr(net, "TargetAspectRatio", 2.0) or 2.0),
            target_velocity_ms=float(getattr(net, "TargetVelocity", 5.0) or 5.0),
            target_friction_rate_pa_per_m=float(getattr(net, "TargetFrictionRate", 1.0) or 1.0),
            regain_factor=float(getattr(net, "StaticRegainFactor", 0.75) or 0.75),
            min_velocity_ms=float(getattr(net, "MinimumVelocity", 2.5) or 2.5),
            # Note: no "or 10.0" fallback here -- unlike the other target
            # properties, 0 is a legitimate, intentional value for this one
            # (disable rounding, keep exact computed sizes), so an explicit
            # 0 must not be silently replaced by the default.
            rounding_mm=float(getattr(net, "SizeRoundingIncrement", 10.0)),
            default_roughness_mm=float(getattr(net, "DefaultRoughness", 0.09) or 0.09),
            default_width_mm=float(getattr(net, "DefaultWidth", 0.0) or 0.0),
            default_height_mm=float(getattr(net, "DefaultHeight", 0.0) or 0.0),
            size_change_policy=str(getattr(net, "SizeChangePolicy", "AtStraightJunctions") or "AtStraightJunctions"),
        )

    def apply(self, result):
        """Write every changed proposed size onto its real segment object."""
        changed_count = 0
        for sres in result.segments:
            if not sres.changed:
                continue
            obj = sres.obj
            if sres.profile == "Circular":
                obj.Diameter = sres.new_diameter_mm
            else:
                obj.Width = sres.new_width_mm
                obj.Height = sres.new_height_mm
            changed_count += 1
        return changed_count
