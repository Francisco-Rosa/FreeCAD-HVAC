# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the HVAC addon.

"""
SMACNA Table 14-14: loss coefficients for diverging junctions (tees, wyes).

Every coefficient multiplies the velocity pressure of the UPSTREAM (common)
section. Subscripts: c = common (inlet), s = straight through (main outlet),
b = branch outlet.

Several branch tables are printed as a triangle (only flow splits that can
occur for a given velocity ratio). The cells outside it are blank, so a
lookup there is filled from the row and flagged.
"""

from .table import REF_UPSTREAM, LossTable, TableRows

_ROUND = ("Circular",)
_RECT = ("Rectangular",)
_BOTH = ("Circular", "Rectangular")

_Q_01_TO_09 = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]
_Q_01_TO_10 = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
_V_00_TO_20 = [0, 0.2, 0.4, 0.6, 0.8, 1.0, 1.2, 1.4, 1.6, 1.8, 2.0]
_V_02_TO_18 = [0.2, 0.4, 0.6, 0.8, 1.0, 1.2, 1.4, 1.6, 1.8]
_ = None  # a blank cell

# ----------------------------------------------------------------------------
# A. Tee or wye, 30 to 90 deg, round.
# Main: keyed by Vs/Vc. This is also the main coefficient the source refers
# to for most of the fittings below.
# Branch: one block per branch angle, keyed by Ab/Ac and the flow ratio Qb/Qc.
# ----------------------------------------------------------------------------

ROUND_MAIN = LossTable(
    "14-14A main",
    "Tee or wye, 30 to 90 deg, round: main",
    [("vs_on_vc", [0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.8, 1.0])],
    [0.35, 0.28, 0.22, 0.17, 0.13, 0.09, 0.06, 0.02, 0],
    REF_UPSTREAM,
    _BOTH,
)

ROUND_BRANCH = LossTable(
    "14-14A branch",
    "Tee or wye, 30 to 90 deg, round: branch",
    [
        ("theta_deg", [30, 45, 60, 90]),
        ("ab_on_ac", [0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1]),
        ("qb_on_qc", _Q_01_TO_09),
    ],
    [
        [
            [0.75, 0.55, 0.40, 0.28, 0.21, 0.16, 0.15, 0.16, 0.19],
            [0.72, 0.51, 0.36, 0.25, 0.18, 0.15, 0.16, 0.20, 0.26],
            [0.69, 0.46, 0.31, 0.21, 0.17, 0.16, 0.20, 0.28, 0.39],
            [0.65, 0.41, 0.26, 0.19, 0.18, 0.22, 0.32, 0.47, 0.67],
            [0.59, 0.33, 0.21, 0.20, 0.27, 0.40, 0.62, 0.92, 1.3],
            [0.55, 0.28, 0.24, 0.38, 0.76, 1.3, 2.0, _, _],
            [0.40, 0.26, 0.58, 1.3, 2.5, _, _, _, _],
            [0.28, 1.5, _, _, _, _, _, _, _],
        ],
        [
            [0.78, 0.62, 0.49, 0.40, 0.34, 0.31, 0.32, 0.35, 0.40],
            [0.77, 0.59, 0.47, 0.38, 0.34, 0.32, 0.35, 0.41, 0.50],
            [0.74, 0.56, 0.44, 0.37, 0.35, 0.36, 0.43, 0.54, 0.68],
            [0.71, 0.52, 0.41, 0.38, 0.40, 0.45, 0.59, 0.78, 1.0],
            [0.66, 0.47, 0.40, 0.43, 0.54, 0.69, 0.95, 1.3, 1.7],
            [0.66, 0.48, 0.52, 0.73, 1.2, 1.8, 2.7, _, _],
            [0.56, 0.56, 1.0, 1.8, _, _, _, _, _],
            [0.60, 2.1, _, _, _, _, _, _, _],
        ],
        [
            [0.83, 0.71, 0.62, 0.56, 0.52, 0.50, 0.53, 0.60, 0.68],
            [0.82, 0.69, 0.61, 0.56, 0.54, 0.54, 0.60, 0.70, 0.82],
            [0.81, 0.68, 0.60, 0.58, 0.58, 0.61, 0.72, 0.87, 1.1],
            [0.79, 0.66, 0.61, 0.62, 0.68, 0.76, 0.94, 1.2, 1.5],
            [0.76, 0.65, 0.65, 0.74, 0.89, 1.1, 1.4, 1.8, 2.3],
            [0.80, 0.75, 0.89, 1.2, 1.8, 2.6, 3.5, _, _],
            [0.77, 0.96, 1.6, 2.5, _, _, _, _, _],
            [1.0, 2.9, _, _, _, _, _, _, _],
        ],
        [
            [0.95, 0.92, 0.92, 0.93, 0.94, 0.95, 1.1, 1.2, 1.4],
            [0.95, 0.94, 0.95, 0.98, 1.0, 1.1, 1.2, 1.4, 1.6],
            [0.96, 0.97, 1.0, 1.1, 1.1, 1.2, 1.4, 1.7, 2.0],
            [0.97, 1.0, 1.1, 1.2, 1.4, 1.5, 1.8, 2.1, 2.5],
            [0.99, 1.1, 1.3, 1.5, 1.7, 2.0, 2.4, _, _],
            [1.1, 1.4, 1.8, 2.3, _, _, _, _, _],
            [1.3, 1.9, 2.9, _, _, _, _, _, _],
            [2.1, _, _, _, _, _, _, _, _],
        ],
    ],
    REF_UPSTREAM,
    _ROUND,
)

