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
Renders every construction layer's own Layer_<id>_Shape with its own native
Layer_<id>_Material (Materials::PropertyMaterial -- see utils/materials.py
and core/_construction_schema.py), plus every construction feature's own
Feature_<id>_Shape, on a single ViewProvider/FeaturePython object, using
FreeCAD's own native per-face appearance mechanism instead of a custom Coin
scene graph:

    Step 1: Shape is always Part.makeCompound([layer shapes in
            obj.ConstructionLayerIds order, then feature shapes in
            obj.ConstructionFeatureIds order]) (see core/_geometry_apply.py).
            Each Layer_<id>_Shape/Feature_<id>_Shape is one of the very
            shapes that compound was built from, so
            len(Layer_<id>_Shape.Faces)/len(Feature_<id>_Shape.Faces) is
            the compound's real, exact per-layer/per-feature face
            partition -- not a guessed or hardcoded split.
    Step 2: build one appearance entry per face, walking layers then
            features in those same declared orders -- each layer's own
            faces get its own Layer_<id>_Material's appearance. A feature
            has no material of its own (see core/_construction_schema.py);
            it visually inherits its host layer's own appearance when
            "visible" (per its own visible_parameter, if declared),
            otherwise a fully-transparent override -- the mechanism behind
            "hide a feature without regenerating geometry": the feature's
            visible_parameter is marked Prop_NoRecompute (see
            core/_construction_schema.py), so changing it re-fires this
            module's updateData() trigger without ever touching Shape.
    Step 3: assign that per-face list to ViewObject.ShapeAppearance (the
            native per-face App::Material list FreeCAD >= 1.0 renders
            with).

Best-effort throughout: an unassigned/unrecognized material never raises,
it just leaves that layer's faces at FreeCAD's own default appearance.
"""

import FreeCAD

from ..utils import hvaclib
from ..utils import materials as hvac_materials
from . import _construction_schema


def _resolve_type_def(obj):
    """The resolved HVACTypeDef for obj's current LibraryId/TypeId, or None."""
    library_id = getattr(obj, "LibraryId", "")
    type_id = getattr(obj, "TypeId", "")
    if not library_id or not type_id:
        return None
    reg = hvaclib.HVACLibraryService.get_hvac_library_registry()
    return reg.resolve_type(library_id, type_id)


def network_display_flags(net):
    """
    (shown roles, show features) from a network's ShowLayer_<Role> and
    ShowFeatures properties; everything shown when net is None or a
    property is missing.
    """
    from ..library.construction import ALL_LAYER_ROLES, role_property_suffix

    shown = {role for role in ALL_LAYER_ROLES if bool(getattr(net, "ShowLayer_" + role_property_suffix(role), True))}
    return shown, bool(getattr(net, "ShowFeatures", True))


def layer_shown(roles, shown_roles):
    """A layer is drawn when any of its roles is shown; a layer with no role is always drawn."""
    roles = list(roles or [])
    return not roles or any(role in shown_roles for role in roles)


def _layer_roles_by_id(obj):
    type_def = _resolve_type_def(obj)
    return {ldef.id: list(ldef.roles) for ldef in getattr(type_def, "construction", None) or []}


def _feature_defs_by_id(obj):
    type_def = _resolve_type_def(obj)
    return {fdef.id: fdef for fdef in getattr(type_def, "features", None) or []}


def hidden_parts(obj):
    """
    (hidden layer ids, hidden feature ids) for `obj` right now: a layer whose
    roles are all switched off on its network (ShowLayer_<Role>), and a
    feature when the network's ShowFeatures is off or its own
    visible_parameter (e.g. FlangeVisible) is off. Nothing is hidden when
    the object's network or type cannot be read.
    """
    try:
        shown_roles, show_features = network_display_flags(hvaclib.getOwnerNetwork(obj))
        roles_by_id = _layer_roles_by_id(obj)
        feature_defs_by_id = _feature_defs_by_id(obj)
    except Exception:
        return set(), set()
    hidden_layers = {
        layer_id
        for layer_id in getattr(obj, "ConstructionLayerIds", []) or []
        if not layer_shown(roles_by_id.get(layer_id), shown_roles)
    }
    hidden_features = set()
    for feature_id in getattr(obj, "ConstructionFeatureIds", []) or []:
        feature_def = feature_defs_by_id.get(feature_id)
        visible = show_features
        if feature_def is not None and feature_def.visible_parameter:
            visible = visible and bool(getattr(obj, feature_def.visible_parameter, True))
        if not visible:
            hidden_features.add(feature_id)
    return hidden_layers, hidden_features


