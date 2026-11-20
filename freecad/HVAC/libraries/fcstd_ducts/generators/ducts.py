# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the HVAC addon.

"""
Ducts, radius elbows and transitions built from the parametric FreeCAD-library
duct models (HVAC/Ducts, Francisco Rosa, CC-BY 3.0), through the FCStd-template
primitive `HVACLibraryAPI.shape_from_fcstd`.

Every template (see tools/build_fcstd_duct_templates.py) is one duct from
opening 1 to opening 2 along a path that starts at the origin:

- a straight path along +X (`Axis.Length`), or
- an arc starting along +Y with its centre on -X (`Axis.Radius`,
  `Axis.LastAngle`),

with a "Port0" marker at the start (local +Z out of the duct, local +X along
the opening's width; for an arc that is away from the arc's centre) and a
"Result" compound of two solids: the duct wall and its insulation.

So each build here works out three things and lets the template do the rest:

1. which template, and its opening sizes (the VarSet parameters);
2. the path length, or radius and angle;
3. where opening 1 sits in the model, as a port: position, outward direction
   and width direction. The loader places the template on that port.

Flanges are not taken from the models: they are the library's shared
`transverse_flange` feature, as in every HVAC library.
"""

import math

# The opening parameters of each template, opening 1 then opening 2, by the
# kind of opening: "circle" (a diameter), "oval" (a diameter and the straight
# length between the two arcs), "rect" (width and height).
_OPENINGS = {
    "Duct_linear_circular_complete": (("circle", "Duct_Diameter1"), ("circle", "Duct_Diameter2")),
    "Duct_curved_circular_complete": (("circle", "Duct_Diameter1"), ("circle", "Duct_Diameter2")),
    "Duct_linear_rectangular_complete": (("rect", "Duct_Opening1"), ("rect", "Duct_Opening2")),
    "Duct_curved_rectangular_complete": (("rect", "Duct_Opening1"), ("rect", "Duct_Opening2")),
    "Duct_linear_oval_complete": (("oval", "Duct_Opening1"), ("oval", "Duct_Opening2")),
    "Duct_curved_oval_complete": (("oval", "Duct_Opening1"), ("oval", "Duct_Opening2")),
    "Duct_linear_rectangular_circular_complete": (("rect", "Duct_Opening1"), ("circle_named", "Duct_Opening2")),
    "Duct_linear_rectangular_oval_complete": (("rect", "Duct_Opening1"), ("oval", "Duct_Opening2")),
    "Duct_linear_circular_oval_complete": (("oval", "Duct_Opening1"), ("circle_named", "Duct_Opening2")),
}

# Straight template for a transition, by (profile at opening 1, profile at opening 2).
_TRANSITIONS = {
    ("Circular", "Circular"): "Duct_linear_circular_complete",
    ("Rectangular", "Rectangular"): "Duct_linear_rectangular_complete",
    ("Oval", "Oval"): "Duct_linear_oval_complete",
    ("Rectangular", "Circular"): "Duct_linear_rectangular_circular_complete",
    ("Rectangular", "Oval"): "Duct_linear_rectangular_oval_complete",
    ("Oval", "Circular"): "Duct_linear_circular_oval_complete",
}

_STRAIGHT = {
    "Circular": "Duct_linear_circular_complete",
    "Rectangular": "Duct_linear_rectangular_complete",
    "Oval": "Duct_linear_oval_complete",
}
_CURVED = {
    "Circular": "Duct_curved_circular_complete",
    "Rectangular": "Duct_curved_rectangular_complete",
    "Oval": "Duct_curved_oval_complete",
}

# An insulation solid always comes out of the template; with no insulation
# this thickness is used and the solid dropped.
_DUMMY_INSULATION = 1.0
_MIN_SHEET = 0.1
_MIN_OVAL_FLAT = 0.5  # mm


def _props(context):
    return dict(context.get("properties") or {})


