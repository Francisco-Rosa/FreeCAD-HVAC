# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the HVAC addon.

"""
SMACNA Table 14-10: loss coefficients for elbows.

Every coefficient multiplies the velocity pressure of the upstream section.
14-10 L (wye- or tee-shaped elbow) has no table of its own: the source says
to use the coefficient of a similar elbow when both legs have equal velocity.
"""

from .table import REF_UPSTREAM, Lookup, LossTable, combine

# The source prints an "infinity" column in a few tables. It is kept as a
# very large coordinate, so any real ratio above the last finite column
# effectively reads that last finite column.
INFINITY = 1.0e9

_ROUND = ("Circular",)
_RECT = ("Rectangular",)

# ----------------------------------------------------------------------------
# Notes shared by several tables
# ----------------------------------------------------------------------------

# Note 1: the smooth-radius tables are for a 90 deg turn; multiply by this for another angle.
ANGLE_FACTOR = LossTable(
    "14-10 Note 1",
    "Angle factor for smooth-radius elbows other than 90 deg",
    [("theta_deg", [0, 20, 30, 45, 60, 75, 90, 110, 130, 150, 180])],
    [0.0, 0.31, 0.45, 0.60, 0.78, 0.90, 1.00, 1.13, 1.20, 1.28, 1.40],
    REF_UPSTREAM,
)

# Notes 2 and 5: Reynolds number correction for mitered and Z-shaped elbows (Re in units of 1e4).
REYNOLDS_FACTOR_MITERED = LossTable(
    "14-10 Note 2",
    "Reynolds number correction, mitered elbows",
    [("re_1e4", [1, 2, 3, 4, 6, 8, 10, 14])],
    [1.40, 1.26, 1.19, 1.14, 1.09, 1.06, 1.04, 1.0],
    REF_UPSTREAM,
)

# Note 3: Reynolds number correction for smooth-radius rectangular elbows.
# Two rows are printed: R/W = 0.5 and R/W >= 0.75.
REYNOLDS_FACTOR_SMOOTH_RECT = LossTable(
    "14-10 Note 3",
    "Reynolds number correction, smooth-radius rectangular elbows",
    [("r_on_w", [0.5, 0.75]), ("re_1e4", [1, 2, 3, 4, 6, 8, 10, 14, 20])],
    [[1.40, 1.26, 1.19, 1.14, 1.09, 1.06, 1.04, 1.0, 1.0], [2.0, 1.77, 1.64, 1.56, 1.46, 1.38, 1.30, 1.15, 1.0]],
    REF_UPSTREAM,
)

# Note 4: aspect-ratio factor for Z-shaped elbows (the table itself is for W/H = 1).
Z_ELBOW_ASPECT_FACTOR = LossTable(
    "14-10 Note 4",
    "Aspect-ratio factor for Z-shaped elbows",
    [("w_on_h", [0.25, 0.50, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0, 6.0, 8.0])],
    [1.10, 1.07, 1.04, 1.0, 0.95, 0.90, 0.83, 0.78, 0.72, 0.70],
    REF_UPSTREAM,
)

# ----------------------------------------------------------------------------
# A. Elbow, smooth radius (die stamped), round -- 90 deg
# ----------------------------------------------------------------------------

SMOOTH_ROUND = LossTable(
    "14-10A",
    "Elbow, smooth radius (die stamped), round",
    [("r_on_d", [0.5, 0.75, 1.0, 1.5, 2.0, 2.5])],
    [0.71, 0.33, 0.22, 0.15, 0.13, 0.12],
    REF_UPSTREAM,
    _ROUND,
)

# ----------------------------------------------------------------------------
# B. Elbow, round, 3 to 5 piece -- 90 deg
# ----------------------------------------------------------------------------

GORED_ROUND = LossTable(
    "14-10B",
    "Elbow, round, 3 to 5 piece, 90 deg",
    [("pieces", [5, 4, 3]), ("r_on_d", [0.5, 0.75, 1.0, 1.5, 2.0])],
    [[None, 0.46, 0.33, 0.24, 0.19], [None, 0.50, 0.37, 0.27, 0.24], [0.98, 0.54, 0.42, 0.34, 0.33]],
    REF_UPSTREAM,
    _ROUND,
)

# ----------------------------------------------------------------------------
# C. Elbow, round, mitered
# ----------------------------------------------------------------------------

MITERED_ROUND = LossTable(
    "14-10C",
    "Elbow, round, mitered",
    [("theta_deg", [20, 30, 45, 60, 75, 90])],
    [0.08, 0.16, 0.34, 0.55, 0.81, 1.2],
    REF_UPSTREAM,
    _ROUND,
)

