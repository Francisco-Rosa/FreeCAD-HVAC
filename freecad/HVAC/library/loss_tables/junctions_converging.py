# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the HVAC addon.

"""
SMACNA Table 14-13: loss coefficients for converging junctions (tees, wyes).

Every coefficient multiplies the velocity pressure of the DOWNSTREAM
(common, combined) section. Subscripts: c = common (outlet), s = straight
through (main inlet), b = branch inlet. A negative coefficient means the
leg gains pressure from the other stream.

Suspected misprints, kept exactly as printed:
- 14-13 A main, Vs/Vc = 1.0, Ab/Ac = 0.4: 0.10 (its neighbours are 0 and 0.02).
- 14-13 E main, As/Ac = 0.3, Ab/Ac = 0.2, Qb/Qs = 0.4: -0.01 (between 5.3 and 2.0).
- 14-13 E main, As/Ac = 0.5, Ab/Ac = 0.2, Qb/Qs = 1.4: 1.3 (the row runs -1.1 ... -1.5).
"""

from .table import REF_DOWNSTREAM, LossTable, TableFamily, TableRows

_ROUND = ("Circular",)
_RECT = ("Rectangular",)

_Q_01_TO_10 = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
_Q_01_TO_09 = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]
_AREA_7 = [0.1, 0.2, 0.3, 0.4, 0.6, 0.8, 1.0]

# ----------------------------------------------------------------------------
# A. Converging wye, round, 45 deg. Keyed by VELOCITY ratios.
# ----------------------------------------------------------------------------

WYE_45_ROUND_BRANCH = LossTable(
    "14-13A branch",
    "Converging wye, round, 45 deg: branch",
    [("vb_on_vc", [0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.5, 2.0, 2.5, 3.0]), ("ab_on_ac", _AREA_7)],
    [
        [-0.56, -0.44, -0.35, -0.28, -0.15, -0.04, 0.05],
        [-0.48, -0.37, -0.28, -0.21, -0.09, 0.02, 0.11],
        [-0.38, -0.27, -0.19, -0.12, 0, 0.10, 0.18],
        [-0.26, -0.16, -0.08, -0.01, 0.10, 0.20, 0.28],
        [-0.21, -0.02, 0.05, 0.12, 0.23, 0.32, 0.40],
        [0.04, 0.13, 0.21, 0.27, 0.37, 0.46, 0.53],
        [0.22, 0.31, 0.38, 0.44, 0.53, 0.62, 0.69],
        [1.4, 1.5, 1.5, 1.6, 1.7, 1.7, 1.8],
        [3.1, 3.2, 3.2, 3.2, 3.3, 3.3, 3.3],
        [5.3, 5.3, 5.3, 5.4, 5.4, 5.4, 5.4],
        [8.0, 8.0, 8.0, 8.0, 8.0, 8.0, 8.0],
    ],
    REF_DOWNSTREAM,
    _ROUND,
)

WYE_45_ROUND_MAIN = LossTable(
    "14-13A main",
    "Converging wye, round, 45 deg: main",
    [("vs_on_vc", _Q_01_TO_10), ("ab_on_ac", _AREA_7)],
    [
        [-8.6, -4.1, -2.5, -1.7, -0.97, -0.58, -0.34],
        [-6.7, -3.1, -1.9, -1.3, -0.67, -0.36, -0.18],
        [-5.0, -2.2, -1.3, -0.88, -0.42, -0.19, -0.05],
        [-3.5, -1.5, -0.88, -0.55, -0.21, -0.05, 0.05],
        [-2.3, -0.95, -0.51, -0.28, -0.06, 0.06, 0.13],
        [-1.3, -0.50, -0.22, -0.09, 0.05, 0.12, 0.17],
        [-0.63, -0.18, -0.03, 0.04, 0.12, 0.16, 0.18],
        [-0.18, 0.01, 0.07, 0.10, 0.13, 0.15, 0.17],
        [0.03, 0.07, 0.08, 0.09, 0.10, 0.11, 0.13],
        [-0.01, 0, 0, 0.10, 0.02, 0.04, 0.05],
    ],
    REF_DOWNSTREAM,
    _ROUND,
)

# ----------------------------------------------------------------------------
# B. Converging tee, 90 deg, round (As = Ac). Keyed by the FLOW ratio Qb/Qc.
# Its main coefficient is also the one the source refers to for the
# rectangular tees C, D and F below.
# ----------------------------------------------------------------------------

