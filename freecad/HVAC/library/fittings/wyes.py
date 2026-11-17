# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the HVAC addon.

"""
Wyes: one main port splitting into two branch routes (mitered and radius).
"""

import math

from ._common import (
    _extend_leg,
    _finish,
    _is_union_of,
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


def _wye_mitered_branch_shapes(api, branch, split_face, route, main_center, cuts, offset=0.0):
    """
    The two pieces that carry one branch into the common leg of a mitered wye.

    Returns (split_shape, bend_shape, branch_trim):
    - split_shape: the branch's own half of the main profile, extruded from
      the split plane up to where its bend starts (None if they coincide).
    - bend_shape: the faceted bend from there to the branch.

    `offset` grows both pieces outward by a wall offset (see _common._finish).
    The split plane, bend route and trim never depend on it.
    """
    split_wire = api.offset_wire(split_face.OuterWire, offset)
    split_port = api.copy_port(main_center, position=split_face.CenterOfMass)
    main_tangent = route["ports"][1]
    main_tangent_position = api.port_position(main_tangent)
    main_reach = main_tangent_position - split_face.CenterOfMass
    tangent_wire = split_wire
    split_shape = None
    if main_reach.Length > api.EPS:
        split_shape = api.extrude(split_wire, main_reach, solid=True)
        tangent_face = api.section_face(split_shape, (main_tangent_position, api.port_direction(main_tangent)))
        tangent_wire = tangent_face.OuterWire

    bend_shape, route_trims = _mitered_bend(
        api, branch, split_port, route["radius"], cuts, profile1=tangent_wire, offset=offset
    )
    return split_shape, bend_shape, route_trims[0]


def _wye_mitered_layout(context):
    """
    Lay out two split-profile faceted bends entering one common leg.

    measure_wye_mitered() and build_wye_mitered() both use this layout, so
    their trims agree.
    """
    api = context["hvac_api"]
    p = _props(context)
    cuts = max(int(p.get("NumberOfCuts", 2) or 2), 1)

    # Reuse the same split plane and feasible elbow paths as the radius wye.
    ports, center, main_center, split_routes = _wye_split_route_layout(context)
    main = ports[0]
    main_direction = api.unit(api.port_direction(main))
    routes = []
    intrinsic_shapes = []

    for branch, branch_index, split_face, route in split_routes:
        split_shape, bend_shape, branch_trim = _wye_mitered_branch_shapes(
            api, branch, split_face, route, main_center, cuts
        )
        routes.append(
            {
                "branch": branch,
                "branch_index": branch_index,
                "split_face": split_face,
                "route": route,
                "split_shape": split_shape,
                "bend_shape": bend_shape,
                "branch_trim": branch_trim,
                "radius": route["radius"],
            }
        )
        intrinsic_shapes.extend((split_shape, bend_shape))

    intrinsic_shape = api.compound(intrinsic_shapes)

    minimums = _junction_minimums(api, center, ports)
    minimums = _junction_shape_minimums(api, center, ports, intrinsic_shape, minimums)
    main_split_trim = (api.port_position(main_center) - api.port_position(main)).dot(main_direction)
    minimums[0] = max(minimums[0], main_split_trim)

    for route in routes:
        branch_index = route["branch_index"]
        minimums[branch_index] = max(minimums[branch_index], route["branch_trim"])

    trims = _junction_trims(api, p, ports, ("TrimMain", "TrimBranchA", "TrimBranchB"), (0.70, 0.70, 0.70), minimums)

    return {
        "ports": ports,
        "center": center,
        "main": main,
        "main_center": main_center,
        "cuts": cuts,
        "routes": routes,
        "trims": trims,
    }


def measure_wye_mitered(context):
    api = context["hvac_api"]
    layout = _wye_mitered_layout(context)

    return api.build_trim_rec_from_port_lengths(list(zip(layout["ports"], layout["trims"])))


def _wye_mitered_envelope(api, layout, offset):
    """The mitered wye's whole outer boundary grown by `offset`: main leg, split halves and bends, fused."""
    main = layout["main"]
    main_center = layout["main_center"]
    trims = layout["trims"]
    main_end = _trimmed(api, main, trims[0])
    main_reach = api.port_position(main_end) - api.port_position(main_center)
    main_tolerance = max(api.EPS, 1.0e-6 * _size(api, main))

    shape = None
    if main_reach.Length > main_tolerance:
        shape = _loft(api, [main_end, main_center], offset, ruled=True)

    for route in layout["routes"]:
        branch = route["branch"]
        # The layout already built the air-space pieces to measure them;
        # only a wall envelope (offset > 0) needs them built again, larger.
        if offset > 0.0:
            split_shape, bend_shape, _ = _wye_mitered_branch_shapes(
                api, branch, route["split_face"], route["route"], main_center, layout["cuts"], offset
            )
        else:
            split_shape, bend_shape = route["split_shape"], route["bend_shape"]
        bend_shape = _extend_leg(api, bend_shape, branch, route["branch_trim"], trims[route["branch_index"]], offset)
        shape = api.fuse(shape, split_shape, bend_shape)
    return shape


def build_wye_mitered(context):
    """Mitered wye with each non-main branch entering the common leg through a faceted bend."""
    api = context["hvac_api"]
    layout = _wye_mitered_layout(context)
    ports = layout["ports"]
    trims = layout["trims"]

    def envelope(offset):
        shape = _wye_mitered_envelope(api, layout, offset)
        validation = api.validate(shape, require_solid=True)
        if not validation["valid"] or validation["solid_count"] != 1:
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


def _wye_split_crosses_curve(api, main, branch_a, branch_b):
    """
    Whether the line splitting the main section between the branches crosses
    a curved side: always on a round duct, on an oval when the cut falls in
    one of its rounded ends, never on a rectangle.

    Where it does, the walls of the two halves would overlap past the cut and
    meet at a grazing angle, which OpenCascade's booleans cannot fuse
    reliably; _wye_main_split_faces then narrows the strip past the cut.
    """
    profile = api.port_profile(main)
    if profile == "Circular":
        return True
    if profile != "Oval":
        return False
    width, height = float(api.port_width(main)), float(api.port_height(main))
    extent_a, extent_b = _wye_horizontal_extent(api, branch_a), _wye_horizontal_extent(api, branch_b)
    cut_from_centre = abs(width * (0.5 - extent_a / (extent_a + extent_b)))
    return cut_from_centre >= max(width - height, 0.0) / 2.0 - api.EPS


# How far (as a share of the wall offset) the strip past the cut is grown on a curved side.
_WYE_STRIP_GROWTH = 0.5


def _wye_main_split_faces(api, main_center, branch_a, branch_b, offset=0.0, curved=False):
    """
    Split the main profile horizontally in proportion to the branches.

    With an `offset` each half is cut from the grown profile, so a half of a
    wall envelope has the same corners as its air half (offsetting the air
    half's wire can add a corner where the arc meets the cut).

    `curved` (the cut crosses a curved side, _wye_split_crosses_curve): the
    strip each grown half reaches past the cut is taken from the profile
    grown by half the offset only. Grown fully, the two halves would share
    the same curved outer face along the strip and meet the other half's
    bend at a grazing angle, which a plain fuse cannot handle; narrowed,
    the strip lies inside the other half's wall wherever both are present.
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
    offset = float(offset)
    if abs(offset) <= api.EPS:
        positive, negative = api.split_profile_face_by_extent(main_profile, horizontal, ratio)
        return {id(branch_a): positive, id(branch_b): negative}

    # Each grown half reaches `offset` past the cut as well, so the wall keeps
    # its thickness in the crotch where the two legs part.
    low, high = api.profile_projection_bounds(main_profile, horizontal)
    extent = high - low
    grown = api.profile_from_port(main_center, offset)
    if curved:
        # Each grown half up to the cut, plus a strip past the cut from the half-grown profile.
        at_cut_positive, at_cut_negative = api.split_profile_face_by_extent(
            grown, horizontal, (extent * ratio + offset) / (extent + 2.0 * offset)
        )
        g = _WYE_STRIP_GROWTH * offset
        narrow = api.profile_from_port(main_center, g)
        strip_positive, _ = api.split_profile_face_by_extent(
            narrow, horizontal, (extent * ratio + g + offset) / (extent + 2.0 * g)
        )
        _, strip_negative = api.split_profile_face_by_extent(
            narrow, horizontal, (extent * ratio + g - offset) / (extent + 2.0 * g)
        )

        def merged(face, strip):
            faces = api.refine(api.fuse(face, strip)).Faces
            if len(faces) != 1:
                raise RuntimeError("Wye split half did not merge into one face")
            return faces[0]

        return {
            id(branch_a): merged(at_cut_positive, strip_positive),
            id(branch_b): merged(at_cut_negative, strip_negative),
        }
    positive, _ = api.split_profile_face_by_extent(
        grown, horizontal, (extent * ratio + 2.0 * offset) / (extent + 2.0 * offset)
    )
    _, negative = api.split_profile_face_by_extent(grown, horizontal, extent * ratio / (extent + 2.0 * offset))
    return {id(branch_a): positive, id(branch_b): negative}


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

    # Step 1: Build provisional paths at the junction center.
    main_direction = api.unit(api.port_direction(main))
    main_axis_center = _port_axis_point(api, main, center)
    main_center = api.copy_port(main, position=main_axis_center)

    def build_routes(split_center):
        split_faces = _wye_main_split_faces(api, split_center, branch_a, branch_b)
        result = []
        for branch_index, branch in branch_legs:
            split_face = split_faces[id(branch)]
            split_port = api.copy_port(split_center, position=split_face.CenterOfMass)
            route = _wye_elbow_route(api, branch, split_port, radius, wall)
            result.append((branch, branch_index, split_face, route))
        return result

    routes = build_routes(main_center)

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
        main_center = api.copy_port(main_center, position=api.port_position(main_center) + main_direction * main_shift)
        routes = build_routes(main_center)

    return ports, center, main_center, routes


def _wye_branch_end_wire(api, route, start_wire, offset):
    """
    The section a split-half sweep ends on at the branch tangent.

    A round branch end is one edge, while the split half it comes from has
    corners, so the sweep twists. The circle is cut where the half's corners
    arrive after turning through the bend (about the bend axis), giving it
    the same number of corners in the same places.
    """
    main_tangent, branch_tangent = route["ports"][1], route["ports"][0]
    profile = api.profile_from_port(branch_tangent, offset)
    corners = [vertex.Point for vertex in start_wire.Vertexes]
    if profile.profile != "Circular" or len(corners) < 2:
        return profile

    start_dir = api.unit(api.port_direction(main_tangent)) * -1.0
    end_dir = api.unit(api.port_direction(branch_tangent))
    bend_axis = start_dir.cross(end_dir)
    start_center = api.port_position(main_tangent)
    directions = []
    for corner in corners:
        relative = corner - start_center
        if bend_axis.Length <= api.EPS:
            directions.append(relative)
            continue
        axis = api.unit(bend_axis)
        across_start, across_end = axis.cross(start_dir), axis.cross(end_dir)
        directions.append(axis * relative.dot(axis) + across_end * relative.dot(across_start))
    return api.make_circular_wire_split_at(profile.center, end_dir, float(profile.params["Diameter"]), directions)


# The order a radius wye's pieces are fused in. OCC booleans on swept solids
# that share seams depend on the order; this one was chosen with the smoke run
# (tools/geometry_smoke.py) as the one that builds the most cases.
_WYE_RADIUS_FUSE_ORDER = ("split_a", "split_b", "bend_a", "bend_b", "main", "trim_a", "trim_b")


def _wye_radius_layout(context):
    """Calculate the split profiles, branch paths, and trims for a wye."""
    api = context["hvac_api"]
    p = _props(context)
    ports, center, main_center, routes = _wye_split_route_layout(context)
    main = ports[0]
    main_direction = api.unit(api.port_direction(main))

    # Include the relocated split plane in the main-leg trim.
    minimums = _junction_minimums(api, center, ports)
    main_split_trim = (api.port_position(main_center) - api.port_position(main)).dot(main_direction)
    minimums[0] = max(minimums[0], main_split_trim)
    for _branch, branch_index, _split_face, route in routes:
        minimums[branch_index] = max(minimums[branch_index], route["trim_lengths"][0])

    trims = _junction_trims(api, p, ports, ("TrimMain", "TrimBranchA", "TrimBranchB"), (0.70, 0.70, 0.70), minimums)
    return ports, main_center, routes, trims


def measure_wye_radius(context):
    api = context["hvac_api"]
    ports, _main_center, _routes, trims = _wye_radius_layout(context)
    return api.build_trim_rec_from_port_lengths(list(zip(ports, trims)))


def build_wye_radius(context):
    """Build a radiused wye from a horizontally divided main profile."""
    api = context["hvac_api"]
    ports, main_center, routes, trims = _wye_radius_layout(context)
    split_crosses_curve = _wye_split_crosses_curve(api, ports[0], ports[1], ports[2])

    def envelope(offset):
        # Sweep each split half of the main profile into its branch tangent.
        split_sweeps = []
        branch_sweeps = []
        grown_faces = _wye_main_split_faces(api, main_center, ports[1], ports[2], offset, split_crosses_curve)
        for branch, _branch_index, split_face, route in routes:
            main_tangent = route["ports"][1]
            main_tangent_position = api.port_position(main_tangent)
            main_reach = main_tangent_position - split_face.CenterOfMass
            split_wire = grown_faces[id(branch)].OuterWire
            tangent_wire = split_wire
            if main_reach.Length > api.EPS:
                route_overlap = 0.1 * _wye_route_clearance(api, branch)
                section_probe = api.extrude(split_wire, main_reach, solid=True)
                probe = api.extrude(split_wire, main_reach + api.unit(main_reach) * route_overlap, solid=True)
                tangent_face = api.section_face(
                    section_probe, (main_tangent_position, api.port_direction(main_tangent))
                )
                tangent_wire = tangent_face.OuterWire
                split_sweeps.append(probe)
            else:
                split_sweeps.append(None)

            try:
                branch_sweeps.append(
                    api.sweep(
                        [tangent_wire, _wye_branch_end_wire(api, route, tangent_wire, offset)],
                        api.reverse(route["path"]),
                        solid=True,
                    )
                )
            except Exception as exc:
                raise RuntimeError(
                    "Wye branch sweep failed at effective radius {:.3f} mm: {}".format(route["radius"], exc)
                ) from exc

        # A small scaled overlap avoids a coplanar boolean at the split plane;
        # the full main profile still stops at the split approach itself.
        main_overlap = 0.1 * min(_wye_route_clearance(api, branch) for branch, _, _, _ in routes)
        main_trim_start = api.copy_port(
            main_center,
            position=(api.port_position(main_center) - api.unit(api.port_direction(main_center)) * main_overlap),
        )
        trim_starts = [main_trim_start] + [route["ports"][0] for _, _, _, route in routes]
        trim_sweeps = []
        for port, trim_start, trim in zip(ports, trim_starts, trims):
            trim_end = _trimmed(api, port, trim)
            trim_reach = api.port_position(trim_end) - api.port_position(trim_start)
            trim_tolerance = max(api.EPS, 1.0e-6 * _size(api, port))
            if trim_reach.Length <= trim_tolerance:
                trim_sweeps.append(None)
                continue
            trim_path = api.make_line(api.port_position(trim_start), api.port_position(trim_end))
            try:
                trim_sweeps.append(
                    api.sweep(
                        [api.profile_from_port(trim_start, offset), api.profile_from_port(trim_end, offset)],
                        trim_path,
                        solid=True,
                    )
                )
            except Exception as exc:
                edge_key = str(port.get("edge_key", "") or "?")
                raise RuntimeError(
                    "Wye trim sweep failed for port '{}' at {:.6f} mm: {}".format(edge_key, trim_reach.Length, exc)
                ) from exc

        # One fuse, in one fixed order (see _WYE_RADIUS_FUSE_ORDER).
        named = {"main": trim_sweeps[0]}
        for leg, side in enumerate("ab"):
            named.update(
                {
                    "split_" + side: split_sweeps[leg],
                    "bend_" + side: branch_sweeps[leg],
                    "trim_" + side: trim_sweeps[leg + 1],
                }
            )
        pieces = [named[name] for name in _WYE_RADIUS_FUSE_ORDER if named[name] is not None]
        try:
            shape = api.fuse(*pieces)
        except Exception:
            shape = None
        if not _is_union_of(api, shape, pieces):
            requested_radius = float(_props(context).get("BranchRadius") or 0.0)
            effective_radii = ", ".join("{:.3f}".format(route["radius"]) for _, _, _, route in routes)
            raise RuntimeError(
                "Wye geometry could not be fused into one valid solid "
                "(requested radius {:.3f} mm; effective branch radii {} mm): use the mitered wye".format(
                    requested_radius, effective_radii
                )
            )
        return shape

    return _finish(context, envelope, api.build_trim_rec_from_port_lengths(list(zip(ports, trims))))