# ----------------------------------------------------------------------------
# D. Elbow, rectangular, mitered
# ----------------------------------------------------------------------------

MITERED_RECT = LossTable(
    "14-10D",
    "Elbow, rectangular, mitered",
    [("theta_deg", [20, 30, 45, 60, 75, 90]), ("h_on_w", [0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0, 5.0, 6.0, 8.0])],
    [
        [0.08, 0.08, 0.08, 0.07, 0.07, 0.07, 0.06, 0.06, 0.05, 0.05, 0.05],
        [0.18, 0.17, 0.17, 0.16, 0.15, 0.15, 0.13, 0.13, 0.12, 0.12, 0.11],
        [0.38, 0.37, 0.36, 0.34, 0.33, 0.31, 0.28, 0.27, 0.26, 0.25, 0.24],
        [0.60, 0.59, 0.57, 0.55, 0.52, 0.49, 0.46, 0.43, 0.41, 0.39, 0.38],
        [0.89, 0.87, 0.84, 0.81, 0.77, 0.73, 0.67, 0.63, 0.61, 0.58, 0.57],
        [1.3, 1.3, 1.2, 1.2, 1.1, 1.1, 0.98, 0.92, 0.89, 0.85, 0.83],
    ],
    REF_UPSTREAM,
    _RECT,
)

# ----------------------------------------------------------------------------
# E. Elbow, rectangular, mitered with converging or diverging flow -- 90 deg
# W = inlet width, W1 = outlet width, H = the common height.
# ----------------------------------------------------------------------------

MITERED_RECT_SIZE_CHANGE = LossTable(
    "14-10E",
    "Elbow, rectangular, mitered with converging or diverging flow",
    [("h_on_w", [0.25, 1.0, 4.0, INFINITY]), ("w1_on_w", [0.6, 0.8, 1.2, 1.4, 1.6, 2.0])],
    [
        [1.8, 1.4, 1.1, 1.1, 1.1, 1.1],
        [1.7, 1.4, 1.0, 0.95, 0.90, 0.84],
        [1.5, 1.1, 0.81, 0.76, 0.72, 0.66],
        [1.5, 1.0, 0.69, 0.63, 0.60, 0.55],
    ],
    REF_UPSTREAM,
    _RECT,
)

# ----------------------------------------------------------------------------
# F. Elbow, rectangular, smooth radius without vanes -- 90 deg
# 0.27 at R/W = 1.0, H/W = 6.0 looks like a misprint; it is kept as printed.
# ----------------------------------------------------------------------------

SMOOTH_RECT = LossTable(
    "14-10F",
    "Elbow, rectangular, smooth radius without vanes",
    [("r_on_w", [0.5, 0.75, 1.0, 1.5, 2.0]), ("h_on_w", [0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0, 5.0, 6.0, 8.0])],
    [
        [1.5, 1.4, 1.3, 1.2, 1.1, 1.0, 1.0, 1.1, 1.1, 1.2, 1.2],
        [0.57, 0.52, 0.48, 0.44, 0.40, 0.39, 0.39, 0.40, 0.42, 0.43, 0.44],
        [0.27, 0.25, 0.23, 0.21, 0.19, 0.18, 0.18, 0.19, 0.20, 0.27, 0.21],
        [0.22, 0.20, 0.19, 0.17, 0.15, 0.14, 0.14, 0.15, 0.16, 0.17, 0.17],
        [0.20, 0.18, 0.16, 0.15, 0.14, 0.13, 0.13, 0.14, 0.14, 0.15, 0.15],
    ],
    REF_UPSTREAM,
    _RECT,
)

# ----------------------------------------------------------------------------
# G. Elbow, rectangular, smooth radius with splitter vanes -- 90 deg
# R here is the THROAT (inside) radius. Axes: vanes, R/W, H/W.
# ----------------------------------------------------------------------------

_SPLITTER_R_ON_W = [0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50]
_SPLITTER_H_ON_W = [0.25, 0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0]

