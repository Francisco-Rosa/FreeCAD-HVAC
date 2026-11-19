# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the HVAC addon.

"""
Offsets: a jog between two parallel ducts of the same section whose axes are
displaced sideways. Three ways of making the jog:

- angled:    one straight inclined piece (SMACNA offset type 1)
- mitered:   straight ends with a mitred inclined piece between them (type 2)
- radiussed: an S-curve of two arcs (type 3, ogee)

An offset is a fitting of its own, with its own properties (OffsetLength,
OffsetRadius). Its shape is the same construction a transition between
displaced ports uses, so the geometry itself lives in transitions.py and is
only called from here with the offset's own property values.
"""

from . import transitions
from ._common import _props, _wall_thickness

# Offset property -> the property name the shared transition geometry reads.
_PROPERTY_MAP = {"OffsetLength": "TransitionLength", "OffsetRadius": "TransitionRadius"}


def _as_transition_context(context):
    """The same context, with the offset's own property values under the names the shared geometry reads."""
    params = _props(context)
    for offset_name, transition_name in _PROPERTY_MAP.items():
        if offset_name in params:
            params[transition_name] = params[offset_name]
    mapped = dict(context)
    mapped["properties"] = params
    return mapped


def _with_derived(context, result, radiussed=False):
    """Replace the transition's computed properties with the offset's own (ROADMAP 6.1)."""
    mapped = _as_transition_context(context)
    api = mapped["hvac_api"]
    dims = transitions.offset_dimensions(
        api, list(api.connected_ports(mapped)), _props(mapped), radiussed, _wall_thickness(mapped)
    )
    computed = {"BodyLength": dims["body_length"], "OffsetAngle": dims["offset_angle"]}
    if radiussed:
        computed["ActualRadius"] = dims["actual_radius"]
    result["computed_properties"] = computed
    return result


def measure_offset_angled(context):
    return transitions.measure_transition(_as_transition_context(context))


def build_offset_angled(context):
    """Offset type 1: one straight inclined piece between the two displaced ports."""
    return _with_derived(context, transitions.build_transition(_as_transition_context(context)))


def measure_offset_mitered(context):
    return transitions.measure_transition_mitered(_as_transition_context(context))


def build_offset_mitered(context):
    """Offset type 2: straight end pieces joined by a mitred inclined piece."""
    return _with_derived(context, transitions.build_transition_mitered(_as_transition_context(context)))


def measure_offset_radiussed(context):
    return transitions.measure_transition_radiussed(_as_transition_context(context))


def build_offset_radiussed(context):
    """Offset type 3: an S-curve of two arcs of radius OffsetRadius (reduced to what fits)."""
    return _with_derived(
        context, transitions.build_transition_radiussed(_as_transition_context(context)), radiussed=True
    )
