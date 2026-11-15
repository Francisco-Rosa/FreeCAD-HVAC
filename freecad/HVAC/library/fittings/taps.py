# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the HVAC addon.

"""
Taps: a branch collar attached to the surface of a continuous run
(straight, saddle and shoe taps).
"""

import functools
import math

from ._common import (
    _clip_branch_at_trunk_center,
    _extra_trim,
    _finish,
    _lean_port,
    _loft,
    _min_bend_radius,
    _port_axis_point,
    _positive,
    _props,
    _size,
    _trimmed,
    _wall_thickness,
    jog_records,
)


def _tap_geometry(context, api, run_a, run_b, branch):
    """Return common profile-independent geometry for tap fittings."""
    trunk_center = api.center_from_context(context)
    branch_dir = api.unit(api.port_direction(branch))
    lean = _lean_port(api, run_a, run_b, branch)
    lean_dir = api.unit(api.port_direction(lean))

    toe_dir = lean_dir - branch_dir * lean_dir.dot(branch_dir)
    if toe_dir.Length <= api.EPS:
        raise ValueError("Tap requires a non-degenerate branch/run angle")
    toe_dir = api.unit(toe_dir)

    branch_axis_center = _port_axis_point(api, branch, trunk_center)
    branch_center = api.copy_port(branch, position=branch_axis_center)
    branch_profile = api.profile_from_port(branch_center)
    branch_min, branch_max = api.profile_projection_bounds(branch_profile, toe_dir)
    branch_width = max(branch_max - branch_min, 1.0)

    center_projection = branch_axis_center.dot(branch_dir)
    near_projection = None
    far_projection = None
    for run_port in (run_a, run_b):
        centered_port = api.copy_port(run_port, position=trunk_center)
        run_profile = api.profile_from_port(centered_port)
        p_min, p_max = api.profile_projection_bounds(run_profile, branch_dir)
        near_projection = p_max if near_projection is None else max(near_projection, p_max)
        far_projection = p_min if far_projection is None else min(far_projection, p_min)

    run_depth = near_projection - far_projection
    if run_depth <= api.EPS:
        raise ValueError("Tap run profile has zero depth")

    run_surface_offset = near_projection - center_projection
    run_surface = branch_axis_center + branch_dir * run_surface_offset

    # Embed to the actual mid-depth of the run. This gives a substantial
    # boolean intersection without approaching the opposite surface.
    overlap = 0.5 * run_depth

    return trunk_center, branch_dir, toe_dir, branch_width, run_depth, overlap, run_surface


def _tap_run_minimums(api, trunk_center, run_a, run_b, surface_profile):
    """Minimum run lengths required by the tap footprint at the run surface."""
    run_a_dir = api.unit(api.port_direction(run_a))
    run_b_dir = api.unit(api.port_direction(run_b))
    _, max_a = api.profile_projection_bounds(surface_profile, run_a_dir)
    _, max_b = api.profile_projection_bounds(surface_profile, run_b_dir)
    min_a = max(0.0, max_a - trunk_center.dot(run_a_dir))
    min_b = max(0.0, max_b - trunk_center.dot(run_b_dir))
    return min_a, min_b


def _tap_trims(
    api, p, run_a, run_b, branch, trunk_center, branch_dir, tap_top, surface_profile, run_factor, branch_factor
):
    """Total connection lengths = intrinsic fitting dimensions + user trims."""
    min_a, min_b = _tap_run_minimums(api, trunk_center, run_a, run_b, surface_profile)
    branch_min = max(0.0, (tap_top - api.port_position(branch)).dot(branch_dir))
    extra_a = _extra_trim(p.get("TrimRunA"), run_factor * _size(api, run_a))
    extra_b = _extra_trim(p.get("TrimRunB"), run_factor * _size(api, run_b))
    extra_branch = _extra_trim(p.get("TrimBranch"), branch_factor * _size(api, branch))
    return min_a + extra_a, min_b + extra_b, branch_min + extra_branch


def _clip_tap_to_run_body(api, shape, trunk_center, run_a, run_b, trim_a, trim_b):
    """Limit tap geometry to the calculated run-body width."""
    for port, trim in ((run_a, trim_a), (run_b, trim_b)):
        direction = api.unit(api.port_direction(port))
        plane_origin = api.port_position(port) + direction * trim
        side = "positive" if (trunk_center - plane_origin).dot(direction) >= 0.0 else "negative"
        shape = api.clip_plane(shape, (plane_origin, direction), side=side)
    return shape


