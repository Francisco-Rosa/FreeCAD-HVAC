# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the HVAC addon.

"""
SMACNA Table 14-15 (entries) and Table 14-16 (exits).

Entry coefficients multiply the velocity pressure of the DOWNSTREAM section
(the duct the air enters). Exit coefficients multiply that of the UPSTREAM
section (the duct the air leaves). D is the duct diameter; for a rectangular
duct the source uses D = 2HW / (H + W).

A screen or perforated plate in the opening adds its own coefficient from
Table 14-17 (see screens.py), scaled to the duct velocity -- see
`with_screen()` at the bottom.

Suspected misprint, kept exactly as printed: 14-16 B, As/A = 10, 60 deg:
0.72 (its neighbours in the column are 0.98 and 1.0).
"""

from .table import REF_DOWNSTREAM, REF_UPSTREAM, Lookup, LossTable

_ROUND = ("Circular",)
_RECT = ("Rectangular",)
_BOTH = ("Circular", "Rectangular")

# ----------------------------------------------------------------------------
# 14-15 A. Duct mounted in wall, round and rectangular.
# t = duct wall thickness, L = how far the duct sticks out of the wall.
# The printed rows are t/D "about 0", 0.02 and ">= 0.05"; the columns end at
# L/D ">= 1.0".
# ----------------------------------------------------------------------------

ENTRY_DUCT_IN_WALL = LossTable(
    "14-15A",
    "Entry, duct mounted in wall",
    [("t_on_d", [0, 0.02, 0.05]), ("l_on_d", [0, 0.002, 0.01, 0.05, 0.2, 0.5, 1.0])],
    [
        [0.50, 0.57, 0.68, 0.80, 0.92, 1.0, 1.0],
        [0.50, 0.51, 0.52, 0.55, 0.66, 0.72, 0.72],
        [0.50, 0.50, 0.50, 0.50, 0.50, 0.50, 0.50],
    ],
    REF_DOWNSTREAM,
    _BOTH,
)

# ----------------------------------------------------------------------------
# 14-15 B, C. Smooth converging bellmouth, round. R = lip radius; the last
# column is "0.20 and greater".
# ----------------------------------------------------------------------------

_BELLMOUTH_R_ON_D = [0, 0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.08, 0.10, 0.12, 0.16, 0.20]

ENTRY_BELLMOUTH_FREE = LossTable(
    "14-15B",
    "Entry, smooth converging bellmouth, round, without end wall",
    [("r_on_d", _BELLMOUTH_R_ON_D)],
    [1.0, 0.87, 0.74, 0.61, 0.51, 0.40, 0.32, 0.20, 0.15, 0.10, 0.06, 0.03],
    REF_DOWNSTREAM,
    _ROUND,
)

ENTRY_BELLMOUTH_WALL = LossTable(
    "14-15C",
    "Entry, smooth converging bellmouth, round, with end wall",
    [("r_on_d", _BELLMOUTH_R_ON_D)],
    [0.50, 0.43, 0.36, 0.31, 0.26, 0.22, 0.20, 0.15, 0.12, 0.09, 0.06, 0.03],
    REF_DOWNSTREAM,
    _ROUND,
)

# ----------------------------------------------------------------------------
# 14-15 D, E. Conical converging bellmouth, round and rectangular.
# L = cone length, theta = included angle (the major angle for rectangular).
# ----------------------------------------------------------------------------

_CONE_THETA = [0, 10, 20, 30, 40, 60, 100, 140, 180]

ENTRY_CONICAL_FREE = LossTable(
    "14-15D",
    "Entry, conical converging bellmouth, without end wall",
    [("l_on_d", [0.025, 0.05, 0.10, 0.25, 0.60, 1.0]), ("theta_deg", _CONE_THETA)],
    [
        [1.0, 0.96, 0.93, 0.90, 0.86, 0.80, 0.69, 0.59, 0.50],
        [1.0, 0.93, 0.86, 0.80, 0.75, 0.67, 0.58, 0.53, 0.50],
        [1.0, 0.80, 0.67, 0.55, 0.48, 0.41, 0.41, 0.44, 0.50],
        [1.0, 0.68, 0.45, 0.30, 0.22, 0.17, 0.22, 0.34, 0.50],
        [1.0, 0.46, 0.27, 0.18, 0.14, 0.13, 0.21, 0.33, 0.50],
        [1.0, 0.32, 0.20, 0.14, 0.11, 0.10, 0.18, 0.30, 0.50],
    ],
    REF_DOWNSTREAM,
    _BOTH,
)

