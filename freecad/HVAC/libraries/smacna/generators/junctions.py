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


def _vec(v):
    if hasattr(v, "x"):
        return FreeCAD.Vector(v)
    return FreeCAD.Vector(*v)


def _port_position(port):
    return _vec(port["position"])


def _make_sphere(center, diameter):
    radius = float(diameter) / 2.0
    if radius <= 0:
        raise ValueError("Marker diameter must be > 0")

    sphere = Part.makeSphere(radius)
    placement = FreeCAD.Placement(center, FreeCAD.Rotation())
    out = sphere.copy()
    out.transformShape(placement.toMatrix(), True, False)
    return out


def _build_records(context, length_value):
    records = []

    connected_ports = list(context.get("connected_ports", []) or [])
    for port in connected_ports:
        edge_key = str(port.get("edge_key", "") or "")
        seg_end = str(port.get("segment_end", "") or "")
        if not edge_key or seg_end not in ("start", "end"):
            continue

        records.append(
            {
                "edge_key": edge_key,
                "segment_end": seg_end,
                "length": float(length_value),
            }
        )

    return records


def _build_marker(context, default_diameter, trim_factor):
    ports = list(context.get("connected_ports", []) or [])
    if not ports:
        raise ValueError("Marker requires at least one port")
    props = dict(context.get("properties", {}) or {})
    dia = float(props.get("MarkerDiameter", default_diameter) or default_diameter)
    center = _port_position(ports[0])

    shape = _make_sphere(center, dia)
    trim_len = float(dia) * float(trim_factor)

    return {
        "shape": shape,
        "connection_lengths": _build_records(context, trim_len),
    }


def build_terminal_marker(context):
    return _build_marker(context, default_diameter=200.0, trim_factor=0.25)


def build_transition_marker(context):
    return _build_marker(context, default_diameter=240.0, trim_factor=0.30)


def build_elbow_marker(context):
    return _build_marker(context, default_diameter=240.0, trim_factor=0.35)


def build_tee_marker(context):
    return _build_marker(context, default_diameter=260.0, trim_factor=0.40)


def build_wye_marker(context):
    return _build_marker(context, default_diameter=260.0, trim_factor=0.40)


def build_cross_marker(context):
    return _build_marker(context, default_diameter=280.0, trim_factor=0.45)


def build_manifold_marker(context):
    return _build_marker(context, default_diameter=320.0, trim_factor=0.50)
