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

"""HVACLibraryAPI, part: trims, booleans, topology, finishing and diagnostics. The class itself is in library_api.py."""

from typing import Mapping

import Part

from ._api_common import _EPS

# Bound to the real class by library_api.py once HVACLibraryAPI exists; the
# methods below call each other through it, as they always have.
HVACLibraryAPI = None


class _BooleansMixin:
    # ------------------------------------------------------------------
    # Trim / booleans
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_plane(plane):
        """Normalize a plane argument -- an ``(origin, normal)`` pair or a mapping -- to vectors."""
        if isinstance(plane, Mapping):
            origin = HVACLibraryAPI.vec(plane.get("origin", plane.get("point", (0, 0, 0))))
            normal = HVACLibraryAPI.unit(plane.get("normal", (0, 0, 1)))
        else:
            origin, normal = plane
            origin, normal = HVACLibraryAPI.vec(origin), HVACLibraryAPI.unit(normal)
        return origin, normal

    @classmethod
    def _bounded_plane_face(cls, shape, origin, normal):
        """A finite planar face, generously sized to cover ``shape``'s bounding box.

        Shared by ``clip_plane`` (which extrudes this into a half-space
        solid to trim ``shape``) and ``section_face`` (which intersects it
        directly to read off an exact cross-section). Also returns
        ``extent``/``signed_distance`` so ``clip_plane`` can size its
        extrusion depth without redoing the bounding-box math.
        """
        bb = shape.BoundBox
        extent = max(
            bb.DiagonalLength if hasattr(bb, "DiagonalLength") else 0.0, bb.XLength, bb.YLength, bb.ZLength, 1.0
        )
        shape_center = cls.vec(((bb.XMin + bb.XMax) / 2.0, (bb.YMin + bb.YMax) / 2.0, (bb.ZMin + bb.ZMax) / 2.0))
        signed_distance = (shape_center - origin).dot(normal)
        plane_center = shape_center - normal * signed_distance
        size = extent * 4.0
        _, x_axis, y_axis, _ = cls.make_profile_frame(normal, None, origin)
        corner = plane_center - x_axis * (size / 2.0) - y_axis * (size / 2.0)
        face = Part.makePlane(size, size, corner, normal, x_axis)
        return face, extent, signed_distance

    @classmethod
    def clip_plane(cls, shape, plane, side="positive"):
        """Keep one half of ``shape`` relative to an infinite plane.

        ``plane`` is ``(origin, normal)`` or a mapping. ``side`` accepts
        positive/front/normal or negative/back/opposite aliases.
        """
        origin, normal = cls._resolve_plane(plane)

        side_key = str(side).strip().lower()
        positive_aliases = {"positive", "+", "front", "normal"}
        negative_aliases = {"negative", "-", "back", "opposite"}
        if side_key not in positive_aliases | negative_aliases:
            raise ValueError(f"Unsupported clip-plane side: {side}")

        plane_face, extent, signed_distance = cls._bounded_plane_face(shape, origin, normal)
        depth = abs(signed_distance) + extent * 2.0
        positive = side_key in positive_aliases
        # FreeCAD's Python Part module does not expose OCC's half-space
        # builder consistently. Extruding a plane larger than the target's
        # bounding box creates an equivalent bounded clipping solid.
        half_space = plane_face.extrude(normal * (depth if positive else -depth))
        result = shape.common(half_space)
        if result.isNull() or not result.Solids:
            # A shape that never actually reaches the requested side of the
            # plane produces an empty (but "valid") result -- fail here,
            # with the plane/side that caused it, instead of leaving an
            # empty shape to crash confusingly deep inside whatever uses
            # it next (e.g. an invalid-bounding-box error far from here).
            raise ValueError(
                f"clip_plane produced an empty shape: nothing of the input "
                f"shape lies on the {side!r} side of the given plane"
            )
        return result

    @classmethod
    def section_face(cls, shape, plane):
        """Return the exact planar cross-section where ``shape`` meets a plane.

        ``plane`` is ``(origin, normal)`` or a mapping, same as
        ``clip_plane``. This is the ready-made face a neighbouring piece
        should be built against after ``clip_plane`` trims a shape back to
        a cut line (e.g. a mitre plane) -- reading the real cut face back
        off the trimmed shape avoids any mismatch against an independently
        built, idealised profile that might not land exactly on the plane.

        Reads the face directly off ``shape.Faces`` rather than
        intersecting with a fresh plane face: a plane coincident with (part
        of) the shape's own boundary -- exactly the case right after
        ``clip_plane`` cut it there -- is a tangential/degenerate boolean
        for OCC, which is unreliable (it can silently return empty). The
        cut face is already a real face of ``shape``; this just finds it.
        """
        origin, normal = cls._resolve_plane(plane)
        bb = shape.BoundBox
        tol = max(bb.DiagonalLength if hasattr(bb, "DiagonalLength") else 0.0, 1.0) * 1e-6

        matches = []
        for face in shape.Faces:
            surface = face.Surface
            if not isinstance(surface, Part.Plane):
                continue
            face_normal = cls.unit(surface.Axis)
            if abs(abs(face_normal.dot(normal)) - 1.0) > 1e-6:
                continue
            if abs((face.CenterOfMass - origin).dot(normal)) > tol:
                continue
            matches.append(face)

        if not matches:
            raise RuntimeError("No face of the shape lies on the requested plane")
        result = matches[0]
        for extra in matches[1:]:
            result = result.fuse(extra)
        return result

    @classmethod
    def trim(cls, shape, boundary, keep="inside"):
        """Trim ``shape`` with a plane or another Part shape.

        Shape boundaries support intersection (``inside``) and difference
        (``outside``). Plane mappings use their own optional ``side`` value
        and default to the positive half-space.
        """
        if isinstance(boundary, Mapping) and ("normal" in boundary or "plane" in boundary):
            plane = boundary.get("plane", boundary)
            return cls.clip_plane(shape, plane, boundary.get("side", "positive"))
        mode = str(keep).lower()
        if mode in {"inside", "common", "intersection"}:
            return cls.common(shape, boundary)
        if mode in {"outside", "cut", "difference"}:
            return cls.cut(shape, boundary)
        raise ValueError(f"Unsupported trim keep mode: {keep}")

    @staticmethod
    def _flatten_shapes(shapes):
        """Flatten nested lists/tuples and discard null or missing shapes."""
        result = []
        for shape in shapes:
            if shape is None:
                continue
            if isinstance(shape, (list, tuple)):
                result.extend(HVACLibraryAPI._flatten_shapes(shape))
            elif not shape.isNull():
                result.append(shape)
        return result

    @classmethod
    def fuse(cls, *shapes, refine=False):
        """Fuse nested shape arguments, optionally removing splitters."""
        items = cls._flatten_shapes(shapes)
        if not items:
            return Part.Shape()
        result = items[0]
        for item in items[1:]:
            result = result.fuse(item)
        return cls.refine(result) if refine else result

    @classmethod
    def cut(cls, shape, *tools, refine=False):
        """Subtract each non-null tool from ``shape`` in argument order."""
        result = shape
        for tool in cls._flatten_shapes(tools):
            result = result.cut(tool)
        return cls.refine(result) if refine else result

    @classmethod
    def common(cls, *shapes, refine=False):
        """Intersect nested shape arguments, optionally removing splitters."""
        items = cls._flatten_shapes(shapes)
        if not items:
            return Part.Shape()
        result = items[0]
        for item in items[1:]:
            result = result.common(item)
        return cls.refine(result) if refine else result

    # ------------------------------------------------------------------
    # Topology
    # ------------------------------------------------------------------

    @staticmethod
    def reverse(shape):
        """Return a copy with reversed topology orientation."""
        out = shape.copy()
        out.reverse()
        return out

    # ------------------------------------------------------------------
    # Finish / diagnostics / tiny common primitives
    # ------------------------------------------------------------------

    @staticmethod
    def refine(shape):
        """
        Remove boolean splitters when OCC can do so safely.

        Merging faces sometimes turns a valid shape into an invalid one
        (seen on fused swept bodies, where a later cut then gives a wrong
        result). In that case the original, unrefined shape is returned.
        """
        if shape is None or shape.isNull():
            return shape
        try:
            # Work on a copy: removeSplitter() can adjust tolerances inside
            # the shape it is given, which leaves the caller's original
            # damaged even when the refined result is thrown away below.
            refined = shape.copy().removeSplitter()
        except Exception:
            return shape
        if refined is None or refined.isNull():
            return shape
        # An invalid input has nothing to protect: refining often repairs it.
        if not shape.isValid():
            return refined
        if not refined.isValid():
            return shape
        # A refined shape can also stay "valid" but silently lose or gain
        # material. Refining a valid shape never should change its volume,
        # so treat any real change as a failed refine.
        try:
            before, after = float(shape.Volume), float(refined.Volume)
        except Exception:
            return refined
        if abs(after - before) > 1.0e-6 * max(abs(before), 1.0):
            return shape
        return refined
        if abs(after - before) > 1.0e-6 * max(abs(before), 1.0):
            return shape
        return refined

    @staticmethod
    def validate(shape, *, raise_on_error=False, require_solid=False):
        """Return a stable diagnostic dictionary for a Part shape.

        Set ``require_solid`` to treat shapes without solids as invalid and
        ``raise_on_error`` to raise ``ValueError`` instead of only reporting
        accumulated messages.
        """
        errors = []
        null = shape is None or shape.isNull()
        valid = False if null else bool(shape.isValid())
        if null:
            errors.append("null shape")
        elif not valid:
            errors.append("Part shape is invalid")
        solid_count = 0 if null else len(shape.Solids)
        if require_solid and solid_count < 1:
            errors.append("shape contains no solid")
        closed = False if null else (shape.isClosed() if hasattr(shape, "isClosed") else None)
        result = {
            "valid": not errors,
            "shape_type": None if null else shape.ShapeType,
            "null": null,
            "closed": closed,
            "solid_count": solid_count,
            "volume": 0.0 if null else float(getattr(shape, "Volume", 0.0) or 0.0),
            "errors": errors,
        }
        if raise_on_error and errors:
            raise ValueError("; ".join(errors))
        return result

    @classmethod
    def make_sphere(cls, center, diameter):
        """Create a sphere from its center and positive diameter."""
        d = float(diameter)
        if d <= _EPS:
            raise ValueError("Sphere diameter must be positive")
        return Part.makeSphere(d / 2.0, cls.vec(center))

    @classmethod
    def make_line(cls, start, end):
        """Create a line edge between two distinct points."""
        start_point = cls.vec(start)
        end_point = cls.vec(end)
        if (end_point - start_point).Length <= _EPS:
            raise ValueError("Line endpoints must be distinct")
        return Part.makeLine(start_point, end_point)

    @classmethod
    def compound(cls, shapes):
        """Create a compound from nested non-null shape sequences."""
        return Part.makeCompound(cls._flatten_shapes(shapes))
