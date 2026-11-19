# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the HVAC addon.

"""
IFC mapping (ROADMAP design 6.8): the core lookup table from type families to
IFC classes, covering layers, system types and property sets. Pure code.
"""

import pytest

from freecad.HVAC.ifc import mapping
from freecad.HVAC.ifc.mapping import Classification


def _junction(families, **kwargs):
    kwargs.setdefault("topology", families[0].split(".")[0])
    return mapping.element_classification("junction", families, **kwargs)


# ----------------------------------------------------------------------------
# Element classes
# ----------------------------------------------------------------------------


def test_segments_are_rigid_or_flexible():
    assert mapping.element_classification("segment", ["straight_segment"]) == Classification(
        "IfcDuctSegment", "RIGIDSEGMENT"
    )
    assert mapping.element_classification("segment", ["curved_segment"]).predefined_type == "RIGIDSEGMENT"
    flex = mapping.element_classification("segment", ["straight_segment.flex", "curved_segment.flex"])
    assert flex == Classification("IfcDuctSegment", "FLEXIBLESEGMENT")


@pytest.mark.parametrize(
    "node_family, expected",
    [
        ("through.bend", Classification("IfcDuctFitting", "BEND")),
        ("through.bend_90", Classification("IfcDuctFitting", "BEND")),
        ("through.offset", Classification("IfcDuctFitting", "USERDEFINED", "Offset")),
        ("through.transition", Classification("IfcDuctFitting", "TRANSITION")),
        ("through.straight", Classification("IfcDuctFitting", "CONNECTOR")),
        ("branch.tee", Classification("IfcDuctFitting", "JUNCTION")),
        ("branch.lateral_tee.3d", Classification("IfcDuctFitting", "JUNCTION")),
        ("branch.wye", Classification("IfcDuctFitting", "JUNCTION")),
        ("cross.double_wye", Classification("IfcDuctFitting", "JUNCTION")),
        ("multiport.multiport", Classification("IfcDuctFitting", "JUNCTION")),
    ],
)
def test_generic_type_follows_the_node_family(node_family, expected):
    # through_generic lists straight, offset and transition: the node says which it is.
    families = ["through.straight", "through.offset", "through.transition"]
    if not node_family.startswith("through"):
        families = [node_family]
    assert _junction(families, node_family=node_family) == expected


def test_type_family_is_used_without_a_node_family():
    assert _junction(["through.bend", "through.bend.3d"]) == Classification("IfcDuctFitting", "BEND")


@pytest.mark.parametrize(
    "family, expected",
    [
        ("through.straight.fire_damper", Classification("IfcDamper", "FIREDAMPER")),
        ("through.straight.damper", Classification("IfcDamper", "BALANCINGDAMPER")),
        ("through.straight.vav", Classification("IfcAirTerminalBox", "VARIABLEFLOWPRESSUREDEPENDANT")),
        ("through.straight.filter", Classification("IfcFilter", "AIRPARTICLEFILTER")),
        ("through.straight.coil", Classification("IfcCoil", "NOTDEFINED")),
        ("through.straight.access_door", Classification("IfcDuctFitting", "USERDEFINED", "Access door")),
        ("through.straight.flex_connector", Classification("IfcDuctFitting", "CONNECTOR")),
        ("through.straight.obstruction", Classification("IfcDuctFitting", "OBSTRUCTION")),
    ],
)
def test_inline_devices(family, expected):
    assert _junction([family], role="Inline", node_family="through.straight") == expected


@pytest.mark.parametrize(
    "profile, predefined",
    [("Circular", "ROUND"), ("Rectangular", "RECTANGULAR"), ("Oval", "FLATOVAL"), ("", "NOTDEFINED")],
)
def test_silencer_by_profile(profile, predefined):
    result = _junction(["through.straight.silencer"], role="Inline", profile=profile)
    assert result == Classification("IfcDuctSilencer", predefined)


def test_tap_with_damper_stays_a_junction_fitting():
    # smacna branch_tap_straight_damper: the damper is part of a tee, not a device.
    result = _junction(["branch.tee.damper", "branch.tee.3d.damper"], node_family="branch.tee")
    assert result == Classification("IfcDuctFitting", "JUNCTION")


def test_plenum_on_any_topology():
    for families in (["through.straight.plenum"], ["branch.tee.plenum"], ["multiport.multiport.plenum"]):
        assert _junction(families) == Classification("IfcDuctFitting", "USERDEFINED", "Plenum")


@pytest.mark.parametrize(
    "families, expected",
    [
        (["end.terminal.diffuser"], Classification("IfcAirTerminal", "DIFFUSER")),
        (
            ["end.terminal.diffuser", "end.terminal.grille", "end.terminal.register"],
            Classification("IfcAirTerminal", "DIFFUSER"),
        ),
        (["end.terminal.grille"], Classification("IfcAirTerminal", "GRILLE")),
        (["end.terminal.register"], Classification("IfcAirTerminal", "REGISTER")),
        (["end.terminal.louver", "end.terminal.hood"], Classification("IfcAirTerminal", "LOUVRE")),
        (["end.terminal.entry"], Classification("IfcDuctFitting", "ENTRY")),
        (["end.terminal.exit"], Classification("IfcDuctFitting", "EXIT")),
        (["end.terminal.duct_closure"], Classification("IfcDuctFitting", "USERDEFINED", "End cap")),
        (["end.terminal.equipment"], Classification("IfcDuctFitting", "USERDEFINED", "Equipment connection")),
        (["end.terminal.fan", "end.terminal.ahu"], Classification("IfcFan", "NOTDEFINED")),
        (["end.terminal"], Classification("IfcDuctFitting", "NOTDEFINED")),
    ],
)
def test_terminals(families, expected):
    assert _junction(families, node_family="end.terminal") == expected


