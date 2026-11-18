# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the HVAC addon.

"""
Wyes: one main port splitting into two branch routes (mitered and radius).
"""

import math

from ._common import (
    _finish,
    _is_union_of,
    _junction_minimums,
    _junction_shape_minimums,
    _junction_trims,
    _loft,
    _min_bend_radius,
    _mitered_bend,
    _outward,
    _port_axis_point,
    _props,
    _size,
    _trimmed,
    _wall_thickness,
)


def _wye_mitered_layout(context):
    """
    Lay out a mitered wye: the shared split layout, plus each leg's
    plane-split piece built once at the air-space size to measure it.

    measure_wye_mitered() and build_wye_mitered() both use this layout, so
    their trims agree.
    """
    api = context["hvac_api"]
    p = _props(context)
    cuts = max(int(p.get("NumberOfCuts", 2) or 2), 1)

    # Reuse the same split plane and feasible elbow paths as the radius wye.
    ports, center, main_center, split_routes, plane = _wye_split_route_layout(context)
    main = ports[0]
    main_direction = api.unit(api.port_direction(main))
    routes = []
    intrinsic_shapes = []

    for branch, branch_index, split_face, route in split_routes:
        leg = {
            "branch": branch,
            "branch_index": branch_index,
            "split_face": split_face,
            "route": route,
            "side": _wye_leg_side(branch_index),
        }
        piece, branch_trim = _wye_leg_piece(api, leg, main_center, plane, 0.0, cuts)
        leg.update({"piece": piece, "branch_trim": branch_trim})
        routes.append(leg)
        intrinsic_shapes.append(piece)

    intrinsic_shape = api.compound(intrinsic_shapes)

    minimums = _junction_minimums(api, center, ports)
    minimums = _junction_shape_minimums(api, center, ports, intrinsic_shape, minimums)
    main_split_trim = (api.port_position(main_center) - api.port_position(main)).dot(main_direction)
    minimums[0] = max(minimums[0], main_split_trim)

    for leg in routes:
        branch_index = leg["branch_index"]
        minimums[branch_index] = max(minimums[branch_index], leg["branch_trim"])

    trims = _junction_trims(api, p, ports, ("TrimMain", "TrimBranchA", "TrimBranchB"), (0.70, 0.70, 0.70), minimums)

    return {
        "ports": ports,
        "center": center,
        "main": main,
        "main_center": main_center,
        "plane": plane,
        "cuts": cuts,
        "routes": routes,
        "trims": trims,
    }


def measure_wye_mitered(context):
    api = context["hvac_api"]
    layout = _wye_mitered_layout(context)

    return api.build_trim_rec_from_port_lengths(list(zip(layout["ports"], layout["trims"])))


def build_wye_mitered(context):
    """Mitered wye: each leg a faceted bend from the full common section, cut by the split plane."""
    api = context["hvac_api"]
    layout = _wye_mitered_layout(context)
    ports = layout["ports"]
    trims = layout["trims"]

    def envelope(offset):
        # The layout already built the air-space pieces to measure them;
        # only a wall envelope (offset > 0) needs them built again, larger.
        pieces = None if offset > 0.0 else [leg["piece"] for leg in layout["routes"]]
        shape = _wye_envelope(api, layout, offset, layout["cuts"], pieces)
        if shape is None:
            raise RuntimeError(
                "Mitered wye geometry could not be fused into one valid solid "
                "(requested radius {:.3f} mm; cuts {})".format(
                    float(_props(context).get("BranchRadius") or 0.0), layout["cuts"]
                )
            )
        return shape

    return _finish(context, envelope, api.build_trim_rec_from_port_lengths(list(zip(ports, trims))))


