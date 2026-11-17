# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the HVAC addon.

"""
Standard fitting-loss functions shared by every library.

A type-def points at one of these with
`"loss": {"module": "shared:losses", "function": "loss_elbow_generic"}`.
A library only needs its own loss module for a fitting whose loss is
genuinely different from the standard one.

Each function receives the same context dict as the shape generators (see
Junction.execute), augmented by the airflow solver with a
"flow_rate_lps"/"velocity_ms"/"reynolds" set of keys on every entry of
"connected_ports", plus "air_density"/"air_kinematic_viscosity". It returns
an analysis.loss.LossEvaluation (never a bare dict/float/None) -- see
library/loss_api.py's own docstring for the LossPath/LossEvaluation/
LossStatus shapes. Compare a result's own status against
context["loss_api"]'s EXACT/APPROXIMATION/CUSTOM/FALLBACK/UNSUPPORTED
aliases. These functions must not do any pressure-unit arithmetic
themselves -- that's the solver's job.

Elbow/transition/tee losses come from SMACNA/ASHRAE duct fitting tables via
HVACLossAPI.elbow_loss/transition_loss/branch_loss (see
library/loss_tables/ for the table data and the misprints kept as printed). A true
Wye has no Tee-style common/straight leg, so it uses HVACLossAPI.wye_loss
instead. Cross and multiport fittings use HVACLossAPI.manifold_loss, which
breaks the junction into a sequence of the same tee/wye lookups (no
dedicated table exists for 4+ port fittings). A "true cross" with more than
one inlet AND more than one outlet has no single trunk to break down
against, so it falls back to a flat coefficient.
"""


def loss_through_generic(context):
    # A generic "through" type covers straight/offset/bend families in one
    # type, so it may be a bend, an area change, or both -- try the elbow
    # (CenterlineRadius-driven) reading first, then fall back to the
    # transition (area-change) reading.
    api = context["loss_api"]
    result = api.elbow_loss(context)
    if result.status != api.UNSUPPORTED:
        return result
    return api.transition_loss(context)


def loss_elbow_generic(context):
    return context["loss_api"].elbow_loss(context)


def loss_elbow_mitered(context):
    # An elbow made of straight pieces (NumberOfCuts + 1 of them): the gored
    # elbow table, or the plain mitered one when there is a single joint.
    return context["loss_api"].elbow_loss(_with_properties(context, ElbowConstruction="gored"))


def loss_elbow_vaned(context):
    # A mitered rectangular elbow with turning vanes of the VaneDesign given.
    return context["loss_api"].elbow_loss(_with_properties(context, ElbowConstruction="turning_vanes"))


def loss_transition_generic(context):
    return context["loss_api"].transition_loss(context)


def loss_offset_generic(context):
    return context["loss_api"].offset_loss(context)


def loss_tee_generic(context):
    return context["loss_api"].branch_loss(context)


def loss_tee_conical(context):
    # A tap whose collar flares out toward the run (a saddle tap): the
    # conical-branch tee tables (SMACNA 14-14 B, C; 14-14 V on a
    # rectangular main). There is no converging table; the plain one is used.
    return context["loss_api"].branch_loss(_with_properties(context, BranchStyle="conical"))


def loss_tee_45_entry(context):
    # A tap with a 45 degree entry (a shoe tap): SMACNA 14-14 N diverging
    # and 14-13 F converging on a rectangular main. On a round main there
    # is no such table; the plain one is used.
    return context["loss_api"].branch_loss(_with_properties(context, BranchStyle="45_entry"))


def loss_tee_damper(context):
    # A rectangular tee with a damper in the branch: SMACNA 14-14 R
    # (diverging). The damper is loss-only, it is not drawn. There is no
    # converging table; the plain one is used.
    return context["loss_api"].branch_loss(_with_properties(context, BranchStyle="damper"))


def loss_tee_45_entry_damper(context):
    # A rectangular 45 degree entry (shoe) tap with a damper: SMACNA 14-14 P
    # (diverging). No converging table; the plain one is used.
    return context["loss_api"].branch_loss(_with_properties(context, BranchStyle="45_entry_damper"))


def loss_tee_extractor(context):
    # A rectangular tee with an extractor (turning blades) at the branch:
    # SMACNA 14-14 S (diverging). Loss-only, not drawn. No converging table.
    return context["loss_api"].branch_loss(_with_properties(context, BranchStyle="extractor"))


