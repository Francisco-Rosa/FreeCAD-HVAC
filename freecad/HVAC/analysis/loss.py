# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the HVAC addon.

################################################################################
#                                                                              #
#   Copyright (c) 2026 Francisco Rosa                                          #
#                                                                              #
#   This addon is free software; you can redistribute it and/or modify it      #
#   under the terms of the GNU Lesser General Public License as published      #
#   by the Free Software Foundation; either version 2.1 of the License, or     #
#   (at your option) any later version.                                        #
#                                                                              #
#   This addon is distributed in the hope that it will be useful,              #
#   but WITHOUT ANY WARRANTY; without even the implied warranty of             #
#   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.                       #
#                                                                              #
#   See the GNU Lesser General Public License for more details.                #
#                                                                              #
#   You should have received a copy of the GNU Lesser General Public           #
#   License along with this addon. If not, see https://www.gnu.org/licenses    #
#                                                                              #
################################################################################

"""
Pure data model for a fitting's loss result -- replaces the old
dict/float/None contract every loss formula used to return.

A loss coefficient always belongs to a directed flow path through a fitting
(`from_edge_key -> to_edge_key`), not implicitly to "the outlet" -- this is
what makes a converging tee (where the physically distinct coefficients
belong to the two INLET legs) representable the same way a diverging tee
(coefficients on the two OUTLET legs) already was. See ARCHITECTURE.md's
"Fitting-loss model" section for the full picture, including the
pressure-reference convention analysis/pressure.py builds on top of this.

Nothing here knows about FreeCAD/core/library -- same "pure" rule as the
rest of the analysis/ package (see model.py's own docstring).
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class LossStatus(Enum):
    """How a LossEvaluation's coefficients were obtained -- lets a caller
    (analysis/pressure.py, analysis/sizing.py) decide whether to warn."""

    EXACT = "exact"            # validated table lookup for this exact case
    APPROXIMATION = "approximation"  # documented estimate, not a literal table entry
    CUSTOM = "custom"          # user-supplied override
    FALLBACK = "fallback"      # explicit generic-K policy (library- or solver-applied)
    UNSUPPORTED = "unsupported"  # no formula for this flow topology


@dataclass(frozen=True)
class LossPath:
    """
    One loss coefficient attached to a directed flow path through a
    fitting. `reference_edge_key` (always equal to `from_edge_key` or
    `to_edge_key`) is whose own velocity `loss_coefficient` is referenced
    to -- the same "K referenced to this leg's own velocity" convention
    every SMACNA/ASHRAE table here already uses.

    `from_edge_key`/`to_edge_key` are only ever None for a 1-port device's
    open-atmosphere side (a terminal diffuser has nothing physically
    connected on its "other" side) -- direction is derived once, when this
    path is built, from each port's own flow_into_junction/flow_into_node,
    never from key ordering.
    """

    from_edge_key: Optional[str]
    to_edge_key: Optional[str]
    reference_edge_key: str
    loss_coefficient: float
    source: Optional[str] = None


@dataclass
class LossEvaluation:
    """One fitting's complete loss result: every LossPath it produced, plus
    an overall status/warning describing how those paths were obtained."""

    paths: List[LossPath] = field(default_factory=list)
    status: LossStatus = LossStatus.UNSUPPORTED
    warning: Optional[str] = None
