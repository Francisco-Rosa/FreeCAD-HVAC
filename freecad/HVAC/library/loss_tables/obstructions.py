# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the HVAC addon.

"""
SMACNA Table 14-17 (screens and plates) and Table 14-18 (obstructions:
dampers, a cylinder across the duct, ducts depressed around an obstacle).

Every coefficient multiplies the velocity pressure of the upstream section
(these fittings keep the duct size, so upstream and downstream are equal).
"""

import math

from .table import REF_UPSTREAM, Lookup, LossTable, combine

_ROUND = ("Circular",)
_RECT = ("Rectangular",)
_BOTH = ("Circular", "Rectangular")

# ----------------------------------------------------------------------------
# 14-17 A. Screen in duct. n = free area ratio of the screen.
# ----------------------------------------------------------------------------

SCREEN = LossTable(
    "14-17A",
    "Screen in duct",
    [("free_area_ratio", [0.30, 0.40, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.90, 1.0])],
    [6.2, 3.0, 1.7, 1.3, 0.97, 0.75, 0.58, 0.44, 0.32, 0.14, 0],
    REF_UPSTREAM,
    _BOTH,
)

# ----------------------------------------------------------------------------
# 14-17 B. Perforated plate in duct, thick (t/d > 0.015).
# t = plate thickness, d = hole diameter, n = free area ratio.
# ----------------------------------------------------------------------------

PERFORATED_PLATE = LossTable(
    "14-17B",
    "Perforated plate in duct, thick",
    [("t_on_d", [0.015, 0.2, 0.4, 0.6]), ("free_area_ratio", [0.20, 0.25, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90])],
    [
        [52, 30, 18, 8.2, 4.0, 2.0, 0.97, 0.42, 0.13],
        [48, 28, 17, 7.7, 3.8, 1.9, 0.91, 0.40, 0.13],
        [46, 27, 17, 7.4, 3.6, 1.8, 0.88, 0.39, 0.13],
        [42, 24, 15, 6.6, 3.2, 1.6, 0.80, 0.36, 0.13],
    ],
    REF_UPSTREAM,
    _BOTH,
)

# ----------------------------------------------------------------------------
# 14-18 A, B, G. Single-blade butterfly dampers. theta = blade angle, 0 deg
# is fully open.
# ----------------------------------------------------------------------------

_BUTTERFLY_THETA = [0, 10, 20, 30, 40, 50, 60]


def _butterfly(letter, title, values, profiles):
    return LossTable("14-18{}".format(letter), title, [("theta_deg", _BUTTERFLY_THETA)], values, REF_UPSTREAM, profiles)


BUTTERFLY_DAMPERS = {
    "thin_plate_round": _butterfly(
        "A", "Damper, butterfly, thin plate, round", [0.20, 0.52, 1.5, 4.5, 11, 29, 108], _ROUND
    ),
    "thin_plate_rect": _butterfly(
        "B", "Damper, butterfly, thin plate, rectangular", [0.04, 0.33, 1.2, 3.3, 9.0, 26, 70], _RECT
    ),
    "airfoil_rect": _butterfly(
        "G", "Damper, butterfly, airfoil blade, rectangular", [0.50, 0.65, 1.6, 4.0, 9.4, 24, 67], _RECT
    ),
}

# ----------------------------------------------------------------------------
# 14-18 C, D. Gate dampers. h = height of the opening left by the gate.
# ----------------------------------------------------------------------------

GATE_DAMPER_ROUND = LossTable(
    "14-18C",
    "Damper, gate, round",
    [("h_on_d", [0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9])],
    [35, 10, 4.6, 2.1, 0.98, 0.44, 0.17, 0.06],
    REF_UPSTREAM,
    _ROUND,
)