def displayed_parts(obj, hidden=None):
    """
    [(kind, id, shape), ...] making up `obj`'s displayed Shape: every layer
    with a real shape, then every feature, in declared order, leaving out
    the hidden ones (see hidden_parts). Hidden parts are left out instead of
    drawn transparent: FreeCAD draws a selected object with one
    transparency for all its faces, so a transparent layer made the whole
    object vanish to a wireframe when selected.
    """
    hidden_layers, hidden_features = hidden if hidden is not None else hidden_parts(obj)
    parts = []
    for layer_id in getattr(obj, "ConstructionLayerIds", []) or []:
        shape = getattr(obj, _construction_schema.shape_property_name(layer_id), None)
        if layer_id not in hidden_layers and _has_geometry(shape):
            parts.append(("layer", layer_id, shape))
    for feature_id in getattr(obj, "ConstructionFeatureIds", []) or []:
        shape = getattr(obj, _construction_schema.feature_shape_property_name(feature_id), None)
        if feature_id not in hidden_features and _has_geometry(shape):
            parts.append(("feature", feature_id, shape))
    return parts


# The (kind, id) list each object's Shape was last built from, so a re-render
# only rebuilds the displayed compound when what is shown actually changed.
_display_keys = {}


def display_shape_is_current(obj, parts=None):
    """True when obj.Shape already holds exactly the parts displayed_parts() gives."""
    parts = displayed_parts(obj) if parts is None else parts
    key = (getattr(getattr(obj, "Document", None), "Name", ""), getattr(obj, "Name", ""))
    signature = _signature(parts)
    return _display_keys.get(key) == signature and _face_count(getattr(obj, "Shape", None)) == sum(
        sig[2] for sig in signature
    )


def refresh_display_shape(obj, force=False):
    """
    Rebuild `obj.Shape` from its shown layers and features (displayed_parts).
    Each layer's and feature's own shape property is untouched, so nothing
    is lost: switching a layer back on just puts it back in the compound.
    Returns the displayed parts.
    """
    import Part

    parts = displayed_parts(obj)
    key = (getattr(getattr(obj, "Document", None), "Name", ""), getattr(obj, "Name", ""))
    signature = _signature(parts)
    current = getattr(obj, "Shape", None)
    if force or _display_keys.get(key) != signature or _face_count(current) != sum(sig[2] for sig in signature):
        # Only the display changed: don't leave the object marked for a (costly) geometry rebuild.
        was_touched = "Touched" in list(getattr(obj, "State", []) or [])
        obj.Shape = Part.makeCompound([shape for _kind, _id, shape in parts])
        if not was_touched and hasattr(obj, "purgeTouched"):
            obj.purgeTouched()
        _display_keys[key] = signature
    return parts


def _trigger_property_names(obj):
    """
    Property names whose change should trigger a re-render for this
    object's own current construction -- passed to
    ViewProvider.updateData(obj, prop) by DuctSegmentViewProvider/
    DuctComponentViewProvider. Computed per-object (not a fixed tuple)
    since which Layer_<id>_*/Feature_<id>_* properties exist, and which
    ordinary property each feature's own visible_parameter names, depends
    on the object's currently-selected type.
    """
    names = []
    for layer_id in getattr(obj, "ConstructionLayerIds", []) or []:
        names.append(_construction_schema.shape_property_name(layer_id))
        names.append(_construction_schema.material_property_name(layer_id))

    feature_defs_by_id = _feature_defs_by_id(obj)
    for feature_id in getattr(obj, "ConstructionFeatureIds", []) or []:
        names.append(_construction_schema.feature_shape_property_name(feature_id))
        feature_def = feature_defs_by_id.get(feature_id)
        if feature_def is not None and feature_def.visible_parameter:
            names.append(feature_def.visible_parameter)

    return names


