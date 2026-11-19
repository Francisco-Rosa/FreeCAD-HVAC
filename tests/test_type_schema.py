"""
Focused tests for the shared apply_type_schema helper (core/_type_schema.py):
dynamic property add/remove/default/editor_mode syncing driven by a type-def's
declared properties, and the `protected_names` wrinkle that lets DuctSegment's
permanent Diameter/Width/Height participate in editor-mode syncing without
ever being removed.
"""

import conftest  # noqa: F401 -- installs FreeCAD/FreeCADGui/Part/PySide stubs
from freecad.HVAC.core import _type_schema
from freecad.HVAC.library.Library import HVACPropertyDef


class FakeDuctObj:
    """Minimal stand-in for a FreeCAD DocumentObject's dynamic-property API."""

    def __init__(self):
        self.PropertiesList = []
        self._editor_modes = {}

    def addProperty(self, prop_type, name, group, description, attr=0):
        if name not in self.PropertiesList:
            self.PropertiesList.append(name)
            setattr(self, name, None)
        return self

    def removeProperty(self, name):
        if name in self.PropertiesList:
            self.PropertiesList.remove(name)
        if hasattr(self, name):
            delattr(self, name)
        return True

    def setEditorMode(self, name, mode):
        self._editor_modes[name] = mode


class _FakeTypeDef:
    def __init__(self, properties):
        self.properties = properties


class _FakeRegistry:
    def __init__(self, type_def):
        self._type_def = type_def

    def resolve_type(self, lib_id, type_id):
        return self._type_def


def _patch_registry(monkeypatch, registry):
    monkeypatch.setattr(
        _type_schema.hvaclib.HVACLibraryService, "get_hvac_library_registry", staticmethod(lambda: registry)
    )


def test_apply_type_schema_honors_editor_mode(monkeypatch):
    properties = [
        HVACPropertyDef(
            name="w_side_1", prop_type="App::PropertyLength", group="Side 1", description="", default=0.0, editor_mode=1
        ),
        HVACPropertyDef(
            name="r_axis",
            prop_type="App::PropertyLength",
            group="Bend geometry",
            description="",
            default=300.0,
            editor_mode=0,
        ),
    ]
    obj = FakeDuctObj()
    _patch_registry(monkeypatch, _FakeRegistry(_FakeTypeDef(properties)))

    _type_schema.apply_type_schema(obj, "smacna", "through_elbow_rectangular")

    assert obj._editor_modes["w_side_1"] == 1
    assert obj._editor_modes["r_axis"] == 0
    assert obj.w_side_1 == 0.0
    assert obj.r_axis == 300.0


def test_apply_type_schema_removes_properties_from_a_previous_type(monkeypatch):
    old_properties = [
        HVACPropertyDef(
            name="r_axis", prop_type="App::PropertyLength", group="Bend geometry", description="", default=300.0
        ),
        HVACPropertyDef(
            name="flange_height", prop_type="App::PropertyLength", group="Flanges", description="", default=25.0
        ),
    ]
    new_properties = [
        HVACPropertyDef(
            name="NeckSize", prop_type="App::PropertyLength", group="Dimensions", description="", default=150.0
        )
    ]
    obj = FakeDuctObj()
    registry = _FakeRegistry(_FakeTypeDef(old_properties))
    _patch_registry(monkeypatch, registry)

    _type_schema.apply_type_schema(obj, "smacna", "through_elbow_rectangular")
    assert {"r_axis", "flange_height"} <= set(obj.PropertiesList)

    # Simulate switching TypeId to a different fitting whose schema doesn't
    # declare r_axis/flange_height at all.
    registry._type_def = _FakeTypeDef(new_properties)
    _type_schema.apply_type_schema(obj, "smacna", "end_diffuser_generic")

    assert "r_axis" not in obj.PropertiesList
    assert "flange_height" not in obj.PropertiesList
    assert not hasattr(obj, "r_axis")
    assert "NeckSize" in obj.PropertiesList


def test_apply_type_schema_does_not_clobber_user_edited_value(monkeypatch):
    properties = [
        HVACPropertyDef(
            name="r_axis", prop_type="App::PropertyLength", group="Bend geometry", description="", default=300.0
        )
    ]
    obj = FakeDuctObj()
    _patch_registry(monkeypatch, _FakeRegistry(_FakeTypeDef(properties)))

    _type_schema.apply_type_schema(obj, "smacna", "through_elbow_rectangular")
    assert obj.r_axis == 300.0

    # User edits the value, then a resync re-applies the same schema.
    obj.r_axis = 450.0
    changed = _type_schema.apply_type_schema(obj, "smacna", "through_elbow_rectangular")

    assert obj.r_axis == 450.0
    assert changed is False


