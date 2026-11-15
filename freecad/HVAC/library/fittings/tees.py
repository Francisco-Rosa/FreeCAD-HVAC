# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the HVAC addon.

"""
Tees: straight, radius (edge- or centre-aligned), mitered-shoe and lateral tees.
"""

from ._common import (
    _clip_branch_at_trunk_center,
    _clip_junction_to_body,
    _extend_leg,
    _extra_trim,
    _finish,
    _junction_minimums,
    _junction_shape_minimums,
    _junction_trims,
    _lean_port,
    _loft,
    _min_bend_radius,
    _mitered_bend,
    _port_axis_point,
    _positive,
    _props,
    _size,
    _trimmed,
    _wall_thickness,
)
from .stars import _star_body
from .taps import build_face_tap, face_tap_layout, measure_face_tap, with_branch_jog


def _star_tee_layout(context, run_factor, branch_factor):
    api = context["hvac_api"]
    run_a, run_b, branch = api.run_branch_ports(context)
    p = _props(context)

    center = api.center_from_context(context)
    tee_ports = [run_a, run_b, branch]
    minimums = _junction_minimums(api, center, tee_ports)
    trims = _junction_trims(
        api, p, tee_ports, ("TrimRunA", "TrimRunB", "TrimBranch"), (run_factor, run_factor, branch_factor), minimums
    )
    return run_a, run_b, branch, center, minimums, trims


def measure_star_tee(context, run_factor, branch_factor):
    api = context["hvac_api"]
    run_a, run_b, branch, center, minimums, trims = _star_tee_layout(context, run_factor, branch_factor)
    return api.build_trim_rec_from_port_lengths([(run_a, trims[0]), (run_b, trims[1]), (branch, trims[2])])


def _star_tee(context, run_factor, branch_factor):
    """Straight-legged tee with trims measured beyond the intrinsic junction body."""
    api = context["hvac_api"]
    run_a, run_b, branch, center, minimums, trims = _star_tee_layout(context, run_factor, branch_factor)

    def envelope(offset):
        return _star_body(api, center, [run_a, run_b, branch], trims, minimums, branch=branch, offset=offset)

    lengths = api.build_trim_rec_from_port_lengths([(run_a, trims[0]), (run_b, trims[1]), (branch, trims[2])])
    return _finish(context, envelope, lengths)


def _run_surface_along_branch(api, center, run_a, run_b, branch_dir):
    """Find where a branch ray actually enters the run's surface, and how
    deep the run extends beyond that surface along the branch, from the
    real run profile geometry -- not a Width/Height or bounding-radius
    assumption, so this works the same for Circular/Rectangular/Oval runs.

    Mirrors the surface-intersection math ``_lateral_tee_layout()`` already
    uses for the lateral tee's own branch surface, generalized to also
    report the run's total depth along the branch ray (needed to tell
    whether a curved/mitred branch shoe can actually fit inside the run).

    Step 1: split the branch direction into the part along the run's own
    axis and the part transverse (perpendicular) to it -- a branch running
    parallel to the run has no well-defined surface to meet.
    Step 2: project the run's own profile onto that transverse direction to
    find its near (branch-side) and far surfaces, then rescale by the
    branch/run angle to turn those into real distances measured along the
    branch ray itself.
    """
    run_dir = api.unit(api.port_direction(run_a))
    transverse = branch_dir - run_dir * branch_dir.dot(run_dir)
    sin_angle = transverse.Length
    if sin_angle <= api.EPS:
        raise ValueError("Branch is parallel to the run; no run surface to meet")
    surface_dir = api.unit(transverse)

    center_projection = center.dot(surface_dir)
    near_projection = None
    far_projection = None
    for run_port in (run_a, run_b):
        centered_port = api.copy_port(run_port, position=center)
        run_profile = api.profile_from_port(centered_port)
        p_min, p_max = api.profile_projection_bounds(run_profile, surface_dir)
        near_projection = p_max if near_projection is None else max(near_projection, p_max)
        far_projection = p_min if far_projection is None else min(far_projection, p_min)

    normal_surface_depth = near_projection - center_projection
    normal_run_depth = near_projection - far_projection
    if normal_run_depth <= api.EPS:
        raise ValueError("Run profile has zero depth")

    branch_surface_distance = normal_surface_depth / sin_angle
    run_depth_along_branch = normal_run_depth / sin_angle
    run_surface = center + branch_dir * branch_surface_distance

    return run_surface, branch_surface_distance, run_depth_along_branch


