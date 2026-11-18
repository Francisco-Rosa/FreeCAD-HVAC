# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the HVAC addon.

"""
Small helpers shared by every fitting module: property access, port sizing,
trim arithmetic, leg clipping and the mitered-bend builder.

Most fittings in this package are split into a small measurement function
(``measure_*``) and a build function (``build_*``/an internal ``_*``
builder), sharing whichever calculation actually determines a port's own
trim length -- a route/axis dict from an HVACLibraryAPI helper
(``make_elbow_path``/``make_radiussed_path``/``offset_transition_axis``), a
plain arithmetic result, or (for a radiused/mitered branch fitting whose
minimum body length genuinely depends on a swept bend's own extent) a
lightweight intermediate bend-stub Shape -- so there is exactly one place
each fitting's own dimensions/trims are computed, never two independently
maintained copies of the same formula. See freecad/HVAC/libraries/README.md's
"connection_lengths" section for the overall contract this supports
(HVACLibraryRegistry.measure_connection_lengths()).
"""

import math

_EPS = 1.0e-7


def _props(context):
    return dict(context.get("properties") or {})


def _size(api, port):
    profile = api.port_profile(port)
    if profile == "Circular":
        return max(float(api.port_diameter(port)), 1.0)
    if profile in {"Rectangular", "Oval"}:
        return max(float(api.port_width(port)), float(api.port_height(port)), 1.0)
    params = api.port_section_params(port)
    return max([abs(float(v or 0.0)) for v in params.values() if isinstance(v, (int, float))] or [1.0])


def _positive(value, fallback):
    value = float(value or 0.0)
    return value if value > _EPS else float(fallback)


def _trimmed(api, port, length):
    return api.copy_port(port, position=api.port_position(port) + api.port_direction(port) * float(length))


def _port_axis_point(api, port, point):
    """Project a point onto the infinite axis defined by a port."""
    position = api.port_position(port)
    direction = api.unit(api.port_direction(port))
    return position + direction * ((api.vec(point) - position).dot(direction))


def _clip_branch_at_trunk_center(api, shape, trunk_center, branch):
    """Keep the branch-facing half of a stub at the trunk center plane."""
    return api.clip_plane(shape, (trunk_center, api.port_direction(branch)), side="positive")


def _loft(api, ports, offset=0.0, ruled=True):
    return api.loft([api.profile_from_port(p, offset) for p in ports], solid=True, ruled=ruled)


def _layer_thickness(layer_def, params):
    """A construction layer's own wall thickness, read from the property it names (0 if it names none)."""
    name = getattr(layer_def, "thickness_property", None)
    return float(params.get(name, 0.0) or 0.0) if name else 0.0


def _wall_thickness(context):
    """Total thickness of every construction layer outside the air space (0 when the type has no wall)."""
    params = _props(context)
    return sum(_layer_thickness(layer_def, params) for layer_def in (context.get("construction_layers") or []))


def _min_bend_radius(size, wall=0.0):
    """
    The smallest centre-line radius a swept or mitered bend of duct `size`
    can take. Below half the size the inside of the bend folds over; every
    wall layer is built further out, so its inner face needs the wall's
    thickness on top, plus a small clearance so the sweep never degenerates.
    """
    size = float(size)
    return 0.5 * size + max(float(wall or 0.0), 0.0) + max(1.0, 0.01 * size)


# The pieces a fitting is fused from overlap only by small modelling
# clearances (and, in a wall envelope, by about a wall thickness where two
# halves meet), so their union keeps nearly all of their summed volume. A fuse
# that silently dropped or mangled a piece keeps much less.
_UNION_MIN_SHARE = 0.9