SMOOTH_RECT_SPLITTER_VANES = LossTable(
    "14-10G",
    "Elbow, rectangular, smooth radius with splitter vanes",
    [("vanes", [1, 2, 3]), ("r_on_w", _SPLITTER_R_ON_W), ("h_on_w", _SPLITTER_H_ON_W)],
    [
        [
            [0.52, 0.40, 0.43, 0.49, 0.55, 0.66, 0.75, 0.84, 0.93, 1.0, 1.1],
            [0.36, 0.27, 0.25, 0.28, 0.30, 0.35, 0.39, 0.42, 0.46, 0.49, 0.52],
            [0.28, 0.21, 0.18, 0.19, 0.20, 0.22, 0.25, 0.26, 0.28, 0.30, 0.32],
            [0.22, 0.16, 0.14, 0.14, 0.15, 0.16, 0.17, 0.18, 0.19, 0.20, 0.21],
            [0.18, 0.13, 0.11, 0.11, 0.11, 0.12, 0.13, 0.14, 0.14, 0.15, 0.15],
            [0.15, 0.11, 0.09, 0.09, 0.09, 0.09, 0.10, 0.10, 0.11, 0.11, 0.12],
            [0.13, 0.09, 0.08, 0.07, 0.07, 0.08, 0.08, 0.08, 0.08, 0.09, 0.09],
            [0.11, 0.08, 0.07, 0.06, 0.06, 0.06, 0.06, 0.07, 0.07, 0.07, 0.07],
            [0.10, 0.07, 0.06, 0.05, 0.05, 0.05, 0.05, 0.05, 0.06, 0.06, 0.06],
            [0.09, 0.06, 0.05, 0.05, 0.04, 0.04, 0.04, 0.05, 0.05, 0.05, 0.05],
        ],
        [
            [0.26, 0.20, 0.22, 0.25, 0.28, 0.33, 0.37, 0.41, 0.45, 0.48, 0.51],
            [0.17, 0.13, 0.11, 0.12, 0.13, 0.15, 0.16, 0.17, 0.19, 0.20, 0.21],
            [0.12, 0.09, 0.08, 0.08, 0.08, 0.09, 0.10, 0.10, 0.11, 0.11, 0.11],
            [0.09, 0.07, 0.06, 0.05, 0.06, 0.06, 0.06, 0.06, 0.07, 0.07, 0.07],
            [0.08, 0.05, 0.04, 0.04, 0.04, 0.04, 0.05, 0.05, 0.05, 0.05, 0.05],
            [0.06, 0.04, 0.03, 0.03, 0.03, 0.03, 0.03, 0.03, 0.04, 0.04, 0.04],
            [0.05, 0.04, 0.03, 0.03, 0.03, 0.03, 0.03, 0.03, 0.03, 0.03, 0.03],
            [0.05, 0.03, 0.03, 0.02, 0.02, 0.02, 0.02, 0.02, 0.02, 0.02, 0.02],
            [0.04, 0.02, 0.02, 0.02, 0.02, 0.02, 0.02, 0.02, 0.02, 0.02, 0.02],
            [0.03, 0.02, 0.02, 0.02, 0.02, 0.01, 0.01, 0.01, 0.01, 0.01, 0.01],
        ],
        [
            [0.11, 0.10, 0.12, 0.13, 0.14, 0.16, 0.18, 0.19, 0.21, 0.22, 0.23],
            [0.07, 0.05, 0.06, 0.06, 0.06, 0.07, 0.07, 0.08, 0.08, 0.08, 0.09],
            [0.05, 0.04, 0.04, 0.04, 0.04, 0.04, 0.04, 0.04, 0.04, 0.05, 0.05],
            [0.03, 0.03, 0.03, 0.03, 0.03, 0.03, 0.03, 0.03, 0.03, 0.03, 0.03],
            [0.03, 0.02, 0.02, 0.02, 0.02, 0.02, 0.02, 0.02, 0.02, 0.02, 0.02],
            [0.03, 0.02, 0.02, 0.02, 0.02, 0.01, 0.01, 0.01, 0.01, 0.01, 0.01],
            [0.02, 0.02, 0.01, 0.01, 0.01, 0.01, 0.01, 0.01, 0.01, 0.01, 0.01],
            [0.02, 0.01, 0.01, 0.01, 0.01, 0.01, 0.01, 0.01, 0.01, 0.01, 0.01],
            [0.01, 0.01, 0.01, 0.01, 0.01, 0.01, 0.01, 0.01, 0.01, 0.01, 0.01],
            [0.01, 0.01, 0.01, 0.01, 0.01, 0.01, 0.01, 0.01, 0.01, 0.01, 0.01],
        ],
    ],
    REF_UPSTREAM,
    _RECT,
)

# ----------------------------------------------------------------------------
# H. Elbow, rectangular, mitered with turning vanes -- 90 deg
# One row per vane design the source lists; R = vane radius, S = vane
# spacing, both in mm. Axes: velocity in m/s.
# ----------------------------------------------------------------------------

_VANE_VELOCITY = [5.0, 7.5, 10.0, 12.5]


