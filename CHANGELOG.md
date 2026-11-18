# Changelog

## Compatibility policy

The software is alpha. Until a release is tagged, nothing is kept backward
compatible: documents and libraries made with an earlier version may need
to be rebuilt.

What a library may rely on is fixed and checked by tests:

- the names in `HVACLibraryAPI.PUBLIC` and `HVACLossAPI.PUBLIC`;
- the context keys in `freecad/HVAC/library/contexts.py`;
- the type-def format described in `freecad/HVAC/libraries/README.md`
  (`geometry.backend`, results as `{"layers": ...}`).

A change to any of these raises `HVACLibraryAPI.API_VERSION` or
`HVACLossAPI.API_VERSION`. A library declares the versions it was written
for in `library.json` (`"requires_api"`) and is refused by any other.

## Unreleased

- SMACNA library brought in line with builtin_basic: `branch_wye_radius` is back (removed on 13 November 2026 when
  its fuse hung; design 6.6 fixed that), and curved segments (`circular_generic`, `oval_generic`,
  `rectangular_generic`) and the flexible duct (`circular_flex`) are added. Before, an arc drawn in a SMACNA network
  had no segment type.
- SMACNA type ids and choices follow builtin_basic: `through_elbow_generic` is now `through_elbow_radius`;
  `branch_tee_generic` and `branch_wye_generic` are replaced by `branch_generic`; `through_straight_generic` is added
  and is the automatic choice on a straight node; the mitered elbow defaults to one cut. A document using a removed id
  needs its fitting type chosen again.
- A route drawn with "New Curved" (a spline) gets the flexible duct by default, where the library has one for the
  profile (round); other profiles, and arcs, keep the curved duct. A type chosen by hand stays.
- SMACNA flexible duct draws its wire-helix ribs as a feature (`flex_ribs`: `RibPitch`, `RibWidth`, `RibHeight`);
  builtin_basic's stays a plain round duct.
- A segment's flanges face along its path at each end; on a curved segment they used to follow the chord.
- A value typed in the property editor is synced when it is entered (Enter, or leaving the field), not on every
  keystroke. A property set from a script, outside a transaction, still syncs at once.

- Radius tees and lateral tees have one radius: `ElbowRadius` is gone from them, and a face-mounted branch uses
  `BranchRadius` for its elbow. A document that set `ElbowRadius` on one of these types loses that value.

- Branch geometry rebuilt for robustness (design 6.6). Wyes (radius and mitered) are split by a plane: each leg is
  built from the full common section and cut by the split plane, with a flat wall plate in the crotch of an uneven wye.
  Legs at a narrow angle get a larger bend radius until they part (`BranchRadius` is a minimum). Lateral tees, double
  wyes, the mitered shoe and the centre radius tee start their bend smaller inside the run, so it crosses the run wall
  at an angle. `tools/geometry_sweep.py` builds these fittings across sizes, angles, profiles and walls: every case
  builds.
- Radiussed offset: `OffsetLength` 0 (the new default) makes the offset as long as its arcs need.
- Drawn as features: turning vanes, splitter vanes, the SMACNA tap dampers, extractor blades, filter media pleats and
  the coil block with its header connections.
- A return duct into an equipment port of another size reads the transition tables (14-11 / 14-12).
- Size Ducts panel: a Friction section (model, CSV chart with Browse, expression).

- Inline devices in both libraries, each a manual choice on a straight node: silencer, filter (pressure drop by
  condition: clean, mid-life, final), coil, fire damper (frame and curtain pack drawn as a feature), access door
  (door panel on a chosen side, a feature) and flexible connector. One loss function, `loss_inline_device`.

- The saddle (conical) tap is offered on lateral tees; side-mounted it reads SMACNA 14-14 C (45 degrees).
- Face-mounted round tees with the collar rolled 45 degrees (`CollarRoll`) read 14-14 D and F (plain tap) or G and H
  (saddle tap), for a branch square or at 45 degrees to the main.
- A conical tap more than 10 degrees from the printed 45 or 90 degrees is reported as an approximation.

## API freeze 1 (tag `api-freeze-1`, 17 November 2026)

API versions: geometry 3, loss 1, PartScript 3. The library surface above is frozen
at these versions; a change to it raises the version.

- Libraries: one type-def form (`"geometry": {"backend": ...}`), one result
  form (`{"layers": ...}`, `HVACLibraryAPI.single_layer` for one solid), one
  context key for property values (`properties`).
- Edge keys are stable across save and reload (sketch geometry ids).
- Networks have a `SystemType`; terminals a `TerminalFunction`.
- HVAC equipment joins networks: an App::Part (the modelled unit) made equipment, its port markers inside it.
- Custom fittings: a user-modelled fitting linked at a node, ducts trimmed to its port markers.
- Equipment and custom fittings are set up in one panel (ports by kind, X/Y offset from a face's centre);
  the separate "Add HVAC Port" command is gone.
- Ducts drawn to end on equipment or custom fitting ports attach automatically: an equipment port is connected
  to its duct end, and the ends on a custom fitting become one junction using the fitting where it is modelled
  (`CustomPlacement` "In place").
- Result labels lie flat on their planes again; they flip or turn a quarter turn only when seen from behind or
  below.
- Pressure balancing keeps sizing sections whole (a section shared with the critical path is reported, not
  shrunk) and keeps the reducer advice.
- A fitting whose geometry fails is drawn as a fallback (end-marker crosses on its duct ends, pulled back slightly
  when the node has two or more ducts) instead of keeping a stale shape; its GeometryError says why. Line-only
  shapes (the fallback, end markers) stay in the displayed shape, so they show and can be picked.
- Taps and tees whose branch crosses the edge of the run are built: the branch is moved in until it fits (onto the
  run axis for the radius tees) and an offset piece, at most 30 degrees, carries it back to its own axis.
- Face-mounted saddle and shoe taps keep their conical or shoe collar. `CollarRoll` rolls a face-mounted collar
  round a round run towards the branch (SMACNA 14-14 D, F to L, "rolled 45 deg"), with a shorter elbow.
- The equipment connection reaches the equipment port it is connected to: a transition at TransitionAngle from the
  port's own profile and size (read off the port marker, i.e. the equipment's collar face) to the duct, shaped as
  its FanConnection names (SMACNA 14-11 F to J: symmetric, top level, top 10 degrees down or up, pyramidal).
  FanOutletWidth / FanOutletHeight now default to that port (0) for the transition and the system-effect loss.