def _is_union_of(api, shape, pieces):
    """
    Cheap check of a fuse result: one valid solid, no larger than the pieces
    together, no smaller than the largest piece, and keeping at least
    `_UNION_MIN_SHARE` of the pieces' summed volume.
    """
    if shape is None or shape.isNull():
        return False
    validation = api.validate(shape, require_solid=True)
    if not validation["valid"] or validation["solid_count"] != 1:
        return False
    volumes = [float(piece.Volume) for piece in pieces]
    total = float(shape.Volume)
    slack = 1.0e-6 * max(sum(volumes), 1.0)
    return max(volumes) - slack <= total <= sum(volumes) + slack and total >= _UNION_MIN_SHARE * sum(volumes)


def jog_records(records, jog):
    """
    (records, branch trim before the jog): the trim records with the branch's
    length extended by the jog's own length (see taps.branch_jog).
    """
    key = jog["branch"].get("edge_key")
    out, base = [], None
    for record in records or []:
        record = dict(record)
        if record.get("edge_key") == key:
            base = float(record["length"])
            record["length"] = base + jog["length"]
        out.append(record)
    return out, base


def _add_branch_jog(api, envelope, connection_lengths, jog):
    """
    Wrap a side fitting's envelope (built on the moved branch) with the jog:
    a straight offset piece from the moved branch's end to the real branch,
    jog["length"] further out. Returns (envelope, connection lengths).
    """
    records, base = jog_records(connection_lengths, jog)
    if base is None:
        return envelope, connection_lengths
    start = _trimmed(api, jog["moved"], base)
    end = _trimmed(api, jog["branch"], base + jog["length"])

    def jogged(offset):
        return api.fuse(envelope(offset), _loft(api, [start, end], offset))

    return jogged, records


def _finish(context, envelope, connection_lengths, port_suffixes=None):
    """
    Turn a fitting's envelope builder into the result dict a generator returns.

    `envelope(offset)` builds the fitting's whole outer boundary as a solid,
    grown outward by `offset` from the clear-air boundary (offset 0 is the
    air space itself). Every fitting in this package describes its shape
    that way, so one fitting works for any wall build-up:

    - The type declares construction layers with a thickness: each layer
      becomes its own hollow shell (HVACLibraryAPI.build_layered_geometry).
      Flanges are not part of it: they are a construction feature of their
      own (fittings/features.py, transverse_flange).
    - No layer has a thickness: there is no wall to build, so the plain
      air-space solid is returned on the type's first layer
      (HVACLibraryAPI.single_layer).

    `port_suffixes` is accepted for older callers and no longer used: the
    flange feature reads port roles itself.
    """
    api = context["hvac_api"]
    params = _props(context)
    layer_defs = list(context.get("construction_layers") or [])

    # A side tap or tee built on a branch moved in to fit the run (taps.branch_jog)
    # gets the offset piece back to the branch's own axis, inside the same envelope.
    jog = context.get("branch_jog")
    if jog:
        envelope, connection_lengths = _add_branch_jog(api, envelope, connection_lengths, jog)

    if any(_layer_thickness(layer_def, params) > _EPS for layer_def in layer_defs):
        result = api.build_layered_geometry(envelope, layer_defs, params)
    else:
        result = api.single_layer(context, api.refine(envelope(0.0)))
    result["connection_lengths"] = connection_lengths
    return result


def _structural_layer_def(context, result):
    """
    The construction layer rigid attachments (flanges, an internal rod, ...)
    belong to: the structural shell if one was built, otherwise the
    innermost layer that has a shape. None when the result has no layers.
    """
    layers = result.get("layers") or {}
    built = [
        layer_def
        for layer_def in (context.get("construction_layers") or [])
        if (layers.get(layer_def.id) or {}).get("shape") is not None
    ]
    if not built:
        return None
    return next((ld for ld in built if "structural_shell" in list(getattr(ld, "roles", []) or [])), built[0])


def _fuse_into_structure(context, result, shape):
    """Fuse an extra solid onto the fitting: its structural layer, or its only layer when no layer has a wall."""
    api = context["hvac_api"]
    layers = result.get("layers") or {}
    host = _structural_layer_def(context, result)
    if host is not None:
        layer_id = host.id
    elif layers:
        layer_id = next(iter(layers))
    else:
        return
    layers[layer_id] = {"shape": api.refine(api.fuse(layers[layer_id]["shape"], shape))}


