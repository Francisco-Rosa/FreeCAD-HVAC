# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the HVAC addon.

"""
The face of an air terminal (diffuser, grille, register), drawn as a
construction feature (see features.py) over the open end of the terminal's
body (terminals.py), so the end reads as the device it stands for.

A face is a border plate from the core (the open area) out over the body's
wall, plus a pattern in the core, picked with FacePattern:

- diffusers (square, round, generic body): "Louvered" (concentric rings
  stepping in), "Plaque" (a plate held in front of the core), "Perforated"
  (a plate with a grid of holes), "Swirl" (a plate with radial slots);
- slot diffusers: "Slots with deflectors", "Plain slots";
- grilles and registers: "Single deflection", "Double deflection",
  "Egg crate", "Perforated"; a register also has opposed damper blades
  behind its face.

Every size of the pattern is a property; a type need not declare them (the
built-in library declares FacePattern only), each one missing falls back to
a size worked out from the face. The face lies in the opening, from the node
plane into the terminal, so it never changes the terminal's length.

Built from plain extrusions in a compound; booleans only where a plate
needs holes or a ring its middle (one cut each).
"""

import math

from ._common import _layer_thickness
from .features import _params
from .terminals import _grown_section, _scaled_section, _section, _terminal_layout

# A pattern never draws more than this many blades or holes (the spacing grows instead).
_MAX_BLADES = 160
_MAX_HOLES = 1200


def _number(params, name, default):
    value = params.get(name)
    try:
        value = float(default if value in (None, "") else value)
    except (TypeError, ValueError):
        value = float(default)
    return value if value > 0.0 else float(default)


def _extents(profile, section):
    if profile == "Circular":
        return float(section["Diameter"]), float(section["Diameter"])
    return float(section["Width"]), float(section["Height"])


def _half_chord(profile, width, height, along_x, offset):
    """
    Half the length of a line across a section, parallel to its x axis
    (along_x) or y axis, `offset` from the centre: 0 when it misses it.
    """
    if profile == "Rectangular":
        reach, half = (height / 2.0, width / 2.0) if along_x else (width / 2.0, height / 2.0)
        return half if abs(offset) < reach else 0.0
    if profile == "Circular":
        radius = width / 2.0
        return math.sqrt(max(radius * radius - offset * offset, 0.0))
    # Oval: straight sides along its longer axis, half circles at its ends.
    long_is_x = width >= height
    radius = min(width, height) / 2.0
    straight = abs(width - height) / 2.0
    if along_x == long_is_x:
        return straight + math.sqrt(max(radius * radius - offset * offset, 0.0)) if abs(offset) < radius else 0.0
    if abs(offset) <= straight:
        return radius
    rest = abs(offset) - straight
    return math.sqrt(max(radius * radius - rest * rest, 0.0))


def _inside(profile, width, height, u, v, margin):
    """True when a circle of radius `margin` at (u, v) lies inside the section."""
    return _half_chord(profile, width - 2.0 * margin, height - 2.0 * margin, True, v) > abs(u)


def _shrunk(profile, section, by):
    """The section made smaller by `by` on every side (None when nothing is left)."""
    grown = _grown_section(profile, section, -by)[1]
    width, height = _extents(profile, grown)
    return grown if min(width, height) > 1.0 else None


