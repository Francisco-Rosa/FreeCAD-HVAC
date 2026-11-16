# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the HVAC addon.

"""
Drop-downs narrowed to the choices that suit a fitting's geometry
(core/_geometry_apply.apply_property_choices), kept narrowed by the type
schema sync (core/_type_schema._sync_enumeration_choices), and the network
sync a user's property edit asks for (core/_type_schema.request_sync_after_edit).
"""

import conftest  # noqa: F401 -- installs FreeCAD/FreeCADGui/Part/PySide stubs
from freecad.HVAC.core import _geometry_apply, _type_schema
from freecad.HVAC.library import geometry_result as gr
from freecad.HVAC.library.Library import HVACPropertyDef

_CHOICES = ["None", "Transition", "Casing"]


class _EnumObj:
    """A stand-in for a FreeCAD object with one enumeration property (Mode)."""

    def __init__(self, choices=_CHOICES, value="None"):
        self.PropertiesList = ["Mode"]
        self._choices = list(choices)
        self._value = value
        self.writes = 0

    def getEnumerationsOfProperty(self, name):
        return list(self._choices)

    def __setattr__(self, name, value):
        if name == "Mode":
            self.writes += 1
            if isinstance(value, list):
                self._choices = list(value)
                if self._value not in self._choices:
                    self._value = self._choices[0]
            else:
                assert value in self._choices
                self._value = value
            return
        object.__setattr__(self, name, value)

    def __getattr__(self, name):
        if name == "Mode":
            return self._value
        raise AttributeError(name)


def _pdef(default="None"):
    return HVACPropertyDef(
        name="Mode",
        prop_type="App::PropertyEnumeration",
        group="Parameters",
        description="",
        default=default,
        validation={"enum": list(_CHOICES)},
    )


class _TypeDef:
    def __init__(self, pdef):
        self.properties = [pdef]


def _apply(obj, offered):
    result = gr.GeometryResult(property_choices=offered)
    return _geometry_apply.apply_property_choices(obj, _TypeDef(_pdef()), result)


def test_choices_are_narrowed_in_type_def_order():
    obj = _EnumObj()
    assert _apply(obj, {"Mode": ["Casing", "None"]})
    assert obj.getEnumerationsOfProperty("Mode") == ["None", "Casing"]


def test_a_value_no_longer_offered_falls_back_to_the_default():
    obj = _EnumObj(value="Transition")
    _apply(obj, {"Mode": ["None", "Casing"]})
    assert obj.Mode == "None"


def test_a_value_still_offered_is_kept():
    obj = _EnumObj(value="Casing")
    _apply(obj, {"Mode": ["None", "Casing"]})
    assert obj.Mode == "Casing"


def test_a_drop_down_the_backend_does_not_name_gets_every_choice_back():
    obj = _EnumObj(choices=["None"])
    assert _apply(obj, {})
    assert obj.getEnumerationsOfProperty("Mode") == _CHOICES


def test_unknown_offered_choices_never_empty_the_list():
    obj = _EnumObj()
    _apply(obj, {"Mode": ["Nonsense"]})
    assert obj.getEnumerationsOfProperty("Mode") == _CHOICES


def test_unchanged_choices_are_not_rewritten():
    obj = _EnumObj(choices=["None", "Casing"])
    assert not _apply(obj, {"Mode": ["None", "Casing"]})
    assert obj.writes == 0


def test_type_schema_sync_keeps_a_narrowed_drop_down():
    # Widening it on every sync would mark the object changed each time.
    obj = _EnumObj(choices=["None", "Casing"])
    assert not _type_schema._sync_enumeration_choices(obj, _pdef())
    assert obj.getEnumerationsOfProperty("Mode") == ["None", "Casing"]


def test_type_schema_sync_resets_choices_the_type_def_does_not_declare():
    obj = _EnumObj(choices=["None", "Other"])
    assert _type_schema._sync_enumeration_choices(obj, _pdef())
    assert obj.getEnumerationsOfProperty("Mode") == _CHOICES


# ----------------------------------------------------------------------------
# request_sync_after_edit
# ----------------------------------------------------------------------------


class _Owner:
    def __init__(self, syncing=False):
        self.Proxy = self
        self._sync_in_progress = syncing
        self.requests = []

    def requestSync(self, **kwargs):
        self.requests.append(kwargs)


class _Doc:
    Restoring = False


class _EditedObj:
    def __init__(self, executing=False, modes=None):
        self.TypeSchemaPropertyNames = ["Thickness"]
        self.Document = _Doc()
        self.Proxy = type("P", (), {"_executing": executing})()
        self._modes = modes or {}

    def getEditorMode(self, name):
        return self._modes.get(name, [])


def _edit(monkeypatch, obj, prop, owner, extra=()):
    monkeypatch.setattr(_type_schema.hvaclib, "getOwnerNetwork", lambda o: owner)
    return _type_schema.request_sync_after_edit(obj, prop, extra)


def test_a_user_edit_of_a_type_property_requests_a_sync(monkeypatch):
    owner = _Owner()
    assert _edit(monkeypatch, _EditedObj(), "Thickness", owner)
    assert owner.requests == [{"force_recompute": True}]


def test_a_listed_extra_property_requests_a_sync(monkeypatch):
    owner = _Owner()
    assert _edit(monkeypatch, _EditedObj(), "Diameter", owner, extra=("Diameter",))


def test_other_properties_do_not_request_a_sync(monkeypatch):
    owner = _Owner()
    assert not _edit(monkeypatch, _EditedObj(), "Label", owner)
    assert owner.requests == []


def test_no_sync_while_syncing_executing_restoring_or_for_read_only(monkeypatch):
    assert not _edit(monkeypatch, _EditedObj(), "Thickness", _Owner(syncing=True))
    assert not _edit(monkeypatch, _EditedObj(executing=True), "Thickness", _Owner())
    assert not _edit(monkeypatch, _EditedObj(modes={"Thickness": ["ReadOnly"]}), "Thickness", _Owner())
    restoring = _EditedObj()
    restoring.Document = type("D", (), {"Restoring": True})()
    assert not _edit(monkeypatch, restoring, "Thickness", _Owner())
    assert not _edit(monkeypatch, _EditedObj(), "Thickness", None)