def loss_wye_generic(context):
    # A true Wye has no Tee-style common/straight leg, so this routes to
    # the Wye-specific API rather than branch_loss() (see HVACLossAPI.
    # wye_loss's own docstring, and TOPOLOGY_CLASSIFICATION.md's
    # common_leg qualifier, which a Wye never gets).
    return context["loss_api"].wye_loss(context)


# ----------------------------------------------------------------------
# Flow-dependent loss variants (see freecad/HVAC/library/Library.py's
# HVACLossVariantDef / validation.resolve_loss_variant): one physical
# fitting TypeId can carry several of these, picked per-call from the
# classifier's own flow_class/qualifiers["common_leg"] rather than
# needing a separate TypeId per flow case -- see each JSON type-def's own
# "loss.variants" and TOPOLOGY_CLASSIFICATION.md.
# ----------------------------------------------------------------------


def loss_transition_expansion(context):
    return context["loss_api"].transition_loss(context)


def loss_transition_contraction(context):
    return context["loss_api"].transition_loss(context)


def loss_branch_diverging_run(context):
    return context["loss_api"].branch_loss(context)


def loss_branch_converging_run(context):
    return context["loss_api"].branch_loss(context)


def loss_branch_diverging_branch(context):
    return context["loss_api"].branch_loss_bullhead(context)


def loss_branch_converging_branch(context):
    return context["loss_api"].branch_loss_bullhead(context)


def loss_cross_generic(context):
    api = context["loss_api"]
    result = api.manifold_loss(context)
    if result.status != api.UNSUPPORTED:
        return result
    return api.uniform_fallback_loss(context, 0.75)


def loss_multiport_generic(context):
    api = context["loss_api"]
    result = api.manifold_loss(context)
    if result.status != api.UNSUPPORTED:
        return result
    return api.uniform_fallback_loss(context, 1.0)


def _with_properties(context, **overrides):
    """A copy of the context with some properties replaced (the original is left alone)."""
    properties = dict(context.get("properties") or {})
    properties.update(overrides)
    return dict(context, properties=properties)


def _fixed_pressure_drop(context):
    """True when the type's LossMode asks for a pressure drop instead of a coefficient."""
    mode = str((context.get("properties") or {}).get("LossMode", "") or "").strip().lower()
    return mode.replace("_", " ") == "fixed pressure drop"


def loss_diffuser_generic(context):
    # LossMode "Fixed pressure drop" uses the PressureDrop given; anything
    # else (or a type with no LossMode) uses K at the neck.
    if _fixed_pressure_drop(context):
        return context["loss_api"].fixed_pressure_drop_loss(context)
    return context["loss_api"].terminal_component_loss(context)


def loss_ahu(context):
    # The unit itself (its own coefficient or pressure drop, as for any
    # terminal) plus, where the duct leaves its fan, the fan connection's
    # system effect (SMACNA 14-11 F to J, 14-16 I).
    api = context["loss_api"]
    unit = loss_diffuser_generic(context)
    fan = api.fan_connection_loss(context)
    return api.sum_losses(unit, fan)


def loss_equipment_connection(context):
    # Where a network meets its equipment (an AHU, a fan; ROADMAP 6.5): only
    # the fan connection's system effect (SMACNA 14-11 F to J, 14-16 I). The
    # equipment's own internal pressure drop belongs to the HVACEquipment
    # object, which adds it to each network's worst path.
    api = context["loss_api"]
    collar = api.terminal_component_loss(_with_properties(context, LossCoefficient=0.0))
    fan = api.fan_connection_loss(context)
    return api.sum_losses(collar, fan)


def loss_register_generic(context):
    # A register is a grille with a damper behind it: the two coefficients add up.
    if _fixed_pressure_drop(context):
        return context["loss_api"].fixed_pressure_drop_loss(context)
    properties = context.get("properties") or {}
    grille = float(properties.get("LossCoefficient", 0.0) or 0.0)
    damper = float(properties.get("DamperLossCoefficient", 0.0) or 0.0)
    return context["loss_api"].terminal_component_loss(_with_properties(context, LossCoefficient=grille + damper))


def loss_plenum(context):
    return context["loss_api"].plenum_loss(context)


def loss_damper_generic(context):
    # DamperType "Coefficient" (or a type with no DamperType at all) uses the
    # user's own K; any other choice reads the damper tables for that kind
    # of damper at its current blade position.
    properties = context.get("properties") or {}
    kind = str(properties.get("DamperType", "") or "").strip().lower()
    if kind in ("", "coefficient"):
        return context["loss_api"].inline_device_loss(context)
    return context["loss_api"].damper_loss(context)