def _radius_tee_layout(context, run_factor, branch_factor, branch_alignment):
    """Layout for a radius tee with an edge- or center-aligned branch.

    Edge alignment splits a rectangular main profile between the branch and
    minor run. Center alignment brings both paths into the full main profile.

    TrimBranch is additional straight length beyond the intrinsic curved
    fitting body, not distance measured from the run surface.
    """
    api = context["hvac_api"]
    run_a, run_b, branch = api.run_branch_ports(context)
    p = _props(context)
    center = api.center_from_context(context)
    tee_ports = [run_a, run_b, branch]
    if branch_alignment not in {"edge", "center"}:
        raise ValueError("Radius tee branch alignment must be 'edge' or 'center'")

    all_rectangular = all(api.port_profile(port) == "Rectangular" for port in tee_ports)
    if branch_alignment == "edge" and not all_rectangular:
        raise ValueError("Radius tee requires rectangular profiles on all three ports")

    branch_size = _size(api, branch)
    radius = _positive(p.get("BranchRadius"), branch_factor * branch_size)

    main = _lean_port(api, run_a, run_b, branch, reverse=bool(p.get("ReverseBranchBend", False)))
    minor = run_b if main is run_a else run_a
    if branch_alignment == "center":
        # The full destination profile needs non-zero clearance around the
        # inner bend; an exact half-size radius produces degenerate sweeps.
        bend_size = max(branch_size, _size(api, main))
        radius = max(radius, _min_bend_radius(bend_size, _wall_thickness(context)))
    else:
        radius = max(radius, _min_bend_radius(branch_size, _wall_thickness(context)))
    inner_position = _port_axis_point(api, main, center)
    run_dir = api.unit(api.port_direction(main))

    if branch_alignment == "edge":
        # Cap only the internal sections; connected duct dimensions stay intact.
        main_width = api.port_width(main)
        branch_width = min(api.port_width(branch), main_width)
        minor_width = min(api.port_width(minor), main_width)
        main_height = api.port_height(main)
        if min(branch_width, minor_width, main_height) <= api.EPS:
            raise ValueError("Radius tee widths and main trunk height must be positive")

        _, horizontal, _, _ = api.make_profile_frame(api.port_direction(main), api.port_profile_x_axis(main), center)
        branch_dir = api.unit(api.port_direction(branch))
        if abs(branch_dir.dot(horizontal)) <= api.EPS:
            raise ValueError("Radius tee branch must separate along the main trunk width")
        if branch_dir.dot(horizontal) < 0.0:
            horizontal = horizontal * -1.0

        # Anchor the inner sections to opposite main-profile edges.
        trunk_axis_port = api.copy_port(main, position=inner_position)
        trunk_axis_port["section_params"] = dict(api.port_section_params(main), Width=branch_width, Height=main_height)
        main_profile = api.profile_from_port(api.copy_port(main, position=inner_position))
        opposite_edge, main_edge = api.profile_projection_bounds(main_profile, horizontal)
        main_midpoint = 0.5 * (opposite_edge + main_edge)
        inner_profile = api.profile_from_port(trunk_axis_port)
        _, inner_edge = api.profile_projection_bounds(inner_profile, horizontal)
        shift = main_edge - inner_edge
        trunk_axis_port = api.copy_port(trunk_axis_port, position=inner_position + horizontal * shift)
    else:
        # The branch sweep ends at the centered, full main profile.
        trunk_axis_port = api.copy_port(main, position=inner_position)

    route = api.make_elbow_path(branch, trunk_axis_port, radius)
    branch_route_trim = route["trim_lengths"][0]

    # Use one main-axis shift for both generated ports and the main inner
    # port, keeping all three on the same tangent plane.
    base_position = api.port_position(trunk_axis_port)
    tangent_position = api.port_position(route["ports"][1])
    axial_shift = run_dir * (tangent_position - base_position).dot(run_dir)
    branch_trunk_port = api.copy_port(trunk_axis_port, position=base_position + axial_shift)
    route["ports"][1] = branch_trunk_port

    if branch_alignment == "edge":
        # Anchor the minor section to the opposite edge. Overlap is allowed.
        minor_shift = opposite_edge + 0.5 * minor_width - base_position.dot(horizontal)
        minor_trunk_port = api.copy_port(
            trunk_axis_port, position=base_position + horizontal * minor_shift + axial_shift
        )
        minor_trunk_port["section_params"] = dict(api.port_section_params(main), Width=minor_width, Height=main_height)
        # Keep the main body centered and on the same tangent plane.
        main_inner_port = api.copy_port(
            main, position=base_position + horizontal * (main_midpoint - base_position.dot(horizontal)) + axial_shift
        )
    else:
        # The minor run also lofts into the centered, full main profile.
        tangent_center = base_position + axial_shift
        minor_trunk_port = api.copy_port(main, position=tangent_center)
        main_inner_port = api.copy_port(main, position=tangent_center)

    # Size the layout from the actual path and connection sections, without
    # adding a guessed allowance for the swept body's intermediate sections.
    minimums = _junction_minimums(api, center, tee_ports)
    inner_ports = [*route["ports"], minor_trunk_port, main_inner_port]
    layout_shapes = [route["path"]] + [api.profile_from_port(port) for port in inner_ports]
    for index, port in enumerate(tee_ports):
        direction = api.unit(api.port_direction(port))
        port_projection = api.port_position(port).dot(direction)
        for shape in layout_shapes:
            _, extent = api.profile_projection_bounds(shape, direction)
            minimums[index] = max(minimums[index], extent - port_projection)
    minimums[2] = max(minimums[2], branch_route_trim)

    main_index = 0 if main is run_a else 1
    # Leave space for the inner section to transition into the main port,
    # even when the requested extra trim is zero.
    main_reach = (api.port_position(main_inner_port) - api.port_position(main)).dot(run_dir)
    minimums[main_index] = max(minimums[main_index], main_reach + run_factor * _size(api, main))

    trims = _junction_trims(
        api, p, tee_ports, ("TrimRunA", "TrimRunB", "TrimBranch"), (run_factor, run_factor, branch_factor), minimums
    )

    return {
        "run_a": run_a,
        "run_b": run_b,
        "branch": branch,
        "center": center,
        "main": main,
        "minor": minor,
        "minor_trunk_port": minor_trunk_port,
        "main_inner_port": main_inner_port,
        "route": route,
        "trims": trims,
    }