# ----------------------------------------------------------------------------
# B to L. Round tees and wyes with a conical tap and/or an elbow on the
# branch (Ac = As). Branch keyed by Vb/Vc; main: 14-14 A.
# ----------------------------------------------------------------------------


def _round_variant(letter, title, values):
    return LossTable(
        "14-14{}".format(letter), title + ": branch", [("vb_on_vc", _V_00_TO_20)], values, REF_UPSTREAM, _ROUND
    )


ROUND_BRANCH_VARIANTS = {
    "conical_tee_90": _round_variant(
        "B", "90 deg conical tee, round", [1.0, 0.85, 0.74, 0.62, 0.52, 0.42, 0.36, 0.32, 0.32, 0.37, 0.52]
    ),
    "conical_wye_45": _round_variant(
        "C", "45 deg conical wye, round", [1.0, 0.84, 0.61, 0.41, 0.27, 0.17, 0.12, 0.12, 0.14, 0.18, 0.27]
    ),
    "tee_90_rolled_45_elbow_45": _round_variant(
        "D",
        "90 deg tee, round, rolled 45 deg with 45 deg elbow, branch 90 deg to main",
        [1.0, 1.32, 1.51, 1.60, 1.65, 1.74, 1.87, 2.0, 2.2, 2.5, 2.7],
    ),
    "tee_90_elbow_90": _round_variant(
        "E",
        "90 deg tee, round, with 90 deg elbow, branch 90 deg to main",
        [1.0, 1.03, 1.08, 1.18, 1.33, 1.56, 1.86, 2.2, 2.6, 3.0, 3.4],
    ),
    "tee_90_rolled_45_elbow_60": _round_variant(
        "F",
        "90 deg tee, round, rolled 45 deg with 60 deg elbow, branch 45 deg to main",
        [1.0, 1.06, 1.15, 1.29, 1.45, 1.65, 1.89, 2.2, 2.5, 2.9, 3.3],
    ),
    "conical_tee_90_rolled_45_elbow_45": _round_variant(
        "G",
        "90 deg conical tee, round, rolled 45 deg with 45 deg elbow, branch 90 deg to main",
        [1.0, 0.94, 0.88, 0.84, 0.80, 0.82, 0.84, 0.87, 0.90, 0.95, 1.02],
    ),
    "conical_tee_90_rolled_45_elbow_60": _round_variant(
        "H",
        "90 deg conical tee, round, rolled 45 deg with 60 deg elbow, branch 45 deg to main",
        [1.0, 0.95, 0.90, 0.86, 0.81, 0.79, 0.79, 0.81, 0.86, 0.96, 1.10],
    ),
    "wye_45_rolled_45_elbow_60": _round_variant(
        "I",
        "45 deg wye, round, rolled 45 deg with 60 deg elbow, branch 90 deg to main",
        [1.0, 0.88, 0.77, 0.68, 0.65, 0.69, 0.73, 0.88, 1.14, 1.54, 2.2],
    ),
    "conical_wye_45_rolled_45_elbow_60": _round_variant(
        "J",
        "45 deg conical wye, round, rolled 45 deg with 60 deg elbow, branch 90 deg to main",
        [1.0, 0.82, 0.63, 0.52, 0.45, 0.42, 0.41, 0.40, 0.41, 0.45, 0.56],
    ),
    "wye_45_rolled_45_elbow_30": _round_variant(
        "K",
        "45 deg wye, round, rolled 45 deg with 30 deg elbow, branch 45 deg to main",
        [1.0, 0.84, 0.72, 0.62, 0.54, 0.50, 0.56, 0.71, 0.92, 1.22, 1.66],
    ),
    "conical_wye_45_rolled_45_elbow_30": _round_variant(
        "L",
        "45 deg conical wye, round, rolled 45 deg with 30 deg elbow, branch 45 deg to main",
        [1.0, 0.93, 0.71, 0.55, 0.44, 0.42, 0.42, 0.44, 0.47, 0.54, 0.62],
    ),
}

