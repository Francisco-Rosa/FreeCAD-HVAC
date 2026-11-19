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

"""HVACLibraryAPI, part: convenience recipes, external geometry and standard fittings. The class itself is in library_api.py."""

import importlib
import math

import Part

from ._api_common import _EPS

# Bound to the real class by library_api.py once HVACLibraryAPI exists; the
# methods below call each other through it, as they always have.
HVACLibraryAPI = None


class _RecipesMixin:
    # ------------------------------------------------------------------
    # Convenience functions: common HVAC recipes and external geometry
    # ------------------------------------------------------------------

    @staticmethod
    def make_flange(port, inward_direction, thickness, height):
        """Build a flat annular flange collar around any supported port profile."""
        thickness = float(thickness)
        height = float(height)
        if thickness <= 0.0 or height <= 0.0:
            raise ValueError("Flange thickness and height must be > 0")
        outer_port = HVACLibraryAPI.grow_port_section(port, height)
        outer_face = HVACLibraryAPI.make_face(
            HVACLibraryAPI.profile_from_port(HVACLibraryAPI.copy_port(outer_port, direction=inward_direction))
        )
        inner_face = HVACLibraryAPI.make_face(
            HVACLibraryAPI.profile_from_port(HVACLibraryAPI.copy_port(port, direction=inward_direction))
        )
        extrusion = HVACLibraryAPI.unit(inward_direction) * thickness
        return outer_face.extrude(extrusion).cut(inner_face.extrude(extrusion))

    @staticmethod
    def make_elbow_path(port0, port1, radius):
        """Create the tangent arc and trimmed ports for a two-port elbow.

        Returns a dict containing ``path``, tangent ``ports``, and
        ``trim_lengths``. Callers can build matching offset profiles at those
        ports and pass them to :meth:`sweep`.
        """
        p0 = HVACLibraryAPI.port_position(port0)
        p1 = HVACLibraryAPI.port_position(port1)
        u0 = HVACLibraryAPI.port_direction(port0)
        u1 = HVACLibraryAPI.port_direction(port1)
        theta = HVACLibraryAPI.angle_between(u0, u1)
        if theta <= 1e-6 or abs(theta - math.pi) <= 1e-6:
            raise ValueError("Elbow requires non-collinear, non-opposite directions")
        radius = float(radius)
        if radius <= 0.0:
            raise ValueError("Elbow radius must be > 0")
        trim = radius / math.tan(theta / 2.0)
        c0, c1 = HVACLibraryAPI.closest_points_on_lines(p0, u0 * -1.0, p1, u1 * -1.0)
        s0 = c0 + u0 * trim
        s1 = c1 + u1 * trim
        center = HVACLibraryAPI.arc_center_from_points_tangents_radius(s0, s1, u0, u1, radius)
        bisector = u0 + u1
        if bisector.Length <= 1e-12:
            raise ValueError("Elbow bisector is undefined")
        bisector.normalize()
        midpoint = center - bisector * radius
        return {
            "path": HVACLibraryAPI._arc_wire(s0, midpoint, s1),
            "ports": [HVACLibraryAPI.copy_port(port0, position=s0), HVACLibraryAPI.copy_port(port1, position=s1)],
            "trim_lengths": [max(0.0, (s0 - p0).dot(u0)), max(0.0, (s1 - p1).dot(u1))],
            "center": center,
        }

    @staticmethod
    def offset_transition_axis(port0, port1, length):
        """Shared axis geometry for a two-port lateral-offset transition.

        Both ports face outward in opposite, parallel directions but sit on
        offset (non-coincident) axes -- the generic "through.offset" case.
        This works out the end points and theoretical sharp turn points
        that every offset-transition builder needs, so the radiussed
        (arc-filleted) and mitered (flat-cut) builders agree on exactly the
        same axis and only differ in how the corner itself is finished.

        Step 1: find the travel direction and the two generated end points,
        ``length`` apart, that preserve the ports' lateral (transverse)
        offset.
        Step 2: find the theoretical sharp turn points -- a quarter of the
        body length in from each end point -- and the direction/angle of
        the diagonal segment connecting them.

        Returns a dict with keys ``p0``/``p1``/``u0``/``u1`` (the original
        port positions/outward directions), ``d`` (unit travel direction,
        port0 -> port1), ``s0``/``s1`` (generated end points), ``corner0``/
        ``corner1`` (turn points), ``diagonal`` (unit corner0 -> corner1
        direction), and ``turn_angle`` (radians, the deflection between the
        end run and the diagonal -- zero for a plain straight run with no
        lateral offset).
        """
        p0 = HVACLibraryAPI.port_position(port0)
        p1 = HVACLibraryAPI.port_position(port1)
        u0 = HVACLibraryAPI.port_direction(port0)
        u1 = HVACLibraryAPI.port_direction(port1)
        theta = HVACLibraryAPI.angle_between(u0, u1)
        if abs(theta - math.pi) > 1e-6:
            raise ValueError("Offset transition requires opposite parallel port directions")
        length = float(length)
        if length <= 0.0:
            raise ValueError("Offset transition length must be > 0")
        eps = HVACLibraryAPI.EPS
        # Step 1: travel direction through the fitting from port0 toward
        # port1, and the two generated end points.  Port directions
        # themselves are outward.
        d = -u0
        d.normalize()
        # Establish corresponding points c0/c1 on the two parallel axes.
        #
        # For parallel lines there is no unique closest-point pair.  Choose
        # points lying at the same axial station, centred between p0 and p1.
        #
        # c1 - c0 is therefore purely transverse to d.
        delta = p1 - p0
        axial_separation = delta.dot(d)
        c0 = p0 + d * (axial_separation / 2.0)
        c1 = p1 - d * (axial_separation / 2.0)
        transverse = c1 - c0
        # Numerical sanity check.
        if abs(transverse.dot(d)) > 1e-6:
            raise ValueError("Failed to establish parallel offset axes")
        # Generated fitting ports.  They are separated by ``length`` in the
        # axial direction while preserving the transverse offset.
        s0 = c0 - d * (length / 2.0)
        s1 = c1 + d * (length / 2.0)
        # Step 2: theoretical sharp corners.
        corner0 = s0 + d * (length / 4.0)
        corner1 = s1 - d * (length / 4.0)
        diagonal_vec = corner1 - corner0
        diagonal_length = diagonal_vec.Length
        if diagonal_length <= eps:
            raise ValueError("Offset transition diagonal is undefined")
        diagonal = HVACLibraryAPI.unit(diagonal_vec)
        # Deflection angle between end straight and diagonal.
        turn_angle = HVACLibraryAPI.angle_between(d, diagonal)
        return {
            "p0": p0,
            "p1": p1,
            "u0": u0,
            "u1": u1,
            "d": d,
            "s0": s0,
            "s1": s1,
            "corner0": corner0,
            "corner1": corner1,
            "diagonal": diagonal,
            "turn_angle": turn_angle,
        }

    @staticmethod
    def make_radiussed_path(port0, port1, length, radius):
        """Create a radiussed offset path between two parallel ports.

        The path consists of:

            straight -> circular arc -> diagonal -> circular arc -> straight

        The fitting has an axial length of ``length``.  The theoretical sharp
        turn points are located at 1/4 of the fitting length from each generated
        port.  ``radius`` specifies the radius of both circular bends.

        The input port directions are outward and must therefore be opposite.

        Returns a dict containing ``path``, trimmed ``ports``,
        ``trim_lengths``, and ``turn_points``.
        """
        length = float(length)
        radius = float(radius)
        if radius <= 0.0:
            raise ValueError("Radiussed offset radius must be > 0")
        axis = HVACLibraryAPI.offset_transition_axis(port0, port1, length)
        p0, p1, u0, u1 = axis["p0"], axis["p1"], axis["u0"], axis["u1"]
        d, s0, s1 = axis["d"], axis["s0"], axis["s1"]
        corner0, corner1 = axis["corner0"], axis["corner1"]
        diagonal, turn_angle = axis["diagonal"], axis["turn_angle"]
        eps = HVACLibraryAPI.EPS
        diagonal_length = (corner1 - corner0).Length
        # ------------------------------------------------------------------
        # No actual offset: return a straight path.
        # ------------------------------------------------------------------
        if turn_angle <= 1e-6:
            return {
                "path": Part.Wire([Part.makeLine(s0, s1)]),
                "ports": [HVACLibraryAPI.copy_port(port0, position=s0), HVACLibraryAPI.copy_port(port1, position=s1)],
                "trim_lengths": [max(0.0, (s0 - p0).dot(u0)), max(0.0, (s1 - p1).dot(u1))],
                "turn_points": [corner0, corner1],
            }
        if turn_angle >= math.pi - 1e-6:
            raise ValueError("Invalid radiussed offset geometry")
        # ------------------------------------------------------------------
        # Circular fillets.
        #
        # Distance from theoretical corner to tangent point:
        #
        #     T = R tan(theta / 2)
        # ------------------------------------------------------------------
        tangent_length = radius * math.tan(turn_angle / 2.0)
        end_straight_available = length / 4.0
        if tangent_length >= end_straight_available - eps:
            raise ValueError("Radius is too large for the available end straight length")
        if 2.0 * tangent_length >= diagonal_length - eps:
            raise ValueError("Radius is too large for the available diagonal length")
        # First bend:
        #
        # s0 ---- a0 )---- a1 ------ diagonal
        #
        a0 = corner0 - d * tangent_length
        a1 = corner0 + diagonal * tangent_length
        # Second bend:
        #
        # diagonal ------ b0 ----( b1 ---- s1
        #
        b0 = corner1 - diagonal * tangent_length
        b1 = corner1 + d * tangent_length

        # ------------------------------------------------------------------
        # Circular arc helper.
        # ------------------------------------------------------------------
        def make_arc(start, end, tangent_start, tangent_end):
            center = HVACLibraryAPI.arc_center_from_points_tangents_radius(
                start, end, tangent_start, tangent_end, radius
            )
            r0 = start - center
            r1 = end - center
            # For bends below 180 degrees, r0 + r1 points toward the
            # midpoint of the minor circular arc.
            rm = r0 + r1
            if rm.Length <= eps:
                raise ValueError("Unable to determine arc midpoint")
            rm.normalize()
            midpoint = center + rm * radius
            return HVACLibraryAPI._arc_wire(start, midpoint, end)

        arc0 = make_arc(a0, a1, d, diagonal)
        arc1 = make_arc(b0, b1, diagonal, d)
        # ------------------------------------------------------------------
        # Assemble continuous path.
        # ------------------------------------------------------------------
        edges = []
        if (a0 - s0).Length > eps:
            edges.append(Part.makeLine(s0, a0))
        edges.extend(arc0.Edges)

        if (b0 - a1).Length > eps:
            edges.append(Part.makeLine(a1, b0))
        edges.extend(arc1.Edges)

        if (s1 - b1).Length > eps:
            edges.append(Part.makeLine(b1, s1))

        return {
            "path": Part.Wire(edges),
            "ports": [HVACLibraryAPI.copy_port(port0, position=s0), HVACLibraryAPI.copy_port(port1, position=s1)],
            "trim_lengths": [max(0.0, (s0 - p0).dot(u0)), max(0.0, (s1 - p1).dot(u1))],
            "turn_points": [corner0, corner1],
        }

    @classmethod
    def build_envelopes(cls, envelope_builder, construction_layers, params):
        """
        Build the nested outer envelopes of a multilayer wall, from the
        clear-air boundary outward.

        `envelope_builder(offset)` builds the fitting's *whole* outer
        boundary shape uniformly offset outward by `offset` from the
        clear-air boundary (an offset of 0 is the air envelope itself) --
        a generator builds this closure once, from its own profiles/path/
        mitre-plane logic (typically via `profile_from_port(..., offset)`),
        and this method is the only thing that ever calls it, so every
        layer reuses exactly the same axes/stations/trim planes.

        `construction_layers` is the type-def's own declared construction
        layers, in order (`context["construction_layers"]`, a list of
        library/construction.py's ConstructionLayerDef). Each layer's
        thickness is read from `params[layer.thickness_property]`; a layer
        with no `thickness_property` contributes zero thickness (e.g. a
        purely descriptive layer with no wall thickness of its own).

        Returns `[air, envelope_1, envelope_2, ..., envelope_N]` -- one
        more shape than there are layers. A zero-thickness layer's
        envelope is the same object as the envelope before it (no
        redundant rebuild), which is how `envelopes_to_layers` recognizes
        it below.
        """
        # Envelopes are kept exactly as built; envelopes_to_layers() decides
        # how to cut them (see _layer_between()).
        envelopes = [envelope_builder(0.0)]
        cumulative = 0.0
        for layer_def in construction_layers:
            thickness_property = getattr(layer_def, "thickness_property", None)
            thickness = float(params.get(thickness_property, 0.0) or 0.0) if thickness_property else 0.0
            if thickness > _EPS:
                cumulative += thickness
                envelopes.append(envelope_builder(cumulative))
            else:
                envelopes.append(envelopes[-1])
        return envelopes

    @classmethod
    def envelopes_to_layers(cls, envelopes):
        """
        Cut `HVACLibraryAPI.build_envelopes()`'s nested envelopes into each
        layer's own physical solid: Layer 1 = Envelope 1 - Air,
        Layer 2 = Envelope 2 - Envelope 1, ..., innermost layer first.

        A layer whose envelope is the same object as the one before it (a
        zero-thickness layer, see `build_envelopes`) is reported as `None`
        without running a boolean at all.
        """
        layers = []
        for inner, outer in zip(envelopes, envelopes[1:]):
            layers.append(None if outer is inner else cls._layer_between(inner, outer))
        return layers

    @classmethod
    def _layer_between(cls, inner, outer):
        """
        One wall layer: the outer envelope with the inner envelope cut out,
        in one cut.

        The inner envelope lies inside the outer one, so the layer's volume
        must equal outer minus inner. A result off by more than 1 % is a
        wrong shape (typically a fragment of the wall) and raises; within
        1 % it is the expected wall, kept even if OCC calls it invalid.
        """
        expected = float(outer.Volume) - float(inner.Volume)
        layer = None
        try:
            layer = cls.refine(cls.cut(outer, inner))
        except Exception:
            layer = None
        if layer is None or layer.isNull() or abs(float(layer.Volume) - expected) > 0.01 * max(abs(expected), 1.0):
            raise ValueError(
                "Could not cut a wall layer out of its envelopes (wall volume should be {:.0f} mm3)".format(expected)
            )
        return layer

    @staticmethod
    def single_layer(context, shape, **extra):
        """
        The `{"layers": ...}` result for a fitting built as one solid (a
        marker, a cap, a fitting with no wall): the shape goes on the type's
        first declared construction layer, or on a layer named "shape" when
        it declares none. Any `extra` keys (connection_lengths, ...) are
        added to the result. The `{"shape": ...}` result form was removed:
        every backend returns layers.
        """
        layers = list(context.get("construction_layers") or [])
        layer_id = layers[0].id if layers else "shape"
        result = {"layers": {layer_id: {"shape": shape}}}
        result.update(extra)
        return result

    @classmethod
    def build_layered_geometry(cls, envelope_builder, construction_layers, params):
        """
        Convenience wrapper: `build_envelopes()` + `envelopes_to_layers()`,
        packaged as the `{"layers": {id: {"shape": ...}}}` dict a geometry
        backend returns (see library/geometry_result.py's `normalize()`).

        This is the one call most multilayer fitting generators need: build
        `envelope_builder(offset)` once from the fitting's own geometry
        context, then hand it here together with `context["construction_layers"]`
        and the resolved `params` -- no per-fitting casing/insulation-specific
        layer helpers required.
        """
        envelopes = cls.build_envelopes(envelope_builder, construction_layers, params)
        layer_shapes = cls.envelopes_to_layers(envelopes)
        return {
            "layers": {layer_def.id: {"shape": shape} for layer_def, shape in zip(construction_layers, layer_shapes)}
        }

    # ------------------------------------------------------------------
    # Standard fittings
    # ------------------------------------------------------------------

    # name -> (shared module, build function, measure function). These are
    # the same shared fitting modules a type-def reaches with the "shared:"
    # module prefix, offered here for code (e.g. a PartScript) that wants a
    # standard fitting as a starting point instead of a whole type.
    STANDARD_FITTINGS = {
        "elbow": ("elbows", "build_elbow", "measure_elbow"),
        "elbow_mitered": ("elbows", "build_elbow_mitered", "measure_elbow_mitered"),
        "transition": ("transitions", "build_transition", "measure_transition"),
        "transition_radiussed": ("transitions", "build_transition_radiussed", "measure_transition_radiussed"),
        "transition_mitered": ("transitions", "build_transition_mitered", "measure_transition_mitered"),
        "tap_straight": ("taps", "build_tap_straight", "measure_tap_straight"),
        "tap_saddle": ("taps", "build_tap_saddle", "measure_tap_saddle"),
        "tap_shoe": ("taps", "build_tap_shoe", "measure_tap_shoe"),
        "tee_straight": ("tees", "build_tee_straight", "measure_tee_straight"),
        "tee_radius_edge": ("tees", "build_tee_radius_edge", "measure_tee_radius_edge"),
        "tee_radius_center": ("tees", "build_tee_radius_center", "measure_tee_radius_center"),
        "tee_mitered_shoe": ("tees", "build_tee_mitered_shoe", "measure_tee_mitered_shoe"),
        "tee_lateral": ("tees", "build_lateral_tee", "measure_lateral_tee"),
        "tee_lateral_radius": ("tees", "build_lateral_tee_radius", "measure_lateral_tee_radius"),
        "tee_lateral_mitered": ("tees", "build_lateral_tee_mitered", "measure_lateral_tee_mitered"),
        "wye_mitered": ("wyes", "build_wye_mitered", "measure_wye_mitered"),
        "wye_radius": ("wyes", "build_wye_radius", "measure_wye_radius"),
        "cross_tee_straight": ("crosses", "build_cross_tee_straight", "measure_cross_tee_straight"),
        "double_wye_radius": ("crosses", "build_double_wye_radius", "measure_double_wye_radius"),
        "double_wye_mitered": ("crosses", "build_double_wye_mitered", "measure_double_wye_mitered"),
        "star_branch": ("stars", "build_branch_generic", "measure_branch_generic"),
        "star_wye": ("stars", "build_wye_generic", "measure_wye_generic"),
        "star_cross": ("stars", "build_cross", "measure_cross"),
        "star_multiport": ("stars", "build_manifold", "measure_manifold"),
        "terminal_body": ("terminals", "build_terminal_body_generic", "measure_terminal_body_generic"),
        "duct_closure": ("terminals", "build_duct_closure_generic", "measure_duct_closure_generic"),
        "terminal_plain": ("terminals", "build_terminal_plain", "measure_terminal_plain"),
        "terminal_bellmouth": ("terminals", "build_terminal_bellmouth", "measure_terminal_bellmouth"),
        "terminal_cone": ("terminals", "build_terminal_cone", "measure_terminal_cone"),
        "terminal_diffusing": ("terminals", "build_terminal_diffusing", "measure_terminal_diffusing"),
        "terminal_hood": ("terminals", "build_terminal_hood", "measure_terminal_hood"),
        "terminal_square": ("terminals", "build_terminal_square", "measure_terminal_square"),
        "terminal_round": ("terminals", "build_terminal_round", "measure_terminal_round"),
        "terminal_slot": ("terminals", "build_terminal_slot", "measure_terminal_slot"),
        "terminal_frame": ("terminals", "build_terminal_frame", "measure_terminal_frame"),
        "plenum": ("boxes", "build_plenum", "measure_plenum"),
        "ahu": ("boxes", "build_ahu", "measure_ahu"),
        "inline_damper": ("inline", "build_damper_generic", "measure_damper_generic"),
        "inline_vav": ("inline", "build_vav_box", "measure_vav_box"),
        "inline_obstruction": ("inline", "build_obstruction_generic", "measure_obstruction_generic"),
        "through": ("through", "build_through_generic", "measure_through_generic"),
    }

    @classmethod
    def _standard_fitting_function(cls, name, index):
        """Look up one function of a named standard fitting (index 1 = build, 2 = measure)."""
        try:
            entry = cls.STANDARD_FITTINGS[name]
        except KeyError:
            raise ValueError(
                "Unknown standard fitting '{}'. Known: {}".format(name, ", ".join(sorted(cls.STANDARD_FITTINGS)))
            ) from None
        # Imported on demand: the fitting modules are plain library code and
        # only ever reach this API through context["hvac_api"].
        module = importlib.import_module("{}.fittings.{}".format(__package__, entry[0]))
        return getattr(module, entry[index])

    @classmethod
    def build_fitting(cls, name, context):
        """
        Build one of the standard fittings (see STANDARD_FITTINGS) for the
        given geometry context: its hollow, layered shape plus its trims,
        as the usual `{"layers": ..., "connection_lengths": ...}` dict. The
        wall build-up comes from the context's construction layers and their
        thickness properties; flanges are the type's construction feature,
        not part of this result.
        """
        return cls._standard_fitting_function(name, 1)(context)

    @classmethod
    def measure_fitting(cls, name, context):
        """The trim records of a standard fitting, without building any shape."""
        return cls._standard_fitting_function(name, 2)(context)

    @classmethod
    def build_layered_fitting(cls, context, envelope_builder, connection_lengths, port_roles=None):
        """
        Finish a custom fitting the same way the standard ones are finished.

        `envelope_builder(offset)` returns the fitting's outer boundary as a
        solid, grown outward by `offset` from the air space. This cuts every
        declared construction layer out of it, adds flanges at the fitting
        ends when the type declares FlangeThickness/FlangeHeight, and
        returns the result dict with `connection_lengths` attached.
        `port_roles` optionally maps edge_key -> role name (e.g. "Branch")
        for per-port ShowFlange<Role> switches.
        """
        common = importlib.import_module("{}.fittings._common".format(__package__))
        return common._finish(context, envelope_builder, connection_lengths, port_roles)

    @staticmethod
    def shape_from_fcstd(
        fcstd_path, context, params=None, result_object="Result", port_names=None, tol_mm=0.5, tol_deg=0.5
    ):
        """Build a shape from an FCStd template file (a parametric sketch-driven model) -- see template_shapes.py."""
        from . import template_shapes

        return template_shapes.build_shape_from_template(
            fcstd_path, context, params, result_object, port_names, tol_mm, tol_deg
        )

    @staticmethod
    def resolve_library_file(context, relative_path):
        """Resolve a path relative to the current type-def's own library folder (e.g. a data file it ships with)."""
        # Lazy import keeps the public API independent from the registry's
        # own import path while this module is being initialized.
        from ..utils import hvaclib

        registry = hvaclib.HVACLibraryService.get_hvac_library_registry()
        return registry.resolve_library_file(context["library_id"], relative_path)