def _radius_tee_connection_lengths(api, layout):
    return api.build_trim_rec_from_port_lengths(
        [
            (layout["run_a"], layout["trims"][0]),
            (layout["run_b"], layout["trims"][1]),
            (layout["branch"], layout["trims"][2]),
        ]
    )


def _measure_radius_tee(context, run_factor, branch_factor, branch_alignment):
    api = context["hvac_api"]
    layout = _radius_tee_layout(context, run_factor, branch_factor, branch_alignment)
    return _radius_tee_connection_lengths(api, layout)


def _radius_tee(context, run_factor, branch_factor, branch_alignment):
    api = context["hvac_api"]
    layout = _radius_tee_layout(context, run_factor, branch_factor, branch_alignment)

    run_a = layout["run_a"]
    run_b = layout["run_b"]
    branch = layout["branch"]
    center = layout["center"]
    trims = layout["trims"]
    route = layout["route"]

    branch_start = route["ports"][0]
    branch_end = _trimmed(api, branch, trims[2])
    branch_reach = api.port_position(branch_end) - api.port_position(branch_start)
    main_index = 0 if layout["main"] is run_a else 1
    minor_index = 1 - main_index
    main_inner_port = layout["main_inner_port"]
    if branch_alignment == "center":
        # Cross the shared tangent plane slightly so OCC fuses the three
        # full-profile bodies by volume instead of a coincident face.
        overlap = max(1.0, 0.01 * _size(api, layout["main"]))
        main_inner_port = api.copy_port(
            main_inner_port,
            position=api.port_position(main_inner_port) - api.unit(api.port_direction(layout["main"])) * overlap,
        )

    def envelope(offset):
        # Build the curved body only here; measurement uses the shared layout.
        stub = api.sweep([api.profile_from_port(port, offset) for port in route["ports"]], route["path"], solid=True)

        # Start the branch extension at the sweep's actual end section. A trim
        # length can be clamped, so reconstructing that section can leave a gap.
        if branch_reach.Length > api.EPS:
            stub = api.fuse(stub, _loft(api, [branch_start, branch_end], offset))

        # Loft the minor trunk into its own section, then join both sections
        # to the full main trunk. The branch sweep keeps its entire profile.
        minor_end = _trimmed(api, layout["minor"], trims[minor_index])
        minor_body = _loft(api, [minor_end, layout["minor_trunk_port"]], offset)
        main_body = _loft(api, [main_inner_port, _trimmed(api, layout["main"], trims[main_index])], offset)
        shape = api.fuse(main_body, minor_body, stub)
        return _clip_junction_to_body(api, shape, center, [run_a, run_b, branch], trims)

    return _finish(context, envelope, _radius_tee_connection_lengths(api, layout))