# ----------------------------------------------------------------------------
# M. 45 deg wye, conical main and branch with 45 deg elbow, branch 90 deg to
# main. It has its own main coefficient.
# ----------------------------------------------------------------------------

WYE_CONICAL_MAIN_AND_BRANCH_BRANCH = LossTable(
    "14-14M branch",
    "45 deg wye, conical main and branch with 45 deg elbow: branch",
    [("vb_on_vc", [0.2, 0.4, 0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.4, 1.6, 1.8, 2.0, 2.2, 2.4, 2.6, 2.8, 3.0])],
    [0.76, 0.60, 0.52, 0.50, 0.51, 0.52, 0.56, 0.61, 0.68, 0.86, 1.1, 1.4, 1.8, 2.2, 2.6, 3.1, 3.7, 4.2],
    REF_UPSTREAM,
    _ROUND,
)

WYE_CONICAL_MAIN_AND_BRANCH_MAIN = LossTable(
    "14-14M main",
    "45 deg wye, conical main and branch with 45 deg elbow: main",
    [("vs_on_vc", [0.2, 0.4, 0.6, 0.8, 1.0, 1.2, 1.4, 1.6, 1.8, 2.0])],
    [0.14, 0.06, 0.05, 0.09, 0.18, 0.30, 0.46, 0.64, 0.84, 1.0],
    REF_UPSTREAM,
    _ROUND,
)

# ----------------------------------------------------------------------------
# N, P, Q, R, S, T. Tees out of a rectangular main (Ac = As). Branch keyed
# by Vb/Vc and Qb/Qc, printed as a triangle. Main: 14-14 A, except P and R
# (with damper), whose main is the one printed under S.
# ----------------------------------------------------------------------------


def _triangle(letter, title, rows):
    """A triangular branch table: row i (Vb/Vc) has i + 1 printed cells; the rest of the row is blank."""
    values = [list(row) + [None] * (len(_Q_01_TO_09) - len(row)) for row in rows]
    return LossTable(
        "14-14{}".format(letter),
        title + ": branch",
        [("vb_on_vc", _V_02_TO_18), ("qb_on_qc", _Q_01_TO_09)],
        values,
        REF_UPSTREAM,
        _RECT,
    )