def _wye_common_index(api, ports):
    """
    Which of a 3-port wye's ports is the common/main leg -- from port
    geometry (each port's own outward direction) only, never from duct
    size: resizing one leg must never change which physical leg is
    common. The two branch legs are normally the pair whose outward
    directions are closest to each other (most nearly parallel); the
    remaining port is the common leg. Never uses flow direction -- this
    is a purely geometric/topological identity, unrelated to which way
    air happens to be moving.
    """
    if len(ports) != 3:
        raise ValueError("Wye requires exactly three ports")
    directions = [api.unit(api.port_direction(port)) for port in ports]
    pairs = ((0, 1), (0, 2), (1, 2))
    # A tee-shaped node used as a wye (a bullhead tee: the flow divides into
    # both run legs) has two legs in a straight line. Those are the two
    # branches; the leg square to them is the common one.
    in_line = [pair for pair in pairs if directions[pair[0]].dot(directions[pair[1]]) < -0.99]
    if len(in_line) == 1:
        branch_pair = in_line[0]
        return next(index for index in range(3) if index not in branch_pair)
    branch_pair = max(pairs, key=lambda pair: directions[pair[0]].dot(directions[pair[1]]))
    return next(index for index in range(3) if index not in branch_pair)


def _wye_branch_sort_key(api, main, branch):
    """Stable branch-side ordering in the main leg's local profile frame."""
    preferred_x = api.port_profile_x_axis(main)

    if preferred_x is not None:
        _, x_axis, y_axis, _ = api.make_profile_frame(api.port_direction(main), preferred_x)
        direction = api.unit(api.port_direction(branch))
        return round(direction.dot(x_axis), 12), round(direction.dot(y_axis), 12)

    key = (str(branch.get("edge_key", "") or ""), str(branch.get("segment_end", "") or ""))

    if key == ("", ""):
        raise ValueError("Wye branch ordering requires profile_x_axis or stable branch edge keys")

    return key


def _wye_port_roles(api, ports):
    """Return stable semantic ordering: common/main leg, branch A, branch B."""
    if len(ports) != 3:
        raise ValueError("Wye requires exactly three ports")

    main_index = _wye_common_index(api, ports)
    main = ports[main_index]
    branches = [ports[index] for index in range(3) if index != main_index]

    branches.sort(key=lambda branch: _wye_branch_sort_key(api, main, branch), reverse=True)
    return main, branches[0], branches[1]


def _wye_horizontal_extent(api, port):
    """Return the branch profile dimension along its horizontal axis."""
    profile = api.port_profile(port)
    if profile == "Circular":
        extent = float(api.port_diameter(port))
    elif profile in {"Rectangular", "Oval"}:
        extent = float(api.port_width(port))
    else:
        raise ValueError("Split-profile wye requires a circular, rectangular, or oval profile")

    if extent <= api.EPS:
        raise ValueError("Wye branch horizontal extent must be positive")
    return extent


def _wye_main_split(api, main_center, branch_a, branch_b):
    """
    Split the main profile across in proportion to the branches' widths.

    Returns ({id(branch): half face}, split plane). The split plane (design
    6.6, called the plane P below) passes through the split line, along the
    main axis and square to the profile's horizontal axis; its normal points
    to branch A's side. The half faces only place each leg's bend route
    (their centres); the legs themselves are cut by the plane.
    """
    main_profile = api.profile_from_port(main_center)
    _, horizontal, _vertical, main_dir = api.make_profile_frame(
        api.port_direction(main_center), api.port_profile_x_axis(main_center), api.port_position(main_center)
    )

    # Keep the positive split face on branch A's side.
    branch_delta = api.unit(api.port_direction(branch_a)) - api.unit(api.port_direction(branch_b))
    branch_delta = branch_delta - main_dir * branch_delta.dot(main_dir)
    side = branch_delta.dot(horizontal)
    if abs(side) <= api.EPS:
        raise ValueError("Wye branches do not separate along the horizontal profile axis")
    if side < 0.0:
        horizontal = horizontal * -1.0

    branch_a_extent = _wye_horizontal_extent(api, branch_a)
    branch_b_extent = _wye_horizontal_extent(api, branch_b)
    ratio = branch_a_extent / (branch_a_extent + branch_b_extent)
    positive, negative = api.split_profile_face_by_extent(main_profile, horizontal, ratio)

    # The cut sits where split_profile_face_by_extent puts it: the positive
    # half takes `ratio` of the extent from the high side.
    low, high = api.profile_projection_bounds(main_profile, horizontal)
    cut = high - (high - low) * ratio
    centre = api.port_position(main_center)
    origin = centre + horizontal * (cut - centre.dot(horizontal))
    return {id(branch_a): positive, id(branch_b): negative}, (origin, horizontal)