def _vane_table(suffix, title, values):
    return LossTable(
        "14-10H {}".format(suffix),
        "Elbow, rectangular, mitered with turning vanes: " + title,
        [("velocity_ms", _VANE_VELOCITY)],
        values,
        REF_UPSTREAM,
        _RECT,
    )


TURNING_VANES = {
    "single_r50_s38": _vane_table("single R50 S38", "single thickness, R 50, S 38", [0.24, 0.23, 0.22, 0.20]),
    "single_r114_s83": _vane_table("single R114 S83", "single thickness, R 114, S 83", [0.26, 0.24, 0.23, 0.22]),
    "double_r50_s38": _vane_table("double R50 S38", "double thickness, R 50, S 38", [0.43, 0.42, 0.41, 0.40]),
    "double_r50_s56": _vane_table("double R50 S56", "double thickness, R 50, S 56", [0.53, 0.52, 0.50, 0.49]),
    "double_r114_s83": _vane_table("double R114 S83", "double thickness, R 114, S 83", [0.27, 0.25, 0.24, 0.23]),
}

# ----------------------------------------------------------------------------
# I. Elbows, 90 deg, rectangular, Z-shaped (two mitered turns in one plane)
# L = distance between the two turns. Printed for W/H = 1 (see Note 4).
# ----------------------------------------------------------------------------

_DOUBLE_ELBOW_L = [
    0,
    0.4,
    0.6,
    0.8,
    1.0,
    1.2,
    1.4,
    1.6,
    1.8,
    2.0,
    2.4,
    2.8,
    3.2,
    4.0,
    5.0,
    6.0,
    7.0,
    9.0,
    10.0,
    INFINITY,
]

Z_SHAPED_RECT = LossTable(
    "14-10I",
    "Elbows, 90 deg, rectangular, Z-shaped",
    [("l_on_h", _DOUBLE_ELBOW_L)],
    [0, 0.62, 0.90, 1.6, 2.6, 3.6, 4.0, 4.2, 4.2, 4.2, 3.7, 3.3, 3.2, 3.1, 2.9, 2.8, 2.7, 2.6, 2.5, 2.3],
    REF_UPSTREAM,
    _RECT,
)

# ----------------------------------------------------------------------------
# J. Elbows, 90 deg, rectangular, in different planes
# ----------------------------------------------------------------------------

DIFFERENT_PLANES_RECT = LossTable(
    "14-10J",
    "Elbows, 90 deg, rectangular in different planes",
    [("l_on_w", _DOUBLE_ELBOW_L)],
    [1.2, 2.4, 2.9, 3.3, 3.4, 3.4, 3.4, 3.3, 3.2, 3.1, 3.2, 3.2, 3.2, 3.0, 2.9, 2.8, 2.7, 2.5, 2.4, 2.3],
    REF_UPSTREAM,
    _RECT,
)

# ----------------------------------------------------------------------------
# K. Elbows, 30 deg, round, offset (two 30 deg turns)
# L = length of the inclined piece between the turns.
# ----------------------------------------------------------------------------

OFFSET_30_ROUND = LossTable(
    "14-10K",
    "Elbows, 30 deg, round, offset",
    [("l_on_d", [0, 0.5, 1.0, 1.5, 2.0, 2.5, 3.0])],
    [0, 0.15, 0.15, 0.16, 0.16, 0.16, 0.16],
    REF_UPSTREAM,
    _ROUND,
)


# ----------------------------------------------------------------------------
# Lookups with their notes applied
# ----------------------------------------------------------------------------


def smooth_round(r_on_d, theta_deg=90.0):
    """14-10 A with the Note 1 angle factor."""
    base, factor = SMOOTH_ROUND.lookup(r_on_d), ANGLE_FACTOR.lookup(theta_deg)
    return combine(base.value * factor.value, base, factor)


def gored_round(pieces, r_on_d, theta_deg=90.0):
    """
    14-10 B, 3 to 5 piece round elbow. The table is for 90 deg; the Note 1
    angle factor is applied for other angles, which the source does not
    state for this fitting -- so any other angle is flagged as clamped.
    """
    base = GORED_ROUND.lookup(pieces, r_on_d)
    if abs(float(theta_deg) - 90.0) <= 1.0e-6:
        return base
    factor = ANGLE_FACTOR.lookup(theta_deg)
    return Lookup(value=base.value * factor.value, clamped=True, filled=base.filled or factor.filled)


def reynolds_factor_mitered(reynolds):
    """Notes 2 and 5. Above Re = 14e4 the factor is 1.0, which is the table's own last value, not a clamp."""
    re_1e4 = float(reynolds) / 1.0e4
    if re_1e4 >= 14.0:
        return REYNOLDS_FACTOR_MITERED.lookup(14.0)
    return REYNOLDS_FACTOR_MITERED.lookup(re_1e4)