TEE_90_ROUND_BRANCH = LossTable(
    "14-13B branch",
    "Converging tee, 90 deg, round: branch",
    [("qb_on_qc", _Q_01_TO_10), ("ab_on_ac", _AREA_7)],
    [
        [0.40, -0.37, -0.51, -0.46, -0.50, -0.51, -0.52],
        [3.8, 0.72, 0.17, -0.02, -0.14, -0.18, -0.24],
        [9.2, 2.3, 1.0, 0.44, 0.21, 0.11, -0.08],
        [16, 4.3, 2.1, 0.94, 0.54, 0.40, 0.32],
        [26, 6.8, 3.2, 1.1, 0.66, 0.49, 0.42],
        [37, 9.7, 4.7, 1.6, 0.92, 0.69, 0.57],
        [43, 13, 6.3, 2.1, 1.2, 0.88, 0.72],
        [65, 17, 7.9, 2.7, 1.5, 1.1, 0.86],
        [82, 21, 9.7, 3.4, 1.8, 1.2, 0.99],
        [101, 26, 12, 4.0, 2.1, 1.4, 1.1],
    ],
    REF_DOWNSTREAM,
    _ROUND,
)

TEE_90_MAIN = LossTable(
    "14-13B main",
    "Converging tee, 90 deg: main",
    [("qb_on_qc", _Q_01_TO_10)],
    [0.16, 0.27, 0.38, 0.46, 0.53, 0.57, 0.59, 0.60, 0.59, 0.55],
    REF_DOWNSTREAM,
    ("Circular", "Rectangular"),
)

# ----------------------------------------------------------------------------
# C, D, F. Converging tees into a rectangular main. Each is printed for one
# set of area ratios only (Ab/As = 0.5, As/Ac = 1.0, Ab/Ac = 0.5), with one
# row for a common-duct velocity below 6 m/s and one above. Main: 14-13 B.
# ----------------------------------------------------------------------------

# The area ratios these three fittings are printed for: (Ab/As, As/Ac, Ab/Ac).
RECT_TEE_AREA_RATIOS = (0.5, 1.0, 0.5)
RECT_TEE_VELOCITY_SPLIT_MS = 6.0


def _velocity_pair(letter, title, low, high):
    """The two printed rows of a rectangular-main tee: (Vc < 6 m/s, Vc > 6 m/s)."""
    return tuple(
        LossTable(
            "14-13{} branch {}".format(letter, label),
            "{}: branch, Vc {} 6 m/s".format(title, sign),
            [("qb_on_qc", _Q_01_TO_10)],
            values,
            REF_DOWNSTREAM,
            _RECT,
        )
        for label, sign, values in (("slow", "<", low), ("fast", ">", high))
    )


TEE_ROUND_BRANCH_RECT_MAIN = _velocity_pair(
    "C",
    "Converging tee, round branch to rectangular main",
    [-0.63, -0.55, 0.13, 0.23, 0.78, 1.30, 1.93, 3.10, 4.88, 5.60],
    [-0.49, -0.21, 0.23, 0.60, 1.27, 2.06, 2.75, 3.70, 4.93, 5.95],
)

TEE_RECT = _velocity_pair(
    "D",
    "Converging tee, rectangular main and branch",
    [-0.75, -0.53, -0.03, 0.33, 1.03, 1.10, 2.15, 2.93, 4.18, 4.78],
    [-0.69, -0.21, 0.23, 0.67, 1.17, 1.66, 2.67, 3.36, 3.93, 5.13],
)

TEE_RECT_45_ENTRY = _velocity_pair(
    "F",
    "Converging tee, 45 deg entry branch to rectangular main",
    [-0.83, -0.68, -0.30, 0.28, 0.55, 1.03, 1.50, 1.93, 2.50, 3.03],
    [-0.72, -0.52, -0.23, 0.34, 0.76, 1.14, 1.83, 2.01, 2.90, 3.63],
)

RECT_MAIN_TEES = {
    "round_branch": TEE_ROUND_BRANCH_RECT_MAIN,
    "rect_branch": TEE_RECT,
    "rect_branch_45_entry": TEE_RECT_45_ENTRY,
}

# ----------------------------------------------------------------------------
# E. Converging wye, conical, round, 45 deg. One block per As/Ac, each with
# its own Ab/Ac rows; keyed by the flow ratio Qb/Qs (branch over straight).
# ----------------------------------------------------------------------------