RECT_MAIN_TEE_BRANCH = {
    "rect_branch_45_entry": _triangle(
        "N",
        "Tee, 45 deg entry, rectangular main and branch",
        [
            [0.91],
            [0.81, 0.79],
            [0.77, 0.72, 0.70],
            [0.78, 0.73, 0.69, 0.66],
            [0.78, 0.98, 0.85, 0.79, 0.74],
            [0.90, 1.11, 1.16, 1.23, 1.03, 0.86],
            [1.19, 1.22, 1.26, 1.29, 1.54, 1.25, 0.92],
            [1.35, 1.42, 1.55, 1.59, 1.63, 1.50, 1.31, 1.09],
            [1.44, 1.50, 1.75, 1.74, 1.72, 2.24, 1.63, 1.40, 1.17],
        ],
    ),
    "rect_branch_45_entry_damper": _triangle(
        "P",
        "Tee, 45 deg entry, rectangular main and branch with damper",
        [
            [0.61],
            [0.46, 0.61],
            [0.43, 0.50, 0.54],
            [0.39, 0.43, 0.62, 0.53],
            [0.34, 0.57, 0.77, 0.73, 0.68],
            [0.37, 0.64, 0.85, 0.98, 1.07, 0.83],
            [0.57, 0.71, 1.04, 1.16, 1.54, 1.36, 1.18],
            [0.89, 1.08, 1.28, 1.30, 1.69, 2.09, 1.81, 1.47],
            [1.33, 1.34, 2.04, 1.78, 1.90, 2.40, 2.77, 2.23, 1.92],
        ],
    ),
    "rect_branch": _triangle(
        "Q",
        "Tee, rectangular main and branch",
        [
            [1.03],
            [1.04, 1.01],
            [1.11, 1.03, 1.05],
            [1.16, 1.21, 1.17, 1.12],
            [1.38, 1.40, 1.30, 1.36, 1.27],
            [1.52, 1.61, 1.68, 1.91, 1.47, 1.66],
            [1.79, 2.01, 1.90, 2.31, 2.28, 2.20, 1.95],
            [2.07, 2.28, 2.13, 2.71, 2.99, 2.81, 2.09, 2.20],
            [2.32, 2.54, 2.64, 3.09, 3.72, 3.48, 2.21, 2.29, 2.57],
        ],
    ),
    "rect_branch_damper": _triangle(
        "R",
        "Tee, rectangular main and branch with damper",
        [
            [0.58],
            [0.67, 0.64],
            [0.78, 0.76, 0.75],
            [0.88, 0.98, 0.81, 1.01],
            [1.12, 1.05, 1.08, 1.18, 1.29],
            [1.49, 1.48, 1.40, 1.51, 1.70, 1.91],
            [2.10, 2.21, 2.25, 2.29, 2.32, 2.48, 2.53],
            [2.72, 3.30, 2.84, 3.09, 3.30, 3.19, 3.29, 3.16],
            [3.42, 4.58, 3.65, 3.92, 4.20, 4.15, 4.14, 4.10, 4.05],
        ],
    ),
    "rect_branch_extractor": _triangle(
        "S",
        "Tee, rectangular main and branch with extractor",
        [
            [0.60],
            [0.62, 0.69],
            [0.74, 0.80, 0.82],
            [0.99, 1.10, 0.95, 0.90],
            [1.48, 1.12, 1.41, 1.24, 1.21],
            [1.91, 1.33, 1.43, 1.52, 1.55, 1.64],
            [2.47, 1.67, 1.70, 2.04, 1.86, 1.98, 2.47],
            [3.17, 2.40, 2.33, 2.53, 2.31, 2.51, 3.13, 3.25],
            [3.85, 3.37, 2.89, 3.23, 3.09, 3.03, 3.30, 3.74, 4.11],
        ],
    ),
    "round_branch": _triangle(
        "T",
        "Tee, rectangular main to round branch",
        [
            [1.00],
            [1.01, 1.07],
            [1.14, 1.10, 1.08],
            [1.18, 1.31, 1.12, 1.13],
            [1.30, 1.38, 1.20, 1.23, 1.26],
            [1.46, 1.58, 1.45, 1.31, 1.39, 1.48],
            [1.70, 1.82, 1.65, 1.51, 1.56, 1.64, 1.71],
            [1.93, 2.06, 2.00, 1.85, 1.70, 1.76, 1.80, 1.88],
            [2.06, 2.17, 2.20, 2.13, 2.06, 1.98, 1.99, 2.00, 2.07],
        ],
    ),
}