def _straight_tap_layout(context, run_factor, branch_factor):
    api = context["hvac_api"]
    run_a, run_b, branch = api.run_branch_ports(context)
    p = _props(context)

    trunk_center, branch_dir, toe_dir, branch_width, run_depth, overlap, run_surface = _tap_geometry(
        context, api, run_a, run_b, branch
    )
    tap_height = _positive(p.get("TapHeight"), 0.5 * branch_width)
    tap_top = run_surface + branch_dir * tap_height
    base_position = run_surface - branch_dir * overlap

    surface_port = api.copy_port(branch, position=run_surface)
    surface_profile = api.profile_from_port(surface_port)
    trim_a, trim_b, trim_branch = _tap_trims(
        api, p, run_a, run_b, branch, trunk_center, branch_dir, tap_top, surface_profile, run_factor, branch_factor
    )

    return {
        "run_a": run_a,
        "run_b": run_b,
        "branch": branch,
        "trunk_center": trunk_center,
        "branch_dir": branch_dir,
        "base_position": base_position,
        "trim_a": trim_a,
        "trim_b": trim_b,
        "trim_branch": trim_branch,
    }


def measure_straight_tap(context, run_factor, branch_factor):
    api = context["hvac_api"]
    layout = _straight_tap_layout(context, run_factor, branch_factor)
    return api.build_trim_rec_from_port_lengths(
        [
            (layout["run_a"], layout["trim_a"]),
            (layout["run_b"], layout["trim_b"]),
            (layout["branch"], layout["trim_branch"]),
        ]
    )


def _straight_tap(context, run_factor, branch_factor):
    """Straight tap. TapHeight defines the intrinsic collar height;
    TrimBranch starts above TapHeight and run trims start beyond the
    minimum tap footprint."""
    api = context["hvac_api"]
    layout = _straight_tap_layout(context, run_factor, branch_factor)
    run_a, run_b, branch = layout["run_a"], layout["run_b"], layout["branch"]
    trunk_center, branch_dir = layout["trunk_center"], layout["branch_dir"]
    base_position = layout["base_position"]
    trim_a, trim_b, trim_branch = layout["trim_a"], layout["trim_b"], layout["trim_branch"]

    branch_end = _trimmed(api, branch, trim_branch)
    reach = max(0.0, (api.port_position(branch_end) - base_position).dot(branch_dir))

    def envelope(offset):
        trunk = _loft(api, [_trimmed(api, run_a, trim_a), _trimmed(api, run_b, trim_b)], offset)
        stub = api.extrude(api.profile_from_port(branch_end, offset), branch_dir * -reach, solid=True)
        stub = _clip_tap_to_run_body(api, stub, trunk_center, run_a, run_b, trim_a, trim_b)
        stub = _clip_branch_at_trunk_center(api, stub, trunk_center, branch)
        return api.fuse(trunk, stub)

    return _finish(
        context,
        envelope,
        api.build_trim_rec_from_port_lengths([(run_a, trim_a), (run_b, trim_b), (branch, trim_branch)]),
    )


def _saddle_tap_layout(context, run_factor, branch_factor, flare_factor=0.6):
    api = context["hvac_api"]
    run_a, run_b, branch = api.run_branch_ports(context)
    p = _props(context)

    trunk_center, branch_dir, toe_dir, branch_width, run_depth, overlap, run_surface = _tap_geometry(
        context, api, run_a, run_b, branch
    )
    tap_height = _positive(p.get("TapHeight"), 0.5 * branch_width)
    growth = _positive(p.get("SaddleGrowth"), flare_factor * branch_width)
    tap_top = run_surface + branch_dir * tap_height
    base_position = run_surface - branch_dir * overlap

    surface_port = api.copy_port(branch, position=run_surface)
    surface_profile = api.offset_profile(api.profile_from_port(surface_port), growth)

    trim_a, trim_b, trim_branch = _tap_trims(
        api, p, run_a, run_b, branch, trunk_center, branch_dir, tap_top, surface_profile, run_factor, branch_factor
    )

    return {
        "run_a": run_a,
        "run_b": run_b,
        "branch": branch,
        "trunk_center": trunk_center,
        "branch_dir": branch_dir,
        "tap_top": tap_top,
        "base_position": base_position,
        "growth": growth,
        "overlap": overlap,
        "tap_height": tap_height,
        "surface_profile": surface_profile,
        "trim_a": trim_a,
        "trim_b": trim_b,
        "trim_branch": trim_branch,
    }


