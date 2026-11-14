# HVAC library structure

An HVAC library is any directory under a configured search path (by default
`freecad/HVAC/libraries/`, see `hvaclib.get_default_library_search_paths()`)
containing a `library.json` manifest. `HVACLibraryRegistry.scan_path` auto-
discovers every such directory; there's no separate registration step.

Three libraries ship today:

- **`builtin_basic`** -- minimal generic types, always available.
- **`smacna`** -- SMACNA-based sheet-metal duct/fitting types, the ones
  actually meant for day-to-day modeling.
- **`samples`** -- not for modeling; reference examples of each geometry
  backend. See `samples/README.md`.

## Directory layout

```
<library>/
  library.json                 # manifest (see below)
  __init__.py                  # empty package marker + SPDX header
  generators/
    __init__.py
    <module>.py                # "geometry": {"backend": "generator", module, function} targets
  models/
    <name>.py                  # PartScript files
    <name>.FCStd                # FCStd-template documents
    <name>.json, <name>.step    # static descriptor + source geometry
  types/
    segments/
      <id>.json                # one type-def per file
    junctions/
      <id>.json
```

`generators/`, `models/`, and the two `types/` subfolders are conventional,
not hardcoded -- `library.json`'s `type_roots` is what the loader actually
walks, and `generators_package` is what `import_generator` imports from.
Keep the convention anyway; every shipped library follows it and there's no
reason to diverge.

## `library.json`

```json
{
  "id": "smacna",
  "label": "SMACNA",
  "requires_api": {"geometry": 3, "loss": 1},
  "generators_package": "freecad.HVAC.libraries.smacna.generators",
  "default_construction": {
    "layers": [{
      "id": "shape",
      "roles": ["flow_surface", "structural_shell"],
      "default_material_role": "flow_surface"
    }]
  },
  "type_roots": ["types/segments", "types/junctions"]
}
```

- `id`: stable identifier, used in `context["library_id"]` and everywhere a
  type is addressed as `(library_id, type_id)`.
- `label`: display name.
- `requires_api` (optional): the `HVACLibraryAPI.API_VERSION` ("geometry")
  and `HVACLossAPI.API_VERSION` ("loss") the library was written for; a
  library written for another version is refused with a message saying so.
  What a library may use is fixed: the names in `HVACLibraryAPI.PUBLIC` /
  `HVACLossAPI.PUBLIC`, and the context keys in
  `freecad/HVAC/library/contexts.py` (both checked by tests).
- `generators_package`: the Python package `import_generator(library_id, module)`
  imports `<generators_package>.<module>` from, for the `"generator"` geometry backend.
- `default_construction`: optional construction layers inherited by every
  type that does not declare its own `construction.layers`. This keeps the
  material construction uniform for simple parts within one library.
- `type_roots`: directories (relative to the library root) scanned for `*.json` type-defs.

### Shared fitting modules (`"shared:"` prefix)

Wherever a type-def names a Python module (`generator`, `connection_lengths`,
`loss`, a loss variant, a construction feature), a plain name such as
`"junctions"` means `<generators_package>.junctions` inside the library
itself. A name with the `shared:` prefix means one of the addon's own shared
fitting modules under `freecad/HVAC/library/fittings/` instead:

```json
"loss": {"module": "shared:losses", "function": "loss_elbow_generic"}
```

Use the shared modules for standard fittings, so a library is only data
(type-defs) plus whatever code is genuinely its own. A third-party library
can use them the same way; nothing has to be copied into its `generators/`.
Only a plain module name may follow the prefix.

The shared geometry modules are `segments`, `elbows`, `transitions`, `taps`,
`offsets`, `tees`, `wyes`, `crosses`, `stars`, `terminals`, `inline`,
`through`, `markers` and `equipment` (equipment models, see
`library/equipment_library.py`). Every
fitting in them is built as an *envelope*: its air space grown outward by a
wall offset. What comes out therefore depends only on what the type-def
declares:

- **Wall layers.** Each construction layer that names a `thickness_property`
  becomes its own hollow shell, innermost first (a casing, then insulation
  around it, ...). If no layer has a thickness above zero, the fitting is
  returned as one solid body of the air space.
- **Flanges.** If the type declares `FlangeThickness` and `FlangeHeight`
  (both above zero), a flange collar is fused onto the structural layer at
  every end of the fitting. One port's flange can be switched off with a
  boolean property: `ShowFlange<Role>` (the role is that port's trim name
  without `Trim`, e.g. `ShowFlangeBranch`), `ShowFlange<N>` (1-based port
  number, e.g. `ShowFlange1` on a two-port fitting), or `ShowFlange`,
  either per-port (its own switch for every port) or one for all ports.

Code that needs a standard fitting directly (a PartScript, a library's own
generator) gets the same builders through the API instead of a type-def:
`api.build_fitting("elbow", context)` / `api.measure_fitting("elbow", context)`
(names in `HVACLibraryAPI.STANDARD_FITTINGS`), and
`api.build_layered_fitting(context, envelope_builder, connection_lengths)`
to give a custom shape the same layer and flange treatment.

## Type-def JSON (`HVACTypeDef`, see `freecad/HVAC/library/Library.py`)

Common fields, both segments and junctions:

| field | meaning |
|---|---|
| `id` | stable identifier within the library; see naming convention below |
| `label` | display name |
| `category` | `"segment"` or `"junction"` |
| `family` | list of dotted family strings the parser's classifier matches against (segments: e.g. `["straight_segment"]`; junctions: e.g. `["through.bend", "through.bend_90"]` -- see `classify_junction_family`, documented in [`freecad/HVAC/core/TOPOLOGY_CLASSIFICATION.md`](../core/TOPOLOGY_CLASSIFICATION.md)) |
| `profiles` | allowed cross-section profiles, e.g. `["Circular"]`, `["Rectangular"]` |
| `constraints` | e.g. `{"degree": 1}` restricting how many ports a junction may have; junctions can additionally constrain `flow_class`, `qualifiers.<key>`, `profile_relation`, `inlet_profile`, `outlet_profile`, and any `derived_values` entry (e.g. `area_ratio`) -- see below |
| `properties` | list of property defs (below) |
| `construction` | optional `{"layers": [...], "features": [...]}` object (below); when omitted, inherits the library manifest's `default_construction`, or falls back to one roleless implicit layer if the manifest has no default |
| `geometry` | required: `{"backend": "generator", "module": "...", "function": "..."}`, `{"backend": "partscript", "file": "..."}` or `{"backend": "static", "descriptor": "..."}`. The old top-level `"generator"` key is refused |
| `connection_lengths` | optional: `{"module": "...", "function": "..."}` -- a lightweight, independent per-port trim *measurement* function (parsed onto `HVACTypeDef.lengths_module`/`lengths_function`; see below) |
| `loss_module` / `loss_function` | optional: fitting-loss coefficient function for the airflow solver; its context provides `HVACLossAPI` as `context["loss_api"]`. May instead (or also) declare `loss.variants` for flow-dependent formulas -- see below |
| `friction` | optional, segments only: `{"module": "...", "function": "..."}` -- a straight-duct friction model factory (see below) |

### `friction`: straight-duct friction models

A segment type can replace or correct the network's friction model
(`DuctNetwork.FrictionModel`: `DarcyAltshulTsal`, the default,
`DarcyColebrook`, `Table` from the CSV in `FrictionTableFile`, or
`Expression` from `FrictionExpression`; see `freecad/HVAC/analysis/friction.py`).
The factory is called once per segment per solve with a context holding
`properties`, `obj`, `roughness_mm`, `base_model` (the network's model; None
means the default) and `friction` (the `analysis.friction` module), and
returns any object with
`rate_pa_per_m(flow_m3_s, area_m2, dh_m, roughness_m, density_kg_m3, kinematic_viscosity_m2_s)`.
A factory that only corrects the network's model should wrap `base_model`
(e.g. `friction.ScaledFriction(base_model, factor)`), so a project-wide
table still applies underneath.

