# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the HVAC addon.

"""
Elbows: smooth-radius and mitered (gored) bends between two ports.
"""

from ._common import (
    _finish,
    _min_bend_radius,
    _mitered_bend,
    _positive,
    _profile_extent,
    _props,
    _size,
    _wall_thickness,
)


def _elbow_route(context):
    """Shared layout for a radiused elbow: the two connected ports and the
    tangent-arc route (HVACLibraryAPI.make_elbow_path) between them -- the
    one calculation that determines both the swept shape's path AND each
    port's own trim length, so measure_elbow()/build_elbow() can never
    disagree."""
    api = context["hvac_api"]
    ports = list(api.connected_ports(context))
    if len(ports) != 2:
        raise ValueError(f"Expected 2 connected ports, got {len(ports)}")
    p = _props(context)
    size = max(_size(api, ports[0]), _size(api, ports[1]))
    radius = _positive(p.get("CenterlineRadius"), 0.6 * size)
    radius = max(radius, _min_bend_radius(size, _wall_thickness(context)))
    route = api.make_elbow_path(ports[0], ports[1], radius)
    return ports, route


def measure_elbow(context):
    api = context["hvac_api"]
    ports, route = _elbow_route(context)
    return api.build_trim_rec_from_port_lengths(
        [(ports[0], route["trim_lengths"][0]), (ports[1], route["trim_lengths"][1])]
    )


def build_elbow(context):
    api = context["hvac_api"]
    ports, route = _elbow_route(context)

    def envelope(offset):
        ends = [api.profile_from_port(route["ports"][0], offset), api.profile_from_port(route["ports"][1], offset)]
        return api.sweep(ends, route["path"], solid=True)

    lengths = api.build_trim_rec_from_port_lengths(
        [(ports[0], route["trim_lengths"][0]), (ports[1], route["trim_lengths"][1])]
    )
    return _finish(context, envelope, lengths)


def _elbow_mitered_radius(context, ports):
    api = context["hvac_api"]
    size = max(_profile_extent(api.profile_from_port(ports[0])), _profile_extent(api.profile_from_port(ports[1])))
    props = _props(context)
    radius = _positive(props.get("CenterlineRadius"), 0.6 * size)
    return max(radius, _min_bend_radius(size, _wall_thickness(context)))


def measure_elbow_mitered(context):
    """The mitred bend's own trims come from the same tangent-arc route
    (api.make_elbow_path) _mitered_bend() uses internally, unaffected by
    NumberOfCuts -- so this can read them directly without paying for
    _mitered_bend()'s own gore/mitre shape construction at all."""
    api = context["hvac_api"]
    ports = list(api.connected_ports(context))
    if len(ports) != 2:
        raise ValueError(f"Expected 2 connected ports, got {len(ports)}")
    radius = _elbow_mitered_radius(context, ports)
    route = api.make_elbow_path(ports[0], ports[1], radius)
    return api.build_trim_rec_from_port_lengths(
        [(ports[0], route["trim_lengths"][0]), (ports[1], route["trim_lengths"][1])]
    )


def build_elbow_mitered(context):
    api = context["hvac_api"]
    ports = list(api.connected_ports(context))
    if len(ports) != 2:
        raise ValueError(f"Expected 2 connected ports, got {len(ports)}")
    port0, port1 = ports
    radius = _elbow_mitered_radius(context, ports)
    props = _props(context)
    cuts = max(int(props.get("NumberOfCuts", 1) or 1), 1)

    def envelope(offset):
        return _mitered_bend(api, port0, port1, radius, cuts, offset=offset)[0]

    # The trims come from the tangent-arc route alone, the same one measure_elbow_mitered() reads.
    route = api.make_elbow_path(port0, port1, radius)
    lengths = api.build_trim_rec_from_port_lengths(
        [(port0, route["trim_lengths"][0]), (port1, route["trim_lengths"][1])]
    )
    return _finish(context, envelope, lengths)
