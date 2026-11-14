# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the HVAC addon.

"""
Damper detail, drawn as construction features (see features.py) of an
inline damper type, so they never take part in the wall booleans:

- `damper_blades`: the blade(s) and their shafts inside the duct, at the
  damper's current position (DamperType, BladeAngle, BladeCount,
  GateOpening; a "Coefficient" damper is drawn as a single blade);
- `damper_operator`: what turns them, outside the duct wall: a hand
  quadrant (a quarter plate and a lever that shows the blade position) or
  an actuator (a box on a bracket), or nothing (Operator "None").

Orientation: OperatorSide picks the side of the duct the shaft comes out of
(Right / Left along the section's width axis, Top / Bottom along its height
axis), so the blades turn about that axis; OperatorRotation turns the
quadrant or actuator about the shaft in quarter turns.

Every piece is a plain extrusion (or one revolve) and the result is a
compound: no booleans, except one clip of multi-blade or gate plates to a
round or oval section.
"""

import math

from ._common import _layer_thickness
from .features import _params

_SIDES = {"Right": ("x", 1.0), "Left": ("x", -1.0), "Top": ("y", 1.0), "Bottom": ("y", -1.0)}
_MULTI_BLADE = ("Parallel blade", "Opposed blade")


def _number(params, name, default):
    value = params.get(name)
    try:
        return float(default if value in (None, "") else value)
    except (TypeError, ValueError):
        return float(default)


def _quarter_turns(params, name):
    """An enumeration of "0" / "90" / "180" / "270" as radians."""
    try:
        degrees = float(str(params.get(name) or "0").strip().rstrip("°"))
    except ValueError:
        degrees = 0.0
    return math.radians(degrees)


def _frame(api, ctx, params):
    """
    Where the damper is and how it is turned, as plain values:
    centre, duct axis, section axes x / y, profile, section, and for the
    shaft: its outward direction (towards the operator), the in-section axis
    across it, its half length inside the duct and the extent across it.
    """
    context = ctx.context
    ports = list(api.connected_ports(context))
    if not ports:
        return None
    port = ports[0]
    centre = api.average_point([api.port_position(p) for p in ports])
    axis = api.unit(api.port_direction(port))
    _placement, x_axis, y_axis, _z = api.make_profile_frame(axis, api.port_profile_x_axis(port))
    profile = api.port_profile(port)
    section = dict(api.port_section_params(port))
    if profile == "Circular":
        width = height = float(section["Diameter"])
    else:
        width, height = float(section["Width"]), float(section["Height"])
    name, sign = _SIDES.get(str(params.get("OperatorSide") or "Right"), ("x", 1.0))
    along_x = name == "x"
    size = max(width, height)
    wall = sum(_layer_thickness(layer_def, params) for layer_def in context.get("construction_layers") or [])
    return {
        "centre": centre,
        "axis": axis,
        "x": x_axis,
        "y": y_axis,
        "profile": profile,
        "section": section,
        "shaft": (x_axis if along_x else y_axis) * sign,
        "across": y_axis if along_x else x_axis,
        "shaft_is_x": along_x,
        "shaft_half": (width if along_x else height) / 2.0,
        "across_extent": height if along_x else width,
        "size": size,
        "wall": wall,
        "clearance": max(1.0, 0.005 * size),
        "blade_thickness": max(1.5, 0.008 * size),
        "shaft_diameter": max(8.0, 0.025 * size),
    }


def _blade_angle(params):
    """Blade position in degrees from fully open (0 open, 90 closed); a gate's travel maps onto the same scale."""
    if str(params.get("DamperType") or "") == "Gate":
        opening = min(max(_number(params, "GateOpening", 1.0), 0.0), 1.0)
        return 90.0 * (1.0 - opening)
    return min(max(_number(params, "BladeAngle", 0.0), 0.0), 90.0)


