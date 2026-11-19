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

"""
Loads a shape from a parametric FreeCAD (.FCStd) template -- a shape-
building primitive a generator function calls directly (via
HVACLibraryAPI.shape_from_fcstd), the same way it already calls
HVACLibraryAPI.make_profile/sweep/loft/etc. NOT a
declarative JSON-driven dispatch: the generator function decides which
.FCStd file to use (so it can pick between several based on its own
conditions -- size range, family, construction class, ...), builds the
VarSet params dict itself, and is responsible for any values (like a
routed segment's length) that aren't fixed type properties.

Template authoring convention (all in the template document's global frame):
  - An App::VarSet object (default name "ParamsVarSet") with one property
    per key in the caller's `params` dict (e.g. Duct_Width -- an
    App::PropertyLength etc.); values are written directly onto these
    VarSet properties before recompute. Feature dimensions elsewhere in the
    template are bound to them via expressions (e.g. ParamsVarSet.
    Duct_Width). Use a "VarSetName.PropName" params key to target a
    non-default VarSet object.
  - A result object (default name "Result", override via the `result_object`
    argument) whose .Shape (with .Placement left at Identity) is the shape
    to extract.
  - One port-reference object per port, named Port0..Port{N-1} (or the
    `port_names` override), ordered to match connected_ports order for
    junctions / [start, end] for segments. Only .Placement is read: local
    +Z is the port's outward flow direction, local +X is its cross-section
    reference axis, .Placement.Base is the port's local position.

Placement is a single rigid transform (no scale) anchored on port 0; any
other ports are best-effort validated against a tolerance and only produce
a console warning if they don't line up -- misalignment never blocks shape
generation (an inter-port distance that isn't correctly parametrized in the
template is an authoring problem to fix, not a reason to hide the shape).

Each call opens the template document fresh (hidden -- not added to the
Gui's tree/3D view), extracts a standalone copy of the Result shape, then
closes it again before returning -- there is no persistent document cache,
so the template is never left open in the session between generator calls.
"""

import math

import FreeCAD

from ..utils import hvaclib
from .library_api import HVACLibraryAPI


class TemplateGeneratorError(Exception):
    """Base for all template-generator failures."""
    pass


class TemplateSchemaError(TemplateGeneratorError):
    pass


class TemplateRecomputeError(TemplateGeneratorError):
    pass


_DEFAULT_VARSET_NAME = "ParamsVarSet"


def _split_param_target(target):
    if "." in target:
        varset_name, prop_attr = target.split(".", 1)
        return varset_name, prop_attr
    return _DEFAULT_VARSET_NAME, target


def _apply_params(doc, params):
    """Write each param value onto its target VarSet property, then recompute the template document."""
    for target, value in (params or {}).items():
        varset_name, prop_attr = _split_param_target(target)
        matches = doc.getObjectsByLabel(varset_name)
        if not matches:
            raise TemplateSchemaError(
                "Template '{}': VarSet '{}' not found".format(doc.Name, varset_name)
            )
        varset = matches[0]
        if not hasattr(varset, prop_attr):
            raise TemplateSchemaError(
                "Template '{}': VarSet '{}' has no property '{}'".format(
                    doc.Name, varset_name, prop_attr
                )
            )
        try:
            setattr(varset, prop_attr, value)
        except Exception as e:
            raise TemplateSchemaError(
                "Template '{}': VarSet '{}' property '{}' rejected value {!r}: {}".format(
                    doc.Name, varset_name, prop_attr, value, e
                )
            )

    doc.recompute()


def _get_result_shape(doc, result_name):
    """Fetch a standalone copy of the template's result object's Shape, after checking it recomputed cleanly."""
    matches = doc.getObjectsByLabel(result_name)
    if not matches or not hasattr(matches[0], "Shape"):
        raise TemplateSchemaError(
            "Template '{}': result object '{}' not found".format(doc.Name, result_name)
        )
    result_obj = matches[0]
    state = list(getattr(result_obj, "State", None) or [])
    if "Invalid" in state:
        raise TemplateRecomputeError(
            "Template '{}': object '{}' is invalid after recompute".format(doc.Name, result_name)
        )
    shape = result_obj.Shape
    if shape is None or shape.isNull():
        raise TemplateSchemaError(
            "Template '{}': result object '{}' has no shape".format(doc.Name, result_name)
        )
    return shape.copy()


