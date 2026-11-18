# Architecture / process flow

Short, practical map of how this addon actually runs — for developers and
for Claude picking up work in a fresh session. Rules for *how* to write code
here live in [`AGENTS.md`](AGENTS.md); this document is about how the
pieces fit together and execute. For the user-facing feature overview see
[`README.md`](README.md).

## The four layers

```
DuctNetwork              container: owns Base/Geometry/Topology folders, drives sync
     |
DuctNetworkParser         classifies: connectivity, topology, family, port profiles
     |
DuctSegment / DuctJunction + DuctComponent   generated objects: hold LibraryId/TypeId + geometry
     |
Library layer              JSON type-defs + HVACLibraryRegistry: what geometry to build
```

Each layer only talks to the one below it. Don't hardcode fitting-specific
logic upstream of where it belongs (e.g. no fitting knowledge in the
parser) — see `AGENTS.md` §3 "Respect the layering".

A `DuctJunction` is a purely logical/connectivity node — it holds no
`LibraryId`/`TypeId`/`Shape` of its own. Each `DuctJunction` has exactly one
**Primary** `DuctComponent` (the automatically/manually selected main
fitting for that node, whatever its topology — a through fitting, a tee, a
cross, a multiport, or a terminal device). Independently of that, each real
junction port/edge may separately carry zero or more user-added **Inline**
components (a damper, a silencer, ...) in series, arranged from the Primary
outward toward that edge's own external segment — not limited to a simple
2-port node: a tee's branch leg and one of its run legs can each grow a
completely independent chain. See "Junction component composition" below.

| Layer | File(s) | Job |
|---|---|---|
| Container | `freecad/HVAC/core/Network.py` (`DuctNetwork`) | Owns the network's Base/Geometry/Topology folders, network-wide defaults, and the sync loop that keeps everything below in step with the base geometry. |
| Classifier | `freecad/HVAC/core/NetworkParser.py` (`DuctNetworkParser`) | Reads base sketches/wires, builds a connectivity graph, and classifies each node's `topology`/`family_key` and each edge's port profile. Never picks a type, never knows about components. See [`core/TOPOLOGY_CLASSIFICATION.md`](freecad/HVAC/core/TOPOLOGY_CLASSIFICATION.md). |
| Generated objects | `freecad/HVAC/core/Segment.py`, `freecad/HVAC/core/Junction.py`, `freecad/HVAC/core/Component.py` | `DuctSegment`/`DuctComponent`: FreeCAD document objects that store `LibraryId`/`TypeId` and other metadata, and `execute()` by resolving that TypeId and asking the library layer to build geometry. `DuctJunction` itself holds no type/geometry — it composes its `DuctComponent` children's local ports each sync and aggregates their trim contributions. None of these classify or select a type themselves. |
| Library | `freecad/HVAC/library/Library.py`, `freecad/HVAC/library/validation.py`, `freecad/HVAC/utils/hvaclib.py` (`HVACLibraryService`), `freecad/HVAC/libraries/**/*.json` | Loads type-defs from JSON, decides *which* type-def matches a request, and dispatches to the geometry backend (PartScript / static BREP / generator). See [`docs/library-guide.md`](docs/library-guide.md). |

## Core modules

One-line concept per module — read the module's own docstring for detail,
it's kept accurate and up to date on purpose.