def _wye_route_clearance(api, branch):
    """Small modeling clearance scaled to the branch profile."""
    return max(1.0e-2 * _size(api, branch), 0.1)


def _wye_elbow_route(api, branch, split_port, requested_radius, wall=0.0):
    """Build a route whose tangent points stay on both usable leg sides."""
    branch_size = _size(api, branch)
    clearance = _wye_route_clearance(api, branch)

    # The minimum keeps the inside of the swept profile (and of each wall
    # layer around it) from folding through the bend centerline.
    radius = max(float(requested_radius or 0.0), _min_bend_radius(branch_size, wall))
    route = api.make_elbow_path(branch, split_port, radius)

    # An offset split profile can need more radius before both tangent points
    # lie beyond their source ports. The signed distances vary linearly with R.
    signed_trims = [
        (api.port_position(route_port) - api.port_position(source_port)).dot(api.unit(api.port_direction(source_port)))
        for route_port, source_port in zip(route["ports"], (branch, split_port))
    ]
    deficit = clearance - signed_trims[0]
    if deficit > 0.0:
        theta = api.angle_between(api.port_direction(branch), api.port_direction(split_port))
        radius += deficit * math.tan(theta / 2.0)
        route = api.make_elbow_path(branch, split_port, radius)

    route["radius"] = radius
    return route


# Growth of a wye leg's bend radius per step while its branch end still crosses the
# split plane, and how many steps are tried before the layout refuses.
_WYE_RADIUS_GROWTH = 1.25
_WYE_RADIUS_STEPS = 16


def _wye_end_crosses_plane(api, route, plane, branch_index, offset=0.0):
    """Whether a leg's branch section (grown by `offset`) where its bend ends reaches the other side of the split plane."""
    origin, normal = plane
    low, high = api.profile_projection_bounds(api.profile_from_port(route["ports"][0], offset), normal)
    level = origin.dot(normal)
    tolerance = max(api.EPS, 1.0e-6 * _size(api, route["ports"][0]))
    if _wye_leg_side(branch_index) == "positive":
        return low < level - tolerance
    return high > level + tolerance


def _wye_split_route_layout(context):
    """Calculate shared port roles, split profiles, and feasible elbow paths."""
    api = context["hvac_api"]
    raw_ports = list(api.connected_ports(context))
    if len(raw_ports) != 3:
        raise ValueError("Fitting requires exactly three connected ports")

    main, branch_a, branch_b = _wye_port_roles(api, raw_ports)
    ports = [main, branch_a, branch_b]
    center = api.center_from_context(context)
    branch_legs = [(1, branch_a), (2, branch_b)]
    wall = _wall_thickness(context)
    radius = float(_props(context).get("BranchRadius") or 0.0)

    main_direction = api.unit(api.port_direction(main))
    main_axis_center = _port_axis_point(api, main, center)

    def build_routes(split_center, radii):
        split_faces, plane = _wye_main_split(api, split_center, branch_a, branch_b)
        result = []
        for (branch_index, branch), leg_radius in zip(branch_legs, radii):
            split_face = split_faces[id(branch)]
            split_port = api.copy_port(split_center, position=split_face.CenterOfMass)
            route = _wye_elbow_route(api, branch, split_port, leg_radius, wall)
            result.append((branch, branch_index, split_face, route))
        return result, plane

    def layout(radii):
        # Step 1: Build provisional paths at the junction center.
        main_center = api.copy_port(main, position=main_axis_center)
        routes, plane = build_routes(main_center, radii)

        # Step 2: Large radii can put an elbow tangent beyond the split plane.
        # Move the plane outward so each split half approaches its arc from behind.
        main_shift = max(
            [0.0]
            + [
                (api.port_position(route["ports"][1]) - split_face.CenterOfMass).dot(main_direction)
                + _wye_route_clearance(api, branch)
                for branch, _, split_face, route in routes
            ]
        )
        if main_shift > api.EPS:
            main_center = api.copy_port(main_center, position=main_axis_center + main_direction * main_shift)
            routes, plane = build_routes(main_center, radii)
        return main_center, routes, plane

    # Step 3: Each leg is cut by the split plane (design 6.6 A), so its branch
    # section must lie wholly on its own side where the bend ends. Legs at a
    # narrow angle leave each other further out: their bends get a larger
    # radius (BranchRadius is a minimum here, as it already is for clearance).
    radii = [radius, radius]
    for _attempt in range(_WYE_RADIUS_STEPS):
        main_center, routes, plane = layout(radii)
        crossing = [_wye_end_crosses_plane(api, route, plane, index, wall) for _b, index, _f, route in routes]
        if not any(crossing):
            break
        radii = [
            route["radius"] * _WYE_RADIUS_GROWTH if crosses else leg_radius
            for crosses, leg_radius, (_b, _i, _f, route) in zip(crossing, radii, routes)
        ]
    else:
        raise ValueError(
            "Wye branches overlap where they leave the fitting: increase the angle between them or BranchRadius"
        )

    return ports, center, main_center, routes, plane


