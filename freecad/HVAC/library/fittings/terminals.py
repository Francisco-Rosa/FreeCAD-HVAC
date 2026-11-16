# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the HVAC addon.

"""
End-of-duct fittings: terminal bodies (entries, exits, hoods, diffusers,
grilles, registers) and the duct closure (end cap).

Every terminal here is laid out the same way, measured from the node (the
drawn end of the duct line) back towards the duct:

    node | lip | body | neck | duct ...

- the *lip* is a short straight piece in the face section (a grille frame),
- the *body* goes from the face section to the duct section (a cone, a
  diffuser boot, a bellmouth),
- the *neck* is a straight collar in the duct's own section (TrimNeck).

The duct is trimmed back by the sum of the three. A fitting that has no lip
or no body simply leaves that part at zero length.
"""

import math

from ._common import _EPS, _finish, _fuse_into_structure, _positive, _props, _size, _trimmed
from .markers import _marker

# Number of sections used to draw the curve of a bellmouth lip.
_BELLMOUTH_STEPS = 5


def _number(props, name, default=0.0):
    """A numeric property, never negative; `default` when it is missing or empty."""
    value = props.get(name)
    return max(float(default if value in (None, "") else value), 0.0)


def _single_port(context):
    api = context["hvac_api"]
    ports = api.connected_ports(context)
    if len(ports) != 1:
        raise ValueError("A terminal fitting requires exactly one connected port")
    return ports[0]


def _neck_length(props, fallback=0.0):
    """TrimNeck as given; `fallback` when it is not set (used by fittings that are nothing but a neck)."""
    return _positive(props.get("TrimNeck"), fallback)


def _section(api, port):
    """(profile, section params) of a port, as plain values."""
    return api.port_profile(port), dict(api.port_section_params(port))


def _grown_section(profile, params, growth):
    """A section made larger by `growth` on every side."""
    if profile == "Circular":
        return profile, dict(params, Diameter=float(params["Diameter"]) + 2.0 * growth)
    return profile, dict(
        params, Width=float(params["Width"]) + 2.0 * growth, Height=float(params["Height"]) + 2.0 * growth
    )


def _scaled_section(profile, params, scale_width, scale_height):
    """A section scaled about its centre. A round section uses scale_width only."""
    if profile == "Circular":
        return profile, dict(params, Diameter=float(params["Diameter"]) * scale_width)
    return profile, dict(
        params, Width=float(params["Width"]) * scale_width, Height=float(params["Height"]) * scale_height
    )


def _half_angle_tan(angle_deg):
    """tan of half an included angle, kept finite for very flat cones."""
    half = math.radians(min(max(float(angle_deg), 0.0), 170.0)) / 2.0
    return math.tan(half)


