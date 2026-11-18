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

"""HVACLibraryAPI, part: basic helpers and context / port helpers (vectors, contexts, ports, trim records). The class itself is in library_api.py."""

import importlib
import math

import FreeCAD

from ..analysis import physics as airflow

# Bound to the real class by library_api.py once HVACLibraryAPI exists; the
# methods below call each other through it, as they always have.
HVACLibraryAPI = None


class _PortsMixin:
    # ------------------------------------------------------------------
    # Basic helpers: vectors, contexts, ports, and trim records
    # ------------------------------------------------------------------

    @staticmethod
    def vec(v):
        """Return *v* as a FreeCAD vector."""
        if hasattr(v, "x"):
            return FreeCAD.Vector(v)
        return FreeCAD.Vector(*v)

    @staticmethod
    def xyz(v):
        """Return a vector-like value as an ``(x, y, z)`` tuple."""
        vv = HVACLibraryAPI.vec(v)
        return (vv.x, vv.y, vv.z)

    @staticmethod
    def unit(v, eps=None):
        """Return a normalized copy of *v*, rejecting a zero-length vector."""
        eps = HVACLibraryAPI.EPS if eps is None else float(eps)
        out = HVACLibraryAPI.vec(v)
        if out.Length <= eps:
            raise ValueError("Zero-length vector")
        out.normalize()
        return out

    @staticmethod
    def is_zero(v, eps=None):
        """Return whether *v* is no longer than the requested tolerance."""
        eps = HVACLibraryAPI.EPS if eps is None else float(eps)
        return HVACLibraryAPI.vec(v).Length <= eps

    @staticmethod
    def angle_between(u1, u2):
        """Return the smaller angle between two vectors in radians."""
        a = HVACLibraryAPI.unit(u1)
        b = HVACLibraryAPI.unit(u2)
        dot = max(-1.0, min(1.0, float(a.dot(b))))
        return math.acos(dot)

    @staticmethod
    def rotate_vector(v, axis, angle):
        """Rotate vector *v* by *angle* radians around a unit *axis* (Rodrigues' formula)."""
        v = HVACLibraryAPI.vec(v)
        axis = HVACLibraryAPI.unit(axis)
        cos_a, sin_a = math.cos(angle), math.sin(angle)
        return v * cos_a + axis.cross(v) * sin_a + axis * (axis.dot(v) * (1.0 - cos_a))

    @staticmethod
    def average_point(points):
        """Return the arithmetic mean of points, or the origin for an empty input."""
        pts = list(points or [])
        if not pts:
            return FreeCAD.Vector(0, 0, 0)
        s = FreeCAD.Vector(0, 0, 0)
        for p in pts:
            s = s + HVACLibraryAPI.vec(p)
        return s * (1.0 / float(len(pts)))

    @staticmethod
    def closest_points_on_lines(p0, d0, p1, d1):
        """
        Return closest points c0 on L0 and c1 on L1 for:

            L0(t) = p0 + t d0
            L1(s) = p1 + s d1

        Returns (None, None) for nearly parallel lines.
        """
        p0 = FreeCAD.Vector(p0)
        p1 = FreeCAD.Vector(p1)
        d0 = FreeCAD.Vector(d0)
        d1 = FreeCAD.Vector(d1)

        if d0.Length <= HVACLibraryAPI.EPS or d1.Length <= HVACLibraryAPI.EPS:
            raise ValueError("Line direction too small")

        d0.normalize()
        d1.normalize()

        w0 = p0 - p1
        a = d0.dot(d0)
        b = d0.dot(d1)
        c = d1.dot(d1)
        d = d0.dot(w0)
        e = d1.dot(w0)

        denom = a * c - b * b
        if abs(denom) <= HVACLibraryAPI.EPS:
            return None, None

        t = (b * e - c * d) / denom
        s = (a * e - b * d) / denom

        c0 = p0 + d0 * t
        c1 = p1 + d1 * s
        return c0, c1

    @staticmethod
    def arc_center_from_points_tangents_radius(p0, p1, u0, u1, radius):
        """
        Compute the center of a circular arc joining p0 -> p1 with given radius,
        using tangent directions u0 at p0 and u1 at p1.

        Parameters
        ----------
        p0, p1 : FreeCAD.Vector
            Arc end points.
        u0, u1 : FreeCAD.Vector
            Tangent directions at p0 and p1.
        radius : float
            Arc radius.

        Returns
        -------
        FreeCAD.Vector
            Arc center.

        Notes
        -----
        - The bend plane is derived from u0 x u1.
        - The chosen center is the one whose radius vectors are most
          perpendicular to the supplied tangents.
        """

        p0 = FreeCAD.Vector(p0)
        p1 = FreeCAD.Vector(p1)
        if radius <= 0:
            raise ValueError("Radius must be positive")
        # Normalize tangent directions
        u0 = FreeCAD.Vector(u0)
        u1 = FreeCAD.Vector(u1)
        if u0.Length <= 1e-12 or u1.Length <= 1e-12:
            raise ValueError("Tangent direction too small")
        u0.normalize()
        u1.normalize()

        # Chord between endpoints
        chord = p1 - p0
        d = chord.Length
        if d <= 1e-12:
            raise ValueError("Arc endpoints are coincident")

        # A circle of radius r can span the chord only if d <= 2r
        if d > 2.0 * float(radius) + 1e-9:
            raise ValueError("Radius too small for given endpoints")

        # Midpoint of the chord
        mid = (p0 + p1) * 0.5

        # Bend plane normal from the two tangents
        plane_n = u0.cross(u1)
        if plane_n.Length <= 1e-12:
            raise ValueError("Elbow requires non-collinear tangent directions")
        plane_n.normalize()

        # Unit chord direction
        chord_dir = FreeCAD.Vector(chord)
        chord_dir.normalize()

        # Direction from chord midpoint toward candidate centers,
        # constrained to remain in the bend plane
        perp = plane_n.cross(chord_dir)
        if perp.Length <= 1e-12:
            perp = chord_dir.cross(plane_n)
        if perp.Length <= 1e-12:
            raise ValueError("Failed to compute elbow center direction")
        perp.normalize()

        # Distance from chord midpoint to the circle center
        h_sq = float(radius) ** 2 - (d * 0.5) ** 2
        if h_sq < -1e-9:
            raise ValueError("Invalid geometry for arc center")
        h = math.sqrt(max(h_sq, 0.0))

        # Two possible centers
        c1 = mid + perp * h
        c2 = mid - perp * h

        def score(c):
            """
            Smaller score is better.
            For a valid circle tangent to the arc, the radius vector at each end
            should be perpendicular to the tangent there.
            """
            v0 = p0 - c
            v1 = p1 - c
            return abs(v0.dot(u0)) + abs(v1.dot(u1))

        return c1 if score(c1) <= score(c2) else c2

    # ------------------------------------------------------------------
    # Context / port helpers
    # ------------------------------------------------------------------

    @staticmethod
    def center_from_context(context):
        """The junction's center point, or (if not given) the average of its connected ports' positions."""
        cp = context.get("center_point", None)
        if cp is not None:
            return HVACLibraryAPI.vec(cp)
        ports = HVACLibraryAPI.connected_ports(context)
        if not ports:
            raise ValueError("Junction context requires center_point or connected_ports")
        return HVACLibraryAPI.average_point([p["position"] for p in ports])

    @staticmethod
    def connected_ports(context):
        """Return a copy of the context's connected-port list."""
        return list(context.get("connected_ports", []) or [])

    @staticmethod
    def collinear_port_index_pairs(context):
        """Index pairs (into ``connected_ports(context)``) the network
        classifier already found collinear (~180 deg apart -- see
        ``NetworkParser._collinear_pairs``), read straight off the
        junction's own ``context["analysis"]["collinear_pairs"]`` payload
        (``NetworkParser.JunctionAnalysis``, propagated via
        ``Component._parentAnalysis``/``AnalysisJson``).

        A "which two of this node's ports form the straight run" generator
        (a radiused/mitered tee's trunk, a tap's main run, ...) should use
        this rather than re-deriving collinearity itself, so it agrees
        exactly with the classifier's own family_key decision (same
        tolerance, same data) instead of risking a second, possibly
        divergent judgment call. Empty if no analysis payload is present
        (e.g. a synthetic/unit-test context) -- callers need their own
        geometric fallback for that case.
        """
        analysis = context.get("analysis") or {}
        pairs = analysis.get("collinear_pairs") or []
        result = []
        for pair in pairs:
            try:
                a, b = int(pair["a"]), int(pair["b"])
            except (KeyError, TypeError, ValueError):
                continue
            result.append((a, b))
        return result

    @staticmethod
    def run_branch_ports(context):
        """Return ``(run_a, run_b, branch)`` for a degree-three tee/tap.

        The run pair comes from the network classifier's collinear-pair
        analysis. Port roles are not guessed again from raw geometry here.
        """
        ports = HVACLibraryAPI.connected_ports(context)
        if len(ports) != 3:
            raise ValueError("Run/branch resolution requires exactly three connected ports")

        pairs = HVACLibraryAPI.collinear_port_index_pairs(context)
        if not pairs:
            raise ValueError("Could not identify run pair: context['analysis']['collinear_pairs'] is empty")

        run_a_index, run_b_index = pairs[0]
        valid_indices = range(len(ports))
        if run_a_index == run_b_index or run_a_index not in valid_indices or run_b_index not in valid_indices:
            raise ValueError("Run pair contains invalid connected-port indices")

        branch_indices = [index for index in valid_indices if index not in (run_a_index, run_b_index)]
        if len(branch_indices) != 1:
            raise ValueError("Could not identify exactly one branch port")

        return ports[run_a_index], ports[run_b_index], ports[branch_indices[0]]

    @classmethod
    def port_roles(cls, context):
        """
        The connected ports of the current node, by role name. The roles
        depend only on how many ports there are and how they are arranged:

        - 1 port:  neck
        - 2 ports: inlet, outlet (by flow direction; port order if unknown)
        - 3 ports with a straight run (a tee, a lateral): run_a, run_b, branch
        - 3 ports with no straight run (a wye): main, branch_a, branch_b
        - 4 ports with a straight run (a cross, a double wye):
          run_a, run_b, branch_a, branch_b
        - anything else, including 5 or more ports: port_1 .. port_n

        "Straight run" is the classifier's own collinear pair, so this
        never disagrees with the family the node was given. For port_1..n
        the order is geometric (by outward direction), so it does not
        depend on the order the ports happen to be listed in.
        """
        ports = list(cls.connected_ports(context))
        pairs = cls.collinear_port_index_pairs(context)
        count = len(ports)

        if count == 1:
            return {"neck": ports[0]}

        if count == 2:
            outlet = next((p for p in ports if p.get("flow_into_junction") is False), None)
            inlet = next((p for p in ports if p.get("flow_into_junction") is True), None)
            if inlet is None or outlet is None or inlet is outlet:
                inlet, outlet = ports[0], ports[1]
            return {"inlet": inlet, "outlet": outlet}

        if count == 3 and pairs:
            run_a, run_b, branch = cls.run_branch_ports(context)
            return {"run_a": run_a, "run_b": run_b, "branch": branch}

        if count == 3:
            wyes = importlib.import_module("{}.fittings.wyes".format(__package__))
            main, branch_a, branch_b = wyes._wye_port_roles(cls, ports)
            return {"main": main, "branch_a": branch_a, "branch_b": branch_b}

        if count == 4 and pairs:
            run_index_a, run_index_b = pairs[0]
            rest = [ports[i] for i in range(4) if i not in (run_index_a, run_index_b)]
            rest.sort(key=cls._direction_sort_key)
            return {"run_a": ports[run_index_a], "run_b": ports[run_index_b], "branch_a": rest[0], "branch_b": rest[1]}

        ordered = sorted(ports, key=cls._direction_sort_key)
        return {"port_{}".format(i + 1): port for i, port in enumerate(ordered)}

    @classmethod
    def _direction_sort_key(cls, port):
        """Sort key from a port's outward direction (rounded, so tiny numeric noise can't reorder ports)."""
        direction = cls.unit(cls.port_direction(port))
        return (round(direction.x, 6), round(direction.y, 6), round(direction.z, 6))

    @staticmethod
    def port_param(context, name, port, default=None):
        """
        A property value for one port.

        Works for a per-port property (a type-def property marked
        `"per_port": true`, resolved to one value per connected port) and
        for an ordinary property (one value shared by every port), so a
        generator need not know which of the two a type declares. `default`
        is returned when the property is missing or not set for that port.
        """
        params = context.get("properties") or {}
        value = params.get(name)
        if hasattr(value, "for_port"):
            value = value.for_port(port)
        elif isinstance(value, dict):
            value = value.get(port.get("edge_key"))
        return default if value is None else value

    @staticmethod
    def port_position(port):
        """Return a port's position as a FreeCAD vector."""
        return HVACLibraryAPI.vec(port["position"])

    @staticmethod
    def port_direction(port):
        """Return a port's outward direction as a unit vector."""
        return HVACLibraryAPI.unit(port["direction"])

    @staticmethod
    def port_profile(port):
        """Return the normalized profile name stored on a port."""
        return str(port.get("profile", "") or "")

    @staticmethod
    def port_section_params(port):
        """Return a copy of a port's section-parameter mapping."""
        return dict(port.get("section_params", {}) or {})

    @staticmethod
    def port_profile_x_axis(port):
        """Return a port's profile x-axis, or ``None`` when it is unavailable."""
        v = port.get("profile_x_axis", None)
        if v is None:
            return None
        vv = HVACLibraryAPI.vec(v)
        return None if vv.Length <= HVACLibraryAPI.EPS else vv

    @staticmethod
    def port_diameter(port):
        """Return a circular port's diameter in millimetres, defaulting to zero."""
        params = HVACLibraryAPI.port_section_params(port)
        return float(params.get("Diameter", 0.0) or 0.0)

    @staticmethod
    def port_width(port):
        """Return a rectangular or oval port's width in millimetres."""
        params = HVACLibraryAPI.port_section_params(port)
        return float(params.get("Width", 0.0) or 0.0)

    @staticmethod
    def port_height(port):
        """Return a rectangular or oval port's height in millimetres."""
        params = HVACLibraryAPI.port_section_params(port)
        return float(params.get("Height", 0.0) or 0.0)

    @staticmethod
    def port_area(port):
        """Cross-section area (m^2) of a port, from its profile/section_params (in mm)."""
        profile = HVACLibraryAPI.port_profile(port)
        if profile == "Circular":
            d = HVACLibraryAPI.port_diameter(port)
            return airflow.circular_area(airflow.mm_to_m(d)) if d > 0.0 else 0.0
        if profile in ("Rectangular", "Oval"):
            w = HVACLibraryAPI.port_width(port)
            h = HVACLibraryAPI.port_height(port)
            if w <= 0.0 or h <= 0.0:
                return 0.0
            if profile == "Rectangular":
                return airflow.rectangular_area(airflow.mm_to_m(w), airflow.mm_to_m(h))
            return airflow.oval_area(airflow.mm_to_m(w), airflow.mm_to_m(h))
        return 0.0

    @staticmethod
    def copy_port(port, position=None, direction=None, profile_x_axis=None, edge_key=None, segment_end=None):
        """
        Copy a port dict, optionally overriding position/direction/
        profile_x_axis/edge_key/segment_end (everything else unchanged).

        edge_key/segment_end are useful when synthesizing a port that
        doesn't correspond to the original port's own connection any more
        (e.g. an internal seam between two chained junction components).
        """
        out = dict(port)
        if position is not None:
            out["position"] = HVACLibraryAPI.vec(position)
        if direction is not None:
            out["direction"] = HVACLibraryAPI.vec(direction)
        if profile_x_axis is not None:
            out["profile_x_axis"] = HVACLibraryAPI.vec(profile_x_axis)
        if edge_key is not None:
            out["edge_key"] = str(edge_key)
        if segment_end is not None:
            out["segment_end"] = str(segment_end)
        return out

    @staticmethod
    def grow_port_section(port, delta):
        """
        Copy of `port` with its cross-section grown by `delta` (uniformly,
        on every side) -- position/direction/profile are unchanged, only
        section_params grows. Shared helper for building an insulation (or
        any other wrap-around) shape's own outer profile from a casing
        port's profile, without duplicating this per fitting generator.
        Used for a flange collar (it sits on the outside of the wall) and
        for any other shape wrapped around a port's own section.
        """
        profile = HVACLibraryAPI.port_profile(port)
        params = HVACLibraryAPI.port_section_params(port)
        delta = float(delta)

        if profile == "Circular":
            diameter = float(params.get("Diameter", 0.0) or 0.0) + 2.0 * delta
            if diameter <= 0.0:
                raise ValueError("Grown Diameter must be positive")
            new_params = dict(params, Diameter=diameter)
        elif profile in ("Rectangular", "Oval"):
            width = float(params.get("Width", 0.0) or 0.0) + 2.0 * delta
            height = float(params.get("Height", 0.0) or 0.0) + 2.0 * delta
            if width <= 0.0 or height <= 0.0:
                raise ValueError("Grown Width/Height must be positive")
            new_params = dict(params, Width=width, Height=height)
        else:
            raise ValueError("Unsupported profile '{}' for grow_port_section".format(profile))

        out = HVACLibraryAPI.copy_port(port)
        out["section_params"] = new_params
        return out

    @staticmethod
    def build_trim_rec_from_port_lengths(port_lengths):
        """
        Build the connection_lengths a generator returns from a list of
        (port, trim_length) pairs -- how far each connected segment is
        trimmed back from its own endpoint to make room for this fitting.
        Ports with no real edge_key/segment_end (e.g. a synthetic port) are
        silently skipped.
        """
        out = []
        for port, length in port_lengths:
            edge_key = str(port.get("edge_key", "") or "")
            seg_end = str(port.get("segment_end", "") or "")
            if not edge_key or seg_end not in ("start", "end"):
                continue
            out.append({"edge_key": edge_key, "segment_end": seg_end, "length": float(length)})
        return out

    def build_trim_rec_from_context_uniform(context, length_value):
        """Same as build_trim_rec_from_port_lengths, but trims every connected port by the same length_value."""
        ports = list(context.get("connected_ports", []) or [])
        return HVACLibraryAPI.build_trim_rec_from_port_lengths([(p, length_value) for p in ports])
