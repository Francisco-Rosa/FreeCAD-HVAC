"""
Tests for the construction-layer property contract on DuctSegment/
DuctComponent: setProperties() itself no longer declares any fixed
Casing/Insulation shape/material properties -- those are now
Layer_<id>_Shape/Layer_<id>_Material pairs added dynamically per the
selected type's own declared construction (core/_construction_schema.py,
covered by tests/test_construction_schema.py). This file just guards that
setProperties() stays free of any such fixed properties, and that
DuctJunction stays entirely geometry-free -- see ARCHITECTURE.md's
"Component geometry & materials" section.
"""

import conftest  # noqa: F401 -- installs FreeCAD/FreeCADGui/Part/PySide stubs

from freecad.HVAC.core import Segment as segment_mod
from freecad.HVAC.core import Component as component_mod
from freecad.HVAC.core import Junction as junction_mod


class FakeObj:
    """Minimal stand-in for a FreeCAD DocumentObject's dynamic-property API,
    additionally recording each property's declared FreeCAD type so tests
    can check it (the reactive-property test fakes elsewhere don't need
    this, since they never assert on prop_type)."""

    def __init__(self):
        self.PropertiesList = []
        self._prop_types = {}
        self._prop_attrs = {}
        self._editor_modes = {}

    def addProperty(self, prop_type, name, group, description, attr=0):
        if name not in self.PropertiesList:
            self.PropertiesList.append(name)
            setattr(self, name, None)
        self._prop_types[name] = prop_type
        self._prop_attrs[name] = attr
        return self

    def removeProperty(self, name):
        if name in self.PropertiesList:
            self.PropertiesList.remove(name)
        if hasattr(self, name):
            delattr(self, name)
        return True

    def setEditorMode(self, name, mode):
        self._editor_modes[name] = mode


def _bare_segment(obj):
    ds = segment_mod.DuctSegment.__new__(segment_mod.DuctSegment)
    ds.Object = obj
    return ds


def _bare_component(obj):
    dc = component_mod.DuctComponent.__new__(component_mod.DuctComponent)
    dc.Object = obj
    return dc


def _assert_no_fixed_casing_insulation_properties(obj):
    for name in ("CasingShape", "InsulationShape", "CasingMaterial", "InsulationMaterial"):
        assert name not in obj.PropertiesList, name
    # No layer or feature property either -- those only ever get added by
    # apply_construction_schema()/apply_construction_features_schema(),
    # never by setProperties() itself.
    assert not any(name.startswith("Layer_") for name in obj.PropertiesList)
    assert not any(name.startswith("Feature_") for name in obj.PropertiesList)


def test_segment_setproperties_declares_no_fixed_layer_properties(monkeypatch):
    monkeypatch.setattr(
        segment_mod.hvaclib.HVACLibraryService, "get_active_hvac_library", staticmethod(lambda: None)
    )
    obj = FakeObj()
    ds = _bare_segment(obj)
    ds.setProperties(obj)

    _assert_no_fixed_casing_insulation_properties(obj)
    assert "ConstructionLayerIds" in obj.PropertiesList
    assert obj._editor_modes["ConstructionLayerIds"] == 2
    assert "ConstructionFeatureIds" in obj.PropertiesList
    assert obj._editor_modes["ConstructionFeatureIds"] == 2


def test_component_setproperties_declares_no_fixed_layer_properties(monkeypatch):
    monkeypatch.setattr(
        component_mod.hvaclib.HVACLibraryService, "get_active_hvac_library", staticmethod(lambda: None)
    )
    obj = FakeObj()
    dc = _bare_component(obj)
    dc.setProperties(obj)

    _assert_no_fixed_casing_insulation_properties(obj)
    assert "ConstructionLayerIds" in obj.PropertiesList
    assert obj._editor_modes["ConstructionLayerIds"] == 2
    assert "ConstructionFeatureIds" in obj.PropertiesList
    assert obj._editor_modes["ConstructionFeatureIds"] == 2


def test_junction_setproperties_has_no_geometry_or_material_properties():
    # DuctJunction is purely logical -- physical fitting geometry/materials
    # belong to its DuctComponent children, never to the junction itself.
    obj = FakeObj()
    dj = junction_mod.DuctJunction.__new__(junction_mod.DuctJunction)
    dj.Object = obj
    dj.setProperties(obj)

    _assert_no_fixed_casing_insulation_properties(obj)
    assert "ConstructionLayerIds" not in obj.PropertiesList
    assert "ConstructionFeatureIds" not in obj.PropertiesList


def test_setproperties_never_creates_a_document_object_for_materials(monkeypatch):
    """
    Regression guard for the native-material migration: a construction
    layer's material lives directly on its own Layer_<id>_Material property
    (Materials::PropertyMaterial -- see test_construction_schema.py) --
    setProperties() must never create a separate per-element material
    document object (the old App::MaterialObjectPython/
    App::PropertyLinkGlobal pattern). FakeObj has no addObject()/doc-creation
    method at all, so any such call would raise AttributeError rather than
    silently succeed.
    """
    monkeypatch.setattr(
        segment_mod.hvaclib.HVACLibraryService, "get_active_hvac_library", staticmethod(lambda: None)
    )
    obj = FakeObj()
    assert not hasattr(obj, "addObject")
    _bare_segment(obj).setProperties(obj)  # must not raise