def _terminal_layout(context, kind):
    """
    Sizes of one terminal fitting, as plain numbers:

        {"port", "neck", "body", "lip", "face": (profile, params) or None,
         "curved": bool, "cap": None or {"distance", "growth", "thickness"}}

    `face` is the section at the node end of the body (None = the duct's own
    section). `curved` asks for a bellmouth curve instead of a straight
    taper. `cap` is a weather-hood plate held clear of the opening.
    """
    api = context["hvac_api"]
    port = _single_port(context)
    props = _props(context)
    size = _size(api, port)
    profile, params = _section(api, port)
    layout = {"port": port, "neck": _neck_length(props), "body": 0.0, "lip": 0.0, "face": None, "curved": False}
    layout["cap"] = None
    layout["wall_flange"] = None
    layout["face_shift"] = (0.0, 0.0)
    # Extra outputs a kind may report: drop-down choices that suit the
    # geometry (GeometryResult.property_choices) and read-only values.
    layout["choices"] = None
    layout["computed"] = None

    if kind == "generic":
        # A plain length of the duct's own section, BodyLength long (plus the neck).
        layout["neck"] += _positive(props.get("BodyLength"), 0.35 * size)

    elif kind == "plain":
        # Nothing but a neck, so it must have some length.
        layout["neck"] = _neck_length(props, 0.25 * size)
        # Optional mounting flange: a ring plate flush with the opening, for a duct ending in a wall.
        width = _number(props, "WallFlangeWidth")
        if width > _EPS:
            layout["wall_flange"] = {"width": width, "thickness": max(_number(props, "WallFlangeThickness"), 0.5)}

    elif kind == "bellmouth":
        radius = _number(props, "LipRadius")
        if radius > _EPS:
            layout.update(body=radius, face=_grown_section(profile, params, radius), curved=True)
        else:
            layout["neck"] = _neck_length(props, 0.25 * size)

    elif kind == "cone":
        # A cone (or pyramid) of ConeLength opening at the included ConeAngle.
        length = _positive(props.get("ConeLength", props.get("HoodLength")), 0.5 * size)
        angle = _number(props, "ConeAngle", _number(props, "HoodAngle"))
        growth = min(length * _half_angle_tan(angle), 3.0 * size)
        if growth > _EPS:
            layout.update(body=length, face=_grown_section(profile, params, growth))
        else:
            layout["neck"] += length

    elif kind == "diffusing":
        # An exit that widens to AreaRatio times the duct area at the included ConeAngle.
        # A "Plane" diffuser widens one pair of sides only; any other widens all sides.
        ratio = max(_number(props, "AreaRatio", 1.0), 1.0)
        plane = str(props.get("DiffuserType", "") or "").strip().lower() == "plane" and profile != "Circular"
        scale_w, scale_h = (ratio, 1.0) if plane else (math.sqrt(ratio), math.sqrt(ratio))
        tan_half = _half_angle_tan(_number(props, "ConeAngle"))
        across = float(params["Diameter"]) if profile == "Circular" else float(params["Width"])
        growth = (scale_w - 1.0) * across / 2.0
        if growth > _EPS and tan_half > _EPS:
            layout.update(body=growth / tan_half, face=_scaled_section(profile, params, scale_w, scale_h))
        else:
            layout["neck"] = _neck_length(props, 0.25 * size)

    elif kind == "hood":
        # SMACNA 14-15 F / 14-16 A: the duct end flares at the included
        # HoodAngle over one duct size (0 = a straight end), and a conical
        # roof twice the duct size across, rising 0.3 x the duct size, stands
        # HoodHeight clear of the opening.
        layout["neck"] = _neck_length(props, 0.25 * size)
        growth = min(size * _half_angle_tan(_number(props, "HoodAngle")), 3.0 * size)
        if growth > _EPS:
            layout.update(body=size, face=_grown_section(profile, params, growth))
        height = _positive(props.get("HoodHeight"), 0.5 * size)
        layout["cap"] = {
            "distance": height,
            "growth": 0.5 * size,
            "rise": 0.3 * size,
            "thickness": max(0.01 * size, 2.0),
        }

    elif kind == "square":
        face = _positive(props.get("FaceSize"), 2.0 * size)
        layout.update(body=_positive(props.get("BodyLength"), 0.5 * size))
        layout["face"] = ("Rectangular", {"Width": face, "Height": face})

    elif kind == "round":
        face = _positive(props.get("FaceDiameter"), 2.0 * size)
        layout.update(body=_positive(props.get("BodyLength"), 0.5 * size))
        layout["face"] = ("Circular", {"Diameter": face})

    elif kind == "slot":
        length = _positive(props.get("SlotLength"), 4.0 * size)
        width = _positive(props.get("SlotWidth"), 0.5 * size)
        layout.update(body=_positive(props.get("BodyLength"), size))
        layout["face"] = ("Rectangular", {"Width": length, "Height": width})

    elif kind == "frame":
        # A grille or register: the duct section with a frame around it at the face.
        layout["neck"] = _neck_length(props, 0.25 * size)
        frame = _number(props, "FrameWidth")
        depth = _number(props, "FrameDepth")
        if frame > _EPS and depth > _EPS:
            layout.update(lip=depth, face=_grown_section(profile, params, frame))

    elif kind == "fan":
        # Where a duct meets its equipment: a collar, and a transition from
        # the fan outlet (the equipment port the end sits on) to the duct,
        # shaped as SMACNA 14-11 F to J draw it.
        layout["neck"] = _neck_length(props, 0.25 * size)
        # Step 1: the fan outlet, and the FanConnection choices that suit it.
        outlet = _fan_outlet(context, port)
        choices = _fan_connection_choices(port, profile, params, outlet)
        choice = str(props.get("FanConnection", "") or "None")
        if choice not in choices:
            # A choice that no longer suits the geometry builds as "None";
            # the property itself is set back to an offered one afterwards.
            choice = "None"
        layout["choices"] = {"FanConnection": choices}
        if outlet is not None:
            width, height = _extents(*outlet)
            layout["computed"] = {"FanOutletWidth": width, "FanOutletHeight": height}
        # Step 2: the transition from the outlet to the duct.
        shape = _fan_transition(context, props, choice.lower(), port, profile, params, outlet)
        if shape is not None:
            length, outlet_section, shift = shape
            layout.update(body=length, face=outlet_section, face_shift=(0.0, shift))

    else:
        raise ValueError("Unknown terminal kind '{}'".format(kind))
    return layout


