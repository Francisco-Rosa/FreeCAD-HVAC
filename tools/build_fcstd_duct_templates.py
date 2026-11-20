# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the HVAC addon.

"""
Builds the FCStd templates of the `fcstd_ducts` library from the parametric
duct models in the FreeCAD-library repository (HVAC/Ducts, by Francisco Rosa,
CC-BY 3.0): https://github.com/Francisco-Rosa/FreeCAD-library/tree/master/HVAC/Ducts

The models are kept as they are, apart from what the HVAC template loader
(library/template_shapes.py) needs and what slows a rebuild down:

1. TechDraw pages, output spreadsheets and the instructions text are removed.
2. The duct path (a Draft Wire line or a Draft Circle arc) is normalised so
   the duct starts at the origin: a line runs along +X; an arc starts at the
   origin heading +Y, its centre at (-Radius, 0, 0), from angle 0. The axis
   object is labelled "Axis", so a generator sets `Axis.Length`, or
   `Axis.Radius` and `Axis.LastAngle`.
3. The parameter VarSet is labelled "ParamsVarSet" (the loader's default).
   Flanges and end closures are switched off: the HVAC library draws flanges
   with its shared flange feature. Insulation is switched on, so its solid
   always exists (a generator drops it when the duct has none).
4. "Port0", an App::Placement at the duct's start: local +Z out of the duct
   (-X for a line, -Y for an arc), local +X along the opening's width
   (+Y for a line; outward from the arc's centre, +X, for an arc).
5. "Result", a Part::Compound of the duct wall, then the insulation.

The flexible duct is different: its path is a Draft Bezier curve and each
opening stands on an axis line of its own. It is left where it is (Port0 is
the identity), so a generator writes the curve's points and both opening axes
in world coordinates. Its Result holds three solids: the inner wall, the
insulation and the outer jacket.

Run in freecadcmd, with the folder holding the downloaded models and the
output folder:

    freecadcmd tools/build_fcstd_duct_templates.py <models folder> <out folder>
"""

import os
import sys

import FreeCAD

# The source models used. Each template keeps its source file's name.
TEMPLATES = (
    "Duct_linear_circular_complete",
    "Duct_linear_rectangular_complete",
    "Duct_linear_oval_complete",
    "Duct_curved_circular_complete",
    "Duct_curved_rectangular_complete",
    "Duct_curved_oval_complete",
    "Duct_linear_rectangular_circular_complete",
    "Duct_linear_rectangular_oval_complete",
    "Duct_linear_circular_oval_complete",
    "Duct_flex_complete",
)

_DROP_TYPES = ("TechDraw::", "App::TextDocument")


def _remove_unneeded(doc):
    """Step 1: drawings, output tables and text; repeated until nothing more can go (dependents first)."""
    for _ in range(10):
        doomed = [
            o
            for o in doc.Objects
            if o.TypeId.startswith(_DROP_TYPES)
            or (o.TypeId == "Spreadsheet::Sheet" and str(o.Label).startswith("Output"))
        ]
        if not doomed:
            return
        for obj in doomed:
            if not [u for u in obj.InList if u not in doomed]:
                try:
                    doc.removeObject(obj.Name)
                except Exception:
                    pass


def _rotation(x_axis, z_axis):
    """A rotation whose local X and Z are the given (orthogonal, unit) world vectors."""
    x = FreeCAD.Vector(*x_axis)
    z = FreeCAD.Vector(*z_axis)
    y = z.cross(x)
    matrix = FreeCAD.Matrix(x.x, y.x, z.x, 0, x.y, y.y, z.y, 0, x.z, y.z, z.z, 0, 0, 0, 0, 1)
    return FreeCAD.Placement(matrix).Rotation


def _visibility(obj):
    return next((e for p, e in obj.ExpressionEngine if p == "Visibility"), "")


def _material_role(obj):
    for prop, expression in obj.ExpressionEngine:
        if prop == "Material":
            return expression.split(".")[-1]
    return ""


