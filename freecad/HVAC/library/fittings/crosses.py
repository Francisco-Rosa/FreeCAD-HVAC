# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the HVAC addon.

"""
Crosses: a continuous straight run with two branches leaving it, one on
each side (four ports). The straight cross joins square branches with plain
stubs; the double wye joins inclined branches through a bend each.
"""

import math

from ._common import (
    _clip_junction_to_body,
    _extend_leg,
    _finish,
    _inset_bend_start,
    _junction_minimums,
    _junction_shape_minimums,
    _junction_trims,
    _loft,
    _min_bend_radius,
    _mitered_bend,
    _port_axis_point,
    _props,
    _size,
    _trimmed,
    _wall_thickness,
)

_CROSS_TRIM_NAMES = ("TrimRunA", "TrimRunB", "TrimBranchA", "TrimBranchB")
_CROSS_ROLES = ("RunA", "RunB", "BranchA", "BranchB")


def _cross_tee_layout(context, run_factor=0.60, branch_factor=0.60):
    """
    Ports and trims of a straight cross. The run is the classifier's own
    collinear pair (api.port_roles), the other two ports are the branches.
    Each trim is the length needed to clear the other ports' sections at
    the centre, plus that port's own Trim<Role> property.
    """
    api = context["hvac_api"]
    roles = api.port_roles(context)
    if set(roles) != {"run_a", "run_b", "branch_a", "branch_b"}:
        raise ValueError("A straight cross needs four ports, two of them forming a straight run")
    ports = [roles["run_a"], roles["run_b"], roles["branch_a"], roles["branch_b"]]

    center = api.center_from_context(context)
    minimums = _junction_minimums(api, center, ports)
    factors = (run_factor, run_factor, branch_factor, branch_factor)
    trims = _junction_trims(api, _props(context), ports, _CROSS_TRIM_NAMES, factors, minimums)
    return ports, center, trims


def _cross_lengths(api, ports, trims):
    return api.build_trim_rec_from_port_lengths(list(zip(ports, trims)))


def measure_cross_tee_straight(context):
    api = context["hvac_api"]
    ports, _center, trims = _cross_tee_layout(context)
    return _cross_lengths(api, ports, trims)


def build_cross_tee_straight(context):
    """
    Straight cross: one continuous trunk between the two run ports, and a
    straight stub for each branch, joined at the trunk.

    Meant for branches square to the run. The stubs are cut correctly at
    any angle, but the run trims only allow for a square branch's
    footprint, so a strongly inclined branch can reach past the run end.
    """
    api = context["hvac_api"]
    ports, center, trims = _cross_tee_layout(context)
    run_a, run_b = ports[0], ports[1]
    trunk_dir = api.unit(api.port_direction(run_a))

    # Step 1: per branch, the stub's two ends and the plane it is cut on.
    stubs = []
    for branch, trim in zip(ports[2:], trims[2:]):
        branch_dir = api.unit(api.port_direction(branch))
        axis_center = _port_axis_point(api, branch, center)
        # The cut plane contains the trunk axis and faces the branch, so an
        # inclined branch is cut flush with the trunk's mid-plane too.
        plane_normal = api.unit(api.unit(trunk_dir.cross(branch_dir)).cross(trunk_dir))
        # Run the stub slightly past the trunk axis: stopping exactly on it
        # leaves a knife edge after the cut, which the fuse can fail on.
        embed = max(0.01 * _size(api, branch), 2.0)
        inner = api.copy_port(branch, position=axis_center - branch_dir * embed)
        stubs.append((_trimmed(api, branch, trim), inner, axis_center, plane_normal))

    def envelope(offset):
        # Step 2: the continuous trunk.
        shape = _loft(api, [_trimmed(api, run_a, trims[0]), _trimmed(api, run_b, trims[1])], offset)
        # Step 3: each branch stub, cut at the trunk mid-plane and kept inside the run body.
        for outer, inner, axis_center, plane_normal in stubs:
            stub = _loft(api, [outer, inner], offset)
            stub = api.clip_plane(stub, (axis_center, plane_normal), side="positive")
            stub = _clip_junction_to_body(api, stub, center, [run_a, run_b], trims[:2])
            shape = api.fuse(shape, stub)
        return shape

    port_roles = {port.get("edge_key"): role for port, role in zip(ports, _CROSS_ROLES)}
    return _finish(context, envelope, _cross_lengths(api, ports, trims), port_roles)


