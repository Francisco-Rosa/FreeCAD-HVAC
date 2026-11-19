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
LossCoefficientSource == "Custom" support: which local ports get a
CustomLossCoefficients slot, and how those user-supplied K values turn into
a LossEvaluator (see analysis/model.py's LossEvaluator type and
analysis/loss.py's LossPath/LossEvaluation). Kept separate from
_analysis_adapter.py (which stays a thin "read the real FreeCAD object"
layer) per the repo's own "small, cohesive modules" convention.

Stored edge keys stay valid across a document reload (edge keys are
stable: see hvaclib.makeLineKey), so no carry-forward is needed.
"""

import json
import math

from ..analysis.loss import LossEvaluation, LossPath, LossStatus


def custom_loss_applicable_ports(local_ports):
    """
    Which local ports get a custom-K slot: the single port of a 1-port
    device, or -- for a fitting with exactly one port on one flow side and
    the rest on the other (plain through, diverging tee, converging tee,
    manifold) -- every port on the "many" side (the same side each library
    loss formula treats as its own reference edge). A true mixed cross (no
    single common side) has no custom-K support yet, same limitation
    manifold_loss already has for that shape -- returns [].
    """
    if len(local_ports) <= 1:
        return list(local_ports)
    inlets = [p for p in local_ports if p.get("flow_into_junction") is True]
    outlets = [p for p in local_ports if p.get("flow_into_junction") is False]
    if len(inlets) == 1:
        return outlets
    if len(outlets) == 1:
        return inlets
    return []


def _common_port(local_ports, applicable_ports):
    """
    The single port on local_ports' other flow side from `applicable_ports`
    -- every applicable port's own LossPath is built against this port's
    edge_key. None for a 1-port device (nothing on the "other side" at
    all) or for a mixed cross (no applicable ports to begin with).
    """
    if len(local_ports) <= 1:
        return None
    applicable_keys = {p.get("edge_key") for p in applicable_ports}
    others = [p for p in local_ports if p.get("edge_key") not in applicable_keys]
    return others[0] if len(others) == 1 else None


def _custom_path(port, other_edge_key, k):
    """Same from/to derivation as library/loss_api.py's own _leg_path -- direction
    always comes from the port's own flow_into_junction, never key ordering."""
    edge_key = port.get("edge_key")
    if port.get("flow_into_junction"):
        from_edge, to_edge = edge_key, other_edge_key
    else:
        from_edge, to_edge = other_edge_key, edge_key
    return LossPath(from_edge, to_edge, edge_key, float(k), source="custom")


def build_custom_loss_evaluator(comp_obj):
    """
    LossCoefficientSource == "Custom" path: map CustomLossCoefficients onto
    each applicable port's own edge_key (see custom_loss_applicable_ports()),
    entirely bypassing the library's own loss formula. CustomLossCoefficients
    and CustomLossCoefficientEdgeKeys are parallel lists -- the edge_key
    each K value belongs to is explicit, not positional, so this never
    depends on LocalPortsJson's own port order matching what's currently
    stored (Component.py's own sync keeps the two in step; this still
    validates it fresh here rather than trusting that blindly).

    Config is validated up front, not lazily inside the returned callable,
    so a bad Custom setup fails as soon as the network model is built --
    "fail clearly during analysis" per the feature's own contract, the same
    way library/validation.py raises ValueError for a malformed type-def
    property rather than silently falling back to a default.
    """
    # Lazy import: _analysis_adapter.py imports this module at call time
    # (build_loss_evaluator -> build_custom_loss_evaluator), so importing
    # it back at module scope here would be circular.
    from ._analysis_adapter import element_identifier

    local_ports = json.loads(getattr(comp_obj, "LocalPortsJson", "") or "[]")
    custom_k = list(getattr(comp_obj, "CustomLossCoefficients", None) or [])
    stored_edge_keys = list(getattr(comp_obj, "CustomLossCoefficientEdgeKeys", None) or [])
    label = element_identifier(comp_obj)

    applicable_ports = custom_loss_applicable_ports(local_ports)
    common_port = _common_port(local_ports, applicable_ports)
    common_edge_key = common_port.get("edge_key") if common_port is not None else None

    port_by_edge = {}
    expected_edge_keys = []
    for port in applicable_ports:
        edge_key = port.get("edge_key")
        if not edge_key:
            raise ValueError(
                "Component '{}': an applicable local port has no edge_key -- can't map its custom K.".format(label)
            )
        expected_edge_keys.append(edge_key)
        port_by_edge[edge_key] = port

    if len(custom_k) != len(stored_edge_keys):
        raise ValueError(
            "Component '{}': CustomLossCoefficients has {} value(s) but CustomLossCoefficientEdgeKeys has {} "
            "-- they must match 1:1.".format(label, len(custom_k), len(stored_edge_keys))
        )

    if set(stored_edge_keys) != set(expected_edge_keys) or len(stored_edge_keys) != len(expected_edge_keys):
        raise ValueError(
            "Component '{}': CustomLossCoefficients is out of sync with this component's current ports "
            "(expected K for {}, has K for {}) -- recompute the network to resync it.".format(
                label, sorted(expected_edge_keys), sorted(stored_edge_keys)
            )
        )

    k_by_edge = {}
    for edge_key, raw_k in zip(stored_edge_keys, custom_k):
        try:
            k_value = float(raw_k)
        except (TypeError, ValueError):
            k_value = float("nan")
        if not math.isfinite(k_value) or k_value < 0.0:
            raise ValueError(
                "Component '{}': custom loss coefficient for port '{}' is '{}' -- K must be finite "
                "and >= 0.".format(label, edge_key, raw_k)
            )
        k_by_edge[edge_key] = k_value

    paths = [
        _custom_path(port_by_edge[edge_key], common_edge_key, k_by_edge[edge_key])
        for edge_key in stored_edge_keys
    ]

    def evaluate(port_velocities):
        # Same paths every call -- a custom K never depends on the current
        # solve's flow (unlike a library formula's velocity-ratio tables).
        return LossEvaluation(paths=list(paths), status=LossStatus.CUSTOM)

    return evaluate
