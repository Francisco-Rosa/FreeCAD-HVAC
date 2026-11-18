# Roadmap: generic library completeness and API freeze

Staged implementation plan for the work listed in the November 2026 planning
request. The project is in alpha, so breaking changes to type ids, property
names and library JSON are acceptable until Stage 11 (API freeze).

Rules in [`AGENTS.md`](AGENTS.md) apply to every stage: unit tests for
data/dispatch/loss code, none for shape construction; the
`topology_family_sub_classification` naming convention; library code talks
only to `HVACLibraryAPI` / `HVACLossAPI`.

## 0. Progress

| Stage | State | Notes |
|---|---|---|
| 0 | Done | Ovals accept any width/height. One trim naming scheme. Unknown property keys are load errors. Dead per-port trim properties on star fittings now work. |
| 1 | Mostly done | Shared `library/fittings/` package behind the `shared:` module prefix; both libraries are type-defs only (smacna keeps `features.py` and its PartScripts). All shared fittings are hollow and layered, with flanges as data. `api.build_fitting` / `measure_fitting` / `build_layered_fitting` added. `tools/geometry_smoke.py` added. Done (13 November 2026, owner dropped the guard): `library_api.py` assembles `HVACLibraryAPI` from `_api_ports`, `_api_profiles`, `_api_solids`, `_api_booleans`, `_api_recipes` (`_api_common` holds `HVACProfile`); the guard test now checks the methods are on the class, wherever written. Smoke run unchanged (333). |
| 2 | Done | Every table of the reference is digitised in `library/loss_tables/` as a `LossTable` (clamped interpolation; a lookup reports when it was outside the printed range or touched a blank cell): 14-9, 14-10 A to K with Notes 1 to 5, 14-11 A to J, 14-12 A to C, 14-13 A to I, 14-14 A to Z, 14-15 A to I, 14-16 A to J, 14-17 A/B, 14-18 A to L. Each was transcribed from a fresh read of its page and spot-tested; an inventory test fails if a printed fitting is missing. `smacna_loss.py` is now a thin layer over these tables. New `HVACLossAPI` entry points with shared loss functions (`shared:losses`): `entry_loss`, `exit_loss`, `screen_loss`, `damper_loss`, `obstruction_loss`; they return `APPROXIMATION` with a reason when a lookup leaves the printed table. Defects fixed on the way: flow-ratio axis on 14-13 B and 14-14 A, elbow turn-angle factor, Reynolds correction end point, two missing columns of 14-10 D. **Left for the fitting stages (4 to 7), where the fittings that need them are built:** variant arguments on `elbow_loss` / `transition_loss` / `branch_loss` / `wye_loss` (gored and vaned elbows, conical taps, rectangular-main tees, fan transitions), and status flags on those four older methods, which still report `EXACT` even when clamped. Not digitised: the charts (Fig. 14-3 roughness correction, 14-4 flex duct, 14-5 density) and the nominal-size tables 14-2 to 14-5, of which only the equivalent-diameter equation is implemented. Suspected misprints in the source are kept as printed and listed in the module docstrings. |
| 3 | Done except the editing table | `"per_port": true` properties: one value per connected port for any port count, stored as a list plus a hidden edge-key list, matched by key, kept in step on every sync and remapped on reload (`core/_port_properties.py`, `validation.PortValues`). `api.port_param()` reads per-port and plain properties alike; `api.port_roles()` names ports by role for 1 to n ports. Generic branch, cross and multiport types in both libraries now use one per-port `TrimLength` (and smacna a per-port `ShowFlange`) instead of lettered properties, so none is capped at four ports. Checked on a real FreeCAD object, including save and reload. **Open:** the per-port table in the Edit Type task panel; until then the values are edited as a plain list in the property editor, in port order, with no indication of which port is which. |
| 4 | Partly done | Done: **tee/tap attachment (item 1).** A branch whose axis passes clear of the run is face-mounted: a collar on the run face it passes over, then a 90 degree elbow into the branch direction (`taps.face_tap_layout`). All seven tap and tee types share it through an `Attachment` property (`Auto`, `Side`, `Face`) and `ElbowRadius`. `Auto` picks from where the branch is drawn; a branch crossing the run edge is an error that says how far to move it. Top versus bottom is not a choice: it follows from which side of the run the branch is on. Done: **90 degree cross (item 4)**, `cross_tee_straight`. Done: **double wye (item 5)**, `cross_double_wye_radius` (default) and `cross_double_wye_mitered`: a straight trunk with two inclined branches, each leaving through its own bend; valid in FreeCAD for 30, 45 and 60 degree branches on every profile. `cross_generic` now only takes irregular crosses. Added on the way: `App::PropertyEnumeration` type-def properties, with choices from `validation.enum`. Smoke run: 25 face-mounted cases and 4 cross cases valid. **Open:** the classifier value `branch_eccentricity_ratio` was not needed (the fitting measures the offset itself) and is not added; Done (decisions 10 to 13): **lateral tees with a bend (item 2)**, `branch_lateral_tee_radius` (default) and `branch_lateral_tee_mitered`: full straight run, branch joining through the double wye's branch bend, loss through `branch_loss`; `branch_lateral_tee_generic` stays as the plain-stub fallback. Valid in FreeCAD at 30, 45 and 60 degrees on every profile, with and without a wall. Done: **wyes on a bullhead tee (item 3)**: `branch_wye_mitered` / `branch_wye_radius` list `branch.tee.bullhead` (manual only) with a `common_leg: branch` constraint, at priorities 18 / 17, below every tee type. The wye generator now takes the leg square to two in-line legs as the common one, so it can build a tee-shaped node at all. **Default wye changed:** automatic selection now picks `branch_wye_mitered` for `branch.wye`, because the radius wye fails to build hollow on round and rectangular ducts (it did before too; see below); the radius wye stays a manual choice. Bullhead geometry: valid for oval and rectangular; a hollow round bullhead fails for both wye types. Rectangular laterals and double wyes came out with the same volume for the radius and the mitered bend: the default one-size bend sat inside the run. Fixed 13 November 2026 (owner: increase the default radius): with no `BranchRadius`, `crosses._branch_bend_radius` picks the radius whose branch-side end lies 1.25 times the run surface's distance out along the branch (at least the branch size); radius and mitered builds now differ and the fittings are longer (run trims about 450 mm instead of 250 on the smoke nodes).  loss wiring (7): done for face-mounted branches only (`branch_loss` detects them; a round diverging one reads 14-14 E, "90 degree tee with 90 degree elbow", every other case is the plain tee plus the branch elbow, flagged `APPROXIMATION`); the cross keeps the decomposed `manifold_loss` (no SMACNA cross table). Done (14 November 2026): the wye types offered on a bullhead tee route `common_leg: branch` to the bullhead loss like the tee types; the three lateral tee types have `Attachment` / `ElbowRadius` and build face-mounted (collar plus 90 degree elbow into the inclined branch, the shared `taps.face_tap_layout`) when the branch passes over the run; their loss is the plain lateral loss plus the branch elbow, since 14-14 E only describes a square branch (now used only within 5 degrees of square). |
| 5 | Mostly done | Done: **offsets and transitions separated (item 1).** Offsets (`through_offset_angled` / `_mitered` / `_radiussed`, SMACNA offset types 1 to 3) have their own module (`fittings/offsets.py`) and properties (`OffsetLength`, `OffsetRadius`); `offset_loss` reads them. Transitions are now `through_transition_concentric` / `_eccentric` / `_offset`, chosen by the classifier's `alignment`; concentric is the default when alignment is unknown (mixed profiles, no flow direction). The three old `through_transition_angled/mitered/radiussed` types are gone. All three transitions are the same straight loft and the same loss; what differs is only which one a node gets. Labels were not checked against the SMACNA Duct Construction Standards (not in `reference/`). Done: **obstruction (item 3)**, `through_obstruction_generic`, an inline round bar across the duct with `ObstructionDiameter` and `OffsetFromCentre`, loss from 14-18 H. Done: **VAV box (item 4)**: `through_vav_generic` is now a closed rectangular casing (`BoxLength/Width/Height`) with an inlet and an outlet collar (`CollarLength`) in the section of the duct each meets; its loss is the user's K or, with `LossMode` set to `Fixed pressure drop`, a `PressureDrop` in Pa (added in Stage 6). Done: **damper types (item 5)**: `DamperType` (`Coefficient`, `Butterfly`, `Butterfly airfoil`, `Gate`, `Parallel blade`, `Opposed blade`) with `BladeAngle`, `GateOpening`, `BladeCount`; `Coefficient` keeps the user's K, the others read 14-18 A to G at the current position. The damper body is still a plain sleeve; blades are not modelled. Done (Stage 7 session): a radiussed offset reduces a radius that does not fit to the largest that does, and only fails (saying how) when even the smallest workable radius, half the duct size, does not fit; and `transition_loss` now reads 14-11 E for any rectangular expansion with one pair of sides straight, which is the shape the eccentric table describes, whichever transition type the node has. Done: **fitting-derived values (2)**, design 6.1: `IncludedAngle`, `BodyLength`, `OffsetAngle`, `ActualRadius` as read-only properties, from the helpers the losses use. |
| 6 | Mostly done | All in `builtin_basic`; every new type is a manual choice (an end node only ever classifies as `end.terminal`). Done: **common terminal body (item 1).** Every terminal is laid out as lip, body, neck from the node back to the duct (`fittings/terminals.py`), and every `end` type has `TrimNeck` except the end cap and the marker. Done: **entries and exits (item 2)**: `end_entry_plain`, `end_entry_bellmouth`, `end_entry_conical`, `end_hood_intake`, `end_hood_tapered`, `end_exit_plain`, `end_exit_conical` (round), `end_exit_pyramidal` (rectangular, `DiffuserType` `Pyramidal` or `Plane`), `end_hood_exhaust`. Each reads its own table of 14-15 / 14-16 through a loss function that fixes the shape, and takes `ScreenFreeArea`. Done: **air terminals (item 3)**: `end_diffuser_square`, `end_diffuser_round`, `end_diffuser_slot` (a boot from the duct to the face), `end_grille_generic`, `end_register_generic` (a framed opening; the register adds `DamperLossCoefficient`). Their loss is K at the neck or, with `LossMode` set to `Fixed pressure drop`, a `PressureDrop` in Pa (`HVACLossAPI.fixed_pressure_drop_loss`, which turns the drop into the K that gives it at the present velocity). Done: **AHU (item 4)**, `end_ahu_generic`: a closed casing behind the node with one collar, `ConnectionOffsetY/Z` to move the connection on the face. Done: **plenum (item 5)**: `through_`, `branch_`, `cross_` and `multiport_plenum_generic`, one builder (`fittings/boxes.py`): a closed box (`BoxLength/Width/Height`, `CentreOffsetX/Y/Z`), each duct leaving through the face its axis crosses, with a per-port `TrimLength` collar; a duct that misses the box or overhangs its face is an error that says by how much. Loss `HVACLossAPI.plenum_loss`: one path per inlet/outlet pair, exit into the box plus entry out of it, `APPROXIMATION`, so mixed multi-inlet / multi-outlet nodes have an answer. The box lines up with its largest duct. Added on the way: `api.make_split_circular_wire`, so a round section lofts to a rectangular one without twisting. Smoke run: all 54 new terminal and AHU builds valid; 24 of 44 plenum builds valid, the other 20 being test nodes whose ducts cross a corner of the default box (see below). Done (Stage 7 session): **AHU fan connection.** `end_ahu_generic` has `FanConnection` (`None`, five fan-outlet transitions 14-11 F to J, `Discharge into casing` 14-16 I), `FanOutletWidth` / `FanOutletHeight`, `TransitionAngle`, `FanWheel`; `HVACLossAPI.fan_connection_loss` reads the table at the fan outlet's velocity and refers it to the duct's, and the shared `loss_ahu` adds it to the unit's own K or pressure drop (`HVACLossAPI.sum_losses`). Supply connections only; 14-16 G and H (a diffuser on a fan with no duct) do not apply to a duct-connected unit and are not wired. Done (13 November 2026): hoods flare by `HoodAngle` under a conical roof. Done (13 November 2026): `end_entry_plain` takes an optional mounting flange (`WallFlangeWidth`, `WallFlangeThickness`), a ring plate flush with the opening outside the duct wall, fused into the structural layer. **Open:** (fixed 13 November 2026: `make_oval_wire` now starts at the rectangle's first corner and winds the same way, and a round face lofted to an oval duct is split at the oval's corners, so oval lofts no longer twist; builtin smoke run unchanged in status); nothing was added to the `smacna` library (Stage 7). |
| 6a | Done | **The manual type list follows the flow.** The Change Type list now passes the node's `flow_class` / `qualifiers` / `derived_values` to `list_types()`, so type constraints filter it the way they already filtered automatic selection: only the transition that fits how the two ducts line up is offered (concentric, eccentric or offset), entries only where air comes in and exits only where it leaves. The classifier gained `flow_class` `entry` / `exit` for end nodes and `diverging` / `converging` for cross and multiport nodes (branch nodes had it already). The entry, exit and hood types declare their direction; no shipped branch or cross type is one-directional yet (their losses switch by variant instead), but a type-def can now say so with a `flow_class` constraint. With no flow direction on the base geometry nothing is filtered. |
| 7 | Started (elbows only) | Done: **elbow constructions.** `HVACLossAPI.elbow_loss` now reads `loss_tables.elbows` directly and takes `ElbowConstruction`: `smooth` (14-10 A, F; G with `SplitterVanes` 1 to 3), `gored` (14-10 B, `NumberOfCuts` + 1 pieces), `mitered` (14-10 C, D), `turning_vanes` (14-10 H, `VaneDesign`). It reports `APPROXIMATION` with the reason when a lookup leaves the printed table (this closes the status-flag item of Stage 2 for elbows), and takes W as the section dimension in the plane of the bend instead of always the duct's `Width`. Shared loss functions `loss_elbow_mitered` and `loss_elbow_vaned`. `builtin_basic/through_elbow_mitered` used the smooth-elbow table by mistake and now uses the gored / mitered ones. New in `smacna`: `through_elbow_mitered` (gored or mitered, any profile), `through_elbow_vaned` (rectangular, 90 degrees), and `SplitterVanes` on `through_elbow_rectangular`. Vanes are loss-only, none is drawn. Smoke run: all 9 builds of the two new types valid. Done: (a) unit tests for every `elbow_loss` branch and the two new loss functions (`tests/test_loss_api_elbows.py`). Done: (b) `transition_loss`, `branch_loss` and `wye_loss` read `loss_tables` directly and report `APPROXIMATION` with the reason. `transition_loss`: round 14-11 A / 14-12 A; rectangular 14-11 B, or 14-11 E when only one pair of sides diverges, at the major angle; round-to-rectangular through the 14-11 C/D angle; oval as a rectangle (approximation, it used to be `UNSUPPORTED`); a `TransitionLength` of 0 now means the geometry's default length instead of an abrupt change. `branch_loss`: rectangular-main tees read 14-14 Q / T / V and 14-13 D / C (the latter only at their printed proportions), with a `BranchStyle` variant (`straight`, `conical` 14-14 B/C/V, `45_entry` 14-14 N / 14-13 F, `damper` 14-14 R, `45_entry_damper` 14-14 P, `extractor` 14-14 S); every other tee reads the round tables, an approximation when the ducts are not round. Shared loss functions `loss_tee_conical` (now on `branch_tap_saddle`) and `loss_tee_45_entry` (on `branch_tap_shoe`). `wye_loss`: a symmetric wye (equal legs, equal angles, areas adding up to the common duct's) reads 14-14 Y / 14-13 I. **Bug fixed:** `branch_loss` and `manifold_loss` measured the branch angle from the straight leg instead of the common one, i.e. 180 degrees minus the real angle, so every lateral and wye-like branch read the 90 degree table. Tests: `tests/test_loss_api_branches.py` and the transition tests in `tests/test_loss_api.py`. Done: (f) loss coverage matrix in `libraries/README.md`, generated by `tools/loss_coverage.py --write`; `tests/test_loss_coverage.py` fails when a selectable type has no loss or the matrix is stale. It showed the seven tap and tee types had no bullhead variant (a bullhead tee got the ordinary tee loss with an arbitrary straight leg); they now route `common_leg: branch` to the bullhead loss. Done: (e) `smacna_loss.py` is deleted; `HVACLossAPI` reads `loss_tables` everywhere (the round branch conversion it used for manifolds is now `HVACLossAPI._round_branch_zetas`). **Done (13 November 2026, builtin_basic as the reference): (d) the Stage 4 to 6 types ported to `smacna` (46 types, same ids and geometry; 0.8 mm sheet `Thickness`, `InsulationThickness`, casing + insulation, the shared `transverse_flange` feature with per-role `ShowFlange*`), including refreshed damper, VAV and generic terminals; `smacna/through_transition_generic` retired for the three transitions; `branch_tee_generic` lowered to a fallback (priority 12). (c) three manual-only rectangular branch types: `branch_tap_straight_damper` (14-14 R), `branch_tap_shoe_damper` (14-14 P), `branch_tap_extractor` (14-14 S), with `loss_tee_damper` / `loss_tee_45_entry_damper` / `loss_tee_extractor` (damper and extractor are loss-only). Smoke run of every smacna type except `branch_wye_radius`: all failures are the known builtin ones (plenum test nodes against the default box, the steep radiussed offset, the tall oval mitered shoe, the hollow round bullhead wye). Done: (g) flanges as construction features (design 6.2). |
| 8 | Started | Done: **size changes only at reducers (item 1).** `analysis/sizing.py` groups segments into sizing sections (`sizing_sections`): merged across bends, across the collinear run pair of a branch or cross node, and across a through node whose `AllowSizeChange` is off; never across a profile change. Every section takes the size of its largest-flow member (`apply_sizing_sections`, run at the end of every sizer); a member whose own flow needs at most 1/1.25 of the shared area is reported as a `ReducerSuggestion`, shown in the Size Ducts warnings as advice to add a reducer at its upstream end. Network property `SizeChangePolicy` (`AtReducers`, the default, or `EverySegment`, the old behaviour); junction property `AllowSizeChange` (through nodes only). `_analysis_adapter` passes each node's family and run edge pairs (from the junction analysis' collinear pairs). Static regain: each segment is still sized against its own upstream velocity, then the section takes its upstream end's size, so regain only matters at section boundaries; this is the simple reading of the plan, not a regain solve per section. Sections win over balancing (owner, 14 November 2026): `PressureBalanceCoordinator` shrinks a whole sizing section at a time, never one member, and a section that also carries the critical path is not shrunk but reported as a balancing requirement; it also passes on the base sizer's sections and reducer advice, which it used to drop. Tests: `tests/test_analysis_sizing_sections.py`. Done: **custom friction (item 2).** `analysis/friction.py`: friction models with `rate_pa_per_m(flow, area, Dh, roughness, density, viscosity)`: `DarcyWeisbach` (Altshul-Tsal, the default, or Colebrook), `TableFriction` (CSV rows of diameter, velocity or flow, Pa/m; log-log interpolation and end-segment extrapolation), `ExpressionFriction` (formula in Q, V, Dh, A, eps, rho, nu, Re, compiled from `ast` by a whitelist walker, never `eval`), `ScaledFriction`. `SegmentModel.friction_model` is used by the pressure solver, all three sizing solvers (the bisections included), the section resize and the balancing coordinator. Network properties `FrictionModel`, `FrictionTableFile`, `FrictionExpression`; a bad table or expression stops the solve with a message. Segment type-def key `friction` (factory, wraps the network model); shipped `builtin_basic/circular_flex` (manual only) with `CompressionPercent` and the SMACNA Fig. 14-4 correction, read off the printed chart (log axis). Fig. 14-5 (air density) is not a multiplier: the Darcy-Weisbach models already use `AirDensity` / `AirKinematicViscosity`. Tests: `tests/test_analysis_friction.py`, `tests/test_friction_wiring.py`. Not done: no UI for picking the CSV beyond the property editor; `circular_flex` not smoke-built in FreeCAD (same generator as `circular_generic`). |
| 9 | Done, owner checked 13 and 17 November | Done, not tried in the GUI: **layer visibility (item 2).** `DuctNetwork` has `ShowLayer_<Role>` for every layer role and `ShowFeatures` (group `HVAC Display`, `Prop_NoRecompute`); `_component_appearance` draws a layer whose roles are all hidden, and every feature when `ShowFeatures` is off, fully transparent (they stay pickable, as decision 7 accepted); changing one re-renders the network's segments and components at once (`DuctNetwork.refreshAppearance`). Owner (14 November 2026): the switches are out of place in Network Defaults, so they were removed there. `HVAC_LayerVisibility` run from the menu, context menu or Tasks pane opens `TaskPanelLayerVisibility` (one checkbox per layer role plus features, "Show All", applied at once); its toolbar button is a drop-down with the same switches (`Toolbar.attach_dropdown`, attached after each workbench activation; checked in FreeCAD 1.1.4 offscreen, not yet by hand). Toolbar, menu and context menu share one list: Renumber sits with the network commands, Layer Visibility with Select All Segments / Components. Tests: `tests/test_layer_visibility.py` (the rules only). Done, not tried in the GUI: **result tooltips (item 1).** While the Calculate Airflow results panel is open, `AirflowResultObserver` listens to mouse moves (never consuming them); after the mouse rests 350 ms it ray-picks its own port planes and segment boxes, or else asks the view for the duct or fitting under the cursor, and shows a `QToolTip`: a duct's flow, velocity, friction rate, friction / fitting / total loss and cumulative pressure; a port's flow and static pressure plus velocity, K, pressure drop, loss status and path on legs with a fitting result; a fitting's legs one per line. Text builders in `core/_component_results.py` (`segment_tooltip`, `port_tooltip`, `component_tooltip`), tested in `tests/test_result_tooltips.py`. Segments only carry a cumulative pressure, so "static pressure at both ends" is not shown. Fixed after the owner's first GUI check: the tooltip closed after about a second (shown with no widget, so Qt closed it on the next mouse event, and every small move re-picked); a held-open `QToolTip` still closed after about a second in the GUI (owner, 13 November 2026), so the observer now shows its own tooltip-styled popup (a frameless `Qt.ToolTip` `QLabel`), which only it hides: when the cursor moves more than 10 px from where the popup opened (also checked every 200 ms, so leaving the 3D view closes it) or the results panel closes. Result planes and boxes gave no tooltip: the pick ran on the overlay subgraph alone, which has no camera; it now picks the whole scene with pick-all and takes the first overlay hit. |
| 10 | Done, owner checked 17 November | Custom fittings, design 6.3 (section 6). Open: save a custom fitting as a library type (owner: not now). |
| 11 | Done, owner checked 17 November; freeze tagged `api-freeze-1` | Design 6.4 and 6.5 (section 6): stable edge keys, single-form schema, public API lists, frozen context keys, `requires_api`, terminal function, equipment. `CHANGELOG.md` has the compatibility policy. Left for after the freeze: the gaps of 6.4 item 5. |
| After the freeze | Started | 6.4 item 5. Done (18 November 2026): **inline devices**, in both libraries, each a manual choice on a straight node (`through.straight.<device>`): `through_silencer_generic` (casing in the duct's own section grown by `CasingGrowth`, collars), `through_filter_generic` and `through_coil_generic` (rectangular housing, the VAV box builder), `through_fire_damper_generic` (sleeve; retaining frame and curtain pack as the `fire_damper_frame` feature), `through_access_door_generic` (sleeve; door panel and handle as the `access_door` feature, `DoorSide`), `through_flex_connector_generic` (sleeve bulging by `Bulge`). Geometry in `fittings/devices.py`. One loss function, `loss_inline_device`: a filter's drop by `FilterCondition` (clean, mid-life, final, from `CleanPressureDrop` / `FinalPressureDrop`), else `LossMode` fixed drop, else K, else no loss of its own; silencer, filter and coil default to typical pressure drops (50, 80 to 250, 120 Pa) the descriptions say to replace with the maker's data. Tests in `tests/test_loss_api_devices.py`. All 48 builds valid in FreeCAD 1.1.4 (both libraries, every profile), features placed outside the wall (checked by bounding box). Owner checked in the GUI, 18 November 2026. |

**Pending items (18 November 2026).** Everything still open in this plan, in one place.

*Needs the owner*
- GUI check of design 6.6 (section 6): wyes (radius and mitered, the crotch plate of an uneven wye with a wall), lateral tees, double wyes, the mitered shoe and the centre radius tee.
- Next (owner, 18 November 2026): review and document the API and the library framework. The "after the freeze" gaps below come after that.
- Deferred by the owner: saving a custom fitting as a library type.

*Owner's GUI check of the pending-items pass (18 November 2026):* drawn vanes, tap damper, extractor, filter media and coil block; radiussed offsets at length 0; the Friction section of the Size Ducts panel; the single BranchRadius: all passed. The radius wye on round ducts failed; fixed by design 6.6.

*After the freeze (6.4 item 5)*
- Fan curves and the fan's operating point.
- Duct leakage.
- Bill of quantities.
- Imperial units in the analysis.
- Design first: looped networks, thermal calculations, acoustic calculations.

*Done in the pending-items pass (18 November 2026)*
- Radius wye: a wall now builds where the split crosses a curved side when it can. Each grown half's strip past the cut comes from the profile grown by half the wall only (`_wye_main_split_faces(curved=True)`), so the two halves never share a curved outer face. The fixed fuse order is now split halves, bends, main, trims (`_WYE_RADIUS_FUSE_ORDER`): same wall results as before, and the solid tall oval wye now builds. The round bullhead builds with a wall; a round wye with a wall still does not fuse and says to use the mitered wye.
- Radiussed offset: `OffsetLength` 0 (now the default in both libraries) makes the offset as long as its arcs need at `OffsetRadius`, by a closed form (`transitions.radiussed_body_length`); a length the user sets is kept and still refused when too steep. `offset_loss` reads the same length.
- Drawn as construction features (`fittings/details.py`): turning vanes (`through_elbow_vaned`, by `VaneDesign`), splitter vanes (`through_elbow_rectangular`), the tap damper blade (`branch_tap_straight_damper`, `branch_tap_shoe_damper`), extractor blades (`branch_tap_extractor`), filter media pleats and the coil's fin block with header connections (`through_filter_generic`, `through_coil_generic`, both libraries).
- Equipment connection: a duct carrying air into a unit through a port of another size or shape reads the transition tables (14-11 / 14-12) at `TransitionAngle`, referred to the duct (`losses._equipment_inlet_transition_loss`). The fan tables stay on the discharge side.
- Size Ducts panel: a Friction section (model, CSV chart with Browse, expression), shown by model; it sets the network's `FrictionModel`, `FrictionTableFile`, `FrictionExpression`, which Calculate Airflow uses too.
- One radius on the radius tees and lateral tees (owner, 18 November 2026): `branch_tee_radius_center`, `branch_tee_radius_edge`, `branch_lateral_tee_radius` and `branch_lateral_tee_mitered` (both libraries) lost `ElbowRadius`; a face-mounted branch uses `BranchRadius` for the elbow after its collar (`taps.face_tap_layout`, `HVACLossAPI._face_elbow_radius`: `ElbowRadius` where a type has it, else `BranchRadius`). `branch_tap_mitered_shoe` keeps both: its `BranchRadius` is the lean its mitre cut approximates, not a bend. All 68 builds of the four types (side and face-mounted) valid.
- `circular_flex` builds valid in FreeCAD 1.1.4 (straight, solid and curved), the same shapes as `circular_generic`.
- Charts: Fig. 14-4 (flex duct compression) was already in `analysis/friction.flex_compression_factor` and on `circular_flex`; Fig. 14-3 (roughness) and 14-5 (density) are what Darcy-Weisbach with the duct's roughness and the network's air properties computes directly; the nominal-size tables 14-2 to 14-5 are the equivalent-diameter equation, which is implemented. Nothing more to digitise.

*Still open: geometry*
- A radiussed offset with a user-set length too short for its arcs is refused (says how long it must be).

*Still open: loss coverage*
- 14-14 I to L: wyes whose collar leaves the run at 45 degrees. No type builds an inclined collar; the tables are digitised and wait for one. 14-14 M (conical main) likewise.
- Static regain applies only at sizing-section boundaries (the simple reading of Stage 8). A regain solve per section needs a design.
- Not in SMACNA, so nothing to read: a cross table (crosses use the decomposed `manifold_loss`, flagged), converging damper and extractor branches (plain table, flagged), 14-16 G and H (a diffuser on a fan with no duct, never a network case).

*Still open: smaller items*
- Transition labels against the SMACNA Duct Construction Standards: the document is not in `reference/`.
- Draft snapping onto equipment snap points not tried by script (the owner's GUI check covered the port panel).

*Testing*
- Unit tests: 2237 pass on Linux (the five split-rule tests went with the rule). The 20 failures once seen on the Windows machine were never investigated.
- Smoke run, 18 November 2026 (after design 6.6): 661 valid / 32 skipped / 0 errors. No build lost; volumes and trims changed only on the types 6.6 rebuilt (and on face-mounted tees, from the single BranchRadius change before it).
- Geometry sweep (`tools/geometry_sweep.py`, design 6.6), 18 November 2026: 1838 / 1838 valid, every type and case (the design's table had the radius wye at 76 / 144, the others failing on full-size branches and thick walls).

Differences from the plan as written below:

- Libraries do not keep thin delegating generator modules. A type-def names
  a shared module directly (`"module": "shared:elbows"`), so there is no
  per-library Python for a standard fitting at all.
- Flanges are handled by the shared finisher (`_common._finish`) from
  `FlangeThickness` / `FlangeHeight` / `ShowFlange*` properties, for every
  shared fitting. Stage 7 item 1 is therefore largely done; what remains
  there is moving flanges from "fused into the casing" to construction
  features.
- Every smacna junction type now declares `connection_lengths` (Stage 7
  item 2 done).

**Stricter wall check (Stage 7 session):** `HVACLibraryAPI._layer_between` used to
hand back the closest wall it could cut even when its volume was wrong. Some
"valid" builds were therefore wrong: the rectangular bellmouth came out as a
solid (the cut had failed, 10.9e6 mm3 instead of a 1.3e5 mm3 wall) and the
radius wye as wall fragments. A wall more than 1 % off the outer-minus-inner
volume is now an error. The bellmouth is fixed (its rectangular loft is now
ruled); the radius wye is not (round and rectangular, hollow). The wye fuse
search now keeps the largest valid single solid instead of the first, since
some orders silently drop a leg.

Known geometry issues from the smoke run (333 of 363 builds valid, after the
stricter check):
`branch_wye_radius` with an Oval profile is hollow with the right volume but
fails OCC's validity check; `branch_tap_mitered_shoe` with a tall Oval was
already invalid before this work; `through_offset_radiussed` reports the
smoke run's rectangular and oval test offsets as too steep (a 400 mm duct
jogging 150 mm in 300 mm: a parameter limit, not a defect); a plenum at its default size rejects the test nodes whose ducts
leave at 45 or 72 degrees, because they cross a corner of the box (also a
parameter limit: 20 builds).

## 0a. Start here (handover)

**Fixed 12 November 2026 (owner report):** taps and tees were not flow
aware. On a square (90 degree) branch the shoe's toe and the branch bend
picked a run leg by the branch profile frame or edge key order, so their
side depended on how the ducts were drawn. They now follow the flow
(`_common._flow_paired_run`): toward the run inlet (upstream) on a supply
tee, toward the run outlet (downstream) on a return tee; an inclined
branch (lateral) still leans by its geometry, and `ReverseBranchBend`
still flips. Flipping exposed a mitered-shoe bug: `_mitered_bend` built
inside-out gores when the profile wound against the extrusion; gores are
now turned outward (`_common._outward`).

**Hood geometry fixed (13 November 2026):** SMACNA 14-15 F / 14-16 A show
the hood angle as the included flare of the duct end over one duct size,
and the cap as a conical roof 2D across with a 0.3D rise. `end_hood_intake`
and `end_hood_exhaust` now flare the neck by `HoodAngle` and draw a
conical (pyramidal for rectangular and oval) sheet roof `HoodHeight` above
the opening; the `HoodAngle` description says so. Valid on every profile
at 0 and 15 degrees.

**Owner's GUI checks (13 November 2026):** tooltips, layer visibility,
the per-port table, the hood roof and the wall flange are OK. Corrections
asked, done the same day:

1. *Robust fittings first.* Automatic selection now prefers the fittings
   that need no radius to fit: mitered elbows (smacna: mitered, then the
   rectangular radius elbow, then the generic one), mitered offsets, the
   straight tee, mitered lateral tees and double wyes; the radius types
   stay in the Change Type list. Every swept or mitered bend clamps its
   radius to `_common._min_bend_radius` (half the duct size plus the whole
   wall, plus 1 % or 1 mm), so a wall layer can no longer fold inside the
   bend. (The mitered wye's retry with a 3 % larger radius was removed on
   14 November 2026, see "Geometry is built once" below; no build needed it.)
   Static checks: `NumberOfCuts` at least 1, segment sizes above 0. Smoke
   run 525 valid of 605 (was 517; 8 fixed, none lost).
2. *Warnings link to elements.* Calculate Airflow and Size Ducts warnings
   show each element number or label as a link that selects it
   (`_analysis_adapter.network_element_index` / `link_spans`).
3. *Result labels face the viewer.* Superseded on review, see below.
4. *Size change policy.* `SizeChangePolicy`: `AtStraightJunctions`
   (default, replaces `AtReducers`: in-line nodes and the run of a tee or
   cross), `AtInlineNodesOnly` (the old rule), `EverySegment`; editable in
   the Size Ducts panel; `AllowSizeChange` now also on branch and cross
   junctions. Old documents map `AtReducers` to `AtStraightJunctions`.
5. *Spreadsheets locked:* solved (owner, 13 November 2026).
6. *Ports.* Port markers are made visible (FreeCAD creates them hidden);
   "Add HVAC Port" first asks for an X/Y offset from the opening's centre
   (`PortOffsetX` / `PortOffsetY`, kept on the marker).
7. *Equipment and custom fitting panels.* "Create / Edit Equipment" and the
   new "Create / Edit Custom Fitting" act on a selected App::Part and open
   one panel (`TaskPanelPortContainer`): ports listed by kind, added on a
   picked face at an X/Y offset, renamed, moved, removed; the equipment's
   internal pressure drop; for a fitting, "Use This Fitting There" at a
   junction.
8. *Equipment holds its ports.* The App::Part itself becomes the
   equipment (`Equipment.make_equipment`), so selecting it selects the
   model and its markers; the old separate object still loads (`model_of`).
9. *Wireframe when selected.* FreeCAD draws a selected object with one
   transparency for every face, so a transparent hidden layer turned the
   whole selection into a wireframe. Hidden layers and features are now
   left out of the displayed `Shape` (`_component_appearance.displayed_parts`);
   each layer keeps its own shape property. The compound is rebuilt
   outside view updates, since one set inside `updateData` left the old
   mesh on screen.

**Corrections 3 and 7 reworked (owner's answers, 13 November 2026); not
yet tried in the GUI.**
- Correction 3, result labels. *Owner:* lay the labels as originally (flat
  on their plane); only flip them (in the plane) or turn them 90 degrees when
  the camera looks from the back or from below. *Done:* the billboard is
  gone. `buildFlowRateLabelCoinNode` builds each label in its 8 in-plane
  orientations (front / back times four quarter turns) under one `SoSwitch`;
  variant 0 is the original layout. A `LabelOrienter` per overlay observer
  watches the active view's camera (`SoFieldSensor` on its orientation) and
  picks, per label, `chooseLabelVariant()`: flipped when seen from behind,
  turned only when another quarter turn's up is clearly better (by 0.3, so
  labels don't flicker near 45 degrees).
- Correction 7, equipment and custom fitting panels. *Owner's sequence:*
  (1) select the App::Part and call the equipment / custom junction command;
  (2) the panel opens to add ports, each with its role (equipment only) and
  X/Y; (3) equipment and custom junctions attach to the network
  automatically when base geometry is drawn to their ports. *Done:*
  `HVAC_CreateEquipment` / `HVAC_CreateCustomFitting` (names and menu texts
  kept; the latter now marks the part, `_custom_fitting.make_custom_fitting`)
  open `TaskPanelPortContainer`, which already had role and X/Y per port;
  the separate `HVAC_AddCustomPort` command and its `PortOffsetDialog` are
  removed. Automatic attachment (`core/_auto_attach.py`,
  `DuctNetwork.getNodeGroups` / `autoAttach`): an open duct end within 1 mm
  of a port marker sits on it. The ends on one custom fitting become one
  node group (like a virtual junction), and that junction's Primary takes
  the fitting with the new `CustomPlacement` = "In place": the App::Part
  stays where it was modelled, no link, each duct's trim is the distance
  from its end to its port (`library/custom_fitting.fit_in_place`); a port no
  duct reaches is left open with a warning. This is done once per junction
  (`AutoAttachedTo`), so a later change by the user is kept. An end on an
  equipment port is connected with `Equipment.connect` (once per port and
  node); connections to nodes that no longer exist are dropped. "Connect to
  Equipment" and "Use This Fitting There" (fit to node) stay as manual
  alternatives. Tests: `tests/test_auto_attach.py`, the in-place tests in
  `tests/test_custom_fitting_fit.py`. Owner's GUI check (14 November 2026): a plain Part cube left both commands
  disabled (they wanted an App::Part) and the Tasks pane never listed them. A selected solid in no App::Part
  is now wrapped in a new one (undoable), and a Tasks pane group "Equipment and Custom Fittings" shows the
  equipment, custom fitting and connect commands while a model is selected. Same check, panel reworked: the separate
  "Add port" and "Selected port" boxes are one Port box driven by the 3D selection (a planar face of the model:
  new port; a port marker or tree row: edit it; nothing: a hint), and the tree follows markers picked in 3D.
  "Use in a network" lists only the junctions the fitting fits (`_custom_fitting.fit_problem`: the same fit
  the component runs, so port count and directions; any junction order, an end node for a one-port
  fitting), in a list synced with the 3D selection both ways (a row selects the junction's fittings). While
  the panel is open each listed junction's fittings are coloured orange (their own `ShapeAppearance`,
  `LineColor`, `PointColor`, a link's override material; saved and put back on close), so pre-selection and
  selection highlight them as usual and an end marker's cross turns orange too. Port markers show while the
  panel is open and are hidden on close. Snapping (owner, 15 November 2026): custom junctions keep "Use This
  Fitting There"; every equipment port gets a snap point, a `Part::Vertex` in the same App::Part attached to
  its marker (`_custom_fitting.ensure_snap_point`), visible when the marker is hidden, deleted with the port,
  made for older ports when the panel opens; picking it picks its port. Checked offscreen in FreeCAD 1.1.4
  (rotated, moved App::Part; offset change; colours set and restored); Draft snapping onto it not tried.

**Done 14 November 2026 (owner's picks):** layer visibility toolbar
dropdown (Stage 9), face-mounted lateral tees and bullhead wye losses
(Stage 4), the exhaust-outlet network direction (6.5), sections win over
balancing (Stage 8), and plenum sizes left at 0 now grow so every duct fits
on its face (`boxes._grow_to_fit`; a size the user set still reports the
overhang). Not done: saving a custom fitting as a library type (owner: not
now).

**Fallback geometry, tee and tap parity, fan transitions (owner, 15 November
2026).**
- *Fallback.* A component whose build raises keeps its GeometryError and is
  drawn as `markers.build_fallback`: an end-marker cross on every duct end,
  pulled back by a quarter of the duct size (at least 25 mm) when the node has
  two or more ducts, and lines from the node to them; its trims are reported,
  so the ducts and the network stay whole. The trim peek
  (`DuctJunction._peekConnectionLengths`) reports the same trims when the
  measurement fails, and a custom fitting that no longer fits gets it too
  (its link is removed). Checked in FreeCAD by forcing a failing Attachment.
- *SMACNA parity, tees and taps (14-14 A to Z, read from the scanned
  reference).* Side taps in any direction round the run (top, bottom: 14-14
  V's conical tap below a rectangular main) were already there. New: a branch
  crossing the run's edge is built (`taps.branch_jog`, `with_branch_jog`, the
  `_common._finish` hook): moved in until it lies within the run (onto the run
  axis for the radius tees, which sweep in the run's plane), with an offset
  piece of at most 30 degrees back to its own axis; Auto no longer refuses it
  (Face still does). Face-mounted saddle (conical) and shoe taps keep their
  collar (`face_tap_layout(collar=...)`, flare kept within the run face), and
  `CollarRoll` rolls the collar round a round run towards the branch, the
  elbow turning the rest (14-14 D, F to L "rolled 45 deg"; 0 is E). Run trims
  of a face mount are now measured from the node (a rolled lateral's collar
  foot moves along the run). Done 17 November 2026: `branch_tap_saddle` is
  also offered on laterals (manual, priority 30, below the lateral tees), the
  cone along the branch axis; side-mounted it reads 14-14 C at 45 degrees (B
  at 90; flagged `APPROXIMATION` more than 10 degrees from either).
  Face-mounted round diverging tees read the rolled-collar tables by
  `CollarRoll` (about 45 degrees), branch angle (90 or 45) and `BranchStyle`:
  14-14 D, F (plain) and G, H (conical); an unrolled collar reads E as before
  (`HVACLossAPI._face_mounted_round_variant`). Not covered: 14-14 I to L
  (wyes whose collar leaves the run at 45 degrees: no type builds an inclined
  collar) and 14-14 M's conical main. Smoke run 603 valid / 32 skipped / 10
  errors: the 16 new saddle-on-lateral builds are valid, nothing else moved.
- *Fan connection.* `end_equipment_connection` builds `terminals.build_terminal_fan`:
  the collar, and for a FanConnection transition a loft from the fan outlet
  (FanOutletWidth x FanOutletHeight at the node) to the duct at the included
  TransitionAngle: symmetric / pyramidal centred, the asymmetric ones keeping
  the top level or sloping 10 degrees down or up (14-11 F to J). "Discharge
  into casing" and "None" stay a collar.
- Sweep in FreeCAD 1.1.4: every tap and tee type with the branch centred on
  the run surface (56 builds), face-mounted (56) and rolled 45 degrees on round
  runs (18), and every fan connection on round and rectangular ducts; all one
  valid solid, trims equal to the measure functions'. Smoke run unchanged in
  status (587 / 32 / 10); only the 19 face-mounted saddle and shoe builds
  changed volume (they now have their collars).

**Damper detail and terminal faces (owner, 15 November 2026).** Both are
construction features, so they never enter the wall booleans and follow
`ShowFeatures`. Dampers (`through_damper_generic`, both libraries):
`damper_blades` draws the blade(s) and shafts at the current position (a
"Coefficient" damper as one blade; multi-blade and gate plates clipped to a
round or oval section with one `common`), `damper_operator` a hand quadrant
(quarter plate, lever at the blade angle, knob) or an actuator (bracket,
clamp, body), with `Operator`, `OperatorSide` and `OperatorRotation`
(`fittings/dampers.py`). The SMACNA tap dampers (`branch_tap_*_damper`) stay
loss-only. Terminals: the diffusers, slot diffuser, grille and register had
an open end; `terminal_face` (`fittings/faces.py`) draws a border plate over
the body's wall and a pattern in the core, `FacePattern` per type;
`builtin_basic` declares only the pattern (sizes worked out from the face),
`smacna` every size. Blades are cut to a round or oval outline by arithmetic;
booleans only for a ring's middle or a plate's holes (one cut each). Sweep in
FreeCAD 1.1.4: every pattern, operator, side and blade type on every profile
in both libraries, 360 builds, all valid, slowest 0.97 s (a perforated
plate); positions checked by bounding box (blades inside the casing,
operator outside the wall on the chosen side). Smoke run unchanged (587 /
32 / 10). Owner checked in the GUI, 17 November 2026.

**A sync rebuilds only what changed (owner report, 15 November 2026: editing a
property felt slow).** Measured on a network of 8 tees (17 ducts, 18 fittings):
every sync rebuilt every fitting, 1.2 s, even with nothing changed. Causes:
`syncJunctionComponents` touched every component of every junction; it also
rewrote each Primary's label, which never compared equal because FreeCAD
appends digits to keep labels unique (`hvaclib.set_label` / `label_matches`
now allow for them; same for segments, junctions, virtual junctions and
numbered labels); and `composeComponents` rewrote `LocalPortsJson` / `Profile`
unchanged (every property write marks the object). Now a junction's
components are touched only when the junction is new or its classification
changed (`rebuild`), on the first sync of a loaded document, or on
`requestSync(rebuild_all=True)` (Reload Libraries). After: a duct size edit
rebuilds its two fittings (0.29 s), a fitting edit only that fitting (0.24 s,
the build itself), a sync with nothing changed nothing. Checked that trims,
duct sizes and moved base geometry still propagate. Reset to Defaults touched
every selected object and rewrote every layer material; it now leaves an
object already at its defaults alone. Left as is: a duct can execute two or
three times in one edit (recompute, then the two segment stages), about 12 ms
each.

**Library equipment (owner, 15 November 2026).** `end_ahu_generic` was retired
with 6.5 (equipment only as user models, answer (g)); the owner now wants
ready-made units back, as equipment. A library keeps equipment models in
`equipment/*.json` (`library/equipment_library.py`: id, label, generator,
typed properties; unknown keys are errors); the shared generators
(`fittings/equipment.py`, `build_ahu`, `build_fan`) return one solid (casing
plus a solid collar per connection) and the ports. "Add Equipment from Library"
(`HVAC_AddEquipment`, `TaskPanelAddEquipment`, `Equipment.create_from_model`)
places one as an App::Part with a body, a port per collar end face (function,
size read from the face, snap point, marker hidden) and its internal pressure
drop. `builtin_basic`: `ahu_generic` (supply, return, optional outdoor air and
exhaust; rectangular or round ports) and `fan_generic` (supply or exhaust
service). The body is a plain solid: to change a size, add the model again.
The VAV box was never an end type: `through_vav_generic` is an inline type.
Checked in FreeCAD 1.1.4 offscreen, including a duct drawn to the supply port
attaching by itself; owner checked in the GUI, 17 November 2026.

**Geometry is built once (owner, 14 November 2026):** "do not use slower
geometry options and do not iterate geometry; use mathematical checks for
failure for fast generation." A fitting builds each shape once, in one fixed
order, with plain booleans: no retries, no search over fuse orders, no fuzzy
booleans. Failure is found by cheap checks: on the layout before building
(radius against `_min_bend_radius`, tangent clearances, the split rule
below) and on the result after (`_common._is_union_of`: one valid solid,
between the largest piece and the pieces' sum, keeping at least 90 % of the
sum; a wall layer must have the volume outer minus inner, within 1 %), and
each raises a clear error. Removed: the radius wye's search over ten fuse
orders, the mitered wye's radius retries, and the second and third cut
attempts in `_layer_between`. Only radius wye builds changed; the whole smoke
run takes 104 s.

**Radius wye (14 November 2026).** `builtin_basic/branch_wye_radius` splits
the main section between the branches and sweeps each half into its branch.
Made exact: the branch end circle is cut where the half's corners arrive
after the bend, so the sweep does not twist (`_wye_branch_end_wire`,
`api.make_circular_wire_split_at`), and a wall half is cut from the grown
main profile, reaching the wall thickness past the cut, instead of
`offset_wire` (`_wye_main_split_faces(offset=...)`). Rule found with the
smoke run: where the split line crosses a curved side of the main section
(always on a round duct; on an oval when the cut falls in a rounded end),
the two wall halves overlap past the cut and meet at a grazing angle that a
plain fuse cannot handle; only a fuzzy fuse did, which is now ruled out. Such
a wye with a wall is refused before any geometry is built
(`_wye_split_crosses_curve`), pointing to the mitered wye; without a wall it
builds. Builds: rectangular and oval (wide) wyes and bullheads; the oval
wye at its default radius is new (fuse order `_WYE_RADIUS_FUSE_ORDER`, chosen
with the smoke run). Fails: round (refused), and the tall oval wye and
bullhead, whose air space itself does not fuse in any fixed order (before,
one of the ten orders tried happened to work). A radius wye now builds in
about a second. Not in `smacna`.

**Owner's GUI check (17 November 2026): passed.** Labels, the port panel
(including ducts drawn onto equipment and custom fitting ports), the layer
visibility dropdown, custom fittings, terminal function, equipment (also
from the library), damper detail, terminal faces, the fallback drawing and
fan connections. "Add Equipment from Library" is now "Add Equipment", in a
"Fittings and Equipment" task group. The freeze is tagged `api-freeze-1`
(geometry API 3, loss API 1, PartScript 3).

**Next task:** the owner's GUI check of design 6.6, then (owner, 18 November
2026) a review and documentation of the API and the library framework. The
"after the freeze" gaps of 6.4 item 5 come after that.

**Branch:** all roadmap work is on `roadmap-stage-0`. Work done in a
worktree is committed there and `roadmap-stage-0` is then fast-forwarded to
it. Nothing has been pushed since Stage 5.

**Running the checks**

- Unit tests: `uvx pytest tests -q`. On the Windows machine used so far, 20
  tests fail before and after Stages 6 and 7 (`test_component_appearance`,
  `test_geometry_apply`, `test_materials`, `test_static_shapes` and four
  single tests in `test_network_component_sync`, `test_reset_to_defaults`,
  `test_segment_reactive_properties`). They were not investigated. Anything
  beyond those 20 is a regression.
- Formatting: `sh tools/ruff.sh <files>`, on the files changed only.
  `core/NetworkParser.py`, `ui/TaskPanel.py`, `library/library_api.py`
  (imports) and `tests/test_network_parser_flow_classification.py` were
  never formatted: do not run the formatter over them, keep additions tidy
  by hand.
- Geometry smoke run: `"<FreeCAD>/bin/python.exe" tools/geometry_smoke.py`
  (add `--all` to list every build, a `.json` path to save the report).
  `freecadcmd tools/geometry_smoke.py` does not execute the script with
  FreeCAD 1.1. Earlier result: 322 valid of 347 builds; latest (14 November 2026, FreeCAD 1.1.4 flatpak on Linux: 587 valid, 10 errors, of 629, in 104 s; the errors are four radius wyes (round refused, tall oval) and the six too-steep radiussed offsets; run it with `flatpak run --env=FREECAD_BIN=/app/freecad/bin --command=sh org.freecad.FreeCAD -c "python3 tools/geometry_smoke.py"`); the 25 others are the
  known cases listed above. A shape that builds valid is not necessarily
  right: new geometry also needs a look in the FreeCAD GUI, which no stage
  so far has had.

**Rules that are easy to trip over** (beyond `AGENTS.md`)

- *One priority per bucket.* Two types that list the same family and share
  a profile must not have the same `selection.priority`
  (`test_bundled_libraries_have_no_unresolved_priority_ties`). Priorities
  also order the Change Type list, so give similar types neighbouring
  numbers (see the end types: diffusers 90 to 87, entries 80 to 78, ...).
- *Manual-only types.* Automatic selection needs the exact family key the
  classifier produces. A type that must only ever be picked by hand lists a
  family one level deeper, which the classifier never produces but which
  still counts as related: `end.terminal.entry`, `branch.tee.plenum`. Such
  a type needs one entry per classifier family it should be offered for,
  the `.3d` forms included.
- *`"unknown"` is a value.* The classifier reports `flow_class` and
  `alignment` as the string `"unknown"` when it cannot tell. A constraint
  enum that leaves `"unknown"` out removes the type whenever the flow
  direction is not known; list it unless that is what is wanted.
- *Classifier vocabulary.* `flow_class` is `expansion` / `contraction` /
  `constant` (through), `diverging` / `converging` (branch, cross,
  multiport), `entry` / `exit` (end), else `unknown`. New qualifier or
  derived-value keys must be added to `validation.KNOWN_QUALIFIER_KEYS` /
  `KNOWN_DERIVED_VALUE_KEYS`, or type-defs using them fail to load.
- *Unknown JSON keys are load errors*, in a property def and in
  `validation`. Negative values need `App::PropertyDistance`;
  `App::PropertyLength` cannot hold them.
- *PartScript types.* A property added to a type whose geometry is a
  PartScript must also be added to the list in
  `tests/test_library_discovery.py`.
- *Build once.* No geometry retries, fuse-order searches or fuzzy booleans;
  check the layout and the result mathematically and raise a clear error
  (see "Geometry is built once" above).
- *Measure equals build.* A fitting's `measure_*` and `build_*` must come
  from one layout function; the smoke run reports a mismatch.
- *Envelope builders.* `envelope(offset)` returns the air space grown by
  `offset` as one solid. Where a part steps outward (a frame, a box end),
  the outer envelope must also grow along the axis by `offset`, or the wall
  has no thickness at the step.
- *Round to rectangular lofts* twist unless the round end is made with
  `api.make_split_circular_wire`.
- *Library code talks to the API only.* A fitting module that needs a new
  primitive gets it as a method on `HVACLibraryAPI`, it does not import
  `Part`.
- *JSON type-defs* are written with two-space indent and LF line endings.

## 0b. Who should take what

"Standard" is work a capable coding agent can do from this document and
the code, with the checks above. "Design first" needs a design pass by a
senior engineer or the strongest available model, and usually an answer
from the project owner, before any code is written; the implementation
after that is standard again.

| Work | Level | Why |
|---|---|---|
| Stage 1: split `library_api.py` into mixin modules | Done | |
| Stage 3: per-port table in the Edit Type panel | Done, needs a GUI check | One row per port (labelled by its duct's number), one column per per-port property of the current type; applied on OK, only while the type is unchanged. Logic in `core/_port_properties.py` (`port_table`, `parse_port_value`, `apply_port_table`), tested in `tests/test_port_table.py`. |
| Stage 4 open: lateral tee and wye items | Standard | Decisions 10 to 13 in section 4 are taken. Build `branch_lateral_tee_radius` / `_mitered` from the double wye's branch bend (`fittings/crosses.py`), with priorities next to `branch_lateral_tee_generic`; add the `common_leg` constraint and the `branch.tee` families to the two wye types at a priority below every tee type. Geometry needs the smoke run at 30, 45 and 60 degrees on every profile. |
| Stage 5 open: eccentric transition table (14-11 E), radius limit on `through_offset_radiussed` | Standard | |
| Stage 5 open: fitting-derived read-only values (`IncludedAngle`) | **Design first** | Adds a second vocabulary next to the classifier's; touches type-def schema, object properties and loss calls. |
| Stage 6 open: hood plate angle, wall flange, oval loft seam | Standard | Geometry only. |
| Stage 6 open: AHU fan-connection tables | Standard | Needs a `FanConnection` choice and a loss method over 14-11 F to J, 14-16 G to I. |
| Stage 7 (a) elbow tests, (b) the other three loss methods, (e) remove the shim, (f) coverage matrix and test | Standard | (b) follows the elbow change as its example. Rectangular branch tables are keyed to discrete area ratios: follow Stage 2 item 4 for when to report `EXACT`. |
| Stage 7 (c) SMACNA-only branch types, (d) Stage 4 to 6 types in `smacna` | Standard, with review | Ids, priorities and which properties `smacna` gets are choices; have them reviewed against the naming rule before merging. |
| Stage 7 (g) flanges as construction features | **Design first** | Changes how every shared fitting hands back its shape; decide the feature contract first. |
| Stage 8 item 2: friction models | Standard | Pure analysis code, fully unit-tested. The expression parser must be a whitelist, never `eval`. |
| Stage 8 item 1: sizing sections | Standard, with one design point | Constant velocity and friction rate are direct. **Design first** for static regain at section boundaries and for what the "extra reducer" advice reports. |
| Stage 9 item 2: layer visibility | Standard | Decision 7 (transparent first) is taken. |
| Stage 9 item 1: result tooltips | Standard | Coin event handling; cannot be verified without the GUI. |
| Stage 10: custom geometry per fitting | Done (design 6.3) | Needs a check in the GUI. Open: save a custom fitting as a library type. |
| Stage 11: gap analysis and API freeze | **Design first** | Schema versioning, stable edge identity and the public API surface are irreversible once frozen. Also where multi-node equipment is decided. |

## 1. Where things stand

Findings from reading the code that shape the plan:

| Area | Current state | Consequence |
|---|---|---|
| Generic fitting code | `builtin_basic/generators/junctions.py` is 2154 lines. `smacna/generators/junctions.py` re-implements the same helpers (`_props`, `_size`, `_trimmed`, `_loft`, markers, star body). The two `junction_losses.py` files differ only in comments. | Every new fitting would be written twice. Consolidate first (Stage 1). |
| Wall geometry | `builtin_basic` lofts with `solid=True` and has one roleless-thickness layer, so its fittings are solid bodies. Only `smacna` uses `build_layered_geometry(envelope_builder, ...)`. | Generic fittings need the offset/envelope pattern before more are added. |
| Trim measurement | All 19 `smacna` junction type-defs lack `connection_lengths`, so each one is built twice per sync (the `_peekConnectionLengths` fallback). | Fixed for free once smacna reuses the shared builders. |
| Per-port properties | Four naming schemes for the same idea: `TrimRunA`, `RunTrimLengthA`, `TrimLengthA`, `TrimMain`. Multiport has one shared `TrimLength`. No list or per-port property mechanism exists. | Blocks the plenum and any fitting of order 5 or more. Needs one mechanism (Stage 3). |
| Property validation | Three type-defs use a top-level `"min"` key (for example `TapHeight` in `branch_tap_straight.json`). `validation.py` only reads `validation.minimum` / `exclusiveMinimum`, so `"min"` appears to be ignored. | Small fix in Stage 0. |
| Loss tables | `library/smacna_loss.py` covers 14-10 A/C/D/F, 14-11 A/B, 14-12 A, 14-13 A/B and 14-14 A. Its docstring says values were never checked against a primary source. Rectangular branches use the round tables as an approximation. | The reference PDF now allows verification and about 60 more tables (Stage 2). |
| Classifier | `end` is always `terminal`. Tee branch eccentricity only shows up as the `3d` qualifier. `cross` falls to `generic` unless it is a clean two-run cross or symmetric double wye. | Top/bottom tee attachment needs one new derived value. Terminal function stays a manual choice. |
| Sizing | `_size_independently` sizes every segment from its own flow, so sizes step at every tee. | Needs a "sizing section" concept (Stage 8). |
| Oval | `width >= height` is enforced in `analysis/physics.py` (areas, hydraulic diameter, three sizing solvers) and `library_api.make_oval_wire`. | Stage 0. |
| Analysis scope | Tree networks only. Friction is Darcy-Weisbach with Altshul-Tsal, hardcoded. | Custom friction needs a model abstraction (Stage 8). |

`reference/SMACNA ref 1.pdf` is currently untracked. It is copyrighted
material, so keep it out of the repository (add `reference/` to
`.gitignore`) and cite table numbers in code instead.

## 2. Stage overview

| Stage | Title | Covers request items | Size | Depends on |
|---|---|---|---|---|
| 0 | Quick fixes and conventions | G8, part of G13 | S | none |
| 1 | Shared fitting core in `library/` | G1 | L | 0 |
| 2 | Loss table library | 9 (data) | L | none, parallel with 1 |
| 3 | Port roles and per-port properties | G6 (generic ports), enabler for 1, 5, 6 | M | 1 |
| 4 | Branch and cross fittings | 1, 5, 7, G6 | L | 1, 3 |
| 5 | Through fittings | 4, 8, VAV from 3 | M | 1, 2 |
| 6 | Terminals, equipment, plenum | 2, 6, AHU from 3, G10 | L | 1, 2, 3 |
| 7 | SMACNA library rebuild | G2, 9 (wiring) | M | 4, 5, 6 |
| 8 | Analysis: sizing sections, friction models | G4, G11 | M | none, parallel |
| 9 | UI: result tooltips, layer visibility | G5, G9 | S to M | none, parallel |
| 10 | Custom geometry per fitting | G12 | M | 3 |
| 11 | Gap analysis and API freeze | G13 | M | all |

Sizes are relative effort: S is a day or two, M about a week, L more than a
week. Stages 2, 8 and 9 do not touch generator code and can be interleaved
with the others at any time.

## 3. Stages

### Stage 0: quick fixes and conventions

Goal: remove known friction before the larger refactors.

1. **Oval without `width >= height` (G8).** Make `oval_area` and
   `hydraulic_diameter_oval` symmetric (use major and minor internally).
   Let `aspect_ratio` be below 1 in `oval_dims_for_velocity`,
   `oval_dims_for_friction_rate` and `oval_dims_for_static_regain`, and fix
   the solver bounds that assume `lo=height`. In `make_oval_wire`, put the
   flat sides along whichever axis is longer. Update `tests/test_physics.py`
   and `tests/test_analysis_sizing.py`.
2. **Trim property names.** Adopt one scheme everywhere:
   `Trim<Role>` where role is `RunA`, `RunB`, `Branch`, `BranchA`,
   `BranchB`, `Main`, `Inlet`, `Outlet`, `Neck`. Rename the smacna
   `RunTrimLengthA` and `TrimLengthA..D` forms.
3. **Property def hygiene.** Convert the three top-level `"min"` keys to
   `validation.minimum`. Make the loader reject unknown property keys so the
   mistake cannot recur. Document `"Parameters"` as an established property
   group (13 uses) next to `"Dimensions"` and `"Options"`.
4. **Docs.** `ARCHITECTURE.md` points to `CLAUDE.md` for rules that now live
   in `AGENTS.md`. Ignore `reference/`.

Exit: full test suite green; no behaviour change other than oval.

### Stage 1: shared fitting core in `library/` (G1)

Goal: one implementation of every basic fitting, hollow and multilayer by
default, reachable from any library through the API.

1. **New package `freecad/HVAC/library/fittings/`** holding the builders
   now in `builtin_basic/generators/junctions.py`, grouped by family:
   `elbows.py`, `transitions.py`, `offsets.py`, `taps.py`, `tees.py`,
   `wyes.py`, `stars.py`, `terminals.py`, `inline.py`, `markers.py`, plus
   `_common.py` for the shared helpers. Each fitting keeps the existing
   three-part shape: `_layout()` (pure numbers), `measure_*()` (trims
   only), `build_*()` (shape).
2. **Every builder becomes an envelope builder.** Signature
   `envelope(offset) -> Part.Shape`, built from
   `profile_from_port(port, offset)`. `build_*` then calls
   `api.build_layered_geometry(envelope, context["construction_layers"], params)`.
   Zero declared thickness still yields a thin shell, never a solid: give
   `builtin_basic`'s default layer a `Thickness` property so the first
   envelope always has something to cut.
3. **API convenience functions on `HVACLibraryAPI`** so a generator is a
   few lines: `build_elbow`, `build_mitered_elbow`, `build_transition`,
   `build_offset`, `build_tap`, `build_tee`, `build_wye`, `build_star`,
   `build_terminal_body`, `build_inline_body`, `build_marker`, each with a
   matching `measure_*`, plus `add_flanges(layers, ports, spec)` built on
   the existing `make_flange`. They accept the context plus keyword
   overrides and return the standard `{"layers": ..., "connection_lengths": ...}`
   dict.
4. **Split `library_api.py`** (1914 lines) into mixin modules
   (`_api_vector.py`, `_api_ports.py`, `_api_profiles.py`,
   `_api_solids.py`, `_api_paths.py`, `_api_layers.py`, `_api_fittings.py`).
   `HVACLibraryAPI` stays the single public class.
5. **Loss side.** Move the body of `junction_losses.py` to
   `library/fitting_losses.py` as the default dispatch functions.
   Each library's `generators/junction_losses.py` shrinks to re-exports
   plus genuine overrides.
6. **Thin the libraries.** `builtin_basic/generators/junctions.py` and
   `smacna/generators/junctions.py` become one-line delegations. Both keep
   their module and function names so type-def JSON does not change in this
   stage.

Tests: layout and `measure_*` functions are data code, so add
`tests/test_fitting_layouts.py` asserting `measure_*` equals the
`connection_lengths` returned by `build_*` for each family (this is the
"same underlying calculation" rule from the libraries README). No tests for
shapes.

Exit: both libraries render the same fittings as before from shared code;
`builtin_basic` fittings are hollow; no duplicated helper remains.

Risk: `branch_wye_radius` is already fragile in OCC sweeps and booleans.
Offsetting multiplies boolean count. Keep a per-fitting fallback that
builds the outer envelope only and reports through `GeometryError`.

### Stage 2: loss table library (item 9, data half)

Goal: every table in the SMACNA reference digitised, verified, and
reachable through `HVACLossAPI`. Pure Python, fully unit-tested, no FreeCAD.

1. **Infrastructure.** New package `library/loss_tables/` with a small
   `LossTable` class: 1D, 2D and 3D clamped linear interpolation, support
   for blank cells (the dashes in 14-14 A), and a result that reports
   whether the lookup was clamped or hit a blank so the API can downgrade
   `EXACT` to `APPROXIMATION` with a warning. Each table records its
   SMACNA id, reference velocity (upstream, downstream, or a named leg)
   and applicable profiles.
2. **Verify what exists.** Check the ten tables in `smacna_loss.py`
   against the PDF, then move them into the new package and leave
   `smacna_loss.py` as a compatibility shim until Stage 7. Confirm the
   elbow angle factor (14-10 Note 1) and Reynolds corrections (Notes 2, 3)
   are applied.
3. **Digitise in this order**, one module and one test file per group:

| Order | SMACNA table | Content | Used by |
|---|---|---|---|
| a | 14-10 B, E, G, H, I, J, K, L | 3 to 5 piece, converging/diverging mitered, splitter vanes, turning vanes, Z-shaped, different planes, 30 degree round offset, wye-shaped elbow | elbows, offsets |
| b | 14-11 C to J | round-rect transitions (angle formula into 14-11 B), sides straight, transitions at fan | transitions, AHU and fan connections |
| c | 14-12 B, C | conical contraction, slot to round | transitions |
| d | 14-14 B to Z | conical tee, conical wye, rolled tees with elbow, rectangular tees (45 degree entry, damper, extractor), rect main to round branch, rectangular wyes, dovetail | taps, tees, wyes |
| e | 14-13 C to I | converging counterparts | taps, tees, wyes |
| f | 14-15 A to I | entries: duct in wall, bellmouth, conical, intake hood, tapered hood, canopy | end fittings |
| g | 14-16 A to J | exits: exhaust hood, conical, plane and pyramidal diffuser, elbow discharge, flush with wall, fan outlet, abrupt | end fittings |
| h | 14-17 A, B | screen, perforated plate | end fittings (additive), inline |
| i | 14-18 A to L | butterfly, gate, parallel and opposed blade dampers, cylinder obstruction, depressed duct | dampers, obstruction, offsets |
| j | 14-9, Fig. 14-3, Fig. 14-4, Tables 14-2 to 14-5 | straight-through regain coefficients, roughness correction, flex duct compression, equivalent diameters | sizing, friction (Stage 8) |

4. **API entry points** on `HVACLossAPI`, following the existing
   `LossPath` conventions: `entry_loss`, `exit_loss`, `screen_loss`,
   `damper_loss`, `obstruction_loss`, and variant keyword arguments on the
   existing `elbow_loss`, `transition_loss`, `offset_loss`, `branch_loss`
   and `wye_loss` (for example `construction="conical"`, `vanes=2`).
   Rectangular branch tables (14-13 C/D/F/H, 14-14 N to W) are keyed to
   discrete area ratios: use them when the geometry is within a stated
   tolerance and report `EXACT`; otherwise keep the round-table
   approximation and report `APPROXIMATION`.

Tests: one spot value per row and column edge, one interpolated value, one
clamped value per table; extend `tests/test_loss_api.py` for each new entry
point.

Exit: table inventory in the module docstring matches the PDF index; no
table is consumed without a status.

### Stage 3: port roles and per-port properties (G6 "generic ports")

Goal: one way to say "this value belongs to that port" that works for any
order, survives reloads, and replaces ad hoc `A/B/C/D` suffixes.

1. **Port roles API.** `api.port_roles(context)` returns a stable mapping
   of role name to port for the current topology: `run_a`/`run_b`/`branch`
   (tee, lateral), `main`/`branch_a`/`branch_b` (wye), `run_a`/`run_b`/
   `branch_a`/`branch_b` (cross, double wye), `inlet`/`outlet` (through),
   `neck` (end), and `port_1..port_n` ordered by a deterministic geometric
   key for multiport. It supersedes `run_branch_ports`, `_wye_port_roles`
   and `_lean_port`, and is what lets a wye builder accept a tee-shaped
   node (Stage 4).
2. **Per-port property declaration.** A property def gains
   `"per_port": true`. Core expands it to one stored list
   (`App::PropertyFloatList` plus a parallel edge-key list), exactly the
   persistence pattern already used by `CustomLossCoefficientEdgeKeys`,
   including the reload remap in `core/_custom_loss.remap_persisted_edge_keys`
   (generalise that helper into `core/_port_properties.py`). Generators
   read `params["TrimLength"][edge_key]` through
   `api.port_param(context, name, port)`.
3. **Editing UI.** The property editor shows a raw list, which is not
   usable. Add a small per-port table to the existing Edit Type task panel
   (role, connected segment label, value).
4. **Decision recorded here:** fixed-order fittings (tee, wye, cross) keep
   named scalar properties (`TrimRunA`, ...) because they read better in
   the property editor; `per_port` is for variable-order fittings
   (multiport, plenum, AHU).

Tests: schema expansion, remap on reload, role resolution for each
topology (`tests/test_port_properties.py`, `tests/test_library_api_ports.py`).

Open question: "Generic Ports" in the request is read here as this
role/per-port mechanism. If it instead means ports on `Generic`-profile
types, say so and this stage shrinks.

### Stage 4: branch and cross fittings (items 1, 5, 7, G6)

1. **Tee and tap attachment modes (item 1).**
   - Classifier: add one derived value for degree-3 tee and lateral
     nodes, `branch_eccentricity_ratio` = signed offset of the branch axis
     from the run axis divided by the run half-depth in that direction.
     Pure geometry, so it belongs in `NetworkParser.classify_flow`;
     register it in `validation.KNOWN_DERIVED_VALUE_KEYS`.
   - Type-def: add `Attachment` enum (`Auto`, `Side`, `Top`, `Bottom`) to
     `branch_tap_*` and `branch_tee_*`. `Auto` picks `Side` while the
     branch footprint lies inside the run face, `Top` or `Bottom` (by
     sign) once the branch axis clears the run surface.
   - Geometry: top/bottom mode is a collar on the top or bottom face,
     then an elbow (shared elbow builder) turning into the branch
     direction. New properties `CollarHeight`, `ElbowRadius`.
     The partial-overlap band between the two modes is a geometry error
     with a clear message.
   - Loss: 14-14 D to L are exactly "tee with elbow, branch 90 degrees to
     main"; wire them as loss variants selected by `Attachment`.
2. **Lateral tee on the wye generator (item 7).** *Replaced by
   decisions 10, 11 and 13 in section 4.* As first written: Rebuild
   `branch_lateral_tee_generic` as a call into the wye mitered/radius
   layout with `run_b` as the straight-through branch. Remove
   `_lateral_tee_layout`.
3. **Wye types accept more families (G6).** *Narrowed by decision 12
   in section 4.* As first written: With `port_roles`, let
   `branch_wye_mitered` and `branch_wye_radius` list `branch.lateral_tee`
   and `branch.tee` in `family`. For a bullhead tee the common leg is the
   branch, which is already exposed as `qualifiers.common_leg`. Keep
   priorities below the dedicated tee types so automatic selection does
   not change; they become available as manual, sticky choices.
4. **90 degree cross (item 5).** New type for `cross.cross`: straight
   trunk with two opposed taps, built from two tap layouts sharing a
   trunk. Each side takes the same `Attachment` and tap style options.
5. **Double wye (item 5).** New type for `cross.double_wye`: wye layout
   mirrored about the trunk, mitered and radius variants.
6. **`cross_generic`** stays the star-body fallback for `cross.generic`
   only.
7. **Loss.** No 4-port table exists in the reference. Keep
   `manifold_loss` (pairwise decomposition, `APPROXIMATION`). For a
   symmetric double wye splitting from one inlet, 14-14 Y and 14-13 I
   apply directly per branch pair.

Naming needs a decision before implementation (AGENTS.md says raise, do
not improvise). Proposed ids: `cross_tee_straight`,
`cross_double_wye_mitered`, `cross_double_wye_radius`.

Tests: classifier derived value, attachment auto-selection, loss variant
resolution, layout/measure parity.

### Stage 5: through fittings (items 4, 8, VAV)

1. **Separate offset and transition (item 8).** Today the three offset
   type-defs reuse `build_transition*` and even carry a `TransitionLength`
   property. Target structure, following SMACNA duct construction
   nomenclature:

| Type id | SMACNA name | Classifier match | Loss |
|---|---|---|---|
| `through_offset_angled` | Offset type 1 (angled) | `through.offset` | 14-10 K (round), 14-18 I, J |
| `through_offset_mitered` | Offset type 2 (mitered) | `through.offset` | 14-10 I (Z-shape), 14-18 L |
| `through_offset_radiussed` | Offset type 3 (radius, ogee) | `through.offset` | 14-18 K |
| `through_transition_concentric` | Concentric transition | `through.transition`, `alignment = concentric` | 14-11 A, B, C, D; 14-12 A, B |
| `through_transition_eccentric` | Eccentric transition | `through.transition`, `alignment` in `eccentric`, `double_eccentric` | 14-11 E; 14-12 A |
| `through_transition_offset` | Offset transition (size change plus jog) | `through.transition`, `alignment = offset` | transition and offset summed, `APPROXIMATION` |

   Offsets get their own module (`fittings/offsets.py`), their own
   properties (`OffsetLength`, `OffsetAngle`, `Radius`), and stop sharing
   transition code. The existing `through_transition_angled/mitered/radiussed`
   ids are retired; "angled/mitered/radiussed" describes how an offset is
   made, not a transition. Confirm the exact figure names against the
   SMACNA HVAC Duct Construction Standards before finalising labels, since
   that document is not in `reference/`.
2. **Fitting-derived values.** Transition included angle depends on the
   chosen `TransitionLength`, so it is a type-derived value, not a parser
   one. Add `computed_properties` output (`IncludedAngle`, read-only) and
   pass it to the loss call. This is the "separate vocabulary" that
   `TOPOLOGY_CLASSIFICATION.md` already anticipates.
3. **Obstruction (item 4).** `through_obstruction_generic`, inline kind:
   a cylinder crossing the duct. Properties `ObstructionDiameter`,
   `OffsetFromCentre`. Loss from 14-18 H. A flat-plate or rectangular
   obstruction variant can follow using the same body.
4. **VAV unit (item 3).** Replace the scaled-stub `through_vav_generic`
   with a box body: round inlet collar, casing `Length/Width/Height`,
   rectangular outlet, `TrimInlet`, `TrimOutlet`. Loss stays a user K or a
   pressure drop at design flow (add `LossMode`: `Coefficient` or
   `FixedPressureDrop`, which needs a small extension of `LossPath` or a
   converter inside `inline_device_loss`).
5. **Dampers.** Add `DamperType` (butterfly, gate, parallel, opposed) and
   `BladeAngle` to `through_damper_generic`; loss from 14-18 A to G.

### Stage 6: terminals, equipment, plenum (items 2, 3, 6, G10)

1. **Common terminal body.** Extend the terminal builder with a neck
   (collar) of `TrimNeck` length, then a face body. Every `end` type gets
   `TrimNeck` (G10). The neck profile is the connected duct profile; the
   face may be larger.
2. **Entries and exits (item 2).** Geometry is simple; value is in the
   loss tables from Stage 2.

| Type id | Body | Loss |
|---|---|---|
| `end_entry_plain` | duct end, optional wall flange | 14-15 A |
| `end_entry_bellmouth` | rounded lip | 14-15 B, C |
| `end_entry_conical` | cone or pyramid | 14-15 D, E |
| `end_hood_intake` | weather hood | 14-15 F |
| `end_hood_tapered` | tapered capture hood | 14-15 G |
| `end_exit_plain` | abrupt exit | 14-16 J |
| `end_exit_conical` | conical diffuser | 14-16 B |
| `end_exit_pyramidal` | plane or pyramidal diffuser | 14-16 C, D |
| `end_hood_exhaust` | exhaust hood | 14-16 A |

   All take an optional `ScreenFreeArea` that adds 14-17 A per Notes 9 to
   12. `end_intake_exhaust_generic` remains the catch-all.
3. **Diffusers, grilles, registers (item 2).** `end_diffuser_square`
   (ceiling, with `FaceSize`, `NeckSize`), `end_diffuser_round`,
   `end_diffuser_slot`, `end_grille_generic`, `end_register_generic`
   (grille plus damper K). No SMACNA table covers these; loss is
   manufacturer data, so keep `LossCoefficient` and add the same
   `FixedPressureDrop` mode as the VAV.
4. **AHU (item 3).** `end_ahu_generic`: box `Length/Width/Height`,
   connection position offsets on the face, `TrimNeck`. Loss from 14-11 F
   to J and 14-16 G to I, selected by a `FanConnection` enum. An AHU that
   joins supply and return in one object needs a multi-node component,
   which the data model does not have; that is deferred to Stage 11.
5. **Plenum (item 6).** Box with `Length`, `Width`, `Height`,
   `CentreOffsetX/Y/Z` from the node, and per-port `TrimLength` using
   Stage 3. Each port exits through the box face its direction hits; a
   port that misses the box is a geometry error. One shared builder,
   registered per topology to respect the id convention:
   `through_plenum_generic`, `branch_plenum_generic`,
   `cross_plenum_generic`, `multiport_plenum_generic`. Loss: each inlet
   as an abrupt exit into the box (14-16 J) and each outlet as an entry
   (14-15 A), which fits the `LossPath` model as one path per inlet/outlet
   pair and finally gives mixed multi-inlet/multi-outlet nodes a defined
   answer instead of `UNSUPPORTED`.

### Stage 7: SMACNA library rebuild (G2, item 9 wiring)

1. Rewrite `smacna` type-defs on the shared builders with construction
   thickness (offset) and flange specifiers declared as data: extend the
   existing `construction.features` mechanism so `transverse_flange`
   applies to every port of any fitting, not just
   `through_elbow_rectangular`.
2. Add `connection_lengths` to every type (falls out of Stage 1).
3. Add SMACNA-specific variants that only make sense there: vaned and
   splitter elbows (14-10 G, H), 3 to 5 piece round elbows (14-10 B),
   conical tees and wyes (14-14 B, C), 45 degree entry rectangular tee
   with damper or extractor (14-14 N to S).
4. Wire each type's `loss.variants` to the exact table for its profile and
   flow class. Delete the `smacna_loss.py` shim.
5. Produce the coverage matrix (type id by profile by flow class, with
   SMACNA table and `LossStatus`) as a generated section of
   `libraries/README.md`, backed by a test that fails when a type has no
   loss wired.

### Stage 8: analysis (G4, G11)

1. **Size changes only at reducers (G4).**
   - New concept in `analysis/sizing.py`: a **sizing section** is a
     maximal chain of segments that must share one cross-section.
     Segments are merged across the collinear run pair of a branch or
     cross node, and across bends. A section ends at a degree-2 collinear
     node (straight, offset or transition family, the place a reducer can
     exist), at a branch leg, and at terminals.
   - `NodeModel` already carries what is needed (topology, family); add
     the trunk pair indices to it in `_analysis_adapter`.
   - Each section is sized once for its largest flow (its upstream end).
     Constant velocity and friction rate: size for that flow. Static
     regain: regain is evaluated at section boundaries, not at each tee.
   - Network property `SizeChangePolicy`: `AtReducers` (new default) or
     `EverySegment` (current behaviour). Junction property
     `AllowSizeChange` (default true) on through nodes lets the user pin
     a straight coupling.
   - Result reporting: the Size Ducts panel lists where an extra reducer
     node would save material (section flow drops by more than a
     threshold) as advice, never an automatic edit of base geometry.
   - Fits the SMACNA tee tables, most of which assume `Ac = As`.
2. **Custom friction (G11).**
   - `analysis/friction.py`: a `FrictionModel` protocol returning Pa/m
     from (flow, section, roughness, air). Built in: Darcy-Weisbach with
     Altshul-Tsal (current), Colebrook. Custom: `TableFriction`
     (rows of flow or velocity by diameter, log-log interpolation) and
     `ExpressionFriction` (a restricted arithmetic expression in `Q`, `V`,
     `Dh`, `eps`, `rho`, evaluated with a whitelist parser, never `eval`).
   - Declaration: segment type-def `"friction": {"module", "function"}`
     for library-supplied models (flex duct, fabric duct), mirroring
     `loss`. Network property for a project-wide table (CSV path stored
     in the document). `_analysis_adapter` resolves it once into
     `SegmentModel.friction_evaluator`, the same closure pattern as
     `loss_evaluator`.
   - `physics._friction_rate_pa_per_m` and the three sizing solvers take
     the evaluator instead of calling Altshul-Tsal directly.
   - Add Fig. 14-4 flex compression and Fig. 14-5 density corrections as
     optional multipliers.

Tests: both items are pure analysis code, fully unit-tested.

### Stage 9: UI (G5, G9)

1. **Result tooltips (G5).** In `ui/Observer.py`'s `AirflowResultObserver`,
   add an `SoLocation2Event` callback that ray-picks against the existing
   arrow, plane and segment overlay separators and shows a `QToolTip` with
   the object's `Calc*` values: segments (flow, velocity, friction rate,
   pressure drop, static pressure at both ends) and ports (flow, velocity,
   K, loss status and source, static pressure). Throttle to mouse-idle.
   Keep the text builder in `core/_component_results.py` so it is
   unit-testable.
2. **Layer visibility per network (G9).** One `ShowLayer_<Role>` bool per
   `LayerRole` on `DuctNetwork`, plus `ShowFeatures`, all
   `Prop_NoRecompute`. `core/_component_appearance.py` already forces
   non-visible feature faces transparent; extend the same pass to layers
   whose roles are all hidden. A layer with several roles is shown if any
   of its roles is shown. Expose as checkboxes in Network Defaults and as
   a toolbar dropdown.
   Limitation to accept or solve: transparent faces remain pickable. If
   that is not acceptable, build a second display-only compound instead.

### Stage 10: custom geometry per fitting (G12)

Read as: override one placed component's shape without writing a library
type. If the request means something else, revisit.

1. `GeometrySource` enum on `DuctComponent` and `DuctSegment`: `Library`
   or `Custom`, mirroring `LossCoefficientSource`.
2. `Custom` takes a link to a document object or an external
   STEP/BREP/FCStd file, plus a port mapping (which named sub-element or
   placement corresponds to which connected port). Reuse
   `static_shapes.py`'s descriptor transform and port validation.
3. Trims come from the mapped port positions. Construction layers:
   accept one shape per declared layer, or a single shape assigned to the
   first layer.
4. "Save as library type": export the custom component as a static
   descriptor into a user library.

### Stage 11: gap analysis and API freeze (G13)

1. **Schema.** Add `schema_version` to `library.json` and type-defs, and
   `api_version` to `HVACLibraryAPI` and `HVACLossAPI`. Remove the dual
   forms: `generator` versus `geometry`, `loss_module`/`loss_function`
   versus `loss: {}`, `{"shape"}` versus `{"layers"}`. Publish JSON Schema
   files and validate at load.
2. **Stable identity.** `edge_key` regenerates on reload and is patched
   by remap helpers. Decide whether to persist a stable id on base
   geometry before freezing anything that stores keys.
3. **API surface review.** Mark each `HVACLibraryAPI` method public or
   private, with a deprecation path. Freeze the context dict keys.
4. **Data structures to review:** `GeometryResult`, `LossPath` and
   `LossEvaluation`, `NetworkModel` and friends, `HVACTypeMatchRequest`,
   property def schema, construction layer and feature defs.
5. **Gaps already visible** (to confirm and prioritise at this stage):
   - Multi-node equipment (AHU with supply and return, fan section) has no
     representation.
   - Terminal function (supply, return, exhaust, outdoor air) is not a
     network or classifier concept.
   - Looped networks are rejected by the flow solver.
   - No fan model: curves, system effect, operating point.
   - No leakage class, no thermal gain/loss, no acoustics, although
     `Construction` already exposes U-value and acoustic impedance.
   - No flexible duct or curved segment types in shipped libraries.
   - Inline catalogue is thin: silencer, filter, coil, fire damper,
     access door, flex connector are missing.
   - Oval and mixed-profile transitions classify as `transition_form =
     unknown`, so they never get an exact loss.
   - No bill of quantities or schedule output; README lists BIM data and
     detailing as goals.
   - SI units only in analysis.
   - Geometry failures: no systematic regression harness for OCC
     booleans. A headless smoke script that builds every type across a
     size matrix would catch most breakage without unit-testing shapes.

## 4. Decisions needed

| # | Question | Recommendation |
|---|---|---|
| 1 | Ids for the new cross types | `cross_tee_straight`, `cross_double_wye_mitered`, `cross_double_wye_radius` |
| 2 | Retire `through_transition_angled/mitered/radiussed` in favour of concentric/eccentric/offset | Yes, alpha allows it |
| 3 | Meaning of "Generic Ports" | Port roles plus per-port properties (Stage 3) |
| 4 | Meaning of "custom geometry for fittings" | Per-instance override (Stage 10) |
| 5 | Sizing sections: do bends end a section | No, only collinear through nodes do |
| 6 | Default `SizeChangePolicy` | `AtReducers` |
| 7 | Hidden layers: transparent or removed from display | Transparent first |
| 8 | Loss tables as Python literals or JSON data files | Python modules, simpler to test and diff |
| 9 | Plenum registered per topology (four type-defs, one builder) | Yes, keeps the id convention intact |

Answers received (12 November 2026):

- **1 and 2 (table rows above): accepted.** Cross ids are `cross_tee_straight`,
  `cross_double_wye_mitered`, `cross_double_wye_radius`. The three
  `through_transition_angled/mitered/radiussed` types are retired for
  `concentric/eccentric/offset`.
- **3, "Generic Ports":** fittings with an arbitrary number of ports must be
  modellable. Stage 3 stands as written (port roles plus per-port
  properties), with the weight on the variable-order case: `port_1..port_n`
  roles and `per_port` properties are the core, not an add-on. Named
  `TrimPortA..D` properties on generic cross/branch types become `per_port`
  too, so no type is capped at four ports.
- **4, "custom geometry for fittings":** the user selects a FreeCAD geometry
  object and defines custom ports on it to describe a fitting. Stage 10
  stands, with these points fixed: the source is a document object (not
  only a file); ports are defined by the user on that object (position,
  direction, profile and size per port), not inferred; and the port count
  is arbitrary, so it builds on Stage 3's per-port mechanism.

Decisions on the Stage 4 lateral tee and wye items:

| # | Question | Options | Recommendation |
|---|---|---|---|
| 10 | What should a lateral tee built "on the wye generator" look like? The wye generators split the main duct's section into two halves, one per leg, so a lateral built literally that way narrows the run to half its section and widens it again. | (A) Full straight run; the branch joins it through a radius or mitered bend, reusing the double wye's branch bend. (B) The literal wye layout, run necked to half. (C) Leave the lateral as it is: full run, plain straight stub. | A, as new types beside the existing one. |
| 11 | If A: ids, and what happens to the existing type. | `branch_lateral_tee_radius` and `branch_lateral_tee_mitered`; keep `branch_lateral_tee_generic` as the plain-stub fallback, or retire it and its `_lateral_tee_layout`. | The two ids as given; keep the generic one. Default: radius. |
| 12 | Should `branch_wye_mitered` / `branch_wye_radius` be offered on tee-shaped nodes? Their split layout is right where the flow really divides two ways, that is a bullhead tee (the common leg is the branch), and wrong where one leg runs straight through. | (A) Offer on `branch.tee` only when `common_leg` is `branch`, as a manual choice. (B) Offer on every tee and lateral. (C) Never. | A. It needs `common_leg` in the type's constraints, which the Change Type list now honours. |
| 13 | Which loss the new lateral types read. | The lateral rows of the tee tables through `branch_loss` (as the plain lateral does now), or the wye tables through `wye_loss`. | `branch_loss`: the run is straight, so the fitting is a tee to the tables. |

Answers received (12 November 2026): **10 to 13 accepted as recommended.**

- **10:** a lateral tee keeps its full straight run; the branch joins it
  through a radius or mitered bend, reusing the double wye's branch bend.
  It is not built on the wye generators' split layout.
- **11:** new types `branch_lateral_tee_radius` (the default) and
  `branch_lateral_tee_mitered`. `branch_lateral_tee_generic` stays as the
  plain-stub fallback, so `_lateral_tee_layout` stays too. This replaces
  Stage 4 item 2 as written in section 3 ("rebuild
  `branch_lateral_tee_generic` as a call into the wye layout, remove
  `_lateral_tee_layout`").
- **12:** `branch_wye_mitered` and `branch_wye_radius` are offered on a
  `branch.tee` node only when `common_leg` is `branch` (a bullhead tee),
  as a manual choice, never on a lateral or a straight-through tee. This
  narrows Stage 4 item 3 as written in section 3.
- **13:** the new lateral types read the tee tables through `branch_loss`.

## 5. Suggested order of work

Stage 0, then Stage 1 and Stage 2 in parallel, then 3, 4, 5, 6, 7.
Stages 8 and 9 fit anywhere after Stage 0. Stage 10 after 3. Stage 11
last, with its gap list updated as each stage closes.

## 6. Designs for the "design first" items

Written 12 November 2026. **Approved by the owner on 12 November 2026**
(6.3 after a revision). Each design ends with the questions it raises.

### 6.1 Fitting-derived values (Stage 5 item 2)

**Problem.** Some values a loss table needs come from the fitting the user
chose, not from the network: a transition's included angle depends on
`TransitionLength`; a radiussed offset's real radius can be smaller than
`OffsetRadius` (it is capped to what fits). Today the loss code recomputes
these with its own copy of the geometry's defaults, and the user never
sees them.

**Design.**

1. One pure helper per fitting kind computes these values from the ports
   and the resolved properties, with no shapes involved. Example:
   `fittings/transitions.py: transition_dimensions(api, ports, params)`
   returns `{"body_length", "included_angle", ...}`. The generator and the
   loss function both call it, so the two can never disagree.
2. The generator reports them as `computed_properties` in its result (the
   mechanism exists: `geometry_result.computed_properties`, applied by
   `_geometry_apply.apply_computed_properties`). The type-def declares them
   as ordinary properties with `"editor_mode": 1` (read-only) in a group
   named `Derived`. Names: `IncludedAngle`, `BodyLength` (transitions);
   `OffsetAngle`, `BodyLength`, `ActualRadius` (offsets).
3. The loss never reads these properties back. They are written at
   recompute time and go stale when a duct moves until the next recompute;
   the loss calls the helper instead. They are for display and reports.
4. Vocabulary: `derived_values` stays the classifier's (network-only
   facts, used for matching). The new values are "fitting-derived" and
   only exist on the object, after a build. `TOPOLOGY_CLASSIFICATION.md`
   gets one paragraph on the difference.

**Owner input:** review only; no open question.

**Status: done** (approved 12 November 2026). Helpers
`transition_dimensions`, `offset_dimensions` in `fittings/transitions.py`;
`transition_loss` and `offset_loss` call them. Read-only `Derived`
properties on the three builtin transitions, `smacna/through_transition_generic`
and the three offsets. The smoke run now records computed properties.

### 6.2 Flanges as construction features (Stage 7 g)

**Problem.** The shared finisher (`fittings/_common._add_flanges`) fuses
flange collars into the structural layer. A flange is then not a thing of
its own: it cannot be hidden, counted or given its own material, and it
makes the layer's wall-volume check meaningless. The `smacna` segments and
the PartScript elbow already use the other route, a
`construction.features` entry with its own generator, which stores each
feature as a separate shape (`Feature_<id>_Shape`).

**Design (the feature contract).**

1. `FeatureContext` gains `result`: the backend's normalized
   `GeometryResult` (layers and `connection_lengths`), so a feature
   generator can find a fitting's real end faces. Nothing else changes in
   the contract; features still return one shape or None.
2. A shared feature module, `library/fittings/features.py`
   (`"module": "shared:features"`), with `transverse_flange(api, ctx)`:
   - end faces: each connected port pushed out by its own connection
     length; a segment, which has no connected ports, uses its start and
     end points;
   - the collar sits on the outer face of the host layer: the port section
     grown by the thickness of every layer up to and including the host;
   - per-port switch: `ShowFlange<Role>` (role from `api.port_roles`,
     CamelCase, e.g. `ShowFlangeBranch`), then `ShowFlange<N>`, then
     `ShowFlange`, as `_flange_enabled` does today, per-port lists
     included.
3. `_finish` no longer adds flanges. `_add_flanges` is deleted.
   `_fuse_into_structure` stays for parts that really are one piece with
   the wall (an obstruction rod).
4. Every type-def that declares `FlangeThickness` gets the feature entry
   (host layer: its structural layer). `smacna/generators/features.py`'s
   own `generate_transverse_flange` is replaced by the shared one, so there
   is one flange builder. A test fails when a type declares
   `FlangeThickness` without a flange feature.
5. Visibility: the feature's `visible_parameter` (`FlangeVisible` where a
   type has it), and later Stage 9's network-wide `ShowFeatures`.

**Owner input:** review only; no open question. Implementation needs a smoke run.

**Status: done** (approved 12 November 2026). `FeatureContext` has
`host_layer_id` and `result`; `fittings/features.py: transverse_flange`;
`_add_flanges` and `smacna/generators/features.py` are deleted; all 13
flanged `smacna` types declare the feature. Smoke run: 333 valid as
before; every flanged `smacna` junction's casing lost the flange volume
and has a valid `transverse_flange` feature of about that volume; the
PartScript elbow's flange is unchanged (70320 mm3, same as the shared
elbow's). `smacna` segments checked by hand: flange on the outside of the
casing. The `samples` FCStd-template segment draws its own flanges and is
exempt.

### 6.3 Custom geometry per fitting (Stage 10)

**Problem.** Decision 4: the user selects a FreeCAD object and defines
ports on it to describe a fitting, with any number of ports.

**Owner answers (12 November 2026):**
- (a) A link to the custom shape is placed at the node; the ducts clip on
  to the defined port attachment points.
- (b) The custom object is the full modelled fitting, walls and thickness
  included. Ports are marked by a datum object (explore which).
- (c) Junctions only.

**Port marker: explored in FreeCAD 1.1.4.**

| Object | Attached to a duct end face | Verdict |
|---|---|---|
| `Part::LocalCoordinateSystem` (LCS) | `FlatFace`: origin at the face, Z along the outward normal; follows the face when the model changes | **Use.** Full frame: Z gives the port direction, X the width axis of a rectangular or oval port. Takes dynamic properties. |
| `Part::DatumPlane` | Same placement as the LCS | Works, but shows no X axis, which a rectangular port needs. |
| `Part::DatumPoint` | Position only, no direction | Not enough. |
| LCS on a circular edge, `Concentric` | Origin at the circle centre, Z along its axis, sign not guaranteed outward | Fallback for round ports; sign checked against the body. |

An `App::Link` to an `App::Part` that holds the body and the LCSs works:
the port's global placement is link x part x LCS, and `Part.getShape(link)`
returns the placed shape.

**Design.**

1. **The custom fitting** is an `App::Part` (a container) holding the
   user's modelled fitting (any objects with a `Shape`, walls included)
   and one LCS per port. Each port LCS carries dynamic properties in a
   group `HVAC Port`: `PortProfile` (`Circular`, `Rectangular`, `Oval`),
   `PortDiameter` or `PortWidth` / `PortHeight` (clear-air size of the
   opening), and an optional `PortName`. Z of the LCS points out of the
   fitting, X along the width of a rectangular or oval port. The same
   container can be used at many nodes.
2. **Defining ports.** Command "Add HVAC Port": select a planar end face
   of the fitting. It creates an LCS attached to that face (`FlatFace`,
   with an `AttachmentOffset` that moves the origin to the centre of the
   opening, because `FlatFace` puts it at the face's own surface origin,
   which is only the centre for symmetric faces), flips Z outward if
   needed, and fills profile and size from the face's inner wire (the
   air opening): a circle gives a diameter; a rectangle width and height
   and the X direction; a slot an oval; anything else an error asking for
   the size by hand. The user can edit every value afterwards.
3. **Using it.** `DuctComponent` (Primary only) gets `GeometrySource`
   (`Library`, `Custom`) and `CustomFitting` (`App::PropertyLink` to the
   container). With `Custom`, the component creates and owns an
   `App::Link` to the container, inside the junction's group, and keeps its
   `LinkPlacement` up to date. The component's own shape is empty; the
   link is what is seen, selected and exported. No construction layers
   are built: the walls are whatever the user modelled, with the user's
   own materials.
4. **Placement at the node.** The link is rigid, so the ducts must arrive
   the way the ports point. On each recompute:
   - Match ports to connected ducts: the node's port count must equal the
     custom port count. Each port is matched to the duct whose outward
     direction is closest (one-to-one, best total angle). A per-port
     override list `CustomPortEdgeKeys` (Stage 3 mechanism) fixes it by
     hand.
   - Rotation: the best fit of the port Z axes onto the duct directions
     (Kabsch). When all ports are parallel (a straight-through fitting)
     the roll about that axis is free: the port X axes are fitted to the
     ducts' profile X axes; for round ducts the roll stays 0.
   - Translation: least squares, so every port origin lies on its duct's
     centre line; any direction left free (ports all parallel) is fixed
     by putting the ports' centroid at the node.
   - A port more than 1 degree or 1 mm off its duct after the fit is a
     `GeometryError` on the component naming the port and the error.
5. **Ducts clip to the ports.** Each duct's trim is the distance along
   its axis from the node to its placed port origin, reported as
   `connection_lengths` exactly like a library fitting, so segments end at
   the port faces. A duct whose section differs from its port's size gets
   a warning (it needs a reducer), not an error.
6. **Loss.** The node keeps its library type for the loss (its topology
   and family do not change), or the user sets
   `LossCoefficientSource = Custom` (per-port K, exists). The port sizes
   from the LCSs are what the loss sees.
7. **Not included:** custom segments (answer c); building layers around a
   custom shape; saving a custom fitting as a library type (can follow,
   as a static descriptor generated from the container).

**Owner input:** approved 12 November 2026.

**Status: done, owner checked in the GUI 17 November 2026.**
- `library/custom_fitting.py` (pure, numpy): port matching (every
  assignment up to 7 ports, best total angle; `CustomPortEdgeKeys`
  overrides), rotation (Kabsch on port Z axes; roll from the X axes when
  all ports share one axis), translation (least squares onto the duct
  centre lines; free directions put the port centroid on the node),
  trims, tolerance errors and reducer warnings.
  `tests/test_custom_fitting_fit.py`.
- `core/_custom_fitting.py`: port markers (`Part::LocalCoordinateSystem`
  with `PortProfile`, `PortDiameter` / `PortWidth` / `PortHeight`,
  `PortName`), `add_port()` (attaches to a planar end face with
  `FlatFace` plus an offset to the opening's centre; reads round,
  rectangular and slot openings), the owned `App::Link`, and `apply()`.
- `DuctComponent`: `GeometrySource`, `CustomFitting`, `CustomPortEdgeKeys`,
  `CustomFitWarnings` (and internal `CustomLinkName`, `CustomPortMapJson`).
  A custom Primary skips the library build, keeps an empty shape, owns the
  link (shown under it in the tree, removed with it or when switched back
  to `Library`). The junction's trim peek uses the same fit. The loss sees
  the custom ports' sizes.
- Command `HVAC_AddCustomPort` ("Add HVAC Port") on the toolbar and menu.
- Checked in FreeCAD 1.1.4 headless: ports added from the end faces of a
  hollow round tee modelled off-origin and rotated; fitted to a node
  rotated 40 degrees: trims 300 / 300 / 250 mm, the linked shape's end
  faces exactly on the duct ends (0.0 mm), a reducer warning on the
  150 mm branch meeting a 200 mm duct. Rectangular and slot openings read
  as 400 x 200 with X along the width. Not checked: the whole network
  path (a network cannot be built headless: its task panel needs the
  GUI), the command itself, and the tree display of the link.
- Known limit: editing a port marker or the modelled body does not by
  itself re-fit the node; recompute the network.

### 6.4 Gap analysis and API freeze (Stage 11)

Written 13 November 2026. **For the owner's review; nothing implemented.**

**What a freeze means here.** After the freeze, a library written against
the frozen surface keeps working until a declared major version change:
its JSON type-defs, the context its functions receive, the
`HVACLibraryAPI` / `HVACLossAPI` methods it calls, and what it returns.
Everything else stays free to change.

**State today (checked in the code):**
- Versions: `HVACLibraryAPI.API_VERSION = 2`, `HVACLossAPI.API_VERSION = 1`,
  PartScripts `HVAC_PARTSCRIPT_API = 2` (checked at load), static
  descriptors `schema_version` 1 (checked). Type-defs and `library.json`
  carry no version.
- Dual forms still accepted: 134 type-defs use `"generator"`, 6 use
  `"geometry"`; a generator may return `{"shape"}` or `{"layers"}` (the
  shared finisher still returns `{"shape"}` for a fitting with no wall);
  the context carries both `params` and `properties` (same dict).
- Identity: a segment's `edge_key` is the sketch geometry `Tag`, or the
  wire's name plus index; a node key is built from its edges. Rebuilding
  a sketch or wire changes them; `DuctNetwork._edge_key_remap` and
  `_custom_loss.remap_persisted_edge_keys` patch the stored keys
  (`CustomLossCoefficientEdgeKeys`, per-port property lists, and now
  `CustomPortEdgeKeys`).
- No list says which `HVACLibraryAPI` methods are public; library code
  may call anything on it.

**Design.**

1. **Schema versions.**
   - `library.json` and every type-def get `"schema_version"`. Version 1
     is today's format, both forms allowed. Version 2 allows one form only:
     `"geometry": {"backend": "generator" | "partscript" | "static", ...}`
     (the generator module/function move inside it), results as
     `{"layers": ...}` only, context `params` only.
   - The loader reads both. A version 1 library loads with one warning
     per library naming what to change. A missing version means 1.
   - `tools/migrate_typedefs.py` rewrites a library to version 2
     (mechanical); the shipped libraries are migrated with it, and
     `_finish` returns `{"layers"}` always (a single roleless layer for no
     wall).
   - JSON Schema files for `library.json`, a type-def and a static
     descriptor go in `freecad/HVAC/library/schemas/`. FreeCAD does not
     ship `jsonschema`, so the loader keeps `validation.py` as the
     enforcing code, and a test checks the shipped libraries against the
     schema files (with `jsonschema` in the test environment only) so the
     two cannot drift.

2. **Stable identity** (the one irreversible choice).
   - (A) **Persisted ids.** The network keeps `EdgeIdentityJson`: one
     UUID per edge, with a fingerprint (end points, source object, index).
     On every sync, edges are matched to the stored ones by key, then by
     fingerprint; a match keeps its UUID, anything new gets one. Everything
     stored on objects (per-port lists, custom-port overrides, results
     keyed by edge) uses the UUID. The remap helpers go away.
   - (B) **Derived keys plus remap** (today), frozen as is.
   - Recommendation: A. Every stored per-port value (Stage 3), custom
     fitting overrides (6.3) and future schedules depend on it, and B's
     remap gets harder with each new stored list. A costs one sync step
     and a migration that assigns UUIDs to existing documents on load.

3. **Public API surface.**
   - Each API class gets a `PUBLIC` frozenset of method names. Everything
     else is renamed with a leading `_` (with a warning alias for one
     release). A test fails when code under `libraries/` or
     `library/fittings/` calls a non-public method, and when a public
     method is removed without a major version.
   - The contexts are frozen as documented key sets, one per call kind:
     geometry, connection lengths, loss, friction, feature. A test checks
     the code that builds each context only emits its documented keys.
   - `API_VERSION` becomes a (major, minor) pair; a library may declare
     `"requires_api": {"geometry": 3, "loss": 2}` in `library.json` and
     is refused with a clear message when the running major differs.

4. **Data structures to settle before the freeze:**
   - `GeometryResult`: layers only; `features`, `connection_lengths`,
     `computed_properties` as they are.
   - `LossPath` / `LossEvaluation`: as they are.
   - `NetworkModel` and friends: carry the stable edge id (2).
   - `HVACTypeMatchRequest`: as is, documented.
   - Property defs: `per_port`, `editor_mode`, `validation` documented as
     part of the type-def schema.
   - Construction layer and feature defs: as is, plus `FeatureContext`
     with `result` / `host_layer_id` (6.2).

5. **Gap list, proposed triage** (from Stage 11 item 5; "before" means
   before the freeze because it changes a frozen structure):
   - Before: terminal function (supply, return, exhaust, outdoor air) as
     a classifier and network concept, since type constraints and losses
     would read it; multi-node equipment (an AHU with supply and return),
     since it changes what a node is.
   - After: looped networks, fan curves and operating point, leakage,
     thermal and acoustic calculations, more inline devices (silencer,
     filter, coil, fire damper, access door, flex connector), bill of
     quantities, imperial units in analysis.
   - Done or partly done since the list was written: a geometry regression
     harness (`tools/geometry_smoke.py`), a flexible duct type, oval
     transitions read as rectangles (approximation).

6. **Freeze procedure:** migrate the shipped libraries to schema 2, land
   (2) and (3), write `CHANGELOG.md` with the compatibility policy, tag
   the commit.

**Owner answer (13 November 2026):** no backward compatibility: the
software is alpha. That settles (b) and (c) and simplifies the design:
- (1) There is one schema version, the new single-form one. The loader
  refuses anything else with a clear message; no version 1 reading, no
  load warnings. The shipped libraries are converted once (the migration
  script is a one-off, not kept).
- (2) If A: no migration of existing documents; ids are assigned on the
  next sync of a document, and old stored per-port lists may be reset.
- (3) No warning aliases: private methods are renamed outright.

**Status, public surface and contexts (3 of 6.4): done 13 November 2026.**
`HVACLibraryAPI.PUBLIC` / `HVACLossAPI.PUBLIC` list every public name
(private ones already carried a leading underscore, so nothing was
renamed); tests fail when a list drifts from its class or when library
code uses a non-public name. `library/contexts.py` documents the geometry,
loss and friction context keys; tests check every context core builds and
every key library code reads against it. `HVACLibraryAPI.API_VERSION` is
3 (the context and result contract changed); `library.json` may declare
`requires_api`, and a library written for another version is refused.
Deviation: API_VERSION stays one integer, not a (major, minor) pair.

**Status, single-form schema (1 of 6.4): done 13 November 2026.**
- Type-defs: `"geometry"` with a required `backend` (`generator` with
  `module` / `function`, `partscript` with `file`, `static` with
  `descriptor`); the top-level `"generator"` key is refused. All 130
  shipped type-defs converted.
- Results: `{"layers": ...}` only; `geometry_result.normalize` refuses a
  `{"shape"}` dict. New `HVACLibraryAPI.single_layer(context, shape,
  **extra)` puts a one-solid result on the type's first layer (markers,
  the duct closure, a fitting with no wall, static shapes, a PartScript
  returning a bare shape).
- Context: `properties` only (resolved values; undeclared supplied
  values pass through); `params` is gone. PartScript API bumped to 3.
- No JSON Schema files were added: `Library._load_type_def_file` stays the
  enforcing check (FreeCAD ships no `jsonschema`).
- Smoke run: 597 builds compared before and after, 0 differences.
- `smacna/branch_wye_radius` removed: with the 0.8 mm SMACNA wall it hangs
  inside an OpenCascade boolean for over 14 minutes on the first case (the
  builtin one fails in seconds, as known). Back when the wye fuse is fixed.

**(a) checked across save and reload (13 November 2026, FreeCAD 1.1.4).**
The owner asked to check the current scheme, which exists to keep keys
stable. Findings:
- A sketch geometry `Tag` survives in-session edits (deleting a line
  shifts the others' indices, their tags stay), but every tag is
  regenerated on reload. That is why the network re-matches segments by
  their persisted (`SourceObjectName`, `SourceIndex`) on the first sync
  after a reload and remaps every stored key (`_edge_key_remap`,
  `_custom_loss.remap_persisted_edge_keys`,
  `_port_properties.remap_port_property_keys`). It works, but each new
  stored list needs its own remap call (the custom-fitting
  `CustomPortEdgeKeys` of 6.3 has none yet).
- A Draft wire has no per-edge tag: its key is name plus index, stable
  across reload, shifting only if a point is inserted.
- **The sketch's own geometry id (`SketchObject.getGeometryId(i)`)
  persists across save and reload and survives index shifts; new
  geometry gets a new id.**

**Revised recommendation, option C: stable derived keys.** A sketch edge's
key becomes `<sketch Name>:g<geometry id>`, any other base edge's
`<object Name>:e<index>`. Both are the same before and after a reload, so
the reload re-match and all three remap helpers are deleted, and every
stored list (per-port values, custom loss K, custom port overrides) is
simply keyed by edge key. Identity changes only when the geometry is
really replaced (deleted and redrawn, or a wire point inserted), which is
the honest answer. Node keys are built from edge keys and become stable
with them. Cheaper than A (no id store) and sturdier than B.

**Owner answer (13 November 2026): C approved. Done.** `hvaclib.makeLineKey`
returns `<sketch>:g<geometry id>` / `<object>:e<index>`; the reload re-match
in `syncSegments`, `_edge_key_remap`, `remap_persisted_edge_keys` and
`remap_port_property_keys` are deleted (no backward compatibility: a
document saved before this gets fresh segments and components on its first
sync). Checked in FreeCAD: keys unchanged after deleting other geometry
and after a save and reload. `tests/test_edge_keys.py`.

### 6.5 Terminal function and multi-node equipment (Stage 11, before the freeze)

Written 13 November 2026 at the owner's request ((d) of 6.4: design both
before the freeze). **For review; nothing implemented.**

**Today.** A network is one tree of ducts. Its terminals each have a
`FlowBoundary`: one `Auto` terminal balances the rest (in practice the
fan or AHU connection), the others are `Fixed` (a design flow) or
`Closed`. Air direction comes from the base geometry's drawing direction.
Whether a terminal is a supply outlet or a return inlet is only implied
by that direction (`flow_class` `entry` / `exit` on end nodes). An AHU is
`end_ahu_generic`: one end node with one collar, so its supply and return
sides cannot both be modelled.

**Terminal function.**
1. `DuctNetwork.SystemType`: `Supply`, `Return`, `Exhaust`,
   `OutdoorAir`. One system per network (a supply tree and its return
   tree are two networks).
2. End junctions get `TerminalFunction`: `Auto` (from the system and the
   node's role), `Supply`, `Return`, `Exhaust`, `OutdoorAir`, `Source`
   (where the system meets its equipment). `Auto` resolves to `Source`
   for the balancing (`Auto` flow) terminal and to the system's own
   function for the others.
3. The classifier adds a qualifier `terminal_function` on end nodes
   (added to `KNOWN_QUALIFIER_KEYS`), so type constraints and loss
   variants can use it: diffusers only on `Supply`, grilles and
   registers on `Return` / `Exhaust`, intake hoods on `OutdoorAir`,
   exhaust hoods on `Exhaust`; an entry loss where air comes in, an exit
   loss where it leaves.
4. The flow solver checks direction against function: in a supply
   system air must leave at every `Supply` terminal. A terminal drawn the
   wrong way becomes a warning that names it ("drawn as an inlet in a
   supply system"); "Edit Duct Directions" stays the fix.
5. Results and display: per-system colours for the airflow overlay, and
   totals per system (supply total, return total) in the results panel.

**Multi-node equipment.**
1. A new document object, `HVACEquipment` (outside any network), with a
   list of ports. Each port: a name, a function (`SupplyOutlet`,
   `ReturnInlet`, `OutdoorAirInlet`, `ExhaustOutlet`), a frame and a
   section (the same `Part::LocalCoordinateSystem` markers with
   `PortProfile` / size as custom fittings, 6.3), and the network and
   terminal node it is connected to (network object plus stable node key,
   6.4 a).
2. Geometry: a library type of a new category `equipment` (several
   ports, built like any shared fitting: casing, collars, flanges as
   features), or a user model with port markers (6.3). `end_ahu_generic`
   is retired; its fan-connection loss (14-11 F to J, 14-16 I) moves to
   the equipment port.
3. Connecting: "Connect to Equipment" takes a network end node and an
   equipment port. The node's `TerminalFunction` becomes `Source` (supply
   outlet, exhaust outlet) or the matching sink (return inlet, outdoor
   air inlet). Its Primary component becomes an equipment connection: a
   collar only, the casing belongs to the equipment. The base geometry's
   end point must sit on the port; the command says by how much it is off
   rather than moving the user's sketch.
4. Analysis: each network is still solved on its own (no loops, no
   coupling of pressures in this stage). The equipment then reports
   across its networks: airflow per port, outdoor air as supply minus
   return when it has both, and the external static pressure each fan
   needs: the worst path of each connected network plus the equipment's
   own internal pressure drop (a property; coils and filters as a list
   later).
5. Data model: `NodeModel.equipment_port` (equipment name, port name);
   results gain an `EquipmentResult` per equipment.

**Owner answers (13 November 2026):** (e) separate networks per system,
joined by equipment; (f) terminal function defaults from the system
(`Auto`), settable per terminal; (g) equipment geometry only as user models
with port markers (the custom-model route exists for corner cases the
library cannot model; no equipment library types).

**Review fix (13 November 2026):** `Auto` first resolved from
`FlowBoundary` alone, and every new terminal starts at `FlowBoundary Auto`,
so a fresh network made every terminal its Source and offered no diffusers
until each boundary was set. `Auto` now follows the drawn direction (supply:
the terminal where air comes in is the Source, the rest are outlets; other
systems: the one where air leaves), falling back to the boundary only when
the direction is unknown. A balancing terminal that resolves to anything
but Source is warned about, once the network has exactly one.

**Status, terminal function: done, owner checked in the GUI 17 November 2026.**
`DuctNetwork.SystemType`; end junctions' `TerminalFunction` (`Auto`,
`Supply`, `Return`, `Exhaust`, `OutdoorAir`, `Discharge` -- added for an
outlet to outside, e.g. after an exhaust fan -- and `Source`), resolved by
`core/_terminal_function.py` during junction sync and stored as the end
node's `terminal_function` qualifier (a new `KNOWN_QUALIFIER_KEYS` entry);
changing either property re-syncs the network. Constraints in both
libraries: intake hood `OutdoorAir`, exhaust hood `Discharge`, diffusers,
grilles and registers `Supply` / `Return` / `Exhaust`. Calculate Airflow
and Size Ducts warn about each terminal drawn the wrong way for its
function. Not done: per-system colours (one network is one system, so the
existing network totals are the system totals). Tests:
`tests/test_terminal_function.py`.

**Status, equipment: done, owner checked in the GUI 17 November 2026.** `core/Equipment.py`:
`HVACEquipment` (`Model` = App::Part with port markers, each with an
`EquipmentPortFunction`: `SupplyOutlet`, `ReturnInlet`, `OutdoorAirInlet`,
`ExhaustOutlet`; `InternalPressureDrop`; `Connections`). Commands "Create
Equipment" (from a selected App::Part) and "Connect to Equipment" (a port
marker plus a duct end): the terminal becomes its network's Source and gets
`end_equipment_connection` (both libraries: a collar with the
fan-connection loss, `loss_equipment_connection`); a duct end more than
1 mm off the port, or a network whose `SystemType` does not match the port,
is reported, not changed. After each network's Calculate Airflow the
equipment stores that network's port flows and worst path and refreshes
`SupplyAirflow`, `ReturnAirflow`, `OutdoorAirflow` (outdoor-air ports, or
supply minus return), `SupplyFanStatic` (internal drop + worst supply +
worst outdoor-air path), `ReturnFanStatic` and `Report`.
`end_ahu_generic` is retired (its builder `boxes.build_ahu` and
`loss_ahu` stay in the API). Deviation: no `NodeModel.equipment_port`; the
equipment reads results after the solve instead. Fixed (14 November 2026): a duct
leaving an AHU's exhaust outlet to outside is a network whose Source
pushes air in; which way the Source moves air now comes from the connected
equipment port (`_terminal_function.source_feeds_air`: SupplyOutlet /
ExhaustOutlet push, ReturnInlet / OutdoorAirInlet draw, else the system),
so that Exhaust network's open ends resolve to `Discharge` and are not
warned about.
Tests: `tests/test_equipment.py`.

**Questions as asked:**
- (e) One system per network (supply and return as separate networks
  joined by equipment), or one network spanning both through the AHU?
  Recommended: separate networks. One network through the AHU would
  carry flow both ways and need the solver to handle loops.
- (f) Terminal function: keep `Auto` resolving from the system (so most
  terminals need no setting), or require it on every terminal?
- (g) Equipment geometry first as library types (an AHU with supply and
  return collars on chosen faces), or only user models with port
  markers to start with?

### 6.6 Robust branch geometry: plane-split wyes, inset branch bends

Written 18 November 2026 after the owner's GUI check found the round
bullhead radius wye failing (and called the radius tee and wye "finicky").
**Owner answers (18 November 2026):** (a) A, for both wyes, with the crotch plate; (b) B, with its margin; (c) yes, commit the sweep; (d) implement 6.6, and keep the radius wye in the Change Type list.

**Status: done, 18 November 2026; needs the owner's GUI check.** See "Implementation" at the end of this section.

**Evidence: a size and wall sweep.** The smoke run builds one node per
family; it hid the problem (the pending-items pass reported the round
bullhead fixed from that one node). A sweep over branch size ratio (0.5,
0.75, 1.0 of the run), branch angle (30, 45, 60 degrees), every profile
(round, rectangular, wide and tall oval) and wall build-up (none, 1 mm,
3 mm; smacna with and without 25 mm insulation), 300 mm run
(`tools/.smoke/robust_sweep.py`, not committed):

| Type | builtin_basic ok / cases | smacna ok / cases | Where it fails |
|---|---|---|---|
| `branch_wye_radius` | 76 / 144 | (not in smacna) | everywhere: every profile, with and without a wall |
| `branch_wye_mitered` | 130 / 144 | 79 / 96 | tall oval; round with a thick wall or insulation |
| `cross_double_wye_radius` | 60 / 72 | 33 / 48 | branch as large as the run |
| `cross_double_wye_mitered` | 70 / 72 | 43 / 48 | branch as large as the run, with a wall |
| `branch_lateral_tee_radius` | 63 / 72 | 40 / 48 | branch as large as the run |
| `branch_lateral_tee_mitered` | 66 / 72 | 45 / 48 | branch as large as the run |
| `branch_tap_mitered_shoe` | 72 / 72 | 45 / 48 | branch as large as the run, round, with a wall |
| `branch_tee_radius_center` / `_edge` | 90 / 90 | 58 / 60 | wide and tall oval, branch as large as the run |
| straight tee, straight / saddle / shoe taps, radius and mitered elbows | all | all | none |

**Comparison with `main`.** `main` built these fittings as air-space
solids only (no wall layers) and tried up to ten fuse orders for the
radius wye, keeping the first result OpenCascade called valid. That hid
the same fragility: Stage 7's stricter check found accepted radius wyes
that had dropped a leg or come out as fragments. This branch builds every
envelope once, in a fixed order, and checks the result, so the failures
now show.

**Causes.** Three patterns, all the same OpenCascade weakness: plain
booleans fail where two solids share a curved face or touch tangentially;
they are reliable where pieces meet on a plane or cross at an angle.

1. *Split-half sweeps (radius wye; mitered wye with a wall).* Each half
   of the split main section is swept round its own bend. The cut edge,
   swept along an arc, is no longer a plane: the two halves touch along
   the start and part tangentially. With a wall, each grown half reaches
   past the cut, so the halves also share curved faces in that strip.
2. *Coaxial branch-bend start (lateral tees, double wyes, mitered shoe).*
   The bend begins on the run axis with the branch's own section, inside
   the run. When the branch is as large as the run (in the bend plane),
   that section coincides with the run's own wall: two identical curved
   surfaces, the bend then leaving the run tangentially.
3. *Walls repeat every boolean.* Each construction layer builds its
   envelope again, so a fragile fuse is attempted two or three times per
   fitting, and each grown copy is closer to tangency. Insulation makes
   pattern 1 and 2 cases fail that build without it.

**Principles (for every branch fitting).**
- Pieces meet only on a plane, or cross at a clear angle. Never a shared
  curved face, never a tangent touch.
- Every cut is a plane cut decided by the layout (a `common` with a
  half-space), never a cut by a curved surface.
- Wall envelopes reuse the same planes; only the sections grow. So the
  grown pieces meet on the same planes as the air-space pieces.
- Where tangency cannot be avoided, the layout refuses before building,
  saying what to change. No retries, fuse-order searches or fuzzy booleans
  (the existing rule).

**A. Plane-split wyes (radius and mitered).**
1. Layout (unchanged): common port C, legs A and B, the split line across
   the main section in the legs' size proportion, the bend routes and the
   trims. New: the split *plane* Π, through the split line, containing the
   common axis direction and the normal of the legs' plane. Leg A lies on
   one side of Π, leg B on the other.
2. Each leg's bend is built with the **full** common section at its start
   (on the split station, centred on the common axis) and the leg's own
   section at its end: a sweep along the arc for the radius wye, the same
   gores as today for the mitered wye. No half sections, no corner-matched
   circle splits (`_wye_branch_end_wire`, `make_circular_wire_split_at`
   are no longer needed here).
3. Leg A's piece is its bend ∩ the half-space on A's side of Π; leg B's
   likewise. The two pieces meet face to face on Π: a plane, which a
   plain fuse handles. The main straight ends on the split station, its
   end face the union of the two pieces' start faces (planar again).
4. Wall envelopes: the same three steps with every section grown by the
   offset, cut by the same Π.
5. Crotch wall on an asymmetric wye. Where the legs differ (size or
   radius), the larger leg's section on Π reaches past the smaller leg's
   near the crotch, and there its air face lies on Π with no wall beyond
   it. The fix is one planar plate: the larger leg's grown section on Π
   minus the smaller leg's grown section on Π, extruded one wall
   thickness into the smaller leg's side. Its faces are planar or
   perpendicular to Π, so it meets the bends at an angle. A symmetric wye
   or bullhead needs no plate.
6. Trims and `measure_*` are unchanged (the routes are the same), so
   measure still equals build.
7. Removed: the split-half sweeps, `_wye_main_split_faces(curved=...)`
   and the narrowed strip added in the pending-items pass, and the radius
   wye's fixed fuse order (the pieces no longer depend on order).

**B. Inset branch-bend start (lateral tees, double wyes, mitered shoe).**
The part of the bend inside the run only has to stay inside the run's air.
Where the bend's start section would reach within a margin of the run
wall, it starts smaller: the start section is the branch section scaled
so it clears the run's inside face by max(10 % of the run's half-depth,
twice the total wall) on every side, and the sweep (or the first gore)
grows it to the full branch section along the bend. The bend then crosses
the run wall at an angle instead of running along it. Nothing changes
outside the run: the reduced part lies inside the run's air. The same
inset start fixes the radius tee's oval ratio-1 cases (its centre-aligned
body meets the run on the shared tangent plane, today patched by a 1 %
overlap; with the inset start the overlap is no longer needed).