def measure_radius_tee_edge(context, run_factor, branch_factor):
    return _measure_radius_tee(context, run_factor, branch_factor, "edge")


def _radius_tee_edge(context, run_factor, branch_factor):
    return _radius_tee(context, run_factor, branch_factor, "edge")


def measure_radius_tee_center(context, run_factor, branch_factor):
    return _measure_radius_tee(context, run_factor, branch_factor, "center")


def _radius_tee_center(context, run_factor, branch_factor):
    return _radius_tee(context, run_factor, branch_factor, "center")


@with_branch_jog(centred=True)
def measure_tee_radius_edge(context):
    # A branch passing over or under the run is face-mounted instead (see taps.face_tap_layout).
    face = face_tap_layout(context)
    if face is not None:
        return measure_face_tap(context, face)
    return measure_radius_tee_edge(context, 0.4, 0.6)


@with_branch_jog(centred=True)
def build_tee_radius_edge(context):
    # A branch passing over or under the run is face-mounted instead (see taps.face_tap_layout).
    face = face_tap_layout(context)
    if face is not None:
        return build_face_tap(context, face)
    return _radius_tee_edge(context, 0.4, 0.6)


@with_branch_jog(centred=True)
def measure_tee_radius_center(context):
    # A branch passing over or under the run is face-mounted instead (see taps.face_tap_layout).
    face = face_tap_layout(context)
    if face is not None:
        return measure_face_tap(context, face)
    return measure_radius_tee_center(context, 0.4, 0.6)


@with_branch_jog(centred=True)
def build_tee_radius_center(context):
    # A branch passing over or under the run is face-mounted instead (see taps.face_tap_layout).
    face = face_tap_layout(context)
    if face is not None:
        return build_face_tap(context, face)
    return _radius_tee_center(context, 0.4, 0.6)


@with_branch_jog
def measure_tee_straight(context):
    # A branch passing over or under the run is face-mounted instead (see taps.face_tap_layout).
    face = face_tap_layout(context)
    if face is not None:
        return measure_face_tap(context, face)
    return measure_star_tee(context, 0.60, 0.60)