# ----------------------------------------------------------------------
# Double wye: a straight trunk with two inclined branches, each leaving
# through its own bend (smooth radius or mitered).
# ----------------------------------------------------------------------


# The default branch bend reaches this far beyond the run's surface, as a
# fraction of the distance from the run axis to that surface along the branch.
_BEND_CLEARANCE = 1.25


def _branch_bend_radius(api, requested, branch, from_leg, center, wall=0.0):
    """
    The radius of a branch bend (double wye, lateral tee): `requested`
    (BranchRadius) when set, else the radius whose branch-side end lies
    _BEND_CLEARANCE times the run surface's distance out along the branch,
    so the bend really emerges from the run instead of sitting inside it
    (a deep rectangular run swallowed a one-size bend completely). Never
    less than the branch size, nor than the bend minimum when requested
    (half the size plus the wall, see _min_bend_radius).
    """
    size = _size(api, branch)
    minimum = _min_bend_radius(size, wall)
    if requested is not None and float(requested or 0.0) > 0.0:
        return max(float(requested), minimum)
    branch_dir = api.unit(api.port_direction(branch))
    run_dir = api.unit(api.port_direction(from_leg))
    across = branch_dir - run_dir * branch_dir.dot(run_dir)
    sin_angle = across.Length
    # Deflection of the bend: from heading out along from_leg to heading out along the branch.
    cos_between = max(-1.0, min(1.0, branch_dir.dot(run_dir)))
    deflection = math.pi - math.acos(cos_between)
    if sin_angle <= 1.0e-6 or deflection <= 1.0e-6:
        return max(size, minimum)
    across = api.unit(across)
    run_profile = api.profile_from_port(api.copy_port(from_leg, position=center))
    _low, high = api.profile_projection_bounds(run_profile, across)
    half_depth = max(high - api.vec(center).dot(across), 0.0)
    reach = _BEND_CLEARANCE * half_depth / sin_angle
    return max(size, minimum, reach / math.tan(deflection / 2.0))


def _double_wye_bend(api, branch, trunk_axis_port, run_port, radius, cuts, mitered, wall=0.0, offset=0.0):
    """
    One branch bend, from the trunk axis out to the branch. Returns
    (shape, trim along the branch from its port to where the bend ends).

    The bend starts on the trunk axis, inside the trunk, and emerges through
    its wall. Its start section is the branch's own, scaled down where it
    would reach the trunk's inside face (_inset_bend_start, design 6.6 B);
    `run_port` gives the trunk's section and `wall` the total wall
    thickness, which sets that margin the same for every wall layer.
    """
    route = api.make_elbow_path(branch, trunk_axis_port, radius)
    start = _inset_bend_start(api, route["ports"][1], run_port, wall)
    start_profile = api.profile_from_port(start, offset)
    if mitered:
        shape, trims = _mitered_bend(api, branch, trunk_axis_port, radius, cuts, profile1=start_profile, offset=offset)
        return shape, trims[0]
    ends = [api.profile_from_port(route["ports"][0], offset), start_profile]
    return api.sweep(ends, route["path"], solid=True), route["trim_lengths"][0]