def _flange_enabled(params, index, suffix, port=None):
    """
    Whether one port gets its flange. The first of these properties the type
    declares decides: ShowFlange<Role> (e.g. ShowFlangeBranch), ShowFlange<N>
    (1-based port number), then ShowFlange -- either one shared switch or a
    per-port one (its own value for every port). Default: yes.
    """
    names = ["ShowFlange{}".format(suffix)] if suffix else []
    names += ["ShowFlange{}".format(index + 1), "ShowFlange"]
    for name in names:
        if name not in params:
            continue
        value = params[name]
        if hasattr(value, "for_port"):
            value = value.for_port(port) if port is not None else value.default
        return True if value is None else bool(value)
    return True


def _profile_extent(profile):
    shape = profile.wire if hasattr(profile, "wire") else profile
    bb = shape.BoundBox
    return max(bb.DiagonalLength, bb.XLength, bb.YLength, bb.ZLength, 1.0)


def _outward(solid):
    """
    `solid` with its faces facing out. Extruding or lofting a profile wire
    that winds against the sweep direction gives an inside-out solid
    (negative volume), which breaks every later boolean -- which way the
    wire winds depends on the profile frame, so it can happen on either
    side of a fitting.
    """
    try:
        if solid is not None and not solid.isNull() and solid.Volume < 0.0:
            solid = solid.copy()
            solid.reverse()
    except Exception:
        pass
    return solid


