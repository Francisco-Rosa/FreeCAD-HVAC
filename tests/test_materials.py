"""
Tests for utils/materials.py: registering this addon's own .FCMat cards
with FreeCAD's native Material subsystem, and the small read-only helpers
core/ code uses to pull physical/appearance values off a
Materials::PropertyMaterial value -- see ARCHITECTURE.md's "Component
geometry & materials" section.
"""

import math
import os
import re

import conftest  # noqa: F401 -- installs FreeCAD/FreeCADGui/Part/Materials/PySide stubs

from freecad.HVAC.utils import hvaclib, materials as hvac_materials


class FakeParam:
    """Stand-in for the FreeCAD.ParamGet(...) group used during registration."""

    def __init__(self):
        self.values = {}

    def SetString(self, key, value):
        self.values[key] = value

    def SetBool(self, key, value):
        self.values[key] = value


class FakeQuantity:
    """Stand-in for Base.Quantity -- getPhysicalValue's real return type."""

    def __init__(self, value):
        self.Value = value


class FakeMaterial:
    """Stand-in for a Materials.Material value (what a construction layer's
    own Layer_<id>_Material actually is at runtime) -- both the
    "unassigned" and "real" shapes."""

    def __init__(self, name="", physical=None, appearance=None):
        self.Name = name
        self._physical = physical or {}
        self._appearance = appearance or {}

    def hasPhysicalProperty(self, name):
        return name in self._physical

    def getPhysicalValue(self, name):
        return self._physical.get(name)

    def hasAppearanceProperty(self, name):
        return name in self._appearance

    def getAppearanceValue(self, name):
        return self._appearance.get(name)


# ----------------------------------------------------------------------
# register_material_resources
# ----------------------------------------------------------------------

def test_register_material_resources_sets_module_dir_to_shipped_folder(monkeypatch):
    captured = {}

    def fake_param_get(path):
        captured["path"] = path
        param = FakeParam()
        captured["param"] = param
        return param

    monkeypatch.setattr(hvac_materials.FreeCAD, "ParamGet", fake_param_get)

    hvac_materials.register_material_resources()

    assert captured["path"] == (
        "User parameter:BaseApp/Preferences/Mod/Material/Resources/Modules/FreeCAD-HVAC"
    )
    materials_path = captured["param"].values["ModuleDir"]
    models_path = captured["param"].values["ModuleModelDir"]
    assert materials_path.endswith(("Resources/Materials", "Resources\\Materials"))
    assert models_path.endswith(("Resources/Models", "Resources\\Models"))
    import os
    assert os.path.isdir(materials_path)
    assert os.path.isdir(models_path)
    assert captured["param"].values["ModuleReadOnly"] is True


def test_register_material_resources_is_a_noop_if_resources_dir_missing(monkeypatch):
    monkeypatch.setattr(hvac_materials.hvaclib, "get_materials_base_path", lambda: "/no/such/dir")
    called = []
    monkeypatch.setattr(hvac_materials.FreeCAD, "ParamGet", lambda path: called.append(path))

    hvac_materials.register_material_resources()

    assert called == []


def test_register_material_resources_is_a_noop_if_models_dir_missing(monkeypatch):
    monkeypatch.setattr(
        hvac_materials.hvaclib, "get_material_models_base_path",
        lambda: "/no/such/dir",
    )
    called = []
    monkeypatch.setattr(hvac_materials.FreeCAD, "ParamGet", lambda path: called.append(path))

    hvac_materials.register_material_resources()

    assert called == []


# ----------------------------------------------------------------------
# get_material_by_uuid / default-material UUID constants
# ----------------------------------------------------------------------

def _card_uuid(relative_path):
    path = os.path.join(hvaclib.get_materials_base_path(), relative_path)
    with open(path, "r", encoding="utf-8") as handle:
        text = handle.read()
    match = re.search(r'UUID:\s*"([0-9a-fA-F-]+)"', text)
    return match.group(1)


def test_default_material_uuids_match_the_shipped_cards():
    # These constants are hand-copied from the .FCMat files' own UUIDs (see
    # Network.py's DefaultMaterial_StructuralShell/DefaultMaterial_
    # ThermalInsulation) -- if a card's UUID ever changes, this must fail
    # loudly rather than silently defaulting new networks to no material.
    assert hvac_materials.GALVANIZED_STEEL_UUID == _card_uuid("Metal/Galvanized-Steel.FCMat")
    assert hvac_materials.NITRILE_RUBBER_UUID == _card_uuid("Insulation/Nitrile-Rubber.FCMat")
    assert hvac_materials.NITRILE_RUBBER_OPEN_CELL_UUID == _card_uuid("Insulation/Nitrile-Rubber-Open-Cell.FCMat")
    assert hvac_materials.GALVANIZED_STEEL_PERFORATED_UUID == _card_uuid("Metal/Galvanized-Steel-Perforated.FCMat")
    assert hvac_materials.ALUMINIUM_UUID == _card_uuid("Metal/Aluminium.FCMat")
    assert hvac_materials.STAINLESS_STEEL_UUID == _card_uuid("Metal/Stainless-Steel.FCMat")