def measure_saddle_tap(context, run_factor, branch_factor, flare_factor=0.6):
    api = context["hvac_api"]
    layout = _saddle_tap_layout(context, run_factor, branch_factor, flare_factor)
    return api.build_trim_rec_from_port_lengths(
        [
            (layout["run_a"], layout["trim_a"]),
            (layout["run_b"], layout["trim_b"]),
            (layout["branch"], layout["trim_branch"]),
        ]
    )


def _saddle_tap(context, run_factor, branch_factor, flare_factor=0.6):
    """Saddle tap. TapHeight defines the flare height; the embedded flare
    continues to the run mid-depth but is clipped to the tap body width."""
    api = context["hvac_api"]
    layout = _saddle_tap_layout(context, run_factor, branch_factor, flare_factor)
    run_a, run_b, branch = layout["run_a"], layout["run_b"], layout["branch"]
    trunk_center, branch_dir = layout["trunk_center"], layout["branch_dir"]
    tap_top, base_position = layout["tap_top"], layout["base_position"]
    growth, overlap, tap_height = layout["growth"], layout["overlap"], layout["tap_height"]
    trim_a, trim_b, trim_branch = layout["trim_a"], layout["trim_b"], layout["trim_branch"]

    top_port = api.copy_port(branch, position=tap_top)
    # The run surface sits one TapHeight below the tap top, along the branch axis.
    surface_port = api.copy_port(branch, position=tap_top - branch_dir * tap_height)
    base_port = api.copy_port(branch, position=base_position)
    base_growth = growth * (tap_height + overlap) / tap_height
    branch_end = _trimmed(api, branch, trim_branch)

    def envelope(offset):
        # Same flare as the layout used for the trims, with every section grown by the wall offset.
        top_profile = api.profile_from_port(top_port, offset)
        surface_profile = api.offset_profile(api.profile_from_port(surface_port, offset), growth)
        base_profile = api.offset_profile(api.profile_from_port(base_port, offset), base_growth)
        trunk = _loft(api, [_trimmed(api, run_a, trim_a), _trimmed(api, run_b, trim_b)], offset)

        profiles = [top_profile, surface_profile, base_profile]
        if (api.port_position(branch_end) - tap_top).Length > api.EPS:
            profiles.insert(0, api.profile_from_port(branch_end, offset))
        stub = api.loft(profiles, solid=True, ruled=True)
        stub = _clip_tap_to_run_body(api, stub, trunk_center, run_a, run_b, trim_a, trim_b)
        stub = _clip_branch_at_trunk_center(api, stub, trunk_center, branch)
        return api.fuse(trunk, stub)

    return _finish(
        context,
        envelope,
        api.build_trim_rec_from_port_lengths([(run_a, trim_a), (run_b, trim_b), (branch, trim_branch)]),
    )


# ----------------------------------------------------------------------
# Face-mounted taps: the branch passes over (or under) the run.
#
# A branch whose own axis misses the run body cannot leave through the
# run's side. It is mounted on the face it passes over instead: a straight
# collar rises from that face to the branch's own level, and a 90 degree
# elbow turns it into the branch direction. The collar axis is the common
# perpendicular of the run axis and the branch axis, so the turn is always
# exactly 90 degrees, whatever the angle between run and branch.
# ----------------------------------------------------------------------

ATTACHMENT_AUTO = "Auto"
ATTACHMENT_SIDE = "Side"
ATTACHMENT_FACE = "Face"