def is_trigger_property(obj, prop):
    """True if a changed property named `prop` on `obj` should trigger a re-render."""
    return prop in _trigger_property_names(obj)


# Guards against a real FreeCAD re-entrancy quirk: querying a
# Materials::PropertyMaterial value's own appearance (e.g.
# hasAppearanceProperty()) can synchronously re-fire updateData() for that
# same property *before* the original call returns, which would otherwise
# recurse until the interpreter's stack limit crashes it. Keyed by the App
# object's id() -- one re-render per object may be genuinely in flight at
# any time, but never nested inside itself.
_rendering = set()


def _signature(parts):
    return tuple((kind, part_id, _face_count(shape), _edge_count(shape)) for kind, part_id, shape in parts)


def _has_geometry(shape):
    """True for a shape with faces or, like a marker or a failed fitting's fallback, only lines."""
    return bool(_face_count(shape) or _edge_count(shape))


def _edge_count(shape):
    if shape is None:
        return 0
    try:
        if shape.isNull():
            return 0
        return len(shape.Edges)
    except Exception:
        return 0


def _face_count(shape):
    if shape is None:
        return 0
    try:
        if shape.isNull():
            return 0
        return len(shape.Faces)
    except Exception:
        return 0


def _schedule_display_refresh(vobj):
    obj = vobj.Object

    def run():
        try:
            if getattr(obj, "Document", None) is None:
                return
            refresh_display_shape(obj)
            apply_component_appearance(vobj)
        except Exception:
            pass

    from PySide import QtCore

    QtCore.QTimer.singleShot(0, run)


def apply_component_appearance(vobj, from_view_update=False):
    """
    Re-render `vobj` (a DuctSegment/DuctComponent ViewObject): first make
    its Shape hold only the shown layers and features (refresh_display_shape,
    so a hidden layer is simply not drawn), then colour each shown layer's
    faces from its own Layer_<id>_Material and each shown feature's faces
    from its host layer's appearance. `from_view_update` says the call comes
    from a view provider's updateData. Safe to call any time; does nothing if
    the object has no faces at all, no ShapeAppearance property (older
    FreeCAD), or nothing resolves to a usable appearance.
    """
    obj = getattr(vobj, "Object", None)
    if obj is None or not hasattr(vobj, "ShapeAppearance"):
        return

    key = id(obj)
    if key in _rendering:
        return
    _rendering.add(key)
    try:
        # Step 1: the displayed compound must hold the shown layers and features only. Changing
        # obj.Shape from inside a view update leaves FreeCAD drawing the old mesh, so there an
        # out-of-date compound is rebuilt on the next event-loop turn, which re-renders after it.
        parts = displayed_parts(obj)
        if not display_shape_is_current(obj, parts):
            if from_view_update:
                _schedule_display_refresh(vobj)
                return
            parts = refresh_display_shape(obj)
        if not parts:
            return

        # Step 2: one appearance per face, in the compound's own order (layers, then features).
        feature_defs_by_id = _feature_defs_by_id(obj)
        layer_appearances = {}
        for layer_id in getattr(obj, "ConstructionLayerIds", []) or []:
            layer_appearances[layer_id] = hvac_materials.get_view_appearance(
                getattr(obj, _construction_schema.material_property_name(layer_id), None)
            )
        per_part = []
        for kind, part_id, shape in parts:
            if kind == "layer":
                appearance = layer_appearances.get(part_id)
            else:
                feature_def = feature_defs_by_id.get(part_id)
                appearance = layer_appearances.get(feature_def.host_layer) if feature_def is not None else None
            per_part.append((appearance, _face_count(shape)))
        # Lines only (a marker, a failed fitting's fallback): no faces to colour.
        if not any(count for _appearance, count in per_part) or all(a is None for a, _count in per_part):
            return
        # A part with no usable appearance still needs an entry per face, so later entries stay aligned.
        default_appearance = FreeCAD.Material() if any(a is None for a, _count in per_part) else None
        entries = []
        for appearance, count in per_part:
            entries.extend([appearance if appearance is not None else default_appearance] * count)

        try:
            vobj.ShapeAppearance = entries
        except Exception:
            pass
    finally:
        _rendering.discard(key)
