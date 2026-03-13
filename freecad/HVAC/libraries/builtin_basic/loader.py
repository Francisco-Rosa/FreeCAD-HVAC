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

from ...Library import HVACLibrary, HVACPropertyDef, HVACTypeDef


def load_into(registry):
    lib = HVACLibrary(
        id="builtin_basic",
        label="Built-in Basic",
        root_path="builtin",
        generators_package="freecad.HVAC.libraries.builtin_basic.generators",
    )

    # Terminal marker
    lib.add_type(HVACTypeDef(
        id="terminal_marker",
        label="Terminal Marker",
        category="junction",
        family="terminal",
        profiles=["generic"],
        constraints={"degree": 1},
        properties=[
            HVACPropertyDef("MarkerDiameter", "App::PropertyLength", "Dimensions", "Marker diameter", 200.0),
        ],
        generator_module="junctions",
        generator_function="build_terminal_marker",
    ))

    # Transition marker
    lib.add_type(HVACTypeDef(
        id="transition_marker",
        label="Transition Marker",
        category="junction",
        family="transition",
        profiles=["generic"],
        constraints={"degree": 2, "collinear": True},
        properties=[
            HVACPropertyDef("MarkerDiameter", "App::PropertyLength", "Dimensions", "Marker diameter", 220.0),
        ],
        generator_module="junctions",
        generator_function="build_transition_marker",
    ))

    # Elbow marker
    lib.add_type(HVACTypeDef(
        id="elbow_marker",
        label="Elbow Marker",
        category="junction",
        family="elbow",
        profiles=["generic"],
        constraints={"degree": 2, "collinear": False},
        properties=[
            HVACPropertyDef("MarkerDiameter", "App::PropertyLength", "Dimensions", "Marker diameter", 240.0),
        ],
        generator_module="junctions",
        generator_function="build_elbow_marker",
    ))

    # Tee marker
    lib.add_type(HVACTypeDef(
        id="tee_marker",
        label="Tee Marker",
        category="junction",
        family="tee",
        profiles=["generic"],
        constraints={"degree": 3},
        properties=[
            HVACPropertyDef("MarkerDiameter", "App::PropertyLength", "Dimensions", "Marker diameter", 260.0),
        ],
        generator_module="junctions",
        generator_function="build_tee_marker",
    ))

    # Wye marker
    lib.add_type(HVACTypeDef(
        id="wye_marker",
        label="Wye Marker",
        category="junction",
        family="wye",
        profiles=["generic"],
        constraints={"degree": 3},
        properties=[
            HVACPropertyDef("MarkerDiameter", "App::PropertyLength", "Dimensions", "Marker diameter", 260.0),
        ],
        generator_module="junctions",
        generator_function="build_wye_marker",
    ))

    # Cross marker
    lib.add_type(HVACTypeDef(
        id="cross_marker",
        label="Cross Marker",
        category="junction",
        family="cross",
        profiles=["generic"],
        constraints={"degree": 4},
        properties=[
            HVACPropertyDef("MarkerDiameter", "App::PropertyLength", "Dimensions", "Marker diameter", 280.0),
        ],
        generator_module="junctions",
        generator_function="build_cross_marker",
    ))

    # Manifold marker
    lib.add_type(HVACTypeDef(
        id="manifold_marker",
        label="Manifold Marker",
        category="junction",
        family="manifold",
        profiles=["generic"],
        constraints={"degree_min": 5},
        properties=[
            HVACPropertyDef("MarkerDiameter", "App::PropertyLength", "Dimensions", "Marker diameter", 300.0),
        ],
        generator_module="junctions",
        generator_function="build_manifold_marker",
    ))

    registry.register_library(lib)