def _mitered_bend(api, port0, port1, radius, cuts, profile0=None, profile1=None, offset=0.0):
    """Build a faceted bend between two arbitrary ports.

    Used by through mitered elbows, the mitered-shoe tee, and mitered wye.
    The tangent-arc route defines the fitting-end positions and the reference
    radius; the actual body between those ends is constructed from straight
    gores separated by mitre planes.

    ``profile0``/``profile1`` optionally replace the exact tangent-end
    sections, allowing a split wye profile to transition through the gores.
    ``offset`` grows the two default end sections outward (see ``_finish``);
    the route, mitre planes and trims never depend on it. A caller passing
    its own profiles applies the offset to them itself.
    Returns ``(shape, [trim0, trim1])``.
    """
    u0 = api.port_direction(port0)
    u1 = api.port_direction(port1)

    # Establish the tangent ends of the fitting.
    route = api.make_elbow_path(port0, port1, radius)
    route_port0, route_port1 = route["ports"]
    s0 = api.port_position(route_port0)
    s1 = api.port_position(route_port1)
    d0 = api.unit(u0 * -1.0)
    d1 = api.unit(u1)
    deflection = api.angle_between(d0, d1)
    if deflection <= api.EPS:
        raise ValueError("Mitered bend requires a non-zero bend angle")
    bend_cross = d0.cross(d1)
    if bend_cross.Length <= api.EPS:
        raise ValueError("Mitered bend plane is undefined")
    bend_normal = api.unit(bend_cross)
    center = api.arc_center_from_points_tangents_radius(s0, s1, u0, u1, radius)

    # Straight gore directions.
    # NumberOfCuts is the number of internal mitre joints.
    # Therefore there are cuts + 1 gores.
    segment_angle = deflection / float(cuts)
    cos_half = math.cos(segment_angle / 2.0)
    if abs(cos_half) <= api.EPS:
        raise ValueError("Mitered bend segment angle is degenerate")
    leg_dirs = [api.unit(api.rotate_vector(d0, bend_normal, i * segment_angle)) for i in range(cuts + 1)]

    # Internal mitre planes.
    radius_vec0 = api.unit(s0 - center)
    joint_radius = radius / cos_half
    joint_positions = []
    joint_planes = []
    for i in range(cuts):
        angle = (i + 0.5) * segment_angle
        position = center + api.rotate_vector(radius_vec0, bend_normal, angle) * joint_radius
        normal = api.unit(leg_dirs[i] + leg_dirs[i + 1])
        joint_positions.append(position)
        joint_planes.append((position, normal))

    # Determine which clipping half-space contains a known point.
    def clip_keep_point(shape, plane, point):
        plane_origin, plane_normal = plane
        value = (api.vec(point) - api.vec(plane_origin)).dot(api.unit(plane_normal))
        side = "positive" if value >= 0.0 else "negative"
        return api.clip_plane(shape, plane, side=side)

    # Calculate the extrusion distance required to pass fully through
    # an inclined mitre plane.
    def reach_to_plane(origin, direction, plane, section):
        plane_origin, plane_normal = plane
        direction = api.unit(direction)
        plane_normal = api.unit(plane_normal)
        denom = direction.dot(plane_normal)
        if abs(denom) <= api.EPS:
            raise ValueError("Mitered bend geometry is degenerate: gore direction is parallel to mitre plane")
        reach = (plane_origin - origin).dot(plane_normal) / denom
        if reach <= api.EPS:
            raise ValueError("Mitered bend has zero or negative gore length")
        extent = _profile_extent(section)
        margin = 2.0 * extent / max(abs(denom), 0.1)
        return reach + margin

    # Build one constant-profile gore from an existing exact section
    # toward a target mitre plane.
    def extrude_to_plane(section, axis_origin, direction, target_plane):
        reach = reach_to_plane(axis_origin, direction, target_plane, section)
        solid = _outward(api.extrude(section, direction * reach, solid=True))
        solid = clip_keep_point(solid, target_plane, axis_origin)
        if solid is None or solid.isNull():
            raise RuntimeError("Mitered bend gore became null after clipping")
        cut_face = api.section_face(solid, target_plane)
        return solid, cut_face.OuterWire

    # Actual fitting-end profiles. These may be geometrically different.
    if profile0 is None:
        profile0 = api.profile_from_port(route_port0, offset)
    if profile1 is None:
        profile1 = api.profile_from_port(route_port1, offset)

    # Use one central gore as the finite transition between the exact
    # profiles propagated from each end.
    transition_gore = cuts // 2
    pieces = []

    # PORT 0 -> FORWARD
    left_section = profile0
    left_axis_point = s0
    for i in range(transition_gore):
        solid, next_section = extrude_to_plane(left_section, left_axis_point, leg_dirs[i], joint_planes[i])
        pieces.append(solid)
        left_section = next_section
        left_axis_point = joint_positions[i]

    # PORT 1 -> BACKWARD
    right_section = profile1
    right_axis_point = s1
    right_pieces = []
    for i in range(cuts, transition_gore, -1):
        target_plane = joint_planes[i - 1]
        backward_direction = leg_dirs[i] * -1.0
        solid, next_section = extrude_to_plane(right_section, right_axis_point, backward_direction, target_plane)
        right_pieces.append(solid)
        right_section = next_section
        right_axis_point = joint_positions[i - 1]

    # The transition gore is a finite loft between exact section wires
    # propagated from port0 and port1.
    transition = api.loft([left_section, right_section], solid=True, ruled=True)
    if transition is None or transition.isNull():
        raise RuntimeError("Mitered bend transition gore loft failed")
    pieces.append(_outward(transition))
    pieces.extend(right_pieces)
    shape = api.fuse(*pieces)
    return shape, [route["trim_lengths"][0], route["trim_lengths"][1]]


# Directions sampled round a section when checking that one section fits inside another.
_INSET_DIRECTIONS = 24
# How far an inset bend start stays clear of the run's inside face: this share of
# the run's half-depth, and at least this many times the total wall thickness.
_INSET_DEPTH_SHARE = 0.10
_INSET_WALL_FACTOR = 2.0


def _scaled_port(api, port, scale):
    """A copy of `port` with its section scaled by `scale` about its centre (same shape, smaller)."""
    params = dict(api.port_section_params(port))
    for name in ("Diameter", "Width", "Height"):
        if name in params and params[name] is not None:
            params[name] = float(params[name]) * scale
    scaled = api.copy_port(port)
    scaled["section_params"] = params
    return scaled


