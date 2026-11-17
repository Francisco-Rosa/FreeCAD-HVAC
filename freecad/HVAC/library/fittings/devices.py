# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the HVAC addon.

"""
Inline devices on a straight run, beyond the damper and the VAV box
(inline.py): silencer, fire damper, access door, flexible connector. The
filter and the coil are rectangular housings and use the VAV box builder
(inline.build_vav_box).

Bodies:

- silencer: a casing in the duct's own section, grown all round by
  CasingGrowth (the acoustic lining), with a collar at each end;
- fire damper, access door: a plain sleeve, with their detail drawn as
  construction features (`fire_damper_frame`, `access_door`), so it never
  takes part in the wall booleans;
- flexible connector: a sleeve whose middle bulges out by Bulge.
"""

from ._common import _finish, _layer_thickness, _positive, _props, _size, _trimmed
from .features import _params
from .inline import _inline, measure_inline

_SIDES = {"Right": ("x", 1.0), "Left": ("x", -1.0), "Top": ("y", 1.0), "Bottom": ("y", -1.0)}


def _two_ports(api, context):
    ports = list(api.connected_ports(context))
    if len(ports) != 2:
        raise ValueError(f"Expected 2 connected ports, got {len(ports)}")
    return ports


# ----------------------------------------------------------------------
# Silencer: a lined casing in the duct's own section.
# ----------------------------------------------------------------------


def _silencer_layout(context):
    """
    Sizes of a silencer. The casing is centred on the node and follows the
    duct's own section, grown all round by CasingGrowth; each collar runs
    from its end of the casing out to the duct. Sizes left at 0 are taken
    from the larger duct.
    """
    api = context["hvac_api"]
    ports = _two_ports(api, context)
    p = _props(context)
    size = max(_size(api, ports[0]), _size(api, ports[1]))
    length = _positive(p.get("BodyLength"), max(3.0 * size, 900.0))
    growth = _positive(p.get("CasingGrowth"), max(50.0, 0.25 * size))
    collar = max(float(p.get("CollarLength", 0.0) or 0.0), 0.0) or 0.25 * size
    return ports, length, growth, length / 2.0 + collar


def measure_silencer(context):
    api = context["hvac_api"]
    ports, _length, _growth, trim = _silencer_layout(context)
    return api.build_trim_rec_from_port_lengths([(ports[0], trim), (ports[1], trim)])


def build_silencer(context):
    """Silencer: a casing in the section of the larger duct, grown by CasingGrowth, with a collar at each end."""
    api = context["hvac_api"]
    ports, length, growth, trim = _silencer_layout(context)
    larger = max(ports, key=lambda port: _size(api, port))
    axis = api.unit(api.port_direction(ports[1]))
    middle = api.average_point([api.port_position(ports[0]), api.port_position(ports[1])])
    ends = [_trimmed(api, port, trim) for port in ports]

    def envelope(offset):
        # The casing grows by the wall offset all round, its ends included, so the end walls get built.
        start = api.copy_port(larger, position=middle - axis * (length / 2.0 + offset), direction=axis)
        casing = api.offset_profile(api.profile_from_port(start, offset), growth)
        shape = api.extrude(casing, axis * (length + 2.0 * offset), solid=True)
        # Each collar runs from the duct end back into the casing (to its middle, so the two always fuse).
        for port, end in zip(ports, ends):
            back = api.unit(api.port_direction(port)) * -1.0
            shape = api.fuse(shape, api.extrude(api.profile_from_port(end, offset), back * trim, solid=True))
        return shape

    lengths = api.build_trim_rec_from_port_lengths([(ports[0], trim), (ports[1], trim)])
    return _finish(context, envelope, lengths)


# ----------------------------------------------------------------------
# Fire damper and access door: a sleeve, detail as features.
# ----------------------------------------------------------------------

# (factor of the duct size, minimum) for the default BodyLength of each sleeve.
_FIRE_DAMPER_LENGTH = (0.5, 300.0)
_ACCESS_DOOR_LENGTH = (1.0, 400.0)


def measure_fire_damper(context):
    return measure_inline(context, *_FIRE_DAMPER_LENGTH)


def build_fire_damper(context):
    return _inline(context, *_FIRE_DAMPER_LENGTH)


def measure_access_door(context):
    return measure_inline(context, *_ACCESS_DOOR_LENGTH)


def build_access_door(context):
    return _inline(context, *_ACCESS_DOOR_LENGTH)


def _number(params, name, default):
    value = params.get(name)
    try:
        value = float(default if value in (None, "") else value)
    except (TypeError, ValueError):
        value = float(default)
    return value if value > 0.0 else float(default)


def _frame(api, ctx, params):
    """Centre, duct axis, section axes, section, sleeve length and wall build-up of a sleeve device."""
    context = ctx.context
    ports = list(api.connected_ports(context))
    if len(ports) != 2:
        return None
    port = ports[0]
    centre = api.average_point([api.port_position(p) for p in ports])
    axis = api.unit(api.port_direction(port))
    _placement, x_axis, y_axis, _z = api.make_profile_frame(axis, api.port_profile_x_axis(port))
    section = dict(api.port_section_params(port))
    if api.port_profile(port) == "Circular":
        width = height = float(section["Diameter"])
    else:
        width, height = float(section["Width"]), float(section["Height"])
    # The sleeve's real length: twice the trim the build reported at each end.
    records = list(getattr(ctx.result, "connection_lengths", None) or [])
    trims = [float(rec["length"]) for rec in records]
    wall = sum(_layer_thickness(layer_def, params) for layer_def in context.get("construction_layers") or [])
    return {
        "port": port,
        "centre": centre,
        "axis": axis,
        "x": x_axis,
        "y": y_axis,
        "width": width,
        "height": height,
        "size": max(width, height),
        "length": 2.0 * min(trims) if trims else None,
        "wall": wall,
    }