def _wye_turn(api, route):
    """
    (axis, across at the main end, across at the branch end) of a leg's bend:
    a section direction at the main end, written as axis * a + across_main * b,
    arrives at the branch end as axis * a + across_branch * b.
    """
    main_tangent, branch_tangent = route["ports"][1], route["ports"][0]
    start_dir = api.unit(api.port_direction(main_tangent)) * -1.0
    end_dir = api.unit(api.port_direction(branch_tangent))
    bend_axis = start_dir.cross(end_dir)
    if bend_axis.Length <= api.EPS:
        return None
    axis = api.unit(bend_axis)
    return axis, axis.cross(start_dir), axis.cross(end_dir)


def _wye_matched_ends(api, route, start, end):
    """
    The two section wires a leg's sweep runs between, with matching corners.

    A round section is one edge while a rectangle or oval has corners, so a
    sweep from one to the other twists. The round one is drawn as arcs that
    meet where the other section's corners arrive after turning through the
    bend (about the bend axis), so both have the same corners in the same
    places. Two round sections, or two with corners, are used as they are.
    """
    start_round, end_round = start.profile == "Circular", end.profile == "Circular"
    if start_round == end_round:
        return start, end
    turn = _wye_turn(api, route)
    if end_round:
        corners, centre, other = start.wire.Vertexes, start.center, end
    else:
        corners, centre, other = end.wire.Vertexes, end.center, start
    directions = []
    for vertex in corners:
        relative = vertex.Point - centre
        if turn is not None:
            axis, across_main, across_branch = turn
            if end_round:
                relative = axis * relative.dot(axis) + across_branch * relative.dot(across_main)
            else:
                relative = axis * relative.dot(axis) + across_main * relative.dot(across_branch)
        directions.append(relative)
    if len(directions) < 2:
        return start, end
    wire = api.make_circular_wire_split_at(other.center, other.direction, float(other.params["Diameter"]), directions)
    return (start, wire) if end_round else (wire, end)


def _wye_leg_side(branch_index):
    """Which side of the split plane a leg is kept on: branch A (index 1) the positive one."""
    return "positive" if branch_index == 1 else "negative"


