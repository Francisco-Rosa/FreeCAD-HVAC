"""
Tests for core/_geometry_apply.apply_computed_properties(): the generic
"copy a geometry backend's computed_properties onto matching schema-declared
object properties" mechanism shared by DuctComponent.execute() and
DuctSegment.execute() (see core/_geometry_apply.py).
"""

import conftest  # noqa: F401 -- installs FreeCAD/FreeCADGui/Part/PySide stubs

from freecad.HVAC.core import _geometry_apply
from freecad.HVAC.library.Library import HVACPropertyDef
from freecad.HVAC.library import geometry_result as geometry_result_mod


class FakeDuctObj:
    """Minimal stand-in for a FreeCAD DocumentObject's dynamic-property API."""

    def __init__(self):
        self.PropertiesList = []

    def addProperty(self, prop_type, name, group, description, attr=0):
        if name not in self.PropertiesList:
            self.PropertiesList.append(name)
            setattr(self, name, None)
        return self


class _FakeTypeDef:
    def __init__(self, properties):
        self.properties = properties


def _readonly_angle_pdef(name="angle", default=0.0):
    return HVACPropertyDef(
        name=name, prop_type="App::PropertyAngle", group="Bend geometry",
        description="", default=default, editor_mode=1,
    )


def _editable_length_pdef(name="Length", default=100.0):
    return HVACPropertyDef(
        name=name, prop_type="App::PropertyLength", group="Dimensions",
        description="", default=default, editor_mode=0,
    )


def _result(computed_properties=None):
    raw = {"layers": {"shape": {"shape": object()}}, "connection_lengths": []}
    if computed_properties is not None:
        raw["computed_properties"] = computed_properties
    return geometry_result_mod.normalize(raw)


def test_apply_sets_declared_readonly_property_from_computed_properties():
    obj = FakeDuctObj()
    obj.addProperty("App::PropertyAngle", "angle", "Bend geometry", "")
    type_def = _FakeTypeDef([_readonly_angle_pdef()])

    changed = _geometry_apply.apply_computed_properties(obj, type_def, _result({"angle": 42.0}))

    assert obj.angle == 42.0
    assert changed is True


def test_apply_updates_value_across_recomputes():
    obj = FakeDuctObj()
    obj.addProperty("App::PropertyAngle", "angle", "Bend geometry", "")
    type_def = _FakeTypeDef([_readonly_angle_pdef()])

    _geometry_apply.apply_computed_properties(obj, type_def, _result({"angle": 10.0}))
    assert obj.angle == 10.0

    # A later recompute (e.g. after a dimension/topology parameter change)
    # reports a different value -- it must overwrite, not stick.
    _geometry_apply.apply_computed_properties(obj, type_def, _result({"angle": 25.0}))
    assert obj.angle == 25.0


def test_apply_ignores_key_not_declared_by_active_schema():
    obj = FakeDuctObj()
    obj.addProperty("App::PropertyAngle", "angle", "Bend geometry", "")
    type_def = _FakeTypeDef([_readonly_angle_pdef()])

    _geometry_apply.apply_computed_properties(
        obj, type_def, _result({"angle": 42.0, "NotDeclared": 99.0})
    )

    assert obj.angle == 42.0
    assert not hasattr(obj, "NotDeclared")
    assert "NotDeclared" not in obj.PropertiesList


def test_apply_ignores_key_declared_but_not_present_on_object():
    # Declared by the schema, but the object never got the property added
    # (e.g. a stale/older object) -- must not error or fabricate it.
    obj = FakeDuctObj()
    type_def = _FakeTypeDef([_readonly_angle_pdef()])

    _geometry_apply.apply_computed_properties(obj, type_def, _result({"angle": 42.0}))

    assert not hasattr(obj, "angle")


def test_apply_with_empty_computed_properties_leaves_editable_property_untouched():
    obj = FakeDuctObj()
    obj.addProperty("App::PropertyLength", "Length", "Dimensions", "")
    obj.Length = 250.0
    type_def = _FakeTypeDef([_editable_length_pdef()])

    changed = _geometry_apply.apply_computed_properties(obj, type_def, _result())

    assert obj.Length == 250.0
    assert changed is False


def test_legacy_generator_return_with_no_computed_properties_key_does_not_error():
    obj = FakeDuctObj()
    obj.addProperty("App::PropertyAngle", "angle", "Bend geometry", "")
    obj.angle = 0.0
    type_def = _FakeTypeDef([_readonly_angle_pdef()])

    # A legacy generator's raw dict has no "computed_properties" key at all.
    result = geometry_result_mod.normalize({"layers": {"shape": {"shape": object()}}, "connection_lengths": []})

    changed = _geometry_apply.apply_computed_properties(obj, type_def, result)

    # No value reported, but the property has a schema default (0.0) -- since
    # the object already reads 0.0, nothing actually changes.
    assert obj.angle == 0.0
    assert changed is False


def test_apply_resets_stale_readonly_property_to_schema_default():
    obj = FakeDuctObj()
    obj.addProperty("App::PropertyAngle", "angle", "Bend geometry", "")
    type_def = _FakeTypeDef([_readonly_angle_pdef(default=0.0)])

    _geometry_apply.apply_computed_properties(obj, type_def, _result({"angle": 42.0}))
    assert obj.angle == 42.0

    # Next build's generator no longer reports "angle" (e.g. fitting family
    # changed to one with no bend) -- the stale 42.0 must not survive.
    _geometry_apply.apply_computed_properties(obj, type_def, _result({}))
    assert obj.angle == 0.0


def test_apply_leaves_readonly_property_with_no_default_unchanged_when_missing():
    obj = FakeDuctObj()
    obj.addProperty("App::PropertyAngle", "angle", "Bend geometry", "")
    obj.angle = 42.0
    type_def = _FakeTypeDef([_readonly_angle_pdef(default=None)])

    changed = _geometry_apply.apply_computed_properties(obj, type_def, _result({}))

    assert obj.angle == 42.0
    assert changed is False
