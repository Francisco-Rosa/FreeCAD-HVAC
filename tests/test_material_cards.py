"""
Structural checks on the .FCMat cards this addon ships under
freecad/HVAC/Resources/Materials/ -- verified to actually parse and load
correctly against a real FreeCAD 1.1 install during development (see
ARCHITECTURE.md's "Component geometry & materials" section); these tests
run without a real FreeCAD/Materials module, so they check the on-disk YAML
structure directly (regex-based -- this addon has no YAML dependency
otherwise, and .FCMat parsing itself is entirely FreeCAD's own job, not
something this addon should reimplement).
"""

import os
import re

import conftest  # noqa: F401 -- installs FreeCAD/FreeCADGui/Part/Materials/PySide stubs

from freecad.HVAC.utils import hvaclib

_UUID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE
)

# The standard FreeCAD model UUIDs every card must reuse (see
# utils/materials.py's module docstring) -- confirmed against a real
# FreeCAD 1.1 install's Resources/Models/*.yml.
_FATHER_MODEL_UUID = "9cdda8b6-b606-4778-8f13-3934d8668e67"
_DENSITY_MODEL_UUID = "454661e5-265b-4320-8e6f-fcf6223ac3af"
_THERMAL_MODEL_UUID = "9959d007-a970-4ea7-bae4-3eb1b8b883c7"
_BASIC_RENDERING_MODEL_UUID = "f006c7e4-35b7-43d5-bbf9-c5d572309e6e"
_HYDRAULIC_MODEL_UUID = "bbfee379-96b0-4995-80e2-e1725b3adfde"

_METAL_CARDS = [
    "Metal/Galvanized-Steel.FCMat",
    "Metal/Aluminium.FCMat",
    "Metal/Stainless-Steel.FCMat",
    "Metal/Galvanized-Steel-Perforated.FCMat",
]
_CASING_CARDS = [
    "Casing/PVC.FCMat",
    "Casing/Concrete.FCMat",
    "Casing/Fiberglass-Reinforced-Plastic.FCMat",
    "Casing/Galvanized-Steel-Spiral-Corrugated.FCMat",
    "Casing/Flexible-Duct-Fabric-and-Wire.FCMat",
    "Casing/Flexible-Duct-Metallic.FCMat",
]
_INSULATION_CARDS = [
    "Insulation/Glass-Wool.FCMat",
    "Insulation/Rock-Wool.FCMat",
    "Insulation/Nitrile-Rubber.FCMat",
    "Insulation/Polyurethane-Foam.FCMat",
    "Insulation/Expanded-Polystyrene.FCMat",
    "Insulation/Nitrile-Rubber-Open-Cell.FCMat",
]
_EXPECTED_CARDS = _METAL_CARDS + _CASING_CARDS + _INSULATION_CARDS


def _materials_root():
    return hvaclib.get_materials_base_path()


def _read(relative_path):
    with open(os.path.join(_materials_root(), relative_path), "r", encoding="utf-8") as handle:
        return handle.read()


def _field(text, name):
    """Pull a simple 'Name: "value"' or 'Name: value' scalar out of the card text."""
    match = re.search(r'^\s*{}:\s*"?([^"\n]+?)"?\s*$'.format(re.escape(name)), text, re.MULTILINE)
    return match.group(1) if match else None


def test_all_expected_cards_exist():
    for relative_path in _EXPECTED_CARDS:
        assert os.path.isfile(os.path.join(_materials_root(), relative_path)), relative_path


def test_every_card_has_a_unique_valid_uuid():
    uuids = []
    for relative_path in _EXPECTED_CARDS:
        text = _read(relative_path)
        uuid = _field(text, "UUID")
        assert uuid and _UUID_RE.fullmatch(uuid), "{}: bad UUID {!r}".format(relative_path, uuid)
        uuids.append(uuid.lower())
    assert len(uuids) == len(set(uuids)), "duplicate UUIDs across shipped cards"


def test_every_card_reuses_the_standard_physical_models():
    for relative_path in _EXPECTED_CARDS:
        text = _read(relative_path)
        assert _FATHER_MODEL_UUID in text, relative_path
        assert _DENSITY_MODEL_UUID in text, relative_path
        assert _THERMAL_MODEL_UUID in text, relative_path


