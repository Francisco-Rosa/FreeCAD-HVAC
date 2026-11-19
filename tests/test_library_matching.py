"""
Tests for the registry-driven library type-matching engine: descriptor
selection metadata (HVACSelectionDef), per-library match indexes, automatic
selection (select_type), compatibility checks (matches_type), and the sticky
current-selection policy (resolve_sticky_type) -- see
freecad/HVAC/library/Library.py and docs/library-guide.md.
"""

import json
import os

import pytest

import conftest  # noqa: F401 -- installs FreeCAD/FreeCADGui/Part/PySide stubs
from freecad.HVAC.library.Library import (
    HVACLibrary,
    HVACLibraryRegistry,
    HVACSelectionDef,
    HVACTypeDef,
    HVACTypeMatchRequest,
)
from freecad.HVAC.utils import hvaclib

LIBRARIES_ROOT = os.path.join(os.path.dirname(__file__), "..", "freecad", "HVAC", "libraries")


def _type_def(id_, category, family, topology="generic", profiles=None, constraints=None, kind="model", priority=0):
    return HVACTypeDef(
        id=id_,
        label=id_,
        category=category,
        topology=topology,
        family=family,
        profiles=list(profiles or []),
        constraints=dict(constraints or {}),
        selection=HVACSelectionDef(kind=kind, priority=priority),
    )


def _library_with(*type_defs):
    lib = HVACLibrary(id="lib", label="Lib", root_path="", generators_package="")
    for t in type_defs:
        lib.add_type(t)
    return lib


def _ports(n, profile="Circular"):
    return [{"profile": profile} for _ in range(n)]


def _junction_request(topology, family, profile, ports):
    return HVACTypeMatchRequest(
        category="junction",
        topology=topology,
        family=family,
        profile=profile,
        context={"connected_ports": ports, "topology": topology},
    )


def _junction_request_ctx(topology, family, profile, ports, **extra_context):
    ctx = {"connected_ports": ports, "topology": topology}
    ctx.update(extra_context)
    return HVACTypeMatchRequest(category="junction", topology=topology, family=family, profile=profile, context=ctx)


def _segment_request(family, profile):
    return HVACTypeMatchRequest(
        category="segment", topology="generic", family=family, profile=profile, context={"profile": profile}
    )


# ----------------------------------------------------------------------
# Descriptor loading
# ----------------------------------------------------------------------


def test_selection_defaults_when_missing_from_json(tmp_path):
    type_file = tmp_path / "through_generic.json"
    type_file.write_text(
        json.dumps(
            {
                "id": "through_generic",
                "label": "Through Generic",
                "category": "junction",
                "geometry": {"backend": "generator", "module": "m", "function": "f"},
                "topology": "through",
                "family": ["through.straight"],
                "profiles": ["Generic"],
            }
        )
    )

    reg = HVACLibraryRegistry()
    type_def = reg._load_type_def_file(str(type_file))

    assert type_def.selection.kind == "model"
    assert type_def.selection.priority == 0


def test_selection_explicit_model_metadata_loads(tmp_path):
    type_file = tmp_path / "branch_tee_generic.json"
    type_file.write_text(
        json.dumps(
            {
                "id": "branch_tee_generic",
                "label": "Tee",
                "category": "junction",
                "geometry": {"backend": "generator", "module": "m", "function": "f"},
                "topology": "branch",
                "family": ["branch.tee"],
                "profiles": ["Circular"],
                "selection": {"kind": "model", "priority": 50},
            }
        )
    )

    reg = HVACLibraryRegistry()
    type_def = reg._load_type_def_file(str(type_file))

    assert type_def.selection.kind == "model"
    assert type_def.selection.priority == 50


def test_selection_explicit_placeholder_metadata_loads(tmp_path):
    type_file = tmp_path / "branch_marker.json"
    type_file.write_text(
        json.dumps(
            {
                "id": "branch_marker",
                "label": "Marker",
                "category": "junction",
                "geometry": {"backend": "generator", "module": "m", "function": "f"},
                "topology": "branch",
                "family": ["branch.tee"],
                "profiles": ["Generic"],
                "selection": {"kind": "placeholder", "priority": 0},
            }
        )
    )

    reg = HVACLibraryRegistry()
    type_def = reg._load_type_def_file(str(type_file))

    assert type_def.selection.kind == "placeholder"


def test_invalid_selection_kind_raises(tmp_path):
    type_file = tmp_path / "bad.json"
    type_file.write_text(
        json.dumps(
            {
                "id": "bad",
                "label": "Bad",
                "category": "junction",
                "geometry": {"backend": "generator", "module": "m", "function": "f"},
                "topology": "branch",
                "family": ["branch.tee"],
                "selection": {"kind": "not_a_real_kind"},
            }
        )
    )

    reg = HVACLibraryRegistry()
    try:
        reg._load_type_def_file(str(type_file))
    except ValueError as exc:
        assert "not_a_real_kind" in str(exc)
    else:
        raise AssertionError("Expected invalid selection.kind to raise")


# ----------------------------------------------------------------------
# Indexing
# ----------------------------------------------------------------------


def test_model_match_index_expands_multiple_families_not_profiles():
    # The index key is (category, topology, family) only -- see
    # HVACMatchKey. A type with several declared profiles is indexed once
    # per family entry, not once per (family, profile) pair; profile
    # compatibility is checked later, per-candidate, by select_type().
    t = _type_def(
        "branch_tee_generic",
        "junction",
        family=["branch.tee", "branch.tee.3d"],
        topology="branch",
        profiles=["Circular", "Rectangular"],
    )
    lib = _library_with(t)

    index = lib.model_match_index
    for fam in ("branch.tee", "branch.tee.3d"):
        key = [k for k in index if k.family == fam]
        assert len(key) == 1
        assert index[key[0]] == [t]


def test_generic_profile_type_is_indexed_by_structure_only():
    # A Generic-profile placeholder is indexed the same way as any other
    # type -- by (category, topology, family) -- profile plays no part in
    # the index itself, only in select_type()'s later ranking.
    t = _type_def(
        "through_marker",
        "junction",
        family=["through.bend"],
        topology="through",
        profiles=["Generic"],
        kind="placeholder",
    )
    lib = _library_with(t)

    index = lib.placeholder_match_index
    matches = [k for k in index if k.family == "through.bend"]
    assert len(matches) == 1
    assert index[matches[0]] == [t]


def test_empty_profiles_list_still_indexed_by_structure_only():
    # Existing repo semantics: profiles=[] is profile-independent, same as
    # ["Generic"] -- see validation.py / docs/library-guide.md. It doesn't
    # change how the type is indexed (still keyed by structure only).
    t = _type_def("multiport_generic", "junction", family=["multiport.multiport"], topology="multiport", profiles=[])
    lib = _library_with(t)

    index = lib.model_match_index
    matches = [k for k in index if k.family == "multiport.multiport"]
    assert len(matches) == 1
    assert index[matches[0]] == [t]


def test_indexes_isolated_per_library():
    t1 = _type_def("a", "segment", family=["straight_segment"], profiles=["Circular"])
    t2 = _type_def("b", "segment", family=["straight_segment"], profiles=["Circular"])
    lib1 = _library_with(t1)
    lib2 = _library_with(t2)

    ids1 = {t.id for cands in lib1.model_match_index.values() for t in cands}
    ids2 = {t.id for cands in lib2.model_match_index.values() for t in cands}
    assert ids1 == {"a"}
    assert ids2 == {"b"}


def test_reindex_after_add_type_reflects_new_type_not_stale():
    lib = _library_with()
    lib._ensure_match_index()  # force an initial (empty) index build
    assert lib.model_match_index == {}

    t = _type_def("new_type", "segment", family=["straight_segment"], profiles=["Circular"])
    lib.add_type(t)

    ids = {tt.id for cands in lib.model_match_index.values() for tt in cands}
    assert ids == {"new_type"}


