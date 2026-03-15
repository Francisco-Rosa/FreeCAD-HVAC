# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the HVAC addon.

################################################################################
#                                                                              #
#   Copyright (c) 2026 Francisco Rosa                                          #
#                                                                              #
#   This addon is free software; you can redistribute it and/or modify it      #
#   under the terms of the GNU Lesser General Public License as published      #
#   by the Free Software Foundation; either version 2.1 of the License, or     #
#   (at your option) any later version.                                        #
#                                                                              #
#   This addon is distributed in the hope that it will be useful,              #
#   but WITHOUT ANY WARRANTY; without even the implied warranty of             #
#   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.                       #
#                                                                              #
#   See the GNU Lesser General Public License for more details.                #
#                                                                              #
#   You should have received a copy of the GNU Lesser General Public           #
#   License along with this addon. If not, see https://www.gnu.org/licenses    #
#                                                                              #
################################################################################

import FreeCAD
import Part


def create_rectangular_duct_geom(start_point, end_point, width, height):
    """
    Create a cuboid centered on the line between two points.

    start_point, end_point : (x,y,z)
    width  : cross-section width
    height : cross-section height

    Returns:
        Part.Shape
    """

    p1 = FreeCAD.Vector(*start_point)
    p2 = FreeCAD.Vector(*end_point)

    direction = p2 - p1
    length = direction.Length

    if length == 0:
        raise ValueError("Start and end points cannot be identical")

    direction_unit = FreeCAD.Vector(direction)
    direction_unit.normalize()

    # Create box with length along X and cross-section in YZ
    # Box origin is at (0,0,0) and spans X:[0,length], Y:[0,width], Z:[0,height]
    shape = Part.makeBox(length, width, height)

    # We want the duct centerline to lie along the box X axis at Y=0, Z=0.
    # Therefore shift the box in its local coordinates by (0, -width/2, -height/2)
    # Then apply rotation that aligns X to the direction vector and translate to p1.
    rotation = FreeCAD.Rotation(FreeCAD.Vector(1, 0, 0), direction_unit)

    local_shift = FreeCAD.Vector(0.0, -width / 2.0, -height / 2.0)
    world_shift = rotation.multVec(local_shift)
    placement_origin = p1.add(world_shift)
    placement = FreeCAD.Placement(placement_origin, rotation)

    shape_mod = shape.copy()
    shape_mod.transformShape(placement.toMatrix(), True, False)

    return shape_mod

def create_circular_duct_geom(start_point, end_point, diameter):
    """
    Create a cylindrical duct centered on the line between two points.

    start_point, end_point : (x,y,z)
    diameter : cross-section diameter

    Returns:
        Part.Shape
    """

    p1 = FreeCAD.Vector(*start_point)
    p2 = FreeCAD.Vector(*end_point)

    direction = p2 - p1
    length = direction.Length

    if length == 0:
        raise ValueError("Start and end points cannot be identical")

    direction_unit = FreeCAD.Vector(direction)
    direction_unit.normalize()

    # Convert diameter to radius for cylinder creation
    radius = float(diameter) / 2.0

    # Create cylinder with axis along Z of height = length
    cyl = Part.makeCylinder(radius, length)

    # Align cylinder Z-axis to direction vector
    rotation = FreeCAD.Rotation(FreeCAD.Vector(0, 0, 1), direction_unit)

    # Place base center at start point
    placement = FreeCAD.Placement(p1, rotation)

    cyl_mod = cyl.copy()
    cyl_mod.transformShape(placement.toMatrix(), True, False)

    return cyl_mod


def build_rectangular_straight(context):
    sp = context["start_point"]
    ep = context["end_point"]
    width = context["properties"].get("Width", 100.0)
    height = context["properties"].get("Height", 100.0)
    shape = create_rectangular_duct_geom(sp, ep, width, height)
    return {"shape": shape}


def build_circular_straight(context):
    sp = context["start_point"]
    ep = context["end_point"]
    diameter = context["properties"].get("Diameter", 100.0)
    shape = create_circular_duct_geom(sp, ep, diameter)
    return {"shape": shape}