def _attachment_offsets(api, run_a, run_b, branch):
    """
    How far the branch axis passes from the run axis, and how that compares
    with the two ducts' own sizes in that direction. Returns None when the
    two axes meet (an ordinary tee) or are parallel; otherwise a dict:

      q_run, q_branch: the closest points of the two axes
      up:              unit vector from the run axis toward the branch axis
      offset:          distance between the axes
      run_half:        run surface height above its own axis, along `up`
      branch_half:     branch half-size along `up`
    """
    run_dir = api.unit(api.port_direction(run_a))
    branch_dir = api.unit(api.port_direction(branch))
    q_run, q_branch = api.closest_points_on_lines(
        api.port_position(run_a), run_dir, api.port_position(branch), branch_dir
    )
    if q_run is None:
        return None
    gap = q_branch - q_run
    if gap.Length <= 1.0e-6:
        return None
    up = api.unit(gap)

    def half_size(port, at):
        profile = api.profile_from_port(api.copy_port(port, position=at))
        _low, high = api.profile_projection_bounds(profile, up)
        return high - at.dot(up)

    return {
        "q_run": q_run,
        "q_branch": q_branch,
        "up": up,
        "offset": gap.Length,
        "run_half": max(half_size(run_a, q_run), half_size(run_b, q_run)),
        "branch_half": half_size(branch, q_branch),
    }


def attachment_mode(requested, offsets, tolerance=1.0e-6):
    """
    Decide between a side tap and a face-mounted tap.

    requested: the type's Attachment property ("Auto", "Side" or "Face").
    offsets:   the dict from _attachment_offsets(), or None when the branch
               axis meets the run axis.

    "Auto" picks Face once the whole branch section is clear of the run
    surface, and Side otherwise. A side branch that does not lie wholly
    within the run's depth (it crosses the run's edge) is built on a copy
    of the branch moved in until it fits, plus an offset piece back to the
    real branch (branch_jog).
    """
    requested = str(requested or ATTACHMENT_AUTO)
    if requested not in (ATTACHMENT_AUTO, ATTACHMENT_SIDE, ATTACHMENT_FACE):
        raise ValueError("Unknown Attachment '{}'".format(requested))
    if offsets is None:
        if requested == ATTACHMENT_FACE:
            raise ValueError("A face-mounted tap needs the branch to pass over or under the run")
        return ATTACHMENT_SIDE
    offset, run_half, branch_half = offsets["offset"], offsets["run_half"], offsets["branch_half"]
    clearance = offset - branch_half - run_half  # gap between run surface and the branch's near side
    if requested == ATTACHMENT_SIDE:
        # A side tap has to touch the run somewhere.
        if clearance >= -tolerance:
            raise ValueError("The branch passes clear of the run, so it cannot be a side tap")
        return ATTACHMENT_SIDE
    if clearance >= -tolerance:
        return ATTACHMENT_FACE
    if requested == ATTACHMENT_FACE:
        raise ValueError(
            "The branch is too close to the run for a face-mounted tap: move it {:.1f} mm further away".format(
                -clearance
            )
        )
    return ATTACHMENT_SIDE


# The offset piece of a jogged branch is never steeper than this, from the branch axis.
_JOG_MAX_SLOPE_DEG = 30.0


def branch_jog(context, centred=False):
    """
    For a side tap or tee whose branch crosses the edge of the run (only
    part of its section lies within the run's depth): the branch moved in,
    towards the run axis, just far enough to lie within the run (or onto
    the run axis, for a branch larger than the run), and the length of the
    straight offset piece that carries it back to its own axis at no more
    than _JOG_MAX_SLOPE_DEG. None when no move is needed (the branch fits,
    meets the run axis, or is face-mounted). `centred`: always move the
    branch onto the run axis (fittings that sweep the branch in the run's
    own plane, the radius tees).

    {"branch": the real branch port, "moved": the moved copy,
     "shift": distance moved, "length": the offset piece's length}
    """
    api = context["hvac_api"]
    try:
        run_a, run_b, branch = api.run_branch_ports(context)
    except Exception:
        return None
    offsets = _attachment_offsets(api, run_a, run_b, branch)
    if offsets is None or attachment_mode(_props(context).get("Attachment"), offsets) != ATTACHMENT_SIDE:
        return None
    inside = offsets["run_half"] - (offsets["offset"] + offsets["branch_half"])
    if centred:
        shift = offsets["offset"]
    elif inside >= -1.0e-6:
        return None
    else:
        shift = min(-inside, offsets["offset"])
    moved = api.copy_port(branch, position=api.port_position(branch) - offsets["up"] * shift)
    length = shift / math.tan(math.radians(_JOG_MAX_SLOPE_DEG))
    return {"branch": branch, "moved": moved, "shift": shift, "length": length}


