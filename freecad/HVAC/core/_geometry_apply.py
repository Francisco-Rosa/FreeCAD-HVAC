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
Shared "apply a GeometryResult onto a FreeCAD object" logic for DuctSegment
and DuctComponent -- the one piece of execute() that was genuinely identical
between the two (everything else, like trim planes vs. connection lengths,
was already different). Internal to core/ -- not part of the stable
library_api.py surface for library/generator authors.
"""

import Part

from . import _construction_schema


def apply_geometry_result(obj, result):
    """
    Write Layer_<id>_Shape (see core/_construction_schema.py) for every
    layer in obj.ConstructionLayerIds from result.layers, then the same for
    every feature in obj.ConstructionFeatureIds from result.features, then
    derive Shape as the compound of whichever layers/features actually have
    a real shape -- layers first, then features, each group in its own
    declared order -- so the ViewProvider can work out per-layer/per-feature
    face ranges without guessing (see core/_component_appearance.py). A
    feature absent from result.features (disabled this build -- see
    library/Library.py's build_geometry()) gets an empty Feature_<id>_Shape
    and contributes nothing to the compound, same as a layer with no shape.
    """
    layer_ids = list(getattr(obj, "ConstructionLayerIds", []) or [])
    ordered_shapes = []

    for layer_id in layer_ids:
        layer_geometry = result.layers.get(layer_id)
        shape = _entry_shape(layer_geometry)
        setattr(obj, _construction_schema.shape_property_name(layer_id), shape if shape is not None else Part.Shape())
        if shape is not None:
            ordered_shapes.append(shape)

    feature_ids = list(getattr(obj, "ConstructionFeatureIds", []) or [])
    for feature_id in feature_ids:
        feature_geometry = result.features.get(feature_id)
        shape = _entry_shape(feature_geometry)
        setattr(obj, _construction_schema.feature_shape_property_name(feature_id), shape if shape is not None else Part.Shape())
        if shape is not None:
            ordered_shapes.append(shape)

    # Layers and features switched off on the network are left out of the
    # displayed compound (their own shape properties above stay complete).
    try:
        from . import _component_appearance

        hidden_layers, hidden_features = _component_appearance.hidden_parts(obj)
    except Exception:
        hidden_layers, hidden_features = set(), set()
    if hidden_layers or hidden_features:
        ordered_shapes = [
            shape
            for kind, part_id, shape in _ordered_parts(obj, result)
            if not (kind == "layer" and part_id in hidden_layers)
            and not (kind == "feature" and part_id in hidden_features)
        ]
    obj.Shape = Part.makeCompound(ordered_shapes)


def _ordered_parts(obj, result):
    """[(kind, id, shape), ...] of the result's real layer and feature shapes, layers first, in declared order."""
    parts = []
    for layer_id in list(getattr(obj, "ConstructionLayerIds", []) or []):
        shape = _entry_shape(result.layers.get(layer_id))
        if shape is not None:
            parts.append(("layer", layer_id, shape))
    for feature_id in list(getattr(obj, "ConstructionFeatureIds", []) or []):
        shape = _entry_shape(result.features.get(feature_id))
        if shape is not None:
            parts.append(("feature", feature_id, shape))
    return parts


def apply_computed_properties(obj, type_def, result):
    """
    Copy result.computed_properties onto matching declared type-schema
    properties (see library/Library.py's HVACPropertyDef) that also exist on
    obj -- a computed-property key that isn't declared by the active type,
    or doesn't exist on obj, is silently ignored (property creation stays
    exclusively _type_schema.py's job). A declared read-only (editor_mode 1)
    property that this call's computed_properties no longer reports is reset
    to its schema default instead of retaining a stale value; editable
    (editor_mode 0) properties are only ever touched when computed_properties
    explicitly names them.
    """
    computed = result.computed_properties or {}
    changed = False
    for pdef in getattr(type_def, "properties", []) or []:
        if pdef.name not in obj.PropertiesList:
            continue
        if pdef.name in computed:
            value = computed[pdef.name]
        elif int(getattr(pdef, "editor_mode", 0) or 0) == 1:
            value = getattr(pdef, "default", None)
            if value is None:
                continue
        else:
            continue
        try:
            if getattr(obj, pdef.name, None) != value:
                setattr(obj, pdef.name, value)
                changed = True
        except Exception:
            pass
    return changed


def apply_property_choices(obj, type_def, result):
    """
    Narrow each drop-down property of `obj` to the choices
    result.property_choices gives for it (kept in the type-def's own order),
    and give a drop-down the backend did not name all of its type-def
    choices back. A current value that is no longer offered falls back to
    the type-def default, else the first choice. Returns True if anything
    changed.

    Used where a choice only makes sense for some geometries (e.g. a fan
    outlet transition only where the outlet and the duct differ), so the
    user is never offered a choice the fitting cannot build.
    """
    from . import _type_schema

    offered = result.property_choices or {}
    changed = False
    for pdef in getattr(type_def, "properties", []) or []:
        if pdef.prop_type != "App::PropertyEnumeration" or pdef.name not in obj.PropertiesList:
            continue
        declared = [str(choice) for choice in (getattr(pdef, "validation", {}) or {}).get("enum", [])]
        allowed = offered.get(pdef.name)
        choices = [choice for choice in declared if allowed is None or choice in allowed] or declared
        if _type_schema.set_enumeration_choices(obj, pdef, choices):
            changed = True
    return changed


def _entry_shape(geometry):
    """A LayerGeometry's/FeatureGeometry's own shape, or None if absent/null."""
    if geometry is None:
        return None
    shape = geometry.shape
    if shape is None:
        return None
    try:
        if shape.isNull():
            return None
    except Exception:
        pass
    return shape
