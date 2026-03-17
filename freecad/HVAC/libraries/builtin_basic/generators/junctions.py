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


# --------------------------------------------------------------------------
# Circular transition generator
# --------------------------------------------------------------------------


def _safe_transition_length(length, d1, d2):
    L = float(length or 0.0)
    if L > 1e-6:
        return L

    # simple fallback rule
    return max(float(d1), float(d2), 1.0) * 1.5

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


# --------------------------------------------------------------------------
# Circular tee and wye generator
# --------------------------------------------------------------------------

def _port_end_point(center, port, trim_length):
    u = _port_direction(port)
    return center + u * float(trim_length)


def _find_run_pair(ports, angle_tol_deg=10.0):
    """
    Return indices (i, j, k) where i,j are the collinear run pair
    and k is the branch port.
    """
    if len(ports) != 3:
        raise ValueError("Tee requires exactly 3 ports")

    best = None
    best_err = None

    for i in range(3):
        for j in range(i + 1, 3):
            u1 = _port_direction(ports[i])
            u2 = _port_direction(ports[j])
            theta = math.degrees(_angle_between(u1, u2))
            err = abs(theta - 180.0)
            if best_err is None or err < best_err:
                k = [x for x in range(3) if x not in (i, j)][0]
                best = (i, j, k)
                best_err = err

    if best is None or best_err > angle_tol_deg:
        raise ValueError("Circular tee requires one near-collinear port pair")

    return best


def _make_cylinder_between_points(p1, p2, diameter):
    axis = p2.sub(p1)
    length = axis.Length
    if length <= 1e-9:
        raise ValueError("Cylinder endpoints are coincident")
    return Part.makeCylinder(float(diameter) / 2.0, length, p1, axis)


def _safe_trim(default_value, fallback_value):
    val = float(default_value or 0.0)
    if val > 1e-6:
        return val
    return float(fallback_value)


def build_circular_tee(context):
    """
    First real circular tee.

    Rules:
    - exactly 3 ports
    - all circular
    - one near-collinear pair forms the run
    - branch is the remaining port

    Geometry:
    - main run cylinder between run trim points
    - branch cylinder from branch trim point toward junction center
    - fused result
    """
    center = _center_from_context(context)
    ports = list(context.get("connected_ports", []) or [])
    props = dict(context.get("properties", {}) or {})

    if len(ports) != 3:
        raise ValueError("Circular tee requires exactly 3 ports")

    for p in ports:
        if _port_profile(p) != "Circular":
            raise ValueError("Circular tee requires circular ports")

    run_a_idx, run_b_idx, branch_idx = _find_run_pair(ports)

    run_a = ports[run_a_idx]
    run_b = ports[run_b_idx]
    branch = ports[branch_idx]

    d_run_a = _port_diameter(run_a)
    d_run_b = _port_diameter(run_b)
    d_branch = _port_diameter(branch)

    if d_run_a <= 0 or d_run_b <= 0 or d_branch <= 0:
        raise ValueError("Circular tee requires valid port diameters")

    # First version: require equal run diameters
    if abs(d_run_a - d_run_b) > 1e-6:
        raise ValueError("Circular tee currently requires equal run diameters")

    run_diameter = d_run_a
    branch_diameter = d_branch

    run_trim = _safe_trim(props.get("RunTrimLength", 0.0), 0.5 * run_diameter)
    branch_trim = _safe_trim(props.get("BranchTrimLength", 0.0), 0.5 * branch_diameter)

    p_run_a = _port_end_point(center, run_a, run_trim)
    p_run_b = _port_end_point(center, run_b, run_trim)
    p_branch = _port_end_point(center, branch, branch_trim)

    run_body = _make_cylinder_between_points(p_run_a, p_run_b, run_diameter)
    branch_body = _make_cylinder_between_points(p_branch, center, branch_diameter)

    shape = run_body.fuse(branch_body)
    try:
        shape = shape.removeSplitter()
    except Exception:
        pass

    trims = [
        {
            "edge_key": str(run_a["edge_key"]),
            "segment_end": str(run_a["segment_end"]),
            "length": float(run_trim),
        },
        {
            "edge_key": str(run_b["edge_key"]),
            "segment_end": str(run_b["segment_end"]),
            "length": float(run_trim),
        },
        {
            "edge_key": str(branch["edge_key"]),
            "segment_end": str(branch["segment_end"]),
            "length": float(branch_trim),
        },
    ]

    return {
        "shape": shape,
        "connection_lengths": trims,
    }


def build_circular_wye(context):
    """
    Circular wye fitting (3 ports).

    - 3 circular ports
    - closest-to-collinear pair defines the run axis
    - third port is the branch at an angle

    Geometry:
    - run cylinder between two trimmed run points
    - branch cylinder entering at an angle toward center
    - fused body
    """
    center = _center_from_context(context)
    ports = list(context.get("connected_ports", []) or [])
    props = dict(context.get("properties", {}) or {})

    if len(ports) != 3:
        raise ValueError("Circular wye requires exactly 3 ports")

    for p in ports:
        if _port_profile(p) != "Circular":
            raise ValueError("Circular wye requires circular ports")

    # relaxed pairing (wye is not strictly collinear)
    run_a_idx, run_b_idx, branch_idx = _find_run_pair(ports, angle_tol_deg=60.0)

    run_a = ports[run_a_idx]
    run_b = ports[run_b_idx]
    branch = ports[branch_idx]

    d_run_a = _port_diameter(run_a)
    d_run_b = _port_diameter(run_b)
    d_branch = _port_diameter(branch)

    if d_run_a <= 0 or d_run_b <= 0 or d_branch <= 0:
        raise ValueError("Circular wye requires valid diameters")

    # first version: enforce equal run diameter
    if abs(d_run_a - d_run_b) > 1e-6:
        raise ValueError("Circular wye currently requires equal run diameters")

    run_diameter = d_run_a
    branch_diameter = d_branch

    run_trim = _safe_trim(props.get("RunTrimLength", 0.0), 0.5 * run_diameter)
    branch_trim = _safe_trim(props.get("BranchTrimLength", 0.0), 0.5 * branch_diameter)

    p_run_a = _port_end_point(center, run_a, run_trim)
    p_run_b = _port_end_point(center, run_b, run_trim)
    p_branch = _port_end_point(center, branch, branch_trim)

    # --- Geometry ---

    # Main run
    run_body = _make_cylinder_between_points(p_run_a, p_run_b, run_diameter)

    # Branch enters at angle toward center
    branch_body = _make_cylinder_between_points(p_branch, center, branch_diameter)

    # Fuse
    shape = run_body.fuse(branch_body)

    try:
        shape = shape.removeSplitter()
    except Exception:
        pass

    trims = [
        {
            "edge_key": str(run_a["edge_key"]),
            "segment_end": str(run_a["segment_end"]),
            "length": float(run_trim),
        },
        {
            "edge_key": str(run_b["edge_key"]),
            "segment_end": str(run_b["segment_end"]),
            "length": float(run_trim),
        },
        {
            "edge_key": str(branch["edge_key"]),
            "segment_end": str(branch["segment_end"]),
            "length": float(branch_trim),
        },
    ]

    return {
        "shape": shape,
        "connection_lengths": trims,
    }