# ----------------------------------------------------------------------
# list_types(): the manual "change type" UI (TaskPanel.TaskPanelTypeEditor)
# and HVACLibraryService.all_type_defs_for_object() both call this with a
# junction's connected_ports rather than a single profile string, since a
# component's own Profile can collapse several distinct connected-port
# profiles into one "Mixed" label that no type ever literally declares.
# ----------------------------------------------------------------------


def test_list_types_plain_profile_still_filters_by_membership():
    # No connected_ports given -- unchanged, pre-existing behavior.
    circular = _type_def("circular_straight", "segment", family=["straight_segment"], profiles=["Circular"])
    rectangular = _type_def("rectangular_straight", "segment", family=["straight_segment"], profiles=["Rectangular"])
    lib = _library_with(circular, rectangular)

    result = lib.list_types(category="segment", profile="Circular")
    assert [t.id for t in result] == ["circular_straight"]


def test_list_types_mixed_profile_connected_ports_does_not_exclude_every_type():
    # This is the bug a plain profile="Mixed" string used to cause: every
    # type's own `profiles` list never literally contains "Mixed", so the
    # old membership check dropped every candidate, including the Generic
    # fallback -- leaving the manual "change type" dropdown empty.
    concrete = _type_def(
        "through_transition_angled",
        "junction",
        family=["through.transition"],
        topology="through",
        profiles=["Circular", "Rectangular", "Oval"],
        priority=50,
    )
    generic = _type_def(
        "through_generic",
        "junction",
        family=["through.transition"],
        topology="through",
        profiles=["Generic"],
        priority=10,
    )
    lib = _library_with(concrete, generic)

    mixed_ports = [{"profile": "Circular"}, {"profile": "Rectangular"}]
    result = lib.list_types(category="junction", topology="through", connected_ports=mixed_ports)

    assert [t.id for t in result] == ["through_transition_angled", "through_generic"]


def test_list_types_connected_ports_drops_types_that_cannot_cover_the_ports():
    # A type declaring only "Rectangular" must not be offered for a
    # Circular/Oval mixed-profile junction -- connected_ports still
    # filters, it just checks each port's real profile instead of a single
    # collapsed string.
    rectangular_only = _type_def(
        "through_elbow_rectangular",
        "junction",
        family=["through.bend"],
        topology="through",
        profiles=["Rectangular"],
        priority=100,
    )
    generic = _type_def(
        "through_generic", "junction", family=["through.bend"], topology="through", profiles=["Generic"], priority=10
    )
    lib = _library_with(rectangular_only, generic)

    mixed_ports = [{"profile": "Circular"}, {"profile": "Oval"}]
    result = lib.list_types(category="junction", topology="through", connected_ports=mixed_ports)

    assert [t.id for t in result] == ["through_generic"]


def test_list_types_includes_inline_kind_types_for_manual_primary_selection():
    # Unlike select_type()'s own automatic-matching indexes, list_types()
    # (the manual "change type" editor's listing) deliberately includes
    # inline-kind types -- a user may want to pick a damper/VAV directly as
    # a junction's Primary type, not just add one as a chained Inline
    # component (see docs/library-guide.md "Inline components"). Here
    # through_damper_generic's family ("through.straight.damper") is an
    # ancestor match for a requested family of "through.straight" (see
    # _family_match), so it shows up alongside the ordinary model.
    damper = _type_def(
        "through_damper_generic",
        "junction",
        family=["through.straight.damper"],
        topology="through",
        profiles=["Circular"],
        kind="inline",
        priority=999,
    )
    model = _type_def(
        "through_straight_generic",
        "junction",
        family=["through.straight"],
        topology="through",
        profiles=["Circular"],
        kind="model",
        priority=50,
    )
    lib = _library_with(damper, model)

    result = lib.list_types(category="junction", topology="through", family="through.straight")
    assert {t.id for t in result} == {"through_straight_generic", "through_damper_generic"}


# ----------------------------------------------------------------------
# Automatic selection (select_type)
# ----------------------------------------------------------------------


def test_select_type_exact_family_and_profile_match():
    t = _type_def("circular_straight", "segment", family=["straight_segment"], profiles=["Circular"])
    lib = _library_with(t)

    selection = lib.select_type(_segment_request("straight_segment", "Circular"))
    assert selection.status == "exact"
    assert selection.type_def.id == "circular_straight"


def test_select_type_generic_profile_fallback():
    t = _type_def("through_generic", "junction", family=["through.bend"], topology="through", profiles=["Generic"])
    lib = _library_with(t)

    selection = lib.select_type(_junction_request("through", "through.bend", "Circular", _ports(2, "Circular")))
    assert selection.status == "generic_profile"
    assert selection.type_def.id == "through_generic"


def test_select_type_prefers_exact_profile_over_generic():
    generic = _type_def(
        "through_generic", "junction", family=["through.bend"], topology="through", profiles=["Generic"], priority=999
    )
    exact = _type_def(
        "through_elbow_generic",
        "junction",
        family=["through.bend"],
        topology="through",
        profiles=["Circular"],
        priority=0,
    )
    lib = _library_with(generic, exact)

    selection = lib.select_type(_junction_request("through", "through.bend", "Circular", _ports(2, "Circular")))
    assert selection.status == "exact"
    assert selection.type_def.id == "through_elbow_generic"


def test_select_type_prefers_model_over_placeholder():
    marker = _type_def(
        "through_marker",
        "junction",
        family=["through.bend"],
        topology="through",
        profiles=["Generic"],
        kind="placeholder",
        priority=999,
    )
    model = _type_def(
        "through_elbow_generic",
        "junction",
        family=["through.bend"],
        topology="through",
        profiles=["Circular"],
        priority=0,
    )
    lib = _library_with(marker, model)

    selection = lib.select_type(_junction_request("through", "through.bend", "Circular", _ports(2, "Circular")))
    assert selection.type_def.id == "through_elbow_generic"
    assert selection.status == "exact"


def test_select_type_priority_resolves_overlapping_candidates():
    broad = _type_def(
        "branch_generic",
        "junction",
        family=["branch.tee", "branch.wye"],
        topology="branch",
        profiles=["Circular"],
        priority=10,
    )
    specific = _type_def(
        "branch_tee_generic", "junction", family=["branch.tee"], topology="branch", profiles=["Circular"], priority=50
    )
    lib = _library_with(broad, specific)

    selection = lib.select_type(_junction_request("branch", "branch.tee", "Circular", _ports(3, "Circular")))
    assert selection.type_def.id == "branch_tee_generic"


def test_select_type_tied_candidates_are_reported_ambiguous_not_insertion_order():
    a = _type_def("b_type", "junction", family=["branch.tee"], topology="branch", profiles=["Circular"], priority=50)
    b = _type_def("a_type", "junction", family=["branch.tee"], topology="branch", profiles=["Circular"], priority=50)
    lib = _library_with(a, b)

    selection = lib.select_type(
        _junction_request("branch", "branch.tee", "Circular", _ports(3, "Circular")), strict=True
    )
    assert selection.status == "ambiguous"
    assert set(selection.candidates) == {"a_type", "b_type"}


def test_select_type_ambiguous_falls_through_to_placeholder_when_not_strict():
    a = _type_def("b_type", "junction", family=["branch.tee"], topology="branch", profiles=["Circular"], priority=50)
    b = _type_def("a_type", "junction", family=["branch.tee"], topology="branch", profiles=["Circular"], priority=50)
    marker = _type_def(
        "branch_marker", "junction", family=["branch.tee"], topology="branch", profiles=["Generic"], kind="placeholder"
    )
    lib = _library_with(a, b, marker)

    selection = lib.select_type(
        _junction_request("branch", "branch.tee", "Circular", _ports(3, "Circular")), strict=False
    )
    assert selection.status == "placeholder"
    assert selection.type_def.id == "branch_marker"


