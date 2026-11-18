# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the HVAC addon.

"""
Construction-feature generators shared by every library (ROADMAP 6.2).

A type-def declares one with
`"construction": {"features": [{"id": "transverse_flange", "role":
"transverse_joint", "host_layer": "<its structural layer>", "module":
"shared:features", "generator": "transverse_flange", "parameters": [...]}]}`.
Each generator is called as `generator(api, ctx)` with a FeatureContext and
returns one shape, or None for nothing to add. The shape is kept as the
feature's own geometry, never fused into a layer.
"""

from ._common import _flange_enabled, _layer_thickness, _trimmed

_EPS = 1.0e-7


def _params(ctx):
    full = dict(ctx.context.get("properties") or {})
    full.update(dict(ctx.parameters or {}))
    return full


def _host_outer_offset(ctx, params):
    """Wall build-up from the air boundary to the host layer's outer face."""
    offset = 0.0
    for layer_def in ctx.context.get("construction_layers") or []:
        offset += _layer_thickness(layer_def, params)
        if layer_def.id == ctx.host_layer_id:
            return offset
    raise ValueError("Flange host layer '{}' is not one of the type's construction layers".format(ctx.host_layer_id))


def _role_suffixes(api, context):
    """{edge_key: "RunA" | "Branch" | ...} from the node's port roles, for ShowFlange<Role>."""
    try:
        roles = api.port_roles(context)
    except Exception:
        return {}
    return {
        port.get("edge_key"): "".join(part.capitalize() for part in role.split("_")) for role, port in roles.items()
    }


def _flange_ends(api, ctx, params):
    """
    (port, edge_key or None) for every end face a flange can go on, each port
    already moved to the fitting's real end:
      1. context["flange_ports"]: set by a generator whose ends are not
         its trimmed connected ports (a PartScript elbow's tangent points);
      2. the connected ports, each pushed out by its connection length;
      3. a segment, which has no connected ports: its start and end points.
    """
    context = ctx.context
    flange_ports = context.get("flange_ports")
    if flange_ports:
        return [(port, port.get("edge_key")) for port in flange_ports]

    ports = list(api.connected_ports(context))
    if ports:
        lengths = {
            rec["edge_key"]: float(rec["length"]) for rec in (getattr(ctx.result, "connection_lengths", None) or [])
        }
        return [
            (_trimmed(api, port, lengths[port.get("edge_key")]), port.get("edge_key"))
            for port in ports
            if port.get("edge_key") in lengths
        ]

    if context.get("start_point") is None or context.get("end_point") is None:
        return []
    start = api.vec(context["start_point"])
    end = api.vec(context["end_point"])
    # A curved segment's ends face along its path tangents, not along the chord.
    chord = api.unit(end - start)
    start_dir = api.unit(api.vec(context["start_direction"])) if context.get("start_direction") is not None else chord
    end_dir = api.unit(api.vec(context["end_direction"])) if context.get("end_direction") is not None else chord
    start_port = {
        "position": start,
        "direction": start_dir * -1.0,
        "profile": context.get("profile", ""),
        "section_params": params,
        "profile_x_axis": context.get("profile_x_axis"),
    }
    return [(start_port, None), (api.copy_port(start_port, position=end, direction=end_dir), None)]


def transverse_flange(api, ctx):
    """
    A flange collar at every enabled end of a fitting or segment, on the outer
    face of the host layer. Needs FlangeThickness and FlangeHeight above zero.
    Per-port switch, first one the type declares: ShowFlange<Role> (e.g.
    ShowFlangeBranch), ShowFlange<N> (1-based), ShowFlange (shared or per
    port). Default: every end.
    """
    params = _params(ctx)
    flange_thickness = float(params.get("FlangeThickness", 0.0) or 0.0)
    flange_height = float(params.get("FlangeHeight", 0.0) or 0.0)
    if flange_thickness <= _EPS or flange_height <= _EPS:
        return None

    outer_offset = _host_outer_offset(ctx, params)
    suffixes = _role_suffixes(api, ctx.context)
    shapes = []
    for index, (port, edge_key) in enumerate(_flange_ends(api, ctx, params)):
        if not _flange_enabled(params, index, suffixes.get(edge_key), port if edge_key else None):
            continue
        end = api.grow_port_section(port, outer_offset)
        shapes.append(api.make_flange(end, api.port_direction(port) * -1.0, flange_thickness, flange_height))
    if not shapes:
        return None
    return api.refine(api.fuse(*shapes)) if len(shapes) > 1 else shapes[0]


def _path_stations(api, context, pitch):
    """
    (point, tangent) every `pitch` along a segment's path, from half a pitch in,
    so the ribs sit evenly between both ends. Follows the path edge of a curved
    segment, else the straight line from start to end.
    """
    start = api.vec(context["start_point"])
    end = api.vec(context["end_point"])
    edge = context.get("path_edge")
    length = float(edge.Length) if edge is not None else (end - start).Length
    count = int(length // pitch)
    if count < 1:
        return []
    margin = 0.5 * (length - (count - 1) * pitch)
    stations = []
    for index in range(count):
        distance = margin + index * pitch
        if edge is not None:
            parameter = edge.getParameterByLength(distance)
            stations.append((edge.valueAt(parameter), api.unit(edge.tangentAt(parameter))))
        else:
            axis = api.unit(end - start)
            stations.append((start + axis * distance, axis))
    return stations


def flex_ribs(api, ctx):
    """
    The wire-helix ribs of a flexible duct, drawn as rings: one every RibPitch
    along the segment's path, RibWidth wide, standing RibHeight proud of the
    host layer's outer face. Drawn as a feature so the duct body stays a plain
    sweep (cheap to build and to fuse) and the ribs can be hidden with Layer
    Visibility. Needs RibPitch, RibWidth and RibHeight above zero.
    """
    params = _params(ctx)
    pitch = float(params.get("RibPitch", 0.0) or 0.0)
    width = float(params.get("RibWidth", 0.0) or 0.0)
    height = float(params.get("RibHeight", 0.0) or 0.0)
    context = ctx.context
    if min(pitch, width, height) <= _EPS or context.get("start_point") is None or context.get("end_point") is None:
        return None
    width = min(width, 0.9 * pitch)

    outer_offset = _host_outer_offset(ctx, params)
    section = {"Diameter": params["Diameter"]} if "Diameter" in params else dict(params)
    rings = []
    for point, tangent in _path_stations(api, context, pitch):
        # Each ring is centred on its station, square to the path there.
        port = {
            "position": point - tangent * (0.5 * width),
            "direction": tangent * -1.0,
            "profile": context.get("profile", ""),
            "section_params": section,
            "profile_x_axis": context.get("profile_x_axis"),
        }
        rings.append(api.make_flange(api.grow_port_section(port, outer_offset), tangent, width, height))
    if not rings:
        return None
    # A compound, not a fuse: the rings never touch, and fusing hundreds of them would be slow.
    return api.compound(rings)