_QB_ON_QS = [0.2, 0.4, 0.6, 0.8, 1.0, 1.2, 1.4, 1.6, 1.8, 2.0]


def _conical_block(part, as_on_ac, ab_on_ac, values):
    return LossTable(
        "14-13E {} As/Ac {}".format(part, as_on_ac),
        "Converging wye, conical, round: {}, As/Ac = {}".format(part, as_on_ac),
        [("ab_on_ac", ab_on_ac), ("qb_on_qs", _QB_ON_QS)],
        values,
        REF_DOWNSTREAM,
        _ROUND,
    )


WYE_CONICAL_ROUND_BRANCH = TableFamily(
    "as_on_ac",
    {
        0.3: _conical_block(
            "branch",
            0.3,
            [0.2, 0.3],
            [
                [-2.4, -0.01, 2.0, 3.8, 5.3, 6.6, 7.8, 8.9, 9.8, 11],
                [-2.8, -1.2, 0.12, 1.1, 1.9, 2.6, 3.2, 3.7, 4.2, 4.6],
            ],
        ),
        0.4: _conical_block(
            "branch",
            0.4,
            [0.2, 0.3, 0.4],
            [
                [-1.2, 0.93, 2.8, 4.5, 5.9, 7.2, 8.4, 9.5, 10, 11],
                [-1.6, -0.27, 0.81, 1.7, 2.4, 3.0, 3.6, 4.1, 4.5, 4.9],
                [-1.8, -0.72, 0.07, 0.66, 1.1, 1.5, 1.8, 2.1, 2.3, 2.5],
            ],
        ),
        0.5: _conical_block(
            "branch",
            0.5,
            [0.2, 0.3, 0.4, 0.5],
            [
                [-0.46, 1.5, 3.3, 4.9, 6.4, 7.7, 8.8, 9.9, 11, 12],
                [-0.94, 0.25, 1.2, 2.0, 2.7, 3.3, 3.8, 4.2, 4.7, 5.0],
                [-1.1, -0.24, 0.42, 0.92, 1.3, 1.6, 1.9, 2.1, 2.3, 2.5],
                [-1.2, -0.38, 0.18, 0.58, 0.88, 1.1, 1.3, 1.5, 1.6, 1.7],
            ],
        ),
        0.6: _conical_block(
            "branch",
            0.6,
            [0.2, 0.3, 0.4, 0.5, 0.6],
            [
                [-0.55, 1.3, 3.1, 4.7, 6.1, 7.4, 8.6, 9.6, 11, 12],
                [-1.1, 0, 0.88, 1.6, 2.3, 2.8, 3.3, 3.7, 4.1, 4.5],
                [-1.2, -0.48, 0.10, 0.54, 0.89, 1.2, 1.4, 1.6, 1.8, 2.0],
                [-1.3, -0.62, -0.14, 0.21, 0.47, 0.68, 0.85, 0.99, 1.1, 1.2],
                [-1.3, -0.69, -0.26, 0.04, 0.26, 0.42, 0.57, 0.66, 0.75, 0.82],
            ],
        ),
        0.8: _conical_block(
            "branch",
            0.8,
            [0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8],
            [
                [0.06, 1.8, 3.5, 5.1, 6.5, 7.8, 8.9, 10, 11, 12],
                [-0.52, 0.35, 1.1, 1.7, 2.3, 2.8, 3.2, 3.6, 3.9, 4.2],
                [-0.67, -0.05, 0.43, 0.80, 1.1, 1.4, 1.6, 1.8, 1.9, 2.1],
                [-0.73, -0.19, 0.18, 0.46, 0.68, 0.85, 0.99, 1.1, 1.2, 1.3],
                [-0.75, -0.27, 0.05, 0.28, 0.45, 0.58, 0.68, 0.76, 0.83, 0.88],
                [-0.77, -0.31, -0.02, 0.18, 0.32, 0.43, 0.50, 0.56, 0.61, 0.65],
                [-0.78, -0.34, -0.07, 0.12, 0.24, 0.33, 0.39, 0.44, 0.47, 0.50],
            ],
        ),
        1.0: _conical_block(
            "branch",
            1.0,
            [0.2, 0.3, 0.4, 0.5, 0.6, 0.8, 1.0],
            [
                [None, 2.1, 3.7, 5.2, 6.6, 7.8, 9.0, 11, 11, 12],
                [None, 0.54, 1.2, 1.8, 2.3, 2.7, 3.1, 3.7, 3.7, 4.0],
                [None, 0.21, 0.62, 0.96, 1.2, 1.5, 1.7, 2.0, 2.0, 2.1],
                [None, 0.05, 0.37, 0.60, 0.79, 0.93, 1.1, 1.2, 1.2, 1.3],
                [None, -0.02, 0.23, 0.42, 0.55, 0.66, 0.73, 0.80, 0.85, 0.89],
                [None, -0.10, 0.11, 0.24, 0.33, 0.39, 0.43, 0.46, 0.47, 0.48],
                [None, -0.14, 0.05, 0.16, 0.23, 0.27, 0.29, 0.30, 0.30, 0.29],
            ],
        ),
    },
)

