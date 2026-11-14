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

## Unreleased (roadmap-stage-0)

API versions: geometry 3, loss 1, PartScript 3.

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