def with_branch_jog(function=None, centred=False):
    """
    Decorate a tap or tee type's build or measure function: when its branch
    crosses the run's edge (branch_jog), run it on the moved branch. A build
    gets the offset piece from _common._finish (it reads "branch_jog" from
    the context); a measure gets the branch trim extended here. Used as
    @with_branch_jog, or @with_branch_jog(centred=True) (see branch_jog).
    """
    if function is None:
        return functools.partial(with_branch_jog, centred=centred)

    @functools.wraps(function)
    def wrapper(context, *args, **kwargs):
        jog = branch_jog(context, centred)
        if jog is None:
            return function(context, *args, **kwargs)
        key = jog["branch"].get("edge_key")
        moved = dict(context)
        moved["connected_ports"] = [
            jog["moved"] if port.get("edge_key") == key else port for port in context.get("connected_ports") or []
        ]
        moved["branch_jog"] = jog
        result = function(moved, *args, **kwargs)
        if isinstance(result, list):
            return jog_records(result, jog)[0]
        return result

    return wrapper


def _rolled_collar(api, context, run_a, run_b, branch, offsets, roll):
    """
    (collar direction, collar foot on the run axis, corner, run half along the
    collar) for a collar rolled `roll` radians about a round run's axis, from
    straight up (the common perpendicular) towards the branch direction, so
    the elbow turns less (SMACNA 14-14 D, F to L: "rolled 45 deg"). The foot
    is where the rolled collar's line, square to the run, meets the branch axis.
    """
    if api.port_profile(run_a) != "Circular" or api.port_profile(run_b) != "Circular":
        raise ValueError("A rolled collar (CollarRoll) needs a round run")
    run_dir = api.unit(api.port_direction(run_a))
    branch_dir = api.unit(api.port_direction(branch))
    up = offsets["up"]
    side = api.unit(run_dir.cross(up))
    if side.dot(branch_dir) < 0.0:
        side = side * -1.0
    collar_dir = up * math.cos(roll) + side * math.sin(roll)
    # Solve foot + s * collar_dir = branch point + t * branch_dir, foot = run point + u * run_dir.
    back = branch_dir * -1.0
    det = run_dir.dot(collar_dir.cross(back))
    if abs(det) < 1.0e-9:
        raise ValueError("The collar cannot be rolled towards this branch (it would run along the branch)")
    gap = api.port_position(branch) - api.port_position(run_a)
    u = gap.dot(collar_dir.cross(back)) / det
    rise = run_dir.dot(gap.cross(back)) / det
    foot = api.port_position(run_a) + run_dir * u
    run_half = 0.5 * max(api.port_diameter(run_a), api.port_diameter(run_b))
    if rise <= run_half:
        raise ValueError("Rolled by CollarRoll, the collar would not reach the branch: use a smaller roll")
    return collar_dir, foot, foot + collar_dir * rise, run_half


