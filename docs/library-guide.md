# Writing an HVAC library

This guide walks through writing a library of duct and fitting types, from
the folder layout to checking the result in FreeCAD. Two companion pages
hold the details:

- [Type-def reference](type-def-reference.md): every key of a type-def JSON
  file (properties, constraints, losses, friction, construction layers and
  features).
- [Library API reference](library-api.md): every function and constant of
  the geometry and loss APIs, and every context key library code receives
  (generated from the code).

[Loss coverage](loss-coverage.md) lists which loss function every shipped
junction type uses. The naming convention for type ids and model files is in
[`freecad/HVAC/libraries/README.md`](../freecad/HVAC/libraries/README.md).

## 1. What a library is

An HVAC library is any directory under a configured search path (by default
`freecad/HVAC/libraries/`, see `hvaclib.get_default_library_search_paths()`)
containing a `library.json` manifest. `HVACLibraryRegistry.scan_path` auto-
discovers every such directory; there's no separate registration step.

Three libraries ship today:

- **`builtin_basic`** -- generic types, always available.
- **`smacna`** -- SMACNA-based sheet-metal duct and fitting types (sheet
  thickness, insulation, flanges), the ones meant for day-to-day modeling.
- **`samples`** -- not for modeling; a minimal working example of each
  geometry backend (section 4).

Both `builtin_basic` and `smacna` are data only: their type-defs point at
the addon's shared fitting modules (`shared:` prefix, section 4.4), so
neither has generator code of its own.

## 2. Directory layout

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

## 3. `library.json`

