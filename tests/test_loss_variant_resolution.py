# SPDX-License-Identifier: LGPL-2.1-or-later
"""
Focused tests for the flow-dependent loss-variant resolver
(validation.resolve_loss_variant / HVACLossVariantDef /
HVACLibraryRegistry.call_loss): one physical fitting TypeId can carry
several flow-dependent loss formulas (e.g. an expanding vs. contracting
transition, or an ordinary vs. bullhead tee) without needing a separate
TypeId per flow case -- see freecad/HVAC/library/Library.py and
freecad/HVAC/library/validation.py.
"""
import os

import conftest  # noqa: F401 -- installs FreeCAD/FreeCADGui/Part/PySide stubs

import pytest

from freecad.HVAC.library import validation
from freecad.HVAC.library.Library import (
    HVACLossVariantDef,
    HVACLibraryRegistry,
    HVACSelectionDef,
    HVACTypeDef,
)

LIBRARIES_ROOT = os.path.join(os.path.dirname(__file__), "..", "freecad", "HVAC", "libraries")


def _type_def(loss_module="junction_losses", loss_function="loss_tee_generic", loss_variants=None):
    return HVACTypeDef(
        id="branch_tee_generic",
        label="Tee - Generic",
        category="junction",
        topology="branch",
        family=["branch.tee"],
        profiles=["Circular"],
        loss_module=loss_module,
        loss_function=loss_function,
        loss_variants=list(loss_variants or []),
        selection=HVACSelectionDef(kind="model", priority=50),
    )


def _variant(constraints, module, function):
    return HVACLossVariantDef(constraints=dict(constraints), module=module, function=function)


# ----------------------------------------------------------------------
# Legacy (no variants) schema
# ----------------------------------------------------------------------

def test_legacy_loss_schema_without_variants_is_unchanged():
    type_def = _type_def(loss_module="junction_losses", loss_function="loss_tee_generic")
    # No loss_variants declared at all -- resolve_loss_variant() must
    # return the plain top-level module/function regardless of context,
    # exactly like call_loss() behaved before this feature existed.
    assert validation.resolve_loss_variant(type_def, {}) == ("junction_losses", "loss_tee_generic")
    assert validation.resolve_loss_variant(
        type_def, {"flow_class": "diverging", "qualifiers": {"common_leg": "run"}}
    ) == ("junction_losses", "loss_tee_generic")


# ----------------------------------------------------------------------
# flow_class / qualifiers-specific variants (branch diverging/converging x
# common_leg run/branch -- see NetworkParser.classify_flow)
# ----------------------------------------------------------------------

def test_flow_class_and_qualifier_variant_selected():
    type_def = _type_def(loss_variants=[
        _variant({"flow_class": {"enum": ["diverging"]}, "qualifiers": {"common_leg": {"enum": ["run"]}}},
                 "junction_losses", "loss_branch_diverging_run"),
        _variant({"flow_class": {"enum": ["converging"]}, "qualifiers": {"common_leg": {"enum": ["run"]}}},
                 "junction_losses", "loss_branch_converging_run"),
        _variant({"flow_class": {"enum": ["diverging"]}, "qualifiers": {"common_leg": {"enum": ["branch"]}}},
                 "junction_losses", "loss_branch_diverging_branch"),
        _variant({"flow_class": {"enum": ["converging"]}, "qualifiers": {"common_leg": {"enum": ["branch"]}}},
                 "junction_losses", "loss_branch_converging_branch"),
    ])

    assert validation.resolve_loss_variant(
        type_def, {"flow_class": "diverging", "qualifiers": {"common_leg": "run"}}
    ) == ("junction_losses", "loss_branch_diverging_run")
    assert validation.resolve_loss_variant(
        type_def, {"flow_class": "converging", "qualifiers": {"common_leg": "branch"}}
    ) == ("junction_losses", "loss_branch_converging_branch")


