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


def _angle_between(u1, u2):
    dot = max(-1.0, min(1.0, float(u1.dot(u2))))
    return math.acos(dot)


def _average_point(points):
    if not points:
        return FreeCAD.Vector(0, 0, 0)
    s = FreeCAD.Vector(0, 0, 0)
    for p in points:
        s = s + (_vec(p))
    return s * (1.0 / float(len(points)))


def _center_from_context(context):
    cp = context.get("center_point", None)
    if cp is not None:
        return _vec(cp)

    ports = list(context.get("connected_ports", []) or [])
    if not ports:
        raise ValueError("Junction context requires center_point or connected_ports")
    return _average_point([p["position"] for p in ports])


def _port_position(port):
    return _vec(port["position"])


def _port_direction(port):
    return _unit(_vec(port["direction"]))


def _port_profile(port):
    return str(port.get("profile", "") or "")


def _port_section_params(port):
    return dict(port.get("section_params", {}) or {})


def _port_diameter(port):
    params = _port_section_params(port)
    return float(params.get("Diameter", 0.0) or 0.0)


def _port_width(port):
    params = _port_section_params(port)
    return float(params.get("Width", 0.0) or 0.0)


def _port_height(port):
    params = _port_section_params(port)
    return float(params.get("Height", 0.0) or 0.0)


def _copy_port(port, position=None, direction=None):
    out = dict(port)
    if position is not None:
        out["position"] = _vec(position)
    if direction is not None:
        out["direction"] = _vec(direction)
    return out


def make_frame_from_direction(direction, origin=None):
    """
    Create a right-handed orthonormal frame given a direction.

    Parameters
    ----------
    direction : FreeCAD.Vector
        Desired Z-axis (path tangent).
    origin : FreeCAD.Vector or None
        Frame origin. Defaults to (0,0,0).

    Returns
    -------
    (placement, x_dir, y_dir, z_dir)
        placement : FreeCAD.Placement
        x_dir, y_dir, z_dir : FreeCAD.Vector
    """
    if direction.Length <= 1e-12:
        raise ValueError("Direction vector too small")

    # Z axis (tangent)
    z_dir = FreeCAD.Vector(direction)
    z_dir.normalize()

    # Choose a stable reference vector
    ref = FreeCAD.Vector(0, 0, 1)
    if abs(z_dir.dot(ref)) > 0.99:
        ref = FreeCAD.Vector(1, 0, 0)

    # Build orthonormal basis
    x_dir = ref.cross(z_dir)
    if x_dir.Length <= 1e-12:
        raise ValueError("Failed to compute X axis")
    x_dir.normalize()

    y_dir = z_dir.cross(x_dir)
    y_dir.normalize()

    # Build rotation matrix (columns = local axes)
    mat = FreeCAD.Matrix()
    mat.A11, mat.A12, mat.A13 = x_dir.x, y_dir.x, z_dir.x
    mat.A21, mat.A22, mat.A23 = x_dir.y, y_dir.y, z_dir.y
    mat.A31, mat.A32, mat.A33 = x_dir.z, y_dir.z, z_dir.z

    placement = FreeCAD.Placement(mat)
    if origin is not None:
        placement.Base = origin
    
    return placement, x_dir, y_dir, z_dir
    

def _pick_reference(u):
    zref = FreeCAD.Vector(0, 0, 1)
    xref = FreeCAD.Vector(1, 0, 0)
    if abs(u.dot(zref)) < 0.95:
        return zref
    return xref


def _section_size_hint(port):
    profile = _port_profile(port)
    if profile == "Circular":
        return max(_port_diameter(port), 1.0)
    if profile == "Rectangular":
        return max(_port_width(port), _port_height(port), 1.0)
    return 1.0


def _safe_trim(value, fallback_value):
    v = float(value or 0.0)
    if v > 1e-6:
        return v
    return float(fallback_value)


def _build_records_from_port_lengths(port_lengths):
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


def _build_uniform_records(context, length_value):
    ports = list(context.get("connected_ports", []) or [])
    return _build_records_from_port_lengths([(p, length_value) for p in ports])


# --------------------------------------------------------------------------
# Generic profile helpers
# --------------------------------------------------------------------------

def _make_circular_wire(center, axis, diameter):
    edge = Part.makeCircle(float(diameter) / 2.0, center, axis)
    return Part.Wire([edge])