# FanConnection choices that are a fan outlet transition, with the slope of
# the transition's top side (degrees, rising towards the duct); None =
# symmetric (top and bottom open equally, half the included angle each).
_FAN_TRANSITION_TOP = {
    "transition symmetric": None,
    "transition pyramidal": None,
    "transition asymmetric top level": 0.0,
    "transition asymmetric top 10 down": -10.0,
    "transition asymmetric top 10 up": 10.0,
}


# Every FanConnection choice, in the type-def's order.
_FAN_NONE = "None"
_FAN_CASING = "Discharge into casing"
_FAN_SYMMETRIC = "Transition symmetric"
_FAN_ASYMMETRIC = (
    "Transition asymmetric top level",
    "Transition asymmetric top 10 down",
    "Transition asymmetric top 10 up",
)
_FAN_PYRAMIDAL = "Transition pyramidal"

# Two sizes closer than this (mm, or this share of the larger) count as equal.
_SAME_SIZE_MM = 1.0
_SAME_SIZE_SHARE = 0.01


def _extents(profile, params):
    """(width, height) of a section; a round one is its diameter both ways."""
    if profile == "Circular":
        return float(params["Diameter"]), float(params["Diameter"])
    return float(params["Width"]), float(params["Height"])


def _same_size(a, b):
    return abs(a - b) <= max(_SAME_SIZE_MM, _SAME_SIZE_SHARE * max(a, b))


def _fan_outlet(context, port):
    """
    (profile, params) of the fan outlet: the equipment port the end is
    connected to (context "equipment_port"), as its marker gives it, laid
    out on the duct's own axes. None when the end is on no equipment port
    (or the port has no size).
    """
    api = context["hvac_api"]
    equipment_port = context.get("equipment_port")
    if not equipment_port:
        return None
    profile, params = _section(api, equipment_port)
    if profile == "Circular":
        return (profile, params) if float(params.get("Diameter", 0.0) or 0.0) > _EPS else None
    if float(params.get("Width", 0.0) or 0.0) <= _EPS or float(params.get("Height", 0.0) or 0.0) <= _EPS:
        return None
    # The port's width runs along its marker's X axis: turned across the duct's, swap them.
    axis = api.unit(api.port_direction(port))
    _placement, duct_x_axis, _y, _z = api.make_profile_frame(axis, api.port_profile_x_axis(port))
    port_x_axis = api.port_profile_x_axis(equipment_port)
    if port_x_axis is not None and abs(api.unit(port_x_axis).dot(duct_x_axis)) < 0.5:
        params = dict(params, Width=params["Height"], Height=params["Width"])
    return profile, params


