# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the HVAC addon.

"""
Inside detail drawn as construction features (see features.py): parts a
fitting's loss already counts but its body did not show. They never take
part in the wall booleans and follow ShowFeatures like flanges.

- `turning_vanes`: the vanes of a mitered 90 degree elbow (VaneDesign);
- `splitter_vanes`: the splitters of a radius elbow (SplitterVanes);
- `tap_damper`: a blade and shaft in the branch collar of a tap;
- `extractor_blades`: the scoop blades of an extractor tap, in the run;
- `filter_media`: a pleated media pack across a filter housing;
- `coil_block`: a coil's fin block and its two header connections.

Every piece is a plain extrusion or revolve; the result is a compound.
"""

import math
import re

from ._common import _layer_thickness, _min_bend_radius
from .features import _params
from .inline import _vav_box_layout


def _wall(context, params):
    return sum(_layer_thickness(layer_def, params) for layer_def in context.get("construction_layers") or [])


def _trim_of(ctx, port):
    """The trim the build reported for one port (0 when it reported none)."""
    for rec in getattr(ctx.result, "connection_lengths", None) or []:
        if rec.get("edge_key") == port.get("edge_key"):
            return float(rec["length"])
    return 0.0


def _plate(api, centre, normal, x_axis, width, height, thickness):
    """A flat plate `thickness` thick centred on `centre`, `width` along x_axis by `height` across it."""
    wire = api.make_profile(
        "Rectangular",
        {"Width": width, "Height": height},
        center=centre - normal * (thickness / 2.0),
        direction=normal,
        profile_x_axis=x_axis,
    )
    return api.extrude(wire, normal * thickness, solid=True)


def _cylinder(api, start, direction, length, diameter):
    wire = api.make_profile("Circular", {"Diameter": diameter}, center=start, direction=direction)
    return api.extrude(wire, api.unit(direction) * length, solid=True)


# ----------------------------------------------------------------------
# Elbow vanes.
# ----------------------------------------------------------------------


def _elbow_frame(api, ctx):
    """
    A two-port elbow's bend: corner (the node), the outward port directions,
    the bend axis, and the section's size in the bend plane (W) and across
    it (H). None for anything but a rectangular two-port bend.
    """
    ports = list(api.connected_ports(ctx.context))
    if len(ports) != 2 or api.port_profile(ports[0]) != "Rectangular":
        return None
    u0, u1 = api.unit(api.port_direction(ports[0])), api.unit(api.port_direction(ports[1]))
    in_plane = u1 - u0 * u1.dot(u0)
    if in_plane.Length <= api.EPS:
        return None
    in_plane = api.unit(in_plane)
    _placement, x_axis, y_axis, _z = api.make_profile_frame(u0, api.port_profile_x_axis(ports[0]))
    width, height = float(api.port_width(ports[0])), float(api.port_height(ports[0]))
    w = abs(x_axis.dot(in_plane)) * width + abs(y_axis.dot(in_plane)) * height
    h = abs(x_axis.dot(in_plane)) * height + abs(y_axis.dot(in_plane)) * width
    corner = api.center_from_context(ctx.context)
    return {"corner": corner, "u0": u0, "u1": u1, "normal": api.unit(u1.cross(u0)), "w": w, "h": h}


def _vane(api, centre, d0, d1, radius, height, thickness):
    """A curved vane: a thin strip `height` high on a circle of `radius` about `centre`, from direction d0 to d1."""
    axis = api.unit(d0.cross(d1))
    tangent = api.unit(axis.cross(d0))
    wire = api.make_profile(
        "Rectangular",
        {"Width": thickness, "Height": height},
        center=centre + d0 * radius,
        direction=tangent,
        profile_x_axis=d0,
    )
    return api.revolve(wire, (centre, axis), math.degrees(api.angle_between(d0, d1)), solid=True)


def _vane_design(text):
    """(vane radius, spacing, double) from a VaneDesign choice such as "Double R50 S38"."""
    found = re.match(r"\s*(single|double)\s+r(\d+(?:\.\d+)?)\s+s(\d+(?:\.\d+)?)", str(text or ""), re.IGNORECASE)
    if not found:
        return 50.0, 38.0, False
    return float(found.group(2)), float(found.group(3)), found.group(1).lower() == "double"