@with_branch_jog
def build_tee_straight(context):
    # A branch passing over or under the run is face-mounted instead (see taps.face_tap_layout).
    face = face_tap_layout(context)
    if face is not None:
        return build_face_tap(context, face)
    api = context["hvac_api"]
    run_a, run_b, branch, center, _, trims = _star_tee_layout(context, 0.60, 0.60)

    branch_end = _trimmed(api, branch, trims[2])
    branch_center = api.copy_port(branch, position=_port_axis_point(api, branch, center))

    def envelope(offset):
        # Build the run as one continuous trunk, matching the radius tee.
        trunk = _loft(api, [_trimmed(api, run_a, trims[0]), _trimmed(api, run_b, trims[1])], offset)

        # Join a straight branch stub at the trunk center plane.
        stub = _loft(api, [branch_end, branch_center], offset)
        stub = _clip_branch_at_trunk_center(api, stub, center, branch)

        shape = api.fuse(trunk, stub)
        return _clip_junction_to_body(api, shape, center, [run_a, run_b, branch], trims)

    return _finish(
        context,
        envelope,
        api.build_trim_rec_from_port_lengths([(run_a, trims[0]), (run_b, trims[1]), (branch, trims[2])]),
    )


def _tee_mitered_shoe_layout(context):
    """Layout for a mitered-shoe tee.

    The theoretical bend corner lies on the branch axis. The mitered bend
    is limited at the trunk center plane before it is fused with the run.

    TrimBranch is additional length beyond the intrinsic mitered body.
    """
    api = context["hvac_api"]
    run_a, run_b, branch = api.run_branch_ports(context)
    p = _props(context)
    center = api.center_from_context(context)
    tee_ports = [run_a, run_b, branch]

    branch_size = _size(api, branch)
    radius = _positive(p.get("BranchRadius"), 0.6 * branch_size)
    radius = max(radius, _min_bend_radius(branch_size, _wall_thickness(context)))
    cuts = max(int(p.get("NumberOfCuts", 1) or 1), 1)

    lean = _lean_port(api, run_a, run_b, branch, reverse=bool(p.get("ReverseBranchBend", False)))
    inner_position = _port_axis_point(api, branch, center)
    trunk_axis_port = api.copy_port(branch, position=inner_position, direction=api.port_direction(lean))

    bend_shape, route_trims = _mitered_bend(api, branch, trunk_axis_port, radius, cuts)
    branch_route_trim, lean_route_trim = route_trims

    minimums = _junction_minimums(api, center, tee_ports)
    minimums = _junction_shape_minimums(api, center, tee_ports, bend_shape, minimums)
    minimums[2] = max(minimums[2], branch_route_trim)

    lean_index = 0 if lean is run_a else 1
    minimums[lean_index] = max(minimums[lean_index], lean_route_trim)

    trims = _junction_trims(api, p, tee_ports, ("TrimRunA", "TrimRunB", "TrimBranch"), (0.4, 0.4, 0.6), minimums)

    return {
        "run_a": run_a,
        "run_b": run_b,
        "branch": branch,
        "center": center,
        "lean": lean,
        "trunk_axis_port": trunk_axis_port,
        "radius": radius,
        "cuts": cuts,
        "bend_shape": bend_shape,
        "branch_route_trim": branch_route_trim,
        "lean_route_trim": lean_route_trim,
        "trims": trims,
    }


@with_branch_jog
def measure_tee_mitered_shoe(context):
    # A branch passing over or under the run is face-mounted instead (see taps.face_tap_layout).
    face = face_tap_layout(context, collar="shoe")
    if face is not None:
        return measure_face_tap(context, face)
    api = context["hvac_api"]
    layout = _tee_mitered_shoe_layout(context)

    return api.build_trim_rec_from_port_lengths(
        [
            (layout["run_a"], layout["trims"][0]),
            (layout["run_b"], layout["trims"][1]),
            (layout["branch"], layout["trims"][2]),
        ]
    )