def mitered_round(theta_deg, reynolds=None):
    """14-10 C with the Note 2 Reynolds correction (skipped when no Reynolds number is given)."""
    base = MITERED_ROUND.lookup(theta_deg)
    if reynolds is None:
        return base
    factor = reynolds_factor_mitered(reynolds)
    return combine(base.value * factor.value, base, factor)


def mitered_rect(h_on_w, theta_deg, reynolds=None):
    """14-10 D with the Note 2 Reynolds correction (skipped when no Reynolds number is given)."""
    base = MITERED_RECT.lookup(theta_deg, h_on_w)
    if reynolds is None:
        return base
    factor = reynolds_factor_mitered(reynolds)
    return combine(base.value * factor.value, base, factor)


def mitered_rect_size_change(h_on_w, w1_on_w, reynolds=None):
    """14-10 E with the Note 2 Reynolds correction."""
    base = MITERED_RECT_SIZE_CHANGE.lookup(h_on_w, w1_on_w)
    if reynolds is None:
        return base
    factor = reynolds_factor_mitered(reynolds)
    return combine(base.value * factor.value, base, factor)


def reynolds_factor_smooth_rect(r_on_w, reynolds):
    """Note 3. The two printed rows are R/W = 0.5 and R/W >= 0.75; from Re = 20e4 up the factor is 1.0."""
    re_1e4 = min(float(reynolds) / 1.0e4, 20.0)
    return REYNOLDS_FACTOR_SMOOTH_RECT.lookup(min(max(float(r_on_w), 0.5), 0.75), re_1e4)


def smooth_rect(h_on_w, r_on_w, reynolds, theta_deg=90.0):
    """14-10 F with the Note 3 Reynolds correction and the Note 1 angle factor."""
    base = SMOOTH_RECT.lookup(r_on_w, h_on_w)
    re_factor = reynolds_factor_smooth_rect(r_on_w, reynolds)
    angle = ANGLE_FACTOR.lookup(theta_deg)
    return combine(base.value * re_factor.value * angle.value, base, re_factor, angle)


def smooth_rect_splitter_vanes(vanes, throat_r_on_w, h_on_w, theta_deg=90.0):
    """14-10 G (1 to 3 splitter vanes; R is the throat radius) with the Note 1 angle factor."""
    base = SMOOTH_RECT_SPLITTER_VANES.lookup(vanes, throat_r_on_w, h_on_w)
    angle = ANGLE_FACTOR.lookup(theta_deg)
    return combine(base.value * angle.value, base, angle)


def mitered_rect_turning_vanes(vane_design, velocity_ms):
    """14-10 H. `vane_design` is one of the TURNING_VANES keys."""
    try:
        table = TURNING_VANES[vane_design]
    except KeyError:
        raise ValueError(
            "Unknown turning vane design '{}'. Known: {}".format(vane_design, ", ".join(sorted(TURNING_VANES)))
        ) from None
    return table.lookup(velocity_ms)


def z_shaped_rect(l_on_h, w_on_h=1.0, reynolds=None):
    """14-10 I with the Note 4 aspect factor and the Note 5 Reynolds correction."""
    base, aspect = Z_SHAPED_RECT.lookup(l_on_h), Z_ELBOW_ASPECT_FACTOR.lookup(w_on_h)
    lookups = [base, aspect]
    value = base.value * aspect.value
    if reynolds is not None:
        factor = reynolds_factor_mitered(reynolds)
        lookups.append(factor)
        value *= factor.value
    return combine(value, *lookups)


def different_planes_rect(l_on_w, w_on_h=1.0, reynolds=None):
    """14-10 J with the Note 4 aspect factor (printed against W/H) and the Note 5 Reynolds correction."""
    base, aspect = DIFFERENT_PLANES_RECT.lookup(l_on_w), Z_ELBOW_ASPECT_FACTOR.lookup(w_on_h)
    lookups = [base, aspect]
    value = base.value * aspect.value
    if reynolds is not None:
        factor = reynolds_factor_mitered(reynolds)
        lookups.append(factor)
        value *= factor.value
    return combine(value, *lookups)


def offset_30_round(l_on_d, reynolds=None):
    """14-10 K with the Note 5 Reynolds correction."""
    base = OFFSET_30_ROUND.lookup(l_on_d)
    if reynolds is None:
        return base
    factor = reynolds_factor_mitered(reynolds)
    return combine(base.value * factor.value, base, factor)