def face_tap_layout(context, run_factor=0.3, branch_factor=0.5, collar="plain"):
    """
    Layout of a face-mounted tap, or None when this node is an ordinary
    side tap (see attachment_mode). Shared by every tap and tee type, since
    once the branch passes over the run they all become the same fitting,
    except for the collar on the run face: `collar` "plain" (a straight
    collar), "conical" (flared at the run face, a saddle / conical tap) or
    "shoe" (a 45 degree toe at the run face). CollarRoll rolls the collar
    about a round run towards the branch (SMACNA "rolled 45 deg"); the
    elbow then turns by what is left.
    """
    api = context["hvac_api"]
    run_a, run_b, branch = api.run_branch_ports(context)
    p = _props(context)
    offsets = _attachment_offsets(api, run_a, run_b, branch)
    if attachment_mode(p.get("Attachment"), offsets) != ATTACHMENT_FACE:
        return None

    branch_dir = api.unit(api.port_direction(branch))
    size = _size(api, branch)
    roll = math.radians(float(p.get("CollarRoll", 0.0) or 0.0))
    if abs(roll) > 1.0e-9:
        up, q_run, corner, run_half = _rolled_collar(api, context, run_a, run_b, branch, offsets, roll)
    else:
        up, q_run, corner, run_half = offsets["up"], offsets["q_run"], offsets["q_branch"], offsets["run_half"]
    turn = api.angle_between(up, branch_dir)
    tangent_factor = math.tan(turn / 2.0)
    if tangent_factor <= 1.0e-6:
        raise ValueError("The collar runs straight into the branch: no elbow to build")

    # Step 1: the elbow radius. Its tangent can't be longer than the height
    # the collar has to rise, and the radius not smaller than the bend
    # minimum (half the branch size plus the wall; below it the inside of
    # the bend folds over).
    rise = (corner - q_run).Length - run_half
    minimum = _min_bend_radius(size, _wall_thickness(context))
    radius = min(max(_positive(p.get("ElbowRadius"), size), minimum), rise / tangent_factor)
    if radius < minimum - 1.0e-6:
        raise ValueError(
            "The branch is too close to the run surface for its elbow: move it {:.1f} mm further away".format(
                (minimum - radius) * tangent_factor
            )
        )

    # Step 2: the collar's own section. It is the branch section turned
    # back through the bend, so the swept elbow does not twist.
    x_axis = api.port_profile_x_axis(branch)
    if x_axis is None:
        _placement, x_axis, _y_axis, _z_axis = api.make_profile_frame(branch_dir)
    bend_axis = api.unit(branch_dir.cross(up))
    collar_x = api.rotate_vector(x_axis, bend_axis, turn)
    collar_port = api.copy_port(branch, position=corner, direction=up * -1.0, profile_x_axis=collar_x)
    route = api.make_elbow_path(collar_port, api.copy_port(branch, position=corner), radius)

    # Step 3: the collar's shape at the run face, within its straight part.
    surface_point = q_run + up * run_half
    straight = max(0.0, (api.port_position(route["ports"][0]) - surface_point).dot(up))
    footprint = api.profile_from_port(api.copy_port(collar_port, position=surface_point))
    flare = min(_positive(p.get("TapHeight"), 0.5 * size), straight)
    growth, toe = 0.0, None
    if collar != "plain" and flare <= 1.0:
        collar = "plain"
    if collar == "conical":
        # The flare may not spread wider than the run face across the run.
        across = api.unit(api.port_direction(run_a).cross(up))
        run_section = api.profile_from_port(api.copy_port(run_a, position=q_run))
        run_low, run_high = api.profile_projection_bounds(run_section, across)
        foot_low, foot_high = api.profile_projection_bounds(footprint, across)
        room = min(foot_low - run_low, run_high - foot_high)
        growth = min(_positive(p.get("SaddleGrowth"), 0.6 * size), room)
        if growth <= 1.0:
            collar, growth = "plain", 0.0
        else:
            footprint = api.offset_profile(footprint, growth)
    elif collar == "shoe":
        lean_dir = api.unit(api.port_direction(_lean_port(api, run_a, run_b, branch)))
        toe = lean_dir - up * lean_dir.dot(up)
        if toe.Length <= api.EPS:
            collar = "plain"
        else:
            toe = api.unit(toe)
            footprint = api.stretch_profile_one_sided(footprint, toe, flare)

    # Step 4: trims. The run has to clear the collar's footprint on its
    # face; the branch starts where the elbow ends.
    min_a, min_b = _tap_run_minimums(api, api.center_from_context(context), run_a, run_b, footprint)
    elbow_end = api.port_position(route["ports"][1])
    branch_min = max(0.0, (elbow_end - api.port_position(branch)).dot(branch_dir))
    return {
        "run_a": run_a,
        "run_b": run_b,
        "branch": branch,
        "q_run": q_run,
        "up": up,
        "route": route,
        "collar": collar,
        "surface_point": surface_point,
        "run_half": run_half,
        "flare": flare,
        "growth": growth,
        "toe": toe,
        "trim_a": min_a + _extra_trim(p.get("TrimRunA"), run_factor * _size(api, run_a)),
        "trim_b": min_b + _extra_trim(p.get("TrimRunB"), run_factor * _size(api, run_b)),
        "trim_branch": branch_min + _extra_trim(p.get("TrimBranch"), branch_factor * size),
    }


