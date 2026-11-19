# Node topology and junction-family classification

When the parser encounters a graph node while syncing a `DuctNetwork`, it
classifies that node's geometry into a `topology` and `family` and combines
them into a dotted `family_key` (e.g. `"through.bend_90.3d"`). This key is
matched against each junction type-def's `family` list to decide which
library types are valid candidates for that node — see
[`freecad/HVAC/libraries/README.md`](../libraries/README.md) for the
type-def side of this contract and the `topology_family_sub_classification`
junction naming convention.

This doc exists so a library author can predict what `topology`/`family`
tokens a given duct layout will produce, and therefore write correct
`family` entries in a junction type-def (`classify_node_topology` /
`classify_junction_family` in `freecad/HVAC/core/NetworkParser.py`).

## `topology`: degree -> topology

`topology` is purely a function of how many ports meet at the node (its
degree):

| degree | topology |
|---|---|
| `<= 0` | `isolated` |
| `1` | `end` |
| `2` | `through` |
| `3` | `branch` |
| `4` | `cross` |
| `>= 5` | `multiport` |

This is exactly the vocabulary required at the start of every junction type
id, and must match the type-def's own `topology` field.

## Geometric concepts used below

`family` classification within a topology is driven by three properties of
the node's connected ports, each computed against a fixed tolerance:

- **Collinear pair** — two ports whose directions are ~180° apart (within
  `2.0°`), i.e. they look like one straight through-run.
- **Eccentricity** — the perpendicular distance between two ports' lines.
  Two ports can be collinear (antiparallel directions) but still offset in
  space; eccentricity is what tells a true straight-through connection
  (`eccentricity < 1e-6`) apart from a jog/offset (`eccentricity >= 1e-6`).
- **Coplanar** — true when every pair of connected ports has zero
  eccentricity, i.e. all ports at the node lie in one plane. Any family
  computed on a non-coplanar node gets the `"3d"` qualifier appended.

## `family`: degree -> (family, qualifiers)

Families are generic and profile-independent — no duct-size or
profile-specific logic feeds into this. The only qualifier in use today is
`"3d"`, appended whenever the node's ports are not coplanar.

**Degree 1 (`end`)** — always `terminal`. No geometry to disambiguate a
single port.

**Degree 2 (`through`)**:
- Ports collinear:
  - Same profile and section size, eccentricity ~0 → `straight`.
  - Same profile and section size, nonzero eccentricity → `offset` (a jog).
  - Different profile or section size (regardless of eccentricity) →
    `transition` (a real section change, whether or not the axes also
    happen to be displaced).
- Ports not collinear, angle ~90° → `bend_90`; otherwise → `bend`.
  `["3d"]` appended if the two ports aren't coplanar.

**Degree 3 (`branch`)**:
- One collinear pair (a trunk run) + one branch port: branch angle to the
  trunk ~90° → `tee`; otherwise → `lateral_tee`. `["3d"]` if not coplanar.
- No collinear pair (all three ports diverge) → `wye`. `["3d"]` if not
  coplanar.
- Any other case (rare/ambiguous geometry) → `generic`.

**Degree 4 (`cross`)**:
- Two independent collinear runs crossing at the node, with the two runs
  roughly orthogonal to each other → `cross`. `["3d"]` if not coplanar.
- One collinear trunk run + two remaining ports that make roughly equal
  angles with the trunk → `double_wye`. `["3d"]` if not coplanar.
- Anything that doesn't cleanly resolve to a two-run cross or a symmetric
  double-wye → `generic`.

**Degree >= 5 (`multiport`)** — always `multiport`. `["3d"]` if not
coplanar. No further family distinction is attempted at this fan-out.

## Matching against type-defs

`topology`, `family`, and any qualifiers are joined into a dotted
`family_key` (e.g. `through.bend_90.3d`, `branch.tee`), which is matched
against a type-def's `family` list as a **prefix** match: a type-def entry
`"through.bend"` matches both `"through.bend"` and `"through.bend.3d"` (any
key starting with `"through.bend."`). This means a type-def can choose to
cover the planar and 3D variants of a family together with one entry, or
list them separately if the two need different geometry/constraints.

## Flow classification: `flow_class` / `qualifiers` / `derived_values`

A second, independent classifier (`DuctNetworkParser.classify_flow`) runs
alongside `topology`/`family`/`family_key` and is kept on separate
`JunctionAnalysis` fields -- it never changes `family_key`, and a type-def's
`family` list is still the only thing that decides index-lookup eligibility
(see "Matching against type-defs" below). Like topology/family, it is
derived purely from base-segment orientation
(`JunctionPort.flow_role`/`flow_direction`), never from the hydraulic
solver.

- `flow_class`: for a `through.transition`-eligible pair (collinear, degree
  2), one of `expansion`/`contraction`/`constant`/`unknown` (by outlet vs.
  inlet cross-section area); for a degree-3 branch, one of
  `diverging`/`converging`/`unknown` (by inlet/outlet port count); for a
  cross or multiport node the same `diverging` (one inlet, the rest outlets)
  / `converging` (one outlet, the rest inlets) / `unknown` (anything else,
  including several inlets and several outlets at once); for an end node,
  `entry` (air comes into the duct system there), `exit` (air leaves it) or
  `unknown`; `unknown` everywhere else (bends, ...). End, cross and
  multiport nodes get a `flow_class` only, no qualifiers or derived values. A degree-2 pair whose
  two ports don't resolve to exactly one inlet and one outlet (see
  `_resolve_inlet_outlet()`) is also `unknown` -- direction always comes
  from base-segment orientation, never an arbitrary port order, so an
  ambiguous pair never gets labelled `expansion`/`contraction` by guesswork
  (and none of `qualifiers`/`derived_values` below is computed for it
  either, since all of it depends on which port is the inlet).