def _make_rectangular_wire(center, x_axis, y_axis, width, height):
    dx = x_axis * (float(width) / 2.0)
    dy = y_axis * (float(height) / 2.0)

    p1 = center - (dx) - (dy)
    p2 = center + (dx) - (dy)
    p3 = center + (dx) + (dy)
    p4 = center - (dx) + (dy)

    edges = [
        Part.makeLine(p1, p2),
        Part.makeLine(p2, p3),
        Part.makeLine(p3, p4),
        Part.makeLine(p4, p1),
    ]
    return Part.Wire(edges)


def _section_wire_from_port(port):
    profile = _port_profile(port)
    center = _port_position(port)
    direction = _port_direction(port)
    _, x_axis, y_axis, z_axis = make_frame_from_direction(direction, center)

    if profile == "Circular":
        diameter = _port_diameter(port)
        if diameter <= 0:
            raise ValueError("Circular profile requires Diameter > 0")
        return _make_circular_wire(center, z_axis, diameter)

    if profile == "Rectangular":
        width = _port_width(port)
        height = _port_height(port)
        if width <= 0 or height <= 0:
            raise ValueError("Rectangular profile requires Width and Height > 0")
        return _make_rectangular_wire(center, x_axis, y_axis, width, height)

    raise ValueError("Unsupported port profile: {}".format(profile))


def _section_face_from_port(port):
    return Part.Face(_section_wire_from_port(port))


def _profiles_compatible(port_a, port_b):
    pa = _port_profile(port_a)
    pb = _port_profile(port_b)
    if pa != pb:
        return False

    if pa == "Circular":
        return True

    if pa == "Rectangular":
        return True

    return False


def _same_section(port_a, port_b, tol=1e-6):
    pa = _port_profile(port_a)
    pb = _port_profile(port_b)
    if pa != pb:
        return False

    if pa == "Circular":
        return abs(_port_diameter(port_a) - _port_diameter(port_b)) <= tol

    if pa == "Rectangular":
        return (
            abs(_port_width(port_a) - _port_width(port_b)) <= tol
            and abs(_port_height(port_a) - _port_height(port_b)) <= tol
        )

    return False


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
    ports = list(context.get("connected_ports", []) or [])
    if not ports:
        raise ValueError("Marker requires at least one port")
    props = dict(context.get("properties", {}) or {})
    dia = float(props.get("MarkerDiameter", default_diameter) or default_diameter)
    center = _port_position(ports[0])

    shape = _make_sphere(center, dia)
    trim_len = float(dia) * float(trim_factor)

    return {
        "shape": shape,
        "connection_lengths": _build_uniform_records(context, trim_len),
    }


def build_terminal_marker(context):
    ports = list(context.get("connected_ports", []) or [])
    props = dict(context.get("properties", {}) or {})
    center = _port_position(ports[0])

    dia = float(props.get("MarkerDiameter", 200.0) or 200.0)
    if dia <= 0:
        raise ValueError("Marker diameter must be > 0")

    trim_len = 0.0

    if len(ports) == 1:
        port_dir = _port_direction(ports[0])
    else:
        port_dir = FreeCAD.Vector(0, 0, 1)

    ref = _pick_reference(port_dir)
    v1 = port_dir.cross(ref)
    if v1.Length <= 1e-9:
        ref = FreeCAD.Vector(0, 1, 0)
        v1 = port_dir.cross(ref)
    v1.normalize()

    v2 = port_dir.cross(v1)
    v2.normalize()

    p1_v1 = center - (v1 * (dia / 2.0))
    p2_v1 = center + (v1 * (dia / 2.0))
    line_v1 = Part.makeLine(p1_v1, p2_v1)

    p1_v2 = center - (v2 * (dia / 2.0))
    p2_v2 = center + (v2 * (dia / 2.0))
    line_v2 = Part.makeLine(p1_v2, p2_v2)

    shape = Part.makeCompound([line_v1, line_v2])

    return {
        "shape": shape,
        "connection_lengths": _build_uniform_records(context, trim_len),
    }


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
# Generic geometric helpers
# --------------------------------------------------------------------------