def measure_face_tap(context, layout):
    api = context["hvac_api"]
    return api.build_trim_rec_from_port_lengths(
        [
            (layout["run_a"], layout["trim_a"]),
            (layout["run_b"], layout["trim_b"]),
            (layout["branch"], layout["trim_branch"]),
        ]
    )


def build_face_tap(context, layout):
    """Face-mounted tap: run trunk, a collar up from its face, a 90 degree elbow, then the branch."""
    api = context["hvac_api"]
    run_a, run_b, branch = layout["run_a"], layout["run_b"], layout["branch"]
    q_run, up, route = layout["q_run"], layout["up"], layout["route"]
    trim_a, trim_b = layout["trim_a"], layout["trim_b"]

    collar_top, elbow_end = route["ports"]
    branch_end = _trimmed(api, branch, layout["trim_branch"])
    branch_reach = (api.port_position(branch_end) - api.port_position(elbow_end)).Length
    # The collar runs from the start of the elbow down to the run's own
    # mid-plane (a little past it, then cut back, for a clean cut face).
    collar_reach = (api.port_position(collar_top) - q_run).dot(up) + max(0.01 * _size(api, branch), 2.0)

    kind, flare = layout["collar"], layout["flare"]
    surface_point = layout["surface_point"]

    def flared_collar(offset):
        # A conical or shoe collar: straight down to TapHeight above the run
        # face, then flared (conical) or stretched to the toe (shoe) at the
        # face and on down to the run axis, with every section grown by the wall offset.
        def section(point, extra):
            profile = api.profile_from_port(api.copy_port(collar_top, position=point), offset)
            if extra <= 0.0:
                return profile
            if kind == "conical":
                return api.offset_profile(profile, extra)
            return api.stretch_profile_one_sided(profile, layout["toe"], extra)

        scale = layout["growth"] if kind == "conical" else flare
        top = surface_point + up * flare
        # Below the run face the collar keeps its footprint down to the run axis (it is inside the run).
        # Lofted upwards, against the collar port's direction, the same sense as the side taps'
        # lofts (the other way round the stretched shoe sections give an inside-out solid).
        profiles = [section(q_run, scale), section(surface_point, scale), section(top, 0.0)]
        if (api.port_position(collar_top) - top).Length > api.EPS:
            profiles.append(api.profile_from_port(collar_top, offset))
        return api.loft(profiles, solid=True, ruled=True)

    def envelope(offset):
        trunk = _loft(api, [_trimmed(api, run_a, trim_a), _trimmed(api, run_b, trim_b)], offset)

        if kind == "plain":
            collar = api.extrude(api.profile_from_port(collar_top, offset), up * -collar_reach, solid=True)
        else:
            collar = flared_collar(offset)
        collar = api.clip_plane(collar, (q_run, up), side="positive")
        collar = _clip_tap_to_run_body(api, collar, q_run, run_a, run_b, trim_a, trim_b)

        ends = [api.profile_from_port(collar_top, offset), api.profile_from_port(elbow_end, offset)]
        parts = [trunk, collar, api.sweep(ends, route["path"], solid=True)]
        if branch_reach > api.EPS:
            parts.append(_loft(api, [elbow_end, branch_end], offset))
        return api.fuse(*parts)

    return _finish(context, envelope, measure_face_tap(context, layout))


@with_branch_jog
def measure_tap_straight(context):
    face = face_tap_layout(context)
    if face is not None:
        return measure_face_tap(context, face)
    return measure_straight_tap(context, 0.3, 0.5)


@with_branch_jog
def build_tap_straight(context):
    face = face_tap_layout(context)
    if face is not None:
        return build_face_tap(context, face)
    return _straight_tap(context, 0.3, 0.5)


@with_branch_jog
def measure_tap_saddle(context):
    face = face_tap_layout(context, collar="conical")
    if face is not None:
        return measure_face_tap(context, face)
    return measure_saddle_tap(context, 0.3, 0.5)


@with_branch_jog
def build_tap_saddle(context):
    face = face_tap_layout(context, collar="conical")
    if face is not None:
        return build_face_tap(context, face)
    return _saddle_tap(context, 0.3, 0.5)


