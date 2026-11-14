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
Dynamic per-layer/per-feature property bookkeeping for FreeCAD objects whose
construction (how many layers/features, what each is called) depends on a
selected library type (DuctSegment, DuctJunction's DuctComponent children).
Sibling of core/_type_schema.py's apply_type_schema() -- same add/remove-
stale-properties pattern, but for the Layer_<id>_Shape/Layer_<id>_Material
pair every construction layer gets, and the Feature_<id>_Shape every
construction feature gets, instead of ordinary declared properties.
Internal to core/ -- not part of the stable library_api.py surface for
library/generator authors.
"""

from ..library import geometry_result
from ..library.construction import role_property_suffix
from ..utils import hvaclib
from ..utils import materials as hvac_materials


def shape_property_name(layer_id):
    return "Layer_{}_Shape".format(layer_id)


def material_property_name(layer_id):
    return "Layer_{}_Material".format(layer_id)


def feature_shape_property_name(feature_id):
    return "Feature_{}_Shape".format(feature_id)


def apply_construction_schema(obj, library_id, type_id):
    """
    Add/remove Layer_<id>_Shape (Part::PropertyPartShape, read-only) and
    Layer_<id>_Material (Materials::PropertyMaterial, Prop_NoRecompute) to
    match the resolved type's declared construction layers. Removes
    leftover Layer_<id>_* properties from a previously-selected type the
    same way apply_type_schema() does for ordinary properties. Writes the
    layer id list, in the type-def's own declared order, onto
    obj.ConstructionLayerIds -- the order core/_geometry_apply.py composes
    Shape in and core/_component_appearance.py splits per-face appearance
    by. Returns True if anything on `obj` changed.

    A type with no declared construction (not yet migrated to the
    multilayer model) gets a single implicit layer id, matching
    HVACLibraryAPI.single_layer() when a type declares no layers, so it
    still gets one Layer_shape_Shape/Layer_shape_Material pair rather than
    none at all.
    """
    reg = hvaclib.HVACLibraryService.get_hvac_library_registry()
    if not library_id or not type_id:
        return False

    type_def = reg.resolve_type(library_id, type_id)
    if type_def is None:
        return False

    construction = getattr(type_def, "construction", None) or []
    new_ids = [ldef.id for ldef in construction] or [geometry_result.LEGACY_SHAPE_LAYER_ID]

    changed = False

    old_ids = list(getattr(obj, "ConstructionLayerIds", []) or [])
    for stale_id in set(old_ids) - set(new_ids):
        for prop_name in (shape_property_name(stale_id), material_property_name(stale_id)):
            if prop_name in obj.PropertiesList:
                try:
                    obj.removeProperty(prop_name)
                    changed = True
                except Exception:
                    pass

    for layer_id in new_ids:
        shape_name = shape_property_name(layer_id)
        if shape_name not in obj.PropertiesList:
            obj.addProperty("Part::PropertyPartShape", shape_name, "Geometry", "Generated solid for construction layer '{}'".format(layer_id))
            changed = True
            try:
                obj.setEditorMode(shape_name, 1)
            except Exception:
                pass

        material_name = material_property_name(layer_id)
        if material_name not in obj.PropertiesList:
            # Prop_NoRecompute (16) -- picking a material never changes this
            # object's own geometry, only its ViewProvider's rendered
            # appearance (see core/_component_appearance.py).
            obj.addProperty("Materials::PropertyMaterial", material_name, "Materials", "Native FreeCAD material for construction layer '{}'".format(layer_id), 16)
            changed = True
        if hvac_materials.ensure_persistable_material(obj, material_name):
            changed = True

    if list(getattr(obj, "ConstructionLayerIds", []) or []) != new_ids:
        try:
            obj.ConstructionLayerIds = new_ids
            changed = True
        except Exception:
            pass

    return changed


def apply_construction_features_schema(obj, library_id, type_id):
    """
    Add/remove Feature_<id>_Shape (Part::PropertyPartShape, read-only) to
    match the resolved type's declared construction features -- sibling of
    apply_construction_schema(), same add/remove-stale-properties pattern,
    keyed off obj.ConstructionFeatureIds instead of ConstructionLayerIds.
    No Feature_<id>_Material -- a feature has no material of its own in
    this design; it visually inherits its host layer's own material (see
    core/_component_appearance.py). No legacy single-implicit-feature
    fallback either (unlike layers) -- a type with no declared features
    simply has none.

    Also marks each declared feature's own visible_parameter property
    Prop_NoRecompute, best-effort, via obj.setPropertyStatus() -- this is
    what makes "changing visibility never requires a geometry rebuild"
    true. The property itself is added as an ordinary declared property by
    core/_type_schema.py's apply_type_schema() (already run earlier in
    applyTypeSchema()'s call order, per the "existing parameter system,
    unchanged" rule -- a feature's visible_parameter/enabled_parameter/
    parameters only ever *reference* a name already declared in the
    type-def's own "properties" list, never a new parameter-definition
    mechanism); enabled_parameter and every name in a feature's own
    `parameters` are deliberately left alone here so they keep triggering a
    normal recompute.

    Returns True if anything on `obj` changed.
    """
    reg = hvaclib.HVACLibraryService.get_hvac_library_registry()
    if not library_id or not type_id:
        return False

    type_def = reg.resolve_type(library_id, type_id)
    if type_def is None:
        return False

    feature_defs = getattr(type_def, "features", None) or []
    new_ids = [fdef.id for fdef in feature_defs]

    changed = False

    old_ids = list(getattr(obj, "ConstructionFeatureIds", []) or [])
    for stale_id in set(old_ids) - set(new_ids):
        prop_name = feature_shape_property_name(stale_id)
        if prop_name in obj.PropertiesList:
            try:
                obj.removeProperty(prop_name)
                changed = True
            except Exception:
                pass

    for feature_def in feature_defs:
        shape_name = feature_shape_property_name(feature_def.id)
        if shape_name not in obj.PropertiesList:
            obj.addProperty("Part::PropertyPartShape", shape_name, "Geometry", "Generated solid for construction feature '{}'".format(feature_def.id))
            changed = True
            try:
                obj.setEditorMode(shape_name, 1)
            except Exception:
                pass

        if feature_def.visible_parameter and feature_def.visible_parameter in obj.PropertiesList:
            try:
                obj.setPropertyStatus(feature_def.visible_parameter, "NoRecompute")
            except Exception:
                pass

    if list(getattr(obj, "ConstructionFeatureIds", []) or []) != new_ids:
        try:
            obj.ConstructionFeatureIds = new_ids
            changed = True
        except Exception:
            pass

    return changed


def normalize_material_properties(obj):
    changed = False
    for layer_id in getattr(obj, "ConstructionLayerIds", []) or []:
        prop_name = material_property_name(layer_id)
        if prop_name in obj.PropertiesList:
            if hvac_materials.ensure_persistable_material(obj, prop_name):
                changed = True
    return changed


def _owner_resolver(obj):
    """
    A zero-arg callable that resolves and memoizes obj's owning network on
    first actual use, not eagerly -- hvaclib.getOwnerNetwork() lazily
    imports core/Network.py (a heavy, GUI-only module), so a layer that
    never needs a role-based default (e.g. it declares its own
    default_material_uuid, or has no roles at all) must never trigger that
    import just from being visited.
    """
    resolved = []

    def resolve():
        if not resolved:
            resolved.append(hvaclib.getOwnerNetwork(obj))
        return resolved[0]

    return resolve


def apply_default_layer_materials(obj, library_id, type_id):
    """
    For every construction layer on `obj` that doesn't have a material of
    its own yet, resolve a default in priority order: the layer's own
    ConstructionLayerDef.default_material_uuid -> the owning network's
    DefaultMaterial_<Role> for the layer's first declared role -> nothing.
    Never overwrites a material `obj` already has -- same "only fill in
    what's missing" convention DuctSegment/DuctComponent's own
    applyOwnerDefaults() has always used for every other default.

    Resolves the owning network itself via hvaclib.getOwnerNetwork(obj)
    (reads obj's own OwnerNetworkName), so this works the same for a
    DuctSegment and a DuctComponent -- no parent-junction indirection
    needed the way the old two-slot applyOwnerDefaults() required.
    """
    reg = hvaclib.HVACLibraryService.get_hvac_library_registry()
    type_def = reg.resolve_type(library_id, type_id) if library_id and type_id else None
    layer_defs_by_id = {ldef.id: ldef for ldef in getattr(type_def, "construction", []) or []} if type_def else {}
    get_owner = _owner_resolver(obj)

    for layer_id in getattr(obj, "ConstructionLayerIds", []) or []:
        material_prop = material_property_name(layer_id)
        if material_prop not in obj.PropertiesList:
            continue

        current = getattr(obj, material_prop, None)
        if hvac_materials.is_material_assigned(current):
            continue
        default_material = _resolve_default_material(
            layer_defs_by_id.get(layer_id),
            get_owner,
        )
        if hvac_materials.is_material_assigned(default_material):
            try:
                setattr(obj, material_prop, default_material)
            except Exception:
                pass
        else:
            hvac_materials.ensure_persistable_material(obj, material_prop)


def reset_layer_materials_to_network_defaults(obj):
    """
    Unconditionally overwrite every construction layer's material with the
    owning network's *current* default for that layer's role -- the
    "explicit reset always wins" counterpart to apply_default_layer_materials()
    (which only fills in what's missing). Must be called after
    apply_construction_schema() has already run for obj's current TypeId,
    so obj.ConstructionLayerIds reflects the type being reset to. Returns
    True if anything on `obj` changed.
    """
    reg = hvaclib.HVACLibraryService.get_hvac_library_registry()
    library_id = getattr(obj, "LibraryId", "")
    type_id = getattr(obj, "TypeId", "")
    type_def = reg.resolve_type(library_id, type_id) if library_id and type_id else None
    layer_defs_by_id = {ldef.id: ldef for ldef in getattr(type_def, "construction", []) or []} if type_def else {}
    get_owner = _owner_resolver(obj)

    changed = False
    for layer_id in getattr(obj, "ConstructionLayerIds", []) or []:
        material_prop = material_property_name(layer_id)
        if material_prop not in obj.PropertiesList:
            continue
        default_material = _resolve_default_material(layer_defs_by_id.get(layer_id), get_owner)
        if not hvac_materials.is_material_assigned(default_material):
            default_material = hvac_materials.get_unassigned_material()
        if default_material is not None and not _same_material(getattr(obj, material_prop, None), default_material):
            try:
                setattr(obj, material_prop, default_material)
                changed = True
            except Exception:
                pass
    return changed


def _same_material(a, b):
    """Both are the same material card (by UUID); False when either cannot say."""
    try:
        return bool(str(a.UUID)) and str(a.UUID) == str(b.UUID)
    except Exception:
        return False


def _resolve_default_material(layer_def, get_owner):
    if layer_def is None:
        return None

    if layer_def.default_material_uuid:
        material = hvac_materials.get_material_by_uuid(layer_def.default_material_uuid)
        if material is not None:
            return material

    # default_material_role, if the layer def declares one, always wins over
    # falling back to its own first-listed role -- a layer's roles are
    # listed for semantic-query purposes (see core/Construction.py), not
    # necessarily in "most material-relevant first" order (e.g. a casing
    # layer's roles are typically ["flow_surface", "structural_shell"], but
    # its material clearly belongs to the structural_shell role).
    role = layer_def.default_material_role or (layer_def.roles[0] if layer_def.roles else None)
    if role is None:
        return None

    owner = get_owner()
    if owner is None:
        return None
    return getattr(owner, "DefaultMaterial_" + role_property_suffix(role), None)