def _wye_leg_piece(api, leg, main_center, plane, offset, cuts=None):
    """
    One leg of a plane-split wye (design 6.6 A), grown by `offset`.

    The leg starts from the *full* common section on the split station,
    centred on the main axis: a straight piece up to its bend's start, then
    the bend into the branch section (a sweep along the arc, or faceted
    gores when `cuts` is given). The result is cut by the split plane and
    only the leg's own side kept, so the two legs meet face to face on a
    plane -- which a plain fuse handles -- instead of along the curved,
    tangent faces two split-half sweeps used to share.

    Returns (piece, trim along the branch to where the bend ends).
    """
    branch, route = leg["branch"], leg["route"]
    main_dir = api.unit(api.port_direction(main_center))
    centre = api.port_position(main_center)

    # Step 1: a branch section that crosses the split plane at the bend's end
    # would lose part of itself to the cut. The layout grows the radius to
    # avoid it, so this only guards a wall grown beyond what it allowed for.
    end_profile = api.profile_from_port(route["ports"][0], offset)
    tolerance = max(api.EPS, 1.0e-6 * _size(api, branch))
    if _wye_end_crosses_plane(api, route, plane, leg["branch_index"], offset):
        raise ValueError(
            "Wye branches overlap where they leave the fitting: increase the angle between them or BranchRadius"
        )

    # Step 2: the straight piece, full common section, from the split station to the bend start.
    station = (api.port_position(route["ports"][1]) - centre).dot(main_dir)
    bend_start = api.copy_port(main_center, position=centre + main_dir * station)
    start_profile = api.profile_from_port(bend_start, offset)
    pieces = []
    if abs(station) > tolerance:
        pieces.append(_outward(api.extrude(api.profile_from_port(main_center, offset), main_dir * station, solid=True)))

    # Step 3: the bend from the full common section into the branch.
    if cuts is not None:
        split_port = api.copy_port(main_center, position=leg["split_face"].CenterOfMass)
        bend, bend_trims = _mitered_bend(
            api, branch, split_port, route["radius"], cuts, profile1=start_profile, offset=offset
        )
        branch_trim = bend_trims[0]
    else:
        try:
            start_wire, end_wire = _wye_matched_ends(api, route, start_profile, end_profile)
            bend = api.sweep([start_wire, end_wire], api.reverse(route["path"]), solid=True)
        except Exception as exc:
            raise RuntimeError(
                "Wye branch sweep failed at effective radius {:.3f} mm: {}".format(route["radius"], exc)
            ) from exc
        branch_trim = route["trim_lengths"][0]
    pieces.append(_outward(bend))

    # Step 4: keep only the leg's own side of the split plane.
    piece = api.fuse(*pieces) if len(pieces) > 1 else pieces[0]
    return api.clip_plane(piece, plane, side=leg["side"]), branch_trim


# A crotch plate is left out when the other leg's grown piece already holds this
# share of it: the wall it would add is there already.
_WYE_PLATE_COVERED = 0.99
# A plate cut from the other leg's piece is trusted only up to this multiple of
# the volume the two legs' faces on the split plane allow for.
_WYE_PLATE_SLACK = 1.1


def _wye_crotch_plates(api, pieces, plane, offset):
    """
    Wall plates on the split plane for an asymmetric wye (design 6.6 A 5).

    Where one leg's section on the plane reaches past the other's, its air
    face lies on the plane with no wall beyond it. The plate fills that
    region to one wall thickness on the other leg's side.

    Step 1 decides whether a side needs a plate at all, from the two legs'
    faces on the plane: nothing is left of one minus the other on a
    symmetric wye or bullhead, and slivers narrower than the wall are
    ignored (their gap lies within the neighbouring wall, and a plate that
    thin only fuses as a separate solid).
    Step 2 builds the plate from the pieces themselves: the leg's own face
    extruded one wall thickness across the plane, minus the other leg's
    piece. The plate then shares the pieces' own faces, which fuses far
    more reliably than a plate drawn from the 2D difference.
    Step 3 falls back to the 2D difference where that cut misfires (it
    keeps more than the faces allow for), leaving out a plate the other
    leg's piece already holds.
    """
    _origin, normal = plane
    faces = [api.section_face(piece, plane) for piece in pieces]
    plates = []
    for own, other, other_piece, into in (
        (faces[0], faces[1], pieces[1], normal * -offset),
        (faces[1], faces[0], pieces[0], normal * offset),
    ):
        # Step 1: the region of this leg's face the other leg's face does not cover.
        regions = [
            face
            for face in api.cut(own, other).Faces
            if face.Area > api.EPS and 2.0 * face.Area / max(face.Length, api.EPS) >= offset
        ]
        if not regions:
            continue
        allowed = _WYE_PLATE_SLACK * sum(face.Area for face in regions) * offset + offset**3

        # Step 2: the leg's own face across the plane, minus the other leg.
        cut = []
        for face in own.Faces:
            prism = _outward(api.extrude(face.OuterWire, into, solid=True))
            cut.extend(solid for solid in api.cut(prism, other_piece).Solids if solid.Volume > offset**3)
        if cut and sum(solid.Volume for solid in cut) <= allowed:
            plates.extend(cut)
            continue

        # Step 3: the 2D difference, extruded.
        for face in regions:
            plate = _outward(api.extrude(face.OuterWire, into, solid=True))
            if api.common(plate, other_piece).Volume < _WYE_PLATE_COVERED * plate.Volume:
                plates.append(plate)
    return plates