def test_select_type_no_model_falls_back_to_placeholder():
    marker = _type_def(
        "through_marker",
        "junction",
        family=["through.bend"],
        topology="through",
        profiles=["Generic"],
        kind="placeholder",
    )
    lib = _library_with(marker)

    selection = lib.select_type(_junction_request("through", "through.bend", "Circular", _ports(2, "Circular")))
    assert selection.status == "placeholder"
    assert selection.type_def.id == "through_marker"


def test_select_type_unsupported_family_returns_not_found_with_no_placeholder():
    t = _type_def("branch_tee_generic", "junction", family=["branch.tee"], topology="branch", profiles=["Circular"])
    lib = _library_with(t)

    selection = lib.select_type(_junction_request("cross", "cross.cross", "Circular", _ports(4, "Circular")))
    assert selection.status == "not_found"
    assert selection.type_def is None


def test_automatic_primary_selection_never_selects_kind_inline():
    """
    An "inline"-kind type (a damper/silencer/etc, meant only for the Add
    Inline Component UI, see list_inline_types) must never be reachable
    through automatic Primary-fitting selection, even when it would
    otherwise be the best (or only) family/topology/profile match --
    _rebuild_match_index deliberately excludes it from both the model and
    placeholder match indexes. This guards the invariant now that the
    junction-composition refactor removed the old topology/degree gate that
    used to make a chain-eligible Primary's own selection path the only one
    that could ever run this matching logic in the first place.
    """
    inline_damper = _type_def(
        "through_damper_generic",
        "junction",
        family=["through.bend"],
        topology="through",
        profiles=["Circular"],
        kind="inline",
        priority=999,
    )
    lib = _library_with(inline_damper)

    selection = lib.select_type(_junction_request("through", "through.bend", "Circular", _ports(2, "Circular")))
    assert selection.type_def is None
    assert selection.status == "not_found"

    # Also true through the sticky resolution path used by normal sync.
    registry = HVACLibraryRegistry()
    registry.register_library(lib)
    sticky = registry.resolve_sticky_type(
        "lib", "", _junction_request("through", "through.bend", "Circular", _ports(2, "Circular"))
    )
    assert sticky.type_def is None

    # But it IS reachable through list_inline_types, the Add Inline
    # Component UI's own lookup.
    assert [t.id for t in lib.list_inline_types(topology="through")] == ["through_damper_generic"]


# ----------------------------------------------------------------------
# Constraints
# ----------------------------------------------------------------------


def test_select_type_rejects_degree_mismatch():
    t = _type_def(
        "branch_tee_generic",
        "junction",
        family=["branch.tee"],
        topology="branch",
        profiles=["Circular"],
        constraints={"degree": 3},
    )
    lib = _library_with(t)

    # Only 2 connected ports -- degree constraint requires 3.
    selection = lib.select_type(_junction_request("branch", "branch.tee", "Circular", _ports(2, "Circular")))
    assert selection.type_def is None


def test_select_type_rejects_topology_mismatch():
    t = _type_def(
        "branch_tee_generic",
        "junction",
        family=["branch.tee"],
        topology="branch",
        profiles=["Circular"],
        constraints={"degree": 3},
    )
    lib = _library_with(t)

    selection = lib.select_type(_junction_request("through", "branch.tee", "Circular", _ports(3, "Circular")))
    assert selection.type_def is None


def test_select_type_rejects_connected_port_profile_mismatch():
    t = _type_def(
        "branch_tee_generic",
        "junction",
        family=["branch.tee"],
        topology="branch",
        profiles=["Circular"],
        constraints={"degree": 3},
    )
    lib = _library_with(t)

    ports = _ports(2, "Circular") + [{"profile": "Rectangular"}]
    selection = lib.select_type(_junction_request("branch", "branch.tee", "Mixed", ports))
    assert selection.type_def is None


def test_select_type_filters_by_flow_class_constraint():
    # Only wins the tier when the classifier's flow_class matches -- see
    # NetworkParser.classify_flow / TOPOLOGY_CLASSIFICATION.md.
    t = _type_def(
        "through_transition_expansion",
        "junction",
        family=["through.transition"],
        topology="through",
        profiles=["Circular"],
        constraints={"flow_class": {"enum": ["expansion"]}},
    )
    lib = _library_with(t)

    contraction = _junction_request_ctx(
        "through", "through.transition", "Circular", _ports(2), flow_class="contraction"
    )
    expansion = _junction_request_ctx("through", "through.transition", "Circular", _ports(2), flow_class="expansion")

    assert lib.select_type(contraction).type_def is None
    assert lib.select_type(expansion).type_def is t


def test_select_type_filters_by_qualifier_constraint():
    # A single-plane eccentric reducer should only be offered when the
    # classifier's own qualifiers dict says so.
    t = _type_def(
        "through_transition_eccentric",
        "junction",
        family=["through.transition"],
        topology="through",
        profiles=["Rectangular"],
        constraints={"qualifiers": {"alignment": {"enum": ["eccentric"]}}},
    )
    lib = _library_with(t)

    concentric = _junction_request_ctx(
        "through", "through.transition", "Rectangular", _ports(2, "Rectangular"), qualifiers={"alignment": "concentric"}
    )
    eccentric = _junction_request_ctx(
        "through",
        "through.transition",
        "Rectangular",
        _ports(2, "Rectangular"),
        qualifiers={"alignment": "eccentric", "aligned_side": "top"},
    )

    assert lib.select_type(concentric).type_def is None
    assert lib.select_type(eccentric).type_def is t


def test_select_type_filters_by_numeric_derived_value_constraint():
    # area_ratio (a JunctionAnalysis.derived_values entry) constrained with
    # plain minimum/maximum, exactly like the JSON example in
    # docs/library-guide.md.
    t = _type_def(
        "through_transition_moderate",
        "junction",
        family=["through.transition"],
        topology="through",
        profiles=["Circular"],
        constraints={"area_ratio": {"minimum": 1.0, "maximum": 4.0}},
    )
    lib = _library_with(t)

    too_large = _junction_request_ctx(
        "through", "through.transition", "Circular", _ports(2), derived_values={"area_ratio": 5.0}
    )
    in_range = _junction_request_ctx(
        "through", "through.transition", "Circular", _ports(2), derived_values={"area_ratio": 2.25}
    )

    assert lib.select_type(too_large).type_def is None
    assert lib.select_type(in_range).type_def is t


def test_select_type_missing_flow_context_does_not_reject_candidate():
    # A request built with no flow_class key in context at all (e.g. a
    # caller that hasn't been updated to pass one) must not be treated as a
    # constraint violation -- absence of data is not the same as a mismatch,
    # matching how the existing profile check only applies "if profile".
    t = _type_def(
        "through_transition_expansion",
        "junction",
        family=["through.transition"],
        topology="through",
        profiles=["Circular"],
        constraints={"flow_class": {"enum": ["expansion"]}},
    )
    lib = _library_with(t)

    bare = _junction_request("through", "through.transition", "Circular", _ports(2))
    assert lib.select_type(bare).type_def is t
    assert lib.matches_type(t, bare) is True


def test_matches_type_and_select_type_agree_on_compatibility():
    t = _type_def(
        "branch_tee_generic",
        "junction",
        family=["branch.tee"],
        topology="branch",
        profiles=["Circular"],
        constraints={"degree": 3},
    )
    lib = _library_with(t)

    compatible_request = _junction_request("branch", "branch.tee", "Circular", _ports(3, "Circular"))
    incompatible_request = _junction_request("through", "through.bend", "Circular", _ports(2, "Circular"))

    selection = lib.select_type(compatible_request)
    assert selection.type_def is t
    assert lib.matches_type(t, compatible_request) is True
    assert lib.matches_type(t, incompatible_request) is False


