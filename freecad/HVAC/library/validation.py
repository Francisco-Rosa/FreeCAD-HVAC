# SPDX-License-Identifier: LGPL-2.1-or-later
"""
Parameter and context validation for HVAC library items: checks a type-def's
own property values (normalize_property_value/validate_value/resolve_params)
and whether a type-def is even a valid fit for the current network context
(context_violations and friends), a compact JSON-Schema-like rule set rather
than a full validation library.
"""

import math

# Standardized qualifier/derived_values key vocabulary (NetworkParser.
# classify_flow -- see core/TOPOLOGY_CLASSIFICATION.md) that "constraints"
# (a type-def's own, or a loss variant's) may reference. Kept here, next
# to flow_classification_violations() which actually reads them, so
# unknown_flow_constraint_keys() (used at JSON-load time by Library.py to
# reject a typo'd key instead of letting it silently become a permanent
# no-op constraint) can never drift out of sync with what's actually
# checked.
KNOWN_QUALIFIER_KEYS = frozenset(
    {
        "alignment",
        "aligned_side",
        "aligned_corner",
        "transition_form",
        "common_leg",
        "profile_relation",
        "inlet_profile",
        "outlet_profile",
        "terminal_function",  # end nodes, from the system (ROADMAP 6.5)
    }
)
# NOTE: this is deliberately only the vocabulary NetworkParser.classify_flow
# itself produces. A value like "transition_angle" that depends on a
# *selected fitting's own* properties (e.g. TransitionLength) is a
# fitting/type-derived value, not a parser-derived one -- it belongs in a
# separate vocabulary exposed by the library layer once that's needed, never
# pretended to be parser output here.
KNOWN_DERIVED_VALUE_KEYS = frozenset(
    {"area_ratio", "aspect_ratio_in", "aspect_ratio_out", "offset_ratio", "branch_angle"}
)
# Top-level constraint keys flow_classification_violations()/context_violations()
# already give dedicated handling -- never checked against
# KNOWN_DERIVED_VALUE_KEYS as a "derived value" typo.
_RESERVED_CONSTRAINT_KEYS = frozenset(
    {
        "degree",
        "degree_min",
        "degree_max",
        "flow_class",
        "qualifiers",
        "profile_relation",
        "inlet_profile",
        "outlet_profile",
    }
)


def unknown_flow_constraint_keys(constraints):
    """
    Return (unknown_qualifier_keys, unknown_top_level_keys) -- any key
    under `constraints["qualifiers"]` not in KNOWN_QUALIFIER_KEYS, and any
    other top-level `constraints` key that isn't one of the reserved
    keys (degree/flow_class/qualifiers/profile_relation/inlet_profile/
    outlet_profile) and isn't in KNOWN_DERIVED_VALUE_KEYS either. Both
    lists are sorted and empty when everything's recognized. Used at
    JSON-load time (Library.py) so a typo'd constraint key (e.g.
    "aera_ratio") fails loudly instead of silently becoming a no-op --
    flow_classification_violations()'s derived_values fallthrough only
    ever checks a key that's actually present in `derived_values`.
    """
    constraints = dict(constraints or {})
    unknown_qualifiers = sorted(set(dict(constraints.get("qualifiers", {}) or {}).keys()) - KNOWN_QUALIFIER_KEYS)
    unknown_top_level = sorted((set(constraints.keys()) - _RESERVED_CONSTRAINT_KEYS) - KNOWN_DERIVED_VALUE_KEYS)
    return unknown_qualifiers, unknown_top_level


_QUANTITY_TYPES = {
    "App::PropertyLength",
    "App::PropertyDistance",
    "App::PropertyAngle",
    "App::PropertyFloatConstraint",
    "App::PropertyPressure",
}
_STRING_TYPES = {"App::PropertyString", "App::PropertyEnumeration", "App::PropertyPath", "App::PropertyFile"}


def normalize_property_value(prop_type, value):
    """Convert FreeCAD property values into small, predictable Python values."""
    if value is None:
        return None

    prop_type = str(prop_type or "")

    if prop_type == "App::PropertyBool":
        return bool(value)
    if prop_type.startswith("App::PropertyInteger"):
        return int(value)
    if prop_type == "App::PropertyFloat" or prop_type in _QUANTITY_TYPES:
        return float(value.Value if hasattr(value, "Value") else value)
    if prop_type in _STRING_TYPES:
        return str(value)

    # Keep compound FreeCAD values such as vectors/placements unchanged.
    return value


