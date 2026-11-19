HVAC_PARTSCRIPT_API = 3


def generate(context):
    api = context["hvac_api"]
    p = dict(context.get("properties") or {})
    start = api.vec(context["start_point"])
    end = api.vec(context["end_point"])
    axis = end - start
    if axis.Length <= 1.0e-7:
        raise ValueError("Acoustic straight duct length must be positive")

    # Diameter is explicitly the clear-air diameter.
    air = api.make_profile(
        "Circular",
        {"Diameter": p["Diameter"]},
        center=start,
        direction=axis,
        profile_x_axis=context.get("profile_x_axis"),
    )
    liner_t = max(float(p.get("LinerThickness", 0.0) or 0.0), 0.0)
    absorber_t = max(float(p.get("AbsorberThickness", 0.0) or 0.0), 0.0)
    jacket_t = max(float(p.get("JacketThickness", p.get("Thickness", 0.0)) or 0.0), 0.0)

    boundaries = [api.extrude(air, axis, solid=True)]
    offsets = [liner_t, liner_t + absorber_t, liner_t + absorber_t + jacket_t]
    for offset in offsets:
        boundaries.append(api.extrude(api.offset_profile(air, offset), axis, solid=True))

    layers = {}
    names = ["liner", "absorber", "jacket"]
    for i, name in enumerate(names, start=1):
        if offsets[i - 1] - (offsets[i - 2] if i > 1 else 0.0) <= 1.0e-7:
            continue
        layers[name] = {"shape": api.refine(api.cut(boundaries[i], boundaries[i - 1]))}
    return {"layers": layers}