# The kinds whose main coefficient is the extractor one (14-14 S main), as the source states.
_EXTRACTOR_MAIN_KINDS = {"rect_branch_45_entry_damper", "rect_branch_damper", "rect_branch_extractor"}

# S main: keyed by Vb/Vc.
EXTRACTOR_MAIN = LossTable(
    "14-14S main",
    "Tee, rectangular main and branch with extractor: main",
    [("vb_on_vc", _V_02_TO_18)],
    [0.03, 0.04, 0.07, 0.12, 0.13, 0.14, 0.27, 0.30, 0.25],
    REF_UPSTREAM,
    _RECT,
)

# ----------------------------------------------------------------------------
# U. Wye, rectangular (Ac = As + Ab), branch at 15 to 90 deg.
# Y prints the same branch coefficients for a symmetric two-branch wye.
# ----------------------------------------------------------------------------

_WYE_V = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.8, 1.0, 1.2, 1.4, 1.6, 1.8, 2.0]
_WYE_BRANCH_VALUES = [
    [0.81, 0.65, 0.51, 0.38, 0.28, 0.20, 0.11, 0.06, 0.14, 0.30, 0.51, 0.76, 1.0],
    [0.84, 0.69, 0.56, 0.44, 0.34, 0.26, 0.19, 0.15, 0.15, 0.30, 0.51, 0.76, 1.0],
    [0.87, 0.74, 0.63, 0.54, 0.45, 0.38, 0.29, 0.24, 0.23, 0.30, 0.51, 0.76, 1.0],
    [0.90, 0.82, 0.79, 0.66, 0.59, 0.53, 0.43, 0.36, 0.33, 0.39, 0.51, 0.76, 1.0],
    [1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0],
]

WYE_RECT_ANGLED_BRANCH = LossTable(
    "14-14U branch",
    "Wye, rectangular: branch",
    [("theta_deg", [15, 30, 45, 60, 90]), ("vb_on_vc", _WYE_V)],
    _WYE_BRANCH_VALUES,
    REF_UPSTREAM,
    _RECT,
)

_WYE_MAIN_V = [0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.8, 1.0, 1.2, 1.4, 1.6, 1.8, 2.0]
_WYE_MAIN_BASE = [1.0, 0.81, 0.64, 0.50, 0.36, 0.25, 0.16, 0.04, 0, 0.07, 0.39, 0.90, 1.8, 3.2]

# Main, branch at 15 to 60 deg: one column for every As/Ac.
WYE_RECT_ANGLED_MAIN = LossTable(
    "14-14U main",
    "Wye, rectangular: main, branch at 15 to 60 deg",
    [("vs_on_vc", _WYE_MAIN_V)],
    _WYE_MAIN_BASE,
    REF_UPSTREAM,
    _RECT,
)