def loss_vav_generic(context):
    if _fixed_pressure_drop(context):
        return context["loss_api"].fixed_pressure_drop_loss(context)
    return context["loss_api"].inline_device_loss(context)


# FilterCondition -> where between the clean and the final pressure drop the filter is taken.
_FILTER_CONDITIONS = {"clean": 0.0, "mid-life": 0.5, "final": 1.0}


def filter_pressure_drop(properties):
    """
    A filter's pressure drop in Pa for its FilterCondition: the clean drop,
    the final (change-out) drop, or halfway between them at mid-life.
    """
    clean = max(float(properties.get("CleanPressureDrop", 0.0) or 0.0), 0.0)
    final = max(float(properties.get("FinalPressureDrop", 0.0) or 0.0), clean)
    condition = str(properties.get("FilterCondition", "") or "mid-life").strip().lower()
    if condition not in _FILTER_CONDITIONS:
        raise ValueError("unknown FilterCondition '{}'".format(properties.get("FilterCondition")))
    return clean + (final - clean) * _FILTER_CONDITIONS[condition]


def loss_inline_device(context):
    """
    Loss of an inline device (silencer, filter, coil, fire damper, access
    door, flexible connector), from whichever of its own properties it has:

    - FilterCondition: the filter's pressure drop at that condition
      (filter_pressure_drop), as a fixed pressure drop;
    - LossMode "Fixed pressure drop": the PressureDrop given;
    - a LossCoefficient above 0: that K at the duct's velocity;
    - otherwise no loss of its own: the duct carries straight through, read
      as a transition (no loss for an unchanged section).
    """
    api = context["loss_api"]
    properties = context.get("properties") or {}
    if "FilterCondition" in properties:
        # An unknown FilterCondition raises: the type-def's enum rules it out.
        drop = filter_pressure_drop(properties)
        return api.fixed_pressure_drop_loss(_with_properties(context, PressureDrop=drop))
    if _fixed_pressure_drop(context):
        return api.fixed_pressure_drop_loss(context)
    if float(properties.get("LossCoefficient", 0.0) or 0.0) > 0.0:
        return api.inline_device_loss(context)
    return api.transition_loss(context)


# ----------------------------------------------------------------------
# Table-driven terminal and inline fittings (SMACNA Tables 14-15 to
# 14-18). Each reads its shape from the type's own properties -- see the
# matching HVACLossAPI method for the property names.
# ----------------------------------------------------------------------


def loss_entry(context):
    return context["loss_api"].entry_loss(context)


def loss_exit(context):
    return context["loss_api"].exit_loss(context)


def loss_screen(context):
    return context["loss_api"].screen_loss(context)


def loss_damper(context):
    return context["loss_api"].damper_loss(context)


def loss_obstruction(context):
    return context["loss_api"].obstruction_loss(context)


# One function per terminal type whose shape is fixed by the type itself, so
# the type-def need not carry an EntryType/ExitType property of its own.


def loss_entry_plain(context):
    return context["loss_api"].entry_loss(_with_properties(context, EntryType="duct_in_wall"))


def loss_entry_bellmouth(context):
    return context["loss_api"].entry_loss(_with_properties(context, EntryType="bellmouth"))


def loss_entry_conical(context):
    return context["loss_api"].entry_loss(_with_properties(context, EntryType="conical"))


def loss_hood_intake(context):
    return context["loss_api"].entry_loss(_with_properties(context, EntryType="intake_hood"))


def loss_hood_tapered(context):
    return context["loss_api"].entry_loss(_with_properties(context, EntryType="tapered_hood"))


def loss_exit_plain(context):
    return context["loss_api"].exit_loss(_with_properties(context, ExitType="abrupt"))


def loss_exit_conical(context):
    return context["loss_api"].exit_loss(_with_properties(context, ExitType="conical"))


def loss_exit_pyramidal(context):
    # DiffuserType "Plane" widens one pair of sides only; anything else widens all four.
    kind = str((context.get("properties") or {}).get("DiffuserType", "") or "").strip().lower()
    exit_type = "plane_diffuser" if kind == "plane" else "pyramidal_diffuser"
    return context["loss_api"].exit_loss(_with_properties(context, ExitType=exit_type))


def loss_hood_exhaust(context):
    return context["loss_api"].exit_loss(_with_properties(context, ExitType="exhaust_hood"))