| Module | Concept |
|---|---|
| `core/Network.py` | `DuctNetwork` container + the debounced sync loop (`requestSync`/`_runDeferredSync`) that keeps `DuctSegment`/`DuctJunction` objects in step with base geometry. Its own two `ViewProvider` classes (`DuctManagedFolderViewProvider`/`DuctNetworkViewProvider` — Coin rendering, task-panel `setEdit`, direction-arrow overlays) live in `ui/NetworkViewProvider.py` instead, so this module has no top-level `FreeCADGui`/`pivy`/`PySide` import and stays importable headless; the few call sites that still need `Gui`/`QtCore` (selection, active-object, the sync debounce timer) import them locally, inside the one method that needs them. |
| `core/NetworkParser.py` | `DuctNetworkParser`: builds a geometric graph from actual snapped endpoints, then an analysis graph on top (grouped "supernodes" for user-defined virtual junctions) that connectivity/degree/classification actually run on. |
| `core/Segment.py` / `core/Component.py` | `DuctSegment`/`DuctComponent`: FreeCAD document objects. `updateMetadata()` is a pure metadata writer (no selection logic); `execute()` does an exact type lookup and builds geometry. Both use the shared `core/_type_schema.apply_type_schema()` helper for their dynamic (type-declared) properties. See "Type selection subsystem" below. |
| `core/Junction.py` | `DuctJunction`: a logical node with no type/geometry of its own. `getComponents()`/`getPrimaryComponent()` find its `DuctComponent` children (via `ParentJunctionName`, in `Sequence` order); `composeComponents()` works out each child's local inlet/outlet ports for the current sync (a single-component junction gets the real connected ports unchanged); `aggregateConnectionLengths()` rolls each component's own trim into the external trim contract (`ConnectionLengthsJson`). See "Junction component composition" below. |
| `core/_port_properties.py` | Per-port type properties (`"per_port": true` in a type-def): keeps each one's value list and hidden edge-key list on a component in step with its current ports, and carries the keys across a document reload. Resolution into `{edge_key: value}` is in `library/validation.py` (`PortValues`). |
| `core/_terminal_function.py` | Terminal function (ROADMAP 6.5): resolves an end node's role (Supply, Return, Exhaust, OutdoorAir, Discharge, Source) from `DuctNetwork.SystemType`, the junction's `TerminalFunction` and its drawn direction; written into the node's `terminal_function` qualifier during junction sync, and checked against the drawn direction by the flow solve. Pure. |
| `core/_custom_fitting.py` | Port markers shared by custom fittings and equipment (ROADMAP 6.3): `Part::LocalCoordinateSystem` with `PortProfile`/size and an X/Y offset from the face centre, `add_port()` / `set_port_offset()` / `remove_port()`. A custom Primary component either places an `App::Link` on its node using `library/custom_fitting.py`'s fit (`CustomPlacement` "Fit to node") or uses the container where it was modelled (`"In place"`, `fit_in_place`). `make_custom_fitting()` marks an App::Part so ducts drawn to its ports attach to it (`attach_in_place()`). |
| `core/_auto_attach.py` | Which open duct ends sit on equipment or custom fitting port markers (pure). `DuctNetwork.getNodeGroups` turns the ends on one custom fitting into one node group (like a virtual junction); `DuctNetwork.autoAttach`, run after `syncJunctions`, gives that junction the fitting in place and connects ends on equipment ports (`Equipment.connect`), dropping connections to nodes that are gone. |
| `core/Equipment.py` | HVAC equipment (ROADMAP 6.5): an App::Part made equipment by `make_equipment()`, whose port markers feed terminals of several networks; `connect()` makes a terminal its network's Source, and `update_from_airflow()` totals port flows and fan duties after each network's calculation. `TaskPanelPortContainer` (ui) edits the ports of equipment and custom fittings. |
| `core/FlowNetwork.py` | Thin FreeCAD adapter: builds a `NetworkModel` from a `DuctNetwork` (via `core/_analysis_adapter.py`) and calls `analysis/flow.py`'s pure solve — see "Analysis layer" below for the actual algorithm. Shared by AirflowSolver and DuctSizer. |
| `core/AirflowSolver.py` | Thin FreeCAD adapter over `analysis/pressure.py`'s pure `PressureSolver`: builds the network model, solves it, writes the results back onto segment/junction/component `Calc*` properties, and returns the same `SegmentResult`/`JunctionResult`/`ComponentResult`/`AirflowSolveResult` shape it always has. |
| `core/DuctSizer.py` | Thin FreeCAD adapter over `analysis/sizing.py`/`analysis/balancing.py`: picks the sizing strategy for the network's `SizingMethod`, maps the pure result back onto `SegmentSizeResult`/`DuctSizingResult`. Never mutates objects itself — `solve()` returns a preview; `apply()` is a separate, explicit write step. |
| `core/_analysis_adapter.py` | The one place a real `DuctNetwork` gets read into `analysis/model.py` dataclasses: `build_network_model()`, and `build_loss_evaluator()` (resolves a component's library type once and returns a plain callable closure — the pure layer never resolves a type itself). |
| `core/Numbering.py` | `renumber_network()`: presentation-only D.../J.../J...-P/J...-NN documentation numbering, walked outward from a deterministic source terminal over the parser's analysis graph. Only ever runs when `HVAC_RenumberNetwork` is invoked — normal sync never renumbers. |
| `library/Library.py` | `HVACTypeDef`/`HVACLibrary`/`HVACLibraryRegistry`: type-def loading, per-library match indexes, `select_type`/`matches_type`/`resolve_sticky_type`, geometry-backend dispatch (`build_geometry`, normalized to a `GeometryResult` -- see `library/geometry_result.py`), and loss dispatch (`call_loss`, resolving a type-def's optional flow-dependent `loss_variants` via `validation.resolve_loss_variant`). |
| `library/validation.py` | Declarative property validation (`resolve_params`) and structural constraint checking (`context_violations`) — the same rules back both geometry execution and type matching. `resolve_loss_variant` reuses the same constraint evaluator to pick a flow-dependent loss formula (`loss.variants`) for an already-selected type, independent of type selection itself. |
| `library/library_api.py` | `HVACLibraryAPI` — the geometry interface generator/PartScript authors receive as `context["hvac_api"]`. The class is assembled here from topic mixins: `_api_ports.py` (context/port helpers, trim records), `_api_profiles.py` (frames, sections), `_api_solids.py` (extrusions, sweeps, lofts), `_api_booleans.py` (trims, booleans, topology, finishing), `_api_recipes.py` (HVAC convenience functions, standard fittings); `_api_common.py` holds `HVACProfile`. |
| `library/contexts.py` | The frozen context keys of each call into library code (geometry, loss, friction); tests check core builds and library code reads only these. |
| `library/custom_fitting.py` | Pure fit of a custom fitting onto a node (numpy): port-to-duct matching, rigid placement, trims, tolerance errors. |
| `library/fittings/` | Shared fitting code every library can use through the `shared:` module prefix: one module per fitting family (`elbows`, `transitions`, `offsets`, `taps`, `tees`, `wyes`, `crosses`, `stars`, `terminals`, `inline`, `devices` (silencer, fire damper, access door, flexible connector), `dampers`, `details` (vanes, tap damper, extractor, filter media, coil block as features), `through`, `markers`, `segments`) plus `losses`. Each fitting is a `_layout()` (pure numbers), a `measure_*()` (trims only) and a `build_*()` (shape). |
| `library/loss_tables/` | The SMACNA fitting-loss tables (14-9 to 14-18), one module per table group. Each printed table is a `LossTable`: clamped linear interpolation whose result says when the point was outside the printed range or in a blank cell. Pure Python, no FreeCAD. `HVACLossAPI` reads them directly. |
| `library/loss_api.py` | `HVACLossAPI` — fitting-loss orchestration exposed to library loss modules as `context["loss_api"]`; it converts library context into inputs for the pure loss tables. |
| `utils/hvaclib.py` | `HVACLibraryService`: thin FreeCAD-facing facade over the registry (search paths, active library, segment/junction type resolution), plus misc FreeCAD object/geometry helpers used throughout `core/`. |
| `analysis/friction.py` | Straight-duct friction models (Darcy-Weisbach with Altshul-Tsal or Colebrook, table, whitelisted expression, scaled); every solver asks `SegmentModel.friction_model` through `rate_pa_per_m()`. |

## Analysis layer

`freecad/HVAC/analysis/` is a pure-Python engineering domain package: **nothing
in it may import FreeCAD, `Part`, `pivy`, `core/`, `library/`, or
`utils/hvaclib`** — only `math`, `dataclasses`, `typing`, and `networkx`
(vendored under `HVAC/ext_libs`, loaded the same way `utils/hvaclib.py` does
but without depending on that module). This is what lets
`tests/test_physics.py`/`tests/test_analysis_*.py` run with no FreeCAD stub
of any kind, unlike every other test in the suite.

```
DuctNetwork (FreeCAD)
     |
core/_analysis_adapter.py    reads the document into pure dataclasses,
     |                       resolves library loss formulas into plain callables
     v
analysis/model.py            NetworkModel / NodeModel / SegmentModel / ComponentModel /
                              PortModel / AirState / SizingSettings -- stable string
                              ids (edge_key / node_id) relate everything back to a
                              real FreeCAD object, never a direct reference
     |
analysis/physics.py          pure formulas (areas, velocity, Reynolds, friction,
     |                       sizing-for-velocity/friction-rate/static-regain)
     v
analysis/flow.py             tree/loop check + mass-conservation flow solve
     |
     +-- analysis/pressure.py   velocity/friction/fitting loss + static pressure
     |        |
     |        v
     |   analysis/paths.py      per-terminal FlowPathResult + CriticalPathResult
     |                          (pressure_deficit_pa relative to the critical path)
     |
     +-- analysis/sizing.py     ConstantVelocitySizer / ConstantFrictionRateSizer /
              |                 LocalStaticRegainSizer (today's "StaticRegain" algorithm,
              |                 unchanged in meaning)
              v
         analysis/balancing.py  PressureBalanceCoordinator: iterates a base sizer +
                                 pressure/path re-solves, shrinking the most-upstream
                                 segment unique to whichever terminal's path has the
                                 largest pressure_deficit_pa, until every path is
                                 within tolerance or a segment can't shrink further --
                                 any deficit left over becomes an explicit
                                 BalancingRequirement (junction_id/branch_port/
                                 pressure_deficit_pa/required_k), with no damper
                                 FreeCAD object required to exist
     |
     v
core/AirflowSolver.py / core/DuctSizer.py   map pure results back onto Calc*
                                             properties / SegmentSizeResult.obj
```

A component's own fitting-loss formula is never resolved by `analysis/`
itself: `core/_analysis_adapter.build_loss_evaluator()` resolves the library
type once and returns a plain `Callable[[port_velocities],
Optional[LossEvaluation]]` closure (`ComponentModel.loss_evaluator`) that
`analysis/pressure.py`/`sizing.py` call with nothing but plain floats — see
"Fitting-loss model" below for the `LossEvaluation`/`LossPath` shape that
callable returns. Each component's own loss is still converted to Pa
**using its own reference velocity before being summed** onto a segment —
`SegmentModel` keeps a node's own Primary contribution (`junction_loss_pa`)
and an edge's own Inline-chain contribution (`component_loss_pa`) as two
separate fields (rather than one combined "fitting loss") specifically so
`analysis/paths.py` can report duct/junction/component/terminal loss
separately along a path.

### Fitting-loss model

`analysis/loss.py` is the pure data model a fitting's own loss formula
(`library/loss_api.py`'s `HVACLossAPI`, called from the shared
`library/fittings/losses.py` or a library's own loss module) returns, and the one every consumer
(`analysis/pressure.py`, `analysis/sizing.py`) reads back:

```
LossPath(from_edge_key, to_edge_key, reference_edge_key, loss_coefficient, source=None)
LossEvaluation(paths: list[LossPath], status: LossStatus, warning: str | None)

LossStatus = EXACT | APPROXIMATION | CUSTOM | FALLBACK | UNSUPPORTED
```

The key invariant: **a loss coefficient belongs to a directed flow path
through a fitting, never implicitly to "the outlet"**. `from_edge_key` is
the path's inlet-side edge, `to_edge_key` its outlet-side edge (either may
be `None` only for a 1-port terminal device's open-atmosphere side) —
direction always comes from each port's own
`flow_into_junction`/`flow_into_node`, never from key ordering.
`reference_edge_key` (always equal to `from_edge_key` or `to_edge_key`) is
whose own velocity `loss_coefficient` is referenced to, matching the
convention every SMACNA/ASHRAE table already used. This is what makes a
converging tee representable at all: its two physically distinct
coefficients belong to its two *inlet* legs, exactly the same shape a
diverging tee's two *outlet* legs already had — neither is a special case
of the other, and a true multi-inlet/multi-outlet cross can express one
`LossPath` per inlet/outlet pairing the library method actually supports.

`LossStatus` separates what used to be collapsed into a single `None`:
`UNSUPPORTED` means the library formula found no applicable formula for the
current flow topology (e.g. a true mixed cross); `FALLBACK` means a generic
coefficient was applied as an explicit, visible policy (either
solver-synthesized, via `analysis/pressure.resolve_loss_evaluation()`'s own
`K_DEFAULT`, or type-declared, via `HVACLossAPI.uniform_fallback_loss()`);
`CUSTOM` is a user-supplied override (`core/_custom_loss.py`, `Component.py`'s
`LossCoefficientSource == "Custom"`). `resolve_loss_evaluation()` (in
`analysis/pressure.py`, reused by `analysis/sizing.py`'s
`LocalStaticRegainSizer` for the same estimate during sizing) is the one
place `UNSUPPORTED`/missing-evaluator both turn into an explicit `FALLBACK`
result — never silently applied without a visible status/warning.

**Pressure-reference convention** (`analysis/pressure.py`'s Phase F/G):
static pressure decreases in the flow direction; a node's own
`static_pressure_pa` is its fitting body's shared reference point, taken
*before* any of its legs' own turning/branching loss is subtracted. A
`LossPath`'s Pa contribution is always attributed onto its own
`reference_edge_key`'s segment — already correct at the node level for
both a diverging fitting (loss on outlet legs) and a converging one (loss
on inlet legs). A single port's own static pressure
(`ComponentPortResult.static_pressure_pa`) does depend on which side of its
own path it's on: the `to_edge_key` side (downstream/outlet) is the node's
reference minus that leg's own `pressure_drop_pa`; the `from_edge_key` side
(upstream/inlet) is the node's reference *plus* that leg's own
`pressure_drop_pa` (pressure is higher there, before the fitting absorbs
the loss).

Custom K (`LossCoefficientSource == "Custom"`) is converted to the same
`LossPath`-based evaluation, not a separate outlet-only mechanism:
`core/_custom_loss.custom_loss_applicable_ports()` generalizes "which local
ports get a custom-K slot" off the same single-common-port shape every
library formula already uses (the "many" side gets a slot — every outlet
of a diverging tee, but every *inlet* of a converging tee). Because
`CustomLossCoefficientEdgeKeys` persists real `edge_key` values and those
regenerate on every document reload (`core/Network.py`'s own
`_edge_key_remap`, built by `syncSegments(initial_sync=True)`), the same
old-tag → new-tag carry-forward already used for `AttachedEdgeKey` is
applied to `CustomLossCoefficientEdgeKeys` too (`core/_custom_loss.
remap_persisted_edge_keys()`, called from `syncJunctionComponents` for both
the Primary and every Inline component) — without it, every stored custom K
would look unmatched after a reload and get silently reset to `0.0`.

`DuctNetwork.SizingMethod` has a fourth option, `PressureBalancedStaticRegain`
(`ui/TaskPanel.py`'s Size Ducts panel), which routes through
`PressureBalanceCoordinator` instead of `LocalStaticRegainSizer` directly —
any `BalancingRequirement` the coordinator can't resolve by sizing alone is
surfaced both as a plain warning in the existing Size Ducts warnings box and
as structured data on the result (`DuctSizingResult.balancing_requirements`)
for anything that wants to act on it later (e.g. flagging where a real
damper should go). The coordinator is deliberately written against a
`base_sizer` it doesn't otherwise know about, so a future Equal-Friction or
Constant-Velocity sizing method could reuse the same balancing layer without
changes to `analysis/balancing.py` itself.

### Airflow & sizing flow

`HVAC_CalculateAirflow` and `HVAC_SizeDucts` share the same first step, then diverge:

```
FlowNetwork.solve_flow_components(net_obj)
   adapter: builds a NetworkModel, then analysis/flow.py solves it --
   one FlowComponent per connected sub-network (must be a tree);
   flow magnitude per segment, solved leaf terminals -> balancing terminal
        |
        +----------------------------+-----------------------------+
        v                                                          v
   AirflowSolver                                              DuctSizer
   adapter over analysis/pressure.py's PressureSolver:         adapter over analysis/sizing.py / balancing.py:
   velocity / Reynolds / friction loss, junction/component     picks ConstantVelocitySizer / ConstantFrictionRateSizer /
   fitting loss (via each node's own loss_evaluator             LocalStaticRegainSizer / PressureBalanceCoordinator per
   closure), static pressure propagated outward from the       the network's SizingMethod -- static regain (plain or
   balancing terminal (0 Pa) -- plus per-terminal               pressure-balanced) walks outward from the balancing
   FlowPathResult/CriticalPathResult (analysis/paths.py)        terminal since each section's target depends on its
                                                                 already-solved parent
```

See "Analysis layer" above for what actually happens inside `analysis/flow.py`/`pressure.py`/`sizing.py`/`paths.py`/`balancing.py` -- this section is only about which FreeCAD command triggers which adapter.

`DuctSizer.solve()` only returns a preview; it never writes to segments —
`apply()` is a separate, explicit step so the UI can show the preview and
let the user confirm first.

## End-to-end flow (normal edit → recompute)

1. User edits base routing geometry (a sketch or line-based object) inside a `DuctNetwork`.
2. `DuctNetwork.requestSync()` is scheduled (debounced via a `QTimer`) and calls `_runDeferredSync()`.
3. `DuctNetworkParser` rebuilds its graph from the base geometry and classifies every node/edge (topology, `family_key`, connected-port profiles).
4. `DuctNetwork.syncSegments` builds a match request from that classification and asks the library registry to resolve a type (see next section) — then writes the result onto the segment (`LibraryId`, `TypeId`, `Profile`, etc.) via `updateMetadata()`, a **pure metadata writer** with no selection logic of its own, and `applyTypeSchema()` adds/removes the FreeCAD properties the selected type declares.
5. `DuctNetwork.syncJunctions` writes each junction's own metadata (`NodeKey`, `CenterPoint`, `Degree`, `Topology`, `Family`, ...), then `syncJunctionComponents` creates/updates that junction's **Primary** `DuctComponent` (same sticky type-resolution policy a junction used to run directly), leaves any **Inline** components untouched (never auto-replaced), and calls `DuctJunction.composeComponents()` to write every component's local inlet/outlet ports for this sync — see "Junction component composition" below.
6. FreeCAD recompute calls `DuctSegment.execute()` / `DuctComponent.execute()`, which do an **exact** `resolve_type(LibraryId, TypeId)` lookup and call `HVACLibraryRegistry.build_geometry()` to produce a `GeometryResult` (see "Component geometry & materials" below), applied onto each of the object's own construction layers' `Layer_<id>_Shape`/aggregate `Shape` by the shared `core/_geometry_apply.apply_geometry_result()` helper. `DuctJunction.aggregateConnectionLengths()` then rolls each component's own trim into the junction's `ConnectionLengthsJson` — the one external trim contract `syncSegments`'s next pass consumes to shorten the two real connected segments.
7. Optionally, `HVAC_CalculateAirflow` (`AirflowSolver`) and `HVAC_SizeDucts` (`DuctSizer`) run over the resulting network for pressure-drop and sizing results — see "Airflow & sizing flow" above.

## Junction component composition

For the common case — a junction with just its Primary component — this is
a no-op: the component simply gets the junction's real connected ports
unchanged, identical to how a single fitting worked before `DuctComponent`
existed. It's only interesting once at least one real edge carries its own
**Inline** chain in series with the Primary — which is independent per
edge, not scoped to a simple 2-port node: a tee's branch leg and one of its
run legs can each grow a completely independent chain, evaluated with that
leg's own geometry alone. The invariant is:

```
Each DuctJunction has exactly one Primary component.

Each real junction port/edge may independently have zero or more
Inline components arranged from the Primary component outward.
```

```
composeComponents()
   real inlet port (port_a) -- real outlet port (port_b)
        |
   Pass 1: for each component (Sequence order), work out its own local
           left/right port templates (direction/profile/edge_key -- all
           position-independent) and "peek" its own (trim_left, trim_right)
           by calling build_geometry once with a placeholder position
           (every 2-port geometry backend treats its two given ports as
           coincident and pushes each outward by a trim that depends only
           on its own properties/profile, never on where that shared point
           sits in space)
        |
   Pass 2: derive each component's real shared anchor point from a running
           sum of (previous component's own outward push + this
           component's own outward push) -- the first component's anchor
           is exactly port_a's own real position, so the upstream
           segment's trim is unaffected by how many components exist
        |
   Pass 3: write each component's final LocalPortsJson at its real anchor
```

Each component's `execute()` (run via `touch()` + the next recompute) then
calls `build_geometry` a second time with those final positions to build the
real `Shape`. For a type that declares an independent `connection_lengths`
function (see `docs/type-def-reference.md`), the "peek" step above no
longer builds any geometry at all — `HVACLibraryRegistry.
measure_connection_lengths()` calls that lightweight measurement function
directly, so `build_geometry`/`execute()` only ever runs once per component
per sync for a migrated type. A type with no independent measurement
function declared (not yet migrated) still falls back to peeking via a full
`build_geometry` call, exactly as every type used to — see
`DuctJunction._peekConnectionLengths()`'s own TODO for that migration path.
Either way, `execute()` remains the single source of truth for `Shape`
rather than caching a result across the sync/recompute boundary.

`AirflowSolver`'s Phase E mirrors this: each edge's own Inline chain is
evaluated independently of the Primary and of every other edge's chain —
each component's own loss is evaluated against its own local ports/velocity
and converted to Pa immediately (never summing raw K values across
components that don't share a reference velocity), then the Pa
contributions are summed once onto that one real segment. Per-component
results (`CalcFlowRate`/`CalcVelocity`/`CalcLossCoefficient`/
`CalcPressureDrop`) are stored on each `DuctComponent`. A node with no
Inline chain on any of its edges (still the common case) behaves exactly as
if `DuctComponent` didn't exist at all.

`DuctJunction` has no `Shape` and so can't be picked in the 3D view — its
own `FlowBoundary`/`DesignFlowRate` (the terminal solve target
`FlowNetwork`/`AirflowSolver` read directly off the junction —
`FlowBoundary` is one of `"Auto"` (solved by mass balance, the balancing
terminal), `"Fixed"` (use `DesignFlowRate` as-is, `0` included), or
`"Closed"` (sealed, always `0` flow regardless of `DesignFlowRate`); see
`analysis/flow.py`) are therefore also mirrored onto its Primary
`DuctComponent`'s own copies of these properties, via a two-way `onChanged`
hook on both `Junction.py` and `Component.py` (each guarded by its own
`_mirroring_design_flow_rate`/`_mirroring_flow_boundary` flag so the two
handlers don't bounce an edit back and forth). The mirror is editable only
on a Primary component whose parent is an `"end"` (terminal) node — hidden
(editor mode 2) everywhere else, and `DesignFlowRate` further only when
`FlowBoundary == "Fixed"` — and is also pulled down from the parent every
sync (`DuctComponent.execute()`'s `_syncFlowBoundary`), so a document
reopen or a topology change always leaves it consistent, not just a live
edit. A library type may prescribe (and optionally lock) a terminal's
`FlowBoundary` via its own type-def `flow_boundary`/`flow_boundary_locked`
fields (see `docs/type-def-reference.md`) — a locked type (e.g. a
duct-closure/end-cap fitting) has its value re-asserted by
`_syncFlowBoundary` every sync, tracked by the Primary's own
`FlowBoundaryLocked` bookkeeping property, which the terminal popup
(`ui/Observer.py`'s `FlowBoundaryDialog`) reads to show a locked terminal
read-only without ever branching on the type's id/family itself.

## Component geometry & materials

Every `DuctSegment`/`DuctComponent` is one physical HVAC element, but that
element can be made of any number of physical **construction layers** -- a
bare sheet-metal wall, a wall plus insulation, or a casing plus an acoustic
fill plus a perforated liner. How many layers a type has, what each is
called, and how they're built is entirely **library-defined data** (a
type-def's own `"construction"` block -- see
`docs/type-def-reference.md`'s "Construction layers" section); core
only owns the standardized semantic **role** vocabulary
(`library/construction.py`'s `LayerRole`: `flow_surface`,
`structural_shell`, `thermal_insulation`, `acoustic_absorber`,
`acoustic_liner`, `vapor_barrier`, `outer_jacket`, `fire_protection`) and
the generic machinery that composes/queries whatever layers a type
declares. Downstream code must only ever branch on a layer's roles, never
on its library-chosen id.

```
library/construction.py     LayerRole vocabulary + ConstructionLayerDef
                             (a type-def's own declared layer: id, roles,
                             default_material_role/uuid, thickness_property)
                             + LayerGeometry (one layer's built shape+roles)
        |
library/geometry_result.py  GeometryResult.layers: dict[layer_id, LayerGeometry]
        |
library/Library.py          HVACTypeDef.construction: list[ConstructionLayerDef],
                             parsed from the type-def's "construction" JSON;
                             build_geometry() stamps each returned layer's
                             roles from there after normalize()
        |
library/library_api.py      HVACLibraryAPI profiles, offsets, sweeps, lofts,
                             and boolean operations -- the shared primitives
                             used by backends to construct each declared
                             layer without importing Part directly
        |
core/_construction_schema.py   apply_construction_schema() -- adds/removes
                                each layer's own Layer_<id>_Shape/
                                Layer_<id>_Material FreeCAD properties to
                                match the selected type, mirroring
                                core/_type_schema.py's dynamic-property
                                pattern; writes the declared order onto
                                obj.ConstructionLayerIds
        |
core/_geometry_apply.py     writes each declared layer's own Layer_<id>_Shape
                             from GeometryResult.layers, then derives the
                             object's own Shape as Part.makeCompound() of
                             every non-null layer shape, in
                             ConstructionLayerIds order
        |
core/Construction.py        the semantic query API: Construction(obj)
                             .layers_with_role(role) / .flow_surface() /
                             .structural_layers() / .thermal_layers() /
                             .acoustic_layers() / .hydraulic_roughness() /
                             .acoustic_impedance() / .overall_u_value() --
                             reachable off a segment/component's own
                             getConstruction()
```

`HVACLibraryRegistry.build_geometry()` normalizes whatever a geometry
backend returned into a `GeometryResult`:

```
GeometryResult
   layers: dict[str, LayerGeometry]  -- arbitrary library-defined layer ids;
               no required keys or count. Each LayerGeometry carries its own
               .shape (None if that layer has no geometry this call) and
               .roles (stamped on by build_geometry() from the type-def's
               own "construction" block -- empty for a not-yet-migrated
               type with no construction block at all).
   connection_lengths / computed_properties / start_trim_plane_json / ...
               -- the same non-shape outputs generators have always returned
   property_choices: dict[str, list[str]] -- drop-downs narrowed to the
               choices that suit this geometry (core/_geometry_apply.
               apply_property_choices); unnamed drop-downs offer every choice
```

Generator/PartScript/static-descriptor authors never import
`GeometryResult`/`LayerGeometry` directly. Geometry code uses
`HVACLibraryAPI`, while loss modules use `HVACLossAPI`; both keep returning
plain values instead of internal library classes. Geometry backends return either the
legacy `{"shape": ...}` form (a type with just one, roleless implicit
layer, id `"shape"`), or `{"layers": {"<id>": {"shape": ...}, ...}}` for a
type with more than one declared layer. `normalize()` accepts both.

`core/_geometry_apply.apply_geometry_result()` is the one place
`DuctSegment.execute()`/`DuctComponent.execute()` share: it writes each of
`obj.ConstructionLayerIds`' own `Layer_<id>_Shape`
(`Part::PropertyPartShape`, read-only in the property editor) from
`result.layers`, then derives the object's own `Shape` as
`Part.makeCompound()` of whichever layers actually have a shape, in that
same declared order. `Shape` is only ever this derived aggregate --
nothing downstream recovers a layer's meaning by inspecting its
faces/solids; that's what `core/Construction.py`'s role queries are for.

**FreeCAD-HVAC uses FreeCAD's native `Materials::PropertyMaterial` and
`.FCMat` database. HVAC supplies only domain-specific material cards;
FreeCAD's Material subsystem owns material storage, selection, physical
properties and appearance.** Each construction layer's own
`Layer_<id>_Material` (`Materials::PropertyMaterial`) holds a native
FreeCAD material value directly -- not a link to a per-object document
object -- so the same database material (built-in, this addon's own, from
another addon, or user-defined) can be assigned to any number of duct
objects without duplication, exactly like assigning a material anywhere
else in FreeCAD. There are no HVAC-specific color/transparency properties:
appearance always comes from the assigned material's own
`AppearanceModels`. Every `Layer_<id>_Material` is added with
`Prop_NoRecompute` -- picking a material never changes the object's own
geometry, only its ViewProvider's rendered appearance, so it shouldn't
force a recompute.

`freecad/HVAC/Resources/Materials/` ships HVAC-domain `.FCMat` cards for
metal casing, rigid nonmetallic casing, flexible duct, and insulation.
They reuse FreeCAD's standard `Father`, `Density`, `Thermal`, and
`BasicRendering` models. Every card also uses the addon's small native
`Hydraulic` material model, declared under
`Resources/Models/`, so effective absolute roughness is a native,
unit-aware material property. Every insulation card's
`BasicRendering.Transparency` is `0.6` so an inner layer stays visible
through an outer wrap while modeling; metal casing cards are opaque
(`0.0`).
`utils/materials.register_material_resources()` (called once from
`init_gui.py`) registers that folder with FreeCAD's Material subsystem the
same way FreeCAD's own Supplemental-Materials addon does (a `ModuleDir` key
and a `ModuleModelDir` key under
`.../Mod/Material/Resources/Modules/FreeCAD-HVAC`), so these cards and the
Hydraulic model show up in the normal material browser/editor next to every
other material FreeCAD knows about -- there is no separate HVAC material
dropdown.
The read-only helpers in `utils/materials.py` are the only way core/ code
reads a `Materials::PropertyMaterial` value: physical-value helpers serve
roughness and future quantity calculations (volume x density -> mass, from a
layer's own `Layer_<id>_Shape` + `Layer_<id>_Material`), while the
appearance helper builds the plain `FreeCAD.Material()` struct
`ViewObject.ShapeAppearance` actually consumes from the native material's
own appearance. That conversion is one-way and read-only; nothing is
written back onto the material or cached onto the HVAC object itself.
Construction parameters
like a layer's own thickness stay separate, plain type properties -- never
part of material identity, so the same Glass Wool material works at any
thickness (a `ConstructionLayerDef.thickness_property`, if declared, names
which one -- purely informational metadata, since a layer's generated
Shape is always the source of truth for its own volume).

Airflow friction follows the same role-based construction contract.
`core/_analysis_adapter.py` asks each segment's own `Construction` for the
`flow_surface()` layer and uses its material's effective
`HydraulicRoughness`; the network's `DefaultRoughness` is used only when
that construction has no usable value. Primary and inline components are
resolved independently and receive their own construction and roughness in
the library loss context. Components have no fictitious straight length,
so their roughness only affects a loss formula that explicitly uses it.
Shipped metal cards declare the native property directly; cards without
that property use the network fallback rather than a name- or UUID-based
implicit material value.

`core/_component_appearance.py` renders every layer's own material. Layers
and features switched off on the network (`ShowLayer_<Role>`,
`ShowFeatures`, a feature's own visible parameter) are left out of `Shape`
(`displayed_parts` / `refresh_display_shape`; each layer keeps its own
`Layer_<id>_Shape`), because FreeCAD draws a selected object with a single
transparency and a transparent layer made it vanish. Since
`Shape` is always the compound of the shown parts in `ConstructionLayerIds` order,
`len(Layer_<id>_Shape.Faces)` for each layer in that same order tells the
ViewProvider exactly where each layer's own faces fall in that compound
(an exact count derived from the very shapes the compound was built from,
never a hardcoded/guessed split), so it can assign a per-face
`ViewObject.ShapeAppearance` array built from each layer's own converted
material appearance -- no custom Coin scene graph needed. It guards
against a real FreeCAD re-entrancy quirk (querying a material's own
appearance can synchronously re-fire `updateData()` for that same property
before the original call returns, which would otherwise recurse until the
interpreter's stack limit crashes it) -- see the module's own `_rendering`
guard and its comment before touching that function.

FreeCAD's generic property editor has no interactive picker for
`Materials::PropertyMaterial` on an arbitrary object (confirmed: no shipped
FreeCAD workbench relies on inline editing for it either -- CAM's own
"Assign Material" feature builds its own dialog the same way). Materials are
assigned via one command, `HVAC_EditMaterial` (`ui/Command.py`), which opens
`ui/TaskPanel.py:TaskPanelEditMaterial` -- one panel with a
`MaterialPickerRow` per construction layer id present on the selection
(the union across a mixed selection of different types), so every layer is
edited together rather than through a separate command per layer. Each
row's "Browse..." button opens a `MaterialPickerDialog` built from
FreeCAD's own `MatGui::MaterialTreeWidget` -- the same native browser
widget the Material workbench and CAM use. A row only reports a material
back to `Network.applyMaterialSelection()` if the user actually picked one
(`MaterialPickerRow.touched`) -- leaving a row alone (e.g. only changing
one layer across a selection with mixed materials on another layer) never
clobbers the other layers' properties with whatever the first selected
object happened to show. `MatGui` (the Gui module that implements the tree
widget) is imported once, at `ui/TaskPanel.py` module scope, since it
isn't loaded automatically just by activating the HVAC workbench.

`DuctNetwork` carries the same picker (embedded in
`TaskPanelNetworkTypeDefaults`, the "Network Defaults" command) for one
`DefaultMaterial_<Role>` property per standardized `LayerRole` (not per
library-defined layer id -- roles are the fixed, small vocabulary core
owns). Fresh networks seed flow surfaces and structural shells with
Galvanised Steel, thermal insulation with closed-cell Nitrile Rubber,
acoustic absorbers with open-cell Nitrile Rubber, acoustic liners with
Galvanized Steel - Perforated, and vapor barriers/outer jackets with
Aluminium. Fire protection remains project-specific and unset.
`core/_construction_schema.apply_default_layer_materials()` (called from
`DuctSegment.applyTypeSchema()`/`DuctComponent.applyTypeSchema()` every
time a type's construction schema is (re)established, not just once at
object creation, since which layers exist depends on a type that isn't
known yet when a segment/component is first created) fills in each layer's
material whenever it doesn't already have one: the layer's own
`ConstructionLayerDef.default_material_uuid`, else the network's
`DefaultMaterial_<Role>` for the layer's own `default_material_role` (or
its first declared role, if the layer doesn't specify one explicitly) --
never overwrites a manual choice or a value restored from an existing
document. `DuctNetwork.resetObjectsToNetworkDefaults()` (the "Reset to
Defaults" command) is the opposite convention, via
`core/_construction_schema.reset_layer_materials_to_network_defaults()` --
like it already does for `LibraryId`/`TypeId`, an explicit reset always
re-applies the network's *current* default materials, discarding whatever
material each layer already had.

`DuctJunction` itself stays geometry-free: it never gets
`ConstructionLayerIds`/`Layer_<id>_Shape`/materials of its own, only its
`DuctComponent` children do.

## Type selection subsystem

This is the part most likely to need touching when adding a new fitting
type or debugging "why did it pick that geometry." Full detail:
[`docs/library-guide.md`](docs/library-guide.md) §"Type selection
(automatic matching)".

```
classifier output (topology, family_key, profile)
        |
HVACTypeMatchRequest
        |
HVACLibraryRegistry.resolve_sticky_type(library_id, current_type_id, request)
        |-- current TypeId still a valid real model? -> keep it (sticky)
        |-- else -> select_type(): best model, else best placeholder
        v
LibraryId / TypeId written onto the object (a segment, or a junction's
                                             Primary DuctComponent)
        v
execute() -> resolve_type() (exact lookup, no matching) -> build_geometry()
```

For a junction this whole flow runs against its **Primary** `DuctComponent`
only (`DuctNetwork.syncJunctionComponents`) — a junction itself is never a
`resolve_sticky_type`/`select_type` target any more. **Inline** components
are never reachable through this automatic flow at all: their type-defs
declare `selection: {kind: "inline"}`, which excludes them from both the
model and placeholder match indexes entirely (`HVACLibrary.
_rebuild_match_index`), so they're only reachable via `HVACLibrary.
list_inline_types()` (the "Edit Inline Components" UI action's Add section).

Key rules (all enforced in `freecad/HVAC/library/Library.py`):
- A type-def opts in via `family` (classifier keys it supports), `profiles`
  (`"Generic"` = wildcard), and `selection: {kind, priority}`.
- `kind: "model"` beats `kind: "placeholder"`; exact profile beats
  `"Generic"` profile; `priority` only breaks ties inside the same tier.
  `kind: "inline"` never participates in automatic matching at all.
- A manually-picked, still-valid `model` type is **sticky** — it survives
  resync even if a higher-priority alternative exists. A `placeholder` is
  **never** sticky, so it can auto-upgrade once a real model qualifies.
- Adding a new fitting = a new JSON type-def + geometry backend. No new
  `if/elif` in `Network.py`/`Junction.py`/`Component.py`/`hvaclib.py`.

## Where to look for more

- **How to write code here** (test policy, naming convention, layering
  rules, SPDX header) → [`AGENTS.md`](AGENTS.md).
- **User-facing feature overview, design goals, status** → [`README.md`](README.md).
- **Writing a library, type selection** → [`docs/library-guide.md`](docs/library-guide.md).
- **Type-def JSON keys** → [`docs/type-def-reference.md`](docs/type-def-reference.md).
- **Naming convention** → [`freecad/HVAC/libraries/README.md`](freecad/HVAC/libraries/README.md).
- **How the parser classifies topology/family** → [`freecad/HVAC/core/TOPOLOGY_CLASSIFICATION.md`](freecad/HVAC/core/TOPOLOGY_CLASSIFICATION.md).
- **Choosing a geometry backend (PartScript / static / generator)** → [`freecad/HVAC/libraries/samples/README.md`](freecad/HVAC/libraries/samples/README.md).
- **Public geometry and loss APIs, context keys** → [`docs/library-api.md`](docs/library-api.md) (generated from `library_api.py`, `loss_api.py`, `contexts.py`).