Shipped: `shared:friction` / `friction_flex_compressed`, used by
`builtin_basic/circular_flex` (manual only): the network's model times the
SMACNA Fig. 14-4 correction for `CompressionPercent`.

### `connection_lengths`: independent trim measurement

```json
"geometry": {"backend": "generator", "module": "shared:elbows", "function": "build_elbow"},
"connection_lengths": {"module": "shared:elbows", "function": "measure_elbow"}
```

`geometry` (any backend) builds the
type's final fitting `Shape`. `connection_lengths` is a separate, optional
function that computes just the same fitting's per-port trim lengths (the
standard `[{"edge_key", "segment_end", "length"}, ...]` records also
returned as `GeometryResult.connection_lengths` -- see
`HVACLibraryAPI.build_trim_rec_from_port_lengths`/
`build_trim_rec_from_context_uniform`) *without* constructing any geometry
at all -- called via `HVACLibraryRegistry.measure_connection_lengths()`,
using the exact same context preparation/parameter resolution as
`build_geometry()`.

This exists so `DuctJunction.composeComponents()` can learn a component's
own trims (needed to work out where a chained Inline component's anchor
sits) without paying for a full Shape build that gets thrown away
immediately afterward. A type with no `connection_lengths` function
declared still works -- `_peekConnectionLengths()` falls back to building
(and discarding) the full geometry, exactly as every type used to.

Both functions must derive a port's trim from the *same* underlying
calculation (e.g. a shared private layout helper, or a lower-level
`HVACLibraryAPI` helper like `make_elbow_path`/`make_radiussed_path` that
both simply call) -- never two independently-maintained copies of the same
formula. A `connection_lengths` function must never build or return a
`Shape`/`GeometryResult`; it returns the plain trim-record list directly.

### Flow-classification constraints

Beyond `degree`/`degree_min`/`degree_max`, a junction type-def's
`constraints` can filter on `DuctNetworkParser`'s flow-classification
output (`flow_class`/`qualifiers`/`derived_values` -- see
[`freecad/HVAC/core/TOPOLOGY_CLASSIFICATION.md`](../core/TOPOLOGY_CLASSIFICATION.md)),
reusing the same `enum`/`minimum`/`maximum`/exclusive-bound operators as
`properties[].validation`:

```json
"constraints": {
  "flow_class": {"enum": ["expansion"]},
  "qualifiers": {
    "alignment": {"enum": ["eccentric"]},
    "transition_form": {"enum": ["single_plane"]}
  },
  "area_ratio": {
    "minimum": 1.0,
    "maximum": 4.0
  }
}
```

`profile_relation`/`inlet_profile`/`outlet_profile` can be constrained the
same way, either directly (as shown for `flow_class`) or nested under
`qualifiers` -- both read from the same classifier-produced qualifier. Note
these are classification *qualifiers*, not actual profile names -- a value
like `profile_relation: "mixed"` describes the shape of the transition
(e.g. differing inlet/outlet profiles), it's never itself a `profiles`
entry or an index key. These constraints never expand `HVACMatchKey`: a
type-def is still indexed purely by (category, topology, family) for the
automatic-selection lookup, and this extra data (like actual per-port
profile compatibility) only filters candidates *after* that lookup, exactly
like the existing `degree`/topology checks.

The manual Change Type list applies the same constraints: it passes the
node's own `flow_class`/`qualifiers`/`derived_values` to `list_types()`, so
it only offers types that fit how air passes that node. Use this to keep a
type out of the list where it does not belong:

- a transition for one way the two ducts line up:
  `"qualifiers": {"alignment": {"enum": ["eccentric", "double_eccentric"]}}`;
- an end fitting for one direction of flow:
  `"flow_class": {"enum": ["entry", "unknown"]}` (or `"exit"`);
- a branch, cross or multiport fitting for one direction of flow:
  `"flow_class": {"enum": ["diverging", "unknown"]}` (or `"converging"`).

List `"unknown"` as well unless the type should disappear whenever the flow
direction is not known: the classifier reports `"unknown"` as a value of
its own, so a constraint that leaves it out does not match it.

Every `qualifiers.<key>` and every other top-level key (an implied
`derived_values` entry) is checked against a fixed, known vocabulary at
load time -- see `validation.KNOWN_QUALIFIER_KEYS`/
`KNOWN_DERIVED_VALUE_KEYS` -- so a typo'd key (`"aera_ratio"`) raises a
clear error instead of silently becoming a permanent no-op constraint.

### Flow-dependent loss variants

One physical fitting (one TypeId, one geometry generator) can carry
several *flow-dependent* loss formulas -- e.g. an expanding vs.
contracting transition, or an ordinary vs. bullhead tee -- without a
separate TypeId per flow case: `loss.variants` is a list of `{constraints,
module, function}` entries, each `constraints` evaluated with the exact
same operators/keys as the type-def-level `constraints` above (see
`validation.flow_classification_violations()`, shared by both). The
plain `loss.module`/`loss.function` stay as the default/wildcard, used
whenever no variant's constraints are satisfied:

```json
"loss": {
  "module": "shared:losses",
  "function": "loss_tee_generic",
  "variants": [
    {
      "constraints": {
        "flow_class": {"enum": ["diverging"]},
        "qualifiers": {"common_leg": {"enum": ["run"]}}
      },
      "module": "shared:losses",
      "function": "loss_branch_diverging_run"
    },
    {
      "constraints": {
        "flow_class": {"enum": ["diverging"]},
        "qualifiers": {"common_leg": {"enum": ["branch"]}}
      },
      "module": "shared:losses",
      "function": "loss_branch_diverging_branch"
    }
  ]
}
```

A type-def with no `"variants"` key behaves exactly as before (the plain
`module`/`function` form). `HVACLibraryRegistry.call_loss()` resolves
which callable to actually invoke via `validation.resolve_loss_variant()`:

- exactly one variant's `constraints` fully satisfied -> that variant;
- more than one matches -> the most specific one wins (most declared
  constraint keys, counting each `qualifiers` entry separately) -- e.g. a
  library-specific variant further narrowed by a `qualifiers` entry (a
  SMACNA-only rectangular-pyramidal-expansion formula) wins over a
  broader one that only checks `flow_class`; a genuine tie at the top
  specificity is a JSON-authoring ambiguity and raises `ValueError`
  rather than silently picking one;
- none match -> the plain `module`/`function`, if declared, as an
  explicit fallback; otherwise `call_loss()` returns `None` -- "no
  applicable loss model," the same clean signal a type with no loss
  function wired up at all already gives its caller (`AirflowSolver`
  then applies its own generic `K_DEFAULT`).

Unlike the type-def-level `constraints` above (permissive about missing
classification data, so an out-of-date caller can't accidentally break an
otherwise-valid match), a loss variant's own `constraints` are evaluated
*strictly*: a key genuinely absent from the current context (as opposed
to present with a non-matching value like `""`/`"unknown"`) counts as a
mismatch, never an accidental match -- picking between several
mutually-exclusive loss formulas must never happen on missing data.

`loss.variants[].constraints` and a type-def's own top-level
`constraints` are deliberately independent: the type-level one decides
whether the physical fitting TypeId is selectable at all (before sync
ever writes it onto an object); a loss variant's own constraints only
run afterward, per airflow-solve call, to pick a loss formula for a
TypeId that's already been chosen -- see
[`freecad/HVAC/core/TOPOLOGY_CLASSIFICATION.md`](../core/TOPOLOGY_CLASSIFICATION.md)
for where `flow_class`/`qualifiers`/`derived_values` themselves come
from (`NetworkParser.classify_flow`).