```json
{
  "id": "smacna",
  "label": "SMACNA",
  "requires_api": {"geometry": 4, "loss": 1},
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
  `freecad/HVAC/library/contexts.py` (both checked by tests, both listed in
  [the API reference](library-api.md)).
- `generators_package`: the Python package `import_generator(library_id, module)`
  imports `<generators_package>.<module>` from, for the `"generator"` geometry backend.
- `default_construction`: optional construction layers inherited by every
  type that does not declare its own `construction.layers`. This keeps the
  material construction uniform for simple parts within one library.
- `type_roots`: directories (relative to the library root) scanned for `*.json` type-defs.

## 4. Producing geometry

A type-def names one *geometry backend* (`"geometry": {"backend": ...}`).
Every backend receives the same `context` dict and returns the same result.

### 4.1 The context

Geometry code gets a `context` dict with exactly the keys listed in
[the API reference](library-api.md#context-keys): `hvac_api` (the geometry
API), `loss_api`, `properties` (the type's resolved property values),
`library_id`, `type_id`, `construction_layers`; for a segment `start_point`,
`end_point`, the path and profile; for a junction `connected_ports` (one
dict per connected duct: `position`, `direction` pointing out of the node,
`profile`, `section_params`, `profile_x_axis`, `edge_key`, ...),
`center_point` and `analysis` (the node's topology analysis, see
[`TOPOLOGY_CLASSIFICATION.md`](../freecad/HVAC/core/TOPOLOGY_CLASSIFICATION.md)).

Read ports through the API (`api.port_position(port)`, `api.port_roles(context)`,
`api.run_branch_ports(context)`, `api.port_param(context, name, port)`), not by
digging into the dicts: the accessors read the classifier's own result
rather than re-deriving collinearity with a tolerance of their own.
`analysis` is empty (`{}`) for a synthetic context (most unit tests);
`run_branch_ports()` then raises a clear `ValueError` instead of guessing.

### 4.2 The result

Every backend returns `{"layers": {<layer id>: {"shape": <Part.Shape or None>}, ...}}`,
one entry per construction layer the type declares (section 6). Layer ids
are whatever the type-def's `"construction"` block declares;
`build_geometry()` stamps each layer's roles on from there.
`api.single_layer(context, shape)` builds the result for a fitting that is
one solid, `api.build_layered_geometry(envelope, layers, params)` for a
fitting built as an envelope (section 4.4).

A junction's result also carries `"connection_lengths"` (how far each
connected duct is trimmed back: `api.build_trim_rec_from_port_lengths`). It
may also carry `"computed_properties"` (`{name: value}` for declared, usually
read-only, properties) and `"property_choices"` (`{name: [choices]}`: a
drop-down offers only these of its declared `validation.enum`; a value no
longer offered falls back to the default). See
`freecad/HVAC/library/geometry_result.py` for the `GeometryResult` /
`LayerGeometry` contract every result is normalized into, and
`freecad/HVAC/library/Library.py:build_geometry` for the dispatch.

### 4.3 The backends

**PartScript** (`"geometry": {"backend": "partscript", "file": "models/<id>.py"}`).
A plain Python file, loaded and run by `freecad/HVAC/library/partscript_shapes.py`.
It sets `HVAC_PARTSCRIPT_API = 3` and defines `generate(context) -> {"layers": ...}`
(a bare `Part.Shape` is also accepted and put on the type's first layer); an
optional `validate(context)` runs first. The preferred backend for a new
parametric type: no code outside the one file. Example:
`samples/types/segments/circular_acoustic_straight.json` ->
`samples/models/circular_acoustic_straight.py`, three concentric layers
(liner, absorber, jacket); `smacna/models/through_elbow_rectangular.py`.

**Static BREP/STEP** (`"geometry": {"backend": "static", "descriptor": "models/<id>.json"}`).
A fixed, non-parametric shape (a vendor STEP file) with a fixed port list.
The descriptor (`freecad/HVAC/library/static_shapes.py`) points at the
geometry file and gives its placement, ports (position, direction, profile,
section) and connection lengths; no Python at all. Example:
`samples/types/junctions/end_diffuser_static.json` ->
`samples/models/static_diffuser.json` -> `static_diffuser.step`.

**Generator function** (`"geometry": {"backend": "generator", "module": "...", "function": "..."}`).
A function `func(context) -> {"layers": ..., "connection_lengths": ...}` in
`<library>/generators/<module>.py`, or in a shared fitting module
(`"module": "shared:elbows"`, section 4.4). It is also how a type loads a
whole parametric FreeCAD document: the generator calls
`api.shape_from_fcstd(path, context, params={...}, result_object=...)`,
which opens the `.FCStd`, sets its `App::VarSet` properties, recomputes and
returns the named object's shape. Example:
`samples/types/segments/rectangular_straight.json` ->
`samples/generators/segments.py:build_rectangular_straight_fcstd` ->
`samples/models/rectangular_straight.FCStd`.

**Choosing a backend.**

- A new parametric type, geometry written in Python: **PartScript**.
- Fixed or imported geometry (vendor part, STEP export): **static**.
- Geometry more naturally drawn in the FreeCAD GUI (sketches, VarSet-driven
  expressions): **generator + `shape_from_fcstd`**.
- A standard fitting (elbow, tee, wye, transition, ...): **a shared fitting
  module**, no code at all (section 4.4).
- Logic beyond one file (choosing between sub-models by size, helpers
  shared by many types): **generator function**.

### 4.4 Shared fitting modules (`"shared:"` prefix)

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
`devices`, `boxes`, `through`, `markers` and `equipment` (equipment models,
see `library/equipment_library.py`); `features`, `dampers`, `details` and
`faces` hold construction-feature generators, `losses` the loss functions
and `friction` the friction factories. Every
fitting in them is built as an *envelope*: its air space grown outward by a
wall offset. What comes out therefore depends only on what the type-def
declares:

- **Wall layers.** Each construction layer that names a `thickness_property`
  becomes its own hollow shell, innermost first (a casing, then insulation
  around it, ...). If no layer has a thickness above zero, the fitting is
  returned as one solid body of the air space.
- **Flanges and other details.** Never part of a layer: a flange is the
  `transverse_flange` construction feature (see the type-def reference,
  "Construction features"), so it can be hidden, counted and given its own
  material.

Code that needs a standard fitting directly (a PartScript, a library's own
generator) gets the same builders through the API instead of a type-def:
`api.build_fitting("elbow", context)` / `api.measure_fitting("elbow", context)`
(names in `HVACLibraryAPI.STANDARD_FITTINGS`), and
`api.build_layered_fitting(context, envelope_builder, connection_lengths)`
to give a custom shape the same layer treatment.

### 4.5 Connection lengths without building

A junction type can also declare `connection_lengths`: a function that
returns its trims without building any geometry, so the network can place
chained inline components cheaply. It must share the calculation its
geometry uses. See the type-def reference, "`connection_lengths`".

## 5. What library code may do

Library code (generators, PartScripts, feature generators, loss and
friction functions) talks to the addon only through its context:

- **Only the APIs.** It never imports `FreeCAD`, `Part` or any internal HVAC
  module (`tests/test_library_geometry_api_v2.py` checks the shipped
  libraries). Everything it needs is in `context["hvac_api"]` and
  `context["loss_api"]`; the public names are fixed per `API_VERSION`.
- **Only the documented context keys** (`tests/test_context_keys.py`).
- **Shapes.** Library code may *read* the shapes the API returns: their
  members (`Volume`, `Area`, `Length`, `BoundBox`, `CenterOfMass`, `Faces`,
  `Edges`, `Vertexes`, `Solids`, `OuterWire`, `isNull()`, `isValid()`) and
  their own queries and booleans (`copy()`, `fuse()`, `cut()`, `common()`,
  `distToShape()`). It *builds* new geometry only through the API:
  sections with `make_profile` / `profile_from_port`, faces with
  `make_face`, solids with `extrude` / `sweep` / `loft` / `revolve`,
  placement with `translate` / `rotate`, points along a path with
  `sample_path`. Vectors come from `api.vec(...)`; ordinary vector
  arithmetic on them is fine.
- **No retries.** A fitting builds each shape once, in a fixed order, and
  checks the result (`api.validate`); a layout that cannot work refuses
  before building, with a message saying what to change. No fuse-order
  searches or fuzzy booleans.

## 6. Construction layers and features

A type's wall is a stack of *construction layers* (a sheet-metal casing,
insulation around it, a liner, ...), each with semantic roles
(`flow_surface`, `structural_shell`, `thermal_insulation`, ...) that
materials, appearance and the analyses query; core never branches on a
layer's id. A layer that names a `thickness_property` becomes its own hollow
shell when the type is built as an envelope (section 4.4).

*Construction features* are smaller attachments on one layer: flanges,
damper blades, the drawn face of a diffuser, a flexible duct's ribs. Each
is its own shape (`Feature_<id>_Shape`), never fused into a layer, so it can
be hidden (Layer Visibility) and counted. Shared feature generators exist
for flanges (`transverse_flange`), flexible duct ribs (`flex_ribs`), damper
blades and operators, and terminal faces.

Both are declared in the type-def's `"construction"` block; the keys are in
the type-def reference ("Construction layers", "Construction features").

## 7. Losses and friction

A junction type names a loss function (`"loss": {"module": ..., "function": ...}`),
usually one of `shared:losses`. It receives the loss context (the ports with
their flow, velocity and Reynolds number, the flow class, qualifiers and
derived values, the construction and roughness) and returns an
`analysis.loss.LossEvaluation`, normally by calling one of the
`HVACLossAPI` functions, which read the digitised SMACNA tables and say when
a reading is an approximation. One type can switch formula by flow
(`loss.variants`, e.g. diverging or converging). A segment type can replace
or correct the network's friction model (`"friction"`). Keys and rules are
in the type-def reference; which function every shipped type uses is in
[Loss coverage](loss-coverage.md).

## 8. Type selection (automatic matching)

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
  [`TOPOLOGY_CLASSIFICATION.md`](../freecad/HVAC/core/TOPOLOGY_CLASSIFICATION.md) for
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
connector) -- see [`ARCHITECTURE.md`](../ARCHITECTURE.md) for how a
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
and `through_vav_generic.json` are the built-in examples; the silencer,
filter, coil, fire damper, access door and flexible connector types
(`through_<device>_generic.json`) follow the same pattern.

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

## 9. Naming

Type ids follow `<profile>_<shape>` for segments and
`topology_family_sub_classification` for junctions; a model file is named
after its type id. The full rules are in
[`freecad/HVAC/libraries/README.md`](../freecad/HVAC/libraries/README.md#naming-convention).

## 10. Checking a library

- **Unit tests** (`python3 -m pytest -q tests`): the shipped type-defs load,
  reference existing functions, match the API and context rules, and every
  selectable junction type has a loss.
- **Smoke run** (`tools/geometry_smoke.py`, in FreeCAD's Python): builds
  every junction type of the shipped libraries on simple nodes and reports
  invalid shapes and trims that disagree with the type's measurement.
- **Geometry sweep** (`tools/geometry_sweep.py`): the branch and bend
  fittings across branch sizes, angles, every profile and wall build-ups;
  the acceptance check for fitting geometry changes. A fitting that builds on
  one node can still fail at another size or with insulation.
- **Generated pages**: `python3 tools/loss_coverage.py --write` and
  `python3 tools/api_reference.py --write` after changing a loss or a public
  API name; the tests fail while either page is stale.
- **The GUI**: shapes still need a look in FreeCAD; no script sees a face
  that is valid but wrong.