def _port_names(port_names, degree):
    """The template's port-reference object names -- the caller's override, or the Port0..Port{N-1} default."""
    names = list(port_names or [])
    if names:
        return names
    return ["Port{}".format(i) for i in range(degree)]


def _real_ports_from_context(context):
    if "connected_ports" in context:
        return list(context["connected_ports"] or [])

    # Segment context: synthesize 2 pseudo-ports from start/end, using the
    # same "outward from the body" sign convention as real junction ports
    # (direction points away from the segment body into the connecting duct).
    sp = HVACLibraryAPI.vec(context["start_point"])
    ep = HVACLibraryAPI.vec(context["end_point"])
    axis = HVACLibraryAPI.unit(ep - sp)
    x_axis = context.get("profile_x_axis")
    return [
        {"position": sp, "direction": axis * -1.0, "profile_x_axis": x_axis},
        {"position": ep, "direction": axis, "profile_x_axis": x_axis},
    ]


def _get_template_ports(doc, port_names):
    """Look up each named port-reference object in the template document."""
    objs = []
    for name in port_names:
        matches = doc.getObjectsByLabel(name)
        if not matches:
            raise TemplateSchemaError(
                "Template '{}': port reference object '{}' not found".format(doc.Name, name)
            )
        objs.append(matches[0])
    return objs


def build_shape_from_template(fcstd_path, context, params=None, result_object="Result",
                               port_names=None, tol_mm=0.5, tol_deg=0.5):
    """Entry point for the FCStd-template backend -- see the module docstring for the authoring convention."""
    # openDocument()/closeDocument() both reassign FreeCAD.ActiveDocument as
    # a side effect (and leave it None once the template is closed, if it
    # was the last/active one) -- other code (e.g. hvaclib.makeLineKey) reads
    # FreeCAD.ActiveDocument assuming it's still the real working document,
    # so it must be restored before returning, not left wherever
    # open/close happened to leave it.
    prev_active = FreeCAD.ActiveDocument
    doc = FreeCAD.openDocument(fcstd_path, hidden=True)
    try:
        _apply_params(doc, params)
        shape = _get_result_shape(doc, result_object)

        real_ports = _real_ports_from_context(context)
        names = _port_names(port_names, len(real_ports))
        if len(names) != len(real_ports):
            raise TemplateSchemaError(
                "Template '{}': declares {} port(s) but this call needs {}".format(
                    doc.Name, len(names), len(real_ports)
                )
            )
        template_ports = _get_template_ports(doc, names)

        # Port 0 fully determines the rigid transform (rotation + translation,
        # no scale); every other port is a best-effort validation only.
        real0 = real_ports[0]
        real_frame0, _x, _y, _z = hvaclib.make_profile_frame(
            direction=HVACLibraryAPI.port_direction(real0),
            preferred_x=HVACLibraryAPI.port_profile_x_axis(real0),
            origin=HVACLibraryAPI.port_position(real0),
        )
        transform = real_frame0.multiply(template_ports[0].Placement.inverse())

        for i in range(1, len(real_ports)):
            predicted = transform.multiply(template_ports[i].Placement)
            predicted_dir = predicted.Rotation.multVec(FreeCAD.Vector(0, 0, 1))
            real_i = real_ports[i]
            pos_err = (predicted.Base - HVACLibraryAPI.port_position(real_i)).Length
            ang_err_deg = math.degrees(
                HVACLibraryAPI.angle_between(predicted_dir, HVACLibraryAPI.port_direction(real_i))
            )
            if pos_err > tol_mm or ang_err_deg > tol_deg:
                FreeCAD.Console.PrintWarning(
                    "HVAC - Template '{}' port {} misaligned: {:.2f}mm / {:.2f}deg "
                    "(tolerance {}mm / {}deg). Applying best-fit placement anyway; check the "
                    "template's parametrized inter-port geometry.\n".format(
                        doc.Name, i, pos_err, ang_err_deg, tol_mm, tol_deg
                    )
                )

        shape.transformShape(transform.toMatrix(), True, False)
        return shape
    finally:
        try:
            FreeCAD.closeDocument(doc.Name)
        except Exception:
            pass
        if prev_active is not None:
            try:
                FreeCAD.setActiveDocument(prev_active.Name)
            except Exception:
                pass