ENTRY_CONICAL_WALL = LossTable(
    "14-15E",
    "Entry, conical converging bellmouth, with end wall",
    [("l_on_d", [0.025, 0.05, 0.075, 0.10, 0.15, 0.60]), ("theta_deg", _CONE_THETA)],
    [
        [0.50, 0.47, 0.45, 0.43, 0.41, 0.40, 0.42, 0.45, 0.50],
        [0.50, 0.45, 0.41, 0.36, 0.33, 0.30, 0.35, 0.42, 0.50],
        [0.50, 0.42, 0.35, 0.30, 0.26, 0.23, 0.30, 0.40, 0.50],
        [0.50, 0.39, 0.32, 0.25, 0.22, 0.18, 0.27, 0.38, 0.50],
        [0.50, 0.37, 0.27, 0.20, 0.16, 0.15, 0.25, 0.37, 0.50],
        [0.50, 0.27, 0.18, 0.13, 0.11, 0.12, 0.23, 0.36, 0.50],
    ],
    REF_DOWNSTREAM,
    _BOTH,
)

# ----------------------------------------------------------------------------
# 14-15 F. Intake hood (weather cap of diameter 2D, L above the duct end).
# theta = 0 is a straight duct end, 15 deg a flared one. Last column: "0.9 or greater".
# ----------------------------------------------------------------------------

ENTRY_INTAKE_HOOD = LossTable(
    "14-15F",
    "Entry, intake hood",
    [("theta_deg", [0, 15]), ("l_on_d", [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9])],
    [[2.6, 1.8, 1.5, 1.4, 1.3, 1.2, 1.2, 1.1, 1.1], [1.3, 0.77, 0.60, 0.48, 0.41, 0.30, 0.29, 0.28, 0.25]],
    REF_DOWNSTREAM,
    _ROUND,
)

# ----------------------------------------------------------------------------
# 14-15 G. Hood, tapered, flanged or unflanged (face area at least twice the
# duct area). Also the coefficient for a slot hood (14-15 I).
# ----------------------------------------------------------------------------

_HOOD_THETA = [0, 20, 40, 60, 80, 100, 120, 140, 160, 180]

ENTRY_HOOD_TAPERED_ROUND = LossTable(
    "14-15G round",
    "Entry, tapered hood, round",
    [("theta_deg", _HOOD_THETA)],
    [1.0, 0.11, 0.06, 0.09, 0.14, 0.18, 0.27, 0.32, 0.43, 0.50],
    REF_DOWNSTREAM,
    _ROUND,
)

ENTRY_HOOD_TAPERED_RECT = LossTable(
    "14-15G rect",
    "Entry, tapered hood, square or rectangular",
    [("theta_deg", _HOOD_THETA)],
    [1.0, 0.19, 0.13, 0.16, 0.21, 0.27, 0.33, 0.43, 0.53, 0.62],
    REF_DOWNSTREAM,
    _RECT,
)

# 14-15 H. Canopy (island or range) hood: one coefficient. The source adds
# the clean-filter resistance plus 25 Pa on top of C * Vp.
ENTRY_CANOPY_HOOD_C = 0.5
ENTRY_CANOPY_HOOD_EXTRA_PA = 25.0

# ----------------------------------------------------------------------------
# 14-16 A. Exhaust hood (weather cap of diameter 2D, L above the duct end).
# ----------------------------------------------------------------------------

EXIT_EXHAUST_HOOD = LossTable(
    "14-16A",
    "Exit, exhaust hood",
    [("theta_deg", [0, 15]), ("l_on_d", [0.1, 0.2, 0.25, 0.3, 0.35, 0.4, 0.5, 0.6, 0.8, 1.0])],
    [[4.0, 2.3, 1.9, 1.6, 1.4, 1.3, 1.2, 1.1, 1.0, 1.0], [2.6, 1.2, 1.0, 0.80, 0.70, 0.65, 0.60, 0.60, 0.60, 0.60]],
    REF_UPSTREAM,
    _ROUND,
)

# ----------------------------------------------------------------------------
# 14-16 B, C, D. Diffusing exits, with or without a wall. As = exit area,
# A = duct area. The last angle column is ">= 90" (B, C) or ">= 60" (D).
# ----------------------------------------------------------------------------

EXIT_CONICAL_ROUND = LossTable(
    "14-16B",
    "Exit, conical, round",
    [("area_ratio", [2, 4, 6, 10, 16]), ("theta_deg", [14, 16, 20, 30, 45, 60, 90])],
    [
        [0.33, 0.36, 0.44, 0.74, 0.97, 0.99, 1.0],
        [0.24, 0.28, 0.36, 0.54, 0.94, 1.0, 1.0],
        [0.22, 0.25, 0.32, 0.49, 0.94, 0.98, 1.0],
        [0.19, 0.23, 0.30, 0.50, 0.94, 0.72, 1.0],
        [0.17, 0.20, 0.27, 0.49, 0.94, 1.0, 1.0],
    ],
    REF_UPSTREAM,
    _ROUND,
)