**Acceptance.** The sweep above becomes a committed tool
(`tools/geometry_sweep.py`, same report as the smoke run). Target: every
case of the types above builds, except ones the layout refuses with a
message; symmetric wyes and bullheads build on every profile with and
without a wall. The smoke run must not lose a build. Shapes still need a
look in the GUI (the crotch plate in particular).

**Risks.**
- A full common section swept into a smaller or differently shaped leg
  can twist (round into rectangular); the existing split-circle start
  (`api.make_split_circular_wire`) is used where profiles differ.
- The crotch plate is new geometry; if its 2D difference on Π degenerates
  (legs nearly equal), it is skipped below a size threshold, which leaves
  a sliver without wall. To be measured by the sweep.
- The radius wye's look changes slightly at the crotch: the legs part on
  a flat face instead of along two curved ones (as the mitered wye does
  today).

**Owner input.**
- (a) Approve A for both wyes, including the crotch plate (5), or limit
  the radius wye to symmetric wyes and bullheads (refusing asymmetric ones
  with a wall)?
- (b) Approve B, with its margin (10 % of the run half-depth, at least
  twice the wall)?
- (c) Commit the sweep as `tools/geometry_sweep.py` and make it the
  acceptance check for fitting geometry changes?
- (d) Until this lands: leave the radius wye as it is (it fails on about
  half the sweep, on every profile), or take it out of the Change Type
  list for round ducts only?