def test_qualifier_specific_smacna_style_variant_wins_over_broader_one():
    # Mirrors the requirement's SMACNA example: a library-specific variant
    # further constrained by a qualifier (transition_form) must win over a
    # broader variant that only checks flow_class, when both match.
    type_def = _type_def(loss_module="", loss_function="", loss_variants=[
        _variant({"flow_class": {"enum": ["expansion"]}}, "generic_losses", "transition_expansion"),
        _variant(
            {"flow_class": {"enum": ["expansion"]}, "qualifiers": {"transition_form": {"enum": ["pyramidal"]}}},
            "smacna_losses", "smacna_rect_pyramidal_expansion",
        ),
    ])

    broad_ctx = {"flow_class": "expansion", "qualifiers": {"transition_form": "single_plane"}}
    specific_ctx = {"flow_class": "expansion", "qualifiers": {"transition_form": "pyramidal"}}

    assert validation.resolve_loss_variant(type_def, broad_ctx) == ("generic_losses", "transition_expansion")
    assert validation.resolve_loss_variant(type_def, specific_ctx) == (
        "smacna_losses", "smacna_rect_pyramidal_expansion"
    )


# ----------------------------------------------------------------------
# Numeric derived_values constraint
# ----------------------------------------------------------------------

def test_numeric_derived_value_constraint_selects_variant():
    type_def = _type_def(loss_module="junction_losses", loss_function="loss_transition_generic", loss_variants=[
        _variant({"flow_class": {"enum": ["expansion"]}, "area_ratio": {"minimum": 1.0, "maximum": 2.0}},
                 "junction_losses", "loss_transition_moderate_expansion"),
        _variant({"flow_class": {"enum": ["expansion"]}, "area_ratio": {"exclusiveMinimum": 2.0}},
                 "junction_losses", "loss_transition_large_expansion"),
    ])

    moderate_ctx = {"flow_class": "expansion", "derived_values": {"area_ratio": 1.5}}
    large_ctx = {"flow_class": "expansion", "derived_values": {"area_ratio": 3.0}}
    out_of_range_ctx = {"flow_class": "expansion", "derived_values": {"area_ratio": 0.5}}

    assert validation.resolve_loss_variant(type_def, moderate_ctx) == (
        "junction_losses", "loss_transition_moderate_expansion"
    )
    assert validation.resolve_loss_variant(type_def, large_ctx) == (
        "junction_losses", "loss_transition_large_expansion"
    )
    # Neither variant's area_ratio range covers 0.5 -- falls back to the
    # type-def's own top-level loss_module/loss_function.
    assert validation.resolve_loss_variant(type_def, out_of_range_ctx) == (
        "junction_losses", "loss_transition_generic"
    )


# ----------------------------------------------------------------------
# No matching variant / fallback / default
# ----------------------------------------------------------------------

def test_no_matching_variant_falls_back_to_default():
    type_def = _type_def(loss_module="junction_losses", loss_function="loss_tee_generic", loss_variants=[
        _variant({"flow_class": {"enum": ["diverging"]}}, "junction_losses", "loss_branch_diverging_run"),
    ])
    result = validation.resolve_loss_variant(type_def, {"flow_class": "converging"})
    assert result == ("junction_losses", "loss_tee_generic")


def test_no_matching_variant_and_no_fallback_reports_no_applicable_loss_model():
    type_def = _type_def(loss_module="", loss_function="", loss_variants=[
        _variant({"flow_class": {"enum": ["diverging"]}}, "junction_losses", "loss_branch_diverging_run"),
    ])
    result = validation.resolve_loss_variant(type_def, {"flow_class": "converging"})
    assert result == ("", "")