# Printed for 0.5 <= H/W <= 2.0.
EXIT_PLANE_DIFFUSER_RECT = LossTable(
    "14-16C",
    "Exit, plane diffuser, rectangular",
    [("area_ratio", [2, 4, 6]), ("theta_deg", [14, 20, 30, 45, 60, 90])],
    [[0.37, 0.38, 0.50, 0.75, 0.90, 1.1], [0.25, 0.37, 0.57, 0.82, 1.0, 1.1], [0.28, 0.47, 0.64, 0.87, 1.0, 1.1]],
    REF_UPSTREAM,
    _RECT,
)

EXIT_PYRAMIDAL_DIFFUSER_RECT = LossTable(
    "14-16D",
    "Exit, pyramidal diffuser, rectangular",
    [("area_ratio", [2, 4, 6, 10]), ("theta_deg", [10, 14, 20, 30, 45, 60])],
    [
        [0.44, 0.58, 0.70, 0.86, 1.0, 1.1],
        [0.31, 0.48, 0.61, 0.76, 0.94, 1.1],
        [0.29, 0.47, 0.62, 0.74, 0.94, 1.1],
        [0.26, 0.45, 0.60, 0.73, 0.89, 1.0],
    ],
    REF_UPSTREAM,
    _RECT,
)

# ----------------------------------------------------------------------------
# 14-16 E. Exit, discharge to atmosphere from a 90 deg elbow. The elbow's
# own loss is included. L = straight length after the elbow.
# ----------------------------------------------------------------------------

EXIT_FROM_ELBOW_RECT = LossTable(
    "14-16E rect",
    "Exit, discharge to atmosphere from a 90 deg elbow, rectangular",
    [("r_on_w", [0, 0.75, 1.0, 1.5, 2.5]), ("l_on_w", [0, 0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 6.0, 8.0, 12.0])],
    [
        [3.0, 3.1, 3.2, 3.0, 2.7, 2.4, 2.2, 2.1, 2.1, 2.0],
        [2.2, 2.2, 2.1, 1.8, 1.7, 1.6, 1.6, 1.5, 1.5, 1.5],
        [1.8, 1.5, 1.4, 1.4, 1.3, 1.3, 1.2, 1.2, 1.2, 1.2],
        [1.5, 1.2, 1.1, 1.1, 1.1, 1.1, 1.1, 1.1, 1.1, 1.1],
        [1.2, 1.1, 1.1, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0],
    ],
    REF_UPSTREAM,
    _RECT,
)

# Printed for R/D = 1.0 only.
EXIT_FROM_ELBOW_ROUND = LossTable(
    "14-16E round",
    "Exit, discharge to atmosphere from a 90 deg elbow, round (R/D = 1.0)",
    [("l_on_d", [0.9, 1.3])],
    [1.5, 1.4],
    REF_UPSTREAM,
    _ROUND,
)

# ----------------------------------------------------------------------------
# 14-16 F. Exit, duct flush with wall, flow along wall. V = duct velocity,
# Vo = velocity of the stream passing the opening, theta = angle between them.
# The rectangular table has three aspect-ratio (H/W) bands; the round table
# is the same as the middle band. Angle ranges printed as one row are
# written as their two end angles.
# ----------------------------------------------------------------------------

_CROSSFLOW_V = [0, 0.5, 1.0, 1.5, 2.0]


def _crossflow(suffix, title, theta, values, profiles):
    return LossTable(
        "14-16F {}".format(suffix),
        "Exit, duct flush with wall, flow along wall: " + title,
        [("theta_deg", theta), ("v_on_vo", _CROSSFLOW_V)],
        values,
        REF_UPSTREAM,
        profiles,
    )


_CROSSFLOW_MIDDLE = [
    [1.0, 1.0, 1.1, 1.3, 1.6],
    [1.0, 1.0, 1.1, 1.3, 1.6],
    [1.0, 0.90, 1.1, 1.4, 1.6],
    [1.0, 0.80, 0.95, 1.4, 1.7],
    [1.0, 0.80, 0.95, 1.3, 1.7],
    [1.0, 0.82, 0.83, 1.0, 1.3],
]

