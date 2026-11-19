# Samples library

This library is **not** meant to be modeled with. Each type here is a
minimal, working example of one way a type-def can produce geometry (a
"geometry backend"), for a library author to copy from. `smacna` and
`builtin_basic` ship the types meant for day-to-day use.

| Backend | Example type-def | Geometry |
|---|---|---|
| PartScript | `types/segments/circular_acoustic_straight.json` | `models/circular_acoustic_straight.py` (three concentric layers) |
| Static BREP/STEP | `types/junctions/end_diffuser_static.json` | `models/static_diffuser.json` (descriptor) and `models/static_diffuser.step` |
| Generator + FCStd template | `types/segments/rectangular_straight.json` | `generators/segments.py:build_rectangular_straight_fcstd` and `models/rectangular_straight.FCStd` |

## Choosing a backend

- A new parametric type, geometry written in Python: **PartScript**.
- Fixed or imported geometry (vendor part, STEP export): **static**.
- Geometry more naturally drawn in the FreeCAD GUI (sketches, VarSet-driven
  expressions): **generator + `shape_from_fcstd`**.
- A standard fitting (elbow, tee, wye, transition, ...): **a shared fitting
  module** (`"module": "shared:..."`), no code at all.
- Logic beyond one file (choosing between sub-models by size, helpers
  shared by many types): **generator function**.

What each backend receives and must return, and the rules library code
follows, are in [the library guide](../../../../docs/library-guide.md)
(section 4, "Producing geometry", and section 5, "What library code may
do").