**Implementation (18 November 2026).**
- A, `fittings/wyes.py`: `_wye_main_split` returns the half faces (they only place each leg's route) and the split plane. `_wye_leg_piece` builds a leg from the full common section: a straight piece to its bend's start, then a sweep (radius) or gores (mitered, `_mitered_bend` with `profile1`) into the branch, cut by the plane. A round section meeting one with corners is drawn as matching arcs (`_wye_matched_ends`). Both wyes share `_wye_envelope` (main straight, legs, plates, trims, one fuse, checked with `_is_union_of`). Removed: the split-half sweeps, the narrowed strip, `_wye_split_crosses_curve`, the radius wye's fixed fuse order (and its unit test, `tests/test_wye_split_rule.py`).
- Found by the sweep, not in the design: on 30 degree wyes with large legs the branch end crosses the split plane, so the cut would take part of the leg. The layout now grows that leg's radius by 25 % per step (up to 16 steps) until its end section, grown by the wall, lies on its own side (`_wye_end_crosses_plane`); BranchRadius is a minimum, as it already was for the tangent clearance. Before, these legs simply overlapped.
- Crotch plate (`_wye_crotch_plates`): needed where one leg's face on the plane minus the other's leaves a region at least a wall wide. Built as the leg's own face extruded one wall across the plane, minus the other leg's piece, so the plate shares the pieces' faces; a plate drawn from the 2D difference alone broke the fuse on most uneven wyes. Where that cut misfires (keeps more than 1.1 times what the faces allow), the 2D plate is used instead, left out when the other leg already holds it.
- B, `_common._inset_bend_start`: the start section is scaled (same shape) to clear the run's inside face by the margin, checked in 24 directions. Used by `crosses._double_wye_bend` (double wyes and both lateral tees), the mitered shoe, and the centre radius tee's sweep end (its 1 % overlap is gone).
- `tools/geometry_sweep.py`: the scratch sweep, committed; it adds an uneven wye (one leg at the ratio and 45 degrees, the other full size at 30 degrees) and the straight tee, taps and elbows. `tools/geometry_smoke.py` gained `build_entry` and `report_and_save` for it.