def _inset_bend_start(api, start_port, run_port, wall=0.0):
    """
    The section a branch bend starts on inside a run (design 6.6 B).

    `start_port` is the bend's start: on the run axis, facing along the run,
    carrying the branch's section. When that section reaches within a
    margin of the run's inside face, the bend would start on (or along)
    the run wall itself: two identical curved surfaces, which OpenCascade's
    booleans cannot fuse. The start section is then scaled down so it
    clears the inside face by max(10 % of the run's half-depth, twice the
    total wall) on every side; the sweep grows it back to the full branch
    section along the bend, so the bend crosses the run wall at an angle.

    Returns `start_port` unchanged when the section already clears the run,
    else a copy with the scaled section. Each wall layer grows the returned
    section by its own offset, which the margin leaves room for.
    """
    position = api.port_position(start_port)
    run_profile = api.profile_from_port(api.copy_port(run_port, position=position))
    branch_profile = api.profile_from_port(start_port)
    _, x_axis, y_axis, _ = api.make_profile_frame(api.port_direction(start_port), api.port_profile_x_axis(start_port))

    # Step 1: how far each section reaches from the shared centre, in many directions.
    run_reach, branch_reach = [], []
    for index in range(_INSET_DIRECTIONS):
        angle = 2.0 * math.pi * index / _INSET_DIRECTIONS
        direction = x_axis * math.cos(angle) + y_axis * math.sin(angle)
        centre = position.dot(direction)
        run_reach.append(api.profile_projection_bounds(run_profile, direction)[1] - centre)
        branch_reach.append(api.profile_projection_bounds(branch_profile, direction)[1] - centre)

    # Step 2: the margin, and the largest scale that keeps it in every direction.
    margin = max(_INSET_DEPTH_SHARE * min(run_reach), _INSET_WALL_FACTOR * max(float(wall or 0.0), 0.0))
    scale = min((run - margin) / branch for run, branch in zip(run_reach, branch_reach) if branch > _EPS)
    if scale >= 1.0:
        return start_port
    if scale <= 0.1:
        raise ValueError("The run is too small for this branch bend to start inside it")
    return _scaled_port(api, start_port, scale)


def _extend_leg(api, shape, port, current_trim, requested_trim, offset=0.0):
    """Fuse a plain straight extension onto a swept/mitred leg's outer end,
    so a user-requested trim length can grow past whatever minimum the
    bend geometry alone requires (``current_trim``) -- e.g. a tee/tap's
    branch leg, whose near end is pinned to the bend's own tangent point.
    A no-op (returns ``shape`` unchanged) when the request is already met.
    """
    extra = float(requested_trim) - float(current_trim)
    if extra <= _EPS:
        return shape
    end = _trimmed(api, port, current_trim)
    stub = api.extrude(api.profile_from_port(end, offset), api.port_direction(port) * extra, solid=True)
    return api.fuse(shape, stub)


def _lean_port_from_profile_frame(api, run_a, run_b, branch):
    """Choose a physical run direction deterministically for a symmetric tee.

    The branch profile frame provides the local reference. Swapping run_a/run_b
    therefore does not mirror the fitting.
    """
    preferred_x = api.port_profile_x_axis(branch)

    if preferred_x is not None:
        _, x_axis, y_axis, _ = api.make_profile_frame(api.port_direction(branch), preferred_x)
        run_dir = api.unit(api.port_direction(run_a))

        local_x = run_dir.dot(x_axis)
        local_y = run_dir.dot(y_axis)

        if abs(local_x) >= abs(local_y):
            return run_a if local_x >= 0.0 else run_b
        return run_a if local_y >= 0.0 else run_b

    key_a = (str(run_a.get("edge_key", "") or ""), str(run_a.get("segment_end", "") or ""))
    key_b = (str(run_b.get("edge_key", "") or ""), str(run_b.get("segment_end", "") or ""))

    if key_a == ("", "") or key_b == ("", ""):
        raise ValueError("Symmetric tee bend direction requires profile_x_axis or stable run edge keys")

    return run_a if key_a > key_b else run_b