# ----------------------------------------------------------------------
# Sticky current-selection policy (resolve_sticky_type)
# ----------------------------------------------------------------------


def _registry_with(*type_defs):
    lib = _library_with(*type_defs)
    reg = HVACLibraryRegistry()
    reg.register_library(lib)
    return reg


def test_resolve_sticky_type_retains_compatible_current_model():
    preferred = _type_def(
        "tee_smacna", "junction", family=["branch.tee"], topology="branch", profiles=["Circular"], priority=50
    )
    current = _type_def(
        "tee_long_radius", "junction", family=["branch.tee"], topology="branch", profiles=["Circular"], priority=10
    )
    reg = _registry_with(preferred, current)

    request = _junction_request("branch", "branch.tee", "Circular", _ports(3, "Circular"))
    selection = reg.resolve_sticky_type("lib", "tee_long_radius", request)

    assert selection.status == "retained"
    assert selection.type_def.id == "tee_long_radius"


def test_resolve_sticky_type_reselects_on_topology_conflict():
    tee = _type_def(
        "branch_tee_generic", "junction", family=["branch.tee"], topology="branch", profiles=["Circular"], priority=50
    )
    elbow = _type_def(
        "through_elbow_generic",
        "junction",
        family=["through.bend_90"],
        topology="through",
        profiles=["Circular"],
        priority=50,
    )
    reg = _registry_with(tee, elbow)

    request = _junction_request("through", "through.bend_90", "Circular", _ports(2, "Circular"))
    selection = reg.resolve_sticky_type("lib", "branch_tee_generic", request)

    assert selection.status != "retained"
    assert selection.type_def.id == "through_elbow_generic"


def test_resolve_sticky_type_reselects_on_family_conflict():
    tee = _type_def(
        "branch_tee_generic", "junction", family=["branch.tee"], topology="branch", profiles=["Circular"], priority=50
    )
    wye = _type_def(
        "branch_wye_generic", "junction", family=["branch.wye"], topology="branch", profiles=["Circular"], priority=10
    )
    reg = _registry_with(tee, wye)

    request = _junction_request("branch", "branch.wye", "Circular", _ports(3, "Circular"))
    selection = reg.resolve_sticky_type("lib", "branch_tee_generic", request)

    assert selection.status != "retained"
    assert selection.type_def.id == "branch_wye_generic"


def test_resolve_sticky_type_reselects_on_profile_conflict():
    circ = _type_def("circular_straight", "segment", family=["straight_segment"], profiles=["Circular"])
    rect = _type_def("rectangular_straight", "segment", family=["straight_segment"], profiles=["Rectangular"])
    reg = _registry_with(circ, rect)

    request = _segment_request("straight_segment", "Rectangular")
    selection = reg.resolve_sticky_type("lib", "circular_straight", request)

    assert selection.status != "retained"
    assert selection.type_def.id == "rectangular_straight"


def test_resolve_sticky_type_reselects_on_constraint_conflict():
    tee = _type_def(
        "branch_tee_generic",
        "junction",
        family=["branch.tee"],
        topology="branch",
        profiles=["Circular"],
        constraints={"degree": 3},
    )
    marker = _type_def(
        "branch_marker", "junction", family=["branch.tee"], topology="branch", profiles=["Generic"], kind="placeholder"
    )
    reg = _registry_with(tee, marker)

    # Degree drops to 2 (no longer a real 3-port tee) -- current tee type
    # violates its own degree constraint now.
    request = _junction_request("branch", "branch.tee", "Circular", _ports(2, "Circular"))
    selection = reg.resolve_sticky_type("lib", "branch_tee_generic", request)

    assert selection.status != "retained"


def test_resolve_sticky_type_reevaluates_current_placeholder():
    marker = _type_def(
        "branch_marker", "junction", family=["branch.tee"], topology="branch", profiles=["Generic"], kind="placeholder"
    )
    model = _type_def(
        "branch_tee_generic", "junction", family=["branch.tee"], topology="branch", profiles=["Circular"], priority=50
    )
    reg = _registry_with(marker, model)

    request = _junction_request("branch", "branch.tee", "Circular", _ports(3, "Circular"))
    selection = reg.resolve_sticky_type("lib", "branch_marker", request)

    # A currently-selected placeholder must never be treated as sticky --
    # it's re-evaluated and upgrades to the real model.
    assert selection.status != "retained"
    assert selection.type_def.id == "branch_tee_generic"


def test_resolve_sticky_type_no_current_type_runs_automatic_selection():
    model = _type_def(
        "branch_tee_generic", "junction", family=["branch.tee"], topology="branch", profiles=["Circular"], priority=50
    )
    reg = _registry_with(model)

    request = _junction_request("branch", "branch.tee", "Circular", _ports(3, "Circular"))
    selection = reg.resolve_sticky_type("lib", "", request)

    assert selection.status == "exact"
    assert selection.type_def.id == "branch_tee_generic"


# ----------------------------------------------------------------------
# Segments: straight vs curved family
# ----------------------------------------------------------------------


def test_select_type_segment_straight_family():
    straight = _type_def("circular_straight", "segment", family=["straight_segment"], profiles=["Circular"])
    curved = _type_def("circular_generic", "segment", family=["curved_segment"], profiles=["Circular"])
    lib = _library_with(straight, curved)

    selection = lib.select_type(_segment_request("straight_segment", "Circular"))
    assert selection.type_def.id == "circular_straight"


def test_select_type_segment_curved_family():
    straight = _type_def("circular_straight", "segment", family=["straight_segment"], profiles=["Circular"])
    curved = _type_def("circular_generic", "segment", family=["curved_segment"], profiles=["Circular"])
    lib = _library_with(straight, curved)

    selection = lib.select_type(_segment_request("curved_segment", "Circular"))
    assert selection.type_def.id == "circular_generic"


def test_resolve_sticky_type_segment_manual_selection_remains_sticky():
    # Two compatible circular-straight models; user manually picked the
    # lower-priority one -- it must not be replaced by the higher-priority
    # default on normal sync.
    default_model = _type_def(
        "circular_straight_smacna", "segment", family=["straight_segment"], profiles=["Circular"], priority=50
    )
    manual_model = _type_def(
        "circular_straight_custom", "segment", family=["straight_segment"], profiles=["Circular"], priority=10
    )
    reg = _registry_with(default_model, manual_model)

    request = _segment_request("straight_segment", "Circular")
    selection = reg.resolve_sticky_type("lib", "circular_straight_custom", request)

    assert selection.status == "retained"
    assert selection.type_def.id == "circular_straight_custom"


# ----------------------------------------------------------------------
# hvaclib.HVACLibraryService.match_profile_from_ports
# ----------------------------------------------------------------------


def test_match_profile_from_ports_homogeneous_circular():
    ports = _ports(3, "Circular")
    assert hvaclib.HVACLibraryService.match_profile_from_ports(ports) == "Circular"


def test_match_profile_from_ports_mixed():
    ports = _ports(2, "Circular") + [{"profile": "Rectangular"}]
    assert hvaclib.HVACLibraryService.match_profile_from_ports(ports) == "Mixed"


def test_match_profile_from_ports_no_known_profiles():
    ports = [{"profile": ""}, {}]
    assert hvaclib.HVACLibraryService.match_profile_from_ports(ports) == ""


def test_match_profile_from_ports_empty_list():
    assert hvaclib.HVACLibraryService.match_profile_from_ports([]) == ""


