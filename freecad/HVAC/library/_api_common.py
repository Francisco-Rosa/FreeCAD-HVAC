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

"""Shared pieces of the HVAC library API (see library_api.py)."""

from dataclasses import dataclass, field
from typing import Any, Mapping

_EPS = 1.0e-7


@dataclass(frozen=True)
class HVACProfile:
    """Immutable section description paired with its generated closed wire.

    ``local_points`` is populated only for polygon profiles so analytical
    offsets can be rebuilt in the same local two-dimensional frame.
    """

    profile: str
    params: Mapping[str, Any]
    center: Any
    direction: Any
    profile_x_axis: Any
    wire: Any = field(repr=False)
    local_points: tuple[tuple[float, float], ...] = ()