Junctions additionally carry a `topology` field (see below), plus two
optional fields a terminal (`topology: "end"`) type may use to prescribe
its own flow condition -- see `core/Junction.py`'s `FlowBoundary` property
and `analysis/flow.py`:

| field | meaning |
|---|---|
| `flow_boundary` | `"Auto"` \| `"Fixed"` \| `"Closed"` (omit to leave the user's own choice, default `"Auto"`, untouched). Applied once, the moment a component adopts this type. |
| `flow_boundary_locked` | `true` to re-assert `flow_boundary` on every sync instead of just once, so the user can never change it (e.g. a duct-closure/end-cap type that must always stay `"Closed"`) |

```json
"flow_boundary": "Closed",
"flow_boundary_locked": true
```

The solver and popup never branch on a type's id/family to detect this --
they only ever read the plain `FlowBoundary`/`FlowBoundaryLocked`
properties these two fields drive.

The loss context also contains the component's own role-based
`context["construction"]` and its resolved effective
`context["hydraulic_roughness_mm"]`. The latter uses the network default
only if the construction's flow-surface material has no roughness value.
Library loss code may call the construction's other physical queries (for
example `acoustic_impedance()` or `overall_u_value()`) without importing
core modules.

Property def (`HVACPropertyDef`):

```json
{
  "name": "Width",
  "prop_type": "App::PropertyLength",
  "group": "Dimensions",
  "description": "Rectangular duct width",
  "default": 100.0,
  "validation": {"exclusiveMinimum": 0.0}
}
```

`prop_type` is any FreeCAD property type string (`App::PropertyLength`,
`App::PropertyBool`, ...). An `App::PropertyEnumeration` (a drop-down) takes
its choices from `validation.enum`, which is then required. `group` is the FreeCAD property-editor group; the
established groups are `"Dimensions"` (sizes/thicknesses), `"Options"`
(booleans/toggles like `ShowFlange1`) and `"Parameters"` (values used for
calculation rather than geometry, like `LossCoefficient` or `NeckSize`).

A property entry may only use the keys `name`, `prop_type`, `group`,
`description`, `default`, `editor_mode`, `required`, `validation` and
`per_port`, and
`validation` may only use the rules `enum`, `minimum`, `maximum`,
`exclusiveMinimum`, `exclusiveMaximum`, `multipleOf`, `minLength` and
`maxLength`. Any other key is a load error, so a typo (or a made-up key like
a top-level `"min"`) can't become a limit that is never enforced.

**Per-port properties.** A property marked `"per_port": true` holds one
value for every connected port instead of one for the whole fitting, so the
same type-def works for any number of ports (a manifold, a plenum):

```json
{
  "name": "TrimLength",
  "prop_type": "App::PropertyLength",
  "group": "Dimensions",
  "description": "Trim length of each port",
  "default": 100.0,
  "per_port": true
}
```

`prop_type` is the type of *one* value; `default` is what a newly connected
port gets. Supported: `App::PropertyLength`, `App::PropertyDistance`,
`App::PropertyFloat`, `App::PropertyAngle`, `App::PropertyBool`,
`App::PropertyInteger`. On the FreeCAD object it appears as a list in port
order, with a hidden companion list (`<Name>EdgeKeys`) recording which port
each value belongs to; values follow their port when ports are added,
removed or reordered, and across a document reload. A generator reads it
with `api.port_param(context, "TrimLength", port)`, which also works for an
ordinary single-value property of that name.

**Port roles.** `api.port_roles(context)` returns the connected ports by
role: `neck` (1 port), `inlet`/`outlet` (2), `run_a`/`run_b`/`branch` (tee),
`main`/`branch_a`/`branch_b` (wye), `run_a`/`run_b`/`branch_a`/`branch_b`
(cross), `port_1`..`port_n` (anything else).

**Trim property names.** A fitting whose ports have fixed roles names one
trim property per role, `Trim<Role>`: `TrimRunA` / `TrimRunB` / `TrimBranch`
(tee, tap, lateral tee), `TrimMain` / `TrimBranchA` / `TrimBranchB` (wye).
A fitting whose ports have no such role (generic branch, cross, multiport)
uses one per-port `TrimLength`. The same goes for flange switches:
`ShowFlange<Role>` for a role, one per-port `ShowFlange` otherwise.

See `samples/README.md` for the three geometry backends (`partscript`,
`static`, and the `generator` function -- including its use as a
FCStd-template loader via `HVACLibraryAPI.shape_from_fcstd`), how to choose
between them, and the `{"layers": {...}}` result contract (the one form;
`HVACLibraryAPI.single_layer` builds it for a one-solid fitting)
every backend's return value is normalized into (see
`freecad/HVAC/library/geometry_result.py` and ARCHITECTURE.md's "Component
geometry & materials").

### Construction layers

