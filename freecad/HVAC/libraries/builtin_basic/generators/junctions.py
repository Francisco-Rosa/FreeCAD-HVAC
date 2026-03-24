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

def _section_size_hint(api, port):
    profile = api.port_profile(port)
    if profile == "Circular":
        return max(api.port_diameter(port), 1.0)
    if profile == "Rectangular":
        return max(api.port_width(port), api.port_height(port), 1.0)
    return 1.0


def _safe_trim(value, fallback_value):
    v = float(value or 0.0)
    if v > 1e-6:
        return v
    return float(fallback_value)

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
    api = context.get("hvac_api", None)
    
    ports = list(context.get("connected_ports", []) or [])
    if not ports:
        raise ValueError("Marker requires at least one port")
    props = dict(context.get("properties", {}) or {})
    dia = float(props.get("MarkerDiameter", default_diameter) or default_diameter)
    center = api.port_position(ports[0])

    shape = _make_sphere(center, dia)
    trim_len = float(dia) * float(trim_factor)

    return {
        "shape": shape,
        "connection_lengths": api.build_trim_rec_from_context_uniform(context, trim_len),
    }


def build_terminal_marker(context):
    api = context.get("hvac_api", None)
    
    ports = list(context.get("connected_ports", []) or [])
    props = dict(context.get("properties", {}) or {})
    center = api.port_position(ports[0])

    dia = float(props.get("MarkerDiameter", 200.0) or 200.0)
    if dia <= 0:
        raise ValueError("Marker diameter must be > 0")

    trim_len = 0.0

    port_dir = api.port_direction(ports[0])

    zref = FreeCAD.Vector(0, 0, 1)
    xref = FreeCAD.Vector(1, 0, 0)
    if abs(port_dir.dot(zref)) < 0.95:
        ref = zref
    else:
        ref = xref
        
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
        "connection_lengths": api.build_trim_rec_from_context_uniform(context, trim_len),
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



# --------------------------------------------------------------------------
# Elbow
# --------------------------------------------------------------------------


def build_elbow(context):
    api = context.get("hvac_api", None)
    
    ports = list(context.get("connected_ports", []) or [])
    props = dict(context.get("properties", {}) or {})

    if len(ports) != 2:
        raise ValueError("Elbow requires exactly 2 ports")

    p0 = api.port_position(ports[0])
    p1 = api.port_position(ports[1])
    u0 = api.port_direction(ports[0])
    u1 = api.port_direction(ports[1])

    theta = api.angle_between(u0, u1)
    if theta <= 1e-6:
        raise ValueError("Elbow requires non-collinear directions")
    if abs(theta - math.pi) <= 1e-6:
        raise ValueError("Elbow cannot be built for opposite directions")

    radius = float(props.get("CenterlineRadius", 0.0) or 0.0)
    if radius <= 1e-6:
        radius = 1.5 * _section_size_hint(api, ports[0])

    # Symmetric elbow trim distance measured from the virtual corner
    trim = radius / math.tan(theta / 2.0)
    c1, c2 = api.closest_points_on_lines(p0, -u0, p1, -u1)
    
    # Tangency points on the two offset segment centerlines
    s0 = c1 + (u0 * trim)
    s1 = c2 + (u1 * trim)
    
    # Calculate trim distances from the tangency points to the original ports
    trim0 = max(0.0, (s0 - p0).dot(u0))
    trim1 = max(0.0, (s1 - p1).dot(u1))
    
    # Find arc center and point on arc using bisector
    arc_center = api.arc_center_from_points_tangents_radius(s0, s1, u0, u1, radius)
    bisector = u0 + u1
    if bisector.Length <= 1e-12:
        raise ValueError("Elbow bisector is undefined")
    bisector.normalize()
    mid_point = arc_center - bisector * float(radius)
    
    # Generate arc wire
    arc_edge = Part.Arc(s0, mid_point, s1).toShape()
    path_wire = Part.Wire([arc_edge])
    
    # Generate a sweep between ports
    sweep_port_0 = api.copy_port(ports[0], position=s0)
    sweep_port_1 = api.copy_port(ports[1], position=s1)
    wire_1 = api.make_section_wire_from_port(sweep_port_0)
    wire_2 = api.make_section_wire_from_port(sweep_port_1)
    shape = api.make_pipe_shell(path_wire, [wire_1, wire_2])
    
    return {
        "shape": shape,
        "connection_lengths": api.build_trim_rec_from_port_lengths(
            [
                (ports[0], trim0),
                (ports[1], trim1),
            ]
        ),
    }

# --------------------------------------------------------------------------
# Transition
# --------------------------------------------------------------------------

def _safe_transition_length(length, d1, d2):
    L = float(length or 0.0)
    if L > 1e-6:
        return L
    return max(float(d1), float(d2), 1.0) * 1.5


