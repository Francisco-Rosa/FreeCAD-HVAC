# SPDX-License-Identifier: LGPL-2.1-or-later
"""
The "static" geometry backend: builds a type's shape from a pre-made
BREP/STEP file instead of generating one in code. A JSON descriptor
alongside that file says how to place it (which point on the file's own
shape lines up with which connected port) and, optionally, which of its
faces are the trim planes / connection points a junction needs to report.

build_static_geometry() is the entry point (called from Library.py's
build_geometry). In short, it: loads the descriptor, reads the shape file,
works out the one transform that moves the shape from its own local
placement to the real, connected position/direction, applies it, sanity-
checks the result against what the descriptor promised, and returns any
extra outputs the descriptor declares (connection lengths, trim planes).
"""

import json
import math
import os

import FreeCAD
import Part


class StaticGeometryError(Exception):
    pass


class StaticDescriptorError(StaticGeometryError):
    pass


def _load_descriptor(descriptor_path):
    """Read and sanity-check the JSON descriptor file next to the shape file."""
    if not os.path.isfile(descriptor_path):
        raise StaticDescriptorError("Static descriptor not found: '{}'".format(descriptor_path))
    with open(descriptor_path, "r", encoding="utf-8") as handle:
        desc = json.load(handle)
    if int(desc.get("schema_version", 1)) != 1:
        raise StaticDescriptorError(
            "Unsupported static descriptor schema_version {!r}".format(desc.get("schema_version"))
        )
    if not isinstance(desc.get("source"), dict) or not desc["source"].get("file"):
        raise StaticDescriptorError("Static descriptor requires source.file")
    return desc


def _source_path(descriptor_path, source):
    """Resolve the descriptor's source.file to an absolute path, and refuse to leave its own directory."""
    base = os.path.dirname(os.path.realpath(descriptor_path))
    path = os.path.realpath(os.path.join(base, source["file"]))
    if os.path.commonpath([base, path]) != base:
        raise StaticDescriptorError("Static source escapes descriptor directory")
    return path


def _read_shape(descriptor_path, source):
    """Load the shape file (STEP or BREP) the descriptor points to."""
    path = _source_path(descriptor_path, source)
    if not os.path.isfile(path):
        raise StaticDescriptorError("Static geometry file not found: '{}'".format(path))

    fmt = str(source.get("format", "") or "").strip().lower()
    if not fmt:
        fmt = os.path.splitext(path)[1].lower().lstrip(".")

    shape = Part.Shape()
    if fmt in ("step", "stp"):
        shape.read(path)
    elif fmt in ("brep", "brp"):
        shape.importBrep(path)
    else:
        raise StaticDescriptorError("Unsupported static geometry format '{}'".format(fmt))

    if shape.isNull():
        raise StaticGeometryError("Static geometry '{}' produced an empty shape".format(path))
    return shape


def _runtime_ports(context, api):
    """
    The real, connected ports to line the static shape up against.

    A junction's context already has these (connected_ports, from the
    network's own topology analysis). A segment's context doesn't -- it
    only has a start/end point -- so build the equivalent two-port list
    from that instead.
    """
    if "connected_ports" in context:
        return list(context.get("connected_ports", []) or [])

    sp = api.vec(context["start_point"])
    ep = api.vec(context["end_point"])
    axis = api.unit(ep - sp)
    x_axis = context.get("profile_x_axis")
    profile = context.get("profile", "")
    params = dict(context.get("properties", {}) or {})
    return [
        {
            "position": sp,
            "direction": axis * -1.0,
            "profile_x_axis": x_axis,
            "profile": profile,
            "section_params": params,
            "segment_end": "start",
        },
        {
            "position": ep,
            "direction": axis,
            "profile_x_axis": x_axis,
            "profile": profile,
            "section_params": params,
            "segment_end": "end",
        },
    ]


def _context_origin(context, api, runtime_ports, mode, anchor_index):
    """Look up one reference point from the context, by the descriptor's requested origin_context mode."""
    if mode == "center_point":
        if context.get("center_point") is None:
            raise StaticDescriptorError("placement.origin_context='center_point' requires center_point")
        return api.vec(context["center_point"])
    if mode == "start_point":
        return api.vec(context["start_point"])
    if mode == "end_point":
        return api.vec(context["end_point"])
    if mode == "runtime_port":
        return api.port_position(runtime_ports[anchor_index])
    raise StaticDescriptorError("Unknown placement.origin_context '{}'".format(mode))


