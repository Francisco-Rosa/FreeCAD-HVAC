# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the HVAC addon.

"""Straight duct segments: one profile extruded (or swept along a path edge) from start to end."""

from ._common import _finish


def _properties(context):
    return dict(context.get("properties") or {})


def _build(context, profile, section):
    api = context["hvac_api"]
    start = api.vec(context["start_point"])
    end = api.vec(context["end_point"])
    path = context.get("path_edge")
    direction = context.get("start_direction") or (end - start)
    x_axis = context.get("profile_x_axis")

    p0 = api.make_profile(profile, section, center=start, direction=direction, profile_x_axis=x_axis)

    def envelope(offset):
        grown = api.offset_profile(p0, offset) if offset > 0.0 else p0
        if path is not None:
            return api.sweep(grown, path, solid=True)
        return api.extrude(grown, end - start, solid=True)

    return _finish(context, envelope, [])


def build_rectangular_straight(context):
    p = _properties(context)
    return _build(context, "Rectangular", {"Width": p["Width"], "Height": p["Height"]})


def build_circular_straight(context):
    p = _properties(context)
    return _build(context, "Circular", {"Diameter": p["Diameter"]})


def build_oval_straight(context):
    p = _properties(context)
    return _build(context, "Oval", {"Width": p["Width"], "Height": p["Height"]})


def build_rectangular_curved(context):
    return build_rectangular_straight(context)


def build_circular_curved(context):
    return build_circular_straight(context)


def build_oval_curved(context):
    return build_oval_straight(context)
