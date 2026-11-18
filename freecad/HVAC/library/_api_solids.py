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

"""HVACLibraryAPI, part: straight solids and surface / solid construction. The class itself is in library_api.py."""

import math
from typing import Mapping

import FreeCAD
import Part

from ._api_common import _EPS, HVACProfile

# Bound to the real class by library_api.py once HVACLibraryAPI exists; the
# methods below call each other through it, as they always have.
HVACLibraryAPI = None


class _SolidsMixin:
    # ------------------------------------------------------------------
    # Straight solids
    # ------------------------------------------------------------------

    @staticmethod
    def _arc_wire(p1, pm, p2):
        """A single-edge wire, a circular arc through p1 -> pm -> p2."""
        edge = Part.Arc(HVACLibraryAPI.vec(p1), HVACLibraryAPI.vec(pm), HVACLibraryAPI.vec(p2)).toShape()
        return Part.Wire([edge])

    @classmethod
    def make_profile(cls, profile_type, params, frame=None, *, center=None, direction=None, profile_x_axis=None):
        """Build a closed section wire in a local placement frame.

        ``profile_type`` accepts rectangular, circular, oval, rounded-
        rectangle, and polygon aliases. ``frame`` may be a mapping with
        origin/normal/x-axis entries or a three-item sequence; explicit frame
        keyword arguments fill any values omitted by a mapping.

        Returns an :class:`HVACProfile`. Invalid or collapsed dimensions raise
        ``ValueError``.
        """
        profile = cls._norm_profile_name(profile_type)
        params = dict(params or {})

        if frame is not None:
            if isinstance(frame, Mapping):
                center = frame.get("origin", frame.get("center", center))
                direction = frame.get("normal", frame.get("direction", direction))
                profile_x_axis = frame.get("x_axis", frame.get("profile_x_axis", profile_x_axis))
            elif isinstance(frame, (tuple, list)) and len(frame) >= 3:
                center, direction, profile_x_axis = frame[:3]

        center = cls.vec(center or (0.0, 0.0, 0.0))
        direction = cls.unit(direction or (0.0, 0.0, 1.0))
        _, x_axis, y_axis, _ = cls.make_profile_frame(direction, profile_x_axis, center)

        if profile in {"Rectangular", "Circular", "Oval"}:
            wire = cls._section_wire(profile, params, center, direction, x_axis)
            return HVACProfile(profile, params, center, direction, x_axis, wire)

        if profile == "RoundedRectangle":
            w = float(params.get("Width", params.get("width", 0.0)) or 0.0)
            h = float(params.get("Height", params.get("height", 0.0)) or 0.0)
            r = float(params.get("Radius", params.get("radius", 0.0)) or 0.0)
            if w <= 0 or h <= 0:
                raise ValueError("Rounded rectangle Width and Height must be positive")
            if r < 0 or r > min(w, h) / 2.0 + _EPS:
                raise ValueError("Rounded rectangle Radius must be between 0 and min(Width, Height)/2")
            if r <= _EPS:
                normalized = {"Width": w, "Height": h}
                wire = cls._section_wire("Rectangular", normalized, center, direction, x_axis)
                return HVACProfile(
                    "RoundedRectangle", {"Width": w, "Height": h, "Radius": 0.0}, center, direction, x_axis, wire
                )
            wire = cls._rounded_rectangle_wire(center, x_axis, y_axis, w, h, r)
            return HVACProfile(
                "RoundedRectangle", {"Width": w, "Height": h, "Radius": r}, center, direction, x_axis, wire
            )

        points = params.get("Points", params.get("points"))
        if not points or len(points) < 3:
            raise ValueError("Polygon requires at least three local 2D Points")
        local = tuple((float(p[0]), float(p[1])) for p in points)
        world = [center + x_axis * x + y_axis * y for x, y in local]
        wire = Part.makePolygon(world + [world[0]])
        return HVACProfile("Polygon", {"Points": local}, center, direction, x_axis, wire, local)

    @classmethod
    def profile_from_port(cls, port, offset=0.0):
        """Build an ``HVACProfile`` from a library port.

        A positive ``offset`` grows the port section uniformly before the
        profile is built; a negative value shrinks it.
        """
        working = cls.grow_port_section(port, float(offset)) if abs(float(offset)) > _EPS else port
        return cls.make_profile(
            cls.port_profile(working),
            cls.port_section_params(working),
            center=cls.port_position(working),
            direction=cls.port_direction(working),
            profile_x_axis=cls.port_profile_x_axis(working),
        )

    @classmethod
    def offset_profile(cls, profile, distance):
        """Return a new profile offset uniformly in its local section plane.

        Positive distances grow the clear-air boundary and negative distances
        shrink it. The input must be an ``HVACProfile`` returned by this API.
        """
        if not isinstance(profile, HVACProfile):
            raise TypeError("offset_profile() requires a profile returned by make_profile()")
        d = float(distance)
        p = dict(profile.params)
        kind = profile.profile

        if kind == "Circular":
            diameter = float(p.get("Diameter", p.get("diameter", 0.0))) + 2.0 * d
            if diameter <= _EPS:
                raise ValueError("Profile offset collapses circular section")
            p = {"Diameter": diameter}
        elif kind in {"Rectangular", "Oval"}:
            width = float(p.get("Width", p.get("width", 0.0))) + 2.0 * d
            height = float(p.get("Height", p.get("height", 0.0))) + 2.0 * d
            if width <= _EPS or height <= _EPS:
                raise ValueError("Profile offset collapses section")
            p = {"Width": width, "Height": height}
        elif kind == "RoundedRectangle":
            width = float(p["Width"]) + 2.0 * d
            height = float(p["Height"]) + 2.0 * d
            radius = float(p["Radius"]) + d
            if width <= _EPS or height <= _EPS or radius < -_EPS:
                raise ValueError("Profile offset collapses rounded rectangle")
            p = {"Width": width, "Height": height, "Radius": max(0.0, radius)}
        elif kind == "Polygon":
            p = {"Points": cls._offset_polygon(profile.local_points, d)}
        else:
            raise ValueError(f"Unsupported profile offset: {kind}")

        return cls.make_profile(
            kind, p, center=profile.center, direction=profile.direction, profile_x_axis=profile.profile_x_axis
        )

    @classmethod
    def offset_wire(cls, wire, distance):
        """
        Grow (positive distance) or shrink (negative) any closed planar wire
        in its own plane, keeping sharp corners sharp.

        Use `offset_profile()` for a normal section profile -- it rebuilds
        the section exactly from its own dimensions. This is for a wire that
        is no longer a plain section, e.g. one half of a split profile or a
        section cut off a mitred body.
        """
        source = cls._wire(wire)
        d = float(distance)
        if abs(d) <= _EPS:
            return source
        # join=2 extends the neighbouring edges until they meet, so corners stay sharp.
        result = source.makeOffset2D(d, join=2)
        wires = list(getattr(result, "Wires", []) or [])
        if len(wires) != 1:
            raise ValueError("Wire offset by {} did not give exactly one closed wire".format(d))
        return wires[0]

    @staticmethod
    def profile_projection_bounds(profile, direction):
        """Return the minimum and maximum projection of a profile along direction."""
        shape = profile.wire if hasattr(profile, "wire") else profile
        d = FreeCAD.Vector(direction.x, direction.y, direction.z)
        if d.Length <= HVACLibraryAPI.EPS:
            raise ValueError("Projection direction must be non-zero")
        d.normalize()

        probe = shape.copy()
        rotation = FreeCAD.Rotation(d, FreeCAD.Vector(1.0, 0.0, 0.0))
        probe.transformShape(rotation.toMatrix())
        return probe.BoundBox.XMin, probe.BoundBox.XMax

    @classmethod
    def split_profile_face_by_extent(cls, profile, split_direction, positive_ratio):
        """Split a profile at a linear ratio of its projected extent.

        The requested direction snaps to the nearest local horizontal or
        vertical axis. The positive face points with that oriented axis.
        """
        if not isinstance(profile, HVACProfile):
            raise TypeError("split_profile_face_by_extent() requires an HVACProfile")

        ratio = float(positive_ratio)
        if not 0.0 < ratio < 1.0:
            raise ValueError("Profile split ratio must be between 0 and 1")

        # Step 1: Snap the requested split to one local profile axis.
        _, x_axis, y_axis, profile_normal = cls.make_profile_frame(
            profile.direction, profile.profile_x_axis, profile.center
        )
        requested = cls.vec(split_direction)
        requested = requested - profile_normal * requested.dot(profile_normal)
        if requested.Length <= cls.EPS:
            raise ValueError("Profile split direction must lie in the profile plane")
        requested = cls.unit(requested)

        x_score = requested.dot(x_axis)
        y_score = requested.dot(y_axis)
        normal = x_axis if abs(x_score) >= abs(y_score) else y_axis
        if requested.dot(normal) < 0.0:
            normal = normal * -1.0
        transverse = profile_normal.cross(normal)

        # Step 2: Convert the ratio directly into a projected cut coordinate.
        normal_min, normal_max = cls.profile_projection_bounds(profile, normal)
        transverse_min, transverse_max = cls.profile_projection_bounds(profile, transverse)
        normal_extent = normal_max - normal_min
        transverse_extent = transverse_max - transverse_min
        if normal_extent <= cls.EPS or transverse_extent <= cls.EPS:
            raise ValueError("Profile has no usable split extent")
        cut = normal_max - normal_extent * ratio

        # Step 3: Clip both sides with masks larger than the profile bounds.
        source_face = Part.Face(profile.wire)
        margin = max(normal_extent, transverse_extent, 1.0)
        mask_height = transverse_extent + 2.0 * margin
        transverse_center = 0.5 * (transverse_min + transverse_max)

        def clipped_face(lower, upper):
            width = upper - lower
            mask_center = cls.vec(profile.center)
            mask_center += normal * (0.5 * (lower + upper) - mask_center.dot(normal))
            mask_center += transverse * (transverse_center - mask_center.dot(transverse))
            mask = Part.Face(cls.make_rectangular_wire(mask_center, normal, transverse, width, mask_height))
            result = source_face.common(mask)
            faces = list(result.Faces)
            if len(faces) != 1 or faces[0].Area <= cls.EPS:
                raise ValueError("Profile extent split did not produce one face")
            return faces[0]

        positive = clipped_face(cut, normal_max + margin)
        negative = clipped_face(normal_min - margin, cut)
        return positive, negative

    @staticmethod
    def stretch_profile_one_sided(profile, direction, extension):
        """Stretch a profile along direction while keeping its heel side fixed.

        The profile's minimum projection along direction is treated as the heel.
        The opposite side is extended by ``extension``. No assumption is made
        about profile type or geometry.
        """
        shape = profile.wire if hasattr(profile, "wire") else profile
        d = FreeCAD.Vector(direction.x, direction.y, direction.z)
        if d.Length <= HVACLibraryAPI.EPS:
            raise ValueError("Stretch direction must be non-zero")
        d.normalize()

        p_min, p_max = HVACLibraryAPI.profile_projection_bounds(shape, d)
        width = p_max - p_min
        if width <= HVACLibraryAPI.EPS:
            raise ValueError("Profile has zero extent along stretch direction")

        factor = (width + float(extension)) / width
        k = factor - 1.0

        matrix = FreeCAD.Matrix()
        matrix.A11 = 1.0 + k * d.x * d.x
        matrix.A12 = k * d.x * d.y
        matrix.A13 = k * d.x * d.z
        matrix.A21 = k * d.y * d.x
        matrix.A22 = 1.0 + k * d.y * d.y
        matrix.A23 = k * d.y * d.z
        matrix.A31 = k * d.z * d.x
        matrix.A32 = k * d.z * d.y
        matrix.A33 = 1.0 + k * d.z * d.z
        matrix.A14 = -k * p_min * d.x
        matrix.A24 = -k * p_min * d.y
        matrix.A34 = -k * p_min * d.z

        return shape.transformGeometry(matrix)

    @staticmethod
    def _offset_polygon(points, distance):
        """Offset a simple polygon by intersecting adjacent shifted edges."""
        pts = [(float(x), float(y)) for x, y in points]
        n = len(pts)
        area2 = sum(pts[i][0] * pts[(i + 1) % n][1] - pts[(i + 1) % n][0] * pts[i][1] for i in range(n))
        if abs(area2) <= _EPS:
            raise ValueError("Polygon profile has zero area")
        # For CCW polygon, interior lies left of edges, so outward is right.
        sign = 1.0 if area2 > 0.0 else -1.0
        shifted = []
        for i in range(n):
            x0, y0 = pts[i]
            x1, y1 = pts[(i + 1) % n]
            dx, dy = x1 - x0, y1 - y0
            length = math.hypot(dx, dy)
            if length <= _EPS:
                raise ValueError("Polygon contains a zero-length edge")
            nx, ny = sign * dy / length, -sign * dx / length
            shifted.append(((x0 + nx * distance, y0 + ny * distance), (dx, dy)))

        result = []
        for i in range(n):
            p1, d1 = shifted[(i - 1) % n]
            p2, d2 = shifted[i]
            den = d1[0] * d2[1] - d1[1] * d2[0]
            if abs(den) <= _EPS:
                # Parallel adjacent edges: use the second shifted vertex.
                result.append(p2)
                continue
            qx, qy = p2[0] - p1[0], p2[1] - p1[1]
            t = (qx * d2[1] - qy * d2[0]) / den
            result.append((p1[0] + t * d1[0], p1[1] + t * d1[1]))
        return tuple(result)

    @staticmethod
    def _rounded_rectangle_wire(center, x_axis, y_axis, width, height, radius):
        """Build a rounded-rectangle wire, including capsule/circle limits."""
        hw, hh, r = width / 2.0, height / 2.0, radius
        s2 = math.sqrt(0.5)

        def v(x, y):
            """Map local profile coordinates into the world-space frame."""
            return center + x_axis * x + y_axis * y

        edges = []

        def add_line(start, end):
            """Append a non-degenerate straight side to the boundary."""
            # Maximum corner radii legitimately collapse one or both pairs of
            # straight sides. OCC rejects a zero-length Part edge.
            if (end - start).Length > _EPS:
                edges.append(Part.makeLine(start, end))

        add_line(v(-hw + r, hh), v(hw - r, hh))
        edges.append(Part.Arc(v(hw - r, hh), v(hw - r + r * s2, hh - r + r * s2), v(hw, hh - r)).toShape())
        add_line(v(hw, hh - r), v(hw, -hh + r))
        edges.append(Part.Arc(v(hw, -hh + r), v(hw - r + r * s2, -hh + r - r * s2), v(hw - r, -hh)).toShape())
        add_line(v(hw - r, -hh), v(-hw + r, -hh))
        edges.append(Part.Arc(v(-hw + r, -hh), v(-hw + r - r * s2, -hh + r - r * s2), v(-hw, -hh + r)).toShape())
        add_line(v(-hw, -hh + r), v(-hw, hh - r))
        edges.append(Part.Arc(v(-hw, hh - r), v(-hw + r - r * s2, hh - r + r * s2), v(-hw + r, hh)).toShape())
        return Part.Wire(edges)

    # ------------------------------------------------------------------
    # Surface / solid construction
    # ------------------------------------------------------------------

    @staticmethod
    def _wire(profile_or_wire):
        """Return a profile's wire and normalize a single edge to a wire."""
        shape = profile_or_wire.wire if isinstance(profile_or_wire, HVACProfile) else profile_or_wire
        if getattr(shape, "ShapeType", "") == "Edge":
            return Part.Wire([shape])
        return shape

    @classmethod
    def extrude(cls, profile, vector, *, solid=False):
        """Extrude a profile or wire along a nonzero vector.

        With ``solid=True`` the wire is first converted to a face, producing a
        solid extrusion. Otherwise the wire itself is extruded into a shell.
        """
        wire = cls._wire(profile)
        vec = cls.vec(vector)
        if vec.Length <= _EPS:
            raise ValueError("Extrusion vector must be non-zero")
        return Part.Face(wire).extrude(vec) if solid else wire.extrude(vec)

    @classmethod
    def sweep(cls, profiles, path, *, solid=False, frenet=False, transition=0):
        """Sweep one or more section profiles along a path wire.

        ``frenet`` and ``transition`` are forwarded to OCC's pipe-shell
        builder. A failed, null, or non-solid result (when ``solid=True``)
        raises ``RuntimeError`` with a stable library-facing message.
        """
        if not isinstance(profiles, (list, tuple)):
            profiles = [profiles]
        spine = cls._wire(path)
        wires = [cls._wire(profile) for profile in profiles]
        try:
            shape = spine.makePipeShell(wires, bool(solid), bool(frenet), int(transition))
        except Exception as exc:
            raise RuntimeError(f"Sweep failed: {exc}") from exc
        if shape.isNull():
            raise RuntimeError("Sweep returned a null shape")
        if solid and not shape.Solids:
            raise RuntimeError("Sweep failed to create a solid")
        return shape

    @classmethod
    def loft(cls, profiles, *, solid=False, ruled=True, closed=False):
        """Loft through at least two profiles and return the resulting shape."""
        wires = [cls._wire(p) for p in profiles]
        if len(wires) < 2:
            raise ValueError("loft() requires at least two profiles")
        return Part.makeLoft(wires, bool(solid), bool(ruled), bool(closed))

    @classmethod
    def make_face(cls, profile):
        """A flat face filling a closed profile or planar wire (its outline only, no holes)."""
        face = Part.Face(cls._wire(profile))
        if face.isNull() or face.Area <= _EPS:
            raise ValueError("make_face() needs a closed, planar, non-degenerate wire")
        return face

    @classmethod
    def translate(cls, shape, vector):
        """A copy of ``shape`` moved by ``vector``."""
        out = shape.copy()
        out.translate(cls.vec(vector))
        return out

    @classmethod
    def rotate(cls, shape, origin, axis, degrees):
        """A copy of ``shape`` turned by ``degrees`` about the line through ``origin`` along ``axis``."""
        out = shape.copy()
        out.rotate(cls.vec(origin), cls.unit(axis), float(degrees))
        return out

    @classmethod
    def sample_path(cls, path, spacing):
        """
        Points along a path edge (or a wire of edges), ``spacing`` apart, as
        ``[(point, unit tangent), ...]``. The stations are centred: whatever
        length is left over is split evenly between both ends, so a row of
        ribs or hangers sits symmetrically. Fewer than one ``spacing`` of
        path gives an empty list.
        """
        spacing = float(spacing)
        if spacing <= _EPS:
            raise ValueError("sample_path() needs a positive spacing")
        edges = list(cls._wire(path).OrderedEdges)
        length = sum(edge.Length for edge in edges)
        count = int(length // spacing)
        if count < 1:
            return []
        distance = 0.5 * (length - (count - 1) * spacing)
        stations = []
        walked = 0.0
        for edge in edges:
            # Every station that falls on this edge, measured from the edge's own start.
            # An edge running against the wire's direction is walked from its far end.
            reversed_edge = getattr(edge, "Orientation", "Forward") == "Reversed"
            while len(stations) < count and distance <= walked + edge.Length + _EPS:
                along = min(max(distance - walked, 0.0), edge.Length)
                parameter = edge.getParameterByLength(edge.Length - along if reversed_edge else along)
                tangent = cls.unit(edge.tangentAt(parameter))
                stations.append((edge.valueAt(parameter), tangent * -1.0 if reversed_edge else tangent))
                distance += spacing
            walked += edge.Length
        return stations

    @classmethod
    def revolve(cls, profile, axis, angle=360.0, *, solid=False):
        """Revolve a profile around ``(origin, direction)`` by degrees.

        ``axis`` may also be a mapping with ``origin`` and ``direction`` (or
        ``axis``) entries. ``solid=True`` revolves the profile's filled face.
        """
        if isinstance(axis, Mapping):
            origin = cls.vec(axis.get("origin", (0, 0, 0)))
            direction = cls.unit(axis.get("direction", axis.get("axis", (0, 0, 1))))
        else:
            origin, direction = axis
            origin, direction = cls.vec(origin), cls.unit(direction)
        base = Part.Face(cls._wire(profile)) if solid else cls._wire(profile)
        return base.revolve(origin, direction, float(angle))
