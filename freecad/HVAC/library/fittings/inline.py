# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the HVAC addon.

"""
Inline devices: a body sitting between two collinear ports (damper, obstruction, VAV box).
"""

from ._common import _finish, _fuse_into_structure, _loft, _positive, _props, _size, _trimmed


def _inline_layout(context, factor, minimum):
    api = context["hvac_api"]
    ports = list(api.connected_ports(context))
    if len(ports) != 2:
        raise ValueError(f"Expected 2 connected ports, got {len(ports)}")
    p = _props(context)
    size = max(_size(api, ports[0]), _size(api, ports[1]))
    requested = p.get("BodyLength", p.get("DeviceLength", p.get("Length")))
    length = _positive(requested, max(minimum, factor * size))
    trim = length / 2.0
    return ports, trim


def measure_inline(context, factor, minimum):
    api = context["hvac_api"]
    ports, trim = _inline_layout(context, factor, minimum)
    return api.build_trim_rec_from_port_lengths([(ports[0], trim), (ports[1], trim)])


def _inline(context, factor, minimum):
    api = context["hvac_api"]
    ports, trim = _inline_layout(context, factor, minimum)
    a, b = _trimmed(api, ports[0], trim), _trimmed(api, ports[1], trim)

    def envelope(offset):
        return _loft(api, [a, b], offset, ruled=True)

    lengths = api.build_trim_rec_from_port_lengths([(ports[0], trim), (ports[1], trim)])
    return _finish(context, envelope, lengths)


def build_damper_generic(context):
    return _inline(context, 0.5, 100.0)


def measure_damper_generic(context):
    return measure_inline(context, 0.5, 100.0)


def build_vav_generic(context):
    return _inline(context, 1.0, 300.0)


def measure_vav_generic(context):
    return measure_inline(context, 1.0, 300.0)


# ----------------------------------------------------------------------
# Obstruction: a round bar (a pipe, a rod) crossing the duct.
# ----------------------------------------------------------------------


def measure_obstruction_generic(context):
    return measure_inline(context, 0.5, 100.0)


def build_obstruction_generic(context):
    """
    A short length of duct with a round bar across it. The bar runs along
    the section's own x axis (the width of a rectangular duct) and is
    shifted from the centreline by OffsetFromCentre along the y axis. It
    is made long enough to pass through the walls on both sides.
    """
    api = context["hvac_api"]
    result = _inline(context, 0.5, 100.0)
    ports = list(api.connected_ports(context))
    p = _props(context)
    diameter = float(p.get("ObstructionDiameter", 0.0) or 0.0)
    if diameter <= 0.0:
        return result

    # Step 1: the duct section's own frame at the middle of the fitting.
    port = ports[0]
    _placement, x_axis, y_axis, _z_axis = api.make_profile_frame(
        api.port_direction(port), api.port_profile_x_axis(port)
    )
    middle = api.average_point([api.port_position(ports[0]), api.port_position(ports[1])])
    offset = float(p.get("OffsetFromCentre", 0.0) or 0.0)

    # Step 2: how long the bar has to be to reach from wall to wall.
    profile = api.profile_from_port(api.copy_port(port, position=middle))
    low, high = api.profile_projection_bounds(profile, x_axis)
    span = high - low
    if api.port_profile(port) == "Circular":
        half = span / 2.0
        if abs(offset) >= half:
            raise ValueError(
                "The obstruction lies outside the duct: OffsetFromCentre must be below {:.1f} mm".format(half)
            )
        span = 2.0 * (half**2 - offset**2) ** 0.5
    # Run it a little past the inside face, so it joins the wall rather than just touching it.
    reach = span / 2.0 + max(0.02 * span, 2.0)

    # Step 3: the bar itself, fused onto the duct wall.
    start = middle + y_axis * offset - x_axis * reach
    bar_profile = api.make_profile("Circular", {"Diameter": diameter}, center=start, direction=x_axis)
    _fuse_into_structure(context, result, api.extrude(bar_profile, x_axis * (2.0 * reach), solid=True))
    return result


# ----------------------------------------------------------------------
# VAV box: a rectangular casing with an inlet collar and an outlet collar.
# ----------------------------------------------------------------------


def _vav_box_layout(context):
    """
    Sizes of a VAV box. The casing is centred on the node; each collar runs
    from its own end of the casing out to the duct it connects. A size left
    at 0 is taken from the larger of the two ducts.
    """
    api = context["hvac_api"]
    ports = list(api.connected_ports(context))
    if len(ports) != 2:
        raise ValueError(f"Expected 2 connected ports, got {len(ports)}")
    p = _props(context)
    size = max(_size(api, ports[0]), _size(api, ports[1]))
    length = _positive(p.get("BoxLength"), max(2.0 * size, 300.0))
    width = _positive(p.get("BoxWidth"), 1.5 * size)
    height = _positive(p.get("BoxHeight"), 1.5 * size)
    collar = max(float(p.get("CollarLength", 0.0) or 0.0), 0.0) or 0.25 * size
    # Each duct stops at the outer end of its collar.
    trim = length / 2.0 + collar
    return ports, length, width, height, trim


def measure_vav_box(context):
    api = context["hvac_api"]
    ports, _length, _width, _height, trim = _vav_box_layout(context)
    return api.build_trim_rec_from_port_lengths([(ports[0], trim), (ports[1], trim)])


def build_vav_box(context):
    """VAV box: a closed rectangular casing with a collar at each end, in the section of the duct it meets."""
    api = context["hvac_api"]
    ports, length, width, height, trim = _vav_box_layout(context)
    # The casing lies along the second port's direction, centred between the two ports.
    axis = api.unit(api.port_direction(ports[1]))
    middle = api.average_point([api.port_position(ports[0]), api.port_position(ports[1])])
    x_axis = api.port_profile_x_axis(ports[1])
    ends = [_trimmed(api, port, trim) for port in ports]

    def envelope(offset):
        # The casing grows by the wall offset in every direction, its two
        # ends included, so the end walls get built too.
        start = middle - axis * (length / 2.0 + offset)
        section = {"Width": width + 2.0 * offset, "Height": height + 2.0 * offset}
        casing = api.make_profile("Rectangular", section, center=start, direction=axis, profile_x_axis=x_axis)
        shape = api.extrude(casing, axis * (length + 2.0 * offset), solid=True)
        # Each collar runs from the duct end back into the casing (to its middle, so the two always fuse).
        for port, end in zip(ports, ends):
            back = api.unit(api.port_direction(port)) * -1.0
            shape = api.fuse(shape, api.extrude(api.profile_from_port(end, offset), back * trim, solid=True))
        return shape

    lengths = api.build_trim_rec_from_port_lengths([(ports[0], trim), (ports[1], trim)])
    return _finish(context, envelope, lengths)