A type's own `"construction"` block is an object with its own `"layers"`
array (this section) and an optional `"features"` array (see "Construction
features" below). `"layers"` declares how many physical layers the type's
wall is built from, in build order (e.g. a bare duct wall, or a wall plus
insulation, or a casing plus an acoustic fill plus a perforated liner) and
what each one *means* -- its FreeCAD-standardized semantic role(s), from
`freecad/HVAC/library/construction.py`'s fixed `LayerRole` vocabulary
(`flow_surface`, `structural_shell`, `thermal_insulation`,
`acoustic_absorber`, `acoustic_liner`, `vapor_barrier`, `outer_jacket`,
`fire_protection`). A layer may declare more than one role (e.g. a
single-wall duct's only layer is both `flow_surface` and
`structural_shell`).

```json
"construction": {
  "layers": [
    {
      "id": "casing",
      "roles": ["flow_surface", "structural_shell"],
      "thickness_property": "Thickness"
    },
    {
      "id": "insulation",
      "roles": ["thermal_insulation"],
      "default_material_role": "thermal_insulation",
      "thickness_property": "InsulationThickness"
    }
  ]
}
```

- `id`: library-chosen, stable within this type-def (e.g. `"casing"`,
  `"liner"`, `"absorber"`) -- pairs a layer's def with the geometry backend's
  own `{"layers": {"<id>": {"shape": ...}}}` return value (see
  `freecad/HVAC/library/geometry_result.py`) and with that layer's own
  `Layer_<id>_Shape`/`Layer_<id>_Material` FreeCAD properties (see
  `core/_construction_schema.py`). Application/core code must never branch
  on this id -- only on `roles`.
- `roles`: the standardized `LayerRole` values this layer plays.
- `default_material_role` (optional): which network-level
  `DefaultMaterial_<Role>` property (see `core/Network.py`) this layer
  falls back to when it has no material of its own yet.
- `default_material_uuid` (optional): an explicit default material,
  overriding `default_material_role`.
- `thickness_property` (optional): the name of one of this type-def's own
  declared `properties` that holds this layer's thickness -- purely
  informational metadata for detailing/mass-calculation consumers; core
  never interprets it (a layer's generated Shape is the source of truth for
  its own volume).

A type-def with no `"construction"` block at all (not yet migrated) behaves
as a single, roleless implicit layer. Geometry backends build each declared
layer from `HVACLibraryAPI` profiles, offsets, sweeps, lofts, and boolean
operations; see `freecad/HVAC/library/library_api.py`.

Downstream code (materials, appearance, and airflow/acoustic/thermal/
detailing) queries construction only by role, via
`core/Construction.py`'s `Construction.layers_with_role(role)` /
`flow_surface()` / `structural_layers()` / `thermal_layers()` /
`acoustic_layers()` -- reachable off a segment/component's own
`getConstruction()`. It must never assume a particular layer id exists.

### Construction features

A construction layer spans the whole wall; a **construction feature** is a
smaller, localized attachment on top of one -- a flange, a stiffener, a
seam, a proprietary fabrication detail. Features are declared in the same
type-def's `"construction"` block, as a sibling `"features"` array:

```json
"construction": {
  "layers": [
    {"id": "casing", "roles": ["flow_surface", "structural_shell"], "thickness_property": "Thickness"}
  ],
  "features": [
    {
      "id": "transverse_flange",
      "role": "transverse_joint",
      "host_layer": "casing",
      "module": "shared:features",
      "generator": "transverse_flange",
      "enabled_parameter": "FlangeEnabled",
      "visible_parameter": "FlangeVisible",
      "parameters": ["Diameter", "FlangeHeight", "FlangeThickness"]
    }
  ]
}
```

- `id`: library-chosen, stable within this type-def -- pairs a feature's def
  with its own `Feature_<id>_Shape` FreeCAD property (see
  `core/_construction_schema.py`) and with the geometry backend's own
  return value key inside `GeometryResult.features` (see
  `freecad/HVAC/library/geometry_result.py`).
- `role`: a free-form, library-chosen string (e.g. `"transverse_joint"`) --
  unlike a layer's `roles`, there is no standardized/enumerated vocabulary
  for feature roles; downstream code queries features only by whatever
  string a library chose, via `Construction.features_with_role(role)`.
- `host_layer`: the `id` of one of this same `"construction"` block's own
  declared layers -- `HVACLibraryRegistry.build_geometry()` resolves this
  to that layer's own already-built `LayerGeometry` (shape + roles) before
  invoking the feature's generator, and it's also what a non-visible
  feature's rendered appearance falls back to (see below).
- `module` (optional): the name of the `<generators_package>` submodule
  this feature's own generator function lives in, resolved the same way
  `generator`/`loss` modules already are (`import_generator()`). Defaults
  to the library's own `"features"` submodule when omitted.
  `"shared:features"` names the shared module
  (`freecad/HVAC/library/fittings/features.py`), which provides
  `transverse_flange`: a flange collar at every enabled end of a fitting
  or segment, on the outer face of `host_layer`, from `FlangeThickness`,
  `FlangeHeight` and `ShowFlange<Role>` / `ShowFlange<N>` / `ShowFlange`.
  Flanges are always this feature, never fused into a layer: a type that
  declares `FlangeThickness` and construction layers must declare it
  (`tests/test_shipped_type_references.py`).
- `generator`: the name of a function inside that module (see `module`
  above), with the signature
  `generate_<name>(api, ctx) -> Part.Shape | None`. `api` is
  `HVACLibraryAPI`; `ctx` (a `FeatureContext`) provides `ctx.parameters`
  (this feature's own declared `parameters`, already-resolved values --
  never the type's full property set), `ctx.host_layer` (the host layer's
  own `LayerGeometry` for this build), `ctx.host_layer_id` (its id),
  `ctx.result` (the geometry backend's own `GeometryResult` for this
  build: its layers and `connection_lengths`, which locate a fitting's
  real end faces), and `ctx.context` (the full
  underlying geometry-build context dict -- ports, start/end points,
  profile, profile_x_axis, path info, ... -- an escape hatch for anything
  else the generator needs). If a feature's geometry is naturally several
  repeated pieces (e.g. several stiffeners), return them fused into one
  compound `Part.Shape` -- a feature is always exactly one shape (or
  `None`, if nothing should be built this call).
- `enabled_parameter` (optional): the name of one of this type-def's own
  declared `properties` whose current value gates whether this feature is
  generated *at all* this build. When it resolves false, the feature's
  generator is never called and it has no entry in `GeometryResult.features`
  -- not an entry with a null shape. Changing this property (an ordinary
  declared property, ordinary recompute behavior) triggers a normal
  geometry rebuild, same as changing any of `parameters`.
- `visible_parameter` (optional): the name of one of this type-def's own
  declared `properties` that controls only the feature's *rendered*
  visibility, independent of whether it was generated. A non-visible
  feature is still built and still part of the object's own `Shape`
  compound (so it stays individually accessible/queryable via
  `Feature_<id>_Shape`/`Construction.feature(id)`) -- only its own faces'
  `ViewObject.ShapeAppearance` are forced fully transparent instead of
  inheriting the host layer's material appearance (see
  `core/_component_appearance.py`). Core marks whatever property this
  names `Prop_NoRecompute` once it's added (see
  `core/_construction_schema.py`), so toggling visibility re-renders
  appearance without ever rebuilding geometry.
- `parameters`: names of existing declared type-def `properties` this
  feature's own generator function needs -- core resolves just these
  (already-resolved) values into `ctx.parameters`.

`enabled_parameter`/`visible_parameter`/`parameters` only ever *reference*
property names -- the properties themselves are declared exactly where
every other type-def property already is, in the same `"properties"` list
described above. There is no separate parameter-definition mechanism for
features (or for layers' `thickness_property`, which follows the same
by-reference convention).

**Shared feature generators.** Besides `shared:features` /
`transverse_flange`:

- `shared:dampers`: `damper_blades` (the blade(s) and shafts at the current
  `DamperType` / `BladeAngle` / `BladeCount` / `GateOpening`) and
  `damper_operator` (`Operator`: `Hand quadrant`, `Actuator` or `None`;
  `OperatorSide`: `Right` / `Left` / `Top` / `Bottom`, the side the shaft
  comes out of; `OperatorRotation`: `0` / `90` / `180` / `270` about the
  shaft).
- `shared:faces`: the face of an air terminal over its open end:
  `square_diffuser_face`, `round_diffuser_face`, `generic_diffuser_face`
  (`FacePattern` `Louvered`, `Plaque`, `Perforated`, `Swirl`),
  `slot_diffuser_face` (`Slots with deflectors`, `Plain slots`),
  `grille_face` and `register_face` (`Single deflection`,
  `Double deflection`, `Egg crate`, `Perforated`; a register adds opposed
  damper blades behind). Every size of a pattern is an optional property
  (`FaceBorder`, `FaceThickness`, `RingCount`, `RingStep`, `PlaqueSize`,
  `PlaqueGap`, `HoleDiameter`, `HolePitch`, `SlotCount`, `SlotWidth`,
  `DividerWidth`, `BladeOrientation`, `BladeSpacing`, `BladeDepth`,
  `BladeThickness`, `BladeAngle`, `DamperBladeAngle`): a type that does not
  declare one gets a size worked out from the face. `builtin_basic` declares
  `FacePattern` (and `BladeOrientation`) only; `smacna` declares them all.

## Loss coverage

