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
The semantic construction query API: a read-only view of one DuctSegment/
DuctComponent's own construction layers, queryable only by standardized
role (see library/construction.py's ROLE_* vocabulary) -- never by a
library-chosen layer id. This is the one seam downstream modules (airflow/
sizing hydraulic roughness, acoustic calculations, thermal calculations,
duct detailing/fabrication) are meant to read construction through, so they
stay generic across whatever arbitrary layers a library type declares.

FreeCAD-aware adapter (reads a real object's own Layer_<id>_Shape/
Layer_<id>_Material properties -- see core/_construction_schema.py -- plus
the resolved type-def's own declared roles), the same role
core/_analysis_adapter.py plays for the analysis layer. Internal to core/ --
not part of the stable library_api.py surface for library/generator authors.
"""

from dataclasses import dataclass, field

from ..utils import hvaclib
from ..library.construction import (
    ROLE_FLOW_SURFACE,
    ROLE_STRUCTURAL_SHELL,
    ROLE_THERMAL_INSULATION,
    ROLE_ACOUSTIC_ABSORBER,
    ROLE_ACOUSTIC_LINER,
)
from . import _construction_schema
from ..utils import materials as hvac_materials


@dataclass
class ConstructionLayer:
    """One construction layer as built for a real object -- its own generated Shape/material, not just its definition."""
    id: str
    roles: list = field(default_factory=list)
    shape: object = None
    material: object = None
    thickness_mm: "float | None" = None

    def has_role(self, role):
        return role in self.roles


@dataclass
class ConstructionFeature:
    """
    One construction feature as built for a real object -- its own
    generated Shape, not just its definition. Unlike a layer, `role` is a
    single free-form string (no standardized vocabulary -- see
    library/construction.py's ConstructionFeatureDef), and `enabled`/
    `visible` reflect the *current* value of whatever property each was
    resolved from (getattr'd fresh off the object, not a stale snapshot
    from whenever geometry was last generated).
    """
    id: str
    role: str = ""
    host_layer: str = ""
    shape: object = None
    enabled: bool = True
    visible: bool = True


class Construction:
    """Queryable view of one object's own construction layers/features, in the type-def's declared order."""

    def __init__(self, layers, features=()):
        self._layers = list(layers)
        self._features = list(features)

    def layers(self):
        return list(self._layers)

    def layer(self, layer_id):
        for layer in self._layers:
            if layer.id == layer_id:
                return layer
        return None

    def layers_with_role(self, role):
        return [layer for layer in self._layers if role in layer.roles]

    def flow_surface(self):
        """The layer facing the airstream, or None if no layer declares that role."""
        layers = self.layers_with_role(ROLE_FLOW_SURFACE)
        return layers[0] if layers else None

    def structural_layers(self):
        return self.layers_with_role(ROLE_STRUCTURAL_SHELL)

    def thermal_layers(self):
        return self.layers_with_role(ROLE_THERMAL_INSULATION)

    def acoustic_layers(self):
        return [
            layer for layer in self._layers
            if ROLE_ACOUSTIC_ABSORBER in layer.roles or ROLE_ACOUSTIC_LINER in layer.roles
        ]

    def hydraulic_roughness(self, default=None):
        """Effective absolute roughness of the flow-surface layer, in mm.

        A native material-card ``HydraulicRoughness`` (or legacy
        ``Roughness``) value is preferred. Returning the caller's fallback
        keeps unassigned materials and cards without that property
        compatible with the network default.
        """
        layer = self.flow_surface()
        if layer is None:
            return default
        value = hvac_materials.get_hydraulic_roughness_mm(layer.material)
        return value if value is not None else default

    def acoustic_impedance(self, frequency_hz=None, default=None):
        """Return the construction's declared acoustic impedance in Pa*s/m.

        A frequency argument is accepted for a stable future-facing API;
        current native cards expose a scalar value.  The flow-facing liner
        takes precedence, followed by an absorber and then any other layer.
        """
        del frequency_hz
        ordered = []
        flow = self.flow_surface()
        if flow is not None:
            ordered.append(flow)
        ordered.extend(layer for layer in self.acoustic_layers() if layer not in ordered)
        ordered.extend(layer for layer in self._layers if layer not in ordered)
        for layer in ordered:
            value = hvac_materials.get_physical_value_as(
                layer.material, "AcousticImpedance", "Pa*s/m"
            )
            if value is not None:
                return value
        return default

    def overall_u_value(self, inside_surface_resistance=0.0,
                        outside_surface_resistance=0.0, default=None):
        """Overall thermal transmittance in W/(m^2*K).

        Layer resistance is ``thickness / conductivity``.  Layers without
        a declared thickness or native ThermalConductivity are ignored; if
        no physical resistance is available, ``default`` is returned.
        Optional surface resistances are in m^2*K/W.
        """
        resistance = float(inside_surface_resistance) + float(outside_surface_resistance)
        physical_layers = 0
        for layer in self._layers:
            if layer.thickness_mm is None or layer.thickness_mm <= 0.0:
                continue
            conductivity = hvac_materials.get_physical_value_as(
                layer.material, "ThermalConductivity", "W/m/K"
            )
            if conductivity is None or conductivity <= 0.0:
                continue
            resistance += (float(layer.thickness_mm) / 1000.0) / conductivity
            physical_layers += 1
        if physical_layers == 0 or resistance <= 0.0:
            return default
        return 1.0 / resistance

    def features(self):
        return list(self._features)

    def feature(self, feature_id):
        for feature in self._features:
            if feature.id == feature_id:
                return feature
        return None

    def features_with_role(self, role):
        return [feature for feature in self._features if feature.role == role]


def construction_for(obj):
    """
    Build a Construction for `obj` (a DuctSegment/DuctComponent) from its
    own obj.ConstructionLayerIds/Layer_<id>_Shape/Layer_<id>_Material and
    obj.ConstructionFeatureIds/Feature_<id>_Shape properties, with each
    layer's roles and each feature's role/host_layer resolved from the
    currently-selected type's own declared construction (empty roles for a
    not-yet-migrated type's single implicit layer; no features at all for a
    type that declares none). A feature's own enabled/visible are read
    fresh off `obj`'s current enabled_parameter/visible_parameter value,
    not cached from whenever its geometry was last generated.
    """
    reg = hvaclib.HVACLibraryService.get_hvac_library_registry()
    library_id = getattr(obj, "LibraryId", "")
    type_id = getattr(obj, "TypeId", "")
    type_def = reg.resolve_type(library_id, type_id) if library_id and type_id else None
    layer_defs_by_id = {ldef.id: ldef for ldef in getattr(type_def, "construction", []) or []} if type_def else {}
    feature_defs_by_id = {fdef.id: fdef for fdef in getattr(type_def, "features", []) or []} if type_def else {}

    layers = []
    for layer_id in getattr(obj, "ConstructionLayerIds", []) or []:
        layer_def = layer_defs_by_id.get(layer_id)
        layers.append(
            ConstructionLayer(
                id=layer_id,
                roles=list(layer_def.roles) if layer_def is not None else [],
                shape=getattr(obj, _construction_schema.shape_property_name(layer_id), None),
                material=getattr(obj, _construction_schema.material_property_name(layer_id), None),
                thickness_mm=(
                    float(getattr(obj, layer_def.thickness_property))
                    if layer_def is not None and layer_def.thickness_property
                    and hasattr(obj, layer_def.thickness_property)
                    else None
                ),
            )
        )

    features = []
    for feature_id in getattr(obj, "ConstructionFeatureIds", []) or []:
        feature_def = feature_defs_by_id.get(feature_id)
        enabled = True
        visible = True
        if feature_def is not None:
            if feature_def.enabled_parameter:
                enabled = bool(getattr(obj, feature_def.enabled_parameter, True))
            if feature_def.visible_parameter:
                visible = bool(getattr(obj, feature_def.visible_parameter, True))
        features.append(
            ConstructionFeature(
                id=feature_id,
                role=feature_def.role if feature_def is not None else "",
                host_layer=feature_def.host_layer if feature_def is not None else "",
                shape=getattr(obj, _construction_schema.feature_shape_property_name(feature_id), None),
                enabled=enabled,
                visible=visible,
            )
        )

    return Construction(layers, features)