# Main, branch at 90 deg: columns for As/Ac 0-0.4, 0.5, 0.6, 0.7 and >= 0.8.
WYE_RECT_ANGLED_MAIN_90 = LossTable(
    "14-14U main 90",
    "Wye, rectangular: main, branch at 90 deg",
    [("as_on_ac", [0.4, 0.5, 0.6, 0.7, 0.8]), ("vs_on_vc", _WYE_MAIN_V)],
    [
        _WYE_MAIN_BASE,
        [1.0, 0.81, 0.64, 0.52, 0.40, 0.30, 0.23, 0.17, 0.20, 0.36, 0.79, 1.4, 2.4, 4.0],
        [1.0, 0.81, 0.64, 0.52, 0.38, 0.28, 0.20, 0.10, 0.10, 0.21, 0.59, 1.2, _, _],
        [1.0, 0.81, 0.64, 0.50, 0.37, 0.27, 0.18, 0.07, 0.05, 0.14, 0.39, _, _, _],
        [1.0, 0.81, 0.64, 0.50, 0.36, 0.25, 0.16, 0.04, 0, 0.07, _, _, _, _],
    ],
    REF_UPSTREAM,
    _RECT,
)

# ----------------------------------------------------------------------------
# V. Tee, rectangular main to conical branch. Main: 14-14 A.
# ----------------------------------------------------------------------------

TEE_RECT_MAIN_CONICAL_BRANCH = LossTable(
    "14-14V",
    "Tee, rectangular main to conical branch: branch",
    [("vb_on_vc", [0.40, 0.50, 0.75, 1.0, 1.3, 1.5])],
    [0.80, 0.83, 0.90, 1.0, 1.1, 1.4],
    REF_UPSTREAM,
    _RECT,
)

# ----------------------------------------------------------------------------
# W. Wye, rectangular, radius branch (R/W = 1.0, 90 deg branch). Each row is
# one specific fitting, identified by (Ab/As, Ab/Ac).
# ----------------------------------------------------------------------------


def _wye_rect_row(part, key, values):
    return (
        key,
        LossTable(
            "14-14W {} {}/{}".format(part, *key),
            "Wye, rectangular, radius branch: {}".format(part),
            [("qb_on_qc", _Q_01_TO_09)],
            values,
            REF_UPSTREAM,
            _RECT,
        ),
    )


WYE_RECT_RADIUS_BRANCH = TableRows(
    ("ab_on_as", "ab_on_ac"),
    [
        _wye_rect_row("branch", (0.25, 0.25), [0.55, 0.50, 0.60, 0.85, 1.2, 1.8, 3.1, 4.4, 6.0]),
        _wye_rect_row("branch", (0.33, 0.25), [0.35, 0.35, 0.50, 0.80, 1.3, 2.0, 2.8, 3.8, 5.0]),
        _wye_rect_row("branch", (0.5, 0.5), [0.62, 0.48, 0.40, 0.40, 0.48, 0.60, 0.78, 1.1, 1.5]),
        _wye_rect_row("branch", (0.67, 0.5), [0.52, 0.40, 0.32, 0.30, 0.34, 0.44, 0.62, 0.92, 1.4]),
        _wye_rect_row("branch", (1.0, 0.5), [0.44, 0.38, 0.38, 0.41, 0.52, 0.68, 0.92, 1.2, 1.6]),
        _wye_rect_row("branch", (1.0, 1.0), [0.67, 0.55, 0.46, 0.37, 0.32, 0.29, 0.29, 0.30, 0.37]),
        _wye_rect_row("branch", (1.33, 1.0), [0.70, 0.60, 0.51, 0.42, 0.34, 0.28, 0.26, 0.26, 0.29]),
        _wye_rect_row("branch", (2.0, 1.0), [0.60, 0.52, 0.43, 0.33, 0.24, 0.17, 0.15, 0.17, 0.21]),
    ],
)