def turning_vanes(api, ctx):
    """
    The turning vanes of a mitered 90 degree elbow: quarter-circle vanes of
    the VaneDesign radius, spaced along the mitre from the outer corner to
    the inner one, each turning from one duct's direction into the other's.
    Double-thickness (airfoil) vanes are drawn three times as thick.
    """
    params = _params(ctx)
    f = _elbow_frame(api, ctx)
    if f is None:
        return None
    radius, spacing, double = _vane_design(params.get("VaneDesign"))
    u0, u1 = f["u0"], f["u1"]
    inward = api.unit(u0 + u1)
    # The mitre runs from the outer corner to the inner corner, both W/2 off each axis.
    outer = f["corner"] - (u0 + u1) * (f["w"] / 2.0)
    mitre_length = f["w"] * math.sqrt(2.0)
    pitch = spacing * math.sqrt(2.0)
    count = int((mitre_length - 2.0 * radius) // pitch) + 1
    if count < 1:
        return None
    used = (count - 1) * pitch
    thickness = max(0.8, 0.004 * f["w"]) * (3.0 if double else 1.0)
    height = f["h"] - 2.0 * max(1.0, 0.005 * f["h"])
    shapes = []
    for index in range(count):
        # The vane's middle sits on the mitre; its centre lies `radius` further in.
        on_mitre = outer + inward * ((mitre_length - used) / 2.0 + index * pitch)
        centre = on_mitre + inward * radius
        shapes.append(_vane(api, centre, u1 * -1.0, u0 * -1.0, radius, height, thickness))
    return api.compound(shapes)


def splitter_vanes(api, ctx):
    """
    The splitter vanes of a radius elbow: SplitterVanes concentric vanes,
    spaced evenly across the bend between the inside and the outside wall,
    each running the whole bend.
    """
    params = _params(ctx)
    count = int(float(params.get("SplitterVanes", 0) or 0))
    f = _elbow_frame(api, ctx)
    if f is None or count < 1:
        return None
    u0, u1 = f["u0"], f["u1"]
    turn = math.pi - api.angle_between(u0, u1)
    if turn <= 1.0e-6:
        return None
    radius = max(
        float(params.get("CenterlineRadius", 0.0) or 0.0), _min_bend_radius(f["w"], _wall(ctx.context, params))
    )
    inward = api.unit(u0 + u1)
    centre = f["corner"] + inward * (radius / math.cos(turn / 2.0))
    reach = radius * math.tan(turn / 2.0)
    d0 = api.unit(f["corner"] + u0 * reach - centre)
    d1 = api.unit(f["corner"] + u1 * reach - centre)
    thickness = max(0.8, 0.004 * f["w"])
    height = f["h"] - 2.0 * max(1.0, 0.005 * f["h"])
    inner = radius - f["w"] / 2.0
    shapes = [
        _vane(api, centre, d0, d1, inner + f["w"] * (index + 1) / (count + 1), height, thickness)
        for index in range(count)
    ]
    return api.compound(shapes)


# ----------------------------------------------------------------------
# Taps.
# ----------------------------------------------------------------------


def tap_damper(api, ctx):
    """
    A tap's damper: one blade, partly open (45 degrees), and its shaft, in
    the branch collar half a TapHeight in from the branch duct's end.
    """
    params = _params(ctx)
    try:
        _run_a, _run_b, branch = api.run_branch_ports(ctx.context)
    except Exception:
        return None
    trim = _trim_of(ctx, branch)
    if trim <= api.EPS:
        return None
    direction = api.unit(api.port_direction(branch))
    _placement, x_axis, y_axis, _z = api.make_profile_frame(direction, api.port_profile_x_axis(branch))
    section = dict(api.port_section_params(branch))
    if api.port_profile(branch) == "Circular":
        width = height = float(section["Diameter"])
    else:
        width, height = float(section["Width"]), float(section["Height"])
    clearance = max(1.0, 0.005 * max(width, height))
    thickness = max(1.5, 0.008 * max(width, height))
    # Half a TapHeight in from the branch end, but never so close that the tilted blade passes the end.
    reach = 0.5 * height * math.sin(math.radians(45.0)) + thickness + clearance
    tap = float(params.get("TapHeight", 0.0) or 0.0) or 0.5 * trim
    centre = api.port_position(branch) + direction * (trim - max(0.5 * min(tap, 0.5 * trim), reach))
    # The shaft runs along the section's x axis; the blade turns about it.
    normal = api.rotate_vector(direction, x_axis, math.radians(45.0))
    blade_section = {
        key: float(value) - 2.0 * clearance if key in ("Diameter", "Width", "Height") else value
        for key, value in section.items()
    }
    wire = api.make_profile(
        api.port_profile(branch),
        blade_section,
        center=centre - normal * (thickness / 2.0),
        direction=normal,
        profile_x_axis=x_axis,
    )
    blade = api.extrude(wire, normal * thickness, solid=True)
    shaft = _cylinder(api, centre - x_axis * (width / 2.0), x_axis, width, max(8.0, 0.025 * max(width, height)))
    return api.compound([blade, shaft])


def extractor_blades(api, ctx):
    """
    An extractor's scoop: three blades in the run under the branch opening,
    inclined 45 degrees so they face the oncoming air and turn it up into
    the branch.
    """
    try:
        run_a, run_b, branch = api.run_branch_ports(ctx.context)
    except Exception:
        return None
    upstream = next((port for port in (run_a, run_b) if port.get("flow_into_junction") is True), run_a)
    flow = api.unit(api.port_direction(upstream)) * -1.0
    branch_dir = api.unit(api.port_direction(branch))
    up = branch_dir - flow * branch_dir.dot(flow)
    if up.Length <= api.EPS:
        return None
    up = api.unit(up)
    across = api.unit(flow.cross(up))
    q_run, _q_branch = api.closest_points_on_lines(
        api.port_position(upstream), flow, api.port_position(branch), branch_dir
    )
    if q_run is None:
        q_run = api.center_from_context(ctx.context)
    _low, run_half = api.profile_projection_bounds(api.profile_from_port(api.copy_port(upstream, position=q_run)), up)
    run_half -= q_run.dot(up)
    opening = api.profile_from_port(api.copy_port(branch, position=q_run + up * run_half))
    low, high = api.profile_projection_bounds(opening, flow)
    span_low, span_high = api.profile_projection_bounds(opening, across)
    opening_length, opening_width = high - low, span_high - span_low
    if opening_length <= api.EPS or opening_width <= api.EPS:
        return None
    count = 3
    chord = min(0.6 * run_half, 1.4 * opening_length / count)
    thickness = max(1.5, 0.008 * opening_width)
    # Each blade rises from upstream to downstream (along flow + up), so it faces the oncoming air.
    normal = api.unit(up - flow)
    start = q_run + flow * (low - q_run.dot(flow))
    shapes = []
    for index in range(count):
        along = opening_length * (index + 0.5) / count
        centre = start + flow * along + up * (run_half - 0.4 * chord)
        shapes.append(_plate(api, centre, normal, across, opening_width, chord, thickness))
    return api.compound(shapes)


# ----------------------------------------------------------------------
# Filter and coil housings (the VAV box layout).
# ----------------------------------------------------------------------


def _housing(api, ctx):
    """Middle, axis, section axes and inside sizes of a rectangular housing built by inline.build_vav_box."""
    context = ctx.context
    try:
        ports, length, width, height, _trim = _vav_box_layout(context)
    except Exception:
        return None
    axis = api.unit(api.port_direction(ports[1]))
    middle = api.average_point([api.port_position(ports[0]), api.port_position(ports[1])])
    _placement, x_axis, y_axis, _z = api.make_profile_frame(axis, api.port_profile_x_axis(ports[1]))
    return {
        "middle": middle,
        "axis": axis,
        "x": x_axis,
        "y": y_axis,
        "length": length,
        "width": width,
        "height": height,
    }


def filter_media(api, ctx):
    """A pleated media pack across the housing: pleats about 50 mm apart, as deep as 40 % of the housing (at most 300 mm)."""
    h = _housing(api, ctx)
    if h is None:
        return None
    clearance = max(2.0, 0.01 * min(h["width"], h["height"]))
    width, height = h["width"] - 2.0 * clearance, h["height"] - 2.0 * clearance
    depth = min(0.4 * h["length"], 300.0)
    count = max(2, int(round(width / 50.0)))
    pitch = width / count
    thickness = 1.0
    shapes = []
    for index in range(count):
        # One pleat face: from one side of the pack to the other across one pitch, alternating.
        x_mid = -width / 2.0 + pitch * (index + 0.5)
        sign = 1.0 if index % 2 == 0 else -1.0
        along = api.unit(h["x"] * pitch + h["axis"] * (sign * depth))
        normal = api.unit(h["y"].cross(along))
        centre = h["middle"] + h["x"] * x_mid
        face_length = math.hypot(pitch, depth)
        shapes.append(_plate(api, centre, normal, along, face_length, height, thickness))
    return api.compound(shapes)


def coil_block(api, ctx):
    """
    A coil: the fin block filling the housing's section, a third of its
    length deep, and two header connections leaving its side along the
    section's x axis.
    """
    h = _housing(api, ctx)
    if h is None:
        return None
    clearance = max(2.0, 0.01 * min(h["width"], h["height"]))
    depth = h["length"] / 3.0
    start = h["middle"] - h["axis"] * (depth / 2.0)
    block = api.make_profile(
        "Rectangular",
        {"Width": h["width"] - 2.0 * clearance, "Height": h["height"] - 2.0 * clearance},
        center=start,
        direction=h["axis"],
        profile_x_axis=h["x"],
    )
    shapes = [api.extrude(block, h["axis"] * depth, solid=True)]
    pipe = max(15.0, 0.08 * h["height"])
    wall = _wall(ctx.context, _params(ctx))
    for sign in (1.0, -1.0):
        base = h["middle"] + h["y"] * (sign * h["height"] / 4.0) + h["x"] * (h["width"] / 2.0 - clearance)
        shapes.append(_cylinder(api, base, h["x"], clearance + wall + 100.0, pipe))
    return api.compound(shapes)
