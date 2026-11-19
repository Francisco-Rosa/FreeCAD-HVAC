# Project development rules

These rules govern how code is written and tested in this repository. They
are deliberately narrow — do not expand their scope beyond what is written
here.

For an overall picture of how the pieces fit together and execute (layers,
end-to-end sync/execute flow, type-selection subsystem), see
[`ARCHITECTURE.md`](ARCHITECTURE.md) before making structural changes.

## 1. Unit test policy

Unit tests are required for data-structure generation/maintenance modules
**and** for geometry-handling code (loading, dispatch, port/property
handling). They are **not** required for the actual geometry-generation
code inside library parts, which is still in an exploratory/testing stage.

**In scope for unit tests:**

*Data structure generation/maintenance:*
- `freecad/HVAC/core/Network.py`
- `freecad/HVAC/core/NetworkParser.py`
- `freecad/HVAC/core/FlowNetwork.py`
- `freecad/HVAC/core/Segment.py` / `freecad/HVAC/core/Junction.py` (data/state handling, not shape generation)
- `freecad/HVAC/core/AirflowSolver.py`, `freecad/HVAC/core/DuctSizer.py`, `freecad/HVAC/core/_analysis_adapter.py`
- `freecad/HVAC/analysis/` (the whole package: `model.py`, `physics.py`, `flow.py`, `pressure.py`, `sizing.py`, `paths.py`, `balancing.py`) — pure engineering domain code, no FreeCAD dependency

