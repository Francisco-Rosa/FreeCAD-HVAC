HVAC_PARTSCRIPT_API = 3


def generate(context):
    api = context["hvac_api"]
    p = dict(context.get("properties") or {})
    ports = list(api.connected_ports(context))
    if len(ports) != 2:
        raise ValueError(f"Expected 2 connected ports, got {len(ports)}")
    if any(api.port_profile(port) != "Rectangular" for port in ports):
        raise ValueError("through_elbow_rectangular requires rectangular ports")

    size = max(api.port_width(ports[0]), api.port_height(ports[0]), api.port_width(ports[1]), api.port_height(ports[1]))
    radius = float(p.get("CenterlineRadius", 0.0) or 0.0)
    if radius <= 1.0e-7:
        radius = 0.6 * size
    # Below half the size plus the wall the inside of the bend (or of a wall
    # layer around it) folds over; keep a small clearance on top.
    wall = sum(
        float(p.get(getattr(layer, "thickness_property", None) or "", 0.0) or 0.0)
        for layer in context.get("construction_layers") or []
    )
    radius = max(radius, 0.5 * size + wall + max(1.0, 0.01 * size))
    route = api.make_elbow_path(ports[0], ports[1], radius)
    # The transverse_flange feature (shared:features) mounts here,
    # not on the raw connected ports -- those sit further back, before the
    # bend's own tangent trim.
    context["flange_ports"] = route["ports"]

    def build_envelope(offset):
        profiles = [api.profile_from_port(route["ports"][0], offset), api.profile_from_port(route["ports"][1], offset)]
        return api.sweep(profiles, route["path"], solid=True)

    result = api.build_layered_geometry(build_envelope, context["construction_layers"], p)
    result["connection_lengths"] = api.build_trim_rec_from_port_lengths(
        [(ports[0], route["trim_lengths"][0]), (ports[1], route["trim_lengths"][1])]
    )
    return result