WYE_RECT_RADIUS_MAIN = TableRows(
    ("ab_on_as", "ab_on_ac"),
    [
        _wye_rect_row("main", (0.25, 0.25), [-0.01, -0.03, -0.01, 0.05, 0.13, 0.21, 0.29, 0.38, 0.46]),
        _wye_rect_row("main", (0.33, 0.25), [0.08, 0, -0.02, -0.01, 0.02, 0.08, 0.16, 0.24, 0.34]),
        _wye_rect_row("main", (0.5, 0.5), [-0.03, -0.06, -0.05, 0, 0.06, 0.12, 0.19, 0.27, 0.35]),
        _wye_rect_row("main", (0.67, 0.5), [0.04, -0.02, -0.04, -0.03, -0.01, 0.04, 0.12, 0.23, 0.37]),
        _wye_rect_row("main", (1.0, 0.5), [0.72, 0.48, 0.28, 0.13, 0.05, 0.04, 0.09, 0.18, 0.30]),
        _wye_rect_row("main", (1.0, 1.0), [-0.02, -0.04, -0.04, -0.01, 0.06, 0.13, 0.22, 0.30, 0.38]),
        _wye_rect_row("main", (1.33, 1.0), [0.10, 0, 0.01, -0.03, -0.01, 0.03, 0.10, 0.20, 0.30]),
        _wye_rect_row("main", (2.0, 1.0), [0.62, 0.38, 0.23, 0.13, 0.08, 0.05, 0.06, 0.10, 0.20]),
    ],
)

# ----------------------------------------------------------------------------
# X. Symmetrical wye, dovetail, rectangular (R/W = 1.5, equal flows).
# ----------------------------------------------------------------------------

WYE_DOVETAIL_RECT = LossTable(
    "14-14X",
    "Symmetrical wye, dovetail, rectangular (diverging)",
    [("ab_on_ac", [0.50, 1.0])],
    [0.30, 0.25],
    REF_UPSTREAM,
    _RECT,
)

# ----------------------------------------------------------------------------
# Y. Wye, rectangular and round: two equal branches (A1b = A2b,
# Ac = A1b + A2b), each at angle theta. Keyed by that branch's own velocity ratio.
# ----------------------------------------------------------------------------

WYE_SYMMETRIC = LossTable(
    "14-14Y",
    "Wye, rectangular and round, symmetric (diverging)",
    [("theta_deg", [15, 30, 45, 60, 90]), ("v_branch_on_vc", _WYE_V)],
    _WYE_BRANCH_VALUES,
    REF_UPSTREAM,
    _BOTH,
)

# ----------------------------------------------------------------------------
# Z. Tee, rectangular reducing, 45 deg entry branch (As/Ac and Ab/Ac from 0.5 to 1.0).
# ----------------------------------------------------------------------------

TEE_RECT_REDUCING_BRANCH = LossTable(
    "14-14Z branch",
    "Tee, rectangular reducing, 45 deg entry branch: branch",
    [("qb_on_qc", _Q_01_TO_10)],
    [1.16, 0.96, 0.82, 0.68, 0.56, 0.49, 0.47, 0.48, 0.50, 0.54],
    REF_UPSTREAM,
    _RECT,
)

TEE_RECT_REDUCING_MAIN = LossTable(
    "14-14Z main",
    "Tee, rectangular reducing, 45 deg entry branch: main",
    [("qs_on_qc", _Q_01_TO_10)],
    [0.21, 0.20, 0.20, 0.20, 0.20, 0.20, 0.22, 0.25, 0.35, 0.53],
    REF_UPSTREAM,
    _RECT,
)


# ----------------------------------------------------------------------------
# Lookups
# ----------------------------------------------------------------------------


def _unknown(kind, known, what):
    return ValueError("Unknown {} '{}'. Known: {}".format(what, kind, ", ".join(sorted(known))))


def round_main(vs_on_vc):
    """14-14 A main coefficient (also used by most other diverging fittings)."""
    return ROUND_MAIN.lookup(vs_on_vc)


def round_tee_or_wye(theta_deg, ab_on_ac, qb_on_qc, vs_on_vc):
    """14-14 A: (branch, main) of a plain round tee/wye with the branch at 30 to 90 deg."""
    return ROUND_BRANCH.lookup(theta_deg, ab_on_ac, qb_on_qc), round_main(vs_on_vc)