def _build_transform(desc, context, api, runtime_ports):
    """
    Work out the one transform that carries the shape from its own local
    placement to its real, connected position/direction in the model.

    One port in the descriptor is picked as the "anchor" (placement.
    runtime_port). We build two matching coordinate frames: the shape's own
    local frame at that port (as authored, from the descriptor), and the
    real frame at the same port (from the actual connected duct). The
    transform that turns one into the other is real_frame * local_frame^-1
    -- applying it moves every point as if it were expressed in the local
    frame and re-expressed in the real one.
    """
    placement = dict(desc.get("placement", {}) or {})
    anchor_index = int(placement.get("runtime_port", 0))
    if anchor_index < 0 or anchor_index >= len(runtime_ports):
        raise StaticDescriptorError("placement.runtime_port {} is out of range".format(anchor_index))

    local_origin = api.vec(placement.get("origin", [0.0, 0.0, 0.0]))
    local_direction = api.vec(placement.get("direction", [0.0, 0.0, 1.0]))
    local_x = placement.get("x_axis", [1.0, 0.0, 0.0])

    if "origin_context" in placement:
        origin_mode = placement["origin_context"]
    else:
        # "runtime_port" tracks the connected segment's own Attachment/Offset
        # (JunctionPort.position is computed via the same compute_port_position()
        # call as the segment's own rendered endpoint), unlike "center_point"
        # which is the raw, unadjusted topology node and never moves with it.
        origin_mode = "runtime_port" if "connected_ports" in context else "start_point"

    real_origin = _context_origin(context, api, runtime_ports, origin_mode, anchor_index)
    real_port = runtime_ports[anchor_index]
    real_direction = api.port_direction(real_port)
    real_x = api.port_profile_x_axis(real_port)

    local_frame, _lx, _ly, _lz = api.make_profile_frame(
        local_direction, preferred_x=local_x, origin=local_origin
    )
    real_frame, _rx, _ry, _rz = api.make_profile_frame(
        real_direction, preferred_x=real_x, origin=real_origin
    )
    return real_frame.multiply(local_frame.inverse())


def _descriptor_port_map(desc, runtime_ports):
    """Match each port the descriptor declares to its real runtime port, by descriptor port id."""
    mapping = {}
    for list_index, port_desc in enumerate(list(desc.get("ports", []) or [])):
        port_id = str(port_desc.get("id", "P{}".format(list_index + 1)))
        runtime_index = int(port_desc.get("runtime_port", list_index))
        if runtime_index < 0 or runtime_index >= len(runtime_ports):
            raise StaticDescriptorError(
                "Descriptor port '{}' runtime_port {} is out of range".format(port_id, runtime_index)
            )
        mapping[port_id] = (port_desc, runtime_ports[runtime_index])
    return mapping


def _port_mismatch(message, strict):
    """Report one validation failure: a hard error in strict mode, a console warning otherwise."""
    if strict:
        raise StaticGeometryError(message)
    FreeCAD.Console.PrintWarning("HVAC - {}\n".format(message))


def _validate_ports(desc, transform, api, runtime_ports):
    """
    Sanity-check that the descriptor's own claims about each port (its
    direction, profile, section size) still roughly match the real
    connected port, after applying the transform. Catches an author's
    placement/port mistakes early instead of silently building a
    misconnected shape.
    """
    validation = dict(desc.get("validation", {}) or {})
    strict = bool(validation.get("strict", True))
    angle_tol = float(validation.get("angle_tolerance_deg", 0.5))
    size_tol = float(validation.get("size_tolerance_mm", 0.5))

    for port_id, (port_desc, real_port) in _descriptor_port_map(desc, runtime_ports).items():
        if "direction" in port_desc:
            local_dir = api.unit(port_desc["direction"])
            predicted_dir = transform.Rotation.multVec(local_dir)
            err = math.degrees(api.angle_between(predicted_dir, api.port_direction(real_port)))
            if err > angle_tol:
                _port_mismatch(
                    "Static descriptor port '{}' direction mismatch: {:.3f} deg > {:.3f} deg".format(
                        port_id, err, angle_tol
                    ),
                    strict,
                )

        expected_profile = str(port_desc.get("profile", "") or "")
        actual_profile = api.port_profile(real_port)
        if expected_profile and actual_profile and expected_profile != actual_profile:
            _port_mismatch(
                "Static descriptor port '{}' profile '{}' does not match '{}'".format(
                    port_id, expected_profile, actual_profile
                ),
                strict,
            )

        expected_section = dict(port_desc.get("section_params", {}) or {})
        actual_section = api.port_section_params(real_port)
        for key, expected in expected_section.items():
            if key not in actual_section:
                _port_mismatch(
                    "Static descriptor port '{}' requires section parameter '{}'".format(port_id, key),
                    strict,
                )
                continue
            actual = actual_section[key]
            try:
                delta = abs(float(actual) - float(expected))
            except (TypeError, ValueError):
                if actual != expected:
                    _port_mismatch(
                        "Static descriptor port '{}' parameter '{}' mismatch".format(port_id, key),
                        strict,
                    )
                continue
            if delta > size_tol:
                _port_mismatch(
                    "Static descriptor port '{}' parameter '{}' mismatch: {} vs {}".format(
                        port_id, key, actual, expected
                    ),
                    strict,
                )


