# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the HVAC addon.

"""
Transitions and offsets between two collinear ports: angled (straight loft),
radiussed (S-curve) and mitered.
"""

import math

from ..loss_tables import transitions as transition_tables
from ._common import _finish, _loft, _min_bend_radius, _positive, _props, _size, _trimmed, _wall_thickness

_KNOWN_PROFILES = ("Circular", "Rectangular", "Oval")


# ----------------------------------------------------------------------------
# Fitting-derived values (ROADMAP 6.1). Pure: ports and resolved properties
# in, numbers out, no shapes. The generators report them as read-only
# computed properties and the loss functions call the same helpers, so the
# two cannot disagree.
# ----------------------------------------------------------------------------


def body_length(api, ports, length_value):
    """The fitting's axial body length: the given length, or the larger duct size (at least 100 mm) when 0."""
    size = max(_size(api, port) for port in ports)
    return _positive(length_value, max(size, 100.0))


def transition_dimensions(api, ports, params):
    """
    A two-port transition's derived values:
      - "body_length": TransitionLength, or its default;
      - "included_angle" (deg): the angle the SMACNA tables are read at --
        round: the cone's included angle; rectangular or oval: the larger of
        the two side pairs' angles; round to rectangular: the 14-11 C/D
        equivalent angle. 0 when both ends are the same size, None when a
        profile is not round, rectangular or oval;
      - "single_plane": rectangular ends with only one pair of sides
        diverging (the 14-11 E shape).
    Independent of flow direction: the angle is the same either way.
    """
    if len(ports) != 2:
        raise ValueError("Expected 2 connected ports, got {}".format(len(ports)))
    length = body_length(api, ports, params.get("TransitionLength"))
    result = {"body_length": length, "included_angle": None, "single_plane": False}
    profiles = [api.port_profile(port) for port in ports]
    if any(profile not in _KNOWN_PROFILES for profile in profiles):
        return result
    small, large = sorted(ports, key=lambda port: float(api.port_area(port)))

    def included(change):
        return math.degrees(2.0 * math.atan(abs(change) / (2.0 * length)))

    round_small = api.port_profile(small) == "Circular"
    round_large = api.port_profile(large) == "Circular"
    if round_small and round_large:
        result["included_angle"] = included(float(api.port_diameter(large)) - float(api.port_diameter(small)))
    elif not round_small and not round_large:
        d_w = float(api.port_width(large)) - float(api.port_width(small))
        d_h = float(api.port_height(large)) - float(api.port_height(small))
        result["included_angle"] = max(included(d_w), included(d_h))
        tolerance = 0.01 * _size(api, large)
        result["single_plane"] = (abs(d_w) <= tolerance) != (abs(d_h) <= tolerance)
    else:
        round_port, rect_port = (small, large) if round_small else (large, small)
        result["included_angle"] = transition_tables.round_rect_equivalent_angle(
            float(api.port_diameter(round_port)),
            float(api.port_width(rect_port)),
            float(api.port_height(rect_port)),
            length,
        )
    return result


def _radiussed_radius(api, ports, total, requested, wall=0.0):
    """
    The arc radius a radiussed offset really gets: the requested one (default
    the duct size), at least the bend minimum (half the duct size plus the
    wall), and at most what fits between the ends and the diagonal. Raises
    when even the minimum does not fit.
    """
    size = max(_size(api, ports[0]), _size(api, ports[1]))
    radius = _positive(requested, max(size, 10.0))
    # A smaller radius folds the swept surface (or a wall layer around it)
    # back on itself on the inside of the bend; build_elbow uses the same minimum.
    minimum = _min_bend_radius(size, wall)
    radius = max(radius, minimum)

    # The two arcs have to fit between the ends and the diagonal: each arc
    # takes R tan(turn / 2) on either side of its corner. A radius larger
    # than that is reduced to the largest that fits (a little short of it,
    # so the straight pieces don't shrink to nothing).
    axis = api.offset_transition_axis(ports[0], ports[1], total)
    turn = axis["turn_angle"]
    if turn > 1.0e-6:
        room = min(total / 4.0, (axis["corner1"] - axis["corner0"]).Length / 2.0)
        largest = 0.98 * room / math.tan(turn / 2.0)
        if largest < minimum:
            raise ValueError(
                "The offset is too steep for a radiussed fitting of this size: make OffsetLength / "
                "TransitionLength longer (the arcs need a radius of at least {:.0f} mm, only {:.0f} mm fits)".format(
                    minimum, largest
                )
            )
        radius = min(radius, largest)
    return radius