def fire_damper_frame(api, ctx):
    """
    A fire damper's retaining frame and curtain housing, outside the sleeve:
    a plate frame round the duct, FrameWidth out from the wall and
    FrameDepth along the duct, and the folded curtain as a block in the
    frame above the duct (a curtain held out of the air stream).
    """
    params = _params(ctx)
    f = _frame(api, ctx, params)
    if f is None:
        return None
    frame_width = _number(params, "FrameWidth", 40.0)
    depth = _number(params, "FrameDepth", 50.0)
    start = f["centre"] - f["axis"] * (depth / 2.0)
    duct = api.make_profile(
        api.port_profile(f["port"]),
        f["port"]["section_params"],
        center=start,
        direction=f["axis"],
        profile_x_axis=f["x"],
    )
    inner = api.offset_profile(duct, f["wall"])
    outer = api.offset_profile(duct, f["wall"] + frame_width)
    # The frame's middle is one cut (the duct and its wall pass through it).
    frame = api.cut(
        api.extrude(outer, f["axis"] * depth, solid=True), api.extrude(inner, f["axis"] * depth, solid=True)
    )
    # The curtain pack: as wide as the duct, filling most of the frame above it.
    pack_height = 0.8 * frame_width
    pack_centre = start + f["y"] * (f["height"] / 2.0 + f["wall"] + 0.1 * frame_width + pack_height / 2.0)
    pack = api.make_profile(
        "Rectangular",
        {"Width": f["width"], "Height": pack_height},
        center=pack_centre,
        direction=f["axis"],
        profile_x_axis=f["x"],
    )
    return api.compound([frame, api.extrude(pack, f["axis"] * depth, solid=True)])


def access_door(api, ctx):
    """
    An access door on one side of the sleeve (DoorSide): a panel DoorWidth
    along the duct by DoorHeight across it, DoorThickness thick, standing on
    the outside of the wall, with a handle. Sizes left at 0 fill the sleeve
    less 50 mm at each end, and three quarters of the face across.
    """
    params = _params(ctx)
    f = _frame(api, ctx, params)
    if f is None:
        return None
    name, sign = _SIDES.get(str(params.get("DoorSide") or "Right"), ("x", 1.0))
    normal = (f["x"] if name == "x" else f["y"]) * sign
    across = f["y"] if name == "x" else f["x"]
    face_half = (f["width"] if name == "x" else f["height"]) / 2.0
    face_across = f["height"] if name == "x" else f["width"]
    length = f["length"] or _number(params, "BodyLength", max(f["size"], 400.0))
    door_width = min(_number(params, "DoorWidth", max(length - 100.0, 0.5 * length)), length)
    door_height = min(_number(params, "DoorHeight", 0.75 * face_across), face_across)
    thickness = _number(params, "DoorThickness", 20.0)

    base = f["centre"] + normal * (face_half + f["wall"])
    panel = api.make_profile(
        "Rectangular",
        {"Width": door_width, "Height": door_height},
        center=base,
        direction=normal,
        profile_x_axis=f["axis"],
    )
    shapes = [api.extrude(panel, normal * thickness, solid=True)]
    # The handle: a short bar across the middle of the panel.
    handle_start = base + normal * thickness - across * (0.15 * door_height)
    grip = api.make_profile(
        "Circular", {"Diameter": max(8.0, 0.1 * thickness + 6.0)}, center=handle_start, direction=across
    )
    shapes.append(api.extrude(grip, across * (0.3 * door_height), solid=True))
    return api.compound(shapes)


# ----------------------------------------------------------------------
# Flexible connector: a sleeve that bulges out in the middle.
# ----------------------------------------------------------------------


def _flex_layout(context):
    api = context["hvac_api"]
    ports = _two_ports(api, context)
    p = _props(context)
    size = max(_size(api, ports[0]), _size(api, ports[1]))
    length = _positive(p.get("BodyLength"), 150.0)
    bulge = _positive(p.get("Bulge"), max(5.0, 0.03 * size))
    return ports, length / 2.0, bulge


def measure_flex_connector(context):
    api = context["hvac_api"]
    ports, trim, _bulge = _flex_layout(context)
    return api.build_trim_rec_from_port_lengths([(ports[0], trim), (ports[1], trim)])


def build_flex_connector(context):
    """Flexible connector: a ruled loft from one duct end to a section grown by Bulge at the middle, then to the other."""
    api = context["hvac_api"]
    ports, trim, bulge = _flex_layout(context)
    a, b = _trimmed(api, ports[0], trim), _trimmed(api, ports[1], trim)
    middle = api.copy_port(b, position=api.average_point([api.port_position(a), api.port_position(b)]))

    def envelope(offset):
        sections = [
            api.profile_from_port(a, offset),
            api.offset_profile(api.profile_from_port(middle, offset), bulge),
            api.profile_from_port(b, offset),
        ]
        return api.loft(sections, solid=True, ruled=True)

    lengths = api.build_trim_rec_from_port_lengths([(ports[0], trim), (ports[1], trim)])
    return _finish(context, envelope, lengths)
