# Samples library

This library is **not** meant to be modeled with directly. It exists purely as a
reference: each type here demonstrates one of the ways a library type-def can
produce geometry (a "geometry backend"), so a library author can see a working,
minimal example of each before writing their own. `smacna` and `builtin_basic`
ship the types actually meant for day-to-day use.

There are three ways to wire geometry to a type-def. All three receive the same
`context` dict (`hvac_api`, `loss_api`, `library_id`, `start_point`/`end_point`
for segments or `connected_ports` for junctions, `properties`, ...)
and must return the one result form:

- `{"layers": {"casing": {"shape": <Part.Shape>}, "insulation": {"shape": <Part.Shape or None>}}}`
  -- for a type with more than one construction layer (e.g. a casing plus
  its own insulation solid, as in `smacna/models/through_elbow_rectangular.py`,
  `library/fittings/elbows.py:build_elbow`). Layer ids are whatever the
  type-def's own `"construction"` block declares (see
  `freecad/HVAC/libraries/README.md`) -- `build_geometry()` stamps each
  returned layer's semantic roles on from there.

Either form may also include `"connection_lengths"` for junctions that trim
the connected segments, exactly as before, `"computed_properties"`
(`{name: value}` for declared, usually read-only, properties), and
`"property_choices"` (`{name: [choices]}`: a drop-down offers only these of
its declared `validation.enum`, e.g. only the fan connections that suit the
outlet; a value no longer offered falls back to the default). See
`freecad/HVAC/library/geometry_result.py` for the full `GeometryResult`/
`LayerGeometry` contract every backend's return value is normalized into,
`freecad/HVAC/library/Library.py:build_geometry` for the exact dispatch,
and `freecad/HVAC/library/library_api.py` for the full `HVACLibraryAPI`
surface available as `context["hvac_api"]`. Fitting-loss modules receive the
separate `HVACLossAPI` surface as `context["loss_api"]`; see
`freecad/HVAC/library/loss_api.py`. Their loss context also carries the
component's own `construction` and resolved `hydraulic_roughness_mm`, with
the network roughness used only as a fallback.

## Generator context

The full set of keys a backend can rely on being present in `context`:

- `hvac_api` -- the `HVACLibraryAPI` class itself (`freecad/HVAC/library/library_api.py`), the only sanctioned entry point into geometry/port helpers.
- `loss_api` -- the `HVACLossAPI` class (`freecad/HVAC/library/loss_api.py`); loss modules only.
- `library_id` -- this library's own `id`, matching its `library.json`.
- `properties` -- this type-def instance's resolved property values (`HVACLibrary.resolve_params`).
- Segments only: `start_point` / `end_point`.
- Junctions only: `connected_ports` -- one dict per connected port (`position`, `direction` (outward, away from the node), `profile`, `section_params`, `profile_x_axis`, `edge_key`, ...) -- see `HVACLibraryAPI.connected_ports` / the `port_*` accessors.
- Junctions only: `center_point` -- the node's representative point (falls back to the average of `connected_ports`' positions, via `HVACLibraryAPI.center_from_context`, when absent).
- Junctions only: `analysis` -- the parent junction's full node-topology analysis dict (`NetworkParser.JunctionAnalysis`, propagated through `Component._parentAnalysis`/the junction's own `AnalysisJson`; field meanings are documented in full in `freecad/HVAC/core/TOPOLOGY_CLASSIFICATION.md`). Notably: `collinear_pairs` / `orthogonal_pairs` (each entry `{"a": i, "b": j, "angle": ..., "eccentricity": ...}`, `i`/`j` indexing into this same `connected_ports` list), `edge_angles`, `edge_eccentricities`, `is_coplanar`, and the same `degree`/`topology`/`family`/`family_key` the classifier used to pick this generator in the first place.

  A degree-three tee/tap generator that needs its two run ports and remaining branch port should call `HVACLibraryAPI.run_branch_ports(context)`. For other topology-specific inspection, use `HVACLibraryAPI.collinear_port_index_pairs(context)`. Both read the classifier's result rather than re-deriving collinearity with a separate tolerance/judgment call, which could silently disagree with the family decision that selected the generator. `analysis` is empty (`{}`) for a synthetic context (e.g. most unit tests); `run_branch_ports()` raises a clear `ValueError` in that case rather than guessing the run pair.
