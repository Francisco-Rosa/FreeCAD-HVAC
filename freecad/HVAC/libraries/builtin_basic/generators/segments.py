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


def build_rectangular_straight(context):
    api = context["hvac_api"]
    
    sp = context["start_point"]
    ep = context["end_point"]
    props = dict(context.get("properties", {}) or {})

    width = float(props.get("Width", 100.0))
    height = float(props.get("Height", 100.0))
    profile_x_axis = context.get("profile_x_axis")
    
    shape = api.make_straight_shape(
        start_point=sp,
        end_point=ep,
        profile="Rectangular",
        section_params={
            "Width": width,
            "Height": height,
        },
        profile_x_axis=profile_x_axis,
    )
        
    return {"shape": shape}


def build_circular_straight(context):
    api = context["hvac_api"]

    sp = context["start_point"]
    ep = context["end_point"]
    props = dict(context.get("properties", {}) or {})

    diameter = float(props.get("Diameter", 100.0))
    profile_x_axis = context.get("profile_x_axis")

    shape = api.make_straight_shape(
        start_point=sp,
        end_point=ep,
        profile="Circular",
        section_params={
            "Diameter": diameter,
        },
        profile_x_axis=profile_x_axis,
    )
    
    return {"shape": shape}


def build_oval_straight(context):
    api = context["hvac_api"]
    
    sp = context["start_point"]
    ep = context["end_point"]
    props = dict(context.get("properties", {}) or {})
    
    width = float(props.get("Width", 200.0))
    height = float(props.get("Height", 100.0))
    profile_x_axis = context.get("profile_x_axis")

    shape = api.make_straight_shape(
        start_point=sp,
        end_point=ep,
        profile="Oval",
        section_params={
            "Width": width,
            "Height": height,
        },
        profile_x_axis=profile_x_axis,
    )
        
    return {"shape": shape}


def build_rectangular_curved(context):
    api = context["hvac_api"]
    
    sp = context["start_point"]
    ep = context["end_point"]
    props = dict(context.get("properties", {}) or {})

    width = float(props.get("Width", 100.0))
    height = float(props.get("Height", 100.0))
    profile_x_axis = context.get("profile_x_axis")
    path_edge = context.get("path_edge", None)
    
    if path_edge is None:
        shape = api.make_straight_shape(
            start_point=sp,
            end_point=ep,
            profile="Rectangular",
            section_params={
                "Width": width,
                "Height": height,
            },
            profile_x_axis=profile_x_axis,
        )
    else:
        direction = context.get("start_direction", None)
        shape = api.make_curved_shape(
            start_point=sp,
            end_point=ep,
            profile="Rectangular",
            section_params={
                "Width": width,
                "Height": height,
            },
            path=path_edge,
            profile_x_axis=profile_x_axis,
            direction = direction
        )
        
    return {"shape": shape}


def build_circular_curved(context):
    api = context["hvac_api"]

    sp = context["start_point"]
    ep = context["end_point"]
    props = dict(context.get("properties", {}) or {})

    diameter = float(props.get("Diameter", 100.0))
    profile_x_axis = context.get("profile_x_axis")
    path_edge = context.get("path_edge", None)

    if path_edge is None:
        shape = api.make_straight_shape(
            start_point=sp,
            end_point=ep,
            profile="Circular",
            section_params={
                "Diameter": diameter,
            },
            profile_x_axis=profile_x_axis,
        )
    else:
        direction = context.get("start_direction", None)
        shape = api.make_curved_shape(
            start_point=sp,
            end_point=ep,
            profile="Circular",
            section_params={
                "Diameter": diameter,
            },
            path=path_edge,
            profile_x_axis=profile_x_axis,
            direction = direction
        )
        
    return {"shape": shape}


def build_oval_curved(context):
    api = context["hvac_api"]
    
    sp = context["start_point"]
    ep = context["end_point"]
    props = dict(context.get("properties", {}) or {})
    
    width = float(props.get("Width", 200.0))
    height = float(props.get("Height", 100.0))
    profile_x_axis = context.get("profile_x_axis")
    path_edge = context.get("path_edge", None)

    if path_edge is None:
        shape = api.make_straight_shape(
            start_point=sp,
            end_point=ep,
            profile="Oval",
            section_params={
                "Width": width,
                "Height": height,
            },
            profile_x_axis=profile_x_axis,
        )
    else:
        direction = context.get("start_direction", None)
        shape = api.make_curved_shape(
            start_point=sp,
            end_point=ep,
            profile="Oval",
            section_params={
                "Width": width,
                "Height": height,
            },
            path=path_edge,
            profile_x_axis=profile_x_axis,
            direction = direction
        )

    return {"shape": shape}