def _layout(f, params):
    """[(blade centre, turn sign), ...] and the index of the driven blade (the one the operator turns)."""
    kind = str(params.get("DamperType") or "")
    count = max(1, int(_number(params, "BladeCount", 1))) if kind in _MULTI_BLADE else 1
    chord = f["across_extent"] / count
    blades = []
    for index in range(count):
        offset = -f["across_extent"] / 2.0 + chord * (index + 0.5)
        sign = -1.0 if kind == "Opposed blade" and index % 2 else 1.0
        blades.append((f["centre"] + f["across"] * offset, sign))
    return blades, count // 2, chord


def _cylinder(api, start, direction, length, diameter):
    wire = api.make_profile("Circular", {"Diameter": diameter}, center=start, direction=direction)
    return api.extrude(wire, api.unit(direction) * length, solid=True)


def _section_prism(api, f, depth):
    """The duct's own section as a slab `depth` thick, centred on the damper: to clip plates to a round or oval duct."""
    start = f["centre"] - f["axis"] * (depth / 2.0)
    wire = api.make_profile(f["profile"], f["section"], center=start, direction=f["axis"], profile_x_axis=f["x"])
    return api.extrude(wire, f["axis"] * depth, solid=True)


def damper_blades(api, ctx):
    """The damper's blade(s) and shafts inside the duct, at the current blade angle or gate opening."""
    params = _params(ctx)
    f = _frame(api, ctx, params)
    if f is None:
        return None
    kind = str(params.get("DamperType") or "")
    angle = _blade_angle(params)
    thickness = f["blade_thickness"] * (3.0 if kind == "Butterfly airfoil" else 1.0)
    clearance = f["clearance"]
    shapes = []
    clip = False

    if kind == "Gate":
        # A plate sliding across the section: the closed part covers (1 - opening) of the extent.
        closed = f["across_extent"] * angle / 90.0
        if closed > clearance:
            centre = f["centre"] + f["across"] * (-f["across_extent"] / 2.0 + closed / 2.0)
            plate = api.make_profile(
                "Rectangular",
                {"Width": 2.0 * f["shaft_half"], "Height": closed},
                center=centre - f["axis"] * (thickness / 2.0),
                direction=f["axis"],
                profile_x_axis=f["shaft"],
            )
            shapes.append(api.extrude(plate, f["axis"] * thickness, solid=True))
            clip = f["profile"] != "Rectangular"
        blades = []
    else:
        blades, _driven, chord = _layout(f, params)
        turn = math.radians(90.0 - angle)
        for centre, sign in blades:
            # The blade's normal: the duct axis turned about the shaft (open: the blade lies along the flow).
            normal = api.rotate_vector(f["axis"], f["shaft"], sign * turn)
            start = centre - normal * (thickness / 2.0)
            if len(blades) == 1:
                # One blade is the duct section itself, less a running clearance.
                section = {
                    key: float(value) - 2.0 * clearance if key in ("Diameter", "Width", "Height") else value
                    for key, value in f["section"].items()
                }
                x_axis = f["x"] if f["shaft_is_x"] else api.rotate_vector(f["x"], f["shaft"], sign * turn)
                wire = api.make_profile(f["profile"], section, center=start, direction=normal, profile_x_axis=x_axis)
            else:
                wire = api.make_profile(
                    "Rectangular",
                    {"Width": 2.0 * (f["shaft_half"] - clearance), "Height": chord - clearance},
                    center=start,
                    direction=normal,
                    profile_x_axis=f["shaft"],
                )
                clip = f["profile"] != "Rectangular"
            shapes.append(api.extrude(wire, normal * thickness, solid=True))

    if clip and shapes:
        shapes = [api.common(api.compound(shapes), _section_prism(api, f, 4.0 * f["across_extent"]))]

    # The shafts, wall to wall (the operator's own stub carries the driven one outside).
    for centre, _sign in blades:
        start = centre - f["shaft"] * f["shaft_half"]
        shapes.append(_cylinder(api, start, f["shaft"], 2.0 * f["shaft_half"], f["shaft_diameter"]))
    return api.compound(shapes) if shapes else None


