# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the HVAC addon.

"""
Star fittings: every port lofted straight to a shared centre. The generic
fallback shape for branch, cross and multiport nodes.
"""

from ._common import (
    _clip_branch_at_trunk_center,
    _clip_junction_to_body,
    _finish,
    _loft,
    _port_axis_point,
    _positive,
    _props,
    _size,
    _trimmed,
)

_TEE_TRIM_NAMES = ("TrimRunA", "TrimRunB", "TrimBranch")


def _star_port_roles(api, context, ports, align_branch):
    """
    Role of each port, by edge_key, for a type that names its trims by tee
    role (TrimRunA/TrimRunB/TrimBranch): {"<edge_key>": "RunA", ...}.
    Empty for every other star fitting, whose ports have no role and whose
    trim is one per-port TrimLength.
    """
    params = _props(context)
    if not (align_branch and len(ports) == 3 and any(name in params for name in _TEE_TRIM_NAMES)):
        return {}
    if not api.collinear_port_index_pairs(context):
        return {}
    run_a, run_b, branch = api.run_branch_ports(context)
    return {run_a.get("edge_key"): "RunA", run_b.get("edge_key"): "RunB", branch.get("edge_key"): "Branch"}


def _star_trims(api, context, ports, roles, default_trim):
    """
    One trim length per port of a star fitting.

    A port with a tee role uses that role's own property (TrimBranch, ...).
    Any other port uses TrimLength, which may be a per-port property (its
    own value for every port, any number of ports) or one shared value.
    A value that is not set (zero or missing) falls back to default_trim.
    """
    params = _props(context)
    trims = []
    for port in ports:
        role = roles.get(port.get("edge_key"))
        value = params.get("Trim" + role) if role else api.port_param(context, "TrimLength", port)
        trims.append(_positive(value, default_trim))
    return trims


def _star_junction_layout(context, default_factor, align_branch=False):
    api = context["hvac_api"]
    ports = api.connected_ports(context)
    if len(ports) < 3:
        raise ValueError("Branch junction requires at least three connected ports")
    center = api.average_point([api.port_position(port) for port in ports])
    default_trim = max(_size(api, port) for port in ports) * default_factor
    # Each port's tee role doubles as the suffix of its flange switch (ShowFlangeBranch, ...).
    roles = _star_port_roles(api, context, ports, align_branch)
    trims = _star_trims(api, context, ports, roles, default_trim)
    return ports, center, trims, roles


def measure_star_junction(context, default_factor=0.6, align_branch=False):
    api = context["hvac_api"]
    ports, center, trims, _roles = _star_junction_layout(context, default_factor, align_branch)
    return api.build_trim_rec_from_port_lengths(list(zip(ports, trims)))


def _star_junction(context, default_factor=0.6, align_branch=False):
    api = context["hvac_api"]
    ports, center, trims, roles = _star_junction_layout(context, default_factor, align_branch)
    branch = None
    if align_branch:
        pairs = api.collinear_port_index_pairs(context)
        if pairs:
            _, _, branch = api.run_branch_ports(context)
            center = api.center_from_context(context)
    trimmed = [_trimmed(api, port, trim) for port, trim in zip(ports, trims)]

    def envelope(offset):
        legs = []
        for source_port, port in zip(ports, trimmed):
            inner_position = _port_axis_point(api, source_port, center) if source_port is branch else center
            center_port = api.copy_port(port, position=inner_position, direction=api.port_direction(port) * -1.0)
            leg = _loft(api, [port, center_port], offset, ruled=True)
            if source_port is branch:
                leg = _clip_branch_at_trunk_center(api, leg, center, branch)
            legs.append(leg)
        return api.fuse(*legs)

    return _finish(context, envelope, api.build_trim_rec_from_port_lengths(list(zip(ports, trims))), roles)


def measure_branch_generic(context):
    return measure_star_junction(context, 0.60, align_branch=True)


def measure_wye_generic(context):
    return measure_star_junction(context, 0.70)


def measure_cross(context):
    return measure_star_junction(context, 0.60)


def measure_manifold(context):
    return measure_star_junction(context, 0.65)


def _star_body(api, center, ports, trims, minimums, branch=None, offset=0.0):
    """Build robust straight-legged junction geometry with controlled overlap."""
    legs = []
    for port, trim, minimum in zip(ports, trims, minimums):
        direction = api.unit(api.port_direction(port))
        end = _trimmed(api, port, trim)
        embed = max(0.10 * minimum, 1.0)
        inner_center = _port_axis_point(api, port, center) if port is branch else center
        inner = api.copy_port(port, position=inner_center - direction * embed)
        leg = _loft(api, [end, inner], offset, ruled=True)
        if port is branch:
            leg = _clip_branch_at_trunk_center(api, leg, center, branch)
        legs.append(leg)
    shape = api.fuse(*legs)
    return _clip_junction_to_body(api, shape, center, ports, trims)


def build_branch_generic(context):
    return _star_junction(context, 0.60, align_branch=True)


def build_wye_generic(context):
    """Plain three-leg star for a wye: slightly longer default legs than the generic branch."""
    return _star_junction(context, 0.70)


def build_cross(context):
    return _star_junction(context, 0.60)


def build_manifold(context):
    return _star_junction(context, 0.65)
