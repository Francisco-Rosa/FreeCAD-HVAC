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

"""Stable public helpers and geometry primitives for HVAC libraries.

Library generators and PartScripts receive this class as
``context["hvac_api"]``. The API is grouped from low-level, non-shape
helpers through direct Part geometry operations to HVAC-specific convenience
recipes. Library code must use this surface instead of importing FreeCAD,
Part, or internal HVAC modules directly.
"""

from . import _api_booleans, _api_ports, _api_profiles, _api_recipes, _api_solids
from ._api_booleans import _BooleansMixin
from ._api_common import _EPS, HVACProfile  # noqa: F401 -- re-exported for library code
from ._api_ports import _PortsMixin
from ._api_profiles import _ProfilesMixin
from ._api_recipes import _RecipesMixin
from ._api_solids import _SolidsMixin


class HVACLibraryAPI(_PortsMixin, _ProfilesMixin, _SolidsMixin, _BooleansMixin, _RecipesMixin):
    """Stable geometry and context API exposed to HVAC library code.

    The methods are written in topic modules, from low-level helpers to HVAC
    recipes: _api_ports (vectors, contexts, ports, trim records),
    _api_profiles (frames, sections), _api_solids (extrusions, sweeps,
    lofts), _api_booleans (trims, booleans, topology, finishing) and
    _api_recipes (layered builds, standard fittings, external geometry).
    This class is still the one public surface: library code only ever
    sees HVACLibraryAPI.
    """

    API_VERSION = 4
    EPS = 1.0e-9

    # The public surface library code may use (ROADMAP 6.4, item 3): every
    # name here, nothing with a leading underscore. tests/
    # test_library_geometry_api_v2.py fails when this list and the class
    # disagree, so adding or removing a public method is a deliberate change.
    PUBLIC = frozenset(
        {
            "API_VERSION",
            "EPS",
            "PUBLIC",
            "STANDARD_FITTINGS",
            "angle_between",
            "arc_center_from_points_tangents_radius",
            "average_point",
            "build_envelopes",
            "build_fitting",
            "build_layered_fitting",
            "build_layered_geometry",
            "build_trim_rec_from_context_uniform",
            "build_trim_rec_from_port_lengths",
            "center_from_context",
            "clip_plane",
            "closest_points_on_lines",
            "collinear_port_index_pairs",
            "common",
            "compound",
            "connected_ports",
            "copy_port",
            "cut",
            "envelopes_to_layers",
            "extrude",
            "fuse",
            "grow_port_section",
            "is_zero",
            "loft",
            "make_circular_wire",
            "make_circular_wire_split_at",
            "make_elbow_path",
            "make_face",
            "make_flange",
            "make_line",
            "make_profile",
            "make_profile_frame",
            "make_radiussed_path",
            "make_rectangular_wire",
            "make_sphere",
            "make_split_circular_wire",
            "measure_fitting",
            "offset_profile",
            "offset_transition_axis",
            "offset_wire",
            "port_area",
            "port_diameter",
            "port_direction",
            "port_height",
            "port_param",
            "port_position",
            "port_profile",
            "port_profile_x_axis",
            "port_roles",
            "port_section_params",
            "port_width",
            "profile_from_port",
            "profile_projection_bounds",
            "refine",
            "resolve_library_file",
            "reverse",
            "revolve",
            "rotate",
            "rotate_vector",
            "run_branch_ports",
            "sample_path",
            "section_face",
            "shape_from_fcstd",
            "single_layer",
            "split_profile_face_by_extent",
            "stretch_profile_one_sided",
            "sweep",
            "translate",
            "trim",
            "unit",
            "validate",
            "vec",
            "xyz",
        }
    )


for _module in (_api_ports, _api_profiles, _api_solids, _api_booleans, _api_recipes):
    _module.HVACLibraryAPI = HVACLibraryAPI
del _module
