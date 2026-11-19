# Type-def reference

<!-- The keys of a type-def JSON file. For how the pieces fit together, see
     the library guide (library-guide.md). -->

Every key of a type-def file (`types/segments/<id>.json`,
`types/junctions/<id>.json`), as loaded into `HVACTypeDef`
(`freecad/HVAC/library/Library.py`). Unknown property keys and validation
rules are load errors, so a typo cannot become a limit that is never
enforced. For how a library is
put together, see [the library guide](library-guide.md); for the APIs and
context keys, [the API reference](library-api.md).

## Fields

Common fields, both segments and junctions:

| field | meaning |
|---|---|
| `id` | stable identifier within the library; see the [naming convention](../freecad/HVAC/libraries/README.md#naming-convention) |
| `label` | display name |
| `category` | `"segment"` or `"junction"` |
| `topology` | junctions: `through`, `branch`, `cross`, `multiport` or `end`, as the classifier assigns it; also the first token of the id (see the naming convention) |
| `family` | list of dotted family strings the parser's classifier matches against (segments: e.g. `["straight_segment"]`; junctions: e.g. `["through.bend", "through.bend_90"]` -- see `classify_junction_family`, documented in [`freecad/HVAC/core/TOPOLOGY_CLASSIFICATION.md`](../freecad/HVAC/core/TOPOLOGY_CLASSIFICATION.md)) |
| `profiles` | allowed cross-section profiles, e.g. `["Circular"]`, `["Rectangular"]` |
| `constraints` | e.g. `{"degree": 1}` restricting how many ports a junction may have; junctions can additionally constrain `flow_class`, `qualifiers.<key>`, `profile_relation`, `inlet_profile`, `outlet_profile`, and any `derived_values` entry (e.g. `area_ratio`) -- see below |
| `properties` | list of property defs (below) |
| `construction` | optional `{"layers": [...], "features": [...]}` object (below); when omitted, inherits the library manifest's `default_construction`, or falls back to one roleless implicit layer if the manifest has no default |
| `geometry` | required: `{"backend": "generator", "module": "...", "function": "..."}`, `{"backend": "partscript", "file": "..."}` or `{"backend": "static", "descriptor": "..."}`. The old top-level `"generator"` key is refused |
| `connection_lengths` | optional: `{"module": "...", "function": "..."}` -- a lightweight, independent per-port trim *measurement* function (parsed onto `HVACTypeDef.lengths_module`/`lengths_function`; see below) |
| `loss` | optional: `{"module": "...", "function": "...", "variants": [...]}` -- the fitting-loss function for the airflow solver; its context provides `HVACLossAPI` as `context["loss_api"]`. `variants` (optional) switch formula by flow -- see "Flow-dependent loss variants" |
| `selection` | optional: `{"kind": "model" \| "placeholder" \| "inline", "priority": <number>}` -- how automatic selection treats the type (see the library guide, "Type selection"); default `model`, priority 0 |
| `flow_boundary`, `flow_boundary_locked` | optional, terminals: the flow condition the type prescribes (see "Terminal flow condition") |
| `friction` | optional, segments only: `{"module": "...", "function": "..."}` -- a straight-duct friction model factory (see below) |

## Properties (`HVACPropertyDef`)

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

### Per-port properties

 A property marked `"per_port": true` holds one
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

### Port roles

 `api.port_roles(context)` returns the connected ports by
role: `neck` (1 port), `inlet`/`outlet` (2), `run_a`/`run_b`/`branch` (tee),
`main`/`branch_a`/`branch_b` (wye), `run_a`/`run_b`/`branch_a`/`branch_b`
(cross), `port_1`..`port_n` (anything else).

### Trim property names

 A fitting whose ports have fixed roles names one
trim property per role, `Trim<Role>`: `TrimRunA` / `TrimRunB` / `TrimBranch`
(tee, tap, lateral tee), `TrimMain` / `TrimBranchA` / `TrimBranchB` (wye).
A fitting whose ports have no such role (generic branch, cross, multiport)
uses one per-port `TrimLength`. The same goes for flange switches:
`ShowFlange<Role>` for a role, one per-port `ShowFlange` otherwise.

## Flow-classification constraints

Beyond `degree`/`degree_min`/`degree_max`, a junction type-def's
`constraints` can filter on `DuctNetworkParser`'s flow-classification
output (`flow_class`/`qualifiers`/`derived_values` -- see
[`freecad/HVAC/core/TOPOLOGY_CLASSIFICATION.md`](../freecad/HVAC/core/TOPOLOGY_CLASSIFICATION.md)),
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

## Flow-dependent loss variants

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
[`freecad/HVAC/core/TOPOLOGY_CLASSIFICATION.md`](../freecad/HVAC/core/TOPOLOGY_CLASSIFICATION.md)
for where `flow_class`/`qualifiers`/`derived_values` themselves come
from (`NetworkParser.classify_flow`).

## Terminal flow condition

A terminal (`topology: "end"`) type may use two optional fields to prescribe
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

## Loss context extras

The loss context also contains the component's own role-based
`context["construction"]` and its resolved effective
`context["hydraulic_roughness_mm"]`. The latter uses the network default
only if the construction's flow-surface material has no roughness value.
Library loss code may call the construction's other physical queries (for
example `acoustic_impedance()` or `overall_u_value()`) without importing
core modules.

## `friction`: straight-duct friction models

A segment type can replace or correct the network's friction model
(`DuctNetwork.FrictionModel`: `DarcyAltshulTsal`, the default,
`DarcyColebrook`, `Table` from the CSV in `FrictionTableFile`, or
`Expression` from `FrictionExpression`; see `freecad/HVAC/analysis/friction.py`).
The factory is called once per segment per solve with a context holding
`properties`, `roughness_mm`, `base_model` (the network's model; None
means the default) and `friction` (the `analysis.friction` module), and
returns any object with
`rate_pa_per_m(flow_m3_s, area_m2, dh_m, roughness_m, density_kg_m3, kinematic_viscosity_m2_s)`.
A factory that only corrects the network's model should wrap `base_model`
(e.g. `friction.ScaledFriction(base_model, factor)`), so a project-wide
table still applies underneath.

Shipped: `shared:friction` / `friction_flex_compressed`, used by
`builtin_basic/circular_flex` and `smacna/circular_flex` (manual only): the network's model times the
SMACNA Fig. 14-4 correction for `CompressionPercent`.

## `connection_lengths`: independent trim measurement

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

## Construction layers

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

## Construction features

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
  It also provides `flex_ribs`: the rings of a flexible duct's wire helix,
  one every `RibPitch` along a segment's path (straight or curved),
  `RibWidth` wide and `RibHeight` proud of `host_layer`'s outer face
  (`smacna/circular_flex`).
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

### Shared feature generators

 Besides `shared:features` /
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