WYE_CONICAL_ROUND_MAIN = TableFamily(
    "as_on_ac",
    {
        0.3: _conical_block(
            "main",
            0.3,
            [0.2, 0.3],
            [
                [5.3, -0.01, 2.0, 1.1, 0.34, -0.20, -0.61, -0.93, -1.2, -1.4],
                [5.4, 3.7, 2.5, 1.6, 1.0, 0.53, 0.16, -0.14, -0.38, -0.58],
            ],
        ),
        0.4: _conical_block(
            "main",
            0.4,
            [0.2, 0.3, 0.4],
            [
                [1.9, 1.1, 0.46, -0.07, -0.49, -0.83, -1.1, -1.3, -1.5, -1.7],
                [2.0, 1.4, 0.81, 0.42, 0.08, -0.20, -0.43, -0.62, -0.78, -0.92],
                [2.0, 1.5, 1.0, 0.68, 0.39, 0.16, -0.04, -0.21, -0.35, -0.47],
            ],
        ),
        0.5: _conical_block(
            "main",
            0.5,
            [0.2, 0.3, 0.4, 0.5],
            [
                [0.77, 0.34, -0.09, -0.48, -0.81, -1.1, 1.3, -1.5, -1.7, -1.8],
                [0.85, 0.56, 0.25, -0.03, -0.27, -0.48, -0.67, -0.82, -0.96, -1.1],
                [0.88, 0.66, 0.43, 0.21, 0.02, -0.15, -0.30, -0.42, -0.54, -0.64],
                [0.91, 0.73, 0.54, 0.36, 0.21, 0.06, -0.06, -0.17, -0.26, -0.35],
            ],
        ),
        0.6: _conical_block(
            "main",
            0.6,
            [0.2, 0.3, 0.4, 0.5, 0.6],
            [
                [0.30, 0, -0.34, -0.67, -0.96, -1.2, -1.4, -1.6, -1.8, -1.9],
                [0.37, 0.21, -0.02, -0.24, -0.44, -0.63, -0.79, -0.93, -1.1, -1.2],
                [0.40, 0.31, 0.16, -0.01, -0.16, -0.30, -0.43, -0.54, -0.64, -0.73],
                [0.43, 0.37, 0.26, 0.14, 0.02, -0.09, -0.20, -0.29, -0.37, -0.45],
                [0.44, 0.41, 0.33, 0.24, 0.14, 0.05, -0.03, -0.11, -0.18, -0.25],
            ],
        ),
        0.8: _conical_block(
            "main",
            0.8,
            [0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8],
            [
                [-0.06, -0.27, -0.57, -0.86, -1.1, -1.4, -1.6, -1.7, -1.9, -2.0],
                [0, -0.08, -0.25, -0.43, -0.62, -0.78, -0.93, -1.1, -1.2, -1.3],
                [0.04, 0.02, -0.08, -0.21, -0.34, -0.46, -0.57, -0.67, -0.77, -0.85],
                [0.06, 0.08, 0.02, -0.06, -0.16, -0.25, -0.34, -0.42, -0.50, -0.57],
                [0.07, 0.12, 0.09, 0.03, -0.04, -0.11, -0.18, -0.25, -0.31, -0.37],
                [0.08, 0.15, 0.14, 0.10, 0.05, -0.01, -0.07, -0.12, -0.17, -0.22],
                [0.09, 0.17, 0.18, 0.16, 0.11, 0.07, 0.02, -0.02, -0.07, -0.11],
            ],
        ),
        1.0: _conical_block(
            "main",
            1.0,
            [0.2, 0.3, 0.4, 0.5, 0.6, 0.8, 1.0],
            [
                [None, -0.39, -0.67, -0.96, -1.2, -1.5, -1.6, -1.8, -2.0, -2.1],
                [None, -0.19, -0.35, -0.54, -0.71, -0.87, -1.0, -1.2, -1.3, -1.4],
                [None, -0.10, -0.19, -0.31, -0.43, -0.55, -0.66, -0.77, -0.86, -0.94],
                [None, -0.04, -0.09, -0.17, -0.26, -0.35, -0.44, -0.52, -0.59, -0.66],
                [None, 0, -0.02, -0.07, -0.14, -0.21, -0.28, -0.34, -0.40, -0.46],
                [None, 0.06, 0.07, 0.05, 0.02, -0.03, -0.07, -0.12, -0.16, -0.20],
                [None, 0.09, 0.13, 0.13, 0.11, 0.08, 0.06, 0.03, -0.01, -0.03],
            ],
        ),
    },
)