@with_branch_jog
def build_tee_mitered_shoe(context):
    # A branch passing over or under the run is face-mounted instead (see taps.face_tap_layout).
    face = face_tap_layout(context, collar="shoe")
    if face is not None:
        return build_face_tap(context, face)
    api = context["hvac_api"]
    layout = _tee_mitered_shoe_layout(context)

    run_a = layout["run_a"]
    run_b = layout["run_b"]
    branch = layout["branch"]
    center = layout["center"]
    trims = layout["trims"]

    def envelope(offset):
        # The layout already built the air-space bend to measure it; only a
        # wall envelope (offset > 0) needs the bend built again, larger.
        if offset > 0.0:
            bend_shape = _mitered_bend(
                api, branch, layout["trunk_axis_port"], layout["radius"], layout["cuts"], offset=offset
            )[0]
        else:
            bend_shape = layout["bend_shape"]
        bend_shape = _extend_leg(api, bend_shape, branch, layout["branch_route_trim"], trims[2], offset)
        trunk = _loft(api, [_trimmed(api, run_a, trims[0]), _trimmed(api, run_b, trims[1])], offset)
        bend_shape = _clip_branch_at_trunk_center(api, bend_shape, center, branch)
        shape = api.fuse(trunk, bend_shape)
        return _clip_junction_to_body(api, shape, center, [run_a, run_b, branch], trims)

    return _finish(
        context,
        envelope,
        api.build_trim_rec_from_port_lengths([(run_a, trims[0]), (run_b, trims[1]), (branch, trims[2])]),
    )


def _lateral_tee_layout(context):
    api = context["hvac_api"]
    run_a, run_b, branch = api.run_branch_ports(context)
    p = _props(context)

    center = api.center_from_context(context)
    branch_dir = api.unit(api.port_direction(branch))
    branch_axis_center = _port_axis_point(api, branch, center)
    lean = _lean_port(api, run_a, run_b, branch)
    run_dir = api.unit(api.port_direction(lean))

    transverse = branch_dir - run_dir * branch_dir.dot(run_dir)
    sin_angle = transverse.Length
    if sin_angle <= api.EPS:
        raise ValueError("Lateral tee branch is parallel to the run")
    surface_dir = api.unit(transverse)

    center_projection = branch_axis_center.dot(surface_dir)
    surface_projection = None
    for run_port in (run_a, run_b):
        centered_port = api.copy_port(run_port, position=center)
        run_profile = api.profile_from_port(centered_port)
        _, p_max = api.profile_projection_bounds(run_profile, surface_dir)
        surface_projection = p_max if surface_projection is None else max(surface_projection, p_max)

    if surface_projection is None:
        raise ValueError("Could not determine run surface")

    normal_depth = surface_projection - center_projection
    branch_depth = normal_depth / sin_angle
    run_surface = branch_axis_center + branch_dir * branch_depth
    surface_port = api.copy_port(branch, position=run_surface)
    surface_profile = api.profile_from_port(surface_port)

    run_a_dir = api.unit(api.port_direction(run_a))
    run_b_dir = api.unit(api.port_direction(run_b))
    _, max_a = api.profile_projection_bounds(surface_profile, run_a_dir)
    _, max_b = api.profile_projection_bounds(surface_profile, run_b_dir)
    min_a = max(0.0, max_a - center.dot(run_a_dir))
    min_b = max(0.0, max_b - center.dot(run_b_dir))

    trim_a = min_a + _extra_trim(p.get("TrimRunA"), 0.65 * _size(api, run_a))
    trim_b = min_b + _extra_trim(p.get("TrimRunB"), 0.65 * _size(api, run_b))

    branch_min = max(0.0, (run_surface - api.port_position(branch)).dot(branch_dir))
    trim_branch = branch_min + _extra_trim(p.get("TrimBranch"), 0.65 * _size(api, branch))

    return {
        "run_a": run_a,
        "run_b": run_b,
        "branch": branch,
        "center": center,
        "branch_dir": branch_dir,
        "run_surface": run_surface,
        "surface_profile": surface_profile,
        "trim_a": trim_a,
        "trim_b": trim_b,
        "trim_branch": trim_branch,
    }


