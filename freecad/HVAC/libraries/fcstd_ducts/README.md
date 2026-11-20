# FreeCAD Library Ducts (`fcstd_ducts`)

Ducts, flexible ducts, radius elbows, transitions, joints and offsets built
from the parametric duct models of the FreeCAD-library repository, through the
FCStd-template geometry backend (`HVACLibraryAPI.shape_from_fcstd`).

## Source and licence

The models in `models/` are derived from the HVAC/Ducts parts of the
FreeCAD-library repository, by Francisco Rosa:
<https://github.com/Francisco-Rosa/FreeCAD-library/tree/master/HVAC/Ducts>

They are licensed under CC-BY 3.0
(<http://creativecommons.org/licenses/by/3.0/>), as is everything in that
repository. Each template keeps the file name of the model it comes from:

| Template in `models/` | Folder in the source repository |
|---|---|
| `Duct_linear_circular_complete.FCStd`, `Duct_curved_circular_complete.FCStd` | `Circular/` |
| `Duct_linear_rectangular_complete.FCStd`, `Duct_curved_rectangular_complete.FCStd` | `Rectangular/` |
| `Duct_linear_oval_complete.FCStd`, `Duct_curved_oval_complete.FCStd` | `Oval/` |
| `Duct_linear_rectangular_circular_complete.FCStd` | `Rectangular_circular/` |
| `Duct_linear_rectangular_oval_complete.FCStd` | `Rectangular_oval/` |
| `Duct_linear_circular_oval_complete.FCStd` | `Circular_oval/` |
| `Duct_flex_complete.FCStd` | `Flex/` |

## Changes made to the original models

`tools/build_fcstd_duct_templates.py` makes every change, so the templates can
be rebuilt from the originals at any time (see the end of this page). No
sketch, constraint, expression, sweep, cut or material of the models is
edited: the duct geometry is the authors' own. What changes:

1. **Removed:** every TechDraw object (drawing pages, views, the SVG
   template), the output spreadsheets (labels starting `Output`, which only
   report quantities) and the `Instructions` text. Nothing else depends on
   them; they only slow every recompute down.
2. **The duct path moved, not reshaped:**
   - straight models: the Draft Wire `Axis` gets an identity placement and
     its two points become (0, 0, 0) and (length, 0, 0), keeping the
     model's length;
   - curved models: the Draft Circle `Axis` gets an identity placement and
     FirstAngle 0, and an expression `Placement.Base.x = -Radius` so the arc
     always starts at the origin heading +Y, its centre on -X;
   - flexible duct: the two opening axis lines (`Opening1_axis`,
     `Opening2_axis`) get an identity placement with their points rewritten
     in world coordinates, so they stay exactly where they were; the Bezier
     curve is not moved.
3. **Labels:** the parameter VarSet becomes `ParamsVarSet` (the loader's
   default), the path `Axis`, the flexible duct's axis lines `Opening1_axis`
   and `Opening2_axis`. Object names (and so every expression) are unchanged.
4. **Parameter values set** (all of them parameters the models expose):
   - `Flange_Flange1` / `Flange_Flange2` / `Flange_Flange_01` /
     `Flange_Flange_02` off: this library draws flanges with the shared
     `transverse_flange` feature, so they match the other libraries and can
     be switched per end;
   - every `..._closure` off (end caps are not ducts);
   - `Duct_Flip_axis`, `Duct_Opening1_axis_flip`, `Duct_Opening2_axis_flip`
     off; `Duct_Duct`, `Duct_Duct_internal`, `Duct_Duct_external`,
     `Insulation_Insulation` on; `Duct_Show_volume_only` off. Insulation is
     always built so its solid always exists; a build drops it when the duct
     has no insulation.
5. **Added:** `Port0`, an `App::Placement` marking opening 1 (local +Z out of
   the duct, local +X along the opening's width), and `Result`, a
   `Part::Compound` of the model's own duct wall and insulation cuts (for the
   flexible duct also its outer jacket), which is what the loader reads.

The models' materials (`Materials_Sheet_metal`, `Materials_Insulation`) are
kept but not used: each layer takes its material from the HVAC construction
layers, like every other library.

## Types

| Type | Built from |
|---|---|
| `circular_straight`, `rectangular_straight`, `oval_straight` | the straight model of the profile |
| `circular_generic`, `rectangular_generic`, `oval_generic` (rigid ducts on an arc) | the curved model of the profile |
| `circular_flex` (flexible duct on a straight, arc or spline path) | the flexible duct model: inner core, insulation and outer jacket |
| `through_elbow_radius` | the curved model; radius `CenterlineRadius` (0: 1.5 times the duct size in the plane of the bend) |
| `through_straight_generic` (a duct-to-duct joint) | the straight model as a sleeve `Length` long (default 50 mm) when both ducts match; a transition when they do not |
| `through_transition_concentric`, `through_transition_eccentric`, `through_transition_offset` | a straight model with a different opening at each end, opening 2 moved sideways for eccentric and offset ones; round, rectangular, flat oval and every mix of two of them |
| `through_offset_generic` (two parallel ducts displaced sideways) | a straight model with opening 2 moved sideways, `OffsetLength` long (0: a 30 degree slope) |
| `through_marker`, `branch_marker`, `cross_marker`, `multiport_marker`, `end_terminal_marker` | the shared markers: the source models have no tees, crosses or terminals |

Every rigid type has a sheet-metal wall (`Thickness`), insulation
(`InsulationThickness`, 0 for none) and flanges (`FlangeHeight`,
`FlangeThickness`, `ShowFlange1`, `ShowFlange2`; off by default). The flexible
duct has an inner core (`Thickness`), insulation and, over insulation, an outer
jacket (an `outer_jacket` layer, exported to IFC as a wrapping); its friction
follows `CompressionPercent`. Losses are the shared SMACNA elbow, transition
and offset losses.

## How a build works

Every rigid model is one duct from opening 1 to opening 2 along a path starting
at the origin: a line along +X, or an arc starting along +Y with its centre on
-X. `generators/ducts.py` sets the opening sizes, opening 2's sideways shift
and the path length (or radius and angle) on the model, and gives the loader
opening 1 as a port: position, outward direction and width direction. The
loader opens the template, recomputes it and places its `Port0` on that port.

The flexible duct stays in world coordinates. Its path is a Draft Bezier curve;
the generator writes the duct's own path into it (a straight cubic for a
straight duct, quarter-turn cubics for an arc, the spline's own Bezier pieces
for a spline) and stands each opening on an axis line along the path's tangent
at that end.