def _fan_connection_choices(port, duct_profile, duct_params, outlet):
    """
    The FanConnection choices that suit this connection, in the type-def's
    order:

    - no fan outlet (the end is on no equipment port), or air flowing into
      the unit here (a fan connection is costed on the discharge only):
      "None" only;
    - otherwise "None" and "Discharge into casing", plus the transitions
      that fit the change from the outlet to the duct (SMACNA 14-11):
      * same size: no transition;
      * only the height changes: symmetric (sides straight) and the three
        asymmetric ones (their top side is set on the height);
      * only the width changes: symmetric (sides straight);
      * both change, or round to rectangular / oval: pyramidal.
    """
    if outlet is None:
        return [_FAN_NONE]
    # Air leaving the unit enters the duct system here: it flows out of this end node.
    if port.get("flow_into_junction") is True:
        return [_FAN_NONE]
    duct_width, duct_height = _extents(duct_profile, duct_params)
    outlet_width, outlet_height = _extents(*outlet)
    same_width = _same_size(duct_width, outlet_width)
    same_height = _same_size(duct_height, outlet_height)

    transitions = []
    if outlet[0] != duct_profile or (not same_width and not same_height):
        transitions = [_FAN_PYRAMIDAL]
    elif duct_profile != "Circular" and same_width and not same_height:
        transitions = [_FAN_SYMMETRIC] + list(_FAN_ASYMMETRIC)
    elif duct_profile != "Circular" and same_height and not same_width:
        transitions = [_FAN_SYMMETRIC]
    elif duct_profile == "Circular" and not same_width:
        transitions = [_FAN_PYRAMIDAL]
    offered = set([_FAN_NONE, _FAN_CASING] + transitions)
    order = [_FAN_NONE, _FAN_SYMMETRIC] + list(_FAN_ASYMMETRIC) + [_FAN_PYRAMIDAL, _FAN_CASING]
    return [choice for choice in order if choice in offered]


def _fan_transition(context, props, choice, port, profile, params, outlet):
    """
    (length, opening section (profile, params), the opening centre's shift
    along the section's height axis) of the transition from the fan outlet
    (_fan_outlet) to the duct, or None when there is none to draw (no
    outlet known, or it is the duct's own section). `choice` is the
    FanConnection choice in force, lower case.

    The transition opens at the included TransitionAngle. A fan outlet
    transition that is asymmetric keeps its top side level, or sloping 10
    degrees down or up towards the duct, and opens the whole angle at the
    bottom; every other one stays centred, top and bottom each opening half
    the angle. Width always changes symmetrically. A change of profile alone
    (a round port on a rectangular duct) is given half the duct's larger
    side, so the loft has room to turn.
    """
    if outlet is None:
        return None
    outlet_profile, outlet_params = outlet
    duct_width, duct_height = _extents(profile, params)
    outlet_width, outlet_height = _extents(outlet_profile, outlet_params)
    angle = math.radians(min(max(_number(props, "TransitionAngle", 20.0), 5.0), 150.0))
    rise_h = duct_height - outlet_height
    length_w = abs(duct_width - outlet_width) / (2.0 * math.tan(angle / 2.0))
    top = _FAN_TRANSITION_TOP.get(choice)
    if top is None:
        # Centred: top and bottom each open half the angle.
        length = max(abs(rise_h) / (2.0 * math.tan(angle / 2.0)), length_w)
        shift = 0.0
    else:
        # The top side keeps its slope; the bottom opens (or closes) the whole angle against it.
        top = math.radians(top)
        bottom = top - angle if rise_h >= 0.0 else top + angle
        length = max(abs(rise_h) / abs(math.tan(top) - math.tan(bottom)), length_w)
        # The outlet's top edge, from the duct axis: the duct's top less what the top side rises over the length.
        shift = duct_height / 2.0 - length * math.tan(top) - outlet_height / 2.0
    if outlet_profile != profile:
        length = max(length, 0.5 * max(duct_width, duct_height))
    if length <= _EPS:
        return None
    return length, (outlet_profile, outlet_params), shift


def _terminal_trim(layout):
    return layout["lip"] + layout["body"] + layout["neck"]


def _measure_terminal(context, kind):
    api = context["hvac_api"]
    layout = _terminal_layout(context, kind)
    return api.build_trim_rec_from_port_lengths([(layout["port"], _terminal_trim(layout))])