def _numeric(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


# Every key a property def's "validation" block may use -- exactly the ones
# validate_value() below understands.
KNOWN_VALIDATION_RULE_KEYS = frozenset(
    {"enum", "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf", "minLength", "maxLength"}
)

# Every key a type-def property entry may use (see Library.HVACPropertyDef).
KNOWN_PROPERTY_DEF_KEYS = frozenset(
    {"name", "prop_type", "group", "description", "default", "editor_mode", "required", "validation", "per_port"}
)

# A "per_port" property holds one value for each connected port instead of
# one value for the whole fitting, so it works for any number of ports. On
# the FreeCAD object it is stored as a list; this maps the property type
# the type-def declares (the type of ONE value) to that list type.
PER_PORT_LIST_TYPES = {
    "App::PropertyLength": "App::PropertyFloatList",
    "App::PropertyDistance": "App::PropertyFloatList",
    "App::PropertyFloat": "App::PropertyFloatList",
    "App::PropertyAngle": "App::PropertyFloatList",
    "App::PropertyBool": "App::PropertyBoolList",
    "App::PropertyInteger": "App::PropertyIntegerList",
}

# The hidden companion list of a per-port property: which port (edge_key)
# each stored value belongs to. Values are matched to ports by this key,
# never by position, so they survive ports being added, removed or reordered.
PER_PORT_KEYS_SUFFIX = "EdgeKeys"


def per_port_keys_name(prop_name):
    """Name of the companion property holding the edge_key of each value of a per-port property."""
    return "{}{}".format(prop_name, PER_PORT_KEYS_SUFFIX)


class PortValues(dict):
    """
    The resolved value of a per-port property: {edge_key: value}, plus the
    `default` used for any port that has no stored value yet (a newly
    connected port, or a context built without a FreeCAD object).
    """

    def __init__(self, values=None, default=None):
        super().__init__(values or {})
        self.default = default

    def for_port(self, port):
        """This property's value for one port (a port dict, or its edge_key)."""
        edge_key = port.get("edge_key") if isinstance(port, dict) else port
        return self.get(edge_key, self.default)

    def in_port_order(self, ports):
        """One value per port, in the given port order."""
        return [self.for_port(port) for port in ports]


def unknown_property_def_keys(raw_property):
    """
    Keys in one raw type-def property entry that nothing reads.

    A misspelled or made-up key (e.g. a top-level "min" instead of
    "validation": {"minimum": ...}) would otherwise load fine and silently
    never be enforced. Unknown "validation" rules are reported with a
    "validation." prefix.
    """
    unknown = [key for key in raw_property if key not in KNOWN_PROPERTY_DEF_KEYS]
    rules = raw_property.get("validation") or {}
    unknown.extend("validation.{}".format(key) for key in rules if key not in KNOWN_VALIDATION_RULE_KEYS)
    return sorted(unknown)


def validate_value(type_id, prop_name, value, rules):
    """Validate one normalized property using a compact JSON-Schema-like subset."""
    rules = dict(rules or {})
    prefix = "Type '{}', property '{}'".format(type_id, prop_name)

    if value is None:
        return

    if _numeric(value) and isinstance(value, float) and not math.isfinite(value):
        raise ValueError("{} must be finite".format(prefix))

    if "enum" in rules and value not in list(rules["enum"] or []):
        raise ValueError("{} must be one of {!r}; got {!r}".format(prefix, rules["enum"], value))

    if "minimum" in rules and value < rules["minimum"]:
        raise ValueError("{} must be >= {}; got {}".format(prefix, rules["minimum"], value))
    if "maximum" in rules and value > rules["maximum"]:
        raise ValueError("{} must be <= {}; got {}".format(prefix, rules["maximum"], value))
    if "exclusiveMinimum" in rules and value <= rules["exclusiveMinimum"]:
        raise ValueError("{} must be > {}; got {}".format(prefix, rules["exclusiveMinimum"], value))
    if "exclusiveMaximum" in rules and value >= rules["exclusiveMaximum"]:
        raise ValueError("{} must be < {}; got {}".format(prefix, rules["exclusiveMaximum"], value))

    if "multipleOf" in rules:
        step = float(rules["multipleOf"])
        if step <= 0.0:
            raise ValueError("{} has invalid multipleOf {}".format(prefix, step))
        q = float(value) / step
        if not math.isclose(q, round(q), rel_tol=1e-9, abs_tol=1e-9):
            raise ValueError("{} must be a multiple of {}; got {}".format(prefix, step, value))

    if "minLength" in rules and len(value) < int(rules["minLength"]):
        raise ValueError("{} length must be >= {}".format(prefix, rules["minLength"]))
    if "maxLength" in rules and len(value) > int(rules["maxLength"]):
        raise ValueError("{} length must be <= {}".format(prefix, rules["maxLength"]))


def _resolve_per_port(type_def, pdef, obj, supplied):
    """
    Resolve one per-port property into a PortValues.

    Sources, in order: a supplied value (a {edge_key: value} mapping, or one
    plain value meant for every port), then the FreeCAD object's own stored
    list and its companion edge-key list, then nothing but the default.
    """
    rules = getattr(pdef, "validation", {})
    default = normalize_property_value(pdef.prop_type, getattr(pdef, "default", None))
    by_edge = {}

    if pdef.name in supplied:
        raw = supplied[pdef.name]
        if isinstance(raw, dict):
            by_edge = dict(raw)
            default = getattr(raw, "default", default)
        else:
            # One plain value: it applies to every port.
            default = normalize_property_value(pdef.prop_type, raw)
    elif obj is not None and hasattr(obj, pdef.name):
        values = list(getattr(obj, pdef.name, None) or [])
        keys = list(getattr(obj, per_port_keys_name(pdef.name), None) or [])
        # A list that is out of step with its keys can't be trusted; fall back to the default.
        if len(values) == len(keys):
            by_edge = dict(zip(keys, values))

    resolved = PortValues(default=default)
    for edge_key, raw_value in by_edge.items():
        value = normalize_property_value(pdef.prop_type, raw_value)
        validate_value(type_def.id, "{}[{}]".format(pdef.name, edge_key), value, rules)
        resolved[edge_key] = value
    validate_value(type_def.id, pdef.name, default, rules)
    return resolved


def resolve_params(type_def, obj=None, supplied=None):
    """
    Resolve type properties from supplied values / FreeCAD object / JSON defaults,
    normalize them, and apply declarative validation.
    """
    supplied = dict(supplied or {})
    params = {}

    for pdef in list(getattr(type_def, "properties", []) or []):
        if bool(getattr(pdef, "per_port", False)):
            params[pdef.name] = _resolve_per_port(type_def, pdef, obj, supplied)
            continue

        if pdef.name in supplied:
            raw = supplied[pdef.name]
        elif obj is not None and hasattr(obj, pdef.name):
            raw = getattr(obj, pdef.name)
        else:
            raw = getattr(pdef, "default", None)

        value = normalize_property_value(pdef.prop_type, raw)
        if bool(getattr(pdef, "required", True)) and value is None:
            raise ValueError("Type '{}': required property '{}' has no value".format(type_def.id, pdef.name))

        validate_value(type_def.id, pdef.name, value, getattr(pdef, "validation", {}))
        params[pdef.name] = value

    return params


def _check_rule(violations, type_def, label, value, rules, strict_missing=False):
    """Validate one context value against a constraint sub-rule, appending
    a human-readable message to `violations` instead of raising -- reuses
    validate_value()'s enum/minimum/maximum/exclusive-bound operators so
    flow_class/qualifiers/derived_values constraints follow the same rules
    as a type-def's own property validation.

    strict_missing=False (type-def matching): a value that's genuinely
    absent from context is never treated as a mismatch -- a caller that
    hasn't populated some piece of classification data shouldn't
    accidentally break an otherwise-valid match.

    strict_missing=True (loss-variant selection, see resolve_loss_variant):
    a declared constraint whose value is absent counts as a violation --
    picking between several mutually-exclusive variants on missing data
    must never "accidentally" match one of them.
    """
    if value is None:
        if strict_missing and rules:
            violations.append(
                "Type '{}': '{}' has no value to satisfy constraint {!r}".format(type_def.id, label, rules)
            )
        return
    try:
        validate_value(type_def.id, label, value, rules)
    except ValueError as exc:
        violations.append(str(exc))


def flow_classification_violations(type_def, constraints, context, strict_missing=False):
    """
    Return violation messages for the flow-classification constraint keys
    (`flow_class`, `qualifiers.<key>`, `profile_relation`, `inlet_profile`,
    `outlet_profile`, and any `derived_values` entry) against `constraints`
    -- the one constraint evaluator shared by context_violations() (a
    type-def's own top-level `constraints`, decides whether the physical
    fitting TypeId is applicable -- always strict_missing=False, permissive)
    and resolve_loss_variant() (a loss-def's own `loss.variants[].constraints`,
    decides which loss function applies *after* the TypeId is already
    selected -- always strict_missing=True, see that function and
    _check_rule()'s own docstring for why the two differ). Both ever pass
    the exact same `constraints`/`context` shape here, so a library author
    uses one operator vocabulary everywhere.

    `type_def` is only used for its `.id` in violation messages -- this
    never reads `type_def.constraints` itself, since the caller decides
    which constraints dict (`type_def.constraints` or one variant's own)
    to check.
    """
    violations = []
    constraints = dict(constraints or {})

    if "flow_class" in constraints:
        _check_rule(
            violations,
            type_def,
            "flow_class",
            context.get("flow_class"),
            constraints["flow_class"],
            strict_missing=strict_missing,
        )

    qualifiers = dict(context.get("qualifiers", {}) or {})
    for key in ("profile_relation", "inlet_profile", "outlet_profile"):
        if key in constraints:
            value = context.get(key, qualifiers.get(key))
            _check_rule(violations, type_def, key, value, constraints[key], strict_missing=strict_missing)

    if "qualifiers" in constraints:
        for key, rule in dict(constraints["qualifiers"] or {}).items():
            _check_rule(
                violations,
                type_def,
                "qualifiers.{}".format(key),
                qualifiers.get(key),
                rule,
                strict_missing=strict_missing,
            )

    # Any other declared constraint key is checked against a matching
    # derived_values entry (e.g. "area_ratio", "transition_angle") --
    # numeric values only ever live in derived_values, never qualifiers.
    derived_values = dict(context.get("derived_values", {}) or {})
    handled_keys = {"flow_class", "qualifiers", "profile_relation", "inlet_profile", "outlet_profile"}
    for key, rule in constraints.items():
        if key in handled_keys:
            continue
        if key in derived_values:
            _check_rule(violations, type_def, key, derived_values.get(key), rule, strict_missing=strict_missing)
        elif strict_missing:
            _check_rule(violations, type_def, key, None, rule, strict_missing=True)

    return violations


def _constraint_specificity(constraints):
    """
    Rough "how many leaf conditions does this constraints dict declare"
    count, used only to rank equally-valid loss variants by specificity --
    more declared conditions wins, a tie is ambiguous. Mirrors the
    "specific wins" philosophy of HVACLibrary's own type-selection ranking
    without reusing its priority field (a loss variant has no
    HVACSelectionDef of its own).
    """
    constraints = dict(constraints or {})
    count = 0
    for key, rule in constraints.items():
        if key == "qualifiers":
            count += len(dict(rule or {}))
        else:
            count += 1
    return count


def resolve_loss_variant(type_def, context):
    """
    Pick exactly one applicable (module, function) loss-callable pair for
    `type_def` given the current classification/context, evaluating each
    declared `loss.variants[]` entry's own `constraints` with the exact
    same flow_classification_violations() rules used for type-def
    matching -- see that function's docstring for why this is the one
    constraint evaluator, not a second incompatible one.

    Precedence:
      1. No variants declared at all -> the type-def's own top-level
         loss_module/loss_function (the pre-existing simple schema,
         unchanged).
      2. Exactly one variant's constraints are all satisfied -> that
         variant.
      3. More than one variant matches -> the most specific one wins
         (see _constraint_specificity); a genuine tie at the top
         specificity is a JSON-authoring ambiguity and raises ValueError
         rather than silently picking one.
      4. No variant matches -> the type-def's own top-level
         loss_module/loss_function, if declared, as an explicit
         wildcard/default; otherwise ("", "") -- "no applicable loss
         model", the same clean signal call_loss() already gives its
         caller for a type with no loss function wired up at all.

    Returns (module, function) -- either may be "" if nothing applies.

    Uses flow_classification_violations()'s strict_missing=True mode: a
    variant's constraint referencing a key that's genuinely absent from
    `context` (as opposed to present with an explicit, non-matching value
    like "" or "unknown") is treated as unsatisfied, not skipped -- unlike
    type-def matching's permissive default, picking between several
    mutually-exclusive loss variants on missing data must never
    "accidentally" match one of them.
    """
    variants = list(getattr(type_def, "loss_variants", None) or [])
    if not variants:
        return type_def.loss_module, type_def.loss_function

    matches = [
        v for v in variants if not flow_classification_violations(type_def, v.constraints, context, strict_missing=True)
    ]

    if not matches:
        return type_def.loss_module, type_def.loss_function

    if len(matches) == 1:
        winner = matches[0]
    else:
        max_specificity = max(_constraint_specificity(v.constraints) for v in matches)
        top = [v for v in matches if _constraint_specificity(v.constraints) == max_specificity]
        if len(top) != 1:
            raise ValueError(
                "Type '{}': ambiguous loss variant match -- {} variants (out of {} total) tie at the same "
                "specificity for the current flow classification".format(type_def.id, len(top), len(variants))
            )
        winner = top[0]

    return winner.module, winner.function


def context_violations(type_def, context):
    """
    Return a list of human-readable constraint violations for the given
    context against a type descriptor's constraints/topology/profile
    restrictions. An empty list means the context is fully compatible.

    This is the shared compatibility rule set used both by validate_context()
    (raises on the first violation, for geometry execution) and by the
    library registry's matches_type()/select_type() (boolean/ranking use,
    for automatic type selection) -- see freecad/HVAC/library/Library.py.
    """
    violations = []
    constraints = dict(getattr(type_def, "constraints", {}) or {})
    category = str(getattr(type_def, "category", "") or "")
    profiles = set(getattr(type_def, "profiles", []) or [])

    if category == "junction":
        ports = list(context.get("connected_ports", []) or [])
        degree = len(ports)

        # Degree: how many ducts connect here.
        if "degree" in constraints and degree != int(constraints["degree"]):
            violations.append("Type '{}' requires degree {}; got {}".format(type_def.id, constraints["degree"], degree))
        if "degree_min" in constraints and degree < int(constraints["degree_min"]):
            violations.append(
                "Type '{}' requires degree >= {}; got {}".format(type_def.id, constraints["degree_min"], degree)
            )
        if "degree_max" in constraints and degree > int(constraints["degree_max"]):
            violations.append(
                "Type '{}' requires degree <= {}; got {}".format(type_def.id, constraints["degree_max"], degree)
            )

        # Topology: through/branch/cross/multiport/end, as classified by NetworkParser.
        expected_topology = str(getattr(type_def, "topology", "") or "")
        actual_topology = str(context.get("topology", "") or "")
        if (
            expected_topology
            and expected_topology != "generic"
            and actual_topology
            and expected_topology != actual_topology
        ):
            violations.append(
                "Type '{}' requires topology '{}'; got '{}'".format(type_def.id, expected_topology, actual_topology)
            )

        # Profile: does every connected port's duct shape (Circular/
        # Rectangular/Oval) match what this type supports? "Generic" is a
        # wildcard used by profile-agnostic placeholder types (e.g. topology
        # marker fittings), which must accept any connected duct profile
        # rather than being restricted to a literal "Generic" port profile.
        if profiles and "Generic" not in profiles:
            for index, port in enumerate(ports):
                profile = str(port.get("profile", "") or "")
                if profile and profile not in profiles:
                    violations.append(
                        "Type '{}' does not support profile '{}' on port {}".format(type_def.id, profile, index)
                    )

        # Flow classification (NetworkParser.JunctionAnalysis.flow_class/
        # qualifiers/derived_values) -- independent of topology/family, so a
        # type-def can additionally require e.g. an expansion transition
        # with an eccentric, single-plane alignment. Shared with
        # resolve_loss_variant()'s own per-variant "constraints" -- see
        # flow_classification_violations().
        violations.extend(flow_classification_violations(type_def, constraints, context))

    elif category == "segment" and profiles and "Generic" not in profiles:
        profile = str(context.get("profile", "") or "")
        if profile and profile not in profiles:
            violations.append("Type '{}' does not support segment profile '{}'".format(type_def.id, profile))

    return violations


def validate_context(type_def, context):
    """Apply structural constraints declared by the type descriptor."""
    violations = context_violations(type_def, context)
    if violations:
        raise ValueError(violations[0])


def is_context_valid(type_def, context):
    """Boolean form of context_violations(), for registry matching use."""
    return not context_violations(type_def, context)