- Dampers show their blades at the current position and an operator: a hand quadrant (its lever shows the blade
  position) or an actuator, on the side of the duct and turned the way `OperatorSide` / `OperatorRotation` say.
- Diffusers, grilles and registers have a face instead of an open end, in a pattern picked with `FacePattern`
  (louvered, plaque, perforated, swirl; slots with or without deflectors; single or double deflection, egg crate,
  perforated; a register adds damper blades). In `smacna` every size of the pattern is a property.
- A sync rebuilds only what changed. It used to mark every fitting for recompute on every sync (and rewrote
  labels FreeCAD had made unique, and unchanged ports), so any property edit rebuilt the whole network.
  Reset to Defaults rebuilds only the objects it changes. Reload Libraries rebuilds everything.
- Equipment models in a library (`<library>/equipment/*.json`, generators in `shared:equipment`): an air handling
  unit and a fan in `builtin_basic`. "Add Equipment from Library" places one with its ports and snap points; its
  Library drop-down (libraries with equipment models, starting on the active network's default) picks the models
  listed.
- A network fed by an equipment outlet (e.g. an AHU exhaust outlet to outside) takes its air direction from the
  port: its open ends are Discharge terminals.
- Lateral tees can be face-mounted (`Attachment`); wyes on a bullhead tee use the bullhead loss.
- Plenum sizes left at 0 grow so every duct fits on its face.
- Fittings are built once, with no retries or fuse-order searches; failures are found by layout and volume checks and
  reported. The radius wye refuses a wall where its split crosses a curved side (round, tall oval: use the mitered
  wye) and builds on the oval at its default radius; `api.make_circular_wire_split_at` added.
- Layer visibility has its own command: the toolbar button drops down the switches, the menu and Tasks entry open a
  Layer Visibility panel; the switches are no longer in Network Defaults. Toolbar regrouped: Renumber with the network
  commands, Layer Visibility with the select-all commands.
- The equipment connection's transition runs from the port where it really is to the duct where its Attachment /
  Offset put it, and only the FanConnection choices that describe it are offered: "None" alone until the duct end
  is on an equipment port that discharges into it; then the one SMACNA 14-11 transition that matches (symmetric
  sides straight; asymmetric top level / 10 down / 10 up by the slope of the side that moves least; pyramidal for
  anything else), none when the port is the duct's section in line. FanConnection no longer shapes the transition,
  only the loss table. FanOutletWidth /
  FanOutletHeight are read-only and show the port's size; the loss uses the port's own area. A geometry backend
  may return `"property_choices": {name: [choices]}` to narrow any drop-down this way.
- Editing a duct's or a fitting's size or type parameter in the property editor re-syncs the network, so the
  fittings at the duct's ends and the ducts at the fitting's ports follow (they used to keep stale geometry until
  the next sync).
- "Connect to Equipment" is gone: routing a duct to end on a port connects it. Equipment and custom fittings are
  made with "Create Custom Equipment" / "Create Custom Fitting"; "Edit Ports" (with the edit tools) opens the
  port panel that suits the selected one. New icons for these and for Add Equipment and Layer Visibility.
- Create / Edit Equipment and Custom Fitting also take a plain solid (a Part cube, a body) that sits in no App::Part:
  it is put in a new App::Part first. Both commands appear in the Tasks pane when such a model is selected.
- Equipment and custom fitting panel: one Port box that follows the 3D selection (a face: new port; a marker or list
  row: edit it; nothing: a hint); the junctions a custom fitting fits (port count and directions, end nodes for a
  one-port fitting) are a list synced with the 3D selection both ways and coloured orange while the panel is open
  (pre-selection and selection still highlight them). Port markers are hidden when the panel closes; every
  equipment port has a snap point (a `Part::Vertex` attached to its marker) so a duct can be drawn onto it.
- Sizing changes duct size only at straight-through junctions by default (`SizeChangePolicy`
  `AtStraightJunctions`, `AtInlineNodesOnly`, `EverySegment`); pluggable friction models.
- Automatic fitting selection prefers mitered and straight types; bend radii clamp to half the duct plus the wall.
- Hidden construction layers are left out of the displayed shape instead of drawn transparent.
- SMACNA library: the full builtin_basic type set with sheet-metal walls, insulation and flanges as construction features.
- Result tooltips; per-network layer visibility; per-port values table.
- "Add Equipment from Library" is "Add Equipment", next to Create Custom Equipment / Custom Fitting, and in a
  "Fittings and Equipment" Tasks group while a network is active and nothing is selected.