def _lateral_offset(api, ports):
    """How far apart the two (parallel) port axes are, across the duct."""
    axis = api.unit(api.port_direction(ports[0]))
    delta = api.port_position(ports[1]) - api.port_position(ports[0])
    return (delta - axis * delta.dot(axis)).Length


def radiussed_body_length(api, ports, params, wall=0.0):
    """
    A radiussed offset's body length: TransitionLength when set; when 0, the
    default length (body_length), made longer where needed so the arcs fit
    at the radius _radiussed_radius starts from.

    The corners sit a quarter of the length in from each end, so the
    diagonal turns by `turn` with tan(turn) = 2 d / L for a lateral offset d,
    and each arc fits when 0.98 (L / 4) / tan(turn / 2) >= R. With
    k = 0.98 / (4 R) and t = tan(turn / 2) = k L, that is
    2 t / (1 - t^2) = 2 d / L, so L = sqrt(d / (k (1 + d k))).
    """
    length = float(params.get("TransitionLength") or 0.0)
    if length > 0.0:
        return length
    length = body_length(api, ports, 0.0)
    size = max(_size(api, ports[0]), _size(api, ports[1]))
    radius = max(_positive(params.get("TransitionRadius"), max(size, 10.0)), _min_bend_radius(size, wall))
    offset = _lateral_offset(api, ports)
    if offset <= api.EPS:
        return length
    k = 0.98 / (4.0 * radius)
    # A hair longer than the exact fit, so the arcs never come out a rounding error short.
    return max(length, 1.001 * math.sqrt(offset / (k * (1.0 + offset * k))))


def offset_dimensions(api, ports, params, radiussed=False, wall=0.0):
    """
    A two-port offset's derived values, from the transition-named properties
    (TransitionLength, TransitionRadius; offsets.py maps OffsetLength and
    OffsetRadius onto them):
      - "body_length": the length, or its default;
      - "offset_angle" (deg): each corner's deflection from the duct axis;
      - "actual_radius": radiussed only, the arc radius after the fit limit
        (`wall` is the fitting's total wall thickness, see _min_bend_radius).
    """
    if len(ports) != 2:
        raise ValueError("Expected 2 connected ports, got {}".format(len(ports)))
    if radiussed:
        length = radiussed_body_length(api, ports, params, wall)
    else:
        length = body_length(api, ports, params.get("TransitionLength"))
    axis = api.offset_transition_axis(ports[0], ports[1], length)
    result = {"body_length": length, "offset_angle": math.degrees(axis["turn_angle"])}
    if radiussed:
        result["actual_radius"] = _radiussed_radius(api, ports, length, params.get("TransitionRadius"), wall)
    return result


def _transition_layout(context):
    api = context["hvac_api"]
    ports = list(api.connected_ports(context))
    if len(ports) != 2:
        raise ValueError(f"Expected 2 connected ports, got {len(ports)}")
    trim = body_length(api, ports, _props(context).get("TransitionLength")) / 2.0
    return ports, trim


def measure_transition(context):
    api = context["hvac_api"]
    ports, trim = _transition_layout(context)
    return api.build_trim_rec_from_port_lengths([(ports[0], trim), (ports[1], trim)])


def build_transition(context):
    api = context["hvac_api"]
    ports, trim = _transition_layout(context)
    a, b = _trimmed(api, ports[0], trim), _trimmed(api, ports[1], trim)

    def envelope(offset):
        return _loft(api, [a, b], offset, ruled=True)

    lengths = api.build_trim_rec_from_port_lengths([(ports[0], trim), (ports[1], trim)])
    result = _finish(context, envelope, lengths)
    dims = transition_dimensions(api, ports, _props(context))
    computed = {"BodyLength": dims["body_length"]}
    if dims["included_angle"] is not None:
        computed["IncludedAngle"] = dims["included_angle"]
    result["computed_properties"] = computed
    return result


def _transition_radiussed_route(context):
    api = context["hvac_api"]
    ports = list(api.connected_ports(context))
    if len(ports) != 2:
        raise ValueError(f"Expected 2 connected ports, got {len(ports)}")
    p = _props(context)
    total = radiussed_body_length(api, ports, p, _wall_thickness(context))
    radius = _radiussed_radius(api, ports, total, p.get("TransitionRadius"), _wall_thickness(context))
    route = api.make_radiussed_path(ports[0], ports[1], total, radius)
    return ports, route


