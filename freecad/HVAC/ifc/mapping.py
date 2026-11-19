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
What an HVAC object exports to IFC as (ROADMAP design 6.8). Pure: no FreeCAD,
no ifcopenshell, only plain strings and numbers in and out.

- `element_classification()`: the IFC class, predefined type and object type
  of a segment or component, looked up from its type-def families. This is
  the "core lookup table" of the design: libraries have no say in it yet.
- `covering_for_roles()`: whether a construction layer is part of the
  element's body or a separate IfcCovering, and which kind.
- `system_classification()`: the IfcDistributionSystem type of a network.
- `property_map()`: the property sets, in the format the BIM workbench
  exporter reads from an object's `IfcProperties` map.

All values are IFC4 names. IFC2X3 has no duct classes as occurrences, so the
export refuses it (see export.py).
"""

import re
from dataclasses import dataclass

# ----------------------------------------------------------------------------
# Element classes
# ----------------------------------------------------------------------------

DUCT_SEGMENT = "IfcDuctSegment"
DUCT_FITTING = "IfcDuctFitting"
AIR_TERMINAL = "IfcAirTerminal"
AIR_TERMINAL_BOX = "IfcAirTerminalBox"
DAMPER = "IfcDamper"
DUCT_SILENCER = "IfcDuctSilencer"
FILTER = "IfcFilter"
COIL = "IfcCoil"
FAN = "IfcFan"
UNITARY_EQUIPMENT = "IfcUnitaryEquipment"

# Every class an HVAC object may export as. Each has a matching type class
# (the name plus "Type"), used for the type objects (plan.py).
ELEMENT_CLASSES = (
    DUCT_SEGMENT,
    DUCT_FITTING,
    AIR_TERMINAL,
    AIR_TERMINAL_BOX,
    DAMPER,
    DUCT_SILENCER,
    FILTER,
    COIL,
    FAN,
    UNITARY_EQUIPMENT,
)

# Equipment default (design 6.8 A3): an air handling unit.
EQUIPMENT_DEFAULT = (UNITARY_EQUIPMENT, "AIRHANDLER")


@dataclass(frozen=True)
class Classification:
    """An IFC class plus its PredefinedType, and ObjectType when the type is USERDEFINED."""

    ifc_class: str
    predefined_type: str
    object_type: str = ""


def _userdefined(ifc_class, object_type):
    return Classification(ifc_class, "USERDEFINED", object_type)


# Inline devices, looked up by a token of the type's family (the last parts
# of e.g. "through.straight.fire_damper"). Only used on through types and
# inline components: "branch.tee.damper" is a tee with a damper, which stays
# a junction fitting. Checked in this order, so "fire_damper" wins over
# "damper".
_DEVICE_RULES = (
    ("fire_damper", Classification(DAMPER, "FIREDAMPER")),
    ("damper", Classification(DAMPER, "BALANCINGDAMPER")),
    ("vav", Classification(AIR_TERMINAL_BOX, "VARIABLEFLOWPRESSUREDEPENDANT")),
    ("silencer", None),  # by profile, see _silencer()
    ("filter", Classification(FILTER, "AIRPARTICLEFILTER")),
    ("coil", Classification(COIL, "NOTDEFINED")),
    ("access_door", _userdefined(DUCT_FITTING, "Access door")),
    ("flex_connector", Classification(DUCT_FITTING, "CONNECTOR")),
    ("obstruction", Classification(DUCT_FITTING, "OBSTRUCTION")),
)

# Terminals (end types), looked up the same way.
_TERMINAL_RULES = (
    ("diffuser", Classification(AIR_TERMINAL, "DIFFUSER")),
    ("grille", Classification(AIR_TERMINAL, "GRILLE")),
    ("register", Classification(AIR_TERMINAL, "REGISTER")),
    ("louver", Classification(AIR_TERMINAL, "LOUVRE")),
    ("entry", Classification(DUCT_FITTING, "ENTRY")),
    ("exit", Classification(DUCT_FITTING, "EXIT")),
    ("hood", None),  # entry or exit by the air direction, see _hood()
    ("duct_closure", _userdefined(DUCT_FITTING, "End cap")),
    ("equipment", _userdefined(DUCT_FITTING, "Equipment connection")),
    ("fan", Classification(FAN, "NOTDEFINED")),
    ("ahu", Classification(UNITARY_EQUIPMENT, "AIRHANDLER")),
)

# Plain fittings, looked up from the node's classified family (more precise
# than a generic type's list of families).
_FITTING_RULES = (
    ("bend", Classification(DUCT_FITTING, "BEND")),
    ("bend_90", Classification(DUCT_FITTING, "BEND")),
    ("offset", _userdefined(DUCT_FITTING, "Offset")),
    ("transition", Classification(DUCT_FITTING, "TRANSITION")),
    ("straight", Classification(DUCT_FITTING, "CONNECTOR")),
    ("tee", Classification(DUCT_FITTING, "JUNCTION")),
    ("wye", Classification(DUCT_FITTING, "JUNCTION")),
    ("lateral_tee", Classification(DUCT_FITTING, "JUNCTION")),
    ("cross", Classification(DUCT_FITTING, "JUNCTION")),
    ("double_wye", Classification(DUCT_FITTING, "JUNCTION")),
    ("multiport", Classification(DUCT_FITTING, "JUNCTION")),
)

NOT_DEFINED_FITTING = Classification(DUCT_FITTING, "NOTDEFINED")

_SILENCER_BY_PROFILE = {"Circular": "ROUND", "Rectangular": "RECTANGULAR", "Oval": "FLATOVAL"}


def _tokens(family):
    """The dot-separated parts of one family string, e.g. "through.straight.damper" -> ["through", ...]."""
    return [part for part in str(family or "").split(".") if part]


def _first_match(families, rules):
    """
    The first rule that matches, going through the families in their
    declared order (a type's first family says what it mainly is) and the
    rules in table order. Returns (token, classification) or None.
    """
    for family in families:
        tokens = set(_tokens(family))
        for token, classification in rules:
            if token in tokens:
                return token, classification
    return None


def _silencer(profile):
    return Classification(DUCT_SILENCER, _SILENCER_BY_PROFILE.get(str(profile or ""), "NOTDEFINED"))


def _hood(leaves_system):
    """A hood is an exit where the air leaves the duct system and an entry where it comes in."""
    if leaves_system is None:
        return _userdefined(DUCT_FITTING, "Hood")
    return Classification(DUCT_FITTING, "EXIT" if leaves_system else "ENTRY")


def element_classification(
    category,
    families=(),
    node_family="",
    topology="",
    role="Primary",
    selection_kind="",
    profile="",
    leaves_system=None,
):
    """
    The IFC classification of one segment or component.

    category        "segment" or "junction" (the type-def's category)
    families        the type-def's own family list, in declared order
    node_family     the classified family of the node a Primary sits on
                    (ignored for inline components)
    topology        the type-def's topology (through, branch, ..., end)
    role            "Primary" or "Inline"
    selection_kind  the type-def's selection kind: "placeholder" types
                    (markers) are not real fittings
    profile         the duct profile, for silencers
    leaves_system   for a hood: True when air leaves the duct system there,
                    False when it comes in, None when unknown
    """
    families = [str(f) for f in (families or []) if f]

    # Step 1: ducts.
    if category == "segment":
        flexible = any("flex" in _tokens(f) for f in families)
        return Classification(DUCT_SEGMENT, "FLEXIBLESEGMENT" if flexible else "RIGIDSEGMENT")

    # Step 2: markers and placeholders stand for "no fitting chosen yet".
    if selection_kind == "placeholder":
        return NOT_DEFINED_FITTING

    # Step 3: inline devices, only on through types or inline components.
    if role == "Inline" or topology == "through":
        match = _first_match(families, _DEVICE_RULES)
        if match is not None:
            token, classification = match
            return _silencer(profile) if token == "silencer" else classification

    # Step 4: a plenum box, on any topology.
    if _first_match(families, (("plenum", None),)) is not None:
        return _userdefined(DUCT_FITTING, "Plenum")

    # Step 5: terminals.
    if topology == "end":
        match = _first_match(families, _TERMINAL_RULES)
        if match is not None:
            token, classification = match
            return _hood(leaves_system) if token == "hood" else classification
        return NOT_DEFINED_FITTING

    # Step 6: plain fittings, from the node's own family when there is one.
    lookup = [node_family] if (node_family and role != "Inline") else []
    match = _first_match(lookup + families, _FITTING_RULES)
    if match is not None:
        return match[1]
    return NOT_DEFINED_FITTING


def bim_type_name(ifc_class):
    """
    The BIM workbench spelling of an IFC class, as its `IfcType` property
    holds it: "IfcDuctFitting" -> "Duct Fitting". The exporter turns it back
    by removing the spaces and adding "Ifc".
    """
    name = str(ifc_class or "")
    if name.startswith("Ifc"):
        name = name[3:]
    return re.sub(r"(?<!^)(?=[A-Z])", " ", name)


def ifc_class_from_bim_name(bim_name):
    """The reverse of bim_type_name(): "Duct Fitting" -> "IfcDuctFitting"."""
    name = str(bim_name or "").replace(" ", "")
    if not name:
        return ""
    return name if name.startswith("Ifc") else "Ifc" + name


# ----------------------------------------------------------------------------
# Construction layers: body or covering
# ----------------------------------------------------------------------------

ROLE_STRUCTURAL_SHELL = "structural_shell"

# Layer roles that make a layer a separate IfcCovering (design 6.8 A6), in
# the order a layer with several of them is judged by.
COVERING_ROLES = (
    ("thermal_insulation", "INSULATION", "Thermal insulation"),
    ("acoustic_liner", "INSULATION", "Acoustic liner"),
    ("acoustic_absorber", "INSULATION", "Acoustic absorber"),
    ("vapor_barrier", "MEMBRANE", "Vapour barrier"),
    ("outer_jacket", "WRAPPING", "Outer jacket"),
    ("fire_protection", "USERDEFINED", "Fire protection"),
)


def covering_for_roles(roles):
    """
    (PredefinedType, ObjectType) of the IfcCovering a layer with these roles
    becomes, or None when the layer belongs to the element's body.

    A structural layer always stays in the body, even if it also insulates.
    A liner that faces the air (roles flow_surface + acoustic_absorber) is a
    covering: the duct itself is the casing around it.
    """
    roles = set(roles or ())
    if ROLE_STRUCTURAL_SHELL in roles:
        return None
    for role, predefined_type, object_type in COVERING_ROLES:
        if role in roles:
            return predefined_type, object_type
    return None


# ----------------------------------------------------------------------------
# Systems and ports
# ----------------------------------------------------------------------------

# IFC4's IfcDistributionSystemEnum has no supply-air or return-air value, so
# the system's name carries the real function (design 6.8 B3).
SYSTEM_TYPE_DEFAULTS = {
    "Supply": "VENTILATION",
    "Return": "VENTILATION",
    "Exhaust": "EXHAUST",
    "OutdoorAir": "VENTILATION",
}
SYSTEM_LONG_NAMES = {
    "Supply": "Supply air",
    "Return": "Return air",
    "Exhaust": "Exhaust air",
    "OutdoorAir": "Outdoor air",
}

# Choices of the network's IfcSystemType property; "Auto" means the default above.
IFC_SYSTEM_TYPE_CHOICES = ["Auto", "VENTILATION", "AIRCONDITIONING", "EXHAUST"]


def system_classification(system_type, override="Auto"):
    """(IfcDistributionSystemEnum value, long name) of a network's system."""
    system_type = str(system_type or "")
    long_name = SYSTEM_LONG_NAMES.get(system_type, system_type or "Air")
    override = str(override or "Auto")
    if override != "Auto":
        return override, long_name
    return SYSTEM_TYPE_DEFAULTS.get(system_type, "VENTILATION"), long_name


def flow_direction(flow_in):
    """IfcFlowDirectionEnum of a port: air enters the element there (SINK), leaves it (SOURCE), or unknown."""
    if flow_in is None:
        return "NOTDEFINED"
    return "SINK" if flow_in else "SOURCE"


# ----------------------------------------------------------------------------
# Property sets
# ----------------------------------------------------------------------------

PSET_SECTION = "HVAC_Section"
PSET_CONSTRUCTION = "HVAC_Construction"
PSET_RESULTS = "HVAC_Results"
PSET_SOURCE = "HVAC_Source"


def _clean_text(value):
    """Text safe for the exporter's "type;;value" encoding."""
    return str(value if value is not None else "").replace(";;", ";").strip()


def _number(value):
    return "{:.6g}".format(float(value))


def property_map(section=None, layers=(), results=None, source=None):
    """
    The `IfcProperties` map the BIM workbench exporter turns into property
    sets: {"<name>;;<pset>": "<IFC type>;;<value>"}.

    section  {"profile", "diameter_mm", "width_mm", "height_mm"}; sizes of 0
             or None are left out
    layers   [{"id", "roles", "material", "thickness_mm"}, ...]
    results  {"flow_lps", "velocity_ms", "friction_loss_pa", "fitting_loss_pa",
             "total_loss_pa", "static_pressure_pa", "loss_coefficient",
             "pressure_drop_pa"}; None values are left out
    source   {"library_id", "type_id", "key", "network"}

    Lengths are written in metres and flows in m3/s: the exporter copies
    numbers as they are, and the file's units are SI with metres.
    """
    out = {}

    def put(pset, name, ifc_type, value):
        if value is None or value == "":
            return
        text = _number(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else _clean_text(value)
        out["{};;{}".format(_clean_text(name), pset)] = "{};;{}".format(ifc_type, text)

    # Step 1: the cross-section.
    section = section or {}
    put(PSET_SECTION, "Profile", "IfcLabel", section.get("profile"))
    for key, name in (("diameter_mm", "Diameter"), ("width_mm", "Width"), ("height_mm", "Height")):
        value = section.get(key)
        if value:
            put(PSET_SECTION, name, "IfcPositiveLengthMeasure", float(value) / 1000.0)

    # Step 2: one group of entries per construction layer, in build order.
    for layer in layers or ():
        layer_id = _clean_text(layer.get("id"))
        if not layer_id:
            continue
        put(PSET_CONSTRUCTION, "{} Roles".format(layer_id), "IfcLabel", ", ".join(layer.get("roles") or ()))
        put(PSET_CONSTRUCTION, "{} Material".format(layer_id), "IfcLabel", layer.get("material"))
        thickness = layer.get("thickness_mm")
        if thickness:
            put(PSET_CONSTRUCTION, "{} Thickness".format(layer_id), "IfcPositiveLengthMeasure", thickness / 1000.0)

    # Step 3: calculated results.
    results = results or {}
    flow = results.get("flow_lps")
    put(PSET_RESULTS, "FlowRate", "IfcVolumetricFlowRateMeasure", None if flow is None else flow / 1000.0)
    put(PSET_RESULTS, "Velocity", "IfcLinearVelocityMeasure", results.get("velocity_ms"))
    put(PSET_RESULTS, "FrictionLoss", "IfcPressureMeasure", results.get("friction_loss_pa"))
    put(PSET_RESULTS, "FittingLoss", "IfcPressureMeasure", results.get("fitting_loss_pa"))
    put(PSET_RESULTS, "TotalLoss", "IfcPressureMeasure", results.get("total_loss_pa"))
    put(PSET_RESULTS, "StaticPressure", "IfcPressureMeasure", results.get("static_pressure_pa"))
    put(PSET_RESULTS, "LossCoefficient", "IfcReal", results.get("loss_coefficient"))
    put(PSET_RESULTS, "PressureDrop", "IfcPressureMeasure", results.get("pressure_drop_pa"))

    # Step 4: where the element came from, for a later round trip.
    source = source or {}
    put(PSET_SOURCE, "LibraryId", "IfcIdentifier", source.get("library_id"))
    put(PSET_SOURCE, "TypeId", "IfcIdentifier", source.get("type_id"))
    put(PSET_SOURCE, "Key", "IfcIdentifier", source.get("key"))
    put(PSET_SOURCE, "Network", "IfcLabel", source.get("network"))
    return out