# ----------------------------------------------------------------------
# Bundled library audit: no unresolved top-ranked ambiguity, and the two
# real overlaps identified during descriptor priority auditing resolve to
# the intended winner (see docs/library-guide.md).
# ----------------------------------------------------------------------


def _load_bundled_registry():
    reg = HVACLibraryRegistry()
    reg.set_search_paths([LIBRARIES_ROOT])
    reg.ensure_loaded()
    return reg


def test_bundled_libraries_have_no_unresolved_priority_ties():
    # An index bucket (category, topology, family) can legitimately hold
    # several same-priority concrete-profile types side by side now (e.g.
    # circular_straight/rectangular_straight/oval_straight all share one
    # "straight_segment" bucket) -- they're never actually ambiguous for a
    # real request as long as they don't advertise any of the same profile,
    # since select_type() only ever compares candidates that both passed
    # per-port/segment profile compatibility for that request. So: check
    # for a genuine priority tie only among candidates that share at least
    # one profile (Generic-profile candidates always "share" with each
    # other, since they accept every request in the bucket).
    reg = _load_bundled_registry()
    for lib in reg.list_libraries():
        for index in (lib.model_match_index, lib.placeholder_match_index):
            for key, candidates in index.items():
                if len(candidates) < 2:
                    continue

                generic = [c for c in candidates if not lib._declares_concrete_profile(c)]
                concrete = [c for c in candidates if lib._declares_concrete_profile(c)]

                def _assert_no_tie(group, label):
                    if len(group) < 2:
                        return
                    max_priority = max(c.selection.priority for c in group)
                    top = [c for c in group if c.selection.priority == max_priority]
                    assert len(top) == 1, (
                        "Ambiguous automatic selection in library '{}' for {} ({}): {} tie at priority {}".format(
                            lib.id, key, label, sorted(c.id for c in top), max_priority
                        )
                    )

                _assert_no_tie(generic, "Generic-profile")

                # Concrete candidates only really compete for a request
                # that shares one of their declared profiles -- group by
                # each profile value seen, and check ties within each group
                # (any pairwise profile overlap is caught this way, since a
                # shared profile always shows up in at least one such group).
                profiles_seen = set()
                for c in concrete:
                    profiles_seen.update(c.profiles or [])
                for profile in profiles_seen:
                    group = [c for c in concrete if profile in (c.profiles or [])]
                    _assert_no_tie(group, "profile={!r}".format(profile))


def test_bundled_builtin_basic_branch_tee_prefers_specific_tee_model():
    # The straight tee is the automatic default: it builds on any duct size,
    # while the radius tees depend on BranchRadius fitting the node.
    reg = _load_bundled_registry()
    request = _junction_request("branch", "branch.tee", "Rectangular", _ports(3, "Rectangular"))
    selection = reg.select_type("builtin_basic", request, strict=True)
    assert selection.type_def.id == "branch_tee_straight"


def test_bundled_builtin_basic_branch_wye_prefers_specific_wye_model():
    # A genuine wye node gets a dedicated wye model, not the broad
    # branch_generic catch-all (priority 10).
    reg = _load_bundled_registry()
    request = _junction_request("branch", "branch.wye", "Circular", _ports(3, "Circular"))
    selection = reg.select_type("builtin_basic", request, strict=True)
    assert selection.type_def.id in ("branch_wye_mitered", "branch_wye_radius")


def test_bundled_smacna_branch_tee_prefers_specific_tee_model():
    reg = _load_bundled_registry()
    request = _junction_request("branch", "branch.tee", "Circular", _ports(3, "Circular"))
    selection = reg.select_type("smacna", request, strict=True)
    # The ported builtin_basic tee types outrank the old star-shaped fallback; the straight tee comes first.
    assert selection.type_def.id == "branch_tee_straight"


def test_bundled_smacna_rectangular_elbow_prefers_the_mitered_then_the_dedicated_rectangular_model():
    # The mitered elbow is the robust default; among the radius elbows the
    # rectangular one still comes before the generic one.
    reg = _load_bundled_registry()
    request = _junction_request("through", "through.bend_90", "Rectangular", _ports(2, "Rectangular"))
    selection = reg.select_type("smacna", request, strict=True)
    assert selection.type_def.id == "through_elbow_mitered"
    lib = reg.get_library("smacna")
    found = lib.list_types(category="junction", family="through.bend_90", connected_ports=_ports(2, "Rectangular"))
    ids = [t.id for t in found]
    assert ids.index("through_elbow_rectangular") < ids.index("through_elbow_radius")


def test_bundled_smacna_circular_elbow_uses_the_mitered_elbow_model():
    # through_elbow_rectangular only advertises the Rectangular profile, so
    # a Circular request is not blocked by it and gets the mitered default.
    reg = _load_bundled_registry()
    request = _junction_request("through", "through.bend_90", "Circular", _ports(2, "Circular"))
    selection = reg.select_type("smacna", request, strict=True)
    assert selection.type_def.id == "through_elbow_mitered"


def test_bundled_end_topology_always_falls_back_to_terminal_marker():
    # Degree-1 nodes only ever classify as family_key "end.terminal" -- the
    # specific end_*_generic fittings (diffuser/fan/louver) are unreachable
    # by automatic selection and exist purely for manual/sticky selection.
    reg = _load_bundled_registry()
    request = _junction_request("end", "end.terminal", "Circular", _ports(1, "Circular"))
    selection = reg.select_type("smacna", request, strict=True)
    assert selection.status == "placeholder"
    assert selection.type_def.id == "end_terminal_marker"


def test_bundled_manual_end_diffuser_selection_stays_sticky():
    # Even though automatic selection can never choose end_diffuser_generic
    # (see test above), a manual selection of it must remain sticky across
    # normal sync, since its family is a specialization of "end.terminal".
    reg = _load_bundled_registry()
    request = _junction_request("end", "end.terminal", "Circular", _ports(1, "Circular"))
    selection = reg.resolve_sticky_type("smacna", "end_diffuser_generic", request)
    assert selection.status == "retained"
    assert selection.type_def.id == "end_diffuser_generic"


# ----------------------------------------------------------------------
# Mixed-profile branch/cross/multiport must never fall to the invisible
# placeholder marker -- and, since matching no longer keys candidates by a
# single pseudo "Mixed" profile string (see HVACMatchKey), a mixed-profile
# request now reaches a dedicated concrete-profile model whenever one
# structurally covers every connected port's own profile (per
# validation.context_violations()'s existing per-port check), the same way
# it already would for a homogeneous request -- it's no longer forced past
# every concrete candidate straight to the broad Generic-profile catch-all.
# Where a library has no dedicated model covering the actual profile mix
# (cross/multiport here), the broad Generic-profile model
# (cross_generic/multiport_generic) is still the correct landing spot, not
# the marker -- this matters because a placeholder selection would silently
# drop to AirflowSolver's generic K_DEFAULT fallback instead of a real,
# type-specific loss coefficient.
# ----------------------------------------------------------------------


def _mixed_ports(n, extra_profile="Rectangular"):
    return _ports(n - 1, "Circular") + [{"profile": extra_profile}]


def test_bundled_builtin_basic_mixed_profile_branch_reaches_dedicated_tee_model():
    # The straight tee accepts each built-in profile, including a mixed set of connected ports.
    reg = _load_bundled_registry()
    request = _junction_request("branch", "branch.tee", "Mixed", _mixed_ports(3))
    selection = reg.select_type("builtin_basic", request, strict=True)
    assert selection.status == "exact"
    assert selection.type_def.id == "branch_tee_straight"