*Geometry handling (loading, dispatch, property/port handling — not shape construction):*
- `freecad/HVAC/library/Library.py` — type-def loading/registry, `resolve_params`, backend dispatch in `build_geometry`
- `freecad/HVAC/library/validation.py` — property validation
- `freecad/HVAC/library/static_shapes.py` — descriptor loading, placement transform, port validation
- `freecad/HVAC/library/partscript_shapes.py` — module loading/caching and `generate()`/`validate()` contract checking (not the PartScript's own geometry code)
- `freecad/HVAC/library/library_api.py` / `_api_ports.py` (the `HVACLibraryAPI` class is assembled in `library_api.py` from the `_api_*.py` mixin modules) — property/port/context helpers only: `vec`/`xyz`/`unit`/`angle_between`/`average_point`, `center_from_context`, `connected_ports`, `port_*` accessors, `copy_port`, `build_trim_rec_from_*`, and the loss-orchestration methods (`elbow_loss`, `transition_loss`, `branch_loss`, `manifold_loss`, `terminal_component_loss`, `inline_device_loss`)

**Out of scope for unit tests** (geometry generation inside library parts —
still in testing/exploratory stage, do not write tests for these):
- Any `generators/*.py` module inside a library (e.g. `smacna/generators/segments.py`)
- Any PartScript model file under a library's `models/*.py`
- `freecad/HVAC/library/template_shapes.py` — an FCStd-template shape-generation primitive, used the same way a generator uses `make_straight_shape`
- The shape-construction primitives of `HVACLibraryAPI` (`_api_profiles.py`, `_api_solids.py`, `_api_booleans.py`, `_api_recipes.py`): `make_profile_frame`, `make_line_edge`, `make_wire_from_edges`, `make_rectangular_wire`, `make_circular_wire`, `make_oval_wire`, `make_section_wire(_from_port)`, `make_section_face(_from_port)`, `make_straight_shape`, `make_curved_shape`, `make_pipe_shell`, `make_loft`, `line_wire`, `arc_wire`, `fuse_shapes`, `shape_from_fcstd`
- Any other code whose job is producing/assembling `Part.Shape` geometry

If it's unclear which bucket a module or function falls into, ask before
adding tests — do not default to writing (or skipping) tests based on
guesswork.

## 2. Naming convention

The library naming convention documented in
[`freecad/HVAC/libraries/README.md`](freecad/HVAC/libraries/README.md) is
the single source of truth and must be followed everywhere a type is named,
including PartScript files.

- **Segments**: `<profile>_<shape>` (e.g. `circular_straight`, `oval_straight`, `rectangular_straight`).
- **Junctions**: `topology_family_sub_classification`, where `topology` is
  one of `through`, `branch`, `cross`, `multiport`, `end` (must match the
  parser's classifier vocabulary), `family` is the specific fitting family
  (omit it if the type is generic across the whole topology), and
  `sub_classification` is `generic`, `marker`, or a backend name (reserved
  for `samples`).

**This naming convention also applies to PartScript files** (`models/<name>.py`)
and any other per-type model file (`.FCStd`, descriptor `.json`, `.step`) —
the file name must match its type-def `id` exactly, so a type-def, its
PartScript/model file, and any generator entry point all use the same name.
See "Model file naming" in
[`freecad/HVAC/libraries/README.md`](freecad/HVAC/libraries/README.md) for
the full rule, including the shared-model-file exception.

Do not invent alternate naming schemes for new segment/junction types or
model files. If a new case doesn't fit the documented convention, raise it
rather than improvising.

## 3. General development guidelines

- **Respect the layering** described in the root `README.md`: network
  container (`Network.py`) → topology/parsing (`NetworkParser.py`) →
  generated objects (`Segment.py`/`Junction.py`) → library layer
  (`Library.py`/`library_api.py`/JSON type-defs). Don't reach across layers
  (e.g. don't hardcode fitting-specific logic into `NetworkParser.py` when
  it belongs in a library type-def).
- **New segment/junction types are added as library data** (JSON type-defs
  + a geometry backend), not by hardcoding new cases into core modules. Core
  code should stay generic across library-defined types.
- **External/library code uses only `HVACLibraryAPI`** (`library_api.py`)
  rather than importing internal HVAC modules directly — this is documented
  as the stable public surface for generator/PartScript authors.
- **New geometry backends aren't invented ad hoc.** Use one of the three
  documented mechanisms (PartScript, static BREP/STEP, legacy generator
  function) — see `freecad/HVAC/libraries/samples/README.md` for how to
  choose between them.
- **Follow the existing library directory layout** (`generators/`, `models/`,
  `types/segments/`, `types/junctions/`) for new library content even though
  it isn't hardcoded — every shipped library follows it.
- **Match the existing SPDX/LGPL file header** on new Python files (see any
  existing module under `freecad/HVAC/` for the exact block).
- Keep changes scoped to what's asked — this project is early-stage and
  under active restructuring, so avoid speculative abstractions or
  refactors bundled into unrelated changes.

## 4. Code comments

This project comments more than the general default minimal style: the
goal is for someone reading a module for the first time to follow what's
happening without having to reverse-engineer it from the code alone.

- Write comments in plain, simple English — avoid dense, jargon-heavy
  prose. Explain it the way you'd say it out loud to a colleague, not the
  way you'd write a spec.
- Keep comments concise: 1-2 lines is normally enough for a given point.
- Beyond function/class docstrings, add short inline comments marking the
  logical steps of a non-trivial multi-step function (e.g. "Step 1: ...",
  "Step 2: ...") so its process flow can be followed without tracing the
  code line by line.
- Still explain the *why* behind non-obvious decisions (hidden constraints,
  invariants, workarounds) — simplify the wording, don't drop the
  substance.
- This is a repo-wide style. When substantially editing a module, bring its
  comments in line with this style rather than leaving old dense/cryptic
  ones sitting next to new ones.

## 5. Python formatting

AI agents must use the following Ruff settings when generating or editing
Python code:

```toml
line-length = 120

[format]
skip-magic-trailing-comma = true

[lint]
select = ["E302", "E303", "I"]

[lint.isort]
split-on-trailing-comma = false
```

Run Ruff's selected lint fixes and formatter on the Python files changed
by the task, then verify that lint and format checks pass. Enable preview
for the lint command if the installed Ruff version requires it for E302
and E303. Do not reformat unrelated files.

## 6. Rule stability

Do not modify this file, or otherwise change the rules above, without
explicit instruction to do so. Encountering a case these rules don't cover
is not sufficient grounds to edit them — flag it instead.
