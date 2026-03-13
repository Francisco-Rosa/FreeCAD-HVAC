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


def _center_from_context(context):
    cp = context["center_point"]
    if hasattr(cp, "x"):
        return FreeCAD.Vector(cp)
    return FreeCAD.Vector(*cp)


def _make_sphere(center, diameter):
    radius = float(diameter) / 2.0
    if radius <= 0:
        raise ValueError("Marker diameter must be > 0")
    sphere = Part.makeSphere(radius)
    placement = FreeCAD.Placement(center, FreeCAD.Rotation())
    out = sphere.copy()
    out.transformShape(placement.toMatrix(), True, False)
    return out


def _make_result(shape, edge_keys, length_value):
    return {
        "shape": shape,
        "connection_lengths": [
            {"edge_key": k, "length": float(length_value)}
            for k in edge_keys
        ],
    }


def build_terminal_marker(context):
    center = _center_from_context(context)
    dia = context["properties"].get("MarkerDiameter", 200.0)
    shape = _make_sphere(center, dia)
    return _make_result(shape, context["edge_keys"], dia * 0.25)


def build_transition_marker(context):
    center = _center_from_context(context)
    dia = context["properties"].get("MarkerDiameter", 220.0)
    shape = _make_sphere(center, dia)
    return _make_result(shape, context["edge_keys"], dia * 0.30)


def build_elbow_marker(context):
    center = _center_from_context(context)
    dia = context["properties"].get("MarkerDiameter", 240.0)
    shape = _make_sphere(center, dia)
    return _make_result(shape, context["edge_keys"], dia * 0.35)


def build_tee_marker(context):
    center = _center_from_context(context)
    dia = context["properties"].get("MarkerDiameter", 260.0)
    shape = _make_sphere(center, dia)
    return _make_result(shape, context["edge_keys"], dia * 0.40)


def build_wye_marker(context):
    center = _center_from_context(context)
    dia = context["properties"].get("MarkerDiameter", 260.0)
    shape = _make_sphere(center, dia)
    return _make_result(shape, context["edge_keys"], dia * 0.40)


def build_cross_marker(context):
    center = _center_from_context(context)
    dia = context["properties"].get("MarkerDiameter", 280.0)
    shape = _make_sphere(center, dia)
    return _make_result(shape, context["edge_keys"], dia * 0.45)


def build_manifold_marker(context):
    center = _center_from_context(context)
    dia = context["properties"].get("MarkerDiameter", 300.0)
    shape = _make_sphere(center, dia)
    return _make_result(shape, context["edge_keys"], dia * 0.50)