@with_branch_jog
def measure_lateral_tee(context):
    # A branch passing over or under the run is face-mounted instead (see taps.face_tap_layout):
    # the collar rises square to the run, and its elbow turns into the inclined branch.
    face = face_tap_layout(context)
    if face is not None:
        return measure_face_tap(context, face)
    api = context["hvac_api"]
    layout = _lateral_tee_layout(context)
    return api.build_trim_rec_from_port_lengths(
        [
            (layout["run_a"], layout["trim_a"]),
            (layout["run_b"], layout["trim_b"]),
            (layout["branch"], layout["trim_branch"]),
        ]
    )


@with_branch_jog
def build_lateral_tee(context):
    """Straight lateral tee with a continuous run trunk and branch stub.

    TrimRunA/TrimRunB are measured beyond the minimum branch footprint.
    TrimBranch is measured outward from the inclined run surface.
    """
    # A branch passing over or under the run is face-mounted instead (see taps.face_tap_layout):
    # the collar rises square to the run, and its elbow turns into the inclined branch.
    face = face_tap_layout(context)
    if face is not None:
        return build_face_tap(context, face)
    api = context["hvac_api"]
    layout = _lateral_tee_layout(context)
    run_a, run_b, branch, center = layout["run_a"], layout["run_b"], layout["branch"], layout["center"]
    trim_a, trim_b, trim_branch = layout["trim_a"], layout["trim_b"], layout["trim_branch"]

    branch_end = _trimmed(api, branch, trim_branch)
    branch_axis_center = _port_axis_point(api, branch, center)
    branch_dir = api.port_direction(branch)
    trunk_dir = api.port_direction(run_a)

    # Run the stub's inner end slightly past the trunk axis. Stopping it
    # exactly on the axis leaves a knife edge there once the inclined clip
    # plane below has cut it, and the fuse with the trunk can then fail
    # (seen on a circular branch at exactly 45 degrees).
    embed = max(0.01 * _size(api, branch), 2.0)
    branch_center = api.copy_port(branch, position=branch_axis_center - api.unit(branch_dir) * embed)

    # The branch stub is cut on a plane perpendicular to the wye plane. Its
    # normal stays in the wye plane and points from the trunk axis toward
    # the branch.
    wye_plane_normal = api.unit(trunk_dir.cross(branch_dir))
    clip_normal = api.unit(wye_plane_normal.cross(trunk_dir))

    def envelope(offset):
        # Build the run as one continuous trunk, matching the straight tee.
        trunk = _loft(api, [_trimmed(api, run_a, trim_a), _trimmed(api, run_b, trim_b)], offset)

        # Join a straight branch stub at the trunk center plane.
        branch_stub = _loft(api, [branch_end, branch_center], offset)
        branch_stub = api.clip_plane(branch_stub, (branch_axis_center, clip_normal), side="positive")
        # Keep the stub inside the run body, so nothing pokes out past the run's own end planes.
        branch_stub = _clip_junction_to_body(api, branch_stub, center, [run_a, run_b], [trim_a, trim_b])
        return api.fuse(trunk, branch_stub)

    lengths = api.build_trim_rec_from_port_lengths([(run_a, trim_a), (run_b, trim_b), (branch, trim_branch)])
    return _finish(context, envelope, lengths)


# ----------------------------------------------------------------------
# Lateral tees with a bend: the run stays full and straight, and the
# branch joins it through a smooth-radius or mitered bend -- the same bend
# a double wye's branches use (crosses._double_wye_bend).
# ----------------------------------------------------------------------


