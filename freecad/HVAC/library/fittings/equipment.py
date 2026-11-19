# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the HVAC addon.

"""
Equipment models (see library/equipment_library.py): a casing with one
collar per connection. Each `build_*(api, values)` returns the unit as one
solid, in its own frame (length along X, width along Y, height along Z,
centred on the origin, standing on Z = -height / 2), and its ports: the
centre of each collar's end face, pointing out of the unit.

Collars are solid stubs, so a collar's end face is exactly the clear
opening the duct connects to (the port's profile and size are read from it).
"""

X_AXIS = (1.0, 0.0, 0.0)
Y_AXIS = (0.0, 1.0, 0.0)
Z_AXIS = (0.0, 0.0, 1.0)


def _casing(api, length, width, height):
    """The casing box, centred on the origin, length along X."""
    start = api.vec((-length / 2.0, 0.0, 0.0))
    wire = api.make_profile(
        "Rectangular", {"Width": width, "Height": height}, center=start, direction=X_AXIS, profile_x_axis=Y_AXIS
    )
    return api.extrude(wire, api.vec((length, 0.0, 0.0)), solid=True)


def _collar(api, shape, round_ports, base, direction, x_axis, width, height, collar):
    """
    Fuse one collar onto `shape`: from 1 mm inside the casing face at `base`
    out along `direction` by `collar`. Returns (shape, port position).
    """
    direction = api.unit(direction)
    base = api.vec(base)
    if round_ports:
        profile, section = "Circular", {"Diameter": width}
    else:
        profile, section = "Rectangular", {"Width": width, "Height": height}
    start = base - direction * 1.0
    wire = api.make_profile(profile, section, center=start, direction=direction, profile_x_axis=x_axis)
    stub = api.extrude(wire, direction * (collar + 1.0), solid=True)
    return api.fuse(shape, stub), api.xyz(base + direction * collar)


def _check_fits(label, size_a, size_b, face_a, face_b):
    if size_a > face_a + 1.0e-6 or size_b > face_b + 1.0e-6:
        raise ValueError(
            "The {} ({:.0f} x {:.0f}) does not fit on its casing face ({:.0f} x {:.0f})".format(
                label, size_a, size_b, face_a, face_b
            )
        )


def build_ahu(api, values):
    """
    Air handling unit: supply outlet on the +X end, return inlet on the -X
    end, and optionally an outdoor air inlet and an exhaust outlet on top,
    at a quarter of the length from the return end and from the middle.
    """
    length, width, height = values["CasingLength"], values["CasingWidth"], values["CasingHeight"]
    collar = values["CollarLength"]
    round_ports = values["PortShape"] == "Round"
    shape = _casing(api, length, width, height)
    ports = []

    def add(name, function, base, direction, x_axis, port_width, port_height, face):
        nonlocal shape
        size_b = port_width if round_ports else port_height
        _check_fits(name.lower(), port_width, size_b, face[0], face[1])
        shape, position = _collar(api, shape, round_ports, base, direction, x_axis, port_width, port_height, collar)
        ports.append({"name": name, "function": function, "position": position, "direction": api.xyz(direction)})

    end_face = (width, height)
    add("Supply", "SupplyOutlet", (length / 2.0, 0.0, 0.0), X_AXIS, Y_AXIS, values["SupplyWidth"],
        values["SupplyHeight"], end_face)  # fmt: skip
    add("Return", "ReturnInlet", (-length / 2.0, 0.0, 0.0), (-1.0, 0.0, 0.0), Y_AXIS, values["ReturnWidth"],
        values["ReturnHeight"], end_face)  # fmt: skip
    # On top the port's width runs across the unit (Y) and its height along it (X).
    top_face = (width, length / 2.0)
    if values["OutdoorAirPort"]:
        add("Outdoor air", "OutdoorAirInlet", (-length / 4.0, 0.0, height / 2.0), Z_AXIS, Y_AXIS,
            values["OutdoorAirWidth"], values["OutdoorAirHeight"], top_face)  # fmt: skip
    if values["ExhaustPort"]:
        add("Exhaust", "ExhaustOutlet", (length / 4.0, 0.0, height / 2.0), Z_AXIS, Y_AXIS, values["ExhaustWidth"],
            values["ExhaustHeight"], top_face)  # fmt: skip
    return {"shape": shape, "ports": ports, "internal_pressure_drop": values["InternalPressureDrop"]}


def build_fan(api, values):
    """
    Fan in a casing, inlet on the -X end and outlet on the +X end. Service
    "Supply": outdoor air inlet to supply outlet. "Exhaust": return inlet to
    exhaust outlet.
    """
    length, width, height = values["CasingLength"], values["CasingWidth"], values["CasingHeight"]
    collar = values["CollarLength"]
    round_ports = values["PortShape"] == "Round"
    port_width, port_height = values["PortWidth"], values["PortHeight"]
    _check_fits("connection", port_width, port_width if round_ports else port_height, width, height)
    supply = values["Service"] == "Supply"
    shape = _casing(api, length, width, height)
    ports = []
    for name, function, sign in (
        ("Inlet", "OutdoorAirInlet" if supply else "ReturnInlet", -1.0),
        ("Outlet", "SupplyOutlet" if supply else "ExhaustOutlet", 1.0),
    ):
        direction = (sign, 0.0, 0.0)
        shape, position = _collar(
            api, shape, round_ports, (sign * length / 2.0, 0.0, 0.0), direction, Y_AXIS, port_width, port_height, collar
        )
        ports.append({"name": name, "function": function, "position": position, "direction": direction})
    return {"shape": shape, "ports": ports, "internal_pressure_drop": 0.0}