def _num(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _section(profile, values):
    """(width, height) of a section along its own x and y; a circle is its diameter both ways."""
    if profile == "Circular":
        d = _num(values.get("Diameter"))
        return d, d
    return _num(values.get("Width")), _num(values.get("Height"))


def _opening_params(template, index, profile, values, swap=False):
    """
    The template parameters of one opening. `swap` exchanges width and
    height (the opening is turned a quarter turn relative to the template's
    width direction).
    """
    kind, key = _OPENINGS[template][index]
    width, height = _section(profile, values)
    if swap:
        width, height = height, width
    if kind == "circle":
        return {key: width}
    if kind == "circle_named":
        return {key + "_diameter": width}
    if kind == "rect":
        return {key + "_width": width, key + "_height": height}
    # A flat oval: two half circles of the smaller size joined by straight
    # sides. The model's oval sketches fail with no straight side at all (an
    # oval with Width = Height), so the sides are at least _MIN_OVAL_FLAT long.
    flat = max(abs(width - height), _MIN_OVAL_FLAT)
    return {key + "_diameter": min(width, height), key + "_distance_between_arcs": flat}


def _oval_turned(profile, values):
    """True when a flat oval is taller than wide: the template's flat sides run along its width."""
    if profile != "Oval":
        return False
    width, height = _section(profile, values)
    return height > width


def _layer_ids(context):
    """(wall, insulation, outer jacket) layer ids from the type's construction layers, picked by role; None if absent."""
    wall = insulation = jacket = None
    for layer in context.get("construction_layers") or []:
        roles = set(getattr(layer, "roles", []) or [])
        if wall is None and "structural_shell" in roles:
            wall = layer.id
        elif insulation is None and "thermal_insulation" in roles:
            insulation = layer.id
        elif jacket is None and "outer_jacket" in roles:
            jacket = layer.id
    return wall or "casing", insulation, jacket


def _common_params(props):
    insulation = _num(props.get("InsulationThickness"))
    return {
        "Duct_Sheet_thickness": max(_num(props.get("Thickness"), 0.8), _MIN_SHEET),
        "Insulation_Thickness": insulation if insulation > 0.0 else _DUMMY_INSULATION,
    }


def _build(context, template, port0, params, connection_lengths=None):
    """
    Build `template` placed on `port0` (opening 1) and return the layered
    result: the wall on the wall layer, the insulation on the insulation
    layer when the type has one and its thickness is above zero.
    """
    api = context["hvac_api"]
    props = _props(context)
    path = api.resolve_library_file(context, "models/{}.FCStd".format(template))

    # The loader places the template's Port0 on the first connected port.
    placed = dict(context)
    placed["connected_ports"] = [port0]
    all_params = _common_params(props)
    all_params.update(params)
    shape = api.shape_from_fcstd(path, placed, params=all_params, result_object="Result", port_names=["Port0"])

    # Two solids (wall, insulation), or three for the flexible duct (inner
    # wall, insulation, outer jacket). Each wraps the one before, so size
    # tells them apart.
    solids = sorted(shape.Solids, key=lambda s: s.BoundBox.DiagonalLength)
    if len(solids) not in (2, 3):
        raise ValueError("Template '{}' built {} solids instead of 2 or 3".format(template, len(solids)))

    wall_id, insulation_id, jacket_id = _layer_ids(context)
    layers = {wall_id: {"shape": solids[0]}}
    insulated = _num(props.get("InsulationThickness")) > 0.0
    if insulation_id and insulated:
        layers[insulation_id] = {"shape": solids[1]}
    # A jacket only exists over insulation.
    if jacket_id and insulated and len(solids) == 3:
        layers[jacket_id] = {"shape": solids[2]}
    return {"layers": layers, "connection_lengths": list(connection_lengths or [])}


def _check_oval_in_plane(api, profile, values, direction, preferred_x, outward):
    """
    A flat oval can only follow a bend with its flat sides in the plane of
    the bend: the template draws it that way. Raise when its long side
    stands across that plane instead.
    """
    if profile != "Oval":
        return
    width, height = _section(profile, values)
    if abs(width - height) <= 1e-6:
        return
    _placement, x_axis, y_axis, _z = api.make_profile_frame(direction, preferred_x)
    long_side = x_axis if width > height else y_axis
    if abs(long_side.dot(outward)) < 0.7:
        raise ValueError(
            "This library bends a flat oval only with its flat sides in the plane of the bend; "
            "turn the duct's Width/Height (or its profile x axis) to bend it the other way"
        )


def _width_axis(api, direction, preferred_x, turned):
    """The width direction of an opening facing `direction`, a quarter turn round when `turned`."""
    _placement, x_axis, y_axis, _z = api.make_profile_frame(direction, preferred_x)
    return y_axis if turned else x_axis


# ----------------------------------------------------------------------------
# Segments
# ----------------------------------------------------------------------------


def _segment(context, profile):
    api = context["hvac_api"]
    props = _props(context)
    start = api.vec(context["start_point"])
    end = api.vec(context["end_point"])
    path = context.get("path_edge")
    turned = _oval_turned(profile, props)

    # A curved segment follows its arc; anything else is straight.
    curve = getattr(path, "Curve", None) if path is not None else None
    if curve is not None and hasattr(curve, "Radius") and hasattr(curve, "Center"):
        radius = float(curve.Radius)
        angle = float(path.Length) / radius
        tangent = api.unit(context.get("start_direction") or (end - start))
        outward = api.unit(start - api.vec(curve.Center))
        # The template's width lies in the plane of the bend; a rectangle whose
        # width stands across that plane is passed turned a quarter. A flat
        # oval keeps its flat sides in the plane of the bend.
        across = False
        x_axis = context.get("profile_x_axis")
        if profile == "Rectangular" and x_axis is not None:
            across = abs(api.unit(x_axis).dot(outward)) < 0.7
        _check_oval_in_plane(api, profile, props, tangent * -1.0, x_axis, outward)
        template = _CURVED[profile]
        port0 = {"position": start, "direction": tangent * -1.0, "profile_x_axis": outward}
        params = {"Axis.Radius": radius, "Axis.LastAngle": math.degrees(angle)}
        for index in (0, 1):
            params.update(_opening_params(template, index, profile, props, swap=across))
        return _build(context, template, port0, params)

    length = (end - start).Length
    # A straight path is its own chord; anything else (a spline) has no template.
    if path is not None and abs(float(path.Length) - length) > 1e-3 * max(length, 1.0):
        raise ValueError("This library builds curved ducts on arcs only, not on splines")
    if length <= 1e-6:
        raise ValueError("A duct needs a length above zero")
    direction = api.unit(end - start)
    template = _STRAIGHT[profile]
    port0 = {
        "position": start,
        "direction": direction * -1.0,
        "profile_x_axis": _width_axis(api, direction * -1.0, context.get("profile_x_axis"), turned),
    }
    params = {"Axis.Length": length}
    for index in (0, 1):
        params.update(_opening_params(template, index, profile, props, swap=turned))
    return _build(context, template, port0, params)


def build_circular_duct(context):
    return _segment(context, "Circular")


def build_rectangular_duct(context):
    return _segment(context, "Rectangular")


def build_oval_duct(context):
    return _segment(context, "Oval")


# ----------------------------------------------------------------------------
# Radius elbows
# ----------------------------------------------------------------------------


def _elbow_layout(context):
    """
    The two ports, the arc route between them (HVACLibraryAPI.make_elbow_path)
    and the template parameters. One calculation for both build_elbow() and
    measure_elbow(), so the trims always match the shape.
    """
    api = context["hvac_api"]
    props = _props(context)
    ports = api.connected_ports(context)
    if len(ports) != 2:
        raise ValueError("An elbow needs 2 connected ports, got {}".format(len(ports)))
    profile = api.port_profile(ports[0])
    if profile not in _CURVED:
        raise ValueError("No elbow template for profile '{}'".format(profile))
    u0, u1 = api.port_direction(ports[0]), api.port_direction(ports[1])
    sections = [api.port_section_params(p) for p in ports]

    # The arc bends towards port 1: its centre lies off port 0's axis on that side.
    toward = u1 - u0 * u0.dot(u1)
    if toward.Length <= 1e-9:
        raise ValueError("An elbow needs two ports at an angle")
    outward = api.unit(toward) * -1.0

    # Which way a rectangle's width lies: in the plane of the bend (as the
    # template draws it) or across it. A flat oval keeps its flat sides in
    # the plane of the bend.
    across = False
    x0 = api.port_profile_x_axis(ports[0])
    if profile == "Rectangular" and x0 is not None:
        across = abs(api.unit(x0).dot(outward)) < 0.7
    _check_oval_in_plane(api, profile, sections[0], u0, x0, outward)
    in_plane = max(
        max(_section(profile, s)) if profile == "Oval" else _section(profile, s)[1 if across else 0] for s in sections
    )

    # Centreline radius: the type's, or 1.5 times the size in the plane of the
    # bend; never so small that the inner wall folds over itself.
    insulation = _num(props.get("InsulationThickness"))
    smallest = 0.5 * in_plane + max(_num(props.get("Thickness"), 0.8), _MIN_SHEET) + max(insulation, 0.0) + 1.0
    radius = max(_num(props.get("CenterlineRadius")) or 1.5 * in_plane, smallest)
    route = api.make_elbow_path(ports[0], ports[1], radius)

    template = _CURVED[profile]
    sweep = math.pi - api.angle_between(u0, u1)
    params = {"Axis.Radius": radius, "Axis.LastAngle": math.degrees(sweep)}
    for index in (0, 1):
        params.update(_opening_params(template, index, profile, sections[index], swap=across))
    port0 = {"position": api.port_position(route["ports"][0]), "direction": u0, "profile_x_axis": outward}
    lengths = api.build_trim_rec_from_port_lengths(
        [(ports[0], route["trim_lengths"][0]), (ports[1], route["trim_lengths"][1])]
    )
    return template, port0, params, lengths


def build_elbow(context):
    template, port0, params, lengths = _elbow_layout(context)
    return _build(context, template, port0, params, lengths)


def measure_elbow(context):
    return _elbow_layout(context)[3]


# ----------------------------------------------------------------------------
# Transitions
# ----------------------------------------------------------------------------


# Parameters that move opening 2 sideways, per straight template. In the
# template's own frame "horizontal" moves it along -X (the width axis of
# Port0) and "vertical" along -Y. The round-to-round model has the
# parameters but nothing uses them, so it cannot be offset; the oval model
# spells its parameter "positon".
_OFFSET_KEYS = {
    "Duct_linear_rectangular_complete": ("Duct_Opening2_horizontal_position", "Duct_Opening2_vertical_position"),
    "Duct_linear_oval_complete": ("Duct_Opening2_horizontal_positon", "Duct_Opening2_vertical_position"),
    "Duct_linear_rectangular_circular_complete": (
        "Duct_Opening2_horizontal_position",
        "Duct_Opening2_vertical_position",
    ),
    "Duct_linear_rectangular_oval_complete": ("Duct_Opening2_horizontal_position", "Duct_Opening2_vertical_position"),
    "Duct_linear_circular_oval_complete": ("Duct_Opening2_horizontal_position", "Duct_Opening2_vertical_position"),
}

_DEFAULT_JOINT_LENGTH = 50.0


def _same_section(profiles, sections):
    """True when both ends have the same profile and size (a plain joint)."""
    if profiles[0] != profiles[1]:
        return False
    a, b = _section(profiles[0], sections[0]), _section(profiles[1], sections[1])
    return abs(a[0] - b[0]) <= 0.5 and abs(a[1] - b[1]) <= 0.5


def _straight_layout(context, kind):
    """
    Template, opening-1 port, parameters and trims of a straight two-port
    fitting built on a straight template, one calculation for build and
    measure. `kind`:

    - "transition": a concentric, eccentric or offset transition, length
      TransitionLength (0: long enough for a 30 degree included angle);
    - "straight": a duct-to-duct joint, a short sleeve of `Length` when both
      ends match, else a transition;
    - "offset": two parallel ducts displaced sideways, length OffsetLength
      (0: long enough for a 30 degree slope).

    The two ports must face opposite ways. Any sideways displacement between
    them moves opening 2 (the templates' opening 2 position parameters).
    """
    api = context["hvac_api"]
    props = _props(context)
    ports = api.connected_ports(context)
    if len(ports) != 2:
        raise ValueError("A straight fitting needs 2 connected ports, got {}".format(len(ports)))

    # Step 1: which template; opening 1 of a mixed template is the rectangle, else the oval.
    order = [0, 1]
    profiles = (api.port_profile(ports[0]), api.port_profile(ports[1]))
    if profiles not in _TRANSITIONS:
        order = [1, 0]
        profiles = (profiles[1], profiles[0])
    if profiles not in _TRANSITIONS:
        raise ValueError("No straight template from {} to {}".format(*profiles))
    first, second = ports[order[0]], ports[order[1]]
    template = _TRANSITIONS[profiles]
    sections = [api.port_section_params(first), api.port_section_params(second)]
    u0, u1 = api.port_direction(first), api.port_direction(second)
    if u0.dot(u1) > -0.999:
        raise ValueError("The two ducts must run in a straight line or parallel to build this fitting")

    # Step 2: the sideways displacement of opening 2 from opening 1's axis.
    p0, p1 = api.port_position(first), api.port_position(second)
    lateral = (p1 - p0) - u0 * (p1 - p0).dot(u0)
    offset = lateral.Length

    # Step 3: the length.
    sizes = [max(_section(profiles[i], sections[i])) for i in (0, 1)]
    if kind == "straight" and _same_section(profiles, sections) and offset <= 0.5:
        length = _num(props.get("Length")) or _DEFAULT_JOINT_LENGTH
    elif kind == "offset":
        length = _num(props.get("OffsetLength"))
        if length <= 0.0:
            length = max(150.0, offset / math.tan(math.radians(30.0)))
    else:
        length = _num(props.get("TransitionLength"))
        if length <= 0.0:
            length = max(150.0, abs(sizes[0] - sizes[1]) / (2.0 * math.tan(math.radians(15.0))))
    half = 0.5 * length

    # Step 4: opening 1 as the port the template is placed on.
    turned = _oval_turned(profiles[0], sections[0])
    x_axis = _width_axis(api, u0, api.port_profile_x_axis(first), turned)
    port0 = {"position": p0 + u0 * half, "direction": u0, "profile_x_axis": x_axis}
    params = {"Axis.Length": length}
    for index in (0, 1):
        params.update(_opening_params(template, index, profiles[index], sections[index], swap=turned))
    if offset > 0.5:
        keys = _OFFSET_KEYS.get(template)
        if keys is None:
            raise ValueError("The round-to-round duct model cannot offset its ends; use another library here")
        y_axis = u0.cross(x_axis)
        params[keys[0]] = -lateral.dot(x_axis)
        params[keys[1]] = -lateral.dot(y_axis)
    lengths = api.build_trim_rec_from_port_lengths([(ports[0], half), (ports[1], half)])
    return template, port0, params, lengths


def build_transition(context):
    template, port0, params, lengths = _straight_layout(context, "transition")
    return _build(context, template, port0, params, lengths)


def measure_transition(context):
    return _straight_layout(context, "transition")[3]


def build_straight(context):
    template, port0, params, lengths = _straight_layout(context, "straight")
    return _build(context, template, port0, params, lengths)


def measure_straight(context):
    return _straight_layout(context, "straight")[3]


def build_offset(context):
    template, port0, params, lengths = _straight_layout(context, "offset")
    return _build(context, template, port0, params, lengths)


def measure_offset(context):
    return _straight_layout(context, "offset")[3]


# ----------------------------------------------------------------------------
# Flexible duct
# ----------------------------------------------------------------------------

_FLEX = "Duct_flex_complete"
# The flexible duct template sits in world coordinates: it is placed on a port
# at the origin facing +Z, which is where its Port0 is, so it does not move.
_IDENTITY_PORT = {"position": (0.0, 0.0, 0.0), "direction": (0.0, 0.0, 1.0), "profile_x_axis": (1.0, 0.0, 0.0)}
_AXIS_LENGTH = 100.0  # length of each opening's axis line, mm


def _rotate(v, axis, angle):
    """`v` turned by `angle` about the unit vector `axis` (Rodrigues' formula)."""
    c, s = math.cos(angle), math.sin(angle)
    return v * c + axis.cross(v) * s + axis * (axis.dot(v) * (1.0 - c))


def _arc_beziers(api, path, start, tangent):
    """Cubic Bezier control points of an arc path, one piece per quarter turn or less."""
    centre = api.vec(path.Curve.Center)
    radius = float(path.Curve.Radius)
    sweep = float(path.Length) / radius
    r0 = start - centre
    normal = api.unit(r0.cross(tangent))
    pieces = max(1, int(math.ceil(sweep / (0.5 * math.pi) - 1e-9)))
    step = sweep / pieces
    handle = 4.0 / 3.0 * math.tan(step / 4.0) * radius
    points = [start]
    for i in range(pieces):
        r_a, r_b = _rotate(r0, normal, i * step), _rotate(r0, normal, (i + 1) * step)
        t_a, t_b = api.unit(normal.cross(r_a)), api.unit(normal.cross(r_b))
        p_a, p_b = centre + r_a, centre + r_b
        points += [p_a + t_a * handle, p_b - t_b * handle, p_b]
    return 3, points


def _flex_path(api, context):
    """
    (degree, points) of the Draft Bezier curve the duct follows, from its
    start to its end: a straight cubic for a straight duct, quarter-turn
    cubics for an arc, and the spline's own Bezier pieces for a spline.
    """
    start = api.vec(context["start_point"])
    end = api.vec(context["end_point"])
    path = context.get("path_edge")
    chord = (end - start).Length
    if chord <= 1e-6:
        raise ValueError("A duct needs a length above zero")
    if path is None or abs(float(path.Length) - chord) <= 1e-3 * max(chord, 1.0):
        return 3, [start + (end - start) * (i / 3.0) for i in range(4)]

    curve = path.Curve
    if hasattr(curve, "Radius") and hasattr(curve, "Center"):
        tangent = api.unit(context.get("start_direction") or (end - start))
        return _arc_beziers(api, path, start, tangent)
    if not hasattr(curve, "toBezier"):
        raise ValueError("The flexible duct follows lines, arcs and splines only")

    # A spline: its Bezier pieces between the trimmed ends, joined end to end.
    spline = curve.copy()
    first, last = float(path.FirstParameter), float(path.LastParameter)
    if abs(first - spline.FirstParameter) > 1e-9 or abs(last - spline.LastParameter) > 1e-9:
        spline.segment(first, last)
    if spline.isRational():
        raise ValueError("The flexible duct cannot follow a rational spline")
    pieces = spline.toBezier()
    degree = max(int(piece.Degree) for piece in pieces)
    for piece in pieces:
        if int(piece.Degree) < degree:
            piece.increase(degree)
    points = [api.vec(p) for p in pieces[0].getPoles()]
    for piece in pieces[1:]:
        points += [api.vec(p) for p in piece.getPoles()[1:]]
    if (points[0] - start).Length > (points[-1] - start).Length:
        points.reverse()
    return degree, points


def build_flex_duct(context):
    """A round flexible duct along the segment's path: inner wall, insulation and outer jacket."""
    api = context["hvac_api"]
    props = _props(context)
    degree, points = _flex_path(api, context)
    diameter = _num(props.get("Diameter"))
    start_tangent = api.unit(points[1] - points[0])
    end_tangent = api.unit(points[-1] - points[-2])
    params = {
        "Duct_Opening1_diameter": diameter,
        "Duct_Opening2_diameter": diameter,
        "Duct_Opening2_horizontal_position": 0.0,
        "Duct_Opening2_vertical_position": 0.0,
        # Each opening stands square to the path, on an axis line along the path's own tangent.
        "Opening1_axis.Points": [points[0], points[0] + start_tangent * _AXIS_LENGTH],
        "Opening2_axis.Points": [points[-1], points[-1] + end_tangent * _AXIS_LENGTH],
        "Axis.Degree": degree,
        "Axis.Points": points,
    }
    port = {key: api.vec(value) for key, value in _IDENTITY_PORT.items()}
    return _build(context, _FLEX, port, params)
