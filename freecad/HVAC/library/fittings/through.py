# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the HVAC addon.

"""
Generic two-port fittings that pick their shape from the node geometry:
straight coupling, bend or transition.
"""

from .elbows import build_elbow, measure_elbow
from .inline import _inline, measure_inline
from .markers import _marker
from .transitions import build_transition, measure_transition


def _straight_is_transition(context):
    api = context["hvac_api"]
    ports = list(api.connected_ports(context))
    if len(ports) != 2:
        raise ValueError(f"Expected 2 connected ports, got {len(ports)}")
    s0, s1 = api.port_section_params(ports[0]), api.port_section_params(ports[1])
    return api.port_profile(ports[0]) != api.port_profile(ports[1]) or s0 != s1


def measure_straight(context):
    if _straight_is_transition(context):
        return measure_transition(context)
    return measure_inline(context, 0.2, 30.0)


def build_straight(context):
    """Plain duct-to-duct connection: no bend, no special fitting.

    Two same-profile, same-size ports become a short coupling sleeve; two
    differently-sized/profiled ports fall back to a transition, since the
    "through.straight" family key is purely about the ports being
    collinear with zero eccentricity (see TOPOLOGY_CLASSIFICATION.md) --
    it says nothing about whether their sizes actually match.
    """
    if _straight_is_transition(context):
        return build_transition(context)
    return _inline(context, 0.2, 30.0)


def _through_generic_dispatch(context):
    """Which of build_through_generic's 4 cases applies: "elbow"
    (non-collinear ports), "transition" (collinear but different profile/
    size), "inline" (collinear, same profile/size), or "marker" (not
    exactly 2 ports -- a defensive fallback for a not-yet-composed node).
    Shared so measure_through_generic() can never disagree with
    build_through_generic() about which case it's in."""
    api = context["hvac_api"]
    ports = api.connected_ports(context)
    if len(ports) != 2:
        return "marker"
    u0 = api.port_direction(ports[0])
    u1 = api.port_direction(ports[1])
    dot = max(-1.0, min(1.0, float(u0.dot(u1))))
    if dot > -0.985:
        return "elbow"
    s0, s1 = api.port_section_params(ports[0]), api.port_section_params(ports[1])
    if api.port_profile(ports[0]) != api.port_profile(ports[1]) or s0 != s1:
        return "transition"
    return "inline"


def measure_through_generic(context):
    kind = _through_generic_dispatch(context)
    if kind == "elbow":
        return measure_elbow(context)
    if kind == "transition":
        return measure_transition(context)
    if kind == "inline":
        return measure_inline(context, 0.35, 80.0)
    return []


def build_through_generic(context):
    kind = _through_generic_dispatch(context)
    if kind == "elbow":
        return build_elbow(context)
    if kind == "transition":
        return build_transition(context)
    if kind == "inline":
        return _inline(context, 0.35, 80.0)
    return _marker(context, 160.0)
