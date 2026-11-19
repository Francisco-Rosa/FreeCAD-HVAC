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
Serialize/deserialize a DuctComponent's per-port calculated results
(CalcPortResultsJson), and keep its legacy scalar Calc* properties
(CalcFlowRate/CalcVelocity/CalcLossCoefficient/CalcPressureDrop) in step with
them -- the one place that JSON shape and the "is this component's scalar
Calc* properties even meaningful" rule are defined, instead of being
scattered across core/AirflowSolver.py and core/Component.py.

See analysis/pressure.py's ComponentPortResult/ComponentResult for the pure
dataclasses this reads/writes, and Component.py's own CalcPortResultsJson
property for where the JSON this module produces actually lives.
"""

import json

from ..analysis.pressure import ComponentPortResult


def serialize_port_results(port_results):
    """{edge_key: ComponentPortResult} -> the JSON string stored in CalcPortResultsJson."""
    return json.dumps({
        edge_key: {
            "flow_lps": pr.flow_lps,
            "velocity_ms": pr.velocity_ms,
            "loss_coefficient": pr.loss_coefficient,
            "pressure_drop_pa": pr.pressure_drop_pa,
            "static_pressure_pa": pr.static_pressure_pa,
            "from_edge_key": pr.from_edge_key,
            "to_edge_key": pr.to_edge_key,
            "status": pr.status,
        }
        for edge_key, pr in port_results.items()
    })


def deserialize_port_results(raw_json):
    """The JSON string from CalcPortResultsJson -> {edge_key: ComponentPortResult}, {} if empty/invalid."""
    if not raw_json:
        return {}
    try:
        data = json.loads(raw_json)
    except Exception:
        return {}
    return {
        edge_key: ComponentPortResult(
            edge_key=edge_key,
            flow_lps=float(entry.get("flow_lps", 0.0) or 0.0),
            velocity_ms=float(entry.get("velocity_ms", 0.0) or 0.0),
            loss_coefficient=(
                float(entry["loss_coefficient"]) if entry.get("loss_coefficient") is not None else None
            ),
            pressure_drop_pa=float(entry.get("pressure_drop_pa", 0.0) or 0.0),
            static_pressure_pa=(
                float(entry["static_pressure_pa"]) if entry.get("static_pressure_pa") is not None else None
            ),
            from_edge_key=entry.get("from_edge_key"),
            to_edge_key=entry.get("to_edge_key"),
            status=str(entry.get("status", "") or ""),
        )
        for edge_key, entry in (data or {}).items()
    }


def is_multiport_primary(comp_obj):
    """
    True if `comp_obj` is a Primary component with more than 2 local ports
    (LocalPortsJson) -- the case where a single scalar K/pressure-drop would
    be ambiguous/misleading (see Component.py's CalcFlowRate/CalcVelocity/
    CalcLossCoefficient/CalcPressureDrop). An Inline component is always a
    physically two-port device, so this is only ever True for a Primary.
    """
    if str(getattr(comp_obj, "ComponentRole", "") or "") != "Primary":
        return False
    try:
        ports = json.loads(getattr(comp_obj, "LocalPortsJson", "") or "[]")
    except Exception:
        return False
    return len(ports) > 2


def write_port_results(comp_obj, port_results):
    """
    Persist one component's solved per-port results onto its own FreeCAD
    object.

    CalcPortResultsJson is always fully overwritten (never merged), so a
    recalculation never leaves stale entries from a previous solve sitting
    next to fresh ones -- pass an empty dict to clear it when this component
    got no fitting-loss contribution this solve.

    The legacy scalar Calc* properties are populated only when there is
    exactly one unambiguous result to show (a 1-port or 2-port component
    with its single loss path) -- a multiport Primary's several legs are
    never collapsed into one number, so those properties are reset to 0.0
    instead and the caller is expected to hide them from the property
    editor (see Component.py's own editor-mode sync).
    """
    comp_obj.CalcPortResultsJson = serialize_port_results(port_results)

    if is_multiport_primary(comp_obj) or len(port_results) != 1:
        comp_obj.CalcFlowRate = 0.0
        comp_obj.CalcVelocity = 0.0
        comp_obj.CalcLossCoefficient = 0.0
        comp_obj.CalcPressureDrop = 0.0
        return

    (result,) = port_results.values()
    comp_obj.CalcFlowRate = result.flow_lps
    comp_obj.CalcVelocity = result.velocity_ms
    comp_obj.CalcLossCoefficient = result.loss_coefficient if result.loss_coefficient is not None else 0.0
    comp_obj.CalcPressureDrop = result.pressure_drop_pa


# ----------------------------------------------------------------------------
# Result tooltips (Stage 9 item 1): plain text for the airflow result
# overlay's hover tooltip. No FreeCAD here, so they are unit-testable; the
# observer (ui/Observer.py) only finds what is under the cursor.
# ----------------------------------------------------------------------------


def _fmt(value, unit, digits=1):
    if value is None:
        return "-"
    return "{:.{d}f} {}".format(float(value), unit, d=digits)


def segment_tooltip(label, seg_res, length_mm=0.0):
    """Tooltip text for one duct segment's airflow result (an AirflowSolver.SegmentResult)."""
    length_m = float(length_mm or 0.0) / 1000.0
    friction_rate = seg_res.friction_loss_pa / length_m if length_m > 1e-9 else None
    lines = [
        "Duct {}".format(label),
        "Flow: {}".format(_fmt(seg_res.flow_lps, "L/s")),
        "Velocity: {}".format(_fmt(seg_res.velocity_ms, "m/s", 2)),
        "Friction rate: {}".format(_fmt(friction_rate, "Pa/m", 2)),
        "Friction loss: {}".format(_fmt(seg_res.friction_loss_pa, "Pa")),
        "Fitting loss: {}".format(_fmt(seg_res.fitting_loss_pa, "Pa")),
        "Total loss: {}".format(_fmt(seg_res.total_loss_pa, "Pa")),
        "Cumulative pressure: {}".format(_fmt(seg_res.cumulative_pressure_pa, "Pa")),
    ]
    if length_m > 1e-9:
        lines.insert(1, "Length: {}".format(_fmt(length_m, "m", 2)))
    return "\n".join(lines)


def port_tooltip(title, flow_lps, static_pressure_pa, row=None):
    """
    Tooltip text for one port of a solved node: its own flow and static
    pressure, plus the fitting result on that leg when there is one (an
    AirflowSolver.ComponentPortRow): velocity, K, pressure drop and the loss
    status and path it came from.
    """
    lines = [title, "Flow: {}".format(_fmt(flow_lps, "L/s")), "Static pressure: {}".format(_fmt(static_pressure_pa, "Pa"))]
    if row is not None:
        lines += [
            "Velocity: {}".format(_fmt(row.velocity_ms, "m/s", 2)),
            "K: {}".format("-" if row.loss_coefficient is None else "{:.3f}".format(row.loss_coefficient)),
            "Pressure drop: {}".format(_fmt(row.pressure_drop_pa, "Pa")),
            "Loss: {}{}".format(row.status or "-", " ({})".format(row.path_label) if row.path_label else ""),
        ]
    return "\n".join(lines)


def component_tooltip(label, rows):
    """Tooltip text for a fitting: one block per leg with a result (ComponentPortRow), or a note when none."""
    if not rows:
        return "{}\nNo fitting loss on any leg".format(label)
    blocks = [label]
    for row in rows:
        blocks.append(
            "{}: {}, {}, K {}, drop {}, {}".format(
                row.path_label or row.leg_label,
                _fmt(row.flow_lps, "L/s"),
                _fmt(row.velocity_ms, "m/s", 2),
                "-" if row.loss_coefficient is None else "{:.3f}".format(row.loss_coefficient),
                _fmt(row.pressure_drop_pa, "Pa"),
                row.status or "-",
            )
        )
    return "\n".join(blocks)