def build(source_path, out_path):
    doc = FreeCAD.openDocument(source_path, hidden=True)
    try:
        _remove_unneeded(doc)
        varset = next(o for o in doc.Objects if o.TypeId == "App::VarSet")
        varset.Label = "ParamsVarSet"

        # Step 2: the path starts at the origin.
        axis = getattr(varset, "Duct_Axis", None) or varset.Duct_Axis_Bezier_curve
        axis.Label = "Axis"
        kind = getattr(axis.Proxy, "Type", "")
        if kind == "BezCurve":
            # Flexible duct: the curve and the opening axes are written per build, in world coordinates.
            for line in (varset.Duct_Opening1_axis, varset.Duct_Opening2_axis):
                points = [line.Placement.multVec(p) for p in line.Points]
                line.Placement = FreeCAD.Placement()
                line.Points = points
            varset.Duct_Opening1_axis.Label = "Opening1_axis"
            varset.Duct_Opening2_axis.Label = "Opening2_axis"
            port = FreeCAD.Placement()
        elif kind == "Circle":
            axis.Placement = FreeCAD.Placement()
            axis.FirstAngle = 0.0
            axis.setExpression(".Placement.Base.x", "-Radius")
            port = FreeCAD.Placement(FreeCAD.Vector(0, 0, 0), _rotation((1, 0, 0), (0, -1, 0)))
        elif kind == "Wire":
            length = float(axis.Length)
            axis.Placement = FreeCAD.Placement()
            axis.Points = [FreeCAD.Vector(0, 0, 0), FreeCAD.Vector(length, 0, 0)]
            port = FreeCAD.Placement(FreeCAD.Vector(0, 0, 0), _rotation((0, 1, 0), (-1, 0, 0)))
        else:
            raise ValueError("{}: unexpected duct axis type '{}'".format(source_path, kind))

        # Step 3: parameters the library does not drive.
        for prop in varset.PropertiesList:
            if prop.startswith("Flange_Flange") or prop.endswith("closure"):
                setattr(varset, prop, False)
        for prop, value in (
            ("Duct_Flip_axis", False),
            ("Duct_Opening1_axis_flip", False),
            ("Duct_Opening2_axis_flip", False),
            ("Duct_Duct", True),
            ("Duct_Duct_internal", True),
            ("Duct_Duct_external", True),
            ("Duct_Show_volume_only", False),
            ("Insulation_Insulation", True),
        ):
            if hasattr(varset, prop):
                setattr(varset, prop, value)

        # Step 4: the port marker.
        marker = doc.addObject("App::Placement", "Port0")
        marker.Label = "Port0"
        marker.Placement = port

        # Step 5: the result compound: duct wall, insulation (and a flexible duct's outer jacket).
        cuts = [o for o in doc.Objects if o.TypeId == "Part::Cut" and _material_role(o)]
        sheets = [o for o in cuts if _material_role(o) == "Materials_Sheet_metal"]
        insulation = next(o for o in cuts if _material_role(o) == "Materials_Insulation")
        if len(sheets) == 2:
            inner = next(o for o in sheets if "internal" in _visibility(o))
            links = [inner, insulation, next(o for o in sheets if o is not inner)]
        else:
            links = [sheets[0], insulation]
        result = doc.addObject("Part::Compound", "Result")
        result.Label = "Result"
        result.Links = links

        doc.recompute()
        if "Invalid" in list(result.State) or len(result.Shape.Solids) != len(links):
            raise ValueError("{}: Result did not build {} solids".format(source_path, len(links)))
        doc.saveAs(out_path)
        return len(result.Shape.Solids), float(result.Shape.Volume)
    finally:
        FreeCAD.closeDocument(doc.Name)


def main(argv):
    source_dir, out_dir = argv[1], argv[2]
    os.makedirs(out_dir, exist_ok=True)
    for name in TEMPLATES:
        solids, volume = build(os.path.join(source_dir, name + ".FCStd"), os.path.join(out_dir, name + ".FCStd"))
        print("{:45s} {} solids, {:.0f} mm3".format(name, solids, volume))


if __name__ == "__main__":
    main(sys.argv)