def test_get_material_by_uuid_returns_manager_lookup(monkeypatch):
    import sys
    from unittest.mock import MagicMock

    fake_material = object()
    fake_manager = MagicMock()
    fake_manager.getMaterial.return_value = fake_material
    fake_materials_module = MagicMock()
    fake_materials_module.MaterialManager.return_value = fake_manager
    monkeypatch.setitem(sys.modules, "Materials", fake_materials_module)

    result = hvac_materials.get_material_by_uuid("some-uuid")

    assert result is fake_material
    fake_manager.getMaterial.assert_called_once_with("some-uuid")


def test_get_material_by_uuid_returns_none_on_any_failure(monkeypatch):
    import sys
    from unittest.mock import MagicMock

    fake_materials_module = MagicMock()
    fake_materials_module.MaterialManager.side_effect = RuntimeError("registry not ready")
    monkeypatch.setitem(sys.modules, "Materials", fake_materials_module)

    assert hvac_materials.get_material_by_uuid("some-uuid") is None


# ----------------------------------------------------------------------
# get_physical_value
# ----------------------------------------------------------------------

def test_get_physical_value_returns_plain_float_from_quantity():
    material = FakeMaterial(name="Steel", physical={"Density": FakeQuantity(7.86e-06)})
    assert hvac_materials.get_physical_value(material, "Density") == 7.86e-06


def test_get_physical_value_none_for_unassigned_material():
    material = FakeMaterial(name="", physical={"Density": FakeQuantity(1.0)})
    assert hvac_materials.get_physical_value(material, "Density") is None


def test_get_physical_value_none_for_missing_material():
    assert hvac_materials.get_physical_value(None, "Density") is None


def test_get_physical_value_none_for_property_not_modeled():
    material = FakeMaterial(name="Steel", physical={})
    assert hvac_materials.get_physical_value(material, "ThermalConductivity") is None


def test_get_physical_value_none_for_nan_value():
    # FreeCAD reports a modeled-but-never-set property as NaN, not missing.
    material = FakeMaterial(name="Steel", physical={"ThermalConductivity": FakeQuantity(float("nan"))})
    assert hvac_materials.get_physical_value(material, "ThermalConductivity") is None


def test_shipped_uuid_without_card_property_has_no_implicit_roughness():
    material = FakeMaterial(name="Renamed material")
    material.UUID = hvac_materials.GALVANIZED_STEEL_UUID
    assert hvac_materials.get_hydraulic_roughness_mm(material) is None


def test_card_hydraulic_roughness_is_read_from_native_property():
    material = FakeMaterial(
        name="Galvanised Steel",
        physical={"HydraulicRoughness": FakeQuantity(0.2)},
    )
    material.UUID = hvac_materials.GALVANIZED_STEEL_UUID
    assert hvac_materials.get_hydraulic_roughness_mm(material) == 0.2


def test_zero_card_hydraulic_roughness_is_a_valid_value():
    material = FakeMaterial(
        name="Ideal smooth surface",
        physical={"HydraulicRoughness": FakeQuantity(0.0)},
    )
    assert hvac_materials.get_hydraulic_roughness_mm(material) == 0.0


def test_stock_display_name_without_stock_uuid_does_not_match_fallback():
    material = FakeMaterial(name="Galvanised Steel")
    material.UUID = "unrelated-user-material"
    assert hvac_materials.get_hydraulic_roughness_mm(material) is None


# ----------------------------------------------------------------------
# get_view_appearance
# ----------------------------------------------------------------------

def test_get_view_appearance_builds_material_struct_from_diffuse_color(monkeypatch):
    built = {}

    class FakeAppMaterial:
        def __init__(self):
            built["instance"] = self

    monkeypatch.setattr(hvac_materials.FreeCAD, "Material", FakeAppMaterial)

    material = FakeMaterial(
        name="Glass Wool",
        appearance={
            "DiffuseColor": "(0.9200, 0.8700, 0.5500, 1.0)",
            "Transparency": "0.0",
        },
    )
    appearance = hvac_materials.get_view_appearance(material)

    assert appearance is built["instance"]
    assert appearance.DiffuseColor == (0.92, 0.87, 0.55, 1.0)
    assert appearance.Transparency == 0.0


def test_get_view_appearance_none_for_unassigned_material():
    material = FakeMaterial(name="", appearance={"DiffuseColor": "(1,1,1,1)"})
    assert hvac_materials.get_view_appearance(material) is None


def test_get_view_appearance_none_without_diffuse_color():
    material = FakeMaterial(name="Steel", appearance={})
    assert hvac_materials.get_view_appearance(material) is None


def test_get_view_appearance_none_for_missing_material():
    assert hvac_materials.get_view_appearance(None) is None


def test_get_view_appearance_ignores_unparseable_secondary_fields(monkeypatch):
    monkeypatch.setattr(hvac_materials.FreeCAD, "Material", lambda: type("M", (), {})())

    material = FakeMaterial(
        name="Odd",
        appearance={"DiffuseColor": "(0.1, 0.2, 0.3, 1.0)", "Shininess": "not-a-number"},
    )
    appearance = hvac_materials.get_view_appearance(material)
    assert appearance.DiffuseColor == (0.1, 0.2, 0.3, 1.0)
    assert not hasattr(appearance, "Shininess")
