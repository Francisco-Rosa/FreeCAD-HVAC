# HVAC libraries

An HVAC library is a directory with a `library.json` manifest and its
type-defs; every directory under `freecad/HVAC/libraries/` (or another
configured search path) that has one is loaded. Three ship here:

- **`builtin_basic`** -- generic types, always available.
- **`smacna`** -- SMACNA sheet-metal duct and fitting types, for day-to-day
  modeling.
- **`samples`** -- one minimal example of each geometry backend (not for
  modeling).

Documentation:

- [Writing an HVAC library](../../../docs/library-guide.md) -- the guide:
  layout, `library.json`, geometry backends, what library code may do,
  construction, losses, type selection, checking a library.
- [Type-def reference](../../../docs/type-def-reference.md) -- every key of a
  type-def file.
- [Library API reference](../../../docs/library-api.md) -- the geometry and loss
  APIs and the context keys (generated).
- [Loss coverage](../../../docs/loss-coverage.md) -- the loss function of every
  shipped junction type (generated).

The naming convention below is the single source of truth for type ids and
model files (see `AGENTS.md`).

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
  `wye`, `elbow`, `transition`, `damper`, `vav`, `silencer`, `filter`, `coil`,
  `fire_damper`, `access_door`, `flex_connector`, `diffuser`, `fan_source`,
  `intake_exhaust`, `terminal`, ...). Omit this token (collapsing to just
  `topology_sub_classification`) when the type is generic across every
  family in its topology rather than one specific fitting -- e.g.
  `through_generic` covers straight/bend/offset alike, vs.
  `through_straight_generic` which is straight-specific.
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
| `branch_tee_straight` | branch | tee | straight (its construction; `radius_center`, `radius_edge` alike) |
| `branch_wye_mitered` | branch | wye | mitered (`radius` alike) |
| `branch_generic` / `branch_marker` | branch | *(all)* | generic / marker |
| `through_elbow_radius` | through | elbow | radius (`mitered`, `vaned`, `rectangular` alike) |
| `through_straight_generic` | through | straight | generic |
| `through_transition_concentric` | through | transition | concentric (its alignment; `eccentric`, `offset` alike) |
| `branch_tap_straight_damper` | branch | tap | straight_damper (a SMACNA-only variant, manual choice) |
| `through_damper_generic` | through | damper | generic |
| `through_vav_generic` | through | vav | generic |
| `through_fire_damper_generic` | through | fire_damper | generic |
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
geometry backend: `smacna/types/junctions/through_elbow_rectangular.json` pairs with
`smacna/models/through_elbow_rectangular.py`, and
`samples/types/junctions/end_diffuser_static.json` pairs with
`samples/models/static_diffuser.json`/`.step` (a static descriptor may point
at a differently-named source file, but the descriptor JSON itself should
still follow the type id where practical). When a library reuses one model
file across several type-defs (e.g. one PartScript parametrized by
`profile`), name the file after the shared generic id, not any one caller.
