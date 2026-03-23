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

from . import hvaclib

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