def round_variant(kind, vb_on_vc, vs_on_vc):
    """14-14 B to L: (branch, main) of a round tee/wye variant. `kind` is one of the ROUND_BRANCH_VARIANTS keys."""
    try:
        table = ROUND_BRANCH_VARIANTS[kind]
    except KeyError:
        raise _unknown(kind, ROUND_BRANCH_VARIANTS, "round tee/wye variant") from None
    return table.lookup(vb_on_vc), round_main(vs_on_vc)


def wye_conical_main_and_branch(vb_on_vc, vs_on_vc):
    """14-14 M: (branch, main)."""
    return WYE_CONICAL_MAIN_AND_BRANCH_BRANCH.lookup(vb_on_vc), WYE_CONICAL_MAIN_AND_BRANCH_MAIN.lookup(vs_on_vc)


def tee_rect_main(kind, vb_on_vc, qb_on_qc, vs_on_vc):
    """
    14-14 N, P, Q, R, S, T: (branch, main) of a tee out of a rectangular
    main. `kind` is one of the RECT_MAIN_TEE_BRANCH keys. The main
    coefficient is 14-14 A, or the extractor one for the damper/extractor kinds.
    """
    try:
        table = RECT_MAIN_TEE_BRANCH[kind]
    except KeyError:
        raise _unknown(kind, RECT_MAIN_TEE_BRANCH, "rectangular-main tee") from None
    main = EXTRACTOR_MAIN.lookup(vb_on_vc) if kind in _EXTRACTOR_MAIN_KINDS else round_main(vs_on_vc)
    return table.lookup(vb_on_vc, qb_on_qc), main


def wye_rect_angled(theta_deg, vb_on_vc, vs_on_vc, as_on_ac):
    """
    14-14 U: (branch, main) of a rectangular wye with the branch at 15 to 90
    deg. The main coefficient has one printed column for 15 to 60 deg and a
    set of As/Ac columns for 90 deg; between 60 and 90 deg it is
    interpolated between the two.
    """
    branch = WYE_RECT_ANGLED_BRANCH.lookup(theta_deg, vb_on_vc)
    general = WYE_RECT_ANGLED_MAIN.lookup(vs_on_vc)
    if float(theta_deg) <= 60.0:
        return branch, general
    # As/Ac at or below 0.4 reads the first printed column, at or above 0.8 the last: both as printed.
    at_90 = WYE_RECT_ANGLED_MAIN_90.lookup(min(max(float(as_on_ac), 0.4), 0.8), vs_on_vc)
    fraction = min((float(theta_deg) - 60.0) / 30.0, 1.0)
    value = general.value + fraction * (at_90.value - general.value)
    return branch, type(at_90)(value, general.clamped or at_90.clamped, general.filled or at_90.filled)


def tee_rect_main_conical_branch(vb_on_vc, vs_on_vc):
    """14-14 V: (branch, main)."""
    return TEE_RECT_MAIN_CONICAL_BRANCH.lookup(vb_on_vc), round_main(vs_on_vc)


def wye_rect_radius(ab_on_as, ab_on_ac, qb_on_qc):
    """14-14 W: (branch, main) of a rectangular wye with a radius branch, from the nearest printed fitting."""
    key = (ab_on_as, ab_on_ac)
    return WYE_RECT_RADIUS_BRANCH.lookup(key, qb_on_qc), WYE_RECT_RADIUS_MAIN.lookup(key, qb_on_qc)


def wye_dovetail_rect(ab_on_ac):
    """14-14 X: the coefficient of either branch of a symmetric dovetail wye (equal flows)."""
    return WYE_DOVETAIL_RECT.lookup(ab_on_ac)


def wye_symmetric(theta_deg, v_branch_on_vc):
    """14-14 Y: the coefficient of one branch of a symmetric two-branch wye."""
    return WYE_SYMMETRIC.lookup(theta_deg, v_branch_on_vc)


def tee_rect_reducing(qb_on_qc, qs_on_qc):
    """14-14 Z: (branch, main)."""
    return TEE_RECT_REDUCING_BRANCH.lookup(qb_on_qc), TEE_RECT_REDUCING_MAIN.lookup(qs_on_qc)