- `qualifiers` (`dict[str, str]`): degree-2 collinear pairs get
  `inlet_profile`/`outlet_profile`/`profile_relation`
  (`"same"`/`"mixed"`), plus `alignment` and (where derivable)
  `transition_form`. `alignment` is computed in one common local frame
  (the inlet's own flow direction as the longitudinal axis, its
  `ProfileXAxis` as the transverse reference -- never each port's own
  outward-pointing `direction` independently, since through-port
  directions are opposite):
  - Same-profile **Rectangular** pair: `"concentric"` (centres aligned),
    `"eccentric"` (exactly one corresponding side aligned, plus
    `aligned_side` = `"top"`/`"bottom"`/`"left"`/`"right"`),
    `"double_eccentric"` (exactly one corresponding corner aligned, plus
    `aligned_corner` = e.g. `"top_left"`), or `"offset"` (none of the
    above).
  - Same-family **Circular**/**Oval** pair: the same "one side flush"
    test as Rectangular (offset entirely along one local axis, by the
    exact radius/half-extent difference -- the classic tangent-edges
    eccentric reducer) gives `"concentric"` or `"eccentric"`, but never
    `"double_eccentric"`/`aligned_side`/`aligned_corner` (no corners, and
    a circle has no side of its own to name) -- anything else (an offset
    that doesn't bring the edges tangent on either axis, e.g. an
    arbitrary diagonal displacement) is `"offset"`.
  - Mixed profile families (e.g. Circular -> Rectangular), or a
    degenerate/unresolvable frame: `"unknown"`.

  `transition_form` is `"conical"` (Circular -> Circular size change),
  `"pyramidal"` (Rectangular -> Rectangular, both dimensions change),
  `"single_plane"` (Rectangular -> Rectangular, one dimension changes),
  `"profile_change"` (different profile families), `"unknown"` (a real
  section change occurred but this profile family -- Oval/Generic/custom
  -- isn't reliably classifiable into the vocabulary above; never
  silently forced into the Circular/Rectangular forms), or omitted
  entirely when there's no actual section change to classify.

  A degree-3 tee/lateral_tee (one geometrically identified trunk/run
  pair) gets `common_leg` (`"run"`/`"branch"`) from which port's flow
  role is the odd one out relative to that trunk pair -- e.g. an ordinary
  dividing tee is `common_leg="run"`, a bullhead dividing tee is
  `common_leg="branch"`; a wye has no trunk pair, so no `common_leg`
  (never inferred by any other means -- a true Wye's own loss lookup
  uses a separate API entry point, `HVACLossAPI.wye_loss`, rather than
  the Tee-oriented `branch_loss`, see `library/loss_api.py`).
  Same-or-mixed-profile is also exposed as `profile_relation` here.
- `derived_values` (`dict[str, float]`): `area_ratio`, `aspect_ratio_in`/
  `aspect_ratio_out`, `offset_ratio` where computable; a branch tee/
  lateral_tee also gets `area_ratio` as branch-leg area over trunk-leg
  area, plus `branch_angle` -- the geometric angle (degrees) between the
  branch leg and whichever trunk leg it's closer to, derived purely from
  each port's own geometric `direction` (never from flow direction, so it
  doesn't flip with base-segment orientation the way `flow_class` does).
  `offset_ratio` is the *transverse* offset only (perpendicular to the
  inlet's flow direction, in the same common frame `alignment` uses) over
  a representative duct dimension -- it never includes any longitudinal
  port separation along the flow axis.

  These are all standardized keys `NetworkParser.classify_flow` itself
  produces (see `library/validation.py`'s `KNOWN_QUALIFIER_KEYS`/
  `KNOWN_DERIVED_VALUE_KEYS`). A value that depends on a *selected
  fitting's own* properties instead -- e.g. a transition angle computed
  from a chosen `TransitionLength` -- is a fitting/type-derived value,
  not a parser-derived one, and isn't exposed through `derived_values`
  here. Those are *fitting-derived values*: a pure helper per fitting
  kind computes them from the ports and the resolved properties (e.g.
  `library/fittings/transitions.py`'s `transition_dimensions` and
  `offset_dimensions`), the generator reports them as read-only computed
  properties (`IncludedAngle`, `BodyLength`, `OffsetAngle`,
  `ActualRadius`, group `Derived`), and the loss function calls the same
  helper. They exist only after a build, so they never take part in type
  matching, and the loss never reads the stored properties back (they go
  stale until the next recompute).

A type-def's JSON `constraints` can filter on any of these -- see
`freecad/HVAC/library/validation.py`'s `context_violations()` and
`freecad/HVAC/libraries/README.md`. The same classification also drives a
type-def's optional `loss.variants` (picking a *loss formula* for an
already-selected TypeId, e.g. an ordinary vs. bullhead tee, rather than
picking the TypeId itself) via `validation.resolve_loss_variant()` --
see `freecad/HVAC/libraries/README.md`'s "Flow-dependent loss variants".

A new family string has no effect on its own — it only becomes reachable
once some type-def's `family` list references its dotted key. If a real
duct layout produces a `topology`/`family` combination that doesn't fit any
existing type-def, or a fitting distinction you need doesn't map onto the
degree/collinearity/eccentricity/coplanarity vocabulary above, raise it
rather than working around it in library code — see `AGENTS.md`'s layering
guidance (core classification logic must stay generic; fitting-specific
behavior belongs in library data).