def _build_connection_lengths(desc, api, runtime_ports):
    """Turn the descriptor's outputs.connection_lengths into the (port, length) records DuctJunction expects."""
    outputs = dict(desc.get("outputs", {}) or {})
    records = outputs.get("connection_lengths", []) or []
    if isinstance(records, dict):
        records = [{"port": key, "length": value} for key, value in records.items()]

    port_map = _descriptor_port_map(desc, runtime_ports)
    port_lengths = []
    for record in records:
        port_id = str(record["port"])
        if port_id not in port_map:
            raise StaticDescriptorError(
                "connection_lengths references unknown descriptor port '{}'".format(port_id)
            )
        _port_desc, real_port = port_map[port_id]
        port_lengths.append((real_port, float(record["length"])))

    return api.build_trim_rec_from_port_lengths(port_lengths)


def _transform_plane(plane, transform, api):
    """Carry a trim plane (position + normal), authored in the shape's local frame, into world coordinates."""
    plane = dict(plane or {})
    position = api.vec(plane.get("position", [0.0, 0.0, 0.0]))
    normal = api.unit(plane.get("normal", [0.0, 0.0, 1.0]))
    world_position = transform.multVec(position)
    world_normal = transform.Rotation.multVec(normal)
    return {
        "position": [world_position.x, world_position.y, world_position.z],
        "normal": [world_normal.x, world_normal.y, world_normal.z],
    }


def build_static_geometry(descriptor_path, context):
    """Entry point for the static backend -- see the module docstring for the overall approach."""
    api = context["hvac_api"]
    desc = _load_descriptor(descriptor_path)
    runtime_ports = _runtime_ports(context, api)
    if not runtime_ports:
        raise StaticGeometryError("Static geometry requires at least one runtime port")

    # Load the shape as authored, work out and apply the one transform that
    # carries it into its real position, then check the result makes sense.
    shape = _read_shape(descriptor_path, desc["source"])
    transform = _build_transform(desc, context, api, runtime_ports)
    _validate_ports(desc, transform, api, runtime_ports)
    shape.transformShape(transform.toMatrix(), True, False)

    # Any extra outputs (connection lengths, trim planes, ...) the
    # descriptor declares get carried through in the same real-world frame.
    outputs = dict(desc.get("outputs", {}) or {})
    result = api.single_layer(context, shape)

    if "connection_lengths" in outputs:
        if "connected_ports" not in context:
            # connection_lengths is a junction-only mechanism: only
            # DuctComponent.execute() reads it back off the generator
            # result, and DuctJunction.aggregateConnectionLengths only ever
            # looks at component objects when building the segment trim
            # map. A segment-backed descriptor authoring this output would
            # otherwise resolve silently to [] and have no effect.
            raise StaticDescriptorError(
                "outputs.connection_lengths is only supported for junction-backed "
                "static descriptors (segment ports have no edge_key to trim against)"
            )
        result["connection_lengths"] = _build_connection_lengths(desc, api, runtime_ports)
    if "start_trim_plane" in outputs:
        result["start_trim_plane_json"] = json.dumps(
            _transform_plane(outputs["start_trim_plane"], transform, api)
        )
    if "end_trim_plane" in outputs:
        result["end_trim_plane_json"] = json.dumps(
            _transform_plane(outputs["end_trim_plane"], transform, api)
        )

    # Future generator-result metadata can be represented directly in JSON.
    reserved = {"connection_lengths", "start_trim_plane", "end_trim_plane"}
    for key, value in outputs.items():
        if key not in reserved:
            result[key] = value

    return result