GATE_DAMPER_RECT = LossTable(
    "14-18D",
    "Damper, gate, rectangular",
    [("h_on_w", [0.5, 1.0, 1.5, 2.0]), ("opening_on_h", [0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9])],
    [
        [14, 6.9, 3.3, 1.7, 0.83, 0.32, 0.09],
        [19, 8.8, 4.5, 2.4, 1.2, 0.55, 0.17],
        [20, 9.1, 4.7, 2.7, 1.2, 0.47, 0.11],
        [18, 8.8, 4.5, 2.3, 1.1, 0.51, 0.13],
    ],
    REF_UPSTREAM,
    _RECT,
)

# ----------------------------------------------------------------------------
# 14-18 E, F. Multi-blade rectangular dampers. theta = blade angle (0 deg is
# fully open). L/R = N W / (2 (H + W)): N blades of length W (the duct
# dimension along the blade axis) over the duct perimeter.
# ----------------------------------------------------------------------------

_BLADE_L_ON_R = [0.3, 0.4, 0.5, 0.6, 0.8, 1.0, 1.5]
_BLADE_THETA = [80, 70, 60, 50, 40, 30, 20, 10, 0]

PARALLEL_BLADE_DAMPER = LossTable(
    "14-18E",
    "Damper, rectangular, parallel blades",
    [("l_on_r", _BLADE_L_ON_R), ("theta_deg", _BLADE_THETA)],
    [
        [116, 32, 14, 9.0, 5.0, 2.3, 1.4, 0.79, 0.52],
        [152, 38, 16, 9.0, 6.0, 2.4, 1.5, 0.85, 0.52],
        [188, 45, 18, 9.0, 6.0, 2.4, 1.5, 0.92, 0.52],
        [245, 45, 21, 9.0, 5.4, 2.4, 1.5, 0.92, 0.52],
        [284, 55, 22, 9.0, 5.4, 2.5, 1.5, 0.92, 0.52],
        [361, 65, 24, 10, 5.4, 2.6, 1.6, 1.0, 0.52],
        [576, 102, 28, 10, 5.4, 2.7, 1.6, 1.0, 0.52],
    ],
    REF_UPSTREAM,
    _RECT,
)

OPPOSED_BLADE_DAMPER = LossTable(
    "14-18F",
    "Damper, rectangular, opposed blades",
    [("l_on_r", _BLADE_L_ON_R), ("theta_deg", _BLADE_THETA)],
    [
        [807, 284, 73, 21, 9.0, 4.1, 2.1, 0.85, 0.52],
        [915, 332, 100, 28, 11, 5.0, 2.2, 0.92, 0.52],
        [1045, 377, 122, 33, 13, 5.4, 2.3, 1.0, 0.52],
        [1121, 411, 148, 38, 14, 6.0, 2.3, 1.0, 0.52],
        [1299, 495, 188, 54, 18, 6.6, 2.4, 1.1, 0.52],
        [1521, 547, 245, 65, 21, 7.3, 2.7, 1.2, 0.52],
        [1654, 677, 361, 107, 28, 9.0, 3.2, 1.4, 0.52],
    ],
    REF_UPSTREAM,
    _RECT,
)

# ----------------------------------------------------------------------------
# 14-18 H. Obstruction, smooth cylinder across the duct: C = K * Co.
# Sm = d L (cylinder diameter times its length inside the duct), A = duct
# area; valid for Sm/A < 0.3. Re is based on the cylinder diameter d.
# The Reynolds number spans seven decades, so the table is stored and
# interpolated against log10(Re). Rows printed for a range of Re are written
# as the two ends of the range.
# ----------------------------------------------------------------------------

_CYLINDER_RE = [0.1, 0.5, 1, 5, 10, 50, 100, 0.5e3, 200e3, 3e5, 4e5, 5e5, 6e5, 10e5]
_CYLINDER_ROWS = [
    [3.9, 8.4, 14, 19],
    [1.5, 3.2, 5.2, 7.1],
    [0.66, 1.4, 2.3, 3.2],
    [0.30, 0.64, 1.1, 1.4],
    [0.17, 0.38, 0.62, 0.84],
    [0.11, 0.24, 0.38, 0.52],
    [0.10, 0.24, 0.35, 0.47],
    [0.07, 0.15, 0.24, 0.33],
    [0.07, 0.15, 0.24, 0.33],
    [0.07, 0.16, 0.26, 0.35],
    [0.05, 0.11, 0.19, 0.25],
    [0.04, 0.09, 0.14, 0.19],
    [0.02, 0.05, 0.07, 0.10],
    [0.02, 0.05, 0.07, 0.10],
]

