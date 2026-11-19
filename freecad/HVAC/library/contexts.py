# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the HVAC addon.

"""
The frozen context keys (ROADMAP 6.4, item 3): exactly which keys each kind
of call into library code receives, each with a one-line meaning.
tests/test_context_keys.py checks that core builds nothing else and that
library code reads nothing else, so a new key is a deliberate API change
made here first. docs/library-api.md lists them (tools/api_reference.py).

Plain data, no FreeCAD.
"""

# Keys core passes to HVACLibraryRegistry.build_geometry() for the registry's
# own use, removed before library code is called.
CALLER_CONTEXT = {
    "obj": "The FreeCAD object being built; the registry reads its property values (validation.resolve_params)."
}

# Geometry builders and connection-length measurement (`geometry.backend`
# generator / partscript / static, and `connection_lengths`). Keys every
# call has, then the ones only junction components or only segments get.
GEOMETRY_CONTEXT = {
    # Added by HVACLibraryRegistry for every build.
    "hvac_api": "HVACLibraryAPI, the geometry API (see the reference above).",
    "hvac_api_version": "HVACLibraryAPI.API_VERSION.",
    "loss_api": "HVACLossAPI, the loss API.",
    "loss_api_version": "HVACLossAPI.API_VERSION.",
    "construction_layers": "The type-def's construction layers, in order (for build_layered_geometry).",
    "properties": "The type's resolved property values: {name: value}.",
    "type_id": "The type-def id being built.",
    "library_id": "The library id.",
    "family": "The classifier family (e.g. 'branch.tee', 'curved_segment').",
    # Junction components.
    "connected_ports": "Junction: the ports, one dict per connected duct, pointing out of the node.",
    "center_point": "Junction: the node position.",
    "analysis": "Junction: the node's topology analysis (collinear pairs, common leg, ...).",
    "topology": "Junction: 'through', 'branch', 'cross', 'multiport' or 'end'.",
    # Segments.
    "start_point": "Segment: the trimmed start point.",
    "end_point": "Segment: the trimmed end point.",
    "start_direction": "Segment: the path tangent at the start, pointing along the duct.",
    "end_direction": "Segment: the path tangent at the end, pointing along the duct.",
    "profile": "Segment: 'Circular', 'Rectangular' or 'Oval'.",
    "profile_x_axis": "Segment: the section's x axis (Width direction), or None.",
    "segment_key": "Segment: its stable key in the network.",
    "source_object_name": "Segment: the base sketch or Draft object it was drawn from.",
    "source_index": "Segment: its edge index in that object.",
    "path_kind": "Segment: 'straight' or 'curved'.",
    "path_edge": "Segment: the trimmed path edge of a curved segment, else None.",
    # Set by the shared fittings themselves, never by core.
    "flange_ports": "Set by a PartScript elbow: its flange ends, for fittings/features.py.",
    "branch_jog": "Set by fittings/taps.with_branch_jog: a side branch moved in to fit the run.",
    # Read only as an optional fallback by the markers.
    "position": "Marker fallback position.",
    "equipment_port": (
        "An end connected to an equipment port: that opening as a port-like dict "
        "(profile, section_params, profile_x_axis, position). Absent otherwise."
    ),
}

# Loss functions (`loss` and its variants).
LOSS_CONTEXT = {
    "hvac_api": "HVACLibraryAPI.",
    "hvac_api_version": "HVACLibraryAPI.API_VERSION.",
    "loss_api": "HVACLossAPI, the loss API.",
    "loss_api_version": "HVACLossAPI.API_VERSION.",
    "construction": "The component's construction (layers and materials).",
    "hydraulic_roughness_mm": "Roughness of the air-side surface, mm.",
    "center_point": "The node position.",
    "properties": "The type's resolved property values.",
    "connected_ports": "The ports, each with flow_rate_lps, velocity_ms and reynolds added by the solver.",
    "family": "The classifier family.",
    "flow_class": "'diverging', 'converging', 'expansion', ... or '' when unknown.",
    "qualifiers": "Classifier qualifiers, e.g. {'common_leg': 'branch'}.",
    "derived_values": "Values the fitting or classifier derived, e.g. {'area_ratio': 0.5}.",
    "type_id": "The type-def id.",
    "library_id": "The library id.",
    "air_density": "Air density, kg/m3.",
    "air_kinematic_viscosity": "Air kinematic viscosity, m2/s.",
    "equipment_port": "As for geometry: the equipment port an end is connected to, when it is.",
}

# Segment friction model factories (`friction`).
FRICTION_CONTEXT = {
    "friction": "The analysis.friction module (DarcyWeisbach, ScaledFriction, ...).",
    "properties": "The segment type's property values.",
    "roughness_mm": "Roughness of the duct surface, mm.",
    "base_model": "The network's own friction model, for a factory to scale or wrap.",
    "type_id": "The segment type-def id.",
    "library_id": "The library id.",
}

CALLER_KEYS = frozenset(CALLER_CONTEXT)
GEOMETRY_CONTEXT_KEYS = frozenset(GEOMETRY_CONTEXT)
LOSS_CONTEXT_KEYS = frozenset(LOSS_CONTEXT)
FRICTION_CONTEXT_KEYS = frozenset(FRICTION_CONTEXT)

ALL_CONTEXT_KEYS = GEOMETRY_CONTEXT_KEYS | LOSS_CONTEXT_KEYS | FRICTION_CONTEXT_KEYS