class _Face:
    """The face plane of one terminal and the pieces drawn on it, in (u, v) along its x / y axes and depth inwards."""

    def __init__(self, api, ctx, kind):
        context = ctx.context
        self.api = api
        self.params = _params(ctx)
        layout = _terminal_layout(context, kind)
        port = layout["port"]
        self.origin = api.port_position(port)
        self.axis = api.unit(api.port_direction(port))  # from the node into the terminal
        _placement, self.x, self.y, _z = api.make_profile_frame(self.axis, api.port_profile_x_axis(port))
        self.face_profile, self.face = layout["face"] or _section(api, port)
        self.duct_profile, self.duct = _section(api, port)
        self.wall = sum(_layer_thickness(ld, self.params) for ld in context.get("construction_layers") or [])
        width, height = _extents(self.face_profile, self.face)
        self.size = max(width, height)
        self.thickness = _number(self.params, "FaceThickness", max(1.5, 0.004 * self.size))
        self.shapes = []

    def point(self, u, v, depth):
        return self.origin + self.x * u + self.y * v + self.axis * depth

    def slab(self, profile, section, depth, thickness, u=0.0, v=0.0):
        wire = self.api.make_profile(
            profile, section, center=self.point(u, v, depth), direction=self.axis, profile_x_axis=self.x
        )
        return self.api.extrude(wire, self.axis * thickness, solid=True)

    def ring(self, profile, outer, inner, depth, thickness):
        """A plate between two sections of one profile."""
        plate = self.slab(profile, outer, depth, thickness)
        if inner is None:
            return plate
        return self.api.cut(plate, self.slab(profile, inner, depth - 1.0, thickness + 2.0))

    def blade(self, u, v, along_x, length, chord, thickness, angle_deg, depth):
        """A flat blade centred at (u, v, depth), its length along x or y, its chord turned from the axis by angle."""
        long_axis = self.x if along_x else self.y
        chord_dir = self.api.rotate_vector(self.axis, long_axis, math.radians(angle_deg))
        wire = self.api.make_profile(
            "Rectangular",
            {"Width": chord, "Height": thickness},
            center=self.point(u, v, depth) - long_axis * (length / 2.0),
            direction=long_axis,
            profile_x_axis=chord_dir,
        )
        return self.api.extrude(wire, long_axis * length, solid=True)

    def border(self, core):
        """The face plate from the core out over the body's wall."""
        outer = _grown_section(self.face_profile, self.face, self.wall)[1]
        self.shapes.append(self.ring(self.face_profile, outer, core, 0.0, self.thickness))

    def result(self):
        return self.api.compound(self.shapes) if self.shapes else None


# ----------------------------------------------------------------------
# Patterns
# ----------------------------------------------------------------------


def _louvered(face, profile, core):
    """Concentric rings, each a step deeper, with a cap in the middle."""
    count = max(1, int(_number(face.params, "RingCount", 3)))
    width, height = _extents(profile, core)
    step = _number(face.params, "RingStep", 0.03 * max(width, height))
    for index in range(count):
        outer = _scaled_section(profile, core, 1.0 - index / (count + 1.0), 1.0 - index / (count + 1.0))[1]
        scale = 1.0 - (index + 0.6) / (count + 1.0)
        inner = _scaled_section(profile, core, scale, scale)[1]
        face.shapes.append(face.ring(profile, outer, inner, step * (index + 1), face.thickness))
    cap = _scaled_section(profile, core, 1.0 / (count + 1.0), 1.0 / (count + 1.0))[1]
    face.shapes.append(face.slab(profile, cap, step * (count + 1), face.thickness))


def _plaque(face, profile, core):
    """A plate held in front of the core, leaving a gap all round."""
    fraction = min(max(_number(face.params, "PlaqueSize", 0.75), 0.1), 0.98)
    width, height = _extents(profile, core)
    gap = _number(face.params, "PlaqueGap", 0.06 * max(width, height))
    plaque = _scaled_section(profile, core, fraction, fraction)[1]
    face.shapes.append(face.slab(profile, plaque, -gap, face.thickness))


def _perforated(face, profile, core):
    """A plate over the core with a square grid of round holes."""
    width, height = _extents(profile, core)
    diameter = _number(face.params, "HoleDiameter", max(4.0, 0.02 * max(width, height)))
    pitch = max(_number(face.params, "HolePitch", 2.0 * diameter), 1.2 * diameter)
    count = (width / pitch) * (height / pitch)
    if count > _MAX_HOLES:
        pitch *= math.sqrt(count / _MAX_HOLES)
    holes = []
    columns, rows = int(width / pitch), int(height / pitch)
    for i in range(-columns, columns + 1):
        for j in range(-rows, rows + 1):
            u, v = i * pitch, j * pitch
            if abs(u) > width / 2.0 or abs(v) > height / 2.0:
                continue
            if not _inside(profile, width, height, u, v, diameter):
                continue
            holes.append(face.slab("Circular", {"Diameter": diameter}, -1.0, face.thickness + 2.0, u, v))
    plate = face.slab(profile, core, 0.0, face.thickness)
    face.shapes.append(face.api.cut(plate, face.api.compound(holes)) if holes else plate)


