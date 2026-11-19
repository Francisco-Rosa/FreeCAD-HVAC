# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the HVAC addon.

"""
SMACNA Table 14-9: loss coefficients for straight-through flow, used with
the static regain method. Vs = downstream (system) velocity, Vc = upstream
(system) velocity. One column for 75 % regain and one for 90 % regain.

The source does not state which velocity pressure the coefficient
multiplies. It is recorded here as the upstream one (Vc), in line with the
other diverging-flow tables; treat that as an assumption.

Also here: the equation printed under Tables 14-2 and 14-3 for the circular
equivalent of a rectangular duct.
"""

from .table import REF_UPSTREAM, LossTable

STRAIGHT_THROUGH_REGAIN = LossTable(
    "14-9",
    "Loss coefficients for straight-through flow",
    [
        ("regain_percent", [75, 90]),
        (
            "vs_on_vc",
            [0.95, 0.91, 0.87, 0.83, 0.80, 0.77, 0.74, 0.71, 0.69, 0.67]
            + [0.65, 0.63, 0.61, 0.59, 0.57, 0.56, 0.54, 0.53, 0.51, 0.50],
        ),
    ],
    [
        [0.03, 0.04, 0.06, 0.08, 0.09, 0.10, 0.11, 0.12, 0.13, 0.14]
        + [0.15, 0.15, 0.16, 0.16, 0.17, 0.18, 0.18, 0.18, 0.18, 0.19],
        [0.01, 0.02, 0.02, 0.03, 0.04, 0.04, 0.04, 0.05, 0.05, 0.06]
        + [0.06, 0.06, 0.06, 0.07, 0.07, 0.07, 0.07, 0.07, 0.07, 0.08],
    ],
    REF_UPSTREAM,
    ("Circular", "Rectangular"),
)


def straight_through(vs_on_vc, regain_percent=75.0):
    """14-9. Between the two printed regain columns (75 and 90 %) the coefficient is interpolated."""
    return STRAIGHT_THROUGH_REGAIN.lookup(regain_percent, vs_on_vc)


def circular_equivalent_of_rectangular(a, b):
    """
    Diameter of the round duct with the same friction and capacity as an
    a x b rectangular duct (Tables 14-2 / 14-3): De = 1.30 (ab)^0.625 / (a + b)^0.25.
    Any length unit; the result is in the same unit.
    """
    a, b = float(a), float(b)
    if a <= 0.0 or b <= 0.0:
        raise ValueError("Both sides must be positive")
    return 1.30 * (a * b) ** 0.625 / (a + b) ** 0.25