def _build_terminal(context, kind):
    """Build a terminal from its layout: lip, body and neck, each only if it has a length."""
    api = context["hvac_api"]
    layout = _terminal_layout(context, kind)
    port = layout["port"]
    lip, body, neck = layout["lip"], layout["body"], layout["neck"]
    axis = api.unit(api.port_direction(port))

    # Step 1: the two sections the fitting runs between.
    throat = _trimmed(api, port, lip + body)
    face_profile, face_params = layout["face"] or _section(api, port)

    duct_profile, duct_params = _section(api, port)
    _placement, x_axis, y_axis, _z_axis = api.make_profile_frame(axis, api.port_profile_x_axis(port))

    def round_to_match(centre, diameter, other_profile, other):
        # A round section about to be lofted to a rectangular or oval one:
        # drawn with a corner where each corner of the other section points,
        # in the same order, so the loft pairs them instead of twisting.
        width, height = float(other["Width"]), float(other["Height"])
        if other_profile == "Oval":
            # An oval's corners are where its straight sides end.
            width, height = (width - height, height) if width >= height else (width, height - width)
            if min(width, height) <= 1e-9:
                return api.make_circular_wire(centre, axis, diameter)
        return api.make_split_circular_wire(centre, x_axis, y_axis, diameter, width, height)

    shift_x, shift_y = layout["face_shift"]

    def face_at(distance, offset, for_loft=False):
        # The face section, `distance` from the node, grown by the wall offset
        # (and moved off the duct axis where the layout says, e.g. a fan outlet).
        _profile, grown = _grown_section(face_profile, face_params, offset)
        centre = api.port_position(port) + axis * distance + x_axis * shift_x + y_axis * shift_y
        if for_loft and face_profile == "Circular" and duct_profile in ("Rectangular", "Oval"):
            return round_to_match(centre, grown["Diameter"], duct_profile, duct_params)
        return api.make_profile(face_profile, grown, center=centre, direction=axis, profile_x_axis=x_axis)

    def throat_for_loft(offset):
        # The duct section at the throat, as the other end of the loft from the face.
        if duct_profile == "Circular" and face_profile in ("Rectangular", "Oval"):
            diameter = float(duct_params["Diameter"]) + 2.0 * offset
            return round_to_match(api.port_position(throat), diameter, face_profile, face_params)
        return api.profile_from_port(throat, offset)

    def bellmouth_sections(offset):
        # Sections along a quarter circle: square to the face at the node, tangent to the duct at the throat.
        radius = body
        sections = []
        for step in range(_BELLMOUTH_STEPS + 1):
            angle = (math.pi / 2.0) * step / _BELLMOUTH_STEPS
            growth = radius * (1.0 - math.sin(angle)) + offset
            distance = lip + radius * (1.0 - math.cos(angle))
            sections.append(api.profile_from_port(_trimmed(api, port, distance), growth))
        return sections

    # Step 2: the air space, grown outward by `offset`.
    def envelope(offset):
        pieces = []
        if lip > _EPS:
            # The outer lip runs on by the wall offset, so the step down to the duct gets a wall too.
            pieces.append(api.extrude(face_at(0.0, offset), axis * (lip + offset), solid=True))
        if body > _EPS and layout["curved"]:
            # A smooth loft through rectangular sections gives curved corner
            # surfaces that OCC cannot cut one from another reliably (the
            # wall comes out solid); a ruled loft through the same sections
            # gives flat facets that it can. Round sections stay smooth.
            ruled = api.port_profile(port) != "Circular"
            pieces.append(api.loft(bellmouth_sections(offset), solid=True, ruled=ruled))
        elif body > _EPS:
            pieces.append(api.loft([face_at(lip, offset, True), throat_for_loft(offset)], solid=True, ruled=True))
        if neck > _EPS:
            pieces.append(api.extrude(api.profile_from_port(throat, offset), axis * neck, solid=True))
        return pieces[0] if len(pieces) == 1 else api.fuse(*pieces)

    lengths = api.build_trim_rec_from_port_lengths([(port, _terminal_trim(layout))])
    result = _finish(context, envelope, lengths)
    if layout["choices"]:
        result["property_choices"] = layout["choices"]
    if layout["computed"]:
        result["computed_properties"] = dict(result.get("computed_properties") or {}, **layout["computed"])

    # Step 3: a weather hood's plate, standing clear of the opening on the far side of the node.
    wall_flange = layout["wall_flange"]
    if wall_flange:
        # The ring reaches from the outside of the duct wall to WallFlangeWidth beyond it.
        wall = sum(
            float(_props(context).get(getattr(ld, "thickness_property", None) or "", 0.0) or 0.0)
            for ld in context.get("construction_layers") or []
        )
        outer = api.extrude(
            api.profile_from_port(port, wall + wall_flange["width"]), axis * wall_flange["thickness"], solid=True
        )
        inner = api.extrude(api.profile_from_port(port, wall), axis * wall_flange["thickness"], solid=True)
        _fuse_into_structure(context, result, api.refine(outer.cut(inner)))

    cap = layout["cap"]
    if cap:
        # A conical (round) or pyramidal (rectangular, oval) roof of sheet
        # thickness: the roof solid less itself moved down by the thickness.
        outside = axis * -1.0
        base_centre = api.port_position(port) + outside * cap["distance"]
        base_profile, base_params = _grown_section(duct_profile, duct_params, cap["growth"])
        apex_profile, apex_params = _scaled_section(base_profile, base_params, 0.02, 0.02)
        base = api.make_profile(base_profile, base_params, center=base_centre, direction=axis, profile_x_axis=x_axis)
        apex = api.make_profile(
            apex_profile, apex_params, center=base_centre + outside * cap["rise"], direction=axis, profile_x_axis=x_axis
        )
        roof = api.loft([base, apex], solid=True, ruled=True)
        under = roof.copy()
        under.translate(axis * cap["thickness"])
        _fuse_into_structure(context, result, api.refine(roof.cut(under)))
    return result


