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
Standardized construction-layer vocabulary.

A duct/fitting's wall can be built from any number of physical layers (a
bare sheet-metal wall, a wall plus insulation wrap, a wall plus an acoustic
fill plus a perforated liner, ...). Library authors invent their own layer
*ids* ("casing", "liner", "absorber", ...) and decide how many layers a type
has and how they're geometrically built -- that recipe lives entirely in
library JSON/generator code (see Library.py's "construction" type-def block
and the profiles, sweeps, lofts, and booleans in library_api.py).

What core owns instead is the semantic *role* vocabulary below: the fixed,
standardized set of physical roles a layer can play. Downstream code
(materials, appearance, and later airflow/acoustic/thermal/detailing) must
only ever branch on a layer's roles, never on its library-chosen id -- that's
what keeps core/application code generic across arbitrary library-defined
constructions.

This module is pure data -- no FreeCAD import, same "library/core-neutral"
convention as geometry_result.py -- so it can be imported from both
library/ (type-def loading, geometry backends) and core/ (the construction
query facade) without pulling in FreeCAD.
"""

from dataclasses import dataclass, field

# A layer may carry more than one role at once -- e.g. a single-wall duct's
# only layer is both the flow surface and the structural shell.
ROLE_FLOW_SURFACE = "flow_surface"
ROLE_STRUCTURAL_SHELL = "structural_shell"
ROLE_THERMAL_INSULATION = "thermal_insulation"
ROLE_ACOUSTIC_ABSORBER = "acoustic_absorber"
ROLE_ACOUSTIC_LINER = "acoustic_liner"
ROLE_VAPOR_BARRIER = "vapor_barrier"
ROLE_OUTER_JACKET = "outer_jacket"
ROLE_FIRE_PROTECTION = "fire_protection"

ALL_LAYER_ROLES = (
    ROLE_FLOW_SURFACE,
    ROLE_STRUCTURAL_SHELL,
    ROLE_THERMAL_INSULATION,
    ROLE_ACOUSTIC_ABSORBER,
    ROLE_ACOUSTIC_LINER,
    ROLE_VAPOR_BARRIER,
    ROLE_OUTER_JACKET,
    ROLE_FIRE_PROTECTION,
)


def role_property_suffix(role):
    """
    PascalCase form of a ROLE_* string, e.g. "structural_shell" ->
    "StructuralShell" -- the single place that maps a semantic role onto
    the network-level DefaultMaterial_<Role> FreeCAD property name (see
    core/Network.py and core/_construction_schema.py), so the two always
    agree on the mapping.
    """
    return "".join(part.capitalize() for part in str(role).split("_"))


@dataclass
class ConstructionLayerDef:
    """
    One library-declared construction layer, parsed from a type-def's
    "construction" JSON block (see Library.py._load_type_def_file).

    id: library-chosen, stable within that type-def (e.g. "casing",
        "liner", "absorber") -- never interpreted by core/application code,
        only used to pair a layer's def with its generated geometry and its
        own Layer_<id>_Shape/Layer_<id>_Material FreeCAD properties.
    roles: standardized ROLE_* strings this layer plays (see module docstring).
    default_material_role: which network-level default-material role (a
        ROLE_* value) to fall back to when this layer has no material of
        its own yet -- see core/Segment.py's applyOwnerDefaults().
    default_material_uuid: an explicit default material, taking priority
        over default_material_role when set.
    thickness_property: name of the type-def property holding this layer's
        thickness, if any. Construction queries use it for thermal
        resistance; the generated Shape remains the source of truth for
        geometry and volume.
    """
    id: str
    roles: list = field(default_factory=list)
    default_material_role: "str | None" = None
    default_material_uuid: "str | None" = None
    thickness_property: "str | None" = None


@dataclass
class LayerGeometry:
    """
    One physical layer's generated geometry for one build_geometry() call.

    `roles` is stamped on by HVACLibraryRegistry.build_geometry() from the
    type-def's matching ConstructionLayerDef (see Library.py), so a
    GeometryResult stays self-describing without needing the type-def
    around afterwards.
    """
    shape: object = None  # Part.Shape, or None if this layer has no geometry this call
    roles: list = field(default_factory=list)


@dataclass
class ConstructionFeatureDef:
    """
    One library-declared construction feature (a localized attachment --
    flange, stiffener, seam, ... -- as opposed to a role-bearing layer
    spanning the whole wall), parsed from a type-def's "construction.features"
    JSON block (see Library.py._load_type_def_file).

    id: library-chosen, stable within that type-def -- pairs a feature's def
        with its generated geometry and its own Feature_<id>_Shape FreeCAD
        property (see core/_construction_schema.py). Never interpreted by
        core/application code.
    role: a free-form, library-chosen string (e.g. "transverse_joint") --
        unlike a layer's roles, there is no standardized/enumerated
        vocabulary for feature roles; core only supports querying by
        whatever string a library chose (see core/Construction.py).
    host_layer: the id of the ConstructionLayerDef this feature is attached
        to/built from (see Library.py.build_geometry(), which resolves this
        to that layer's own already-built LayerGeometry before invoking the
        feature's generator).
    module: name of the generators submodule (generators_package + "." +
        module) this feature's own generator function lives in, resolved
        the same way generator_module/loss_module already are
        (HVACLibraryRegistry.import_generator()). Empty/falsy defaults to
        the conventional "features" submodule (generators_package +
        ".features"), so most type-defs never need to set this.
    generator: name of the function inside that module (see "module"
        above) -- resolved and invoked by build_geometry(), never
        imported by core ahead of time.
    enabled_parameter: name of an *existing* declared type-def property
        (see HVACPropertyDef) whose current value gates whether this
        feature is generated at all this build. None means always enabled.
    visible_parameter: name of an *existing* declared type-def property
        whose current value controls only the feature's rendered
        visibility, independent of whether it was generated -- see
        core/_construction_schema.py for why this property is marked
        Prop_NoRecompute (changing visibility must never trigger a
        geometry rebuild). None means always visible.
    parameters: names of existing declared type-def properties this
        feature's own generator function needs -- core resolves just these
        (already-resolved) values into the generator's own FeatureContext.parameters,
        never the type's full property set. This list, and
        enabled_parameter/visible_parameter, only ever *reference* property
        names -- the properties themselves stay declared exactly where they
        already are, in the type-def's own "properties" list.
    """
    id: str
    role: str = ""
    host_layer: str = ""
    module: str = ""
    generator: str = ""
    enabled_parameter: "str | None" = None
    visible_parameter: "str | None" = None
    parameters: list = field(default_factory=list)


@dataclass
class FeatureGeometry:
    """
    One feature's generated geometry for one build_geometry() call. Absent
    from GeometryResult.features entirely when disabled (see
    ConstructionFeatureDef.enabled_parameter) -- unlike a layer, a feature
    has no "present but null" state, only "present" or "not generated at
    all this call."
    """
    shape: object = None  # Part.Shape (or a compound, for repeated geometry)
    role: str = ""
    visible: bool = True


@dataclass
class FeatureContext:
    """
    The `ctx` argument a library's own feature generator function receives
    (alongside HVACLibraryAPI as `api`) -- see Library.py.build_geometry()'s
    feature-generation pass.

    parameters: {name: value} filtered to exactly this feature's own
        declared ConstructionFeatureDef.parameters (already resolved by the
        same validation.resolve_params() call that resolved every other
        property for this build -- never a second/separate resolution).
    host_layer: this feature's own host layer's already-built LayerGeometry
        (shape + roles) for this same build_geometry() call.
    host_layer_id: the feature def's host_layer id (the key into
        context["construction_layers"]).
    result: the geometry backend's own normalized GeometryResult for this
        build (its layers and connection_lengths), before any feature.
    context: the full underlying geometry-build context dict (ports,
        start/end points, profile, profile_x_axis, path info, ...) -- an
        escape hatch for anything a feature generator needs beyond its own
        parameters/host layer, so this dataclass doesn't need to re-invent
        every context key generator/PartScript authors already rely on.
    """
    parameters: dict = field(default_factory=dict)
    host_layer: object = None
    context: dict = field(default_factory=dict)
    # The feature def's own host_layer id, and the backend's normalized
    # GeometryResult (layers, connection_lengths) for this same build, so a
    # feature can find a fitting's real end faces (ROADMAP 6.2).
    host_layer_id: str = ""
    result: object = None