def _lateral_bend_layout(context, mitered):
    """Ports, branch bend and trims of a lateral tee whose branch joins through a bend."""
    from .crosses import _branch_bend_radius, _double_wye_bend

    api = context["hvac_api"]
    p = _props(context)
    run_a, run_b, branch = api.run_branch_ports(context)
    ports = [run_a, run_b, branch]
    center = api.center_from_context(context)
    cuts = max(int(p.get("NumberOfCuts", 2) or 2), 1)

    # The branch turns away from the run leg it makes the wider angle with,
    # so air coming along the run takes the gentle turn into the branch.
    branch_dir = api.unit(api.port_direction(branch))
    from_leg = min((run_a, run_b), key=lambda leg: branch_dir.dot(api.unit(api.port_direction(leg))))
    radius = _branch_bend_radius(api, p.get("BranchRadius"), branch, from_leg, center, _wall_thickness(context))
    trunk_axis_port = api.copy_port(
        branch, position=_port_axis_point(api, branch, center), direction=api.port_direction(from_leg)
    )
    bend_shape, branch_trim = _double_wye_bend(api, branch, trunk_axis_port, radius, cuts, mitered)

    # Each port's body has to contain the other sections and the bend itself.
    minimums = _junction_minimums(api, center, ports)
    minimums = _junction_shape_minimums(api, center, ports, bend_shape, minimums)
    minimums[2] = max(minimums[2], branch_trim)
    trims = _junction_trims(api, p, ports, ("TrimRunA", "TrimRunB", "TrimBranch"), (0.4, 0.4, 0.6), minimums)
    return {
        "ports": ports,
        "center": center,
        "cuts": cuts,
        "radius": radius,
        "trunk_axis_port": trunk_axis_port,
        "bend_shape": bend_shape,
        "branch_trim": branch_trim,
        "trims": trims,
    }


@with_branch_jog
def _measure_lateral_bend(context, mitered):
    # A branch passing over or under the run is face-mounted instead (see taps.face_tap_layout):
    # the collar rises square to the run, and its elbow turns into the inclined branch.
    face = face_tap_layout(context)
    if face is not None:
        return measure_face_tap(context, face)
    api = context["hvac_api"]
    layout = _lateral_bend_layout(context, mitered)
    return api.build_trim_rec_from_port_lengths(list(zip(layout["ports"], layout["trims"])))


@with_branch_jog
def _build_lateral_bend(context, mitered):
    from .crosses import _double_wye_bend

    # A branch passing over or under the run is face-mounted instead (see taps.face_tap_layout):
    # the collar rises square to the run, and its elbow turns into the inclined branch.
    face = face_tap_layout(context)
    if face is not None:
        return build_face_tap(context, face)
    api = context["hvac_api"]
    layout = _lateral_bend_layout(context, mitered)
    run_a, run_b, branch = layout["ports"]
    center, trims = layout["center"], layout["trims"]

    def envelope(offset):
        trunk = _loft(api, [_trimmed(api, run_a, trims[0]), _trimmed(api, run_b, trims[1])], offset)
        # The layout already built the air-space bend to measure it; only a
        # wall envelope (offset > 0) needs it built again, larger.
        if offset > 0.0:
            bend, _trim = _double_wye_bend(
                api, branch, layout["trunk_axis_port"], layout["radius"], layout["cuts"], mitered, offset
            )
        else:
            bend = layout["bend_shape"]
        bend = _extend_leg(api, bend, branch, layout["branch_trim"], trims[2], offset)
        return _clip_junction_to_body(api, api.fuse(trunk, bend), center, layout["ports"], trims)

    lengths = api.build_trim_rec_from_port_lengths(list(zip(layout["ports"], trims)))
    roles = {run_a.get("edge_key"): "RunA", run_b.get("edge_key"): "RunB", branch.get("edge_key"): "Branch"}
    return _finish(context, envelope, lengths, roles)


def measure_lateral_tee_radius(context):
    return _measure_lateral_bend(context, mitered=False)


def build_lateral_tee_radius(context):
    """Lateral tee: full straight run, the branch joining it through a smooth-radius bend."""
    return _build_lateral_bend(context, mitered=False)


def measure_lateral_tee_mitered(context):
    return _measure_lateral_bend(context, mitered=True)


def build_lateral_tee_mitered(context):
    """Lateral tee: full straight run, the branch joining it through a mitered bend."""
    return _build_lateral_bend(context, mitered=True)