def test_wildcard_variant_with_no_constraints_acts_as_in_list_fallback():
    # A variant with an empty/absent "constraints" always matches -- useful
    # as an explicit last-resort entry within the variants list itself,
    # distinct from the type-def's own top-level module/function.
    type_def = _type_def(loss_module="", loss_function="", loss_variants=[
        _variant({"flow_class": {"enum": ["diverging"]}}, "junction_losses", "loss_branch_diverging_run"),
        _variant({}, "junction_losses", "loss_branch_wildcard"),
    ])
    assert validation.resolve_loss_variant(type_def, {"flow_class": "converging"}) == (
        "junction_losses", "loss_branch_wildcard"
    )
    # A more specific variant still wins over the wildcard when it matches.
    assert validation.resolve_loss_variant(type_def, {"flow_class": "diverging"}) == (
        "junction_losses", "loss_branch_diverging_run"
    )


# ----------------------------------------------------------------------
# Ambiguous matches
# ----------------------------------------------------------------------

# ----------------------------------------------------------------------
# Strict-missing behaviour: a loss variant whose constraint references a
# key that's genuinely absent from context must NOT match -- unlike
# type-def matching (context_violations()), which stays permissive about
# missing data. See validation._check_rule()/flow_classification_violations().
# ----------------------------------------------------------------------

def test_strict_missing_flow_class_does_not_match_variant():
    type_def = _type_def(loss_module="junction_losses", loss_function="loss_tee_generic", loss_variants=[
        _variant({"flow_class": {"enum": ["diverging"]}}, "junction_losses", "loss_branch_diverging_run"),
    ])
    # context carries no "flow_class" key at all.
    assert validation.resolve_loss_variant(type_def, {}) == ("junction_losses", "loss_tee_generic")


def test_strict_missing_qualifier_does_not_match_variant():
    type_def = _type_def(loss_module="", loss_function="", loss_variants=[
        _variant(
            {"flow_class": {"enum": ["diverging"]}, "qualifiers": {"common_leg": {"enum": ["branch"]}}},
            "junction_losses", "loss_branch_diverging_branch",
        ),
    ])
    # flow_class matches, but "qualifiers" is entirely absent from context
    # (e.g. a wye with no geometrically identified run pair).
    result = validation.resolve_loss_variant(type_def, {"flow_class": "diverging"})
    assert result == ("", "")


def test_strict_missing_derived_value_does_not_match_variant():
    type_def = _type_def(loss_module="junction_losses", loss_function="loss_transition_generic", loss_variants=[
        _variant({"area_ratio": {"minimum": 1.0}}, "junction_losses", "loss_transition_large_expansion"),
    ])
    # No "derived_values" key in context at all -- the area_ratio
    # constraint can't be confirmed, so this must fall back, not match.
    result = validation.resolve_loss_variant(type_def, {"flow_class": "expansion"})
    assert result == ("junction_losses", "loss_transition_generic")


def test_permissive_type_level_matching_still_tolerates_missing_context():
    # Contrast case: type-def-level matching (context_violations(), via
    # flow_classification_violations(..., strict_missing=False)) must stay
    # permissive -- a candidate type-def is not rejected just because the
    # caller hasn't populated flow_class/qualifiers/derived_values.
    type_def = HVACTypeDef(
        id="through_transition_expansion_only", label="x", category="junction", topology="through",
        family=["through.transition"], profiles=["Circular"],
        constraints={"flow_class": {"enum": ["expansion"]}},
        selection=HVACSelectionDef(kind="model", priority=50),
    )
    context = {"connected_ports": [{"profile": "Circular"}, {"profile": "Circular"}], "topology": "through"}
    assert validation.context_violations(type_def, context) == []


def test_ambiguous_matching_variants_at_same_specificity_raises():
    type_def = _type_def(loss_variants=[
        _variant({"flow_class": {"enum": ["diverging"]}}, "junction_losses", "loss_a"),
        _variant({"flow_class": {"enum": ["diverging"]}}, "junction_losses", "loss_b"),
    ])
    with pytest.raises(ValueError, match="ambiguous"):
        validation.resolve_loss_variant(type_def, {"flow_class": "diverging"})


