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

import math
import FreeCAD
import Part

from ..utils import hvaclib

class HVACLibraryAPI:
    """
    Stable public API for built-in and external HVAC generator libraries.

    External/user-defined libraries should use only this API surface instead of
    importing internal HVAC modules directly.
    """

    API_VERSION = 1
    EPS = 1e-9

    # ------------------------------------------------------------------
    # Basic vector / numeric helpers
    # ------------------------------------------------------------------
    @staticmethod
    def vec(v):
        if hasattr(v, "x"):
            return FreeCAD.Vector(v)
        return FreeCAD.Vector(*v)

    @staticmethod
    def xyz(v):
        vv = HVACLibraryAPI.vec(v)
        return (vv.x, vv.y, vv.z)

    @staticmethod
    def unit(v, eps=None):
        eps = HVACLibraryAPI.EPS if eps is None else float(eps)
        out = HVACLibraryAPI.vec(v)
        if out.Length <= eps:
            raise ValueError("Zero-length vector")
        out.normalize()
        return out

    @staticmethod
    def is_zero(v, eps=None):
        eps = HVACLibraryAPI.EPS if eps is None else float(eps)
        return HVACLibraryAPI.vec(v).Length <= eps

    @staticmethod
    def angle_between(u1, u2):
        a = HVACLibraryAPI.unit(u1)
        b = HVACLibraryAPI.unit(u2)
        dot = max(-1.0, min(1.0, float(a.dot(b))))
        return math.acos(dot)

    @staticmethod
    def average_point(points):
        pts = list(points or [])
        if not pts:
            return FreeCAD.Vector(0, 0, 0)
        s = FreeCAD.Vector(0, 0, 0)
        for p in pts:
            s = s + HVACLibraryAPI.vec(p)
        return s * (1.0 / float(len(pts)))
        
    @staticmethod
    def distance_between_lines(origin_i, dir_i, origin_j, dir_j):
        """
        Compute the perpendicular distance between two lines in 3D.
        Each line is defined by a FreeCAD.Vector origin and direction.
        Handles parallel/coincident lines as a special case.
        """    
        u_i = FreeCAD.Vector(dir_i).normalize()
        u_j = FreeCAD.Vector(dir_j).normalize()
        w0  = FreeCAD.Vector(origin_i) - FreeCAD.Vector(origin_j)
    
        cross = u_i.cross(u_j)
        denom = cross.Length
    
        if denom < 1e-10:
            # Lines are parallel — distance is |w0 × u_i|
            return w0.cross(u_i).Length
    
        # Skew lines — |(w0 · (d_i × d_j))| / |d_i × d_j|
        return abs(w0.dot(cross)) / denom
        
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
    def virtual_corner_for_lines(p0, u0, p1, u1):
        """
        Compute the virtual corner from the two offset segment centerlines.
        Lines starting from p0 with direction u0 and from p1 with direction u1.
        """
        d0 = FreeCAD.Vector(u0)
        d1 = FreeCAD.Vector(u1)
        d0.normalize()
        d1.normalize()
    
        # Lines traced back toward the junction
        c0, c1 = HVACLibraryAPI.closest_points_on_lines(
            FreeCAD.Vector(p0), d0,
            FreeCAD.Vector(p1), d1
        )
        if c0 is None or c1 is None:
            raise ValueError("Failed to compute virtual corner")
    
        # For clean coplanar cases c0 ~= c1; midpoint is robust
        corner = (c0 + c1) * 0.5
    
        # Sanity check
        if (c0 - c1).Length > HVACLibraryAPI.EPS:
            FreeCAD.Console.PrintWarning(
                "HVAC: elbow centerlines do not intersect exactly; using midpoint of closest points\n"
            )
    
        return corner
        
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
        cp = context.get("center_point", None)
        if cp is not None:
            return HVACLibraryAPI.vec(cp)
        ports = HVACLibraryAPI.connected_ports(context)
        if not ports:
            raise ValueError("Junction context requires center_point or connected_ports")
        return HVACLibraryAPI.average_point([p["position"] for p in ports])

    @staticmethod
    def connected_ports(context):
        return list(context.get("connected_ports", []) or [])
        
    @staticmethod
    def port_position(port):
        return HVACLibraryAPI.vec(port["position"])

    @staticmethod
    def port_direction(port):
        return HVACLibraryAPI.unit(port["direction"])

    @staticmethod
    def port_profile(port):
        return str(port.get("profile", "") or "")

    @staticmethod
    def port_section_params(port):
        return dict(port.get("section_params", {}) or {})

    @staticmethod
    def port_profile_x_axis(port):
        v = port.get("profile_x_axis", None)
        if v is None:
            return None
        vv = HVACLibraryAPI.vec(v)
        return None if vv.Length <= HVACLibraryAPI.EPS else vv

    @staticmethod
    def port_diameter(port):
        params = HVACLibraryAPI.port_section_params(port)
        return float(params.get("Diameter", 0.0) or 0.0)

    @staticmethod
    def port_width(port):
        params = HVACLibraryAPI.port_section_params(port)
        return float(params.get("Width", 0.0) or 0.0)

    @staticmethod
    def port_height(port):
        params = HVACLibraryAPI.port_section_params(port)
        return float(params.get("Height", 0.0) or 0.0)

    @staticmethod
    def copy_port(port, position=None, direction=None, profile_x_axis=None):
        out = dict(port)
        if position is not None:
            out["position"] = HVACLibraryAPI.vec(position)
        if direction is not None:
            out["direction"] = HVACLibraryAPI.vec(direction)
        if profile_x_axis is not None:
            out["profile_x_axis"] = HVACLibraryAPI.vec(profile_x_axis)
        return out
    
    @staticmethod
    def build_trim_rec_from_port_lengths(port_lengths):
        out = []
        for port, length in port_lengths:
            edge_key = str(port.get("edge_key", "") or "")
            seg_end = str(port.get("segment_end", "") or "")
            if not edge_key or seg_end not in ("start", "end"):
                continue
            out.append(
                {
                    "edge_key": edge_key,
                    "segment_end": seg_end,
                    "length": float(length),
                }
            )
        return out
    
    def build_trim_rec_from_context_uniform(context, length_value):
        ports = list(context.get("connected_ports", []) or [])
        return HVACLibraryAPI.build_trim_rec_from_port_lengths([(p, length_value) for p in ports])


    # ------------------------------------------------------------------
    # Frame helpers
    # ------------------------------------------------------------------
    @staticmethod
    def make_profile_frame(direction, preferred_x=None, origin=None):
        return hvaclib.make_profile_frame(direction, preferred_x, origin)

    # ------------------------------------------------------------------
    # Section/profile creation helpers
    # ------------------------------------------------------------------
    @staticmethod
    def make_line_edge(p0, p1):
        v0 = HVACLibraryAPI.vec(p0)
        v1 = HVACLibraryAPI.vec(p1)

        if (v1.sub(v0)).Length <= 1e-9:
            raise ValueError("Cannot create line edge from coincident points")

        return Part.makeLine(v0, v1)

    @staticmethod
    def make_wire_from_edges(edges):
        edge_list = [e for e in (edges or []) if e is not None]

        if not edge_list:
            raise ValueError("make_wire_from_edges requires at least one edge")

        wire = Part.Wire(edge_list)

        if wire.isNull():
            raise ValueError("Failed to create wire from edges")

        return wire
    
    @staticmethod
    def make_rectangular_wire(center, x_axis, y_axis, width, height):
        c = HVACLibraryAPI.vec(center)
        x = HVACLibraryAPI.unit(x_axis) * (float(width) * 0.5)
        y = HVACLibraryAPI.unit(y_axis) * (float(height) * 0.5)

        p1 = c - x - y
        p2 = c + x - y
        p3 = c + x + y
        p4 = c - x + y
        
        return Part.Wire([
            Part.makeLine(p1, p2),
            Part.makeLine(p2, p3),
            Part.makeLine(p3, p4),
            Part.makeLine(p4, p1),
        ])

    @staticmethod
    def make_circular_wire(center, normal, diameter):
        c = HVACLibraryAPI.vec(center)
        n = HVACLibraryAPI.unit(normal)
        r = float(diameter) * 0.5
        circle = Part.Circle(c, n, r)
        return Part.Wire([Part.Edge(circle)])
        
    @staticmethod
    def make_oval_wire(center, x_axis, y_axis, width, height):
        """
        Flat-oval / obround section.
        Major axis along x_axis, minor axis along y_axis.
    
        width  = total overall width
        height = total overall height
    
        Requires width >= height > 0.
        """
        c = HVACLibraryAPI.vec(center)
        x = HVACLibraryAPI.unit(x_axis)
        y = HVACLibraryAPI.unit(y_axis)
    
        width = float(width or 0.0)
        height = float(height or 0.0)
    
        if width <= 0.0 or height <= 0.0:
            raise ValueError("Oval section requires positive Width and Height")
    
        if width < height:
            raise ValueError("Oval section currently requires Width >= Height")
    
        r = 0.5 * height
        straight = width - height
    
        # Degenerates to a circle when width == height
        if straight <= HVACLibraryAPI.EPS:
            return HVACLibraryAPI.make_circular_wire(c, x.cross(y), height)
    
        half_straight = 0.5 * straight
    
        left_center = c - x * half_straight
        right_center = c + x * half_straight
    
        p_lt = left_center + y * r
        p_lb = left_center - y * r
        p_rt = right_center + y * r
        p_rb = right_center - y * r
    
        # top and bottom straight edges
        e_top = Part.makeLine(p_lt, p_rt)
        e_bottom = Part.makeLine(p_rb, p_lb)
    
        normal = x.cross(y)
        if normal.Length <= HVACLibraryAPI.EPS:
            raise ValueError("Invalid oval frame")
        normal.normalize()
    
        # Left semicircle: top -> bottom
        left_arc = Part.Arc(p_lt, left_center - x * r, p_lb).toShape()
    
        # Right semicircle: bottom -> top
        right_arc = Part.Arc(p_rb, right_center + x * r, p_rt).toShape()
    
        return Part.Wire([e_top, right_arc, e_bottom, left_arc])

    @staticmethod
    def make_section_wire(profile, section_params, center, direction, profile_x_axis=None):
        profile = str(profile or "")
        params = dict(section_params or {})
        center = HVACLibraryAPI.vec(center)
        direction = HVACLibraryAPI.unit(direction)
        _, x_axis, y_axis, _ = HVACLibraryAPI.make_profile_frame(
            direction, profile_x_axis, center
        )
        
        if profile == "Circular":
            diameter = float(params.get("Diameter", 0.0) or 0.0)
            if diameter <= 0.0:
                raise ValueError("Circular section requires a positive Diameter")
            return HVACLibraryAPI.make_circular_wire(center, direction, diameter)

        if profile == "Rectangular":
            width = float(params.get("Width", 0.0) or 0.0)
            height = float(params.get("Height", 0.0) or 0.0)
            if width <= 0.0 or height <= 0.0:
                raise ValueError("Rectangular section requires positive Width and Height")
            return HVACLibraryAPI.make_rectangular_wire(center, x_axis, y_axis, width, height)
            
        if profile == "Oval":
            width = float(params.get("Width", 0.0) or 0.0)
            height = float(params.get("Height", 0.0) or 0.0)
            return HVACLibraryAPI.make_oval_wire(center, x_axis, y_axis, width, height)

        raise ValueError("Unsupported profile '{}'".format(profile))
        
    @staticmethod
    def make_section_wire_from_port(port):
        profile = HVACLibraryAPI.port_profile(port)
        center = HVACLibraryAPI.port_position(port)
        direction = HVACLibraryAPI.port_direction(port)
        preferred_x = HVACLibraryAPI.port_profile_x_axis(port)
        section_params = HVACLibraryAPI.port_section_params(port)
        
        return HVACLibraryAPI.make_section_wire(profile, section_params, center, direction, profile_x_axis=preferred_x)
            
    @staticmethod
    def make_section_face(profile, section_params, center, direction, profile_x_axis=None):
        wire = HVACLibraryAPI.make_section_wire(
            profile=profile,
            section_params=section_params,
            center=center,
            direction=direction,
            profile_x_axis=profile_x_axis,
        )
        return Part.Face(wire)
    
    @staticmethod
    def make_section_face_from_port(port):
        profile = HVACLibraryAPI.port_profile(port)
        center = HVACLibraryAPI.port_position(port)
        direction = HVACLibraryAPI.port_direction(port)
        preferred_x = HVACLibraryAPI.port_profile_x_axis(port)
        section_params = HVACLibraryAPI.port_section_params(port)
        
        return HVACLibraryAPI.make_section_face(profile, section_params, center, direction, profile_x_axis=preferred_x)
    
    # ------------------------------------------------------------------
    # Straight solids
    # ------------------------------------------------------------------
    @staticmethod
    def make_straight_shape(start_point, end_point, profile, section_params, profile_x_axis=None):
        p1 = HVACLibraryAPI.vec(start_point)
        p2 = HVACLibraryAPI.vec(end_point)
        direction = p2 - p1
        length = direction.Length
        if length <= HVACLibraryAPI.EPS:
            raise ValueError("Start and end points cannot be identical")

        face = HVACLibraryAPI.make_section_face(
            profile=profile,
            section_params=section_params,
            center=p1,
            direction=direction,
            profile_x_axis=profile_x_axis,
        )
        # _, _, _, z_axis = HVACLibraryAPI.make_profile_frame(direction, profile_x_axis, p1)
        shape = face.extrude(HVACLibraryAPI.unit(direction) * length)

        try:
            return shape.removeSplitter()
        except Exception:
            return shape

    # ------------------------------------------------------------------
    # Sweep helpers
    # ------------------------------------------------------------------
    @staticmethod
    def make_curved_shape(start_point, end_point, profile, section_params, path, profile_x_axis=None, direction = None):
        p1 = HVACLibraryAPI.vec(start_point)
        p2 = HVACLibraryAPI.vec(end_point)
        if direction is None:
            direction = p2 - p1
        direction.normalize()

        if (p2 - p1).Length <= HVACLibraryAPI.EPS:
            raise ValueError("Start and end points cannot be identical")

        section_wire = HVACLibraryAPI.make_section_wire(
            profile=profile,
            section_params=section_params,
            center=p1,
            direction=direction,
            profile_x_axis=profile_x_axis,
        )
        path_wire = Part.Wire([path])
        shape = HVACLibraryAPI.make_pipe_shell(
            spine_wire=path_wire,
            profile_wires=[section_wire],
            make_solid=True,
            is_frenet=False,
        )
        
        try:
            return shape.removeSplitter()
        except Exception:
            return shape
            
    @staticmethod
    def make_pipe_shell(spine_wire, profile_wires, make_solid=True, is_frenet=False):
        shell = Part.BRepOffsetAPI.MakePipeShell(spine_wire)
        for pw in profile_wires:
            shell.add(pw)
        shell.setFrenetMode(bool(is_frenet))
        shell.build()
        if make_solid:
            shell.makeSolid()
        return shell.shape()
        
    @staticmethod
    def make_loft(profile_wires, solid=True, ruled=True):
        return Part.makeLoft(profile_wires, bool(solid), bool(ruled))

    @staticmethod
    def line_wire(p1, p2):
        return Part.Wire([Part.makeLine(HVACLibraryAPI.vec(p1), HVACLibraryAPI.vec(p2))])

    @staticmethod
    def arc_wire(p1, pm, p2):
        edge = Part.Arc(
            HVACLibraryAPI.vec(p1),
            HVACLibraryAPI.vec(pm),
            HVACLibraryAPI.vec(p2),
        ).toShape()
        return Part.Wire([edge])

    @staticmethod
    def fuse_shapes(shapes):
        valid = [s for s in (shapes or []) if s is not None]
        if not valid:
            raise ValueError("No shapes to fuse")
        out = valid[0]
        for shp in valid[1:]:
            out = out.fuse(shp)
        try:
            return out.removeSplitter()
        except Exception:
            return out