def _line_line_intersection_best_fit(p1, u1, p2, u2):
    """
    Best-fit intersection of two infinite 3D lines:
        L1 = p1 + t*u1
        L2 = p2 + s*u2

    Returns midpoint of shortest segment between the two lines.
    """
    a = float(u1.dot(u1))
    b = float(u1.dot(u2))
    c = float(u2.dot(u2))
    w0 = p1 - (p2)
    d = float(u1.dot(w0))
    e = float(u2.dot(w0))
    den = a * c - b * b

    if abs(den) <= 1e-12:
        return None

    t = (b * e - c * d) / den
    s = (a * e - b * d) / den

    q1 = p1 + (u1 * (t))
    q2 = p2 + (u2 * (s))
    return (q1 + q2) * 0.5
    

def arc_center_from_points_radius_dirs(p0, p1, u0, u1, radius):
    """
    Compute arc center given endpoints, radius, and tangent directions.

    Parameters
    ----------
    p0, p1 : FreeCAD.Vector
        Endpoints of arc
    u0, u1 : FreeCAD.Vector
        Tangent directions at p0 and p1
    radius : float

    Returns
    -------
    center : FreeCAD.Vector
    """

    if radius <= 0:
        raise ValueError("Radius must be positive")

    # normalize directions
    u0 = FreeCAD.Vector(u0)
    u1 = FreeCAD.Vector(u1)
    u0.normalize()
    u1.normalize()

    # chord
    chord = p1 - p0
    d = chord.Length

    if d <= 1e-12:
        raise ValueError("Points too close")

    if d > 2 * radius:
        raise ValueError("No valid circle (points too far apart)")

    # midpoint
    mid = (p0 + p1) * 0.5

    # perpendicular direction to chord
    u = FreeCAD.Vector(chord)
    u.normalize()

    ref = FreeCAD.Vector(0, 0, 1)
    perp = u.cross(ref)

    if perp.Length <= 1e-12:
        ref = FreeCAD.Vector(1, 0, 0)
        perp = u.cross(ref)

    perp.normalize()

    # distance from midpoint to center
    h = math.sqrt(max(radius**2 - (d * 0.5)**2, 0.0))

    # two candidates
    c1 = mid + perp * h
    c2 = mid - perp * h

    # --- select correct one using tangent condition
    def score(c):
        # radius vector must be perpendicular to tangent
        v0 = (p0 - c)
        v1 = (p1 - c)
        return abs(v0.dot(u0)) + abs(v1.dot(u1))

    if score(c1) < score(c2):
        return c1
    else:
        return c2


def _make_loft_between_ports(port_a, port_b, solid=True, ruled=True):
    wire_a = _section_wire_from_port(port_a)
    wire_b = _section_wire_from_port(port_b)
    return Part.makeLoft([wire_a, wire_b], bool(solid), bool(ruled))
    
    
def _make_multisection_sweep_between_ports(port_a, port_b, path_wire):
    wire_a = _section_wire_from_port(port_a)
    wire_b = _section_wire_from_port(port_b)
    ps = Part.BRepOffsetAPI.MakePipeShell(path_wire)
    ps.add(wire_a)
    ps.add(wire_b)
    ps.setFrenetMode(True)   # important for stable frame
    ps.build()
    ps.makeSolid()
    return ps.shape()


def _make_solid_from_pipe(path_wire, profile_wire):
    shell = path_wire.makePipeShell([profile_wire], True, True)
    try:
        return Part.makeSolid(shell)
    except Exception:
        return shell


def _fuse_shapes(shapes):
    if not shapes:
        raise ValueError("No shapes to fuse")
    out = shapes[0]
    for s in shapes[1:]:
        out = out.fuse(s)
    try:
        out = out.removeSplitter()
    except Exception:
        pass
    return out


def _make_transition_section_at_point(base_port, point):
    return _copy_port(base_port, position=point)


def _make_center_merge_port(port, center, inset):
    """
    Create a smaller 'inner' port very near the junction center.
    The section is kept identical; only the position is moved.
    """
    u = _port_direction(port)
    p = center - (u * (float(inset)))
    return _copy_port(port, position=p)


# --------------------------------------------------------------------------
# Elbow
# --------------------------------------------------------------------------