- `hvac_api_version` -- the `HVACLibraryAPI.API_VERSION` this context was built against.
- Fitting-loss context only (`context["loss_api"]` callers): `construction` (this component's own resolved `Construction`) and `hydraulic_roughness_mm` (network default used only as a fallback).

## 1. PartScript (`"geometry": {"backend": "partscript", "file": "..."}`)

A plain Python file, loaded and executed directly (`freecad/HVAC/library/partscript_shapes.py`),
with access to every geometry primitive through `context["hvac_api"]`
(`make_profile`, `sweep`, `loft`, boolean operations, ...). It must set
`HVAC_PARTSCRIPT_API = 3` and define
`generate(context) -> {"layers": ...}` (a bare `Part.Shape` is also
accepted and put on the type's first layer; an optional `validate(context)` runs
first if present). This is the preferred backend for new parametric types --
no JSON schema beyond pointing at the file, and the model author uses the same
public geometry API as a generator function.

Example here: `types/segments/circular_acoustic_straight.json` ->
`models/circular_acoustic_straight.py`. It demonstrates a PartScript that
returns three concentric construction layers: acoustic liner, absorber, and
outer jacket.

## 2. Static BREP/STEP (`"geometry": {"backend": "static", "descriptor": "..."}`)

For a fixed, non-parametric shape (a vendor-supplied STEP file, say) with a
fixed port list. The `descriptor` is a JSON file (`freecad/HVAC/library/static_shapes.py`)
that points at the geometry file plus its placement, ports (position,
direction, profile, section params) and `connection_lengths` -- no Python code
at all.

Example here: `types/junctions/end_diffuser_static.json` ->
`models/static_diffuser.json` (descriptor) -> `models/static_diffuser.step`
(geometry).

## 3. Generator function (`"geometry": {"backend": "generator", "module": "...", "function": "..."}`)

A Python function `func(context) -> {"layers": ..., "connection_lengths": ...}`
(`HVACLibraryAPI.single_layer(context, shape, connection_lengths=...)` builds
the result for a fitting that is one solid)
in `<library>/generators/<module>.py`, or in one of the addon's shared
fitting modules (`freecad/HVAC/library/fittings/`, named with the `shared:`
module prefix -- see `libraries/README.md`). This is the original,
fully-general mechanism -- every procedural type in `builtin_basic` uses the
shared modules, and `smacna` uses its own `generators/junctions.py`.

It's also how a type loads an entire parametric **FreeCAD document** as its
shape: the generator function itself is a thin wrapper that calls
`HVACLibraryAPI.shape_from_fcstd(fcstd_path, context, params={...},
result_object=...)`, which opens the `.FCStd`, sets its `App::VarSet`
properties, recomputes, and extracts the named result object's shape. This
is heavier than PartScript (a whole FreeCAD document + spreadsheet-style
parametrics vs. a Python file) but useful when the source geometry is more
naturally authored in the FreeCAD GUI than in code.

Example here: `types/segments/rectangular_straight.json` ->
`generators/segments.py:build_rectangular_straight_fcstd` ->
`models/rectangular_straight.FCStd`.

## Choosing a backend

- New parametric type, comfortable writing the geometry in Python: **PartScript**.
- Fixed/imported geometry (vendor part, STEP export), no parametrics needed: **static**.
- Geometry is more naturally authored/edited in the FreeCAD GUI as a `.FCStd`
  document (sketches, VarSet-driven expressions): **generator + `shape_from_fcstd`**.
- Anything needing bespoke Python logic beyond what PartScript's `generate()`
  contract offers (e.g. dispatching to different sub-models based on size, or
  reuse of shared helper code across many types): **generator function**.
