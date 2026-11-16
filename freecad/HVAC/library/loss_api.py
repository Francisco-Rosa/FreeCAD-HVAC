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

"""Stable fitting-loss calculations exposed to HVAC libraries.

Loss modules receive this class as ``context["loss_api"]``. It translates
library context data into the pure SMACNA/ASHRAE table inputs and returns
an analysis.loss.LossEvaluation -- never a bare dict/float/None (see that
module's own docstring for the LossPath/LossEvaluation/LossStatus shapes).
Generator code never imports analysis.loss directly; it compares against
the class-level LossStatus aliases below instead (e.g.
``result.status == context["loss_api"].UNSUPPORTED``).
"""

import math

from ..analysis import physics as airflow
from ..analysis.loss import LossEvaluation, LossPath, LossStatus
from .fittings import taps as tap_fittings
from .fittings import transitions as transition_fittings
from .library_api import HVACLibraryAPI
from .loss_tables import elbows as elbow_tables
from .loss_tables import entries_exits as entry_exit_tables
from .loss_tables import junctions_converging as converging_tables
from .loss_tables import junctions_diverging as diverging_tables
from .loss_tables import obstructions as obstruction_tables
from .loss_tables import table as loss_table
from .loss_tables import transitions as transition_tables


class HVACLossAPI:
    """Library-facing fitting-loss orchestration API."""

    API_VERSION = 1

    # The public surface (see HVACLibraryAPI.PUBLIC).
    PUBLIC = frozenset(
        {
            "API_VERSION", "APPROXIMATION", "CUSTOM", "EXACT", "FALLBACK", "PUBLIC", "UNSUPPORTED",
            "branch_loss", "branch_loss_bullhead", "damper_loss", "elbow_loss", "entry_loss", "exit_loss",
            "fan_connection_loss", "fixed_pressure_drop_loss", "inline_device_loss", "manifold_loss",
            "obstruction_loss", "offset_loss", "plenum_loss", "screen_loss", "sum_losses",
            "terminal_component_loss", "transition_loss", "uniform_fallback_loss", "wye_loss"
        }
    )

    # Aliases so generator code (which only ever sees context["loss_api"],
    # never imports analysis.loss directly) can compare a result's status
    # without a new import path.
    EXACT = LossStatus.EXACT
    APPROXIMATION = LossStatus.APPROXIMATION
    CUSTOM = LossStatus.CUSTOM
    FALLBACK = LossStatus.FALLBACK
    UNSUPPORTED = LossStatus.UNSUPPORTED

    # ------------------------------------------------------------------
    # LossEvaluation/LossPath builders -- shared by every method below.
    # ------------------------------------------------------------------

    @staticmethod
    def _leg_path(port, other_edge_key, k, source=None):
        """
        LossPath for `port` (has its own edge_key/flow_into_junction)
        against `other_edge_key` (the fitting's other side -- another
        port's edge_key, or None for a 1-port terminal's open-atmosphere
        side). `k` is referenced to `port`'s own velocity -- the
        convention every table in this module already uses.
        """
        edge_key = port["edge_key"]
        if port.get("flow_into_junction"):
            from_edge, to_edge = edge_key, other_edge_key
        else:
            from_edge, to_edge = other_edge_key, edge_key
        return LossPath(from_edge, to_edge, edge_key, float(k), source=source)

    @staticmethod
    def _exact(paths, warning=None):
        return LossEvaluation(paths=list(paths), status=LossStatus.EXACT, warning=warning)

    @staticmethod
    def _approximation(paths, warning=None):
        return LossEvaluation(paths=list(paths), status=LossStatus.APPROXIMATION, warning=warning)

    @staticmethod
    def _unsupported(warning=None):
        return LossEvaluation(paths=[], status=LossStatus.UNSUPPORTED, warning=warning)

    @staticmethod
    def _bend_dims_mm(port, bend_normal):
        """
        (W, H) of a rectangular or oval section the way the elbow tables
        mean them: W lies in the plane of the bend, H is square to it. Which
        of the duct's own Width/Height that is depends on how the section
        is turned relative to the bend.
        """
        width = float(HVACLibraryAPI.port_width(port))
        height = float(HVACLibraryAPI.port_height(port))
        if bend_normal is None:
            return width, height
        _placement, x_axis, _y_axis, _z_axis = HVACLibraryAPI.make_profile_frame(
            HVACLibraryAPI.port_direction(port), HVACLibraryAPI.port_profile_x_axis(port)
        )
        # The duct's Width runs along x_axis: if that points out of the bend plane, Width is the tables' H.
        if abs(x_axis.dot(bend_normal)) > 0.7071:
            return height, width
        return width, height

    @staticmethod
    def elbow_loss(context):
        """
        Loss of an elbow (SMACNA Table 14-10), for any turn angle.
        properties["ElbowConstruction"] picks how the elbow is made:

        - "smooth" (default): smooth radius. Round: 14-10 A. Rectangular:
          14-10 F, or 14-10 G when SplitterVanes is 1 to 3. Needs
          CenterlineRadius.
        - "gored": made of straight pieces, NumberOfCuts + 1 of them. Round
          with 3 to 5 pieces: 14-10 B (needs CenterlineRadius). Two pieces
          is a plain mitered elbow (below). A gored rectangular elbow has
          no table; the smooth one is used and flagged.
        - "mitered": one mitre joint. Round: 14-10 C. Rectangular: 14-10 D.
        - "turning_vanes": rectangular, mitered, with turning vanes: 14-10 H
          for the VaneDesign given (see loss_tables.elbows.TURNING_VANES).

        Expects exactly 2 connected ports (one inlet, one outlet). Returns
        one LossPath referenced to the outlet's velocity: EXACT when the
        point was inside the printed table, APPROXIMATION (with the reason)
        when it was not, UNSUPPORTED when the fitting cannot be worked out.
        """
        try:
            ports = HVACLibraryAPI.connected_ports(context)
            if len(ports) != 2:
                return HVACLossAPI._unsupported("expected exactly 2 connected ports, found {}".format(len(ports)))
            outlet = next((p for p in ports if p.get("flow_into_junction") is False), None)
            if outlet is None:
                return HVACLossAPI._unsupported("could not resolve outlet direction")
            inlet = next((p for p in ports if p is not outlet), None)

            properties = context.get("properties") or {}
            construction = HVACLossAPI._choice(properties.get("ElbowConstruction"), "smooth")
            radius = float(properties.get("CenterlineRadius", 0.0) or 0.0)
            profile = HVACLibraryAPI.port_profile(outlet)
            if profile not in ("Circular", "Rectangular", "Oval"):
                return HVACLossAPI._unsupported("unsupported profile '{}'".format(profile))
            is_round = profile == "Circular"
            reynolds = float(outlet.get("reynolds", 0.0) or 0.0)
            notes = []

            # Step 1: the turn. Port directions point outward, so the two
            # ports of a straight run are 180 deg apart: the turn is
            # whatever is missing from that.
            d_in = HVACLibraryAPI.unit(HVACLibraryAPI.port_direction(inlet))
            d_out = HVACLibraryAPI.unit(HVACLibraryAPI.port_direction(outlet))
            theta = max(0.0, 180.0 - math.degrees(HVACLibraryAPI.angle_between(d_in, d_out)))
            normal = d_in.cross(d_out)
            normal = HVACLibraryAPI.unit(normal) if normal.Length > 1.0e-9 else None

            # Step 2: the section, as the tables measure it.
            if is_round:
                diameter = float(HVACLibraryAPI.port_diameter(outlet))
                if diameter <= 0.0:
                    return HVACLossAPI._unsupported("invalid diameter")
            else:
                width, height = HVACLossAPI._bend_dims_mm(outlet, normal)
                if width <= 0.0 or height <= 0.0:
                    return HVACLossAPI._unsupported("invalid width/height")

            def smooth_rectangular():
                if reynolds <= 0.0:
                    return None
                return elbow_tables.smooth_rect(height / width, radius / width, reynolds, theta)

            # Step 3: a gored elbow of two pieces is a plain mitered one.
            pieces = int(properties.get("NumberOfCuts", 1) or 1) + 1
            if construction == "gored" and pieces <= 2:
                construction = "mitered"

            # Step 4: read the table for this construction.
            if construction in ("smooth", "gored") and radius <= 0.0:
                return HVACLossAPI._unsupported("invalid diameter/CenterlineRadius")

            if construction == "smooth":
                vanes = int(properties.get("SplitterVanes", 0) or 0)
                if is_round:
                    lookup = elbow_tables.smooth_round(radius / diameter, theta)
                elif vanes > 0:
                    throat = radius - width / 2.0
                    if throat <= 0.0:
                        return HVACLossAPI._unsupported("CenterlineRadius leaves no throat radius for splitter vanes")
                    if vanes > 3:
                        notes.append("table stops at 3 splitter vanes")
                    lookup = elbow_tables.smooth_rect_splitter_vanes(
                        min(vanes, 3), throat / width, height / width, theta
                    )
                else:
                    lookup = smooth_rectangular()
                    if lookup is None:
                        return HVACLossAPI._unsupported("no Reynolds number available (zero flow?)")
            elif construction == "gored":
                if is_round:
                    if pieces > 5:
                        notes.append("table stops at 5 pieces")
                    lookup = elbow_tables.gored_round(min(pieces, 5), radius / diameter, theta)
                else:
                    lookup = smooth_rectangular()
                    if lookup is None:
                        return HVACLossAPI._unsupported("no Reynolds number available (zero flow?)")
                    notes.append("no table for a gored rectangular elbow, smooth radius elbow used")
            elif construction == "mitered":
                re = reynolds if reynolds > 0.0 else None
                if is_round:
                    lookup = elbow_tables.mitered_round(theta, re)
                else:
                    lookup = elbow_tables.mitered_rect(height / width, theta, re)
            elif construction == "turning_vanes":
                if is_round:
                    return HVACLossAPI._unsupported("turning vanes are tabulated for rectangular elbows only")
                design = HVACLossAPI._choice(properties.get("VaneDesign"), "single_r50_s38")
                lookup = elbow_tables.mitered_rect_turning_vanes(design, float(outlet.get("velocity_ms", 0.0) or 0.0))
                if abs(theta - 90.0) > 1.0:
                    notes.append("table is for a 90 degree elbow")
            else:
                return HVACLossAPI._unsupported("unknown ElbowConstruction '{}'".format(construction))

            if profile == "Oval":
                notes.append("table is not printed for an Oval duct")
            source = "smacna_elbow" if construction == "smooth" else "smacna_elbow_" + construction
            return HVACLossAPI._from_lookup(outlet, inlet["edge_key"], lookup, source, notes)
        except Exception as exc:
            return HVACLossAPI._unsupported("unexpected error computing elbow loss: {}".format(exc))

    @staticmethod
    def transition_loss(context):
        """
        Loss of a transition: a change of duct size, and possibly of shape,
        along a straight axis (SMACNA Tables 14-11 and 14-12).

        - Round to round: expansion 14-11 A (by Reynolds number), contraction 14-12 A.
        - Rectangular to rectangular: expansion 14-11 E when only one pair of
          sides diverges ("sides straight"), else 14-11 B (pyramidal);
          contraction 14-12 A. The angle is the larger of the two side-pair
          angles (the "major angle" of the tables).
        - Round to rectangular, either way: the equivalent angle of 14-11 C/D,
          then 14-11 B for an expansion or 14-12 A for a contraction (the
          latter is not printed for this shape: approximation).
        - Oval is read as the rectangle of the same width and height: approximation.

        properties["TransitionLength"] is the body length; 0 uses the duct
        size (at least 100 mm), as the geometry does. Returns one LossPath
        referenced to the outlet's velocity: EXACT when every lookup was
        inside a table printed for this fitting, APPROXIMATION (with the
        reason) when not, UNSUPPORTED when it cannot be worked out.
        """
        try:
            ports = HVACLibraryAPI.connected_ports(context)
            if len(ports) != 2:
                return HVACLossAPI._unsupported("expected exactly 2 connected ports, found {}".format(len(ports)))
            outlet = next((p for p in ports if p.get("flow_into_junction") is False), None)
            inlet = next((p for p in ports if p.get("flow_into_junction") is True), None)
            if outlet is None or inlet is None:
                return HVACLossAPI._unsupported("could not resolve inlet/outlet direction")

            area_out = HVACLibraryAPI.port_area(outlet)
            area_in = HVACLibraryAPI.port_area(inlet)
            if area_out <= 0.0 or area_in <= 0.0:
                return HVACLossAPI._unsupported("invalid inlet/outlet area")

            area_ratio = max(area_in, area_out) / min(area_in, area_out)
            if area_ratio <= 1.05:
                # Essentially the same size on both sides: the tables start at
                # an area ratio of 2:1 and don't cover this, so the loss is
                # taken as negligible rather than clamped to their first row.
                return HVACLossAPI._exact(
                    [HVACLossAPI._leg_path(outlet, inlet["edge_key"], 0.0, source="smacna_transition")]
                )

            profile_in, profile_out = HVACLibraryAPI.port_profile(inlet), HVACLibraryAPI.port_profile(outlet)
            known = ("Circular", "Rectangular", "Oval")
            if profile_in not in known or profile_out not in known:
                return HVACLossAPI._unsupported(
                    "no transition table for profile '{}'".format(
                        profile_out if profile_out not in known else profile_in
                    )
                )
            notes = []
            if "Oval" in (profile_in, profile_out):
                notes.append("oval duct read as the rectangle of the same width and height")

            # Steps 1 and 2: body length and table angle, from the same helper
            # the geometry reports them with (fittings/transitions.py).
            dims = transition_fittings.transition_dimensions(
                HVACLibraryAPI, [inlet, outlet], context.get("properties") or {}
            )
            theta, single_plane = dims["included_angle"], dims["single_plane"]
            expanding = area_out > area_in
            small, large = (inlet, outlet) if expanding else (outlet, inlet)
            round_small = HVACLibraryAPI.port_profile(small) == "Circular"
            round_large = HVACLibraryAPI.port_profile(large) == "Circular"

            # Step 3: the table. Expansion tables are printed against the
            # smaller (upstream) duct's velocity; the loss is referenced to
            # the outlet, whose velocity is area_ratio times lower.
            if expanding:
                if round_small and round_large:
                    reynolds = float(inlet.get("reynolds", 0.0) or 0.0)
                    if reynolds <= 0.0:
                        return HVACLossAPI._unsupported("no Reynolds number available (zero flow?)")
                    lookup = transition_tables.expansion_round(theta, area_ratio, reynolds)
                    source = "smacna_transition_round"
                elif single_plane:
                    lookup = transition_tables.expansion_rect_sides_straight(theta, area_ratio)
                    source = "smacna_transition_sides_straight"
                else:
                    lookup = transition_tables.expansion_rect_pyramidal(theta, area_ratio)
                    source = "smacna_transition_pyramidal"
                lookup = loss_table.Lookup(lookup.value * area_ratio**2, lookup.clamped, lookup.filled)
            else:
                if round_small != round_large:
                    notes.append("contraction table is not printed for round to rectangular, 14-11 C/D angle used")
                lookup = transition_tables.contraction(theta, area_ratio)
                source = "smacna_contraction"
            return HVACLossAPI._from_lookup(outlet, inlet["edge_key"], lookup, source, notes)
        except Exception as exc:
            return HVACLossAPI._unsupported("unexpected error computing transition loss: {}".format(exc))

    @staticmethod
    def offset_loss(context):
        """
        Lateral-offset (jog) fitting loss: a same-size collinear pair whose
        axes are transversely displaced -- the "through.offset" case (see
        TOPOLOGY_CLASSIFICATION.md), as opposed to transition_loss's area
        change. Expects exactly 2 connected_ports and the offset body's own
        axial length in properties: "OffsetLength" (an offset type) or
        "TransitionLength" (a transition-style type used for an offset).

        Modelled as two corner deflections in series, each at the fitting's
        own turn angle (HVACLibraryAPI.offset_transition_axis), using
        SMACNA's generic-angle mitered-elbow tables (A7C/A7D) -- unlike the
        90-deg-only smooth-radius tables (elbow_zeta_round/rect), these are
        indexed by angle directly, which an offset's shallow corners need.
        An "OffsetRadius"/"TransitionRadius" entry in properties (the
        radiussed style) still borrows the mitered coefficient, since SMACNA has no
        generic-angle smooth-radius table -- that case comes back as
        APPROXIMATION rather than EXACT.
        """
        try:
            ports = HVACLibraryAPI.connected_ports(context)
            if len(ports) != 2:
                return HVACLossAPI._unsupported("expected exactly 2 connected ports, found {}".format(len(ports)))
            outlet = next((p for p in ports if p.get("flow_into_junction") is False), None)
            if outlet is None:
                return HVACLossAPI._unsupported("could not resolve outlet direction")
            inlet = next((p for p in ports if p is not outlet), None)

            properties = context.get("properties") or {}
            # An offset type names its length OffsetLength; a transition-style
            # type used for an offset (the generic through fitting) names it
            # TransitionLength. Same helper as the geometry's derived values.
            length_value = properties.get("OffsetLength", properties.get("TransitionLength", 0.0))
            dims = transition_fittings.offset_dimensions(
                HVACLibraryAPI, list(ports), {"TransitionLength": length_value}
            )
            theta_deg = dims["offset_angle"]
            if theta_deg <= 1e-6:
                return HVACLossAPI._exact(
                    [HVACLossAPI._leg_path(outlet, inlet["edge_key"], 0.0, source="smacna_offset")]
                )

            profile = HVACLibraryAPI.port_profile(outlet)
            if profile == "Circular":
                corner_zeta = elbow_tables.MITERED_ROUND(theta_deg)
            elif profile == "Rectangular":
                width = HVACLibraryAPI.port_width(outlet)
                height = HVACLibraryAPI.port_height(outlet)
                if width <= 0.0 or height <= 0.0:
                    return HVACLossAPI._unsupported("invalid width/height")
                corner_zeta = elbow_tables.MITERED_RECT(theta_deg, height / width)
            else:
                return HVACLossAPI._unsupported("no offset table for profile '{}'".format(profile))

            path = HVACLossAPI._leg_path(outlet, inlet["edge_key"], 2.0 * corner_zeta, source="smacna_offset")
            if "OffsetRadius" in properties or "TransitionRadius" in properties:
                return HVACLossAPI._approximation(
                    [path],
                    warning=(
                        "radiused-corner offset loss approximated via SMACNA A7C/A7D "
                        "mitered-elbow coefficients; SMACNA has no generic-angle "
                        "smooth-radius elbow table"
                    ),
                )
            return HVACLossAPI._exact([path])
        except Exception as exc:
            return HVACLossAPI._unsupported("unexpected error computing offset loss: {}".format(exc))

    @staticmethod
    def _leg_angle_deg(leg_dir, reference_dir):
        """
        Angle (degrees) a leg makes against a reference leg, given both as
        outward-pointing direction vectors (each pointing away from the
        junction along its own duct, e.g. HVACLibraryAPI.vec(port["direction"])).
        Two outward-pointing vectors that are anti-parallel represent duct
        legs that are physically in line with each other (0 deg apart, not
        180), so this is 180 minus the raw angle between the vectors.
        Shared by every branch-angle lookup in this module (branch_loss,
        _no_straight_leg_branch_zetas, manifold_loss) instead of
        reimplementing the same clamp/acos/180-minus pattern in each.
        """
        cos_angle = max(-1.0, min(1.0, leg_dir.dot(reference_dir)))
        return 180.0 - math.degrees(math.acos(cos_angle))

    @staticmethod
    def _split_single_common_port(ports):
        """
        Split `ports` into (primary, secondaries, diverging) where exactly
        one port sits on one flow side (the sole inlet if diverging, the
        sole outlet if converging) and the rest sit on the other side --
        the single-trunk shape shared by branch_loss, branch_loss_bullhead,
        wye_loss, and manifold_loss. Returns None when that's not the flow
        pattern (e.g. a mixed multi-inlet/multi-outlet "true cross" has no
        single trunk to decompose against).
        """
        inlets = [p for p in ports if p.get("flow_into_junction") is True]
        outlets = [p for p in ports if p.get("flow_into_junction") is False]

        if len(inlets) == 1 and outlets:
            return inlets[0], outlets, True
        if len(outlets) == 1 and inlets:
            return outlets[0], inlets, False
        return None

    @staticmethod
    def branch_loss(context):
        """
        Converging (merging) or diverging (splitting) tee/wye fitting loss.
        Expects exactly 3 connected_ports: one "common"/trunk port (the sole
        inlet if diverging, the sole outlet if converging) and two "secondary"
        ports (branch + straight-through), identified by which secondary
        port's direction is closest to anti-parallel with the common port's
        direction (the straight-through continuation of the duct run).

        properties["BranchStyle"] picks how the branch is joined (see
        _tee_zetas for the table each reads): "straight" (default),
        "conical", "45_entry", "damper", "45_entry_damper", "extractor".

        Returns two LossPaths (branch, straight), each referenced to that
        leg's own velocity: EXACT when every lookup was inside a printed
        table made for this fitting, APPROXIMATION (with the reason) when
        not, UNSUPPORTED for an ambiguous/degenerate flow pattern or
        invalid geometry.
        """
        try:
            ports = HVACLibraryAPI.connected_ports(context)
            if len(ports) != 3:
                return HVACLossAPI._unsupported("expected exactly 3 connected ports, found {}".format(len(ports)))

            split = HVACLossAPI._split_single_common_port(ports)
            if split is None:
                return HVACLossAPI._unsupported("ambiguous/degenerate flow pattern (no single common port)")
            primary, secondaries, diverging = split

            primary_dir = HVACLibraryAPI.vec(primary["direction"])
            sec_a, sec_b = secondaries
            dot_a = primary_dir.dot(HVACLibraryAPI.vec(sec_a["direction"]))
            dot_b = primary_dir.dot(HVACLibraryAPI.vec(sec_b["direction"]))
            # Both port directions point away from the junction, so the leg
            # that continues straight through sits opposite the primary leg
            # (most negative dot product); the other secondary is the branch.
            straight, branch = (sec_a, sec_b) if dot_a < dot_b else (sec_b, sec_a)

            v_common = float(primary.get("velocity_ms", 0.0) or 0.0)
            if v_common <= 1e-9:
                return HVACLossAPI._exact(
                    [
                        HVACLossAPI._leg_path(branch, primary["edge_key"], 0.0, source="smacna_branch"),
                        HVACLossAPI._leg_path(straight, primary["edge_key"], 0.0, source="smacna_branch"),
                    ]
                )

            a_common = HVACLibraryAPI.port_area(primary)
            a_branch = HVACLibraryAPI.port_area(branch)
            if a_common <= 0.0 or a_branch <= 0.0:
                return HVACLossAPI._unsupported("invalid common/branch area")

            # The tables' branch angle is between the branch and the main
            # flow, i.e. how far the branch leg is from lining up with the
            # common leg (0 = straight on, 90 = square). Measuring it from the
            # straight leg instead would give 180 minus that angle.
            branch_dir = HVACLibraryAPI.vec(branch["direction"])
            angle_deg = HVACLossAPI._leg_angle_deg(branch_dir, primary_dir)

            ab_on_ac = a_branch / a_common
            vb_on_vc = float(branch.get("velocity_ms", 0.0) or 0.0) / v_common
            vs_on_vc = float(straight.get("velocity_ms", 0.0) or 0.0) / v_common

            # A branch that passes over or under the run is face-mounted: it
            # leaves through a collar and a 90 deg elbow, which has its own loss.
            if HVACLossAPI._branch_is_face_mounted(context, primary, straight, branch):
                return HVACLossAPI._face_mounted_branch_loss(
                    context, primary, straight, branch, diverging, angle_deg, ab_on_ac, vb_on_vc, vs_on_vc
                )

            zeta_branch, zeta_straight, source, reasons = HVACLossAPI._tee_zetas(
                context, primary, straight, branch, diverging, angle_deg, ab_on_ac, vb_on_vc, vs_on_vc
            )
            paths = [
                HVACLossAPI._leg_path(branch, primary["edge_key"], zeta_branch, source=source),
                HVACLossAPI._leg_path(straight, primary["edge_key"], zeta_straight, source=source),
            ]
            if reasons:
                return HVACLossAPI._approximation(paths, "{}: {}".format(source, "; ".join(reasons)))
            return HVACLossAPI._exact(paths)
        except Exception as exc:
            return HVACLossAPI._unsupported("unexpected error computing branch loss: {}".format(exc))

    # Tee kinds by BranchStyle: (diverging table key, converging table key);
    # None where SMACNA has no table for that style and direction.
    _RECT_TEE_KINDS = {
        "straight": ("rect_branch", "rect_branch"),
        "45_entry": ("rect_branch_45_entry", "rect_branch_45_entry"),
        "damper": ("rect_branch_damper", None),
        "45_entry_damper": ("rect_branch_45_entry_damper", None),
        "extractor": ("rect_branch_extractor", None),
    }

    @staticmethod
    def _tee_zetas(context, common, straight, branch, diverging, angle_deg, ab_on_ac, vb_on_vc, vs_on_vc):
        """
        (zeta_branch, zeta_straight, source, reasons) for an ordinary tee,
        each zeta referenced to its own leg's velocity. `reasons` lists why
        the result is only an approximation (empty when it is exact).

        Which table is read:

        - A rectangular run of constant size (As = Ac) with a branch about
          square to it uses the rectangular-main tables: diverging 14-14 Q
          (rectangular branch) / T (round branch) / N, P, R, S (the
          BranchStyle variants) / V (conical branch); converging 14-13 D /
          C / F, which are printed for one set of proportions only
          (Ab/As 0.5, As/Ac 1.0, Ab/Ac 0.5).
        - Everything else uses the round tables: diverging 14-14 A (B or C
          for a conical branch), converging 14-13 A (45 deg) or B (90 deg).
          For a duct that is not round, that is an approximation.

        Both 14-13 and 14-14 are printed against the common duct's velocity
        (upstream for diverging, downstream for converging; the common duct
        either way), so the conversion to each leg's own velocity is the same.
        """
        properties = context.get("properties") or {}
        style = HVACLossAPI._choice(properties.get("BranchStyle"), "straight")
        reasons = []
        profiles = {HVACLibraryAPI.port_profile(p) for p in (common, straight, branch)}
        main_rect = all(HVACLibraryAPI.port_profile(p) == "Rectangular" for p in (common, straight))
        branch_round = HVACLibraryAPI.port_profile(branch) == "Circular"
        qb_on_qc = vb_on_vc * ab_on_ac

        def own(lookup, v_on_vc):
            value = lookup.value
            return value / (v_on_vc**2) if v_on_vc > 0 else value

        def flags(*lookups):
            if any(lookup.clamped for lookup in lookups):
                reasons.append("outside the printed range of the table")
            if any(lookup.filled for lookup in lookups):
                reasons.append("in a cell the table leaves blank")

        a_common, a_straight = HVACLibraryAPI.port_area(common), HVACLibraryAPI.port_area(straight)
        constant_run = a_common > 0.0 and abs(a_straight - a_common) <= 0.05 * a_common
        square = abs(angle_deg - 90.0) <= 10.0

        # Step 1: a rectangular main with a square branch -> the rectangular-main tables.
        if main_rect and square:
            if diverging and constant_run:
                if style == "conical":
                    branch_l, main_l = diverging_tables.tee_rect_main_conical_branch(vb_on_vc, vs_on_vc)
                    source = "smacna_tee_rect_conical"
                else:
                    if style not in HVACLossAPI._RECT_TEE_KINDS:
                        raise ValueError("unknown BranchStyle '{}'".format(style))
                    kind = HVACLossAPI._RECT_TEE_KINDS[style][0]
                    if branch_round:
                        if style == "straight":
                            kind = "round_branch"
                        else:
                            reasons.append("the {} table is printed for a rectangular branch".format(style))
                    branch_l, main_l = diverging_tables.tee_rect_main(kind, vb_on_vc, qb_on_qc, vs_on_vc)
                    source = "smacna_tee_rect_" + kind
                flags(branch_l, main_l)
                return own(branch_l, vb_on_vc), own(main_l, vs_on_vc), source, reasons
            if not diverging and style != "conical":
                if style not in HVACLossAPI._RECT_TEE_KINDS:
                    raise ValueError("unknown BranchStyle '{}'".format(style))
                kind = HVACLossAPI._RECT_TEE_KINDS[style][1]
                if kind is None:
                    reasons.append("no converging table for a {} branch, plain one used".format(style))
                    kind = "rect_branch"
                if branch_round:
                    kind = "round_branch" if kind == "rect_branch" else kind
                ab_on_as = HVACLibraryAPI.port_area(branch) / a_straight if a_straight > 0.0 else 0.0
                as_on_ac = a_straight / a_common if a_common > 0.0 else 0.0
                printed = converging_tables.RECT_TEE_AREA_RATIOS
                if all(abs(got - want) <= 0.1 * want for got, want in zip((ab_on_as, as_on_ac, ab_on_ac), printed)):
                    vc_ms = float(common.get("velocity_ms", 0.0) or 0.0)
                    branch_l, main_l = converging_tables.tee_rect_main(kind, qb_on_qc, vc_ms)
                    flags(branch_l, main_l)
                    return own(branch_l, vb_on_vc), own(main_l, vs_on_vc), "smacna_tee_rect_" + kind, reasons
                reasons.append("rectangular converging tee tables are printed for Ab/As 0.5, As/Ac 1.0, Ab/Ac 0.5 only")
            elif diverging:
                reasons.append("rectangular tee tables assume the run keeps its size")

        # Step 2: the round tables.
        if profiles != {"Circular"}:
            reasons.append("round tee tables used for a {} tee".format("/".join(sorted(profiles))))
        if diverging:
            if style == "conical":
                variant = "conical_wye_45" if angle_deg <= 67.5 else "conical_tee_90"
                branch_l, main_l = diverging_tables.round_variant(variant, vb_on_vc, vs_on_vc)
                source = "smacna_tee_" + variant
            else:
                if style not in ("straight",):
                    if style not in HVACLossAPI._RECT_TEE_KINDS:
                        raise ValueError("unknown BranchStyle '{}'".format(style))
                    reasons.append("no round table for a {} branch, plain one used".format(style))
                branch_l, main_l = diverging_tables.round_tee_or_wye(angle_deg, ab_on_ac, qb_on_qc, vs_on_vc)
                source = "smacna_branch_diverging"
        else:
            if style != "straight":
                if style != "conical" and style not in HVACLossAPI._RECT_TEE_KINDS:
                    raise ValueError("unknown BranchStyle '{}'".format(style))
                reasons.append("no converging table for a {} branch, plain one used".format(style))
            if angle_deg <= 67.5:
                branch_l, main_l = converging_tables.wye_45_round(ab_on_ac, vb_on_vc, vs_on_vc)
                if abs(angle_deg - 45.0) > 10.0:
                    reasons.append("converging tables are printed for 45 and 90 degrees only")
            else:
                branch_l, main_l = converging_tables.tee_90_round(ab_on_ac, qb_on_qc)
                if abs(angle_deg - 90.0) > 10.0:
                    reasons.append("converging tables are printed for 45 and 90 degrees only")
            source = "smacna_branch_converging"
        flags(branch_l, main_l)
        return own(branch_l, vb_on_vc), own(main_l, vs_on_vc), source, reasons

    @staticmethod
    def _port_half_extent_mm(port, direction):
        """
        Half the size of a port's section measured along `direction` (a unit
        vector across the duct). Exact for round and rectangular sections;
        an oval is measured as the rectangle around it.
        """
        if HVACLibraryAPI.port_profile(port) == "Circular":
            return float(HVACLibraryAPI.port_diameter(port)) / 2.0
        width, height = float(HVACLibraryAPI.port_width(port)), float(HVACLibraryAPI.port_height(port))
        axis = HVACLibraryAPI.unit(HVACLibraryAPI.port_direction(port))
        # The section's own x axis: the port's stored one, or the same
        # default rule make_profile_frame() uses when there is none.
        preferred = HVACLibraryAPI.port_profile_x_axis(port)
        x_axis = None
        if preferred is not None:
            candidate = HVACLibraryAPI.vec(preferred)
            candidate = candidate - axis * candidate.dot(axis)
            if candidate.Length > HVACLibraryAPI.EPS:
                x_axis = HVACLibraryAPI.unit(candidate)
        if x_axis is None:
            reference = HVACLibraryAPI.vec((0, 0, 1))
            if abs(axis.dot(reference)) > 0.99:
                reference = HVACLibraryAPI.vec((1, 0, 0))
            x_axis = HVACLibraryAPI.unit(reference.cross(axis))
        y_axis = HVACLibraryAPI.unit(axis.cross(x_axis))
        return abs(direction.dot(x_axis)) * width / 2.0 + abs(direction.dot(y_axis)) * height / 2.0

    @staticmethod
    def _branch_is_face_mounted(context, common, straight, branch):
        """
        Whether a tee's branch is face-mounted (passes over or under the
        run) rather than a side tap: the same decision the geometry makes
        (fittings/taps.attachment_mode), from the type's own Attachment
        property and how far the branch axis is from the run axis. Always
        False for a type with no Attachment property.
        """
        properties = context.get("properties") or {}
        if "Attachment" not in properties:
            return False
        try:
            run_dir = HVACLibraryAPI.unit(HVACLibraryAPI.port_direction(common))
            branch_dir = HVACLibraryAPI.unit(HVACLibraryAPI.port_direction(branch))
            q_run, q_branch = HVACLibraryAPI.closest_points_on_lines(
                HVACLibraryAPI.port_position(common), run_dir, HVACLibraryAPI.port_position(branch), branch_dir
            )
            offsets = None
            if q_run is not None and (q_branch - q_run).Length > 1.0e-6:
                up = HVACLibraryAPI.unit(q_branch - q_run)
                offsets = {
                    "offset": (q_branch - q_run).Length,
                    "run_half": max(
                        HVACLossAPI._port_half_extent_mm(common, up), HVACLossAPI._port_half_extent_mm(straight, up)
                    ),
                    "branch_half": HVACLossAPI._port_half_extent_mm(branch, up),
                }
            return tap_fittings.attachment_mode(str(properties.get("Attachment") or ""), offsets) == "Face"
        except Exception:
            # Geometry the fitting itself would refuse to build: leave it to the plain tee loss.
            return False

    # A face-mounted branch within this many degrees of square reads the 90 degree tee-with-elbow table.
    _SQUARE_BRANCH_TOLERANCE_DEG = 5.0

    @staticmethod
    def _face_mounted_branch_loss(
        context, common, straight, branch, diverging, angle_deg, ab_on_ac, vb_on_vc, vs_on_vc
    ):
        """
        Loss of a tee whose branch is face-mounted (collar plus 90 deg elbow).

        A round diverging tee with a square branch has its own table for
        exactly this fitting (SMACNA 14-14 E, "90 deg tee, round, with 90 deg
        elbow"). Every other case has none -- including a face-mounted
        lateral, whose elbow turns into an inclined branch -- so the plain
        tee loss at the branch's angle is used with the loss of the branch
        elbow added to the branch leg, as an approximation.
        """
        source = "smacna_branch_face_mounted"
        round_ducts = all(HVACLibraryAPI.port_profile(p) == "Circular" for p in (common, straight, branch))
        square_branch = abs(angle_deg - 90.0) <= HVACLossAPI._SQUARE_BRANCH_TOLERANCE_DEG

        if diverging and round_ducts and square_branch:
            lookup_branch, lookup_main = diverging_tables.round_variant("tee_90_elbow_90", vb_on_vc, vs_on_vc)
            # Both are printed against the common duct's velocity; each path is referenced to its own leg's.
            zeta_branch = lookup_branch.value / (vb_on_vc**2) if vb_on_vc > 0 else lookup_branch.value
            zeta_straight = lookup_main.value / (vs_on_vc**2) if vs_on_vc > 0 else lookup_main.value
            paths = [
                HVACLossAPI._leg_path(branch, common["edge_key"], zeta_branch, source=source),
                HVACLossAPI._leg_path(straight, common["edge_key"], zeta_straight, source=source),
            ]
            reasons = []
            if not (lookup_branch.exact and lookup_main.exact):
                reasons.append("outside the printed range of the table")
            # The table is printed for a run of constant size (Ac = As).
            a_common, a_straight = HVACLibraryAPI.port_area(common), HVACLibraryAPI.port_area(straight)
            if a_common > 0.0 and abs(a_straight - a_common) > 0.02 * a_common:
                reasons.append("the table assumes the run keeps its size through the tee")
            if reasons:
                return HVACLossAPI._approximation(paths, "{}: {}".format(source, "; ".join(reasons)))
            return HVACLossAPI._exact(paths)

        # No table: plain tee, plus the branch elbow at the branch's own velocity.
        zeta_branch, zeta_straight, _source, _reasons = HVACLossAPI._tee_zetas(
            context, common, straight, branch, diverging, angle_deg, ab_on_ac, vb_on_vc, vs_on_vc
        )
        properties = context.get("properties") or {}
        if HVACLibraryAPI.port_profile(branch) == "Circular":
            size = float(HVACLibraryAPI.port_diameter(branch))
            radius = max(float(properties.get("ElbowRadius", 0.0) or 0.0) or size, 0.5 * size)
            zeta_elbow = elbow_tables.SMOOTH_ROUND(radius / size)
        else:
            width, height = float(HVACLibraryAPI.port_width(branch)), float(HVACLibraryAPI.port_height(branch))
            size = max(width, height)
            radius = max(float(properties.get("ElbowRadius", 0.0) or 0.0) or size, 0.5 * size)
            # With no Reynolds number for the branch, skip the correction (it is 1.0 from Re = 2e5 up).
            reynolds = float(branch.get("reynolds", 0.0) or 0.0) or 1.0e6
            zeta_elbow = elbow_tables.smooth_rect(height / width, radius / width, reynolds).value
        paths = [
            HVACLossAPI._leg_path(branch, common["edge_key"], zeta_branch + zeta_elbow, source=source),
            HVACLossAPI._leg_path(straight, common["edge_key"], zeta_straight, source=source),
        ]
        return HVACLossAPI._approximation(
            paths, "{}: no table for this face-mounted branch; plain tee loss plus the branch elbow".format(source)
        )

    @staticmethod
    def _round_branch_zetas(diverging, angle_deg, ab_on_ac, vb_on_vc, vs_on_vc):
        """
        (zeta_branch, zeta_straight) from the round branch tables, each
        referenced to that leg's OWN velocity: diverging 14-14 A (30 to 90
        deg, interpolated), converging 14-13 A (45 deg wye) up to 67.5 deg
        and 14-13 B (90 deg tee) above. The angle is the branch's, measured
        from the common leg (0 = in line, 90 = square).

        The 90 deg converging tee and every diverging branch table are keyed
        by the branch flow ratio Qb/Qc = (Vb/Vc) * (Ab/Ac); the 45 deg
        converging wye by the velocity ratio. Used where a fitting is broken
        down into tee-like steps (a manifold, a leg with no straight-through
        partner); branch_loss itself goes through _tee_zetas.
        """
        qb_on_qc = vb_on_vc * ab_on_ac
        if diverging:
            branch, main = diverging_tables.round_tee_or_wye(angle_deg, ab_on_ac, qb_on_qc, vs_on_vc)
        elif angle_deg <= 67.5:
            branch, main = converging_tables.wye_45_round(ab_on_ac, vb_on_vc, vs_on_vc)
        else:
            branch, main = converging_tables.tee_90_round(ab_on_ac, qb_on_qc)
        zeta_branch = branch.value / (vb_on_vc**2) if vb_on_vc > 0 else branch.value
        zeta_straight = main.value / (vs_on_vc**2) if vs_on_vc > 0 else main.value
        return zeta_branch, zeta_straight

    @staticmethod
    def _round_branch_zetas_fn(diverging):
        """_round_branch_zetas with the direction fixed: f(angle, ab_on_ac, vb_on_vc, vs_on_vc)."""

        def zetas(angle_deg, ab_on_ac, vb_on_vc, vs_on_vc):
            return HVACLossAPI._round_branch_zetas(diverging, angle_deg, ab_on_ac, vb_on_vc, vs_on_vc)

        return zetas

    @staticmethod
    def _no_straight_leg_branch_zetas(common, legs, diverging):
        """
        Shared math for a 3-port branch fitting where no leg can be
        singled out as "the straight-through continuation" of the common
        leg -- used by both a bullhead tee/wye (branch_loss_bullhead) and
        a true Wye (wye_loss). These are geometrically different fittings
        (a bullhead is a Tee whose common flow sits on the branch leg; a
        true Wye has no run/branch split at all -- see NetworkParser's
        qualifiers["common_leg"], never assigned to a Wye), but they share
        the exact same "every non-common leg is independently a branch
        relative to the common leg" shape, so the underlying calculation
        lives here once rather than duplicated.

        No SMACNA table treats this shape as its own entry (neither leg
        gets the "straight-through continuation" the ordinary branch
        table's branch/straight split assumes), so each leg is evaluated
        independently against the common leg with the same diverging/
        converging branch-zeta tables an ordinary tee's own branch leg
        uses, reusing each leg's own velocity ratio for both table
        arguments -- a reasonable estimate, not a validated table value.

        Returns [LossPath, ...] (one per leg, each already referenced to
        that leg's own velocity and to `common`'s own edge_key), or None
        if the geometry is invalid (caller turns that into UNSUPPORTED).
        """
        v_common = float(common.get("velocity_ms", 0.0) or 0.0)
        if v_common <= 1e-9:
            return [HVACLossAPI._leg_path(leg, common["edge_key"], 0.0) for leg in legs]

        a_common = HVACLibraryAPI.port_area(common)
        if a_common <= 0.0:
            return None

        common_dir = HVACLibraryAPI.vec(common["direction"])
        zeta_fn = HVACLossAPI._round_branch_zetas_fn(diverging)

        paths = []
        for leg in legs:
            a_leg = HVACLibraryAPI.port_area(leg)
            if a_leg <= 0.0:
                return None

            leg_dir = HVACLibraryAPI.vec(leg["direction"])
            angle_deg = HVACLossAPI._leg_angle_deg(leg_dir, common_dir)

            a_on_ac = a_leg / a_common
            v_on_vc = float(leg.get("velocity_ms", 0.0) or 0.0) / v_common
            # No independent "straight-through" leg exists here, so the
            # reference velocity ratio the table otherwise expects for it
            # is undefined -- reuse this leg's own ratio for both table
            # arguments.
            zeta_leg, _ = zeta_fn(angle_deg, a_on_ac, v_on_vc, v_on_vc)
            paths.append(HVACLossAPI._leg_path(leg, common["edge_key"], zeta_leg))

        return paths

    @staticmethod
    def branch_loss_bullhead(context):
        """
        Bullhead tee/wye: the single common-flow port sits on the
        geometric *branch* leg instead of the run (see NetworkParser's
        qualifiers["common_leg"] == "branch" -- library JSON loss.variants
        route here for exactly that case, distinct from the ordinary
        common_leg == "run" case branch_loss() above already handles
        correctly). Expects exactly 3 connected_ports.

        This is a generic APPROXIMATION (see _no_straight_leg_branch_zetas),
        not a validated SMACNA table entry for a bullhead arrangement --
        never presented to a caller as an EXACT table result.

        Returns one LossPath per run leg, each already referenced to that
        leg's own velocity, or UNSUPPORTED for an ambiguous/degenerate flow
        pattern or invalid geometry.
        """
        try:
            ports = HVACLibraryAPI.connected_ports(context)
            if len(ports) != 3:
                return HVACLossAPI._unsupported("expected exactly 3 connected ports, found {}".format(len(ports)))

            split = HVACLossAPI._split_single_common_port(ports)
            if split is None:
                return HVACLossAPI._unsupported("ambiguous/degenerate flow pattern (no single common port)")
            common, run_legs, diverging = split

            paths = HVACLossAPI._no_straight_leg_branch_zetas(common, run_legs, diverging)
            if paths is None:
                return HVACLossAPI._unsupported("invalid port geometry (zero/invalid duct area)")
            return HVACLossAPI._approximation(paths)
        except Exception as exc:
            return HVACLossAPI._unsupported("unexpected error computing bullhead branch loss: {}".format(exc))

    @staticmethod
    def wye_loss(context):
        """
        True Wye (branch.wye) fitting loss: three ports where no pair is a
        Tee-style collinear run -- NetworkParser never assigns a
        qualifiers["common_leg"] to a Wye, since there's no run/branch
        split to name (see TOPOLOGY_CLASSIFICATION.md). This is therefore
        a distinct API entry point from branch_loss()/branch_loss_bullhead()
        rather than routing a Wye through either of those Tee-oriented
        methods -- it never guesses a "straight-through" secondary leg,
        since a true Wye has none by definition.

        Internally this reuses the same "no independent straight leg"
        calculation a bullhead tee/wye needs (see
        _no_straight_leg_branch_zetas): each non-common leg is evaluated
        independently against the common leg with the diverging/converging
        branch-zeta tables. A symmetric wye (equal legs at equal angles
        whose areas add up to the common duct's) reads its own tables
        instead (see _symmetric_wye_loss); anything else is a reasonable
        engineering APPROXIMATION, never presented as an EXACT table value.

        Expects exactly 3 connected_ports. Returns one LossPath per leg,
        each already referenced to that leg's own velocity, or UNSUPPORTED
        for an ambiguous/degenerate flow pattern or invalid geometry.
        """
        try:
            ports = HVACLibraryAPI.connected_ports(context)
            if len(ports) != 3:
                return HVACLossAPI._unsupported("expected exactly 3 connected ports, found {}".format(len(ports)))

            split = HVACLossAPI._split_single_common_port(ports)
            if split is None:
                return HVACLossAPI._unsupported("ambiguous/degenerate flow pattern (no single common port)")
            common, legs, diverging = split

            symmetric = HVACLossAPI._symmetric_wye_loss(common, legs, diverging)
            if symmetric is not None:
                return symmetric

            paths = HVACLossAPI._no_straight_leg_branch_zetas(common, legs, diverging)
            if paths is None:
                return HVACLossAPI._unsupported("invalid port geometry (zero/invalid duct area)")
            return HVACLossAPI._approximation(paths)
        except Exception as exc:
            return HVACLossAPI._unsupported("unexpected error computing wye loss: {}".format(exc))

    @staticmethod
    def _symmetric_wye_loss(common, legs, diverging):
        """
        The table result for a symmetric wye, or None when this wye is not one.

        SMACNA prints one fitting for two equal branches at equal angles
        whose areas add up to the common duct's (A1b = A2b, Ac = A1b + A2b):
        14-14 Y diverging (keyed by each branch's velocity ratio) and
        14-13 I converging (keyed by each branch's share of the flow). Both
        are printed against the common duct's velocity. A wye within 5 % of
        those proportions and 5 degrees of symmetry reads them.
        """
        a_common = HVACLibraryAPI.port_area(common)
        areas = [HVACLibraryAPI.port_area(leg) for leg in legs]
        if a_common <= 0.0 or min(areas) <= 0.0:
            return None
        common_dir = HVACLibraryAPI.vec(common["direction"])
        angles = [HVACLossAPI._leg_angle_deg(HVACLibraryAPI.vec(leg["direction"]), common_dir) for leg in legs]
        equal_legs = abs(areas[0] - areas[1]) <= 0.05 * max(areas)
        adds_up = abs(sum(areas) - a_common) <= 0.05 * a_common
        if not (equal_legs and adds_up and abs(angles[0] - angles[1]) <= 5.0):
            return None

        v_common = float(common.get("velocity_ms", 0.0) or 0.0)
        source = "smacna_wye_symmetric"
        if v_common <= 1e-9:
            return HVACLossAPI._exact(
                [HVACLossAPI._leg_path(leg, common["edge_key"], 0.0, source=source) for leg in legs]
            )

        paths, lookups = [], []
        for leg, area, angle in zip(legs, areas, angles):
            v_on_vc = float(leg.get("velocity_ms", 0.0) or 0.0) / v_common
            if diverging:
                lookup = diverging_tables.wye_symmetric(angle, v_on_vc)
            else:
                # This branch's share of the flow: Q = V * A.
                lookup = converging_tables.wye_symmetric(angle, v_on_vc * area / a_common)
            lookups.append(lookup)
            zeta = lookup.value / (v_on_vc**2) if v_on_vc > 0 else lookup.value
            paths.append(HVACLossAPI._leg_path(leg, common["edge_key"], zeta, source=source))

        reasons = []
        if any(lookup.clamped for lookup in lookups):
            reasons.append("outside the printed range of the table")
        if any(lookup.filled for lookup in lookups):
            reasons.append("in a cell the table leaves blank")
        if reasons:
            return HVACLossAPI._approximation(paths, "{}: {}".format(source, "; ".join(reasons)))
        return HVACLossAPI._exact(paths)

    @staticmethod
    def manifold_loss(context):
        """
        Cross (4-port) or multiport (5+ port) fitting loss, for the common
        single-trunk case: exactly one port on one flow side (all inlet, or
        all outlet) and the rest ("secondaries") on the other side.

        No dedicated SMACNA/ASHRAE table exists for 4+ port fittings, so this
        decomposes the junction into a sequence of pairwise branch (tee/wye)
        calculations, reusing the exact same diverging_branch_zetas /
        converging_branch_zetas tables as branch_loss: secondaries are
        peeled off one at a time, least-straight (most branch-like) first,
        straightest last -- mirroring how a real header/manifold is
        typically laid out (larger/sharper takeoffs nearer the main
        connection, the straightest path continuing furthest). Each pairwise
        step is referenced against the PRIMARY port's own duct size and
        direction (and, for the branch-angle lookup, the straightest
        secondary's direction) as a stand-in for the intermediate duct
        geometry this addon doesn't actually model between successive
        virtual merges/splits -- an APPROXIMATION, not a literal per-leg
        geometry readout. With exactly 2 secondaries this reduces to
        exactly the same numbers as branch_loss's 3-port calculation.

        Returns one LossPath per secondary port (each already referenced to
        that leg's own velocity and to the primary port's own edge_key), or
        UNSUPPORTED for a mixed multi-inlet/multi-outlet ("true cross") flow
        pattern -- which has no single trunk to decompose against -- or on
        any missing/invalid geometry.
        """
        try:
            ports = HVACLibraryAPI.connected_ports(context)
            if len(ports) < 3:
                return HVACLossAPI._unsupported("expected at least 3 connected ports, found {}".format(len(ports)))

            split = HVACLossAPI._split_single_common_port(ports)
            if split is None:
                return HVACLossAPI._unsupported(
                    "mixed multi-inlet/multi-outlet flow arrangement has no single trunk to decompose"
                )
            primary, secondaries, diverging = split

            if len(secondaries) < 2:
                return HVACLossAPI._unsupported("expected at least 2 secondary ports")

            a_ref = HVACLibraryAPI.port_area(primary)
            v_primary = float(primary.get("velocity_ms", 0.0) or 0.0)
            if a_ref <= 0.0:
                return HVACLossAPI._unsupported("invalid primary port area")
            port_by_edge = {p["edge_key"]: p for p in secondaries}
            if v_primary <= 1e-9:
                paths = [
                    HVACLossAPI._leg_path(p, primary["edge_key"], 0.0, source="smacna_manifold") for p in secondaries
                ]
                return HVACLossAPI._approximation(paths)
            for p in secondaries:
                if HVACLibraryAPI.port_area(p) <= 0.0:
                    return HVACLossAPI._unsupported("invalid secondary port area")

            primary_dir = HVACLibraryAPI.vec(primary["direction"])
            # Least-straight (most branch-like) first, straightest (closest
            # continuation of the primary direction) last -- same selection
            # rule as branch_loss, generalized to N-1 secondaries.
            ordered = sorted(
                secondaries, key=lambda p: primary_dir.dot(HVACLibraryAPI.vec(p["direction"])), reverse=True
            )
            # Every branch angle is measured from the primary (common) leg,
            # as in branch_loss: 0 = in line with it, 90 = square to it.

            zeta_fn = HVACLossAPI._round_branch_zetas_fn(diverging)
            result = {}
            m = len(ordered)

            def _angle_deg(branch_port):
                branch_dir = HVACLibraryAPI.vec(branch_port["direction"])
                return HVACLossAPI._leg_angle_deg(branch_dir, primary_dir)

            if diverging:
                remaining_flow_lps = float(primary.get("flow_rate_lps", 0.0) or 0.0)
                for i in range(m - 1):
                    branch = ordered[i]
                    is_penultimate = i == m - 2
                    branch_flow_lps = float(branch.get("flow_rate_lps", 0.0) or 0.0)
                    after_flow_lps = remaining_flow_lps - branch_flow_lps

                    v_common_step = airflow.velocity_from_flow(airflow.lps_to_m3s(remaining_flow_lps), a_ref)
                    if v_common_step <= 1e-9:
                        result[branch["edge_key"]] = 0.0
                        remaining_flow_lps = after_flow_lps
                        continue

                    if is_penultimate:
                        # What's left after this branch IS the last real
                        # secondary -- use its own real velocity.
                        v_after_step = float(ordered[-1].get("velocity_ms", 0.0) or 0.0)
                    else:
                        v_after_step = airflow.velocity_from_flow(airflow.lps_to_m3s(after_flow_lps), a_ref)

                    ab_on_ac = HVACLibraryAPI.port_area(branch) / a_ref
                    vb_on_vc = float(branch.get("velocity_ms", 0.0) or 0.0) / v_common_step
                    vs_on_vc = v_after_step / v_common_step

                    zeta_branch, zeta_after = zeta_fn(_angle_deg(branch), ab_on_ac, vb_on_vc, vs_on_vc)
                    result[branch["edge_key"]] = zeta_branch
                    if is_penultimate:
                        result[ordered[-1]["edge_key"]] = zeta_after

                    remaining_flow_lps = after_flow_lps
            else:
                # Mirror of the diverging loop: instead of a shrinking
                # "remaining trunk", the reference here is a growing
                # "accumulated so far" stream, seeded with the straightest
                # secondary's own real flow (it is the fixed "main" duct
                # that every other, less-straight secondary merges into,
                # one at a time) and ending at the primary's real flow once
                # the last (second-straightest) secondary has merged in.
                main = ordered[-1]
                v_main = float(main.get("velocity_ms", 0.0) or 0.0)
                accumulated_flow_lps = float(main.get("flow_rate_lps", 0.0) or 0.0)
                for i in range(m - 1):
                    branch = ordered[i]
                    is_last = i == m - 2
                    branch_flow_lps = float(branch.get("flow_rate_lps", 0.0) or 0.0)
                    accumulated_after_lps = accumulated_flow_lps + branch_flow_lps

                    if is_last:
                        # This merge produces the fully-combined stream -- use the primary's own real velocity.
                        v_common_step = v_primary
                    else:
                        v_common_step = airflow.velocity_from_flow(airflow.lps_to_m3s(accumulated_after_lps), a_ref)
                    if v_common_step <= 1e-9:
                        result[branch["edge_key"]] = 0.0
                        accumulated_flow_lps = accumulated_after_lps
                        continue

                    if i == 0:
                        # Nothing has merged into main yet -- use its own real velocity.
                        v_straight_side = v_main
                    else:
                        v_straight_side = airflow.velocity_from_flow(airflow.lps_to_m3s(accumulated_flow_lps), a_ref)

                    ab_on_ac = HVACLibraryAPI.port_area(branch) / a_ref
                    vb_on_vc = float(branch.get("velocity_ms", 0.0) or 0.0) / v_common_step
                    vs_on_vc = v_straight_side / v_common_step

                    zeta_branch, zeta_straight = zeta_fn(_angle_deg(branch), ab_on_ac, vb_on_vc, vs_on_vc)
                    result[branch["edge_key"]] = zeta_branch
                    if is_last:
                        result[main["edge_key"]] = zeta_straight

                    accumulated_flow_lps = accumulated_after_lps

            paths = [
                HVACLossAPI._leg_path(port_by_edge[edge_key], primary["edge_key"], k, source="smacna_manifold")
                for edge_key, k in result.items()
            ]
            return HVACLossAPI._approximation(paths)
        except Exception as exc:
            return HVACLossAPI._unsupported("unexpected error computing manifold loss: {}".format(exc))

    @staticmethod
    def terminal_component_loss(context):
        """
        Generic terminal air device (diffuser/grille/register) loss: a
        dimensionless coefficient K (from properties["LossCoefficient"]),
        referenced to velocity at the device's own neck
        (properties["NeckSize"]) rather than the connecting duct's own
        velocity -- the neck is often a different size than the duct feeding
        it. Converted to a K_effective referenced to the connecting duct's
        velocity (K_effective = K * (V_neck / V_duct)^2, since velocity
        pressure ~ V^2 at constant density) so it composes with the solver's
        existing K * velocity_pressure(duct) convention used for every other
        fitting -- no special-casing needed downstream.

        Expects exactly 1 connected port (a terminal). Returns one EXACT
        LossPath (the port's open-atmosphere side is None), or UNSUPPORTED
        if NeckSize/LossCoefficient aren't set (nothing to compute) or the
        port geometry is invalid.
        """
        try:
            ports = HVACLibraryAPI.connected_ports(context)
            if len(ports) != 1:
                return HVACLossAPI._unsupported("expected exactly 1 connected port, found {}".format(len(ports)))
            port = ports[0]

            properties = context.get("properties") or {}
            neck_size_mm = float(properties.get("NeckSize", 0.0) or 0.0)
            k = float(properties.get("LossCoefficient", 0.0) or 0.0)
            if neck_size_mm <= 0.0 or k <= 0.0:
                return HVACLossAPI._unsupported("NeckSize/LossCoefficient not set")

            duct_velocity = float(port.get("velocity_ms", 0.0) or 0.0)
            flow_lps = float(port.get("flow_rate_lps", 0.0) or 0.0)
            if flow_lps <= 0.0 or duct_velocity <= 1e-9:
                return HVACLossAPI._exact([HVACLossAPI._leg_path(port, None, 0.0, source="terminal_device")])

            neck_area_m2 = airflow.circular_area(airflow.mm_to_m(neck_size_mm))
            neck_velocity_ms = airflow.velocity_from_flow(airflow.lps_to_m3s(flow_lps), neck_area_m2)

            k_effective = k * (neck_velocity_ms / duct_velocity) ** 2
            return HVACLossAPI._exact([HVACLossAPI._leg_path(port, None, k_effective, source="terminal_device")])
        except Exception as exc:
            return HVACLossAPI._unsupported("unexpected error computing terminal device loss: {}".format(exc))

    @staticmethod
    def inline_device_loss(context):
        """
        Generic inline device (damper, VAV box, ...) loss: a single
        dimensionless coefficient K taken directly from
        properties["LossCoefficient"], applied to the connecting duct's own
        velocity pressure at the device's outlet. No neck-size conversion is
        needed here (unlike terminal_component_loss) since these devices
        carry the same duct through both ports rather than stepping down to
        a separate neck size.

        Expects exactly 2 connected_ports (one inlet, one outlet). Returns
        one EXACT LossPath referenced to the outlet's own velocity
        (matching the inline-chain convention analysis/pressure.py already
        uses), or UNSUPPORTED if LossCoefficient isn't set (nothing to
        compute) or the topology can't be resolved.
        """
        try:
            ports = HVACLibraryAPI.connected_ports(context)
            if len(ports) != 2:
                return HVACLossAPI._unsupported("expected exactly 2 connected ports, found {}".format(len(ports)))
            outlet = next((p for p in ports if p.get("flow_into_junction") is False), None)
            inlet = next((p for p in ports if p is not outlet), None)
            if outlet is None:
                return HVACLossAPI._unsupported("could not resolve outlet direction")

            properties = context.get("properties") or {}
            k = float(properties.get("LossCoefficient", 0.0) or 0.0)
            if k <= 0.0:
                return HVACLossAPI._unsupported("LossCoefficient not set")

            return HVACLossAPI._exact([HVACLossAPI._leg_path(outlet, inlet["edge_key"], k, source="inline_device")])
        except Exception as exc:
            return HVACLossAPI._unsupported("unexpected error computing inline device loss: {}".format(exc))

    # FanConnection choice -> which table (see fan_connection_loss).
    _FAN_TRANSITIONS = {
        "transition_symmetric": "symmetric_sides_straight",
        "transition_asymmetric_top_level": "asymmetric_top_level",
        "transition_asymmetric_top_10_down": "asymmetric_top_10_down",
        "transition_asymmetric_top_10_up": "asymmetric_top_10_up",
        "transition_pyramidal": "pyramidal",
    }
    _FAN_WHEELS = {"airfoil": "airfoil", "backward_inclined": "backward_inclined", "forward_curved": "forward_curved"}

    @staticmethod
    def fan_connection_loss(context):
        """
        The system-effect loss where a duct leaves a fan (an AHU's supply
        connection), from properties["FanConnection"]:

        - "Transition symmetric" / "... asymmetric top level" / "... top 10
          down" / "... top 10 up" / "... pyramidal": a transition from the
          fan outlet to the duct, SMACNA 14-11 F to J, at TransitionAngle
          and the area ratio duct / fan outlet.
        - "Discharge into casing": the fan blows freely into the unit's own
          casing (a plenum) and the duct leaves that, 14-16 I, by FanWheel.

        The fan outlet is the equipment port the end is connected to
        (context "equipment_port"). The tables are
        printed against the fan outlet's velocity; the result is referenced
        to the duct's, K = C (A_duct / A_outlet)^2. Only for air leaving the
        unit into the duct. "None" or no FanConnection: UNSUPPORTED (no fan
        connection to cost), as is a duct that carries air into the unit.
        """
        try:
            properties = context.get("properties") or {}
            choice = HVACLossAPI._choice(properties.get("FanConnection"), "none")
            if choice == "none":
                return HVACLossAPI._unsupported("no fan connection")
            port, problem = HVACLossAPI._single_port(context, entering=True)
            if port is None:
                return HVACLossAPI._unsupported("fan connection: " + problem)

            # The fan outlet is the equipment port the end sits on. (FanOutletWidth /
            # FanOutletHeight only show its size, and a round port's would be its
            # diameter twice, so the port's own area is used.)
            a_duct = HVACLibraryAPI.port_area(port)
            equipment_port = context.get("equipment_port")
            a_outlet = HVACLibraryAPI.port_area(equipment_port) if equipment_port else 0.0
            if a_outlet <= 0.0:
                # A document from before kept a typed-in outlet size: still honoured.
                width = float(properties.get("FanOutletWidth", 0.0) or 0.0)
                height = float(properties.get("FanOutletHeight", 0.0) or 0.0)
                a_outlet = width * height / 1.0e6
            if a_outlet <= 0.0 or a_duct <= 0.0:
                return HVACLossAPI._unsupported("no fan outlet size: the duct end is on no equipment port")
            to_duct = (a_duct / a_outlet) ** 2

            if choice in HVACLossAPI._FAN_TRANSITIONS:
                notes = []
                area_ratio = a_duct / a_outlet
                if area_ratio < 1.0:
                    notes.append("the duct is smaller than the fan outlet; the tables are for an expansion")
                angle = float(properties.get("TransitionAngle", 0.0) or 0.0)
                lookup = transition_tables.expansion_at_fan(HVACLossAPI._FAN_TRANSITIONS[choice], angle, area_ratio)
                lookup = loss_table.Lookup(lookup.value * to_duct, lookup.clamped, lookup.filled)
                return HVACLossAPI._from_lookup(port, None, lookup, "smacna_fan_" + choice, notes)
            if choice == "discharge_into_casing":
                wheel = HVACLossAPI._choice(properties.get("FanWheel"), "backward_inclined")
                if wheel not in HVACLossAPI._FAN_WHEELS:
                    return HVACLossAPI._unsupported("unknown FanWheel '{}'".format(wheel))
                lookup = entry_exit_tables.exit_fan_into_plenum(HVACLossAPI._FAN_WHEELS[wheel])
                lookup = loss_table.Lookup(lookup.value * to_duct)
                return HVACLossAPI._from_lookup(port, None, lookup, "smacna_fan_discharge_into_casing")
            return HVACLossAPI._unsupported("unknown FanConnection '{}'".format(choice))
        except Exception as exc:
            return HVACLossAPI._unsupported("unexpected error computing fan connection loss: {}".format(exc))

    @staticmethod
    def sum_losses(first, second):
        """
        Two LossEvaluations of the same one-path fitting added together
        (e.g. a unit's own coefficient plus its fan connection). An
        UNSUPPORTED one is left out; the status is the weaker of the two
        (EXACT only when both are), and warnings are joined.
        """
        parts = [e for e in (first, second) if e is not None and e.status != LossStatus.UNSUPPORTED and e.paths]
        if not parts:
            return first if first is not None else second
        if len(parts) == 1:
            return parts[0]
        a, b = parts
        if len(a.paths) != 1 or len(b.paths) != 1 or a.paths[0].reference_edge_key != b.paths[0].reference_edge_key:
            raise ValueError("sum_losses needs two one-path evaluations on the same leg")
        path = a.paths[0]
        total = LossPath(
            path.from_edge_key,
            path.to_edge_key,
            path.reference_edge_key,
            path.loss_coefficient + b.paths[0].loss_coefficient,
            source="{}+{}".format(path.source, b.paths[0].source),
        )
        warnings = "; ".join(w for w in (a.warning, b.warning) if w) or None
        status = LossStatus.EXACT if a.status == b.status == LossStatus.EXACT else LossStatus.APPROXIMATION
        return LossEvaluation(paths=[total], status=status, warning=warnings)

    @staticmethod
    def fixed_pressure_drop_loss(context):
        """
        A device rated by a pressure drop instead of a coefficient (an air
        terminal or a VAV box from a manufacturer's data sheet):
        properties["PressureDrop"] in Pa, taken as given at the current flow.

        The solver only works in coefficients, so the drop is turned into
        the K that gives exactly that many Pa at the device's present
        velocity: K = PressureDrop / (rho * V^2 / 2). Works for a 1-port
        terminal and for a 2-port inline device (referenced to its outlet).
        UNSUPPORTED when PressureDrop is not set.
        """
        try:
            ports = HVACLibraryAPI.connected_ports(context)
            if len(ports) == 1:
                port, other_edge_key = ports[0], None
            elif len(ports) == 2:
                pair, problem = HVACLossAPI._inline_ports(context)
                if pair is None:
                    return HVACLossAPI._unsupported(problem)
                port, other_edge_key = pair[1], pair[0]["edge_key"]
            else:
                return HVACLossAPI._unsupported("expected 1 or 2 connected ports, found {}".format(len(ports)))

            properties = context.get("properties") or {}
            pressure_drop_pa = float(properties.get("PressureDrop", 0.0) or 0.0)
            if pressure_drop_pa <= 0.0:
                return HVACLossAPI._unsupported("PressureDrop not set")

            source = "fixed_pressure_drop"
            velocity = float(port.get("velocity_ms", 0.0) or 0.0)
            density = float(context.get("air_density", 0.0) or 0.0)
            if velocity <= 1e-9:
                # No flow, no loss: there is no velocity to refer a coefficient to.
                return HVACLossAPI._exact([HVACLossAPI._leg_path(port, other_edge_key, 0.0, source=source)])
            if density <= 0.0:
                return HVACLossAPI._unsupported("air density is not known")
            k = pressure_drop_pa / airflow.velocity_pressure(density, velocity)
            return HVACLossAPI._exact([HVACLossAPI._leg_path(port, other_edge_key, k, source=source)])
        except Exception as exc:
            return HVACLossAPI._unsupported("unexpected error computing fixed pressure drop: {}".format(exc))

    @staticmethod
    def plenum_loss(context):
        """
        Loss of a plenum box, for any number of inlets and outlets.

        The box is large enough for the air to come to rest in it, so each
        inlet is an abrupt exit into the box (SMACNA Table 14-16, C = 1 on
        the inlet velocity) and each outlet is a flush entry from it (Table
        14-15 A, C = 0.5 on the outlet velocity). One LossPath per
        inlet/outlet pair, referenced to the outlet:

            K = C_entry + C_exit * (V_inlet / V_outlet)^2

        Always APPROXIMATION: the tables are for an opening in a large
        space, which a real plenum only approaches.
        """
        try:
            ports = HVACLibraryAPI.connected_ports(context)
            inlets = [p for p in ports if p.get("flow_into_junction") is True]
            outlets = [p for p in ports if p.get("flow_into_junction") is False]
            if not inlets or not outlets:
                return HVACLossAPI._unsupported("a plenum needs at least one inlet and one outlet with known flow")

            c_exit = entry_exit_tables.EXIT_ABRUPT_C
            c_entry = entry_exit_tables.entry_duct_in_wall(0.0, 0.0).value
            paths = []
            for outlet in outlets:
                v_out = float(outlet.get("velocity_ms", 0.0) or 0.0)
                for inlet in inlets:
                    v_in = float(inlet.get("velocity_ms", 0.0) or 0.0)
                    k = 0.0 if v_out <= 1e-9 else c_entry + c_exit * (v_in / v_out) ** 2
                    paths.append(
                        LossPath(inlet["edge_key"], outlet["edge_key"], outlet["edge_key"], k, source="plenum")
                    )
            warning = "plenum: each inlet taken as an abrupt exit, each outlet as a flush entry"
            return HVACLossAPI._approximation(paths, warning)
        except Exception as exc:
            return HVACLossAPI._unsupported("unexpected error computing plenum loss: {}".format(exc))

    # ------------------------------------------------------------------
    # Table-driven entries, exits, screens, dampers and obstructions
    # (SMACNA Tables 14-15 to 14-18, see library/loss_tables/).
    #
    # Each reads its geometry from the type's own properties. Lengths are
    # in mm and angles in degrees, like every other property.
    # ------------------------------------------------------------------

    @staticmethod
    def _choice(value, default):
        """
        A drop-down choice as the key these methods use: lower case with
        underscores, so a type-def may show "Opposed blade" for
        "opposed_blade". Empty or missing gives `default`.
        """
        key = str(value or "").strip().lower().replace(" ", "_").replace("-", "_")
        return key or default

    @staticmethod
    def _from_lookup(port, other_edge_key, lookup, source, notes=()):
        """
        One-path LossEvaluation from a table Lookup. EXACT when the point
        was inside the printed table; otherwise APPROXIMATION with a
        warning saying why (off the printed range, a blank cell, or any
        extra `notes` the caller adds).
        """
        path = HVACLossAPI._leg_path(port, other_edge_key, lookup.value, source=source)
        reasons = list(notes)
        if lookup.clamped:
            reasons.append("outside the printed range of the table")
        if lookup.filled:
            reasons.append("in a cell the table leaves blank")
        if reasons:
            return HVACLossAPI._approximation([path], "{}: {}".format(source, "; ".join(reasons)))
        return HVACLossAPI._exact([path])

    @staticmethod
    def _reference_diameter_mm(port):
        """
        The "D" the tables divide lengths by: the diameter of a round duct,
        2HW / (H + W) for a rectangular one. Returns (D, note); the note is
        set for a profile the tables are not printed for (oval is treated
        like a rectangle of the same width and height).
        """
        profile = HVACLibraryAPI.port_profile(port)
        if profile == "Circular":
            return float(HVACLibraryAPI.port_diameter(port)), None
        width, height = float(HVACLibraryAPI.port_width(port)), float(HVACLibraryAPI.port_height(port))
        if width <= 0.0 or height <= 0.0:
            return 0.0, None
        note = None if profile == "Rectangular" else "table is not printed for a {} duct".format(profile)
        return 2.0 * height * width / (height + width), note

    @staticmethod
    def _screen_lookup(properties):
        """The Table 14-17 lookup for an optional screen/plate in an opening, or None if there is none."""
        free_area = float(properties.get("ScreenFreeArea", 0.0) or 0.0)
        if free_area <= 0.0 or free_area >= 1.0:
            return None
        return obstruction_tables.screen(free_area)

    @staticmethod
    def _single_port(context, entering):
        """
        The one port of a terminal fitting, checked against the flow
        direction the fitting is for. Returns (port, None) or (None, reason).
        `entering` = air enters the duct system here.
        """
        ports = HVACLibraryAPI.connected_ports(context)
        if len(ports) != 1:
            return None, "expected exactly 1 connected port, found {}".format(len(ports))
        port = ports[0]
        # Air entering the system flows out of this terminal node into its duct.
        flows_into_node = port.get("flow_into_junction")
        if flows_into_node is None:
            return None, "flow direction at the terminal is not known"
        if bool(flows_into_node) == bool(entering):
            kind = "an entry" if entering else "an exit"
            return None, "this is {} fitting, but air flows the other way here".format(kind)
        return port, None

    @staticmethod
    def entry_loss(context):
        """
        Loss of an entry: air entering the duct system from a room or from
        outdoors (SMACNA Table 14-15). properties["EntryType"] picks the shape:

        - "duct_in_wall" (default): plain duct end. WallThickness,
          ProjectionLength (how far it sticks out of the wall; 0 = flush).
        - "bellmouth": rounded lip (round ducts). LipRadius, EndWall.
        - "conical": cone or pyramid. ConeAngle (included), ConeLength, EndWall.
        - "intake_hood": weather hood. HoodAngle (0 or 15), HoodHeight.
        - "tapered_hood": capture hood. HoodAngle (included).
        - "canopy_hood": kitchen canopy, one fixed coefficient.

        ScreenFreeArea (0 to 1) adds a screen in the opening; OpeningAreaRatio
        is that opening's area over the duct area (default 1).
        """
        try:
            port, problem = HVACLossAPI._single_port(context, entering=True)
            if port is None:
                return HVACLossAPI._unsupported(problem)
            properties = context.get("properties") or {}
            kind = HVACLossAPI._choice(properties.get("EntryType"), "duct_in_wall")
            diameter, note = HVACLossAPI._reference_diameter_mm(port)
            if diameter <= 0.0:
                return HVACLossAPI._unsupported("invalid duct size")
            rectangular = HVACLibraryAPI.port_profile(port) != "Circular"
            notes = [note] if note else []

            def length(name):
                return max(float(properties.get(name, 0.0) or 0.0), 0.0)

            end_wall = bool(properties.get("EndWall", False))
            if kind == "duct_in_wall":
                lookup = entry_exit_tables.entry_duct_in_wall(
                    length("WallThickness") / diameter, length("ProjectionLength") / diameter
                )
            elif kind == "bellmouth":
                if rectangular:
                    notes.append("bellmouth table is printed for round ducts")
                lookup = entry_exit_tables.entry_bellmouth(length("LipRadius") / diameter, end_wall)
            elif kind == "conical":
                lookup = entry_exit_tables.entry_conical(length("ConeAngle"), length("ConeLength") / diameter, end_wall)
            elif kind == "intake_hood":
                lookup = entry_exit_tables.entry_intake_hood(length("HoodAngle"), length("HoodHeight") / diameter)
            elif kind == "tapered_hood":
                lookup = entry_exit_tables.entry_hood_tapered(length("HoodAngle"), rectangular)
            elif kind == "canopy_hood":
                lookup = loss_table.Lookup(entry_exit_tables.ENTRY_CANOPY_HOOD_C)
            else:
                return HVACLossAPI._unsupported("unknown EntryType '{}'".format(kind))

            screen = HVACLossAPI._screen_lookup(properties)
            if screen is not None:
                ratio = float(properties.get("OpeningAreaRatio", 1.0) or 1.0)
                lookup = entry_exit_tables.with_screen(lookup, screen, ratio)
            return HVACLossAPI._from_lookup(port, None, lookup, "smacna_entry_" + kind, notes)
        except Exception as exc:
            return HVACLossAPI._unsupported("unexpected error computing entry loss: {}".format(exc))

    @staticmethod
    def exit_loss(context):
        """
        Loss of an exit: air leaving the duct system (SMACNA Table 14-16).
        properties["ExitType"] picks the shape:

        - "abrupt" (default): plain duct end, C = 1.
        - "conical": round diffusing cone. ConeAngle (included), AreaRatio
          (exit area over duct area).
        - "plane_diffuser": rectangular, one pair of sides diverging. ConeAngle, AreaRatio.
        - "pyramidal_diffuser": rectangular, all sides diverging. ConeAngle, AreaRatio.
        - "exhaust_hood": weather hood. HoodAngle (0 or 15), HoodHeight.

        ScreenFreeArea (0 to 1) adds a screen in the exit opening.
        """
        try:
            port, problem = HVACLossAPI._single_port(context, entering=False)
            if port is None:
                return HVACLossAPI._unsupported(problem)
            properties = context.get("properties") or {}
            kind = HVACLossAPI._choice(properties.get("ExitType"), "abrupt")
            diameter, note = HVACLossAPI._reference_diameter_mm(port)
            if diameter <= 0.0:
                return HVACLossAPI._unsupported("invalid duct size")
            rectangular = HVACLibraryAPI.port_profile(port) != "Circular"
            notes = [note] if note else []

            def value(name, default=0.0):
                return max(float(properties.get(name, default) or default), 0.0)

            area_ratio = max(value("AreaRatio", 1.0), 1.0)
            opening_ratio = 1.0
            if kind == "abrupt":
                lookup = loss_table.Lookup(entry_exit_tables.EXIT_ABRUPT_C)
            elif kind == "conical":
                if rectangular:
                    notes.append("conical exit table is printed for round ducts")
                lookup = entry_exit_tables.exit_conical_round(value("ConeAngle"), area_ratio)
                opening_ratio = area_ratio
            elif kind in ("plane_diffuser", "pyramidal_diffuser"):
                if not rectangular:
                    notes.append("diffuser exit table is printed for rectangular ducts")
                table_fn = (
                    entry_exit_tables.exit_plane_diffuser_rect
                    if kind == "plane_diffuser"
                    else entry_exit_tables.exit_pyramidal_diffuser_rect
                )
                lookup = table_fn(value("ConeAngle"), area_ratio)
                opening_ratio = area_ratio
            elif kind == "exhaust_hood":
                lookup = entry_exit_tables.exit_exhaust_hood(value("HoodAngle"), value("HoodHeight") / diameter)
            else:
                return HVACLossAPI._unsupported("unknown ExitType '{}'".format(kind))

            screen = HVACLossAPI._screen_lookup(properties)
            if screen is not None:
                lookup = entry_exit_tables.with_screen(lookup, screen, opening_ratio)
            return HVACLossAPI._from_lookup(port, None, lookup, "smacna_exit_" + kind, notes)
        except Exception as exc:
            return HVACLossAPI._unsupported("unexpected error computing exit loss: {}".format(exc))

    @staticmethod
    def _inline_ports(context):
        """(inlet, outlet) of a two-port inline fitting, or (None, reason)."""
        ports = HVACLibraryAPI.connected_ports(context)
        if len(ports) != 2:
            return None, "expected exactly 2 connected ports, found {}".format(len(ports))
        outlet = next((p for p in ports if p.get("flow_into_junction") is False), None)
        if outlet is None:
            return None, "could not resolve outlet direction"
        inlet = next(p for p in ports if p is not outlet)
        return (inlet, outlet), None

    @staticmethod
    def screen_loss(context):
        """
        Loss of a screen or perforated plate across the duct (SMACNA Table
        14-17). properties["FreeAreaRatio"] is the open fraction (0 to 1).
        A perforated plate also sets PlateThickness and HoleDiameter; with
        no HoleDiameter the fitting is treated as a wire screen.
        """
        try:
            pair, problem = HVACLossAPI._inline_ports(context)
            if pair is None:
                return HVACLossAPI._unsupported(problem)
            inlet, outlet = pair
            properties = context.get("properties") or {}
            free_area = float(properties.get("FreeAreaRatio", 0.0) or 0.0)
            if free_area <= 0.0 or free_area > 1.0:
                return HVACLossAPI._unsupported("FreeAreaRatio must be above 0 and at most 1")
            hole = float(properties.get("HoleDiameter", 0.0) or 0.0)
            if hole > 0.0:
                thickness = float(properties.get("PlateThickness", 0.0) or 0.0)
                lookup = obstruction_tables.perforated_plate(free_area, thickness / hole)
                source = "smacna_perforated_plate"
            else:
                lookup = obstruction_tables.screen(free_area)
                source = "smacna_screen"
            return HVACLossAPI._from_lookup(outlet, inlet["edge_key"], lookup, source)
        except Exception as exc:
            return HVACLossAPI._unsupported("unexpected error computing screen loss: {}".format(exc))

    @staticmethod
    def damper_loss(context):
        """
        Loss of a damper at its current blade position (SMACNA Table 14-18
        A to G). properties["DamperType"] picks the kind:

        - "butterfly" (default): single thin blade. BladeAngle (0 = fully open).
        - "butterfly_airfoil": single airfoil blade, rectangular. BladeAngle.
        - "gate": sliding gate. GateOpening = open height over duct height (0 to 1).
        - "parallel_blade" / "opposed_blade": multi-blade, rectangular.
          BladeAngle, BladeCount; the blades run along the duct width.
        """
        try:
            pair, problem = HVACLossAPI._inline_ports(context)
            if pair is None:
                return HVACLossAPI._unsupported(problem)
            inlet, outlet = pair
            properties = context.get("properties") or {}
            kind = HVACLossAPI._choice(properties.get("DamperType"), "butterfly")
            angle = max(float(properties.get("BladeAngle", 0.0) or 0.0), 0.0)
            profile = HVACLibraryAPI.port_profile(outlet)
            round_duct = profile == "Circular"
            notes = []
            if profile not in ("Circular", "Rectangular"):
                notes.append("table is not printed for a {} duct".format(profile))

            if kind == "butterfly":
                table_kind = "thin_plate_round" if round_duct else "thin_plate_rect"
                lookup = obstruction_tables.butterfly_damper(table_kind, angle)
            elif kind == "butterfly_airfoil":
                if round_duct:
                    notes.append("airfoil blade table is printed for rectangular ducts")
                lookup = obstruction_tables.butterfly_damper("airfoil_rect", angle)
            elif kind == "gate":
                opening = float(properties.get("GateOpening", 1.0) or 0.0)
                if opening <= 0.0:
                    return HVACLossAPI._unsupported("GateOpening must be above 0 (a closed gate passes no air)")
                if round_duct:
                    lookup = obstruction_tables.gate_damper_round(opening)
                else:
                    width, height = HVACLibraryAPI.port_width(outlet), HVACLibraryAPI.port_height(outlet)
                    if width <= 0.0 or height <= 0.0:
                        return HVACLossAPI._unsupported("invalid duct size")
                    lookup = obstruction_tables.gate_damper_rect(height / width, opening)
            elif kind in ("parallel_blade", "opposed_blade"):
                if round_duct:
                    return HVACLossAPI._unsupported("multi-blade damper tables are for rectangular ducts")
                width, height = HVACLibraryAPI.port_width(outlet), HVACLibraryAPI.port_height(outlet)
                blades = int(properties.get("BladeCount", 0) or 0)
                if width <= 0.0 or height <= 0.0 or blades <= 0:
                    return HVACLossAPI._unsupported("invalid duct size or BladeCount")
                l_on_r = obstruction_tables.blade_l_on_r(blades, width, width, height)
                lookup = obstruction_tables.multi_blade_damper(kind == "opposed_blade", l_on_r, angle)
            else:
                return HVACLossAPI._unsupported("unknown DamperType '{}'".format(kind))
            return HVACLossAPI._from_lookup(outlet, inlet["edge_key"], lookup, "smacna_damper_" + kind, notes)
        except Exception as exc:
            return HVACLossAPI._unsupported("unexpected error computing damper loss: {}".format(exc))

    @staticmethod
    def obstruction_loss(context):
        """
        Loss of a smooth cylinder (a pipe, a rod) crossing the duct (SMACNA
        Table 14-18 H). properties: ObstructionDiameter, and OffsetFromCentre
        (distance of the cylinder axis from the duct centreline; 0 = centred).
        In a rectangular duct the cylinder runs along the width and is
        offset along the height.

        Needs the air's kinematic viscosity and the duct velocity from the
        solver context. With no flow the coefficient cannot be read (it
        depends on the Reynolds number), so a zero loss is returned.
        """
        try:
            pair, problem = HVACLossAPI._inline_ports(context)
            if pair is None:
                return HVACLossAPI._unsupported(problem)
            inlet, outlet = pair
            properties = context.get("properties") or {}
            d_mm = float(properties.get("ObstructionDiameter", 0.0) or 0.0)
            offset_mm = abs(float(properties.get("OffsetFromCentre", 0.0) or 0.0))
            if d_mm <= 0.0:
                return HVACLossAPI._unsupported("ObstructionDiameter not set")

            # Step 1: the length of cylinder inside the duct, and the duct depth it is offset along.
            profile = HVACLibraryAPI.port_profile(outlet)
            notes = []
            if profile == "Circular":
                depth = float(HVACLibraryAPI.port_diameter(outlet))
                if offset_mm >= depth / 2.0:
                    return HVACLossAPI._unsupported("the obstruction lies outside the duct")
                inside_length = 2.0 * math.sqrt((depth / 2.0) ** 2 - offset_mm**2)
            else:
                inside_length = float(HVACLibraryAPI.port_width(outlet))
                depth = float(HVACLibraryAPI.port_height(outlet))
                if profile != "Rectangular":
                    notes.append("table is not printed for a {} duct".format(profile))
            area_mm2 = HVACLibraryAPI.port_area(outlet) * 1.0e6
            if depth <= 0.0 or inside_length <= 0.0 or area_mm2 <= 0.0:
                return HVACLossAPI._unsupported("invalid duct size")

            # Step 2: Reynolds number of the cylinder itself.
            velocity = float(outlet.get("velocity_ms", 0.0) or 0.0)
            viscosity = float(context.get("air_kinematic_viscosity", 0.0) or 0.0)
            if velocity <= 1.0e-9:
                zero = HVACLossAPI._leg_path(outlet, inlet["edge_key"], 0.0, source="smacna_obstruction")
                return HVACLossAPI._exact([zero])
            if viscosity <= 0.0:
                return HVACLossAPI._unsupported("no air viscosity available")
            reynolds = velocity * airflow.mm_to_m(d_mm) / viscosity

            # Step 3: table lookup. The source limits the table to Sm/A < 0.3.
            sm_on_a = d_mm * inside_length / area_mm2
            if sm_on_a >= 0.3:
                notes.append("the obstruction blocks more of the duct than the table covers")
            lookup = obstruction_tables.cylinder(reynolds, sm_on_a, offset_mm / depth)
            return HVACLossAPI._from_lookup(outlet, inlet["edge_key"], lookup, "smacna_obstruction", notes)
        except Exception as exc:
            return HVACLossAPI._unsupported("unexpected error computing obstruction loss: {}".format(exc))

    @staticmethod
    def uniform_fallback_loss(context, k, warning=None):
        """
        Explicit generic-K policy for a fitting shape with no dedicated
        formula (e.g. a true multi-in/multi-out cross): applies `k`
        uniformly to every outlet port, same as the old "return a bare
        float" convention used to mean -- but now an explicit FALLBACK
        result instead of a silently-applied default.
        """
        try:
            ports = HVACLibraryAPI.connected_ports(context)
        except Exception:
            ports = []
        outlets = [p for p in ports if p.get("flow_into_junction") is False]
        paths = [HVACLossAPI._leg_path(p, None, k, source="type-declared fallback") for p in outlets]
        return LossEvaluation(paths=paths, status=LossStatus.FALLBACK, warning=warning)