CYLINDER_CO = LossTable(
    "14-18H Co",
    "Obstruction, smooth cylinder: base coefficient Co",
    [("log10_reynolds", [math.log10(re) for re in _CYLINDER_RE]), ("sm_on_a", [0.05, 0.10, 0.15, 0.20])],
    _CYLINDER_ROWS,
    REF_UPSTREAM,
    _BOTH,
)

# y = distance of the cylinder axis from the duct centreline (over D, or H for rectangular).
CYLINDER_OFFSET_K = LossTable(
    "14-18H K",
    "Obstruction, smooth cylinder: offset factor K",
    [("y_on_d", [0, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40])],
    [1.0, 0.97, 0.93, 0.89, 0.84, 0.79, 0.74, 0.67, 0.58],
    REF_UPSTREAM,
    _BOTH,
)

# ----------------------------------------------------------------------------
# 14-18 I to L. Ducts depressed (offset) to pass an obstruction.
# ----------------------------------------------------------------------------

# I. Round duct, depressed with two 30 deg turns: one printed point.
DEPRESSED_ROUND_L_ON_D = 0.33
DEPRESSED_ROUND_C = 0.24

# J. Rectangular duct, depressed with two 15 deg turns. L = depth of the depression.
DEPRESSED_RECT = LossTable(
    "14-18J",
    "Rectangular duct, depressed to avoid an obstruction",
    [("w_on_h", [1.0, 4.0]), ("l_on_h", [0.125, 0.15, 0.25, 0.30])],
    [[0.26, 0.30, 0.33, 0.35], [0.10, 0.14, 0.22, 0.30]],
    REF_UPSTREAM,
    _RECT,
)

# K. Rectangular duct with four 45 deg smooth-radius ells. Printed for
# W/H = 4, R/H = 1, L/H = 1.5 only; keyed by velocity (m/s).
FOUR_RADIUS_ELLS_RECT = LossTable(
    "14-18K",
    "Rectangular duct with four 45 deg smooth radius ells to avoid an obstruction",
    [("velocity_ms", [4, 6, 8, 10, 12])],
    [0.18, 0.22, 0.24, 0.25, 0.26],
    REF_UPSTREAM,
    _RECT,
)

# L. Rectangular duct with four 90 deg mitered ells (W/H 1.0 to 3.0).
# One row per vane arrangement, keyed by L/H.
_FOUR_MITERED_L_ON_H = [0.5, 1.0, 1.5, 2.0]


def _four_mitered(suffix, title, values):
    return LossTable(
        "14-18L {}".format(suffix),
        "Rectangular duct with four 90 deg mitered ells: " + title,
        [("l_on_h", _FOUR_MITERED_L_ON_H)],
        values,
        REF_UPSTREAM,
        _RECT,
    )


FOUR_MITERED_ELLS_RECT = {
    "single_blade_vanes": _four_mitered("single vanes", "single blade turning vanes", [None, 0.86, 0.83, 0.77]),
    "double_blade_vanes": _four_mitered("double vanes", "double blade turning vanes", [None, 1.85, 2.84, 2.91]),
    "s_splitter_vanes": _four_mitered("S vanes", "S type splitter vanes", [0.61, 0.65, None, None]),
    "no_vanes_slow": _four_mitered("no vanes slow", "no vanes, up to 6 m/s", [0.88, 5.26, 6.92, 7.56]),
    "no_vanes_fast": _four_mitered("no vanes fast", "no vanes, over 6 m/s", [1.26, 6.22, 8.82, 9.24]),
}
FOUR_MITERED_ELLS_VELOCITY_SPLIT_MS = 6.0


# ----------------------------------------------------------------------------
# Lookups
# ----------------------------------------------------------------------------