def _swirl(face, profile, core):
    """A plate over the core with slots set round the centre, each turned off the radius."""
    width, height = _extents(profile, core)
    reach = min(width, height) / 2.0
    count = max(4, int(_number(face.params, "SlotCount", 24)))
    slot_width = _number(face.params, "SlotWidth", max(4.0, 0.03 * reach))
    length = 0.45 * reach
    middle = 0.55 * reach
    slots = []
    for index in range(count):
        angle = 2.0 * math.pi * index / count
        radial = face.x * math.cos(angle) + face.y * math.sin(angle)
        direction = face.api.rotate_vector(radial, face.axis, math.radians(25.0))
        centre = face.origin + radial * middle
        wire = face.api.make_profile(
            "Rectangular",
            {"Width": slot_width, "Height": face.thickness + 2.0},
            center=centre - direction * (length / 2.0) + face.axis * (face.thickness / 2.0),
            direction=direction,
            profile_x_axis=face.axis.cross(direction),
        )
        slots.append(face.api.extrude(wire, direction * length, solid=True))
    plate = face.slab(profile, core, 0.0, face.thickness)
    face.shapes.append(face.api.cut(plate, face.api.compound(slots)))


def _blade_row(face, profile, core, along_x, spacing, chord, thickness, angle, depth, alternate=False):
    """Blades across the core, `spacing` apart, each cut to the core's outline (by arithmetic, not booleans)."""
    width, height = _extents(profile, core)
    across = height if along_x else width
    if across / spacing > _MAX_BLADES:
        spacing = across / _MAX_BLADES
    count = max(1, int(across / spacing))
    first = -(count - 1) * spacing / 2.0
    for index in range(count):
        offset = first + index * spacing
        half = _half_chord(profile, width, height, along_x, offset)
        if half <= 1.0:
            continue
        u, v = (0.0, offset) if along_x else (offset, 0.0)
        sign = -1.0 if alternate and index % 2 else 1.0
        face.shapes.append(face.blade(u, v, along_x, 2.0 * half, chord, thickness, sign * angle, depth))


def _grille(face, profile, core, pattern):
    params = face.params
    along_x = str(params.get("BladeOrientation") or "Horizontal") != "Vertical"
    width, height = _extents(profile, core)
    spacing = _number(params, "BladeSpacing", max(12.0, 0.06 * min(width, height)))
    depth = _number(params, "BladeDepth", max(15.0, 1.2 * spacing))
    thickness = _number(params, "BladeThickness", max(1.0, 0.08 * spacing))
    angle = min(max(float(params.get("BladeAngle", 0.0) or 0.0), -60.0), 60.0)
    if pattern == "Perforated":
        _perforated(face, profile, core)
        return depth
    if pattern == "Egg crate":
        _blade_row(face, profile, core, True, spacing, depth, thickness, 0.0, depth / 2.0)
        _blade_row(face, profile, core, False, spacing, depth, thickness, 0.0, depth / 2.0)
        return depth
    _blade_row(face, profile, core, along_x, spacing, depth, thickness, angle, depth / 2.0)
    if pattern == "Double deflection":
        # A second row behind the first, square to it.
        _blade_row(face, profile, core, not along_x, spacing, depth, thickness, -angle, 1.5 * depth + 3.0)
        return 2.0 * depth + 3.0
    return depth


# ----------------------------------------------------------------------
# Feature generators (one per terminal layout kind)
# ----------------------------------------------------------------------