def test_hydraulic_model_and_all_card_values_are_declared_with_units():
    model_path = os.path.join(
        hvaclib.get_material_models_base_path(), "HVAC", "Hydraulic.yml"
    )
    assert os.path.isfile(model_path)
    with open(model_path, "r", encoding="utf-8") as handle:
        model_text = handle.read()
    assert _HYDRAULIC_MODEL_UUID in model_text
    assert "HydraulicRoughness:" in model_text
    assert "Units: 'mm'" in model_text

    expected = {
        "Metal/Galvanized-Steel.FCMat": 0.09,
        "Metal/Galvanized-Steel-Perforated.FCMat": 0.9,
        "Metal/Aluminium.FCMat": 0.046,
        "Metal/Stainless-Steel.FCMat": 0.046,
        "Casing/PVC.FCMat": 0.046,
        "Casing/Concrete.FCMat": 3.0,
        "Casing/Fiberglass-Reinforced-Plastic.FCMat": 0.9,
        "Casing/Galvanized-Steel-Spiral-Corrugated.FCMat": 0.9,
        "Casing/Flexible-Duct-Fabric-and-Wire.FCMat": 0.9,
        "Casing/Flexible-Duct-Metallic.FCMat": 3.0,
        "Insulation/Glass-Wool.FCMat": 3.0,
        "Insulation/Rock-Wool.FCMat": 3.0,
        "Insulation/Nitrile-Rubber.FCMat": 0.9,
        "Insulation/Polyurethane-Foam.FCMat": 0.9,
        "Insulation/Expanded-Polystyrene.FCMat": 0.9,
        "Insulation/Nitrile-Rubber-Open-Cell.FCMat": 0.9,
    }
    for relative_path, roughness_mm in expected.items():
        text = _read(relative_path)
        assert _HYDRAULIC_MODEL_UUID in text, relative_path
        assert 'HydraulicRoughness: "{} mm"'.format(roughness_mm) in text


def test_every_card_declares_density_and_thermal_properties_with_units():
    for relative_path in _EXPECTED_CARDS:
        text = _read(relative_path)
        assert re.search(r"Density:\s*\"[\d.]+\s*kg/m\^3\"", text), relative_path
        assert re.search(r"ThermalConductivity:\s*\"[\d.]+\s*W/m/K\"", text), relative_path
        assert re.search(r"SpecificHeat:\s*\"[\d.]+\s*J/kg/K\"", text), relative_path


def test_every_card_declares_a_basic_rendering_appearance():
    for relative_path in _EXPECTED_CARDS:
        text = _read(relative_path)
        assert _BASIC_RENDERING_MODEL_UUID in text, relative_path
        assert re.search(r"DiffuseColor:\s*\"\([^)]+\)\"", text), relative_path


def test_metal_cards_are_filed_under_metal_and_insulation_cards_under_insulation():
    for relative_path in _METAL_CARDS:
        assert 'Father: "Metal"' in _read(relative_path), relative_path

    for relative_path in _INSULATION_CARDS:
        assert 'Father: "Insulation"' in _read(relative_path), relative_path


def test_insulation_cards_are_60_percent_transparent_so_ducts_show_through():
    for relative_path in _INSULATION_CARDS:
        assert re.search(r'Transparency:\s*"0\.6"', _read(relative_path)), relative_path

    for relative_path in _METAL_CARDS + _CASING_CARDS:
        assert re.search(r'Transparency:\s*"0\.0"', _read(relative_path)), relative_path


def test_perforated_galvanized_card_uses_new_name_only():
    new_path = os.path.join(_materials_root(), "Metal/Galvanized-Steel-Perforated.FCMat")
    old_path = os.path.join(_materials_root(), "Metal/Perforated-Galvanized-Steel.FCMat")
    assert os.path.isfile(new_path)
    assert not os.path.exists(old_path)
    assert _field(_read("Metal/Galvanized-Steel-Perforated.FCMat"), "Name") == (
        "Galvanized Steel - Perforated"
    )


def test_material_card_folder_contains_only_native_fc_mat_cards():
    # Model schemas live in Resources/Models, not mixed into the card tree.
    for dirpath, _dirs, filenames in os.walk(_materials_root()):
        for filename in filenames:
            assert filename.endswith(".FCMat"), os.path.join(dirpath, filename)