def measure_transition_radiussed(context):
    api = context["hvac_api"]
    ports, route = _transition_radiussed_route(context)
    return api.build_trim_rec_from_port_lengths(
        [(ports[0], route["trim_lengths"][0]), (ports[1], route["trim_lengths"][1])]
    )


def build_transition_radiussed(context):
    api = context["hvac_api"]
    ports, route = _transition_radiussed_route(context)

    def envelope(offset):
        ends = [api.profile_from_port(route["ports"][0], offset), api.profile_from_port(route["ports"][1], offset)]
        return api.sweep(ends, route["path"], solid=True)

    lengths = api.build_trim_rec_from_port_lengths(
        [(ports[0], route["trim_lengths"][0]), (ports[1], route["trim_lengths"][1])]
    )
    return _finish(context, envelope, lengths)


def _transition_mitered_layout(context):
    api = context["hvac_api"]
    ports = list(api.connected_ports(context))
    if len(ports) != 2:
        raise ValueError(f"Expected 2 connected ports, got {len(ports)}")
    size = max(_size(api, ports[0]), _size(api, ports[1]))
    total = body_length(api, ports, _props(context).get("TransitionLength"))

    # Shared axis geometry with the radiussed transition -- same end
    # points and theoretical sharp turn points, only the corner treatment
    # differs (a flat mitre cut here, an arc there).
    axis = api.offset_transition_axis(ports[0], ports[1], total)
    trim0 = max(0.0, (axis["s0"] - api.port_position(ports[0])).dot(api.port_direction(ports[0])))
    trim1 = max(0.0, (axis["s1"] - api.port_position(ports[1])).dot(api.port_direction(ports[1])))
    return ports, size, total, axis, trim0, trim1


def measure_transition_mitered(context):
    api = context["hvac_api"]
    ports, size, total, axis, trim0, trim1 = _transition_mitered_layout(context)
    return api.build_trim_rec_from_port_lengths([(ports[0], trim0), (ports[1], trim1)])


def build_transition_mitered(context):
    api = context["hvac_api"]
    ports, size, total, axis, trim0, trim1 = _transition_mitered_layout(context)
    d = axis["d"]
    s0, s1 = axis["s0"], axis["s1"]
    corner0, corner1 = axis["corner0"], axis["corner1"]
    diagonal, turn_angle = axis["diagonal"], axis["turn_angle"]

    end_a = api.copy_port(ports[0], position=s0)
    end_b = api.copy_port(ports[1], position=s1)

    def envelope(offset):
        if turn_angle <= 1e-6:
            # No actual lateral offset: an ordinary straight loft, there is
            # no corner to mitre.
            return _loft(api, [end_a, end_b], offset, ruled=True)

        # The mitre plane bisects the straight-run direction and the
        # diagonal, so a straight stub and the diagonal middle piece meet
        # flush -- both turn points share this same bisector as their
        # plane normal, only the plane's own origin differs.
        normal = api.unit(d + diagonal)

        # Extend each port's own profile from its end point toward the
        # transition's centre, then clip it back at its own turn point
        # with the mitre plane.
        reach = total / 2.0 + size
        stub_a = api.extrude(api.profile_from_port(end_a, offset), d * reach, solid=True)
        stub_a = api.clip_plane(stub_a, (corner0, normal), side="negative")
        stub_b = api.extrude(api.profile_from_port(end_b, offset), d * -reach, solid=True)
        stub_b = api.clip_plane(stub_b, (corner1, normal), side="positive")

        # Loft between the stubs' own cut faces at the turn points -- not
        # a fresh, idealised profile wire, which sits on a different plane
        # than the mitre cut and would not line up with it once clipped.
        # Reading the real cut face back off each already-trimmed stub
        # guarantees the middle piece meets them exactly, and needs no
        # further clipping of its own.
        face_a = api.section_face(stub_a, (corner0, normal))
        face_b = api.section_face(stub_b, (corner1, normal))
        middle = api.loft([face_a.OuterWire, face_b.OuterWire], solid=True, ruled=True)
        return api.fuse(stub_a, stub_b, middle)

    lengths = api.build_trim_rec_from_port_lengths([(ports[0], trim0), (ports[1], trim1)])
    return _finish(context, envelope, lengths)