# (lowest H/W, highest H/W, table) for each printed aspect-ratio band.
EXIT_CROSSFLOW_RECT_BANDS = [
    (
        0.1,
        0.2,
        _crossflow(
            "rect H/W 0.1-0.2",
            "rectangular, H/W 0.1 to 0.2",
            [30, 90, 120, 150],
            [
                [1.0, 0.95, 1.2, 1.5, 1.8],
                [1.0, 0.95, 1.2, 1.5, 1.8],
                [1.0, 0.92, 1.1, 1.4, 1.9],
                [1.0, 0.75, 0.95, 1.4, 1.8],
            ],
            _RECT,
        ),
    ),
    (
        0.5,
        2.0,
        _crossflow(
            "rect H/W 0.5-2.0", "rectangular, H/W 0.5 to 2.0", [30, 45, 60, 90, 120, 150], _CROSSFLOW_MIDDLE, _RECT
        ),
    ),
    (
        5.0,
        10.0,
        _crossflow(
            "rect H/W 5-10",
            "rectangular, H/W 5 to 10",
            [45, 60, 90, 120],
            [
                [1.0, 0.92, 0.93, 1.1, 1.3],
                [1.0, 0.87, 0.87, 1.0, 1.3],
                [1.0, 0.82, 0.80, 0.97, 1.2],
                [1.0, 0.80, 0.76, 0.90, 0.98],
            ],
            _RECT,
        ),
    ),
]

EXIT_CROSSFLOW_ROUND = _crossflow("round", "round", [30, 45, 60, 90, 120, 150], _CROSSFLOW_MIDDLE, _ROUND)

# ----------------------------------------------------------------------------
# 14-16 G, H. Diffusers at a fan outlet without ductwork (free discharge).
# A = fan outlet area, A1 = diffuser exit area.
# ----------------------------------------------------------------------------

_FAN_AREA_RATIO = [1.5, 2.0, 2.5, 3.0, 3.5, 4.0]

EXIT_FAN_PLANE_ASYMMETRIC = LossTable(
    "14-16G",
    "Exit, plane asymmetric diffuser at fan outlet without ductwork",
    [("theta_deg", [10, 15, 20, 25, 30, 35]), ("area_ratio", _FAN_AREA_RATIO)],
    [
        [0.51, 0.34, 0.25, 0.21, 0.18, 0.17],
        [0.54, 0.36, 0.27, 0.24, 0.22, 0.20],
        [0.55, 0.38, 0.31, 0.27, 0.25, 0.24],
        [0.59, 0.43, 0.37, 0.35, 0.33, 0.33],
        [0.63, 0.50, 0.46, 0.44, 0.43, 0.42],
        [0.65, 0.56, 0.53, 0.52, 0.51, 0.50],
    ],
    REF_UPSTREAM,
    _RECT,
)

EXIT_FAN_PYRAMIDAL = LossTable(
    "14-16H",
    "Exit, pyramidal diffuser at fan outlet without ductwork",
    [("theta_deg", [10, 15, 20, 25, 30]), ("area_ratio", _FAN_AREA_RATIO)],
    [
        [0.54, 0.42, 0.37, 0.34, 0.32, 0.31],
        [0.67, 0.58, 0.53, 0.51, 0.50, 0.51],
        [0.75, 0.67, 0.65, 0.64, 0.64, 0.65],
        [0.80, 0.74, 0.72, 0.70, 0.70, 0.72],
        [0.85, 0.78, 0.76, 0.75, 0.75, 0.76],
    ],
    REF_UPSTREAM,
    _RECT,
)

# 14-16 I. Fan, free discharge into a plenum: one coefficient per wheel type.
EXIT_FAN_INTO_PLENUM_C = {"airfoil": 1.0, "backward_inclined": 1.5, "forward_curved": 1.8}

# 14-16 J. Exit, abrupt, round and rectangular, with or without a wall.
EXIT_ABRUPT_C = 1.0


# ----------------------------------------------------------------------------
# Lookups
# ----------------------------------------------------------------------------


def entry_duct_in_wall(t_on_d, l_on_d):
    """14-15 A. t/D of 0.05 and above, and L/D of 1.0 and above, read the last row/column as printed."""
    return ENTRY_DUCT_IN_WALL.lookup(min(float(t_on_d), 0.05), min(float(l_on_d), 1.0))


def entry_bellmouth(r_on_d, end_wall):
    """14-15 B (no end wall) / C (with end wall). R/D of 0.20 and above reads the last column as printed."""
    table = ENTRY_BELLMOUTH_WALL if end_wall else ENTRY_BELLMOUTH_FREE
    return table.lookup(min(float(r_on_d), 0.20))


def entry_conical(theta_deg, l_on_d, end_wall):
    """14-15 D (no end wall) / E (with end wall)."""
    table = ENTRY_CONICAL_WALL if end_wall else ENTRY_CONICAL_FREE
    return table.lookup(l_on_d, theta_deg)