def build_elbow(context):
    ports = list(context.get("connected_ports", []) or [])
    props = dict(context.get("properties", {}) or {})

    if len(ports) != 2:
        raise ValueError("Elbow requires exactly 2 ports")

    # if not _profiles_compatible(ports[0], ports[1]):
    #     raise ValueError("Elbow requires compatible port profiles")

    # if not _same_section(ports[0], ports[1]):
    #     raise ValueError("Elbow currently requires equal end sections")

    p0 = _port_position(ports[0])
    p1 = _port_position(ports[1])
    u0 = _port_direction(ports[0])
    u1 = _port_direction(ports[1])

    theta = _angle_between(u0, u1)
    if theta <= 1e-6:
        raise ValueError("Elbow requires non-collinear directions")
    if abs(theta - math.pi) <= 1e-6:
        raise ValueError("Elbow cannot be built for opposite directions")

    radius = float(props.get("CenterlineRadius", 0.0) or 0.0)
    if radius <= 1e-6:
        radius = 1.5 * _section_size_hint(ports[0])

    # Calculate trim from geometry using u0, u1 and radius
    trim = radius / math.tan(theta / 2.0)
    
    # Find trimed segment mid points (Directions points away from the junction along the connected segment)
    s0 = p0 + (u0 * trim)
    s1 = p1 + (u1 * trim)
    
    # Find arc center and point on arc using bisector
    arc_center = arc_center_from_points_radius_dirs(s0, s1, u0, u1, radius)
    mid_point = arc_center - (u0 + u1).normalize() * float(radius)
    
    # Generate arc wire
    arc_edge = Part.Arc(s0, mid_point, s1).toShape()
    path_wire = Part.Wire([arc_edge])
    
    # Generate a sweep between ports
    sweep_port_0 = _copy_port(ports[0], position=s0, direction=u0)
    sweep_port_1 = _copy_port(ports[1], position=s1, direction=u1)
    shape = _make_multisection_sweep_between_ports(sweep_port_0, sweep_port_1, path_wire)

    return {
        "shape": shape,
        "connection_lengths": _build_records_from_port_lengths(
            [
                (ports[0], trim),
                (ports[1], trim),
            ]
        ),
    }


def build_circular_elbow_90(context):
    return build_elbow(context)


# --------------------------------------------------------------------------
# Transition
# --------------------------------------------------------------------------

def _safe_transition_length(length, d1, d2):
    L = float(length or 0.0)
    if L > 1e-6:
        return L
    return max(float(d1), float(d2), 1.0) * 1.5


def build_transition(context):
    ports = list(context.get("connected_ports", []) or [])
    props = dict(context.get("properties", {}) or {})

    if len(ports) != 2:
        raise ValueError("Transition requires exactly 2 ports")

    if not _profiles_compatible(ports[0], ports[1]):
        raise ValueError("Transition requires compatible port profiles")

    u1 = _port_direction(ports[0])
    u2 = _port_direction(ports[1])
    theta = _angle_between(u1, u2)

    if abs(theta - math.pi) > math.radians(10.0):
        raise ValueError("Transition requires near-opposite port directions")

    h1 = _section_size_hint(ports[0])
    h2 = _section_size_hint(ports[1])
    length = _safe_transition_length(props.get("TransitionLength", 0.0), h1, h2)

    trim1 = 0.5 * length
    trim2 = 0.5 * length

    p1 = _port_position(ports[0]) + (u1 * (trim1))
    p2 = _port_position(ports[1]) + (u2 * (trim2))

    port1 = _make_transition_section_at_point(ports[0], p1)
    port2 = _make_transition_section_at_point(ports[1], p2)

    shape = _make_loft_between_ports(port1, port2, solid=True, ruled=True)

    return {
        "shape": shape,
        "connection_lengths": _build_records_from_port_lengths(
            [
                (ports[0], trim1),
                (ports[1], trim2),
            ]
        ),
    }


def build_circular_transition(context):
    return build_transition(context)


# --------------------------------------------------------------------------
# Tee / Wye helpers
# --------------------------------------------------------------------------

def _find_run_pair(ports, angle_tol_deg=10.0):
    """
    Return indices (i, j, k) where i,j are the near-collinear run pair
    and k is the remaining branch port.
    """
    if len(ports) != 3:
        raise ValueError("Requires exactly 3 ports")

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
        raise ValueError("Could not identify run pair")

    return best