def _diffuser(api, ctx, kind):
    face = _Face(api, ctx, kind)
    pattern = str(face.params.get("FacePattern") or "Louvered")
    border = _number(face.params, "FaceBorder", max(10.0, 0.06 * face.size))
    core = _shrunk(face.face_profile, face.face, border)
    face.border(core)
    if core is not None:
        builder = {"Plaque": _plaque, "Perforated": _perforated, "Swirl": _swirl}.get(pattern, _louvered)
        builder(face, face.face_profile, core)
    return face.result()


def square_diffuser_face(api, ctx):
    """Face of a square diffuser (FacePattern: Louvered, Plaque, Perforated, Swirl)."""
    return _diffuser(api, ctx, "square")


def round_diffuser_face(api, ctx):
    """Face of a round diffuser (FacePattern: Louvered, Plaque, Perforated, Swirl)."""
    return _diffuser(api, ctx, "round")


def generic_diffuser_face(api, ctx):
    """Face of a diffuser body in the duct's own section (FacePattern: Louvered, Plaque, Perforated, Swirl)."""
    return _diffuser(api, ctx, "generic")


def slot_diffuser_face(api, ctx):
    """
    Face of a slot diffuser: SlotCount slots along the face's length,
    divided by bars; "Slots with deflectors" adds a blade turned by
    BladeAngle in each slot.
    """
    face = _Face(api, ctx, "slot")
    params = face.params
    length, width = _extents(face.face_profile, face.face)
    border = _number(params, "FaceBorder", max(8.0, 0.1 * width))
    core_length, core_width = length - 2.0 * border, width - 2.0 * border
    face.border(None if min(core_length, core_width) <= 1.0 else {"Width": core_length, "Height": core_width})
    if min(core_length, core_width) <= 1.0:
        return face.result()
    count = max(1, int(_number(params, "SlotCount", 2)))
    divider = _number(params, "DividerWidth", max(4.0, 0.08 * core_width))
    slot = (core_width - (count - 1) * divider) / count
    if slot <= 1.0:
        raise ValueError("{} slots do not fit across a {:.0f} mm slot face".format(count, width))
    depth = _number(params, "BladeDepth", 0.8 * slot)
    for index in range(count):
        v = -core_width / 2.0 + slot / 2.0 + index * (slot + divider)
        if index:
            bar = {"Width": core_length, "Height": divider}
            face.shapes.append(face.slab("Rectangular", bar, 0.0, depth, 0.0, v - slot / 2.0 - divider / 2.0))
        if str(params.get("FacePattern") or "Slots with deflectors") == "Slots with deflectors":
            angle = min(max(float(params.get("BladeAngle", 30.0) or 0.0), -60.0), 60.0)
            chord = min(depth, 0.9 * slot / max(math.sin(math.radians(abs(angle))), 0.3))
            face.shapes.append(face.blade(0.0, v, True, core_length, chord, 1.5, angle, depth / 2.0))
    return face.result()


def grille_face(api, ctx):
    """Face of a grille (FacePattern: Single deflection, Double deflection, Egg crate, Perforated)."""
    face = _Face(api, ctx, "frame")
    pattern = str(face.params.get("FacePattern") or "Single deflection")
    face.border(face.duct)
    _grille(face, face.duct_profile, face.duct, pattern)
    return face.result()


def register_face(api, ctx):
    """
    Face of a register: a grille face (as grille_face) with a row of
    opposed damper blades behind it, turned by DamperBladeAngle from open.
    """
    face = _Face(api, ctx, "frame")
    params = face.params
    pattern = str(params.get("FacePattern") or "Double deflection")
    face.border(face.duct)
    behind = _grille(face, face.duct_profile, face.duct, pattern)
    width, height = _extents(face.duct_profile, face.duct)
    along_x = str(params.get("BladeOrientation") or "Horizontal") != "Vertical"
    spacing = 2.5 * _number(params, "BladeSpacing", max(12.0, 0.06 * min(width, height)))
    angle = min(max(float(params.get("DamperBladeAngle", 30.0) or 0.0), 0.0), 90.0)
    _blade_row(
        face, face.duct_profile, face.duct, along_x, spacing, 1.05 * spacing, 1.0, angle,
        behind + 5.0 + spacing / 2.0, alternate=True,
    )  # fmt: skip
    return face.result()