def _flow_paired_run(run_a, run_b, branch):
    """
    The run leg the branch exchanges air with, by flow direction, or None
    when flow is unknown or ambiguous (a bullhead, no flow direction yet):
    diverging (air leaves through the branch) -> the run inlet, the
    upstream side; converging (air enters through the branch) -> the run
    outlet, the downstream side. A shoe's toe and a branch bend point at
    this leg, so the air turns along them rather than against them.
    """
    branch_in = branch.get("flow_into_junction")
    a_in, b_in = run_a.get("flow_into_junction"), run_b.get("flow_into_junction")
    if branch_in is None or a_in is None or b_in is None or bool(a_in) == bool(b_in):
        return None
    want_into_junction = not bool(branch_in)
    return run_a if bool(a_in) == want_into_junction else run_b


def _lean_port(api, run_a, run_b, branch, reverse=False):
    """
    Pick the run leg toward which an asymmetric branch bend (or a shoe's
    toe) is formed. An inclined branch decides it by geometry: it leans
    toward the run leg it points away from. A square branch has no
    geometric lean, so the flow decides it (_flow_paired_run), and only
    without a flow direction a deterministic profile-frame choice.
    `reverse` (ReverseBranchBend) flips the result.
    """
    incoming = api.unit(api.port_direction(branch) * -1.0)
    dir_a = api.unit(api.port_direction(run_a))
    dir_b = api.unit(api.port_direction(run_b))

    score_a = incoming.dot(dir_a)
    score_b = incoming.dot(dir_b)

    if abs(score_a - score_b) > _EPS:
        selected = run_a if score_a > score_b else run_b
    else:
        selected = _flow_paired_run(run_a, run_b, branch) or _lean_port_from_profile_frame(api, run_a, run_b, branch)

    if reverse:
        return run_b if selected is run_a else run_a

    return selected


def _extra_trim(value, default):
    """Additional trim measured beyond the intrinsic fitting body."""
    if value is None:
        return max(float(default), 0.0)
    return max(float(value or 0.0), 0.0)


def _junction_minimums(api, center, ports):
    """Minimum visible body length along each port required to contain the
    other port profiles at the junction centre."""
    centered_profiles = [api.profile_from_port(api.copy_port(port, position=center)) for port in ports]
    minimums = []
    for port in ports:
        direction = api.unit(api.port_direction(port))
        center_projection = center.dot(direction)
        minimum = 0.0
        for profile in centered_profiles:
            _, p_max = api.profile_projection_bounds(profile, direction)
            minimum = max(minimum, p_max - center_projection)
        minimums.append(max(minimum, 1.0))
    return minimums


def _junction_shape_minimums(api, center, ports, shape, minimums=None):
    """Expand junction minimums to contain the actual generated intrinsic shape."""
    result = list(minimums or _junction_minimums(api, center, ports))
    for i, port in enumerate(ports):
        direction = api.unit(api.port_direction(port))
        _, p_max = api.profile_projection_bounds(shape, direction)
        result[i] = max(result[i], p_max - center.dot(direction))
    return result


def _junction_trims(api, p, ports, names, factors, minimums):
    """Total connection lengths = intrinsic fitting body + additional trims."""
    trims = []
    for port, name, factor, minimum in zip(ports, names, factors, minimums):
        extra = _extra_trim(p.get(name), factor * _size(api, port))
        trims.append(minimum + extra)
    return trims


def _clip_junction_to_body(api, shape, center, ports, trims):
    """Prevent overlap geometry from extending beyond connection planes."""
    for port, trim in zip(ports, trims):
        direction = api.unit(api.port_direction(port))
        plane_origin = api.port_position(port) + direction * trim
        side = "positive" if (center - plane_origin).dot(direction) >= 0.0 else "negative"
        shape = api.clip_plane(shape, (plane_origin, direction), side=side)
    return shape