def test_hood_follows_the_air_direction():
    assert _junction(["end.terminal.hood"], leaves_system=True).predefined_type == "EXIT"
    assert _junction(["end.terminal.hood"], leaves_system=False).predefined_type == "ENTRY"
    assert _junction(["end.terminal.hood"]) == Classification("IfcDuctFitting", "USERDEFINED", "Hood")


def test_placeholders_are_not_defined():
    result = _junction(
        ["through.straight", "through.offset"], selection_kind="placeholder", node_family="through.offset"
    )
    assert result == Classification("IfcDuctFitting", "NOTDEFINED")


def test_unknown_family_is_not_defined():
    assert _junction(["through.something_new"]) == Classification("IfcDuctFitting", "NOTDEFINED")


def test_every_shipped_class_has_a_type_class_name():
    for ifc_class in mapping.ELEMENT_CLASSES:
        assert ifc_class.startswith("Ifc")
    assert mapping.EQUIPMENT_DEFAULT == ("IfcUnitaryEquipment", "AIRHANDLER")


def test_bim_type_names_round_trip():
    assert mapping.bim_type_name("IfcDuctFitting") == "Duct Fitting"
    assert mapping.bim_type_name("IfcAirTerminalBox") == "Air Terminal Box"
    for ifc_class in mapping.ELEMENT_CLASSES:
        assert mapping.ifc_class_from_bim_name(mapping.bim_type_name(ifc_class)) == ifc_class
    assert mapping.ifc_class_from_bim_name("") == ""


# ----------------------------------------------------------------------------
# Coverings, systems, ports
# ----------------------------------------------------------------------------


def test_covering_roles():
    assert mapping.covering_for_roles(["flow_surface", "structural_shell"]) is None
    assert mapping.covering_for_roles(["thermal_insulation"]) == ("INSULATION", "Thermal insulation")
    # The SMACNA liner faces the air but is still a covering.
    assert mapping.covering_for_roles(["flow_surface", "acoustic_absorber"]) == ("INSULATION", "Acoustic absorber")
    assert mapping.covering_for_roles(["vapor_barrier"]) == ("MEMBRANE", "Vapour barrier")
    assert mapping.covering_for_roles(["outer_jacket"]) == ("WRAPPING", "Outer jacket")
    assert mapping.covering_for_roles(["fire_protection"]) == ("USERDEFINED", "Fire protection")
    # A structural layer stays in the body even when it also insulates.
    assert mapping.covering_for_roles(["structural_shell", "thermal_insulation"]) is None
    # A roleless layer (a type not migrated to construction layers) is body.
    assert mapping.covering_for_roles([]) is None


def test_system_classification():
    assert mapping.system_classification("Supply") == ("VENTILATION", "Supply air")
    assert mapping.system_classification("Return") == ("VENTILATION", "Return air")
    assert mapping.system_classification("Exhaust") == ("EXHAUST", "Exhaust air")
    assert mapping.system_classification("OutdoorAir") == ("VENTILATION", "Outdoor air")
    assert mapping.system_classification("Supply", "AIRCONDITIONING") == ("AIRCONDITIONING", "Supply air")
    assert mapping.IFC_SYSTEM_TYPE_CHOICES[0] == "Auto"


def test_flow_direction():
    assert mapping.flow_direction(True) == "SINK"
    assert mapping.flow_direction(False) == "SOURCE"
    assert mapping.flow_direction(None) == "NOTDEFINED"


# ----------------------------------------------------------------------------
# Property sets
# ----------------------------------------------------------------------------


def test_property_map_units_and_format():
    props = mapping.property_map(
        section={"profile": "Rectangular", "width_mm": 400.0, "height_mm": 250.0, "diameter_mm": 0.0},
        layers=[
            {"id": "casing", "roles": ["flow_surface", "structural_shell"], "material": "Steel", "thickness_mm": 0.8},
            {"id": "insulation", "roles": ["thermal_insulation"], "material": "", "thickness_mm": 0.0},
        ],
        results={"flow_lps": 250.0, "velocity_ms": 2.5, "total_loss_pa": None},
        source={"library_id": "smacna", "type_id": "rectangular_straight", "key": "Sketch:0", "network": "Supply 1"},
    )
    assert props["Profile;;HVAC_Section"] == "IfcLabel;;Rectangular"
    assert props["Width;;HVAC_Section"] == "IfcPositiveLengthMeasure;;0.4"
    assert props["Height;;HVAC_Section"] == "IfcPositiveLengthMeasure;;0.25"
    assert "Diameter;;HVAC_Section" not in props
    assert props["casing Roles;;HVAC_Construction"] == "IfcLabel;;flow_surface, structural_shell"
    assert props["casing Thickness;;HVAC_Construction"] == "IfcPositiveLengthMeasure;;0.0008"
    assert props["casing Material;;HVAC_Construction"] == "IfcLabel;;Steel"
    assert "insulation Material;;HVAC_Construction" not in props
    assert "insulation Thickness;;HVAC_Construction" not in props
    assert props["FlowRate;;HVAC_Results"] == "IfcVolumetricFlowRateMeasure;;0.25"
    assert props["Velocity;;HVAC_Results"] == "IfcLinearVelocityMeasure;;2.5"
    assert "TotalLoss;;HVAC_Results" not in props
    assert props["Key;;HVAC_Source"] == "IfcIdentifier;;Sketch:0"


def test_property_map_strips_the_separator():
    props = mapping.property_map(source={"network": "A;;B"})
    assert props["Network;;HVAC_Source"] == "IfcLabel;;A;B"


def test_property_map_empty():
    assert mapping.property_map() == {}