def damper_operator(api, ctx):
    """A hand quadrant or an actuator on the driven shaft, outside the duct wall (None for Operator "None")."""
    params = _params(ctx)
    kind = str(params.get("Operator") or "Hand quadrant")
    if kind == "None":
        return None
    f = _frame(api, ctx, params)
    if f is None:
        return None
    shaft, axis = f["shaft"], f["axis"]
    if str(params.get("DamperType") or "") == "Gate":
        driven_centre = f["centre"]
    else:
        blades, driven, _chord = _layout(f, params)
        driven_centre = blades[driven][0]
    # The outer face of the wall where the shaft comes out, and the operator's own plane axes.
    base = driven_centre + shaft * (f["shaft_half"] + f["wall"])
    u = api.rotate_vector(axis, shaft, _quarter_turns(params, "OperatorRotation"))
    scale = min(max(f["size"] / 400.0, 0.7), 1.5)
    ds = f["shaft_diameter"]
    shapes = []

    if kind == "Actuator":
        length, width, height = 220.0 * scale, 110.0 * scale, 90.0 * scale
        standoff = 30.0 * scale
        # Bracket plate on the duct, a clamp round the shaft, and the actuator body (shaft 20 % from one end).
        bracket = api.make_profile(
            "Rectangular", {"Width": length + 20.0, "Height": width}, center=base + u * (0.3 * length), direction=shaft,
            profile_x_axis=u,
        )  # fmt: skip
        shapes.append(api.extrude(bracket, shaft * 3.0, solid=True))
        shapes.append(_cylinder(api, base - shaft * f["wall"], shaft, f["wall"] + standoff, ds))
        shapes.append(_cylinder(api, base + shaft * 3.0, shaft, standoff - 3.0, 3.0 * ds))
        body = api.make_profile(
            "Rectangular", {"Width": length, "Height": width}, center=base + shaft * standoff + u * (0.3 * length),
            direction=shaft, profile_x_axis=u,
        )  # fmt: skip
        shapes.append(api.extrude(body, shaft * height, solid=True))
    else:
        radius = 110.0 * scale
        plate_thickness = 3.0
        standoff = 6.0
        # The quadrant: a quarter ring plate swept from u towards v (open towards closed).
        ring = api.make_rectangular_wire(
            base + shaft * (standoff + plate_thickness / 2.0) + u * ((radius + 2.0 * ds) / 2.0),
            u,
            shaft,
            radius - 2.0 * ds,
            plate_thickness,
        )
        shapes.append(api.revolve(ring, (base, shaft), 90.0, solid=True))
        # The lever shows the blade position: along u fully open, along v fully closed.
        lever_dir = api.rotate_vector(u, shaft, math.radians(_blade_angle(params)))
        lever_height = standoff + plate_thickness + 1.0
        lever_length = 1.2 * radius
        lever = api.make_profile(
            "Rectangular",
            {"Width": 18.0 * scale, "Height": 6.0},
            center=base + shaft * (lever_height + 3.0) - lever_dir * (0.15 * radius),
            direction=lever_dir,
            profile_x_axis=shaft.cross(lever_dir),
        )
        shapes.append(api.extrude(lever, lever_dir * lever_length, solid=True))
        tip = base + lever_dir * (lever_length - 0.15 * radius - 10.0) + shaft * (lever_height + 6.0)
        shapes.append(_cylinder(api, tip, shaft, 25.0 * scale, 16.0 * scale))
        shapes.append(_cylinder(api, base - shaft * f["wall"], shaft, f["wall"] + lever_height + 10.0, ds))
        shapes.append(_cylinder(api, base + shaft * (lever_height + 6.0), shaft, 8.0, 2.5 * ds))
    return api.compound(shapes)