# ----------------------------------------------------------------------------
# G. Symmetrical wye, dovetail, rectangular (R/W = 1.5, equal flows).
# One coefficient for either branch.
# ----------------------------------------------------------------------------

WYE_DOVETAIL_RECT = LossTable(
    "14-13G",
    "Symmetrical wye, dovetail, rectangular (converging)",
    [("ab_on_ac", [0.50, 1.0])],
    [0.23, 0.07],
    REF_DOWNSTREAM,
    _RECT,
)

# ----------------------------------------------------------------------------
# H. Converging wye, rectangular (radius branch, R/W = 1.0). Each row is one
# specific fitting, identified by two area ratios.
# ----------------------------------------------------------------------------


def _wye_rect_row(part, key, values):
    return (
        key,
        LossTable(
            "14-13H {} {}/{}".format(part, *key),
            "Converging wye, rectangular: {}".format(part),
            [("qb_on_qc", _Q_01_TO_09)],
            values,
            REF_DOWNSTREAM,
            _RECT,
        ),
    )


# Rows are keyed by (Ab/As, Ab/Ac).
WYE_RECT_BRANCH = TableRows(
    ("ab_on_as", "ab_on_ac"),
    [
        _wye_rect_row("branch", (0.25, 0.25), [-0.50, 0, 0.50, 1.2, 2.2, 3.7, 5.8, 8.4, 11]),
        _wye_rect_row("branch", (0.33, 0.25), [-1.2, -0.40, 0.40, 1.6, 3.0, 4.8, 6.8, 8.9, 11]),
        _wye_rect_row("branch", (0.5, 0.5), [-0.50, -0.20, 0, 0.25, 0.45, 0.70, 1.0, 1.5, 2.0]),
        _wye_rect_row("branch", (0.67, 0.5), [-1.0, -0.60, -0.20, 0.10, 0.30, 0.60, 1.0, 1.5, 2.0]),
        _wye_rect_row("branch", (1.0, 0.5), [-2.2, -1.5, -0.95, -0.50, 0, 0.40, 0.80, 1.3, 1.9]),
        _wye_rect_row("branch", (1.0, 1.0), [-0.60, -0.30, -0.10, -0.04, 0.13, 0.21, 0.29, 0.36, 0.42]),
        _wye_rect_row("branch", (1.33, 1.0), [-1.2, -0.80, -0.40, -0.20, 0, 0.16, 0.24, 0.32, 0.38]),
        _wye_rect_row("branch", (2.0, 1.0), [-2.1, -1.4, -0.90, -0.50, -0.20, 0, 0.20, 0.25, 0.30]),
    ],
)

# Rows are keyed by (As/Ac, Ab/Ac).
WYE_RECT_MAIN = TableRows(
    ("as_on_ac", "ab_on_ac"),
    [
        _wye_rect_row("main", (0.75, 0.25), [0.30, 0.30, 0.20, -0.10, -0.45, -0.92, -1.5, -2.0, -2.6]),
        _wye_rect_row("main", (1.0, 0.5), [0.17, 0.16, 0.10, 0, -0.08, -0.18, -0.27, -0.37, -0.46]),
        _wye_rect_row("main", (0.75, 0.5), [0.27, 0.35, 0.32, 0.25, 0.12, -0.03, -0.23, -0.42, -0.58]),
        _wye_rect_row("main", (0.5, 0.5), [1.2, 1.1, 0.90, 0.65, 0.35, 0, -0.40, -0.80, -1.3]),
        _wye_rect_row("main", (1.0, 1.0), [0.18, 0.24, 0.27, 0.26, 0.23, 0.18, 0.10, 0, -0.12]),
        _wye_rect_row("main", (0.75, 1.0), [0.75, 0.36, 0.38, 0.35, 0.27, 0.18, 0.05, -0.08, -0.22]),
        _wye_rect_row("main", (0.5, 1.0), [0.80, 0.87, 0.80, 0.68, 0.55, 0.40, 0.25, 0.08, -0.10]),
    ],
)

