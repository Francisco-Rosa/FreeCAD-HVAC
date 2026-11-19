# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the HVAC addon.

"""
SMACNA Table 14-11 (transitions, diverging flow) and Table 14-12
(transitions, converging flow).

14-11 coefficients multiply the velocity pressure of the UPSTREAM section;
14-12 coefficients multiply that of the DOWNSTREAM section. In both, A is
the smaller area and A1 the larger one, and theta is the included angle of
the transition (180 deg is an abrupt change).
"""

import math

from .table import REF_DOWNSTREAM, REF_UPSTREAM, LossTable, combine

_ROUND = ("Circular",)
_RECT = ("Rectangular",)
_BOTH = ("Circular", "Rectangular")

# ----------------------------------------------------------------------------
# 14-11 A. Transition, round, conical
# Three blocks are printed, for Re = 0.5e5, 2e5 and >= 6e5 (Re of the
# upstream duct). ">= 16" is the last area-ratio row.
# 0.90 at Re 2e5, A1/A = 6, 45 deg looks like a misprint; kept as printed.
# ----------------------------------------------------------------------------

_EXPANSION_THETA = [16, 20, 30, 45, 60, 90, 120, 180]

EXPANSION_ROUND = LossTable(
    "14-11A",
    "Transition, round, conical",
    [("reynolds", [0.5e5, 2.0e5, 6.0e5]), ("area_ratio", [2, 4, 6, 10, 16]), ("theta_deg", _EXPANSION_THETA)],
    [
        [
            [0.14, 0.19, 0.32, 0.33, 0.33, 0.32, 0.31, 0.30],
            [0.23, 0.30, 0.46, 0.61, 0.68, 0.64, 0.63, 0.62],
            [0.27, 0.33, 0.48, 0.66, 0.77, 0.74, 0.73, 0.72],
            [0.29, 0.38, 0.59, 0.76, 0.80, 0.83, 0.84, 0.83],
            [0.31, 0.38, 0.60, 0.84, 0.88, 0.88, 0.88, 0.88],
        ],
        [
            [0.07, 0.12, 0.23, 0.28, 0.27, 0.27, 0.27, 0.26],
            [0.15, 0.18, 0.36, 0.55, 0.59, 0.59, 0.58, 0.57],
            [0.19, 0.28, 0.44, 0.90, 0.70, 0.71, 0.71, 0.69],
            [0.20, 0.24, 0.43, 0.76, 0.80, 0.81, 0.81, 0.81],
            [0.21, 0.28, 0.52, 0.76, 0.87, 0.87, 0.87, 0.87],
        ],
        [
            [0.05, 0.07, 0.12, 0.27, 0.27, 0.27, 0.27, 0.27],
            [0.17, 0.24, 0.38, 0.51, 0.56, 0.58, 0.58, 0.57],
            [0.16, 0.29, 0.46, 0.60, 0.69, 0.71, 0.70, 0.70],
            [0.21, 0.33, 0.52, 0.60, 0.76, 0.83, 0.84, 0.83],
            [0.21, 0.34, 0.56, 0.72, 0.79, 0.85, 0.87, 0.89],
        ],
    ],
    REF_UPSTREAM,
    _ROUND,
)

# ----------------------------------------------------------------------------
# 14-11 B. Transition, rectangular, pyramidal (">= 10" is the last row)
# Also the table used for round-to-rectangular and rectangular-to-round
# transitions (14-11 C and D), with an equivalent angle.
# ----------------------------------------------------------------------------

EXPANSION_RECT_PYRAMIDAL = LossTable(
    "14-11B",
    "Transition, rectangular, pyramidal",
    [("area_ratio", [2, 4, 6, 10]), ("theta_deg", _EXPANSION_THETA)],
    [
        [0.18, 0.22, 0.25, 0.29, 0.31, 0.32, 0.33, 0.30],
        [0.36, 0.43, 0.50, 0.56, 0.61, 0.63, 0.63, 0.63],
        [0.42, 0.47, 0.58, 0.68, 0.72, 0.76, 0.76, 0.75],
        [0.42, 0.49, 0.59, 0.70, 0.80, 0.87, 0.85, 0.86],
    ],
    REF_UPSTREAM,
    _RECT,
)

# ----------------------------------------------------------------------------
# 14-11 E. Transition, rectangular, sides straight (only one pair of sides diverges)
# ----------------------------------------------------------------------------

EXPANSION_RECT_SIDES_STRAIGHT = LossTable(
    "14-11E",
    "Transition, rectangular, sides straight",
    [("area_ratio", [2, 4, 6]), ("theta_deg", [14, 20, 30, 45, 60, 90, 180])],
    [
        [0.09, 0.12, 0.20, 0.34, 0.37, 0.38, 0.35],
        [0.16, 0.25, 0.42, 0.60, 0.68, 0.70, 0.66],
        [0.19, 0.30, 0.48, 0.65, 0.76, 0.83, 0.80],
    ],
    REF_UPSTREAM,
    _RECT,
)