def build_transition(context):
    api = context.get("hvac_api", None)
    
    ports = list(context.get("connected_ports", []) or [])
    props = dict(context.get("properties", {}) or {})

    if len(ports) != 2:
        raise ValueError("Transition requires exactly 2 ports")

    u1 = api.port_direction(ports[0])
    u2 = api.port_direction(ports[1])
    theta = api.angle_between(u1, u2)

    if abs(theta - math.pi) > math.radians(10.0):
        raise ValueError("Transition requires near-opposite port directions")

    h1 = _section_size_hint(api, ports[0])
    h2 = _section_size_hint(api, ports[1])
    length = _safe_transition_length(props.get("TransitionLength", 0.0), h1, h2)

    trim1 = 0.5 * length
    trim2 = 0.5 * length

    p1 = api.port_position(ports[0]) + (u1 * (trim1))
    p2 = api.port_position(ports[1]) + (u2 * (trim2))

    port1 = api.copy_port(ports[0], position=p1)
    port2 = api.copy_port(ports[1], position=p2)
    wire1 = api.make_section_wire_from_port(port1)
    wire2 = api.make_section_wire_from_port(port2)
    
    shape = api.make_loft([wire1, wire2], solid=True, ruled=True)

    return {
        "shape": shape,
        "connection_lengths": api.build_trim_rec_from_port_lengths(
            [
                (ports[0], trim1),
                (ports[1], trim2),
            ]
        ),
    }


# --------------------------------------------------------------------------
# Tee / Wye helpers
# --------------------------------------------------------------------------

def _make_center_merge_port(api, port, center, inset):
    """
    Create a smaller 'inner' port very near the junction center.
    The section is kept identical; only the position is moved.
    """
    u = api.port_direction(port)
    p = center - (u * (float(inset)))
    return api.copy_port(port, position=p)
    
    
def _find_run_pair(api, ports, angle_tol_deg=10.0):
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
            u1 = api.port_direction(ports[i])
            u2 = api.port_direction(ports[j])
            theta = math.degrees(api.angle_between(u1, u2))
            err = abs(theta - 180.0)
            if best_err is None or err < best_err:
                k = [x for x in range(3) if x not in (i, j)][0]
                best = (i, j, k)
                best_err = err

    if best is None or best_err > angle_tol_deg:
        raise ValueError("Could not identify run pair")

    return best


def _make_leg_to_center(api, port, center, trim_length, inner_inset=None):
    u = api.port_direction(port)
    outer_pos = api.port_position(port) + (u * (float(trim_length)))
    outer_port = api.copy_port(port, position=outer_pos)

    if inner_inset is None:
        inner_inset = max(0.05 * _section_size_hint(api, port), 1.0)
    inner_port = _make_center_merge_port(api, port, center, inner_inset)
    
    outer_wire = api.make_section_wire_from_port(outer_port)
    inner_wire = api.make_section_wire_from_port(inner_port)
    shape = api.make_loft([outer_wire, inner_wire], solid=True, ruled=True)
    
    return shape


# --------------------------------------------------------------------------
# Tee
# --------------------------------------------------------------------------