def _wye_envelope(api, layout, offset, cuts=None, pieces=None):
    """
    A plane-split wye's whole outer boundary grown by `offset`: the main
    straight up to the split station, both legs (cut by the split plane),
    the crotch plates of a wall envelope, and each branch's straight trim.
    `pieces` reuses legs already built at this offset. Returns None when the
    fuse does not give one valid solid holding every piece.
    """
    main, main_center, trims = layout["main"], layout["main_center"], layout["trims"]
    legs = layout["routes"]
    if pieces is None:
        pieces = [_wye_leg_piece(api, leg, main_center, layout["plane"], offset, cuts)[0] for leg in legs]

    parts = list(pieces)
    if offset > 0.0:
        parts.extend(_wye_crotch_plates(api, pieces, layout["plane"], offset))

    # The main straight ends on the split station, where the two legs' start faces meet it.
    main_end = _trimmed(api, main, trims[0])
    main_reach = api.port_position(main_end) - api.port_position(main_center)
    if main_reach.Length > max(api.EPS, 1.0e-6 * _size(api, main)):
        parts.append(_loft(api, [main_end, main_center], offset, ruled=True))

    # Each branch's straight trim past its bend.
    for leg in legs:
        branch = leg["branch"]
        start = leg["route"]["ports"][0]
        end = _trimmed(api, branch, trims[leg["branch_index"]])
        if (api.port_position(end) - api.port_position(start)).Length > max(api.EPS, 1.0e-6 * _size(api, branch)):
            parts.append(_loft(api, [start, end], offset, ruled=True))

    try:
        shape = api.fuse(*parts)
    except Exception:
        return None
    return shape if _is_union_of(api, shape, parts) else None


def _wye_radius_layout(context):
    """Calculate the split plane, branch paths, and trims for a radius wye."""
    api = context["hvac_api"]
    p = _props(context)
    ports, center, main_center, routes, plane = _wye_split_route_layout(context)
    main = ports[0]
    main_direction = api.unit(api.port_direction(main))

    # Include the relocated split plane in the main-leg trim.
    minimums = _junction_minimums(api, center, ports)
    main_split_trim = (api.port_position(main_center) - api.port_position(main)).dot(main_direction)
    minimums[0] = max(minimums[0], main_split_trim)
    for _branch, branch_index, _split_face, route in routes:
        minimums[branch_index] = max(minimums[branch_index], route["trim_lengths"][0])

    trims = _junction_trims(api, p, ports, ("TrimMain", "TrimBranchA", "TrimBranchB"), (0.70, 0.70, 0.70), minimums)
    legs = [
        {
            "branch": branch,
            "branch_index": branch_index,
            "split_face": split_face,
            "route": route,
            "side": _wye_leg_side(branch_index),
        }
        for branch, branch_index, split_face, route in routes
    ]
    return {"ports": ports, "main": main, "main_center": main_center, "plane": plane, "routes": legs, "trims": trims}


def measure_wye_radius(context):
    api = context["hvac_api"]
    layout = _wye_radius_layout(context)
    return api.build_trim_rec_from_port_lengths(list(zip(layout["ports"], layout["trims"])))


def build_wye_radius(context):
    """Radius wye: each leg swept from the full common section into its branch, cut by the split plane."""
    api = context["hvac_api"]
    layout = _wye_radius_layout(context)
    ports, trims = layout["ports"], layout["trims"]

    def envelope(offset):
        shape = _wye_envelope(api, layout, offset)
        if shape is None:
            requested_radius = float(_props(context).get("BranchRadius") or 0.0)
            effective_radii = ", ".join("{:.3f}".format(leg["route"]["radius"]) for leg in layout["routes"])
            raise RuntimeError(
                "Wye geometry could not be fused into one valid solid "
                "(requested radius {:.3f} mm; effective branch radii {} mm)".format(requested_radius, effective_radii)
            )
        return shape

    return _finish(context, envelope, api.build_trim_rec_from_port_lengths(list(zip(ports, trims))))