def _pair(kind):
    """The (build, measure) functions of one terminal kind."""

    def build(context):
        return _build_terminal(context, kind)

    def measure(context):
        return _measure_terminal(context, kind)

    return build, measure


# Generic terminal body (diffuser/grille/register, fan connection, louver):
# a plain extrusion of the connected port's own section. A NeckSize such a
# type declares feeds its loss formula only, it is not a second profile.
build_terminal_body_generic, measure_terminal_body_generic = _pair("generic")

# Where a duct meets its equipment: a collar, with the fan outlet transition FanConnection asks for.
build_terminal_fan, measure_terminal_fan = _pair("fan")

# Entries and exits (SMACNA Tables 14-15 and 14-16).
build_terminal_plain, measure_terminal_plain = _pair("plain")
build_terminal_bellmouth, measure_terminal_bellmouth = _pair("bellmouth")
build_terminal_cone, measure_terminal_cone = _pair("cone")
build_terminal_diffusing, measure_terminal_diffusing = _pair("diffusing")
build_terminal_hood, measure_terminal_hood = _pair("hood")

# Air terminals: a boot from the duct to a square, round or slot face, and a framed grille.
build_terminal_square, measure_terminal_square = _pair("square")
build_terminal_round, measure_terminal_round = _pair("round")
build_terminal_slot, measure_terminal_slot = _pair("slot")
build_terminal_frame, measure_terminal_frame = _pair("frame")


def _duct_closure_thickness(context):
    return _positive(_props(context).get("PlateThickness"), 3.0)


def measure_duct_closure_generic(context):
    api = context["hvac_api"]
    ports = api.connected_ports(context)
    if not ports:
        return []
    return api.build_trim_rec_from_context_uniform(context, _duct_closure_thickness(context))


def build_duct_closure_generic(context):
    """A thin blanking plate/cap sealing off a single terminal port."""
    api = context["hvac_api"]
    ports = api.connected_ports(context)
    if not ports:
        return _marker(context, 150.0)
    p = ports[0]
    thickness = _duct_closure_thickness(context)
    shape = api.extrude(api.profile_from_port(p), api.port_direction(p) * thickness, solid=True)
    return api.single_layer(
        context, api.refine(shape), connection_lengths=api.build_trim_rec_from_context_uniform(context, thickness)
    )