def test_bundled_builtin_basic_radius_tee_alignment_follows_profile_in_the_list():
    # Both radius tees come after the straight default; the edge-aligned one
    # is offered for rectangular ducts only.
    lib = _load_bundled_registry().get_library("builtin_basic")
    for profile in ("Rectangular", "Circular", "Oval"):
        found = lib.list_types(category="junction", family="branch.tee", connected_ports=_ports(3, profile))
        ids = [t.id for t in found]
        assert ids[0] == "branch_tee_straight"
        assert "branch_tee_radius_center" in ids
        assert ("branch_tee_radius_edge" in ids) == (profile == "Rectangular")


def test_bundled_builtin_basic_mixed_profile_cross_reaches_dedicated_cross_model():
    # The straight cross accepts each built-in profile, including a mixed set of connected ports.
    reg = _load_bundled_registry()
    request = _junction_request("cross", "cross.cross", "Mixed", _mixed_ports(4))
    selection = reg.select_type("builtin_basic", request, strict=True)
    assert selection.status == "exact"
    assert selection.type_def.id == "cross_tee_straight"


def test_bundled_builtin_basic_double_wye_reaches_the_mitered_double_wye():
    # Two dedicated double-wye models exist; the mitered one (no radius to fit) has the higher priority.
    reg = _load_bundled_registry()
    request = _junction_request("cross", "cross.double_wye", "Circular", _ports(4, "Circular"))
    selection = reg.select_type("builtin_basic", request, strict=True)
    assert selection.status == "exact"
    assert selection.type_def.id == "cross_double_wye_mitered"


def test_bundled_builtin_basic_irregular_cross_still_uses_the_generic_cross():
    reg = _load_bundled_registry()
    request = _junction_request("cross", "cross.generic", "Circular", _ports(4, "Circular"))
    selection = reg.select_type("builtin_basic", request, strict=True)
    assert selection.type_def.id == "cross_generic"


def test_bundled_builtin_basic_mixed_profile_multiport_uses_generic_model_not_marker():
    reg = _load_bundled_registry()
    request = _junction_request("multiport", "multiport.multiport", "Mixed", _mixed_ports(6))
    selection = reg.select_type("builtin_basic", request, strict=True)
    assert selection.status == "generic_profile"
    assert selection.type_def.id == "multiport_generic"


# ----------------------------------------------------------------------
# Circular -> Rectangular (and other cross-profile) transitions: since
# matching no longer indexes on a single profile, a 2-port through.transition
# node with two different connected-port profiles now reaches the library's
# dedicated transition model instead of being routed past it straight to the
# broad through_generic fallback -- see HVACMatchKey/select_type().
# ----------------------------------------------------------------------


def test_bundled_smacna_circular_to_rectangular_transition_reaches_dedicated_model():
    reg = _load_bundled_registry()
    ports = [{"profile": "Circular"}, {"profile": "Rectangular"}]
    request = _junction_request("through", "through.transition", "Mixed", ports)
    selection = reg.select_type("smacna", request, strict=True)
    assert selection.status == "exact"
    # through_transition_generic was retired for the three alignment-specific
    # transitions (as in builtin_basic); concentric is the default.
    assert selection.type_def.id == "through_transition_concentric"


def test_bundled_builtin_basic_circular_to_rectangular_transition_reaches_dedicated_model():
    reg = _load_bundled_registry()
    ports = [{"profile": "Circular"}, {"profile": "Rectangular"}]
    request = _junction_request("through", "through.transition", "Mixed", ports)
    selection = reg.select_type("builtin_basic", request, strict=True)
    assert selection.status == "exact"
    # A round-to-rectangular transition has no classified alignment, so it
    # gets the concentric transition, the default of the three.
    assert selection.type_def.id == "through_transition_concentric"


def _rect_transition_request(**qualifiers):
    ports = _ports(2, "Rectangular")
    if not qualifiers:
        return _junction_request("through", "through.transition", "Rectangular", ports)
    return _junction_request_ctx("through", "through.transition", "Rectangular", ports, qualifiers=qualifiers)


def test_bundled_builtin_basic_transition_is_chosen_by_alignment():
    reg = _load_bundled_registry()
    expected = {
        "concentric": "through_transition_concentric",
        "unknown": "through_transition_concentric",
        "eccentric": "through_transition_eccentric",
        "double_eccentric": "through_transition_eccentric",
        "offset": "through_transition_offset",
    }
    for alignment, type_id in expected.items():
        selection = reg.select_type("builtin_basic", _rect_transition_request(alignment=alignment), strict=True)
        assert selection.status == "exact", alignment
        assert selection.type_def.id == type_id, alignment


def test_bundled_builtin_basic_transition_without_alignment_data_is_concentric():
    reg = _load_bundled_registry()
    selection = reg.select_type("builtin_basic", _rect_transition_request(), strict=True)
    assert selection.type_def.id == "through_transition_concentric"


def test_bundled_builtin_basic_offset_types_use_their_own_properties():
    lib = _load_bundled_registry().get_library("builtin_basic")
    for style in ("angled", "mitered", "radiussed"):
        type_def = lib.get_type("through_offset_" + style)
        names = {p.name for p in type_def.properties}
        assert "OffsetLength" in names
        assert "TransitionLength" not in names
        assert type_def.generator_module == "shared:offsets"
    assert "OffsetRadius" in {p.name for p in lib.get_type("through_offset_radiussed").properties}


def test_bundled_generic_fallback_still_used_when_no_concrete_type_covers_profile():
    # No shipped transition model declares a "CustomShape" profile, so even
    # though matching no longer requires an exact index-key hit, the
    # structural candidates for through.transition all fail their per-port
    # profile check -- automatic selection correctly falls through to the
    # library's broad Generic-profile through_generic model.
    reg = _load_bundled_registry()
    ports = [{"profile": "CustomShape"}, {"profile": "CustomShape"}]
    request = _junction_request("through", "through.transition", "CustomShape", ports)
    for lib_id in ("smacna", "builtin_basic"):
        selection = reg.select_type(lib_id, request, strict=True)
        assert selection.status == "generic_profile"
        assert selection.type_def.id == "through_generic"


def test_bundled_smacna_mixed_profile_branch_uses_a_model_not_marker():
    # Since the Stage 4-6 types were ported to smacna (as in builtin_basic),
    # a mixed-profile wye matches the mitered wye exactly, port by port.
    reg = _load_bundled_registry()
    request = _junction_request("branch", "branch.wye", "Mixed", _mixed_ports(3))
    selection = reg.select_type("smacna", request, strict=True)
    assert selection.status == "exact"
    assert selection.type_def.id == "branch_wye_mitered"


def test_bundled_smacna_mixed_profile_cross_uses_a_model_not_marker():
    reg = _load_bundled_registry()
    request = _junction_request("cross", "cross.cross", "Mixed", _mixed_ports(4))
    selection = reg.select_type("smacna", request, strict=True)
    assert selection.status == "exact"
    assert selection.type_def.id == "cross_tee_straight"


def test_bundled_smacna_mixed_profile_multiport_uses_generic_model_not_marker():
    reg = _load_bundled_registry()
    request = _junction_request("multiport", "multiport.multiport", "Mixed", _mixed_ports(6))
    selection = reg.select_type("smacna", request, strict=True)
    assert selection.status == "generic_profile"
    assert selection.type_def.id == "multiport_generic"


def test_bundled_mixed_profile_fix_does_not_disturb_exact_profile_ranking():
    # The specific tee model must still win over the now-Generic-profile-
    # capable broad model for a real, single-profile Circular tee.
    reg = _load_bundled_registry()
    request = _junction_request("branch", "branch.tee", "Circular", _ports(3, "Circular"))
    for lib_id, expected in (("builtin_basic", "branch_tee_straight"), ("smacna", "branch_tee_straight")):
        selection = reg.select_type(lib_id, request, strict=True)
        assert selection.status == "exact"
        assert selection.type_def.id == expected