# ----------------------------------------------------------------------------
# 14-11 F to J. Transitions at a fan outlet, with duct downstream.
# Axes: theta (deg), A1/A.
# ----------------------------------------------------------------------------

_FAN_AREA_RATIO = [1.5, 2.0, 2.5, 3.0, 3.5, 4.0]
_FAN_THETA = [10, 15, 20, 25, 30, 35]


def _fan_table(letter, title, theta, values):
    return LossTable(
        "14-11{}".format(letter),
        title,
        [("theta_deg", theta), ("area_ratio", _FAN_AREA_RATIO)],
        values,
        REF_UPSTREAM,
        _RECT,
    )


FAN_SYMMETRIC_SIDES_STRAIGHT = _fan_table(
    "F",
    "Transition, symmetric at fan with duct sides straight",
    _FAN_THETA,
    [
        [0.05, 0.07, 0.09, 0.10, 0.11, 0.11],
        [0.06, 0.09, 0.11, 0.13, 0.13, 0.14],
        [0.07, 0.10, 0.13, 0.15, 0.16, 0.16],
        [0.08, 0.13, 0.16, 0.19, 0.21, 0.23],
        [0.16, 0.24, 0.29, 0.32, 0.34, 0.35],
        [0.24, 0.34, 0.39, 0.44, 0.48, 0.50],
    ],
)

FAN_ASYMMETRIC_TOP_LEVEL = _fan_table(
    "G",
    "Transition, asymmetric at fan with duct sides straight, top level",
    _FAN_THETA,
    [
        [0.08, 0.09, 0.10, 0.10, 0.11, 0.11],
        [0.10, 0.11, 0.12, 0.13, 0.14, 0.15],
        [0.12, 0.14, 0.15, 0.16, 0.17, 0.18],
        [0.15, 0.18, 0.21, 0.23, 0.25, 0.26],
        [0.18, 0.25, 0.30, 0.33, 0.35, 0.35],
        [0.21, 0.31, 0.38, 0.41, 0.43, 0.44],
    ],
)

FAN_ASYMMETRIC_TOP_10_DOWN = _fan_table(
    "H",
    "Transition, asymmetric at fan with duct sides straight, top 10 deg down",
    _FAN_THETA,
    [
        [0.11, 0.13, 0.14, 0.14, 0.14, 0.14],
        [0.13, 0.15, 0.16, 0.17, 0.18, 0.18],
        [0.19, 0.22, 0.24, 0.26, 0.28, 0.30],
        [0.29, 0.32, 0.35, 0.37, 0.39, 0.40],
        [0.36, 0.42, 0.46, 0.49, 0.51, 0.51],
        [0.44, 0.54, 0.61, 0.64, 0.66, 0.66],
    ],
)

FAN_ASYMMETRIC_TOP_10_UP = _fan_table(
    "I",
    "Transition, asymmetric at fan with duct sides straight, top 10 deg up",
    _FAN_THETA,
    [
        [0.05, 0.08, 0.11, 0.13, 0.13, 0.14],
        [0.06, 0.10, 0.12, 0.14, 0.15, 0.15],
        [0.07, 0.11, 0.14, 0.15, 0.16, 0.16],
        [0.09, 0.14, 0.18, 0.20, 0.21, 0.22],
        [0.13, 0.18, 0.23, 0.26, 0.28, 0.29],
        [0.15, 0.23, 0.28, 0.33, 0.35, 0.36],
    ],
)

FAN_PYRAMIDAL = _fan_table(
    "J",
    "Transition, pyramidal at fan with duct",
    [10, 15, 20, 25, 30],
    [
        [0.10, 0.18, 0.21, 0.23, 0.24, 0.25],
        [0.23, 0.33, 0.38, 0.40, 0.42, 0.44],
        [0.31, 0.43, 0.48, 0.53, 0.56, 0.58],
        [0.36, 0.49, 0.55, 0.58, 0.62, 0.64],
        [0.42, 0.53, 0.59, 0.64, 0.67, 0.69],
    ],
)

FAN_TRANSITIONS = {
    "symmetric_sides_straight": FAN_SYMMETRIC_SIDES_STRAIGHT,
    "asymmetric_top_level": FAN_ASYMMETRIC_TOP_LEVEL,
    "asymmetric_top_10_down": FAN_ASYMMETRIC_TOP_10_DOWN,
    "asymmetric_top_10_up": FAN_ASYMMETRIC_TOP_10_UP,
    "pyramidal": FAN_PYRAMIDAL,
}

# ----------------------------------------------------------------------------
# 14-12 A. Contraction, round and rectangular, gradual to abrupt
# The source prints two angle ranges (15-40 and 50-60 deg) as single
# columns; each is written here as its two end angles with the same value.
# ----------------------------------------------------------------------------