def _tap_shoe_layout(context):
    api = context["hvac_api"]
    run_a, run_b, branch = api.run_branch_ports(context)
    p = _props(context)

    trunk_center, branch_dir, toe_dir, branch_width, run_depth, overlap, run_surface = _tap_geometry(
        context, api, run_a, run_b, branch
    )
    tap_height = _positive(p.get("TapHeight"), 0.5 * branch_width)
    tap_top = run_surface + branch_dir * tap_height
    base_position = run_surface - branch_dir * overlap

    surface_port = api.copy_port(branch, position=run_surface)
    surface_profile = api.stretch_profile_one_sided(api.profile_from_port(surface_port), toe_dir, tap_height)

    trim_a, trim_b, trim_branch = _tap_trims(
        api, p, run_a, run_b, branch, trunk_center, branch_dir, tap_top, surface_profile, 0.3, 0.5
    )

    return {
        "run_a": run_a,
        "run_b": run_b,
        "branch": branch,
        "trunk_center": trunk_center,
        "branch_dir": branch_dir,
        "toe_dir": toe_dir,
        "tap_top": tap_top,
        "base_position": base_position,
        "overlap": overlap,
        "tap_height": tap_height,
        "surface_profile": surface_profile,
        "trim_a": trim_a,
        "trim_b": trim_b,
        "trim_branch": trim_branch,
    }


@with_branch_jog
def measure_tap_shoe(context):
    # A branch passing over or under the run is face-mounted instead (see taps.face_tap_layout).
    face = face_tap_layout(context, collar="shoe")
    if face is not None:
        return measure_face_tap(context, face)
    api = context["hvac_api"]
    layout = _tap_shoe_layout(context)
    return api.build_trim_rec_from_port_lengths(
        [
            (layout["run_a"], layout["trim_a"]),
            (layout["run_b"], layout["trim_b"]),
            (layout["branch"], layout["trim_branch"]),
        ]
    )


@with_branch_jog
def build_tap_shoe(context):
    """45-degree shoe tap with profile-independent geometry. TapHeight
    defines both the vertical shoe height and, at 45 degrees, the toe
    extension at the run surface."""
    # A branch passing over or under the run is face-mounted instead (see taps.face_tap_layout).
    face = face_tap_layout(context, collar="shoe")
    if face is not None:
        return build_face_tap(context, face)
    api = context["hvac_api"]
    layout = _tap_shoe_layout(context)
    run_a, run_b, branch = layout["run_a"], layout["run_b"], layout["branch"]
    trunk_center, branch_dir, toe_dir = layout["trunk_center"], layout["branch_dir"], layout["toe_dir"]
    tap_top, base_position = layout["tap_top"], layout["base_position"]
    overlap, tap_height = layout["overlap"], layout["tap_height"]
    trim_a, trim_b, trim_branch = layout["trim_a"], layout["trim_b"], layout["trim_branch"]

    top_port = api.copy_port(branch, position=tap_top)
    # The run surface sits one TapHeight below the tap top, along the branch axis.
    surface_port = api.copy_port(branch, position=tap_top - branch_dir * tap_height)
    base_port = api.copy_port(branch, position=base_position)
    branch_end = _trimmed(api, branch, trim_branch)

    def envelope(offset):
        # Same shoe as the layout used for the trims, with every section grown by the wall offset.
        top_profile = api.profile_from_port(top_port, offset)
        surface_profile = api.stretch_profile_one_sided(
            api.profile_from_port(surface_port, offset), toe_dir, tap_height
        )
        base_profile = api.stretch_profile_one_sided(
            api.profile_from_port(base_port, offset), toe_dir, tap_height + overlap
        )
        trunk = _loft(api, [_trimmed(api, run_a, trim_a), _trimmed(api, run_b, trim_b)], offset)

        profiles = [top_profile, surface_profile, base_profile]
        if (api.port_position(branch_end) - tap_top).Length > api.EPS:
            profiles.insert(0, api.profile_from_port(branch_end, offset))
        stub = api.loft(profiles, solid=True, ruled=True)
        stub = _clip_tap_to_run_body(api, stub, trunk_center, run_a, run_b, trim_a, trim_b)
        stub = _clip_branch_at_trunk_center(api, stub, trunk_center, branch)
        return api.fuse(trunk, stub)

    return _finish(
        context,
        envelope,
        api.build_trim_rec_from_port_lengths([(run_a, trim_a), (run_b, trim_b), (branch, trim_branch)]),
    )