Which loss function every junction type of `builtin_basic` and `smacna`
uses, and the variants it switches to by flow (see "Flow-dependent loss
variants" above). The `HVACLossAPI` method behind each function says which
SMACNA table it reads and when it reports `APPROXIMATION`. A type with
**MISSING** has no loss wired: `tests/test_loss_coverage.py` fails on it,
and also when this table is out of date (regenerate it with
`python3 tools/loss_coverage.py --write`).

<!-- LOSS-COVERAGE:BEGIN (generated by tools/loss_coverage.py, do not edit by hand) -->

| Library | Type | Profiles | Selection | Loss (default; flow-dependent variants) |
|---|---|---|---|---|
| builtin_basic | `branch_generic` | Circular, Rectangular, Oval, Generic | model | `loss_wye_generic`; diverging, common_leg run: `loss_branch_diverging_run`; converging, common_leg run: `loss_branch_converging_run`; diverging, common_leg branch: `loss_branch_diverging_branch`; converging, common_leg branch: `loss_branch_converging_branch` |
| builtin_basic | `branch_lateral_tee_generic` | Circular, Rectangular, Oval | model | `loss_tee_generic`; diverging, common_leg run: `loss_branch_diverging_run`; converging, common_leg run: `loss_branch_converging_run`; diverging, common_leg branch: `loss_branch_diverging_branch`; converging, common_leg branch: `loss_branch_converging_branch` |
| builtin_basic | `branch_lateral_tee_mitered` | Circular, Rectangular, Oval | model | `loss_tee_generic`; diverging, common_leg run: `loss_branch_diverging_run`; converging, common_leg run: `loss_branch_converging_run`; diverging, common_leg branch: `loss_branch_diverging_branch`; converging, common_leg branch: `loss_branch_converging_branch` |
| builtin_basic | `branch_lateral_tee_radius` | Circular, Rectangular, Oval | model | `loss_tee_generic`; diverging, common_leg run: `loss_branch_diverging_run`; converging, common_leg run: `loss_branch_converging_run`; diverging, common_leg branch: `loss_branch_diverging_branch`; converging, common_leg branch: `loss_branch_converging_branch` |
| builtin_basic | `branch_marker` | Generic | placeholder | none (marker) |
| builtin_basic | `branch_plenum_generic` | Circular, Rectangular, Oval | model | `loss_plenum` |
| builtin_basic | `branch_tap_mitered_shoe` | Circular, Rectangular, Oval | model | `loss_tee_generic`; diverging, common_leg branch: `loss_branch_diverging_branch`; converging, common_leg branch: `loss_branch_converging_branch` |
| builtin_basic | `branch_tap_saddle` | Circular, Rectangular, Oval | model | `loss_tee_conical`; diverging, common_leg branch: `loss_branch_diverging_branch`; converging, common_leg branch: `loss_branch_converging_branch` |
| builtin_basic | `branch_tap_shoe` | Circular, Rectangular, Oval | model | `loss_tee_45_entry`; diverging, common_leg branch: `loss_branch_diverging_branch`; converging, common_leg branch: `loss_branch_converging_branch` |
| builtin_basic | `branch_tap_straight` | Circular, Rectangular, Oval | model | `loss_tee_generic`; diverging, common_leg branch: `loss_branch_diverging_branch`; converging, common_leg branch: `loss_branch_converging_branch` |
| builtin_basic | `branch_tee_radius_center` | Circular, Rectangular, Oval | model | `loss_tee_generic`; diverging, common_leg branch: `loss_branch_diverging_branch`; converging, common_leg branch: `loss_branch_converging_branch` |
| builtin_basic | `branch_tee_radius_edge` | Rectangular | model | `loss_tee_generic`; diverging, common_leg branch: `loss_branch_diverging_branch`; converging, common_leg branch: `loss_branch_converging_branch` |
| builtin_basic | `branch_tee_straight` | Circular, Rectangular, Oval | model | `loss_tee_generic`; diverging, common_leg branch: `loss_branch_diverging_branch`; converging, common_leg branch: `loss_branch_converging_branch` |
| builtin_basic | `branch_wye_mitered` | Circular, Rectangular, Oval | model | `loss_wye_generic`; diverging, common_leg branch: `loss_branch_diverging_branch`; converging, common_leg branch: `loss_branch_converging_branch` |
| builtin_basic | `branch_wye_radius` | Circular, Rectangular, Oval | model | `loss_wye_generic`; diverging, common_leg branch: `loss_branch_diverging_branch`; converging, common_leg branch: `loss_branch_converging_branch` |
| builtin_basic | `cross_double_wye_mitered` | Circular, Rectangular, Oval | model | `loss_cross_generic` |
| builtin_basic | `cross_double_wye_radius` | Circular, Rectangular, Oval | model | `loss_cross_generic` |
| builtin_basic | `cross_generic` | Circular, Rectangular, Oval, Generic | model | `loss_cross_generic` |
| builtin_basic | `cross_marker` | Generic | placeholder | none (marker) |
| builtin_basic | `cross_plenum_generic` | Circular, Rectangular, Oval | model | `loss_plenum` |
| builtin_basic | `cross_tee_straight` | Circular, Rectangular, Oval | model | `loss_cross_generic` |
| builtin_basic | `end_diffuser_generic` | Circular, Rectangular, Oval | model | `loss_diffuser_generic` |
| builtin_basic | `end_diffuser_round` | Circular, Rectangular, Oval | model | `loss_diffuser_generic` |
| builtin_basic | `end_diffuser_slot` | Circular, Rectangular, Oval | model | `loss_diffuser_generic` |
| builtin_basic | `end_diffuser_square` | Circular, Rectangular, Oval | model | `loss_diffuser_generic` |
| builtin_basic | `end_duct_closure_generic` | Circular, Rectangular, Oval | model | none (no flow: always closed) |
| builtin_basic | `end_entry_bellmouth` | Circular, Rectangular, Oval | model | `loss_entry_bellmouth` |
| builtin_basic | `end_entry_conical` | Circular, Rectangular, Oval | model | `loss_entry_conical` |
| builtin_basic | `end_entry_plain` | Circular, Rectangular, Oval | model | `loss_entry_plain` |
| builtin_basic | `end_equipment_connection` | Circular, Rectangular, Oval | model | `loss_equipment_connection` |
| builtin_basic | `end_exit_conical` | Circular | model | `loss_exit_conical` |
| builtin_basic | `end_exit_plain` | Circular, Rectangular, Oval | model | `loss_exit_plain` |
| builtin_basic | `end_exit_pyramidal` | Rectangular | model | `loss_exit_pyramidal` |
| builtin_basic | `end_fan_source_generic` | Circular, Rectangular, Oval | model | `loss_diffuser_generic` |
| builtin_basic | `end_grille_generic` | Circular, Rectangular, Oval | model | `loss_diffuser_generic` |
| builtin_basic | `end_hood_exhaust` | Circular, Rectangular, Oval | model | `loss_hood_exhaust` |
| builtin_basic | `end_hood_intake` | Circular, Rectangular, Oval | model | `loss_hood_intake` |
| builtin_basic | `end_hood_tapered` | Circular, Rectangular, Oval | model | `loss_hood_tapered` |
| builtin_basic | `end_intake_exhaust_generic` | Circular, Rectangular, Oval | model | `loss_diffuser_generic` |
| builtin_basic | `end_register_generic` | Circular, Rectangular, Oval | model | `loss_register_generic` |
| builtin_basic | `end_terminal_marker` | Generic | placeholder | none (marker) |
| builtin_basic | `multiport_generic` | Circular, Rectangular, Oval, Generic | model | `loss_multiport_generic` |
| builtin_basic | `multiport_marker` | Generic | placeholder | none (marker) |
| builtin_basic | `multiport_plenum_generic` | Circular, Rectangular, Oval | model | `loss_plenum` |
| builtin_basic | `through_damper_generic` | Circular, Rectangular, Oval | inline | `loss_damper_generic` |
| builtin_basic | `through_elbow_mitered` | Circular, Rectangular, Oval | model | `loss_elbow_mitered` |
| builtin_basic | `through_elbow_radius` | Circular, Rectangular, Oval | model | `loss_elbow_generic` |
| builtin_basic | `through_generic` | Generic | model | `loss_through_generic` |
| builtin_basic | `through_marker` | Generic | placeholder | none (marker) |
| builtin_basic | `through_obstruction_generic` | Circular, Rectangular, Oval | inline | `loss_obstruction` |
| builtin_basic | `through_offset_angled` | Circular, Rectangular, Oval | model | `loss_offset_generic` |
| builtin_basic | `through_offset_mitered` | Circular, Rectangular, Oval | model | `loss_offset_generic` |
| builtin_basic | `through_offset_radiussed` | Circular, Rectangular, Oval | model | `loss_offset_generic` |
| builtin_basic | `through_plenum_generic` | Circular, Rectangular, Oval | model | `loss_plenum` |
| builtin_basic | `through_straight_generic` | Circular, Rectangular, Oval | model | `loss_transition_generic` |
| builtin_basic | `through_transition_concentric` | Circular, Rectangular, Oval | model | `loss_transition_generic`; expansion: `loss_transition_expansion`; contraction: `loss_transition_contraction` |
| builtin_basic | `through_transition_eccentric` | Circular, Rectangular, Oval | model | `loss_transition_generic`; expansion: `loss_transition_expansion`; contraction: `loss_transition_contraction` |
| builtin_basic | `through_transition_offset` | Circular, Rectangular, Oval | model | `loss_transition_generic`; expansion: `loss_transition_expansion`; contraction: `loss_transition_contraction` |
| builtin_basic | `through_vav_generic` | Circular, Rectangular, Oval | inline | `loss_vav_generic` |
| smacna | `branch_lateral_tee_generic` | Circular, Rectangular, Oval | model | `loss_tee_generic`; diverging, common_leg run: `loss_branch_diverging_run`; converging, common_leg run: `loss_branch_converging_run`; diverging, common_leg branch: `loss_branch_diverging_branch`; converging, common_leg branch: `loss_branch_converging_branch` |
| smacna | `branch_lateral_tee_mitered` | Circular, Rectangular, Oval | model | `loss_tee_generic`; diverging, common_leg run: `loss_branch_diverging_run`; converging, common_leg run: `loss_branch_converging_run`; diverging, common_leg branch: `loss_branch_diverging_branch`; converging, common_leg branch: `loss_branch_converging_branch` |
| smacna | `branch_lateral_tee_radius` | Circular, Rectangular, Oval | model | `loss_tee_generic`; diverging, common_leg run: `loss_branch_diverging_run`; converging, common_leg run: `loss_branch_converging_run`; diverging, common_leg branch: `loss_branch_diverging_branch`; converging, common_leg branch: `loss_branch_converging_branch` |
| smacna | `branch_marker` | Generic | placeholder | none (marker) |
| smacna | `branch_plenum_generic` | Circular, Rectangular, Oval | model | `loss_plenum` |
| smacna | `branch_tap_extractor` | Rectangular | model | `loss_tee_extractor`; diverging, common_leg branch: `loss_branch_diverging_branch`; converging, common_leg branch: `loss_branch_converging_branch` |
| smacna | `branch_tap_mitered_shoe` | Circular, Rectangular, Oval | model | `loss_tee_generic`; diverging, common_leg branch: `loss_branch_diverging_branch`; converging, common_leg branch: `loss_branch_converging_branch` |
| smacna | `branch_tap_saddle` | Circular, Rectangular, Oval | model | `loss_tee_conical`; diverging, common_leg branch: `loss_branch_diverging_branch`; converging, common_leg branch: `loss_branch_converging_branch` |
| smacna | `branch_tap_shoe` | Circular, Rectangular, Oval | model | `loss_tee_45_entry`; diverging, common_leg branch: `loss_branch_diverging_branch`; converging, common_leg branch: `loss_branch_converging_branch` |
| smacna | `branch_tap_shoe_damper` | Rectangular | model | `loss_tee_45_entry_damper`; diverging, common_leg branch: `loss_branch_diverging_branch`; converging, common_leg branch: `loss_branch_converging_branch` |
| smacna | `branch_tap_straight` | Circular, Rectangular, Oval | model | `loss_tee_generic`; diverging, common_leg branch: `loss_branch_diverging_branch`; converging, common_leg branch: `loss_branch_converging_branch` |
| smacna | `branch_tap_straight_damper` | Rectangular | model | `loss_tee_damper`; diverging, common_leg branch: `loss_branch_diverging_branch`; converging, common_leg branch: `loss_branch_converging_branch` |
| smacna | `branch_tee_generic` | Circular, Rectangular, Oval | model | `loss_tee_generic`; diverging, common_leg run: `loss_branch_diverging_run`; converging, common_leg run: `loss_branch_converging_run`; diverging, common_leg branch: `loss_branch_diverging_branch`; converging, common_leg branch: `loss_branch_converging_branch` |
| smacna | `branch_tee_radius_center` | Circular, Rectangular, Oval | model | `loss_tee_generic`; diverging, common_leg branch: `loss_branch_diverging_branch`; converging, common_leg branch: `loss_branch_converging_branch` |
| smacna | `branch_tee_radius_edge` | Rectangular | model | `loss_tee_generic`; diverging, common_leg branch: `loss_branch_diverging_branch`; converging, common_leg branch: `loss_branch_converging_branch` |
| smacna | `branch_tee_straight` | Circular, Rectangular, Oval | model | `loss_tee_generic`; diverging, common_leg branch: `loss_branch_diverging_branch`; converging, common_leg branch: `loss_branch_converging_branch` |
| smacna | `branch_wye_generic` | Circular, Rectangular, Oval, Generic | model | `loss_wye_generic`; diverging, common_leg run: `loss_branch_diverging_run`; converging, common_leg run: `loss_branch_converging_run`; diverging, common_leg branch: `loss_branch_diverging_branch`; converging, common_leg branch: `loss_branch_converging_branch` |
| smacna | `branch_wye_mitered` | Circular, Rectangular, Oval | model | `loss_wye_generic`; diverging, common_leg branch: `loss_branch_diverging_branch`; converging, common_leg branch: `loss_branch_converging_branch` |
| smacna | `cross_double_wye_mitered` | Circular, Rectangular, Oval | model | `loss_cross_generic` |
| smacna | `cross_double_wye_radius` | Circular, Rectangular, Oval | model | `loss_cross_generic` |
| smacna | `cross_generic` | Circular, Rectangular, Oval, Generic | model | `loss_cross_generic` |
| smacna | `cross_marker` | Generic | placeholder | none (marker) |
| smacna | `cross_plenum_generic` | Circular, Rectangular, Oval | model | `loss_plenum` |
| smacna | `cross_tee_straight` | Circular, Rectangular, Oval | model | `loss_cross_generic` |
| smacna | `end_diffuser_generic` | Circular, Rectangular, Oval | model | `loss_diffuser_generic` |
| smacna | `end_diffuser_round` | Circular, Rectangular, Oval | model | `loss_diffuser_generic` |
| smacna | `end_diffuser_slot` | Circular, Rectangular, Oval | model | `loss_diffuser_generic` |
| smacna | `end_diffuser_square` | Circular, Rectangular, Oval | model | `loss_diffuser_generic` |
| smacna | `end_duct_closure_generic` | Circular, Rectangular, Oval | model | none (no flow: always closed) |
| smacna | `end_entry_bellmouth` | Circular, Rectangular, Oval | model | `loss_entry_bellmouth` |
| smacna | `end_entry_conical` | Circular, Rectangular, Oval | model | `loss_entry_conical` |
| smacna | `end_entry_plain` | Circular, Rectangular, Oval | model | `loss_entry_plain` |
| smacna | `end_equipment_connection` | Circular, Rectangular, Oval | model | `loss_equipment_connection` |
| smacna | `end_exit_conical` | Circular | model | `loss_exit_conical` |
| smacna | `end_exit_plain` | Circular, Rectangular, Oval | model | `loss_exit_plain` |
| smacna | `end_exit_pyramidal` | Rectangular | model | `loss_exit_pyramidal` |
| smacna | `end_fan_source_generic` | Circular, Rectangular, Oval | model | `loss_diffuser_generic` |
| smacna | `end_grille_generic` | Circular, Rectangular, Oval | model | `loss_diffuser_generic` |
| smacna | `end_hood_exhaust` | Circular, Rectangular, Oval | model | `loss_hood_exhaust` |
| smacna | `end_hood_intake` | Circular, Rectangular, Oval | model | `loss_hood_intake` |
| smacna | `end_hood_tapered` | Circular, Rectangular, Oval | model | `loss_hood_tapered` |
| smacna | `end_intake_exhaust_generic` | Circular, Rectangular, Oval | model | `loss_diffuser_generic` |
| smacna | `end_register_generic` | Circular, Rectangular, Oval | model | `loss_register_generic` |
| smacna | `end_terminal_marker` | Generic | placeholder | none (marker) |
| smacna | `multiport_generic` | Circular, Rectangular, Oval, Generic | model | `loss_multiport_generic` |
| smacna | `multiport_marker` | Generic | placeholder | none (marker) |
| smacna | `multiport_plenum_generic` | Circular, Rectangular, Oval | model | `loss_plenum` |
| smacna | `through_damper_generic` | Circular, Rectangular, Oval | inline | `loss_damper_generic` |
| smacna | `through_elbow_generic` | Circular, Rectangular, Oval | model | `loss_elbow_generic` |
| smacna | `through_elbow_mitered` | Circular, Rectangular, Oval | model | `loss_elbow_mitered` |
| smacna | `through_elbow_rectangular` | Rectangular | model | `loss_elbow_generic` |
| smacna | `through_elbow_vaned` | Rectangular | model | `loss_elbow_vaned` |
| smacna | `through_generic` | Generic | model | `loss_through_generic` |
| smacna | `through_marker` | Generic | placeholder | none (marker) |
| smacna | `through_obstruction_generic` | Circular, Rectangular, Oval | inline | `loss_obstruction` |
| smacna | `through_offset_angled` | Circular, Rectangular, Oval | model | `loss_offset_generic` |
| smacna | `through_offset_mitered` | Circular, Rectangular, Oval | model | `loss_offset_generic` |
| smacna | `through_offset_radiussed` | Circular, Rectangular, Oval | model | `loss_offset_generic` |
| smacna | `through_plenum_generic` | Circular, Rectangular, Oval | model | `loss_plenum` |
| smacna | `through_transition_concentric` | Circular, Rectangular, Oval | model | `loss_transition_generic`; expansion: `loss_transition_expansion`; contraction: `loss_transition_contraction` |
| smacna | `through_transition_eccentric` | Circular, Rectangular, Oval | model | `loss_transition_generic`; expansion: `loss_transition_expansion`; contraction: `loss_transition_contraction` |
| smacna | `through_transition_offset` | Circular, Rectangular, Oval | model | `loss_transition_generic`; expansion: `loss_transition_expansion`; contraction: `loss_transition_contraction` |
| smacna | `through_vav_generic` | Circular, Rectangular, Oval | inline | `loss_vav_generic` |

<!-- LOSS-COVERAGE:END -->

## Type selection (automatic matching)

`freecad/HVAC/core/NetworkParser.py` classifies *what* a network item is
(topology, family, connected-port profiles). It never picks a TypeId. That
job belongs to `HVACLibraryRegistry` (see `freecad/HVAC/library/Library.py`),
which matches a `HVACTypeMatchRequest` (category/topology/family, derived
by `DuctNetwork` sync from the parser's output) against every type-def a
library declares, and picks one. `DuctNetwork` sync then writes the
resulting `LibraryId`/`TypeId` onto the segment/junction object;
`execute()` only ever does an exact `resolve_type(library_id, type_id)`
lookup -- it never classifies or matches anything itself.

Profile is deliberately not part of the request's structural index key: a
junction can have several distinct connected-port profiles at once (e.g. a
Circular -> Rectangular transition, or a mixed-profile multiport), so a
single profile string can't correctly key a junction lookup. Every type
that structurally fits (same category/topology/family) is instead checked
for profile compatibility individually -- a junction against every
connected port's own profile (`context["connected_ports"]`), a segment
against its own single profile (`context["profile"]`) -- via
`validation.context_violations()`, the same check `matches_type()` already
used. A segment only ever has one profile, so this reduces to the same
exact-vs-Generic behavior as before for segments and homogeneous-profile
junctions.

A type-def opts into this by declaring what it can represent:

- `family`: the classifier's dotted family keys it supports (see
  `classify_junction_family` /
  [`TOPOLOGY_CLASSIFICATION.md`](../core/TOPOLOGY_CLASSIFICATION.md) for
  junctions; `"straight_segment"`/`"curved_segment"` for segments).
- `profiles`: the cross-section profiles it supports, or the `"Generic"`
  wildcard (see below).
- `selection`: matching metadata, new in this system:

  ```json
  "selection": {
    "kind": "model",
    "priority": 50
  }
  ```

  - `kind`: `"model"` (a real, geometry-producing type), `"placeholder"`
    (an invisible marker/fallback -- see `*_marker.json`), or `"inline"`
    (a user-added-only device -- damper, silencer, flex connector, ...;
    see "Inline components" below). Descriptors without a `selection`
    block default to `kind: "model"`, `priority: 0`, so existing type-defs
    keep loading unchanged.
  - `priority`: tiebreaker used only when more than one type is otherwise
    equally specific for the same request (see "Ranking" below). It plays
    no role once a type is already selected -- see "Sticky selection". Not
    used for `kind: "inline"` types, which are never ranked against one
    another automatically.

### `"Generic"` profile wildcard

`profiles: ["Generic"]` (or an empty `profiles` list, which existing
validation already treats the same way) makes a type profile-independent --
it matches any requested profile, but always ranks below a type that
matches the exact requested profile. This is the same wildcard semantics
`freecad/HVAC/library/validation.py` already used for structural validation;
matching reuses it rather than introducing a second, conflicting wildcard
system.

### Explicit family aliases

A type-def lists every classifier family key it supports explicitly --
matching never walks the family up or down the dotted hierarchy to find a
looser match (that would risk silently selecting the wrong fitting). If a
type should also match the non-coplanar variant of a family, say so:

```json
"family": ["branch.tee", "branch.tee.3d"]
```

(The one exception: a *currently selected* type's family may be a
descendant of the requested family, so a manually-picked, more specific
type stays valid even though the classifier can never literally produce
anything more specific -- see "Sticky selection".)

### How automatic matching works (`select_type`)

For a request (category, topology, family), `select_type()` first pulls
every structurally-indexed candidate (same category/topology/family, see
`HVACMatchKey`), then checks each one against the request's full context
(topology, degree/constraints, connected-port profiles) using the same
rules as `freecad/HVAC/library/validation.py`'s `context_violations()` --
a candidate that fails degree/topology/profile constraints is dropped
before ranking, so `matches_type()` and `select_type()` can never disagree
about whether a given type is eligible for a request.

The surviving, compatible candidates are then ranked into tiers, in order:

1. `kind: "model"`, declares concrete profile(s)
2. `kind: "model"`, `"Generic"`-profile match
3. `kind: "placeholder"`, declares concrete profile(s)
4. `kind: "placeholder"`, `"Generic"`-profile match

A type only reaches tier 1/3 if it's already been confirmed compatible --
i.e. its declared `profiles` cover every connected port's actual profile,
even when those ports span more than one profile (e.g. a dedicated
Circular -> Rectangular transition type with `profiles: ["Circular",
"Rectangular"]` outranks the broad Generic-profile fallback for a
mixed-profile transition, the same way it would for a homogeneous one).

**Ranking** picks the highest `selection.priority` within the first
non-empty, constraint-passing tier. If two or more candidates in that tier
tie at the highest priority, that's a genuine authoring ambiguity: it's
never resolved by JSON file/directory load order. In normal (non-strict)
use, an ambiguous tier is logged as a warning and matching falls through to
the next (broader) tier, eventually a placeholder, rather than silently
guessing; strict/testing callers can pass `strict=True` to get
`status="ambiguous"` back instead.

Priority only decides *which* type wins a fresh automatic selection -- see
"Sticky selection" for why it never disturbs an already-valid choice.

### Sticky selection

Normal network sync (`DuctNetwork.syncSegments`/`syncJunctions`) doesn't
call `select_type()` on every object on every sync. It first asks
`resolve_sticky_type(library_id, current_type_id, request)`:

- if the object's current `TypeId` resolves to a real (`kind: "model"`)
  type in its current `LibraryId`, and that type is still compatible with
  the latest classifier output -> **keep it**, no matter its
  `selection.priority` relative to other candidates.
- otherwise -> run `select_type()`.

This is why a manually-picked, lower-priority fitting (e.g. a long-radius
elbow instead of the library's default short-radius elbow) survives every
subsequent sync as long as it stays geometrically valid, and is only
replaced when the classification genuinely changes underneath it (topology,
family, profile, or a structural constraint like degree/port-profile no
longer holds).

**Placeholders are never sticky.** If the current `TypeId` resolves to
`kind: "placeholder"`, sync always re-runs `select_type()` -- so a marker
automatically upgrades to a real model the moment one becomes eligible
(more specific classification, a newly-available connected-port profile, a
reloaded library, ...).

An explicit **"reset to network defaults"** (`resetObjectsToNetworkDefaults`)
intentionally bypasses stickiness and always calls `select_type()` fresh
against the network's default library, since the user is asking to discard
manual choices, not just repair invalid ones.

### Inline components

A `DuctJunction` that's a simple 2-port `through` node can carry, besides
its automatically-selected **Primary** `DuctComponent`, zero or more
user-added **Inline** components in series (a damper, a silencer, a flex
connector) -- see [`ARCHITECTURE.md`](../../ARCHITECTURE.md) for how a
junction composes its component chain. A type-def marks itself as one of
these by declaring `selection.kind: "inline"`.

Inline types are excluded entirely from `HVACLibrary`'s automatic-matching
indexes (`_rebuild_match_index`), so `select_type()` can never choose one as
a Primary component *automatically*, no matter how its `family`/`profiles`
are declared. They're reachable through two deliberate, manual paths
instead:

- `HVACLibraryRegistry.list_inline_types(library_id, topology=, profile=)`,
  which the "Add Inline Component" UI action uses to populate its type
  picker (no family matching involved here -- adding an inline component
  is always a direct user choice, not something the classifier's output
  should drive);
- `HVACLibrary.list_types(...)`, the same listing the "change type" editor
  uses for a Primary component, which includes inline types too -- so a
  user can deliberately set a damper/VAV as a junction's Primary type
  itself, not just as a chained Inline component. Once set this way,
  `resolve_sticky_type()` retains it across sync like any other
  non-placeholder type (see "Sticky selection" below) -- only a *fresh*
  `select_type()` call never returns one.

`freecad/HVAC/libraries/smacna/types/junctions/through_damper_generic.json`
and `through_vav_generic.json` are the built-in examples.

### Adding a new type that's automatically selectable

A third-party/user library needs nothing beyond a descriptor JSON (declaring
`category`/`topology`/`family`/`profiles`/`selection`) and a geometry
implementation -- no change to `Network.py`, `Junction.py`, or any other
core module. Give it:

- the exact classifier `family` key(s) it should match,
- the `profiles` it supports (or `"Generic"`),
- a `selection.priority` higher than any broader/generic type it should be
  preferred over, if it overlaps with one.

Descriptors intentionally reachable only by *manual* selection (e.g. a
degree-1 terminal's specific function -- diffuser vs. AHU connection vs.
louver -- which the classifier cannot infer from geometry alone) don't need
a priority audit: they simply won't appear in any automatic-selection tier
whose family key the classifier can produce, and rely on "Sticky selection"
to stay selected once a user picks one.

## Naming convention

### Segments

`<profile>_<shape>`, e.g. `circular_straight`, `oval_straight`,
`rectangular_straight`, `circular_generic`. `profile` matches (lowercased)
one of the type's `profiles` entries.

### Junctions: `topology_family_sub_classification`

Every junction id **must start with its `topology` value** -- this is the
connectivity-graph role the parser's classifier assigns, and is one of:

- `through` -- degree-2, in-line (straight run, bend, transition, offset, inline device)
- `branch` -- a tee/wye/lateral splitting one run into two
- `cross` -- a 4-way crossing/double-wye
- `multiport` -- more than 4 ports meeting at one node
- `end` -- degree-1 (a terminal: diffuser, grille, louver, fan/AHU connection, ...)

For exactly how `topology` and `family` are derived from node geometry
(the degree/collinearity/eccentricity/coplanarity rules behind
`classify_node_topology` and `classify_junction_family`, and how the two
combine into the dotted `family` key matched against a type-def's `family`
list), see
[`freecad/HVAC/core/TOPOLOGY_CLASSIFICATION.md`](../core/TOPOLOGY_CLASSIFICATION.md).

After the topology, two further tokens narrow it down:

- **`family`** -- the specific fitting family within that topology (`tee`,
  `wye`, `elbow`, `transition`, `damper`, `vav`, `diffuser`, `fan_source`,
  `intake_exhaust`, `terminal`, ...). Omit this token (collapsing to just
  `topology_sub_classification`) when the type is generic across every
  family in its topology rather than one specific fitting -- e.g.
  `through_generic` covers straight/bend/offset alike, vs.
  `through_elbow_generic` which is bend-specific.
- **`sub_classification`** -- the implementation nature of the type:
  - `generic` -- a real, parametric geometry generator, usable for any
    configuration within its family.
  - `marker` -- an invisible placeholder with no real geometry, used purely
    to hold a graph node's connectivity (see `*_marker.json` throughout
    `builtin_basic`/`smacna`).
  - a backend name (e.g. `static`) -- reserved for `samples`, where the
    sub-classification records which geometry backend the type demonstrates
    rather than a real modeling distinction (`end_diffuser_static`).

Worked examples (from `smacna/types/junctions/`):

| id | topology | family | sub_classification |
|---|---|---|---|
| `branch_tee_generic` | branch | tee | generic |
| `branch_wye_generic` | branch | wye | generic |
| `branch_generic` / `branch_marker` | branch | *(all)* | generic / marker |
| `through_elbow_generic` | through | elbow | generic |
| `through_transition_concentric` | through | transition | concentric (its alignment; `eccentric`, `offset` alike) |
| `branch_tap_straight_damper` | branch | tap | straight_damper (a SMACNA-only variant, manual choice) |
| `through_damper_generic` | through | damper | generic |
| `through_vav_generic` | through | vav | generic |
| `through_generic` / `through_marker` | through | *(all)* | generic / marker |
| `cross_generic` / `cross_marker` | cross | *(all)* | generic / marker |
| `multiport_generic` / `multiport_marker` | multiport | *(all)* | generic / marker |
| `end_diffuser_generic` | end | diffuser | generic |
| `end_fan_source_generic` | end | fan_source | generic |
| `end_intake_exhaust_generic` | end | intake_exhaust | generic |
| `end_terminal_marker` | end | terminal | marker |
| `end_diffuser_static` (samples) | end | diffuser | static |

When adding a new junction type, pick the real topology first (it must match
the classifier's vocabulary, not just read naturally), then decide whether
it needs its own `family` token or genuinely applies across the whole
topology.

### Model file naming

A type's model file(s) under `models/` must be named after the type-def
`id`, not invented independently -- `models/<id>.py` for a PartScript,
`models/<id>.FCStd` for an FCStd-template, `models/<id>.json`/`models/<id>.step`
for a static descriptor + its source geometry. This applies regardless of
geometry backend: `smacna/types/segments/circular_straight.json` pairs with
`smacna/models/circular_straight.py`, `smacna/types/segments/rectangular_straight.json`
pairs with `smacna/models/rectangular_straight.FCStd`, and
`samples/types/junctions/end_diffuser_static.json` pairs with
`samples/models/static_diffuser.json`/`.step` (a static descriptor may point
at a differently-named source file, but the descriptor JSON itself should
still follow the type id where practical). When a library reuses one model
file across several type-defs (e.g. one PartScript parametrized by
`profile`), name the file after the shared generic id, not any one caller.
