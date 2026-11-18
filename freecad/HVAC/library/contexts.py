# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the HVAC addon.

"""
The frozen context keys (ROADMAP 6.4, item 3): exactly which keys each kind
of call into library code receives. tests/test_context_keys.py checks that
core builds nothing else and that library code reads nothing else, so a new
key is a deliberate API change made here first.

Plain data, no FreeCAD.
"""

# Geometry builders and connection-length measurement (`geometry.backend`
# generator / partscript / static, and `connection_lengths`). Keys every
# call has, then the ones only junction components or only segments get.
# Keys core passes to HVACLibraryRegistry.build_geometry() for the registry's
# own use, removed before library code is called: "obj", the FreeCAD object
# whose property values the registry reads (validation.resolve_params).
CALLER_KEYS = frozenset({"obj"})

GEOMETRY_CONTEXT_KEYS = frozenset(
    {
        # Added by HVACLibraryRegistry for every build.
        "hvac_api",
        "hvac_api_version",
        "loss_api",
        "loss_api_version",
        "construction_layers",
        "properties",
        "type_id",
        "library_id",
        "family",
        # Junction components.
        "connected_ports",
        "center_point",
        "analysis",
        "topology",
        # Segments.
        "start_point",
        "end_point",
        "start_direction",
        "end_direction",
        "profile",
        "profile_x_axis",
        "segment_key",
        "source_object_name",
        "source_index",
        "path_kind",
        "path_edge",
        # Set by the shared fittings themselves, never by core:
        # a PartScript elbow's flange ends, for fittings/features.py,
        "flange_ports",
        # and, from fittings/taps.with_branch_jog for fittings/_common._finish, a
        # side branch moved in to fit the run and its offset piece back to its axis.
        "branch_jog",
        # Read only as an optional fallback by the markers.
        "position",
        # An end connected to an equipment port: that port's opening, as a
        # port-like dict {"profile", "section_params", "profile_x_axis", "position"}
        # (core/Equipment.port_context). Absent otherwise.
        "equipment_port",
    }
)

# Loss functions (`loss`, `loss.variants`).
LOSS_CONTEXT_KEYS = frozenset(
    {
        "hvac_api",
        "hvac_api_version",
        "loss_api",
        "loss_api_version",
        "construction",
        "hydraulic_roughness_mm",
        "center_point",
        "properties",
        "connected_ports",
        "family",
        "flow_class",
        "qualifiers",
        "derived_values",
        "type_id",
        "library_id",
        "air_density",
        "air_kinematic_viscosity",
        # As for geometry: the equipment port an end is connected to, when it is.
        "equipment_port",
    }
)

# Segment friction model factories (`friction`).
FRICTION_CONTEXT_KEYS = frozenset({"friction", "properties", "roughness_mm", "base_model", "type_id", "library_id"})

ALL_CONTEXT_KEYS = GEOMETRY_CONTEXT_KEYS | LOSS_CONTEXT_KEYS | FRICTION_CONTEXT_KEYS