def test_protected_names_are_never_removed_but_editor_mode_still_tracks_relevance(monkeypatch):
    """
    Mirrors DuctSegment's Diameter/Width/Height: permanent core properties
    that must survive a type switch even when the newly-selected type
    doesn't declare them, but whose visibility should still hide/show based
    on whether the active type cares about them.
    """
    obj = FakeDuctObj()
    obj.addProperty("App::PropertyLength", "Diameter", "HVAC", "")
    obj.Diameter = 200.0

    rectangular_properties = [
        HVACPropertyDef(name="Width", prop_type="App::PropertyLength", group="HVAC", description="", default=100.0)
    ]
    registry = _FakeRegistry(_FakeTypeDef(rectangular_properties))
    monkeypatch.setattr(
        _type_schema.hvaclib.HVACLibraryService, "get_hvac_library_registry", staticmethod(lambda: registry)
    )

    _type_schema.apply_type_schema(
        obj, "smacna", "rectangular_straight", protected_names=("Diameter", "Width", "Height")
    )

    # Diameter isn't declared by this type -- hidden, but not removed, and
    # its user value survives.
    assert "Diameter" in obj.PropertiesList
    assert obj.Diameter == 200.0
    assert obj._editor_modes["Diameter"] == 1
    # Width IS declared -- visible.
    assert obj._editor_modes["Width"] == 0


# ----------------------------------------------------------------------------
# Enumeration properties: choices come from the type-def's validation.enum
# ----------------------------------------------------------------------------


class FakeEnumObj(FakeDuctObj):
    """Adds FreeCAD's enumeration behaviour: assigning a list sets the choices, a string picks one."""

    def __init__(self):
        super().__init__()
        object.__setattr__(self, "_choices", {})

    def __setattr__(self, name, value):
        if isinstance(value, list) and name in getattr(self, "_enum_names", ()):
            self._choices[name] = list(value)
            object.__setattr__(self, name, value[0])
            return
        object.__setattr__(self, name, value)

    def addProperty(self, prop_type, name, group, description, attr=0):
        if prop_type == "App::PropertyEnumeration":
            object.__setattr__(self, "_enum_names", set(getattr(self, "_enum_names", set())) | {name})
        return super().addProperty(prop_type, name, group, description, attr)

    def getEnumerationsOfProperty(self, name):
        return self._choices.get(name, [])


def _attachment_def(choices, default="Auto"):
    return HVACPropertyDef(
        name="Attachment",
        prop_type="App::PropertyEnumeration",
        group="Options",
        description="",
        default=default,
        validation={"enum": choices},
    )


def test_enumeration_gets_its_choices_and_default(monkeypatch):
    obj = FakeEnumObj()
    _patch_registry(monkeypatch, _FakeRegistry(_FakeTypeDef([_attachment_def(["Auto", "Side", "Face"])])))
    assert _type_schema.apply_type_schema(obj, "lib", "type") is True
    assert obj.getEnumerationsOfProperty("Attachment") == ["Auto", "Side", "Face"]
    assert obj.Attachment == "Auto"


def test_enumeration_keeps_the_users_choice_when_choices_change(monkeypatch):
    obj = FakeEnumObj()
    _patch_registry(monkeypatch, _FakeRegistry(_FakeTypeDef([_attachment_def(["Auto", "Side", "Face"])])))
    _type_schema.apply_type_schema(obj, "lib", "type")
    obj.Attachment = "Face"
    _patch_registry(monkeypatch, _FakeRegistry(_FakeTypeDef([_attachment_def(["Auto", "Face"])])))
    _type_schema.apply_type_schema(obj, "lib", "type")
    assert obj.getEnumerationsOfProperty("Attachment") == ["Auto", "Face"]
    assert obj.Attachment == "Face"


def test_enumeration_falls_back_to_default_when_the_choice_is_gone(monkeypatch):
    obj = FakeEnumObj()
    _patch_registry(monkeypatch, _FakeRegistry(_FakeTypeDef([_attachment_def(["Auto", "Side", "Face"])])))
    _type_schema.apply_type_schema(obj, "lib", "type")
    obj.Attachment = "Side"
    _patch_registry(monkeypatch, _FakeRegistry(_FakeTypeDef([_attachment_def(["Auto", "Face"])])))
    _type_schema.apply_type_schema(obj, "lib", "type")
    assert obj.Attachment == "Auto"


def test_enumeration_choices_are_not_reset_when_unchanged(monkeypatch):
    obj = FakeEnumObj()
    _patch_registry(monkeypatch, _FakeRegistry(_FakeTypeDef([_attachment_def(["Auto", "Side"])])))
    _type_schema.apply_type_schema(obj, "lib", "type")
    obj.Attachment = "Side"
    assert _type_schema.apply_type_schema(obj, "lib", "type") is False
    assert obj.Attachment == "Side"