## Limits of the original models

What the models themselves cannot do, and what this library does about it:

- **Rigid curved ducts follow a circular arc only.** The curved models sweep
  along a Draft Circle, so they cannot follow a spline. A spline drawn as a
  rigid duct is refused with a message; draw it round, as a flexible duct.
  (The flexible duct model follows a Bezier curve, which can match any
  non-rational spline exactly.)
- **Only the flexible duct follows a spline, and it is round only.** There
  is no rectangular or flat oval flexible model, so a rectangular or oval
  spline has no duct in this library.
- **A flat oval bends only with its flat sides in the plane of the bend.**
  The curved oval model draws it that way and has no parameter to turn it;
  the other way round is refused with a message.
- **The round-to-round straight model cannot shift opening 2 sideways.** It
  has the `Duct_Opening2_horizontal_position` / `_vertical_position`
  parameters, but nothing in the model uses them. So an eccentric or offset
  round-to-round transition, and a round offset, are refused with a message.
  Every other straight model (rectangular, oval and the three mixed ones) can.
- **A flat oval needs a straight side.** With `distance_between_arcs` at
  exactly 0 (an oval with Width = Height) the oval sketches fail to solve;
  this library uses at least 0.5 mm.
- **The oval model spells one parameter `Duct_Opening2_horizontal_positon`.**
  This library uses that name as it is.
- **Each build opens and recomputes a model file,** so a large network
  rebuilds more slowly than with the `smacna` or `builtin_basic` libraries.
- **No tees, crosses, wyes, taps or terminals** exist in the source models;
  those nodes get the shared markers.
- **Not used yet:** the mixed curved models (`Duct_curved_rectangular_circular`,
  `_rectangular_oval`, `_circular_oval`: an elbow that also changes profile)
  and the older spreadsheet-driven fittings (reductions, chamfered and
  extended bends, square-to-round transition).

## Rebuilding the templates

Download the models (the `.FCStd` files listed above) into a folder of their
own, then run, from the repository root:

    freecadcmd tools/build_fcstd_duct_templates.py <models folder> freecad/HVAC/libraries/fcstd_ducts/models
