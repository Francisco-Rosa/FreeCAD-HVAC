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


# --------------------------------------------------------------------------
# Basic helpers
# --------------------------------------------------------------------------

def _vec(v):
    if hasattr(v, "x"):
        return FreeCAD.Vector(v)
    return FreeCAD.Vector(*v)


def _unit(v):
    out = FreeCAD.Vector(v)
    if out.Length <= 1e-9:
        raise ValueError("Zero-length vector")
    out.normalize()
    return out


def _center_from_context(context):
    return _vec(context["center_point"])


def _angle_between(u1, u2):
    dot = max(-1.0, min(1.0, float(u1.dot(u2))))
    return math.acos(dot)


def _port_direction(port):
    return _unit(_vec(port["direction"]))


def _port_profile(port):
    return str(port.get("profile", "") or "")


def _port_section_params(port):
    return dict(port.get("section_params", {}) or {})


def _port_diameter(port):
    params = _port_section_params(port)
    return float(params.get("Diameter", 0.0) or 0.0)
    
    
def _port_point_and_dir(center, port, length):
    """
    Return the endpoint of a port measured away from the junction center.
    """
    u = _port_direction(port)
    p = center + u * float(length)
    return p, u


def _make_circular_face(center, axis, diameter):
    edge = Part.makeCircle(float(diameter) / 2.0, center, axis)
    wire = Part.Wire([edge])
    return Part.Face(wire)


def _safe_transition_length(length, d1, d2):
    L = float(length or 0.0)
    if L > 1e-6:
        return L

    # simple fallback rule
    return max(float(d1), float(d2), 1.0) * 1.5


# --------------------------------------------------------------------------
# Generic trim reporting
# --------------------------------------------------------------------------

def _build_records(context, length_value):
    records = []

    connected_ports = list(context.get("connected_ports", []) or [])
    for port in connected_ports:
        edge_key = str(port.get("edge_key", "") or "")
        seg_end = str(port.get("segment_end", "") or "")
        if not edge_key or seg_end not in ("start", "end"):
            continue

        records.append(
            {
                "edge_key": edge_key,
                "segment_end": seg_end,
                "length": float(length_value),
            }
        )

    return records


# --------------------------------------------------------------------------
# Marker geometry
# --------------------------------------------------------------------------

def _make_sphere(center, diameter):
    radius = float(diameter) / 2.0
    if radius <= 0:
        raise ValueError("Marker diameter must be > 0")

    sphere = Part.makeSphere(radius)
    placement = FreeCAD.Placement(center, FreeCAD.Rotation())
    out = sphere.copy()
    out.transformShape(placement.toMatrix(), True, False)
    return out


def _build_marker(context, default_diameter, trim_factor):
    center = _center_from_context(context)
    dia = float(context["properties"].get("MarkerDiameter", default_diameter) or default_diameter)

    shape = _make_sphere(center, dia)
    trim_len = float(dia) * float(trim_factor)

    return {
        "shape": shape,
        "connection_lengths": _build_records(context, trim_len),
    }


# --------------------------------------------------------------------------
# Marker generators
# --------------------------------------------------------------------------

def build_terminal_marker(context):
    return _build_marker(context, default_diameter=200.0, trim_factor=0.25)


def build_transition_marker(context):
    return _build_marker(context, default_diameter=240.0, trim_factor=0.30)


def build_elbow_marker(context):
    return _build_marker(context, default_diameter=240.0, trim_factor=0.35)


def build_tee_marker(context):
    return _build_marker(context, default_diameter=260.0, trim_factor=0.40)


def build_wye_marker(context):
    return _build_marker(context, default_diameter=260.0, trim_factor=0.40)


def build_cross_marker(context):
    return _build_marker(context, default_diameter=280.0, trim_factor=0.45)


def build_manifold_marker(context):
    return _build_marker(context, default_diameter=320.0, trim_factor=0.50)


# --------------------------------------------------------------------------
# Circular elbow generator
# --------------------------------------------------------------------------

def _elbow_trim(radius, theta_rad):
    t = math.tan(theta_rad / 2.0)
    if abs(t) <= 1e-12:
        return 0.0
    return float(radius) * t


def _minor_arc_delta(a1, a2):
    da = a2 - a1
    while da <= -math.pi:
        da += 2.0 * math.pi
    while da > math.pi:
        da -= 2.0 * math.pi
    return da