CONTRACTION = LossTable(
    "14-12A",
    "Contraction, round and rectangular, gradual to abrupt",
    [("area_ratio", [2, 4, 6, 10]), ("theta_deg", [10, 15, 40, 50, 60, 90, 120, 150, 180])],
    [
        [0.05, 0.05, 0.05, 0.06, 0.06, 0.12, 0.18, 0.24, 0.26],
        [0.05, 0.04, 0.04, 0.07, 0.07, 0.17, 0.27, 0.35, 0.41],
        [0.05, 0.04, 0.04, 0.07, 0.07, 0.18, 0.28, 0.36, 0.42],
        [0.05, 0.05, 0.05, 0.08, 0.08, 0.19, 0.29, 0.37, 0.43],
    ],
    REF_DOWNSTREAM,
    _BOTH,
)

# ----------------------------------------------------------------------------
# 14-12 B. Contraction, conical, round and rectangular: C = K * Co
# (a short cone on the end of a larger duct or plenum). L = cone length,
# D = downstream diameter (hydraulic diameter 2HW/(H+W) for rectangular).
# ----------------------------------------------------------------------------

CONICAL_CONTRACTION_K = LossTable(
    "14-12B K",
    "Contraction, conical: area factor K",
    [("a_on_a1", [0, 0.2, 0.4, 0.6, 0.8, 0.9, 1.0])],
    [1.0, 0.85, 0.68, 0.50, 0.30, 0.18, 0],
    REF_DOWNSTREAM,
    _BOTH,
)

CONICAL_CONTRACTION_CO = LossTable(
    "14-12B Co",
    "Contraction, conical: base coefficient Co",
    [("l_on_d", [0.025, 0.05, 0.075, 0.10, 0.15, 0.60]), ("theta_deg", [0, 10, 20, 30, 40, 60, 100, 140, 180])],
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
# 14-12 C. Contraction, rectangular slot to round (Re of the round outlet,
# in units of 1e4; ">= 40" is the last column)
# ----------------------------------------------------------------------------

SLOT_TO_ROUND = LossTable(
    "14-12C",
    "Contraction, rectangular slot to round",
    [("re_1e4", [1, 2, 4, 6, 8, 10, 20, 40])],
    [0.27, 0.25, 0.20, 0.17, 0.14, 0.11, 0.04, 0],
    REF_DOWNSTREAM,
    ("Circular", "Rectangular"),
)


# ----------------------------------------------------------------------------
# Lookups
# ----------------------------------------------------------------------------


def expansion_round(theta_deg, area_ratio, reynolds):
    """
    14-11 A. Between the three printed Reynolds numbers the coefficient is
    interpolated; below 0.5e5 the first block is used (flagged as clamped),
    and from 6e5 up the last block applies as printed.
    """
    return EXPANSION_ROUND.lookup(min(float(reynolds), 6.0e5), min(float(area_ratio), 16.0), theta_deg)


def expansion_rect_pyramidal(theta_deg, area_ratio):
    """14-11 B (area ratios of 10 and above read the last row, as printed)."""
    return EXPANSION_RECT_PYRAMIDAL.lookup(min(float(area_ratio), 10.0), theta_deg)


def round_rect_equivalent_angle(diameter, width, height, length):
    """
    14-11 C and D: the included angle (deg) to read Table 14-11 B at, for a
    transition between a round end (diameter) and a rectangular end
    (width x height) of the given length. The same formula serves both
    directions; only which end is larger changes its sign.
    """
    if length <= 0.0:
        return 180.0
    half = math.atan(abs(1.13 * math.sqrt(float(width) * float(height)) - float(diameter)) / (2.0 * float(length)))
    return math.degrees(2.0 * half)


def expansion_round_rect(diameter, width, height, length, area_ratio):
    """14-11 C / D: a round-to-rectangular or rectangular-to-round expansion, read from 14-11 B."""
    return expansion_rect_pyramidal(round_rect_equivalent_angle(diameter, width, height, length), area_ratio)


def expansion_rect_sides_straight(theta_deg, area_ratio):
    """14-11 E."""
    return EXPANSION_RECT_SIDES_STRAIGHT.lookup(area_ratio, theta_deg)


def expansion_at_fan(kind, theta_deg, area_ratio):
    """14-11 F to J. `kind` is one of the FAN_TRANSITIONS keys."""
    try:
        table = FAN_TRANSITIONS[kind]
    except KeyError:
        raise ValueError(
            "Unknown fan transition '{}'. Known: {}".format(kind, ", ".join(sorted(FAN_TRANSITIONS)))
        ) from None
    return table.lookup(theta_deg, area_ratio)


def contraction(theta_deg, area_ratio):
    """14-12 A. area_ratio = larger area / smaller area."""
    return CONTRACTION.lookup(area_ratio, theta_deg)


def conical_contraction(theta_deg, l_on_d, a_on_a1):
    """14-12 B: C = K * Co. a_on_a1 = smaller (outlet) area / larger (inlet) area."""
    k, co = CONICAL_CONTRACTION_K.lookup(a_on_a1), CONICAL_CONTRACTION_CO.lookup(l_on_d, theta_deg)
    return combine(k.value * co.value, k, co)


def slot_to_round(reynolds):
    """14-12 C. From Re = 40e4 up the coefficient is 0, as printed."""
    return SLOT_TO_ROUND.lookup(min(float(reynolds) / 1.0e4, 40.0))