def entry_intake_hood(theta_deg, l_on_d):
    """14-15 F. L/D of 0.9 and above reads the last column as printed."""
    return ENTRY_INTAKE_HOOD.lookup(theta_deg, min(float(l_on_d), 0.9))


def entry_hood_tapered(theta_deg, rectangular):
    """14-15 G (also used for the slot hood of 14-15 I)."""
    table = ENTRY_HOOD_TAPERED_RECT if rectangular else ENTRY_HOOD_TAPERED_ROUND
    return table.lookup(theta_deg)


def exit_exhaust_hood(theta_deg, l_on_d):
    """14-16 A."""
    return EXIT_EXHAUST_HOOD.lookup(theta_deg, l_on_d)


def exit_conical_round(theta_deg, area_ratio):
    """14-16 B. 90 deg and above reads the last column as printed."""
    return EXIT_CONICAL_ROUND.lookup(area_ratio, min(float(theta_deg), 90.0))


def exit_plane_diffuser_rect(theta_deg, area_ratio):
    """14-16 C. 90 deg and above reads the last column as printed."""
    return EXIT_PLANE_DIFFUSER_RECT.lookup(area_ratio, min(float(theta_deg), 90.0))


def exit_pyramidal_diffuser_rect(theta_deg, area_ratio):
    """14-16 D. 60 deg and above reads the last column as printed."""
    return EXIT_PYRAMIDAL_DIFFUSER_RECT.lookup(area_ratio, min(float(theta_deg), 60.0))


def exit_from_elbow_rect(r_on_w, l_on_w):
    """14-16 E, rectangular."""
    return EXIT_FROM_ELBOW_RECT.lookup(r_on_w, l_on_w)


def exit_from_elbow_round(l_on_d, r_on_d=1.0):
    """14-16 E, round. Only printed for R/D = 1.0; any other radius is flagged."""
    result = EXIT_FROM_ELBOW_ROUND.lookup(l_on_d)
    off_table = abs(float(r_on_d) - 1.0) > 0.02
    return Lookup(result.value, result.clamped or off_table, result.filled)


def exit_crossflow_rect(h_on_w, theta_deg, v_on_vo):
    """
    14-16 F, rectangular. Uses the printed aspect-ratio band H/W falls in;
    between two bands the nearer one is used and the result is flagged.
    """
    h_on_w = float(h_on_w)

    def gap(band):
        low, high, _table = band
        return 0.0 if low <= h_on_w <= high else min(abs(h_on_w - low), abs(h_on_w - high))

    band = min(EXIT_CROSSFLOW_RECT_BANDS, key=gap)
    result = band[2].lookup(theta_deg, v_on_vo)
    return Lookup(result.value, result.clamped or gap(band) > 0.0, result.filled)


def exit_crossflow_round(theta_deg, v_on_vo):
    """14-16 F, round."""
    return EXIT_CROSSFLOW_ROUND.lookup(theta_deg, v_on_vo)


def exit_fan_diffuser(pyramidal, theta_deg, area_ratio):
    """14-16 G (plane asymmetric) / H (pyramidal): a diffuser on a fan outlet discharging freely."""
    table = EXIT_FAN_PYRAMIDAL if pyramidal else EXIT_FAN_PLANE_ASYMMETRIC
    return table.lookup(theta_deg, area_ratio)


def exit_fan_into_plenum(wheel):
    """14-16 I. `wheel` is one of the EXIT_FAN_INTO_PLENUM_C keys."""
    try:
        return Lookup(EXIT_FAN_INTO_PLENUM_C[wheel])
    except KeyError:
        raise ValueError(
            "Unknown fan wheel '{}'. Known: {}".format(wheel, ", ".join(sorted(EXIT_FAN_INTO_PLENUM_C)))
        ) from None


def with_screen(base, screen, opening_area_ratio=1.0):
    """
    Notes 9 to 12: add a screen or perforated plate in the opening.

    `base` is the entry/exit Lookup, `screen` the Table 14-17 Lookup, and
    `opening_area_ratio` = area of the opening the screen sits in / duct
    area (As/A, or A1/A at a fan diffuser). The screen coefficient is
    referenced to the velocity through that opening, so it is divided by
    the area ratio squared to bring it to the duct velocity.
    """
    ratio = float(opening_area_ratio)
    if ratio <= 0.0:
        raise ValueError("opening_area_ratio must be positive")
    value = base.value + screen.value / (ratio**2)
    return Lookup(value, base.clamped or screen.clamped, base.filled or screen.filled)