# ----------------------------------------------------------------------
# selection.kind == "inline": dampers/silencers/flex connectors -- never
# reachable through automatic (topology, family, profile) matching, only
# through HVACLibrary.list_inline_types() for the "Add Inline Component"
# UI action. See freecad/HVAC/library/Library.py and docs/library-guide.md.
# ----------------------------------------------------------------------


def test_selection_kind_inline_excluded_from_match_indexes():
    model = _type_def(
        "m1", "junction", ["through.straight.damper"], topology="through", profiles=["Circular"], kind="model"
    )
    inline = _type_def(
        "i1", "junction", ["through.straight.damper"], topology="through", profiles=["Circular"], kind="inline"
    )
    lib = _library_with(model, inline)
    lib.reindex()

    all_indexed = set(lib.model_match_index.keys()) | set(lib.placeholder_match_index.keys())
    indexed_ids = {t.id for candidates in lib.model_match_index.values() for t in candidates}
    indexed_ids |= {t.id for candidates in lib.placeholder_match_index.values() for t in candidates}
    assert "i1" in {t.id for t in [model, inline]}  # sanity: both types exist
    assert "i1" not in indexed_ids
    assert "m1" in indexed_ids
    assert all_indexed  # the model's key is present


def test_select_type_never_returns_an_inline_type():
    model = _type_def(
        "m1",
        "junction",
        ["through.straight.damper"],
        topology="through",
        profiles=["Circular"],
        kind="model",
        priority=0,
    )
    inline = _type_def(
        "i1",
        "junction",
        ["through.straight.damper"],
        topology="through",
        profiles=["Circular"],
        kind="inline",
        priority=1000,
    )
    lib = _library_with(model, inline)
    request = _junction_request("through", "through.straight.damper", "Circular", _ports(2))

    selection = lib.select_type(request, strict=True)
    assert selection.type_def is not None
    assert selection.type_def.id == "m1"


def test_resolve_sticky_type_retains_manually_chosen_inline_current_type():
    # A user can deliberately set an inline-kind type (damper/VAV) as a
    # junction's Primary type via the manual "change type" editor
    # (list_types() includes inline types for that picker -- see
    # test_list_types_includes_inline_kind_types_for_manual_primary_selection).
    # Sync must not silently discard that choice back to whatever
    # select_type() would auto-pick -- resolve_sticky_type() retains a
    # compatible inline current type exactly like any other non-placeholder
    # type.
    inline = _type_def("i1", "junction", ["through.straight"], topology="through", profiles=["Circular"], kind="inline")
    fallback = _type_def(
        "m1", "junction", ["through.straight"], topology="through", profiles=["Circular"], kind="model"
    )
    lib = _library_with(inline, fallback)
    reg = HVACLibraryRegistry()
    reg.register_library(lib)

    request = _junction_request("through", "through.straight", "Circular", _ports(2))
    selection = reg.resolve_sticky_type("lib", "i1", request)
    assert selection.status == "retained"
    assert selection.type_def.id == "i1"


def test_resolve_sticky_type_reselects_when_inline_current_type_no_longer_compatible():
    # Retention still requires actual compatibility -- an inline current
    # type that no longer matches the request re-runs automatic selection
    # exactly like a model would, and (per select_type()'s own inline
    # exclusion) can never land back on another inline type.
    inline = _type_def("i1", "junction", ["through.straight"], topology="through", profiles=["Circular"], kind="inline")
    fallback = _type_def(
        "m1", "junction", ["through.straight"], topology="through", profiles=["Circular"], kind="model"
    )
    lib = _library_with(inline, fallback)
    reg = HVACLibraryRegistry()
    reg.register_library(lib)

    # Rectangular request -- "i1" only declares "Circular".
    request = _junction_request("through", "through.straight", "Rectangular", _ports(2, "Rectangular"))
    selection = reg.resolve_sticky_type("lib", "i1", request)
    assert selection.status != "retained"
    assert selection.type_def is None


def test_list_inline_types_filters_by_topology_and_profile():
    damper = _type_def(
        "through_damper",
        "junction",
        ["through.straight.damper"],
        topology="through",
        profiles=["Circular", "Rectangular"],
        kind="inline",
    )
    vav = _type_def(
        "through_vav", "junction", ["through.straight.vav"], topology="through", profiles=["Oval"], kind="inline"
    )
    model = _type_def("m1", "junction", ["through.straight"], topology="through", profiles=["Circular"], kind="model")
    lib = _library_with(damper, vav, model)

    all_inline = lib.list_inline_types()
    assert {t.id for t in all_inline} == {"through_damper", "through_vav"}

    circular_only = lib.list_inline_types(topology="through", profile="Circular")
    assert {t.id for t in circular_only} == {"through_damper"}

    wrong_topology = lib.list_inline_types(topology="branch", profile="Circular")
    assert wrong_topology == []


def test_bundled_damper_and_vav_are_reclassified_inline():
    reg = _load_bundled_registry()
    for lib_id in ("smacna", "builtin_basic"):
        lib = reg.get_library(lib_id)
        damper = lib.get_type("through_damper_generic")
        vav = lib.get_type("through_vav_generic")
        assert damper.selection.kind == "inline"
        assert vav.selection.kind == "inline"

        inline_types = {t.id for t in lib.list_inline_types(topology="through")}
        assert {"through_damper_generic", "through_vav_generic"} <= inline_types

        # Never reachable through automatic matching, even if their own
        # declared family were somehow requested.
        request = _junction_request("through", "through.straight.damper", "Circular", _ports(2))
        selection = reg.select_type(lib_id, request, strict=True)
        assert selection.type_def is None or selection.type_def.id != "through_damper_generic"


def test_bundled_reclassifying_dampers_to_inline_does_not_disturb_other_selection():
    # The through/2-port automatic-selection outcome for an ordinary
    # straight/bend run must be unaffected by the damper/VAV reclassification
    # (they were never reachable by the classifier's own family keys anyway
    # -- see through_damper_generic.json/through_vav_generic.json).
    reg = _load_bundled_registry()
    request = _junction_request("through", "through.straight", "Circular", _ports(2))
    selection = reg.select_type("smacna", request, strict=True)
    assert selection.type_def is not None
    # A plain equal-size straight run gets the dedicated straight joint, as in builtin_basic.
    assert selection.type_def.id == "through_straight_generic"


# ----------------------------------------------------------------------
# list_types() filtered by the node's flow classification (the manual
# Change Type list)
# ----------------------------------------------------------------------


def _listed(topology, family, ports, classification=None):
    lib = _load_bundled_registry().get_library("builtin_basic")
    type_defs = lib.list_types(
        category="junction",
        family=family,
        connected_ports=ports,
        include_placeholders=False,
        classification=classification,
    )
    return {t.id for t in type_defs if t.topology == topology}


_TRANSITIONS = {"through_transition_concentric", "through_transition_eccentric", "through_transition_offset"}


@pytest.mark.parametrize(
    "alignment, expected",
    [
        ("concentric", "through_transition_concentric"),
        ("eccentric", "through_transition_eccentric"),
        ("double_eccentric", "through_transition_eccentric"),
        ("offset", "through_transition_offset"),
        ("unknown", "through_transition_concentric"),
    ],
)
def test_list_types_offers_only_the_transition_that_fits_the_alignment(alignment, expected):
    classification = {"flow_class": "expansion", "qualifiers": {"alignment": alignment}}
    listed = _listed("through", "through.transition", _ports(2, "Rectangular"), classification)
    assert listed & _TRANSITIONS == {expected}


def test_list_types_offers_every_transition_when_the_alignment_was_not_worked_out():
    # No flow direction on the base geometry: the classifier gives no qualifiers at all.
    classification = {"flow_class": "unknown", "qualifiers": {}}
    assert _TRANSITIONS <= _listed("through", "through.transition", _ports(2, "Rectangular"), classification)
    assert _TRANSITIONS <= _listed("through", "through.transition", _ports(2, "Rectangular"))