def build_tee(context):
    api = context.get("hvac_api", None)
    
    ports = list(context.get("connected_ports", []) or [])
    props = dict(context.get("properties", {}) or {})

    if len(ports) != 3:
        raise ValueError("Tee requires exactly 3 ports")

    run_a_idx, run_b_idx, branch_idx = _find_run_pair(api, ports, angle_tol_deg=10.0)

    run_a = ports[run_a_idx]
    run_b = ports[run_b_idx]
    branch = ports[branch_idx]

    run_a_hint = _section_size_hint(api, run_a)
    run_b_hint = _section_size_hint(api, run_b)
    run_hint = max(run_a_hint, run_b_hint)
    branch_hint = _section_size_hint(api, branch)

    run_trim = _safe_trim(props.get("RunTrimLength", 0.0), 0.5 * run_hint)
    branch_trim = _safe_trim(props.get("BranchTrimLength", 0.0), 0.5 * branch_hint)
    inner_inset = float(props.get("CenterInset", 0.0) or 0.0)
    if inner_inset <= 1e-6:
        inner_inset = max(0.05 * max(run_hint, branch_hint), 1.0)
        
    # Find intersection/ closest point b/w main and branch
    c1a, c2a = api.closest_points_on_lines(api.port_position(run_a), api.port_direction(run_a), 
                                        api.port_position(branch), api.port_direction(branch))
    c1b, c2b = api.closest_points_on_lines(api.port_position(run_b), api.port_direction(run_b), 
                                        api.port_position(branch), api.port_direction(branch))
    center_main = (c1a + c1b) / 2
    center_branch = (c2a + c2b) / 2
    
    # Main branch
    angle = api.angle_between(api.port_direction(run_a), api.port_direction(branch))
    angle_sine = math.sin(angle)
    angle_cosine = math.cos(angle)
    if angle_sine > 0.1:
        scale = angle_cosine / angle_sine
    # adjust trim to account for branch duct size
    if run_a_hint >= run_b_hint:
        pos_a = c1a + api.port_direction(run_a) * (run_trim + branch_hint/2 + run_a_hint/2 * scale)
        pos_b = c1b + api.port_direction(run_b) * (run_trim + branch_hint/2 - run_b_hint/2 * scale)
    else:
        pos_a = c1a + api.port_direction(run_a) * (run_trim + branch_hint/2 - run_a_hint/2 * scale)
        pos_b = c1b + api.port_direction(run_b) * (run_trim + branch_hint/2 + run_b_hint/2 * scale)
    run_trim_a = (pos_a - api.port_position(run_a)).Length
    run_trim_b = (pos_b - api.port_position(run_b)).Length
    port_a = api.copy_port(run_a, position=pos_a)
    port_b = api.copy_port(run_b, position=pos_b)
    if run_a_hint >= run_b_hint:
        # mid_pos = api.port_position(port_a) - api.port_direction(port_a) * (run_trim + branch_hint)
        mid_pos = c1a - api.port_direction(port_a) * branch_hint
        port_mid = api.copy_port(port_a, position=mid_pos)
    else:
        # mid_pos = api.port_position(port_b) - api.port_direction(port_b) * (run_trim + branch_hint)
        mid_pos = c1b - api.port_direction(port_b) * branch_hint
        port_mid = api.copy_port(port_b, position=mid_pos)
    section_a = api.make_section_wire_from_port(port_a)
    section_b = api.make_section_wire_from_port(port_b)
    section_mid = api.make_section_wire_from_port(port_mid)
    leg_main = api.make_loft([section_a, section_mid, section_b])
    
    # Branch leg
    pos_branch = center_branch + api.port_direction(branch) * branch_trim
    pos_mid_branch = center_branch - api.port_direction(branch) * 0
    port_branch = api.copy_port(branch, position=pos_branch)
    port_mid_branch = api.copy_port(branch, position=pos_mid_branch)
    section_branch = api.make_section_wire_from_port(port_branch)
    section_mid_branch = api.make_section_wire_from_port(port_mid_branch)
    branch_leg = api.make_loft([section_branch, section_mid_branch])

    # Fuse shapes
    shape = api.fuse_shapes([leg_main, branch_leg])
    
    return {
        "shape": shape,
        "connection_lengths": api.build_trim_rec_from_port_lengths(
            [
                (run_a, run_trim_a),
                (run_b, run_trim_b),
                (branch, branch_trim),
            ]
        ),
    }


# --------------------------------------------------------------------------
# Wye
# --------------------------------------------------------------------------

def build_wye(context):
    api = context.get("hvac_api", None)
    
    center = api.center_from_context(context)
    ports = list(context.get("connected_ports", []) or [])
    props = dict(context.get("properties", {}) or {})

    if len(ports) != 3:
        raise ValueError("Wye requires exactly 3 ports")

    run_a_idx, run_b_idx, branch_idx = _find_run_pair(api, ports, angle_tol_deg=60.0)

    run_a = ports[run_a_idx]
    run_b = ports[run_b_idx]
    branch = ports[branch_idx]

    run_hint = max(_section_size_hint(api, run_a), _section_size_hint(api, run_b))
    branch_hint = _section_size_hint(api, branch)

    run_trim = _safe_trim(props.get("RunTrimLength", 0.0), 0.5 * run_hint)
    branch_trim = _safe_trim(props.get("BranchTrimLength", 0.0), 0.5 * branch_hint)
    inner_inset = float(props.get("CenterInset", 0.0) or 0.0)
    if inner_inset <= 1e-6:
        inner_inset = max(0.05 * max(run_hint, branch_hint), 1.0)

    run_leg_a = _make_leg_to_center(api, run_a, center, run_trim, inner_inset=inner_inset)
    run_leg_b = _make_leg_to_center(api, run_b, center, run_trim, inner_inset=inner_inset)
    branch_leg = _make_leg_to_center(api, branch, center, branch_trim, inner_inset=inner_inset)

    shape = api.fuse_shapes([run_leg_a, run_leg_b, branch_leg])

    return {
        "shape": shape,
        "connection_lengths": api.build_trim_rec_from_port_lengths(
            [
                (run_a, run_trim),
                (run_b, run_trim),
                (branch, branch_trim),
            ]
        ),
    }
