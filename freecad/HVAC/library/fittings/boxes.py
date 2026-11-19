# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the HVAC addon.

"""
Box fittings: a closed rectangular casing with one collar per connected
duct. The plenum (any number of ports) and the AHU connection (one port)
are the same builder with different placement rules.

Each duct leaves through whichever face of the box its own axis passes
through, and stops at the outer end of its collar. A plenum size left at 0
is automatic: twice the largest duct, grown where needed so every duct fits
on the face it leaves through.
"""

from ._common import _EPS, _finish, _positive, _props, _size, _trimmed


def _number(props, name):
    return float(props.get(name, 0.0) or 0.0)


def _lead_port(api, context):
    """The port the box is lined up with: the largest one (the first by role when sizes are equal)."""
    ordered = list(api.port_roles(context).values())
    largest = max(_size(api, port) for port in ordered)
    return next(port for port in ordered if _size(api, port) >= largest - _EPS)


def _box_frame(api, lead):
    """The box's own axes: length along the lead port, width and height along that port's section axes."""
    _placement, x_axis, y_axis, z_axis = api.make_profile_frame(api.port_direction(lead), api.port_profile_x_axis(lead))
    return z_axis, x_axis, y_axis


def _section_half_extent(api, port, direction):
    """Half the size of a port's section measured along `direction` (an oval is treated as its bounding rectangle)."""
    if api.port_profile(port) == "Circular":
        return float(api.port_diameter(port)) / 2.0
    _placement, x_axis, y_axis, _z = api.make_profile_frame(api.port_direction(port), api.port_profile_x_axis(port))
    half_width, half_height = float(api.port_width(port)) / 2.0, float(api.port_height(port)) / 2.0
    return abs(x_axis.dot(direction)) * half_width + abs(y_axis.dot(direction)) * half_height


def _port_exit(api, port, centre, axes, halves):
    """
    Where a port's axis leaves the box, by the usual slab test.

    Returns (distance along the port from its own position to the exit
    face, length of the port's axis line inside the box). Raises ValueError when the
    axis misses the box or the duct section does not fit on the exit face.
    """
    leave, chord, needed = _port_fit(api, port, centre, axes, halves)
    for index, reach in needed.items():
        if reach > halves[index] + 1.0e-6:
            label = str(port.get("edge_key", "") or "port")
            raise ValueError(
                "Duct {} does not fit on the box face: it overhangs by {:.1f} mm".format(label, reach - halves[index])
            )
    return leave, chord


def _port_fit(api, port, centre, axes, halves):
    """
    The slab test of _port_exit without the fit check: (leave, chord,
    needed), where needed[i] is the half-size the box must have along axis i
    for the duct section to lie inside the face it leaves through (the
    exit face's own axis is left out). Raises ValueError when the axis
    misses the box.
    """
    label = str(port.get("edge_key", "") or "port")
    position = api.port_position(port)
    direction = api.unit(api.port_direction(port))
    local_position = [(position - centre).dot(axis) for axis in axes]
    local_direction = [direction.dot(axis) for axis in axes]

    # Step 1: clip the axis line against the three pairs of faces.
    enter, leave, exit_axis = -float("inf"), float("inf"), None
    for index in range(3):
        p, d, half = local_position[index], local_direction[index], halves[index]
        if abs(d) <= _EPS:
            if abs(p) > half + _EPS:
                raise ValueError("Duct {} passes beside the box: move the box or make it larger".format(label))
            continue
        near, far = sorted(((-half - p) / d, (half - p) / d))
        enter = max(enter, near)
        if far < leave:
            leave, exit_axis = far, index
    if exit_axis is None or enter > leave + _EPS or leave < -_EPS:
        raise ValueError("Duct {} does not meet the box: move the box or make it larger".format(label))
    chord = leave - enter
    leave = max(leave, 0.0)

    # Step 2: how far the duct section reaches across the face it leaves through.
    needed = {}
    for index in range(3):
        if index == exit_axis:
            continue
        needed[index] = abs(local_position[index] + local_direction[index] * leave) + _section_half_extent(
            api, port, axes[index]
        )
    return leave, chord, needed


# A box size left automatic grows at most this many times to fit its ducts.
_AUTO_GROW_PASSES = 12


def _grow_to_fit(api, ports, centre, axes, halves, automatic):
    """
    Grow the automatic box sizes (automatic[i] True) until every duct's
    section fits on the face it leaves through. Growing one size can move a
    duct onto another face, so it repeats until nothing changes. A size the
    user set is never changed: a duct that still overhangs it is reported
    by _port_exit afterwards.
    """
    halves = list(halves)
    for _pass in range(_AUTO_GROW_PASSES):
        grown = False
        for port in ports:
            _leave, _chord, needed = _port_fit(api, port, centre, axes, halves)
            for index, reach in needed.items():
                if automatic[index] and reach > halves[index] + 1.0e-6:
                    # A small margin, so the duct does not sit exactly on the box edge.
                    halves[index] = reach + max(1.0, 0.01 * reach)
                    grown = True
        if not grown:
            break
    return halves