def _build_circular_elbow_shape(center, u1, u2, diameter, radius):
    """
    Build a swept circular elbow from two outgoing port directions.

    center   : junction corner point
    u1, u2   : unit vectors pointing away from the junction
    diameter : duct diameter
    radius   : centerline radius
    """
    theta = _angle_between(u1, u2)

    if theta <= 1e-6:
        raise ValueError("Elbow requires non-collinear directions")
    if abs(theta - math.pi) <= 1e-6:
        raise ValueError("Elbow cannot be built for opposite directions")

    normal = u1.cross(u2)
    if normal.Length <= 1e-9:
        raise ValueError("Elbow plane is undefined")
    normal.normalize()

    bis = FreeCAD.Vector(u1.add(u2))
    if bis.Length <= 1e-9:
        raise ValueError("Invalid elbow bisector")
    bis.normalize()

    trim = _elbow_trim(radius, theta)

    # Tangency points on the two connected straight segments
    p1 = center + u1 * trim
    p2 = center + u2 * trim

    # Arc center lies on the internal angle bisector
    dist_to_arc_center = float(radius) / math.sin(theta / 2.0)
    arc_center = center + bis * dist_to_arc_center

    # Build minor arc explicitly using a midpoint on the intended elbow side
    mid_dir = FreeCAD.Vector(bis)
    mid_dir.multiply(-1.0)   # inward from arc center toward elbow interior
    mid_point = arc_center + mid_dir * float(radius)

    arc_edge = Part.Arc(p1, mid_point, p2).toShape()
    path_wire = Part.Wire([arc_edge])

    # Circular profile normal to tangent at p1
    profile_edge = Part.makeCircle(float(diameter) / 2.0, p1, u1)
    profile_wire = Part.Wire([profile_edge])

    shell = path_wire.makePipeShell([profile_wire], True, True)
    solid = Part.makeSolid(shell)

    return solid, trim
    
def build_circular_elbow_90(context):
    """
    First real port-aware fitting.

    Requirements:
    - exactly 2 ports
    - both ports circular
    - equal diameters
    """
    center = _center_from_context(context)
    ports = list(context.get("connected_ports", []) or [])
    props = dict(context.get("properties", {}) or {})

    if len(ports) != 2:
        raise ValueError("Circular elbow requires exactly 2 ports")

    for p in ports:
        if _port_profile(p) != "Circular":
            raise ValueError("Circular elbow requires circular ports")

    d1 = _port_diameter(ports[0])
    d2 = _port_diameter(ports[1])
    if d1 <= 0 or d2 <= 0:
        raise ValueError("Circular elbow requires valid port diameters")

    if abs(d1 - d2) > 1e-6:
        raise ValueError("Circular elbow currently requires equal diameters")

    diameter = d1
    radius = float(props.get("CenterlineRadius", 0.0) or 0.0)
    if radius <= 0:
        radius = 1.5 * diameter

    u1 = _port_direction(ports[0])
    u2 = _port_direction(ports[1])

    shape, trim = _build_circular_elbow_shape(center, u1, u2, diameter, radius)

    trims = [
        {
            "edge_key": str(ports[0]["edge_key"]),
            "segment_end": str(ports[0]["segment_end"]),
            "length": float(trim),
        },
        {
            "edge_key": str(ports[1]["edge_key"]),
            "segment_end": str(ports[1]["segment_end"]),
            "length": float(trim),
        },
    ]

    return {
        "shape": shape,
        "connection_lengths": trims,
    }


def build_circular_transition(context):
    """
    Port-aware circular transition between two circular ports.

    Requirements:
    - exactly 2 ports
    - both circular
    - nearly opposite directions
    """
    center = _center_from_context(context)
    ports = list(context.get("connected_ports", []) or [])
    props = dict(context.get("properties", {}) or {})

    if len(ports) != 2:
        raise ValueError("Circular transition requires exactly 2 ports")

    for p in ports:
        if _port_profile(p) != "Circular":
            raise ValueError("Circular transition requires circular ports")

    d1 = _port_diameter(ports[0])
    d2 = _port_diameter(ports[1])

    if d1 <= 0 or d2 <= 0:
        raise ValueError("Circular transition requires valid port diameters")

    u1 = _port_direction(ports[0])
    u2 = _port_direction(ports[1])

    theta = _angle_between(u1, u2)

    # Transition should be nearly straight / collinear
    if abs(theta - math.pi) > math.radians(10.0):
        raise ValueError("Circular transition requires near-opposite port directions")

    length = _safe_transition_length(props.get("TransitionLength", 0.0), d1, d2)

    trim1 = 0.5 * length
    trim2 = 0.5 * length

    p1, _ = _port_point_and_dir(center, ports[0], trim1)
    p2, _ = _port_point_and_dir(center, ports[1], trim2)

    # Loft between two circular faces
    face1 = _make_circular_face(p1, u1, d1)
    face2 = _make_circular_face(p2, u2, d2)

    loft = Part.makeLoft([face1.OuterWire, face2.OuterWire], True, True)

    trims = [
        {
            "edge_key": str(ports[0]["edge_key"]),
            "segment_end": str(ports[0]["segment_end"]),
            "length": float(trim1),
        },
        {
            "edge_key": str(ports[1]["edge_key"]),
            "segment_end": str(ports[1]["segment_end"]),
            "length": float(trim2),
        },
    ]

    return {
        "shape": loft,
        "connection_lengths": trims,
    }
