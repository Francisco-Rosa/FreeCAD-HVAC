# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the HVAC addon.

"""
Placeholder markers: a small sphere standing in for a fitting that has no
real geometry yet, and the fallback drawn when a fitting's own geometry
fails to build (build_fallback).
"""

from ._common import _props, _size

# The fallback pulls each duct back by this share of its size (at least the
# minimum), so the gap shows where the fitting that failed belongs. None on
# an end: like the end marker, the duct runs to the node.
FALLBACK_TRIM_FACTOR = 0.25
FALLBACK_MIN_TRIM = 25.0


def _marker(context, diameter, trim=0.0):
    api = context["hvac_api"]
    ports = api.connected_ports(context)
    if ports:
        center = sum((api.port_position(p) for p in ports), api.vec((0, 0, 0))) / len(ports)
    else:
        center = api.vec(context.get("position", (0, 0, 0)))
    result = api.single_layer(context, api.make_sphere(center, diameter))
    if ports and trim > 0:
        result["connection_lengths"] = api.build_trim_rec_from_port_lengths([(p, trim) for p in ports])
    return result


def build_terminal_marker(context):
    api = context["hvac_api"]
    ports = api.connected_ports(context)
    props = _props(context)
    center = api.port_position(ports[0])

    diameter = float(props.get("MarkerDiameter", 200.0) or 200.0)
    if diameter <= 0.0:
        raise ValueError("Marker diameter must be > 0")

    port_direction = api.port_direction(ports[0])
    z_reference = api.vec((0, 0, 1))
    x_reference = api.vec((1, 0, 0))
    reference = z_reference if abs(port_direction.dot(z_reference)) < 0.95 else x_reference

    first_axis = port_direction.cross(reference)
    if api.is_zero(first_axis):
        first_axis = port_direction.cross(api.vec((0, 1, 0)))
    first_axis = api.unit(first_axis)
    second_axis = api.unit(port_direction.cross(first_axis))

    radius = diameter / 2.0
    first_line = api.make_line(center - first_axis * radius, center + first_axis * radius)
    second_line = api.make_line(center - second_axis * radius, center + second_axis * radius)

    return api.single_layer(
        context,
        api.compound([first_line, second_line]),
        connection_lengths=api.build_trim_rec_from_context_uniform(context, 0.0),
    )


def build_transition_marker(context):
    return _marker(context, 160.0, 60.0)


def build_elbow_marker(context):
    return _marker(context, 180.0, 70.0)


def build_tee_marker(context):
    return _marker(context, 200.0, 80.0)


def build_wye_marker(context):
    return _marker(context, 200.0, 80.0)


def build_cross_marker(context):
    return _marker(context, 220.0, 90.0)


def build_manifold_marker(context):
    return _marker(context, 240.0, 90.0)


def fallback_trims(api, ports):
    """The fallback's trim for each port: none on an end, else FALLBACK_TRIM_FACTOR of the duct size."""
    if len(ports) < 2:
        return [0.0 for _port in ports]
    return [max(FALLBACK_MIN_TRIM, FALLBACK_TRIM_FACTOR * _size(api, port)) for port in ports]


def measure_fallback(context):
    api = context["hvac_api"]
    ports = list(api.connected_ports(context))
    return api.build_trim_rec_from_port_lengths(list(zip(ports, fallback_trims(api, ports))))


def build_fallback(context):
    """
    Stand-in for a fitting whose own geometry failed (the component keeps
    its GeometryError): an end-marker cross on every duct end, across the
    duct's own width and height, each end pulled back by fallback_trims()
    when the node has two or more ducts, and a line from the node to each
    pulled-back end. Lines only, so it cannot fail itself and costs nothing.
    """
    api = context["hvac_api"]
    ports = list(api.connected_ports(context))
    if not ports:
        return api.single_layer(context, api.make_sphere(api.vec(context.get("center_point", (0, 0, 0))), 100.0))
    centre = api.average_point([api.port_position(port) for port in ports])
    trims = fallback_trims(api, ports)
    lines = []
    for port, trim in zip(ports, trims):
        direction = api.unit(api.port_direction(port))
        end = api.port_position(port) + direction * trim
        _placement, x_axis, y_axis, _z = api.make_profile_frame(direction, api.port_profile_x_axis(port))
        params = api.port_section_params(port)
        if api.port_profile(port) == "Circular":
            width = height = float(params.get("Diameter", 0.0) or 0.0)
        else:
            width, height = float(params.get("Width", 0.0) or 0.0), float(params.get("Height", 0.0) or 0.0)
        width, height = max(width, 50.0), max(height, 50.0)
        lines.append(api.make_line(end - x_axis * (width / 2.0), end + x_axis * (width / 2.0)))
        lines.append(api.make_line(end - y_axis * (height / 2.0), end + y_axis * (height / 2.0)))
        if (end - centre).Length > 1.0:
            lines.append(api.make_line(centre, end))
    return api.single_layer(
        context, api.compound(lines), connection_lengths=api.build_trim_rec_from_port_lengths(list(zip(ports, trims)))
    )