def _box_layout(context, kind):
    """
    Sizes and placement of a box fitting:

        {"ports", "centre", "axes": (length, width, height directions),
         "dims": (length, width, height), "collars": [...], "exits": [...],
         "inside": [...], "trims": [...]}

    `exits[i]` is how far port i runs from its own position to the box face,
    `collars[i]` the collar length beyond that face, and `trims[i]` their sum.
    """
    api = context["hvac_api"]
    ports = list(api.connected_ports(context))
    if not ports:
        raise ValueError("A box fitting requires at least one connected port")
    props = _props(context)
    lead = _lead_port(api, context)
    axes = _box_frame(api, lead)
    size = max(_size(api, port) for port in ports)
    node = api.center_from_context(context)

    if kind == "ahu":
        if len(ports) != 1:
            raise ValueError("An AHU connection requires exactly one connected port")
        dims = (
            _positive(props.get("BoxLength"), 3.0 * size),
            _positive(props.get("BoxWidth"), 2.0 * size),
            _positive(props.get("BoxHeight"), 2.0 * size),
        )
        # The unit stands behind the node, with the connection on its front face;
        # the two offsets move the connection away from the middle of that face.
        centre = api.port_position(lead) - axes[0] * (dims[0] / 2.0)
        centre = centre - axes[1] * _number(props, "ConnectionOffsetY") - axes[2] * _number(props, "ConnectionOffsetZ")
        collars = [_positive(props.get("TrimNeck"), 0.25 * _size(api, lead))]
    else:
        names = ("BoxLength", "BoxWidth", "BoxHeight")
        dims = tuple(_positive(props.get(name), 2.0 * size) for name in names)
        offsets = [_number(props, name) for name in ("CentreOffsetX", "CentreOffsetY", "CentreOffsetZ")]
        centre = node + axes[0] * offsets[0] + axes[1] * offsets[1] + axes[2] * offsets[2]
        collars = [_positive(api.port_param(context, "TrimLength", port), 0.25 * _size(api, port)) for port in ports]
        # A size left at 0 is automatic: it starts at twice the largest duct and grows until every duct fits.
        automatic = [_number(props, name) <= 0.0 for name in names]
        if any(automatic):
            halves = _grow_to_fit(api, ports, centre, axes, [value / 2.0 for value in dims], automatic)
            dims = tuple(2.0 * half for half in halves)

    halves = [value / 2.0 for value in dims]
    exits, inside = [], []
    for port in ports:
        leave, chord = _port_exit(api, port, centre, axes, halves)
        exits.append(leave)
        inside.append(chord)
    trims = [leave + collar for leave, collar in zip(exits, collars)]
    return {
        "ports": ports,
        "centre": centre,
        "axes": axes,
        "dims": dims,
        "collars": collars,
        "exits": exits,
        "inside": inside,
        "trims": trims,
    }


def _measure_box(context, kind):
    api = context["hvac_api"]
    layout = _box_layout(context, kind)
    return api.build_trim_rec_from_port_lengths(list(zip(layout["ports"], layout["trims"])))


def _build_box(context, kind):
    api = context["hvac_api"]
    layout = _box_layout(context, kind)
    ports, centre, trims = layout["ports"], layout["centre"], layout["trims"]
    axis, x_axis, _y_axis = layout["axes"]
    length, width, height = layout["dims"]

    def envelope(offset):
        # Step 1: the casing, grown by the wall offset on all six sides so it stays closed.
        start = centre - axis * (length / 2.0 + offset)
        section = {"Width": width + 2.0 * offset, "Height": height + 2.0 * offset}
        casing = api.make_profile("Rectangular", section, center=start, direction=axis, profile_x_axis=x_axis)
        shape = api.extrude(casing, axis * (length + 2.0 * offset), solid=True)

        # Step 2: one collar per duct, from the duct end back into the casing (half way along its path inside).
        for port, trim, collar, chord in zip(ports, trims, layout["collars"], layout["inside"]):
            end = _trimmed(api, port, trim)
            back = api.unit(api.port_direction(port)) * -1.0
            reach = collar + max(chord / 2.0, offset + 1.0)
            shape = api.fuse(shape, api.extrude(api.profile_from_port(end, offset), back * reach, solid=True))
        return shape

    lengths = api.build_trim_rec_from_port_lengths(list(zip(ports, trims)))
    return _finish(context, envelope, lengths)


def build_plenum(context):
    """Plenum box: BoxLength/BoxWidth/BoxHeight, moved from the node by CentreOffsetX/Y/Z, per-port TrimLength collars."""
    return _build_box(context, "plenum")


def measure_plenum(context):
    return _measure_box(context, "plenum")


def build_ahu(context):
    """AHU connection: a casing behind the node with one collar (TrimNeck) on its front face."""
    return _build_box(context, "ahu")


def measure_ahu(context):
    return _measure_box(context, "ahu")