def _make_leg_to_center(port, center, trim_length, inner_inset=None):
    u = _port_direction(port)
    outer_pos = _port_position(port) + (u * (float(trim_length)))
    outer_port = _copy_port(port, position=outer_pos, direction=u)

    if inner_inset is None:
        inner_inset = max(0.05 * _section_size_hint(port), 1.0)

    inner_port = _make_center_merge_port(port, center, inner_inset)
    return _make_loft_between_ports(outer_port, inner_port, solid=True, ruled=True)


def _validate_profiles_for_junction(ports):
    if not ports:
        raise ValueError("No ports provided")

    base = _port_profile(ports[0])
    if not base:
        raise ValueError("Port profile is missing")

    for p in ports[1:]:
        if _port_profile(p) != base:
            raise ValueError("Mixed profiles are not yet supported for this junction")

    return base


# --------------------------------------------------------------------------
# Tee
# --------------------------------------------------------------------------

def build_tee(context):
    center = _center_from_context(context)
    ports = list(context.get("connected_ports", []) or [])
    props = dict(context.get("properties", {}) or {})

    if len(ports) != 3:
        raise ValueError("Tee requires exactly 3 ports")

    _validate_profiles_for_junction(ports)

    run_a_idx, run_b_idx, branch_idx = _find_run_pair(ports, angle_tol_deg=10.0)

    run_a = ports[run_a_idx]
    run_b = ports[run_b_idx]
    branch = ports[branch_idx]

    run_hint = max(_section_size_hint(run_a), _section_size_hint(run_b))
    branch_hint = _section_size_hint(branch)

    run_trim = _safe_trim(props.get("RunTrimLength", 0.0), 0.5 * run_hint)
    branch_trim = _safe_trim(props.get("BranchTrimLength", 0.0), 0.5 * branch_hint)
    inner_inset = float(props.get("CenterInset", 0.0) or 0.0)
    if inner_inset <= 1e-6:
        inner_inset = max(0.05 * max(run_hint, branch_hint), 1.0)

    run_leg_a = _make_leg_to_center(run_a, center, run_trim, inner_inset=inner_inset)
    run_leg_b = _make_leg_to_center(run_b, center, run_trim, inner_inset=inner_inset)
    branch_leg = _make_leg_to_center(branch, center, branch_trim, inner_inset=inner_inset)

    shape = _fuse_shapes([run_leg_a, run_leg_b, branch_leg])

    return {
        "shape": shape,
        "connection_lengths": _build_records_from_port_lengths(
            [
                (run_a, run_trim),
                (run_b, run_trim),
                (branch, branch_trim),
            ]
        ),
    }


def build_circular_tee(context):
    return build_tee(context)


# --------------------------------------------------------------------------
# Wye
# --------------------------------------------------------------------------

def build_wye(context):
    center = _center_from_context(context)
    ports = list(context.get("connected_ports", []) or [])
    props = dict(context.get("properties", {}) or {})

    if len(ports) != 3:
        raise ValueError("Wye requires exactly 3 ports")

    _validate_profiles_for_junction(ports)

    run_a_idx, run_b_idx, branch_idx = _find_run_pair(ports, angle_tol_deg=60.0)

    run_a = ports[run_a_idx]
    run_b = ports[run_b_idx]
    branch = ports[branch_idx]

    run_hint = max(_section_size_hint(run_a), _section_size_hint(run_b))
    branch_hint = _section_size_hint(branch)

    run_trim = _safe_trim(props.get("RunTrimLength", 0.0), 0.5 * run_hint)
    branch_trim = _safe_trim(props.get("BranchTrimLength", 0.0), 0.5 * branch_hint)
    inner_inset = float(props.get("CenterInset", 0.0) or 0.0)
    if inner_inset <= 1e-6:
        inner_inset = max(0.05 * max(run_hint, branch_hint), 1.0)

    run_leg_a = _make_leg_to_center(run_a, center, run_trim, inner_inset=inner_inset)
    run_leg_b = _make_leg_to_center(run_b, center, run_trim, inner_inset=inner_inset)
    branch_leg = _make_leg_to_center(branch, center, branch_trim, inner_inset=inner_inset)

    shape = _fuse_shapes([run_leg_a, run_leg_b, branch_leg])

    return {
        "shape": shape,
        "connection_lengths": _build_records_from_port_lengths(
            [
                (run_a, run_trim),
                (run_b, run_trim),
                (branch, branch_trim),
            ]
        ),
    }


def build_circular_wye(context):
    return build_wye(context)
    