_ENTRIES = {"end_entry_plain", "end_entry_bellmouth", "end_entry_conical", "end_hood_intake", "end_hood_tapered"}
_EXITS = {"end_exit_plain", "end_exit_conical", "end_hood_exhaust"}
_EITHER_WAY = {"end_diffuser_generic", "end_diffuser_square", "end_grille_generic", "end_equipment_connection"}


def test_list_types_offers_entries_only_where_air_comes_in():
    listed = _listed("end", "end.terminal", _ports(1), {"flow_class": "entry"})
    assert _ENTRIES <= listed
    assert not (_EXITS & listed)
    assert _EITHER_WAY <= listed


def test_list_types_offers_exits_only_where_air_leaves():
    listed = _listed("end", "end.terminal", _ports(1), {"flow_class": "exit"})
    assert _EXITS <= listed
    assert not (_ENTRIES & listed)
    assert _EITHER_WAY <= listed


def test_list_types_offers_entries_and_exits_when_the_direction_is_unknown():
    assert _ENTRIES | _EXITS <= _listed("end", "end.terminal", _ports(1), {"flow_class": "unknown"})
    assert _ENTRIES | _EXITS <= _listed("end", "end.terminal", _ports(1))


def test_list_types_honours_a_diverging_or_converging_constraint():
    def _one_way(type_id, flow_class):
        return HVACTypeDef(
            id=type_id,
            label=type_id,
            category="junction",
            topology="branch",
            family=["branch.tee"],
            profiles=["Circular"],
            constraints={"degree": 3, "flow_class": {"enum": [flow_class]}},
        )

    lib = HVACLibrary(id="t", label="t", root_path="")
    lib.add_type(_one_way("diverging_only", "diverging"))
    lib.add_type(_one_way("converging_only", "converging"))

    def listed(flow_class):
        classification = {"flow_class": flow_class}
        found = lib.list_types(category="junction", connected_ports=_ports(3), classification=classification)
        return {t.id for t in found}

    assert listed("diverging") == {"diverging_only"}
    assert listed("converging") == {"converging_only"}
    # A flow class the classifier reports as "unknown" is a real value, so neither type claims it.
    assert listed("unknown") == set()


def test_end_types_are_listed_grouped_by_kind():
    # Priorities of end fittings are banded (diffusers, grilles, entries,
    # hoods, exits, equipment, end cap) so alternatives sit next to each
    # other in the Change Type list instead of being interleaved.
    lib = _load_bundled_registry().get_library("builtin_basic")
    listed = lib.list_types(
        category="junction", family="end.terminal", connected_ports=_ports(1), include_placeholders=False
    )
    groups = [t.id.split("_")[1] for t in listed]
    # Each group name appears as one unbroken run.
    runs = [name for index, name in enumerate(groups) if index == 0 or groups[index - 1] != name]
    assert len(runs) == len(set(runs)), groups
    assert runs[0] == "diffuser" and runs[-1] == "duct"


# ----------------------------------------------------------------------
# Lateral tees with a bend, and wyes offered on a bullhead tee
# (roadmap decisions 10 to 13)
# ----------------------------------------------------------------------


def test_bundled_builtin_basic_lateral_tee_defaults_to_the_mitered_one():
    reg = _load_bundled_registry()
    request = _junction_request("branch", "branch.lateral_tee", "Circular", _ports(3, "Circular"))
    selection = reg.select_type("builtin_basic", request, strict=True)
    assert selection.status == "exact"
    assert selection.type_def.id == "branch_lateral_tee_mitered"


def test_bundled_builtin_basic_lateral_tee_list_offers_all_three_kinds_in_order():
    lib = _load_bundled_registry().get_library("builtin_basic")
    found = lib.list_types(category="junction", family="branch.lateral_tee", connected_ports=_ports(3, "Circular"))
    ids = [t.id for t in found]
    laterals = [i for i in ids if i.startswith("branch_lateral_tee_")]
    assert laterals == ["branch_lateral_tee_mitered", "branch_lateral_tee_radius", "branch_lateral_tee_generic"]


def test_bundled_builtin_basic_wye_types_are_offered_on_a_bullhead_tee_only():
    bullhead = {"flow_class": "diverging", "qualifiers": {"common_leg": "branch"}}
    ordinary = {"flow_class": "diverging", "qualifiers": {"common_leg": "run"}}
    on_bullhead = _listed("branch", "branch.tee", _ports(3, "Circular"), bullhead)
    on_ordinary = _listed("branch", "branch.tee", _ports(3, "Circular"), ordinary)
    assert {"branch_wye_radius", "branch_wye_mitered"} <= on_bullhead
    assert not {"branch_wye_radius", "branch_wye_mitered"} & on_ordinary
    on_lateral = _listed("branch", "branch.lateral_tee", _ports(3, "Circular"), bullhead)
    assert not {"branch_wye_radius", "branch_wye_mitered"} & on_lateral


def test_bundled_builtin_basic_wye_types_are_never_chosen_automatically_for_a_tee():
    reg = _load_bundled_registry()
    request = _junction_request_ctx(
        "branch", "branch.tee", "Circular", _ports(3, "Circular"), qualifiers={"common_leg": "branch"}
    )
    selection = reg.select_type("builtin_basic", request, strict=True)
    assert not selection.type_def.id.startswith("branch_wye_")


def test_bundled_builtin_basic_wye_defaults_to_the_mitered_wye():
    reg = _load_bundled_registry()
    request = _junction_request("branch", "branch.wye", "Circular", _ports(3, "Circular"))
    # The radius wye fails to build hollow on round and rectangular ducts (see README), so it is manual only.
    assert reg.select_type("builtin_basic", request, strict=True).type_def.id == "branch_wye_mitered"


# ----------------------------------------------------------------------------
# A spline route (the "New Curved" tool) defaults to a flexible duct.
# ----------------------------------------------------------------------------


@pytest.fixture
def bundled_service(monkeypatch):
    reg = _load_bundled_registry()
    monkeypatch.setattr(hvaclib.HVACLibraryService, "_get_registry", classmethod(lambda cls: reg))
    return hvaclib.HVACLibraryService


@pytest.mark.parametrize("library_id", ["builtin_basic", "smacna"])
def test_a_round_spline_route_gets_the_flexible_duct(bundled_service, library_id):
    selection = bundled_service.select_segment_type(library_id, "Circular", curved=True, flex=True)
    assert selection.type_def.id == "circular_flex"


@pytest.mark.parametrize("library_id", ["builtin_basic", "smacna"])
def test_a_rectangular_spline_route_falls_back_to_the_curved_duct(bundled_service, library_id):
    # No flexible rectangular duct: the plain curved one is used.
    selection = bundled_service.select_segment_type(library_id, "Rectangular", curved=True, flex=True)
    assert selection.type_def.id == "rectangular_generic"


def test_an_arc_route_keeps_the_curved_duct(bundled_service):
    selection = bundled_service.select_segment_type("smacna", "Circular", curved=True)
    assert selection.type_def.id == "circular_generic"


def test_a_curved_duct_chosen_by_hand_on_a_spline_route_stays(bundled_service):
    selection = bundled_service.resolve_segment_type("smacna", "circular_generic", "Circular", curved=True, flex=True)
    assert selection.type_def.id == "circular_generic"
    assert selection.status == "retained"


def test_a_spline_route_whose_profile_changes_moves_to_a_type_for_the_new_profile(bundled_service):
    selection = bundled_service.resolve_segment_type("smacna", "circular_flex", "Rectangular", curved=True, flex=True)
    assert selection.type_def.id == "rectangular_generic"
