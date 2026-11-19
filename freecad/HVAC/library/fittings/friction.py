# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the HVAC addon.

"""
Standard straight-duct friction model factories shared by every library.

A segment type-def points at one of these with
`"friction": {"module": "shared:friction", "function": "friction_flex_compressed"}`.
Each receives the context described in HVACLibraryRegistry.call_friction()
and returns an analysis.friction model. `context["base_model"]` is the
network's own model (None for the default Darcy-Weisbach); a factory that
only corrects it should wrap it, so a project-wide friction table still
applies underneath.
"""


def friction_flex_compressed(context):
    """
    Flexible duct: the network's friction model times the SMACNA Fig. 14-4
    correction for `CompressionPercent` (percent of the fully extended
    length the duct is shortened by, 0 to 30).
    """
    friction = context["friction"]
    properties = context.get("properties") or {}
    percent = float(properties.get("CompressionPercent", 0.0) or 0.0)
    factor = friction.flex_compression_factor(percent)
    return friction.ScaledFriction(
        context.get("base_model"), factor, label="flexible duct, {:.0f} % compressed (x {:.2f})".format(percent, factor)
    )