def _double_wye_layout(context, mitered):
    """Ports, bends and trims of a double wye. `mitered` picks faceted bends over smooth ones."""
    api = context["hvac_api"]
    p = _props(context)
    roles = api.port_roles(context)
    if set(roles) != {"run_a", "run_b", "branch_a", "branch_b"}:
        raise ValueError("A double wye needs four ports, two of them forming a straight run")
    run_a, run_b = roles["run_a"], roles["run_b"]
    ports = [run_a, run_b, roles["branch_a"], roles["branch_b"]]
    center = api.center_from_context(context)
    cuts = max(int(p.get("NumberOfCuts", 2) or 2), 1)
    wall = _wall_thickness(context)

    bends = []
    for branch in ports[2:]:
        branch_dir = api.unit(api.port_direction(branch))
        # The branch turns away from the run leg it makes the wider angle
        # with (air coming from that leg takes the gentle turn into it).
        from_leg = min((run_a, run_b), key=lambda leg: branch_dir.dot(api.unit(api.port_direction(leg))))
        radius = _branch_bend_radius(api, p.get("BranchRadius"), branch, from_leg, center, wall)
        # A port on the trunk axis, where the branch axis meets it, heading out along that run leg.
        trunk_axis_port = api.copy_port(
            branch, position=_port_axis_point(api, branch, center), direction=api.port_direction(from_leg)
        )
        shape, branch_trim = _double_wye_bend(api, branch, trunk_axis_port, from_leg, radius, cuts, mitered, wall)
        bends.append(
            {
                "branch": branch,
                "from_leg": from_leg,
                "trunk_axis_port": trunk_axis_port,
                "radius": radius,
                "shape": shape,
                "branch_trim": branch_trim,
            }
        )

    # Each port's body has to contain the other ports' sections and the bends themselves.
    minimums = _junction_minimums(api, center, ports)
    minimums = _junction_shape_minimums(api, center, ports, api.compound([b["shape"] for b in bends]), minimums)
    for index, bend in enumerate(bends, start=2):
        minimums[index] = max(minimums[index], bend["branch_trim"])
    trims = _junction_trims(api, p, ports, _CROSS_TRIM_NAMES, (0.4, 0.4, 0.6, 0.6), minimums)
    return {"ports": ports, "center": center, "cuts": cuts, "wall": wall, "bends": bends, "trims": trims}


def _build_double_wye(context, mitered):
    api = context["hvac_api"]
    layout = _double_wye_layout(context, mitered)
    ports, center, trims = layout["ports"], layout["center"], layout["trims"]
    run_a, run_b = ports[0], ports[1]

    def envelope(offset):
        shape = _loft(api, [_trimmed(api, run_a, trims[0]), _trimmed(api, run_b, trims[1])], offset)
        for index, bend in enumerate(layout["bends"], start=2):
            # The layout already built the air-space bend to measure it;
            # only a wall envelope (offset > 0) needs it built again, larger.
            if offset > 0.0:
                bend_shape, _trim = _double_wye_bend(
                    api,
                    bend["branch"],
                    bend["trunk_axis_port"],
                    bend["from_leg"],
                    bend["radius"],
                    layout["cuts"],
                    mitered,
                    layout["wall"],
                    offset,
                )
            else:
                bend_shape = bend["shape"]
            bend_shape = _extend_leg(api, bend_shape, bend["branch"], bend["branch_trim"], trims[index], offset)
            shape = api.fuse(shape, bend_shape)
        return _clip_junction_to_body(api, shape, center, ports, trims)

    port_roles = {port.get("edge_key"): role for port, role in zip(ports, _CROSS_ROLES)}
    return _finish(context, envelope, _cross_lengths(api, ports, trims), port_roles)


def measure_double_wye_radius(context):
    api = context["hvac_api"]
    layout = _double_wye_layout(context, mitered=False)
    return _cross_lengths(api, layout["ports"], layout["trims"])


def build_double_wye_radius(context):
    """Double wye whose two branches leave the trunk through smooth-radius bends."""
    return _build_double_wye(context, mitered=False)


def measure_double_wye_mitered(context):
    api = context["hvac_api"]
    layout = _double_wye_layout(context, mitered=True)
    return _cross_lengths(api, layout["ports"], layout["trims"])


def build_double_wye_mitered(context):
    """Double wye whose two branches leave the trunk through mitered (faceted) bends."""
    return _build_double_wye(context, mitered=True)