def screen(free_area_ratio):
    """14-17 A."""
    return SCREEN.lookup(free_area_ratio)


def perforated_plate(free_area_ratio, t_on_d):
    """14-17 B."""
    return PERFORATED_PLATE.lookup(t_on_d, free_area_ratio)


def butterfly_damper(kind, theta_deg):
    """14-18 A, B, G. `kind` is one of the BUTTERFLY_DAMPERS keys; theta 0 is fully open."""
    try:
        table = BUTTERFLY_DAMPERS[kind]
    except KeyError:
        raise ValueError(
            "Unknown butterfly damper '{}'. Known: {}".format(kind, ", ".join(sorted(BUTTERFLY_DAMPERS)))
        ) from None
    return table.lookup(theta_deg)


def gate_damper_round(h_on_d):
    """14-18 C. h/D = 1 (gate fully withdrawn) is not printed; it reads the 0.9 column, flagged."""
    return GATE_DAMPER_ROUND.lookup(h_on_d)


def gate_damper_rect(h_on_w, opening_on_h):
    """14-18 D."""
    return GATE_DAMPER_RECT.lookup(h_on_w, opening_on_h)


def blade_l_on_r(blades, blade_length, width, height):
    """L/R of a multi-blade damper: total blade length over the duct perimeter (14-18 E, F)."""
    return float(blades) * float(blade_length) / (2.0 * (float(height) + float(width)))


def multi_blade_damper(opposed, l_on_r, theta_deg):
    """14-18 E (parallel blades) / F (opposed blades); theta 0 is fully open."""
    table = OPPOSED_BLADE_DAMPER if opposed else PARALLEL_BLADE_DAMPER
    return table.lookup(l_on_r, theta_deg)


def cylinder(reynolds, sm_on_a, y_on_d=0.0):
    """
    14-18 H: C = K * Co for a smooth cylinder across the duct. `reynolds`
    is based on the cylinder diameter. The source limits this to
    Sm/A < 0.3; beyond the last printed column the result is flagged.
    """
    reynolds = float(reynolds)
    if reynolds <= 0.0:
        raise ValueError("reynolds must be positive")
    co = CYLINDER_CO.lookup(math.log10(reynolds), sm_on_a)
    k = CYLINDER_OFFSET_K.lookup(abs(float(y_on_d)))
    return combine(co.value * k.value, co, k)


def depressed_round(l_on_d):
    """14-18 I: a single printed point (L/D = 0.33); any other depth is flagged."""
    return Lookup(DEPRESSED_ROUND_C, clamped=abs(float(l_on_d) - DEPRESSED_ROUND_L_ON_D) > 0.01)


def depressed_rect(w_on_h, l_on_h):
    """14-18 J."""
    return DEPRESSED_RECT.lookup(w_on_h, l_on_h)


def four_radius_ells_rect(velocity_ms):
    """14-18 K (printed for W/H = 4, R/H = 1, L/H = 1.5 only)."""
    return FOUR_RADIUS_ELLS_RECT.lookup(velocity_ms)


def four_mitered_ells_rect(vanes, l_on_h, velocity_ms=None):
    """
    14-18 L. `vanes` is "single_blade_vanes", "double_blade_vanes",
    "s_splitter_vanes" or "no_vanes" (which needs the velocity to pick its row).
    """
    key = vanes
    if vanes == "no_vanes":
        if velocity_ms is None:
            raise ValueError("no_vanes needs velocity_ms to choose between the two printed rows")
        key = "no_vanes_slow" if float(velocity_ms) <= FOUR_MITERED_ELLS_VELOCITY_SPLIT_MS else "no_vanes_fast"
    try:
        table = FOUR_MITERED_ELLS_RECT[key]
    except KeyError:
        known = ["single_blade_vanes", "double_blade_vanes", "s_splitter_vanes", "no_vanes"]
        raise ValueError("Unknown vane arrangement '{}'. Known: {}".format(vanes, ", ".join(known))) from None
    return table.lookup(l_on_h)