def test_two_wildcard_variants_are_ambiguous():
    type_def = _type_def(loss_variants=[
        _variant({}, "junction_losses", "loss_a"),
        _variant({}, "junction_losses", "loss_b"),
    ])
    with pytest.raises(ValueError, match="ambiguous"):
        validation.resolve_loss_variant(type_def, {"flow_class": "diverging"})


# ----------------------------------------------------------------------
# End-to-end against the real bundled smacna library (JSON loading ->
# resolve_loss_variant -> HVACLibraryRegistry.call_loss -> real function).
# ----------------------------------------------------------------------

def _load_bundled_registry():
    reg = HVACLibraryRegistry()
    reg.set_search_paths([LIBRARIES_ROOT])
    reg.ensure_loaded()
    return reg


def _port(edge_key, direction, flow_into_junction, diameter, velocity_ms):
    return {
        "edge_key": edge_key,
        "direction": direction,
        "flow_into_junction": flow_into_junction,
        "profile": "Circular",
        "section_params": {"Diameter": diameter},
        "velocity_ms": velocity_ms,
        "reynolds": 0.0,
        "flow_rate_lps": 0.0,
    }


def test_bundled_smacna_branch_generic_declares_four_variants():
    reg = _load_bundled_registry()
    type_def = reg.get_library("smacna").get_type("branch_generic")
    assert len(type_def.loss_variants) == 4
    resolved = {
        (v.constraints["flow_class"]["enum"][0], v.constraints["qualifiers"]["common_leg"]["enum"][0]): v.function
        for v in type_def.loss_variants
    }
    assert resolved[("diverging", "run")] == "loss_branch_diverging_run"
    assert resolved[("converging", "run")] == "loss_branch_converging_run"
    assert resolved[("diverging", "branch")] == "loss_branch_diverging_branch"
    assert resolved[("converging", "branch")] == "loss_branch_converging_branch"


def test_bundled_smacna_call_loss_dispatches_to_bullhead_variant():
    reg = _load_bundled_registry()
    type_def = reg.get_library("smacna").get_type("branch_generic")

    # Bullhead diverging: single inlet on the branch leg, splitting into
    # two collinear run legs -- common_leg="branch".
    common = _port("IN", (-1, 0, 0), True, 300.0, 5.0)
    run_a = _port("RUN_A", (0, 1, 0), False, 200.0, 3.0)
    run_b = _port("RUN_B", (0, -1, 0), False, 200.0, 3.0)
    context = {
        "connected_ports": [common, run_a, run_b],
        "properties": {},
        "flow_class": "diverging",
        "qualifiers": {"common_leg": "branch"},
        "derived_values": {},
    }

    result = reg.call_loss("smacna", type_def, context)

    paths_by_edge = {p.reference_edge_key: p.loss_coefficient for p in result.paths}
    assert set(paths_by_edge.keys()) == {"RUN_A", "RUN_B"}
    assert all(v > 0.0 for v in paths_by_edge.values())


def test_bundled_smacna_call_loss_falls_back_when_flow_class_unresolved():
    # An unresolved/unknown flow_class (e.g. build_loss_evaluator()'s own
    # "" default for a node classify_flow() couldn't place, see
    # NetworkParser.classify_flow) satisfies none of the four flow_class-
    # specific variants -- falls back to the type-def's own top-level
    # loss_module/loss_function, same as before this feature existed.
    reg = _load_bundled_registry()
    type_def = reg.get_library("smacna").get_type("branch_generic")

    primary = _port("IN", (-1, 0, 0), True, 300.0, 5.0)
    straight = _port("STRAIGHT", (1, 0, 0), False, 300.0, 4.0)
    branch = _port("BRANCH", (0, 1, 0), False, 150.0, 3.0)
    context = {
        "connected_ports": [primary, straight, branch], "properties": {},
        "flow_class": "", "qualifiers": {}, "derived_values": {},
    }

    result = reg.call_loss("smacna", type_def, context)
    assert {p.reference_edge_key for p in result.paths} == {"BRANCH", "STRAIGHT"}