# ----------------------------------------------------------------------------
# I. Wye, rectangular and round: two equal branches (A1b = A2b,
# Ac = A1b + A2b), each at angle theta to the common axis. The coefficient
# of a branch is keyed by that branch's own share of the flow.
# ----------------------------------------------------------------------------

WYE_SYMMETRIC = LossTable(
    "14-13I",
    "Wye, rectangular and round, symmetric (converging)",
    [("theta_deg", [15, 30, 45]), ("q_branch_on_qc", [0, 0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 0.90, 1.0])],
    [
        [-2.6, -1.9, -1.3, -0.77, -0.30, 0.10, 0.41, 0.67, 0.85, 0.97, 1.0],
        [-2.1, -1.5, -1.0, -0.53, -0.10, 0.28, 0.69, 0.91, 1.1, 1.4, 1.6],
        [-1.3, -0.93, -0.55, -0.16, 0.20, 0.56, 0.92, 1.26, 1.6, 2.0, 2.3],
    ],
    REF_DOWNSTREAM,
    ("Circular", "Rectangular"),
)


# ----------------------------------------------------------------------------
# Lookups
# ----------------------------------------------------------------------------


def wye_45_round(ab_on_ac, vb_on_vc, vs_on_vc):
    """14-13 A: (branch, main) coefficients of a 45 deg round converging wye."""
    return WYE_45_ROUND_BRANCH.lookup(vb_on_vc, ab_on_ac), WYE_45_ROUND_MAIN.lookup(vs_on_vc, ab_on_ac)


def tee_90_round(ab_on_ac, qb_on_qc):
    """14-13 B: (branch, main) coefficients of a 90 deg round converging tee."""
    return TEE_90_ROUND_BRANCH.lookup(qb_on_qc, ab_on_ac), TEE_90_MAIN.lookup(qb_on_qc)


def tee_rect_main(kind, qb_on_qc, vc_ms):
    """
    14-13 C, D, F: (branch, main) coefficients of a tee into a rectangular
    main. `kind` is one of the RECT_MAIN_TEES keys. The tables only hold for
    RECT_TEE_AREA_RATIOS; the caller decides how to treat other proportions.
    """
    try:
        slow, fast = RECT_MAIN_TEES[kind]
    except KeyError:
        raise ValueError(
            "Unknown rectangular-main tee '{}'. Known: {}".format(kind, ", ".join(sorted(RECT_MAIN_TEES)))
        ) from None
    branch_table = slow if float(vc_ms) < RECT_TEE_VELOCITY_SPLIT_MS else fast
    return branch_table.lookup(qb_on_qc), TEE_90_MAIN.lookup(qb_on_qc)


def wye_conical_round(as_on_ac, ab_on_ac, qb_on_qs):
    """14-13 E: (branch, main) coefficients of a 45 deg conical round converging wye."""
    return (
        WYE_CONICAL_ROUND_BRANCH.lookup(as_on_ac, ab_on_ac, qb_on_qs),
        WYE_CONICAL_ROUND_MAIN.lookup(as_on_ac, ab_on_ac, qb_on_qs),
    )


def wye_dovetail_rect(ab_on_ac):
    """14-13 G: the coefficient of either branch of a symmetric dovetail wye (equal flows)."""
    return WYE_DOVETAIL_RECT.lookup(ab_on_ac)


def wye_rect(ab_on_as, as_on_ac, ab_on_ac, qb_on_qc):
    """14-13 H: (branch, main) coefficients of a rectangular converging wye, from the nearest printed fitting."""
    return (
        WYE_RECT_BRANCH.lookup((ab_on_as, ab_on_ac), qb_on_qc),
        WYE_RECT_MAIN.lookup((as_on_ac, ab_on_ac), qb_on_qc),
    )


def wye_symmetric(theta_deg, q_branch_on_qc):
    """14-13 I: the coefficient of one branch of a symmetric two-branch wye carrying that share of the flow."""
    return WYE_SYMMETRIC.lookup(theta_deg, q_branch_on_qc)
