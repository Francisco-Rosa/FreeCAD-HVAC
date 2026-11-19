# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the HVAC addon.

"""
Per-port properties (a type-def property marked "per_port": true): loading,
resolution into PortValues, the FreeCAD-side value/key lists and their
upkeep, and the API accessor generators read them through.
"""

import json
from types import SimpleNamespace

import pytest

import conftest  # noqa: F401 -- installs FreeCAD/FreeCADGui/Part/PySide stubs
from freecad.HVAC.core import _port_properties, _type_schema
from freecad.HVAC.library import validation
from freecad.HVAC.library.Library import HVACLibraryRegistry, HVACPropertyDef
from freecad.HVAC.library.library_api import HVACLibraryAPI
from freecad.HVAC.library.validation import PortValues


class FakeObj:
    """Minimal stand-in for a FreeCAD DocumentObject's dynamic-property API."""

    def __init__(self):
        self.PropertiesList = []
        self._types = {}
        self.editor_modes = {}

    def addProperty(self, prop_type, name, group, description, attr=0):
        if name not in self.PropertiesList:
            self.PropertiesList.append(name)
            self._types[name] = prop_type
            setattr(self, name, [] if prop_type.endswith("List") else None)
        return self

    def removeProperty(self, name):
        self.PropertiesList.remove(name)
        del self._types[name]
        delattr(self, name)
        return True

    def getTypeIdOfProperty(self, name):
        return self._types[name]

    def setEditorMode(self, name, mode):
        self.editor_modes[name] = mode


def _trim_def(**extra):
    kwargs = dict(name="TrimLength", prop_type="App::PropertyLength", group="Dimensions", default=100.0, per_port=True)
    kwargs.update(extra)
    return HVACPropertyDef(**kwargs)


def _type_def(*properties):
    return SimpleNamespace(id="multiport_generic", properties=list(properties))


def _obj_with(values, keys):
    obj = FakeObj()
    obj.addProperty("App::PropertyFloatList", "TrimLength", "Dimensions", "")
    obj.addProperty("App::PropertyStringList", "TrimLengthEdgeKeys", "HVAC", "")
    obj.TrimLength, obj.TrimLengthEdgeKeys = list(values), list(keys)
    return obj


# ----------------------------------------------------------------------------
# PortValues
# ----------------------------------------------------------------------------


def test_port_values_fall_back_to_the_default_for_an_unknown_port():
    values = PortValues({"A": 50.0}, default=100.0)
    assert values.for_port({"edge_key": "A"}) == 50.0
    assert values.for_port({"edge_key": "B"}) == 100.0
    assert values.for_port("A") == 50.0
    assert values.in_port_order([{"edge_key": "B"}, {"edge_key": "A"}]) == [100.0, 50.0]


# ----------------------------------------------------------------------------
# Loading
# ----------------------------------------------------------------------------


def _write_type(tmp_path, prop):
    raw = {
        "id": "multiport_generic",
        "label": "x",
        "category": "junction",
        "geometry": {"backend": "generator", "module": "m", "function": "f"},
        "topology": "multiport",
        "family": ["multiport.multiport"],
        "profiles": ["Circular"],
        "properties": [prop],
    }
    path = tmp_path / "type.json"
    path.write_text(json.dumps(raw))
    return str(path)


def test_per_port_flag_is_loaded(tmp_path):
    path = _write_type(
        tmp_path, {"name": "TrimLength", "prop_type": "App::PropertyLength", "default": 100.0, "per_port": True}
    )
    type_def = HVACLibraryRegistry()._load_type_def_file(path)
    assert type_def.properties[0].per_port is True


def test_per_port_is_rejected_for_a_type_that_has_no_list_form(tmp_path):
    path = _write_type(tmp_path, {"name": "Label", "prop_type": "App::PropertyString", "per_port": True})
    with pytest.raises(ValueError) as excinfo:
        HVACLibraryRegistry()._load_type_def_file(path)
    assert "per_port" in str(excinfo.value)


# ----------------------------------------------------------------------------
# resolve_params
# ----------------------------------------------------------------------------


def test_resolve_reads_the_objects_value_and_key_lists():
    obj = _obj_with([110.0, 120.0], ["A", "B"])
    params = validation.resolve_params(_type_def(_trim_def()), obj=obj)
    assert isinstance(params["TrimLength"], PortValues)
    assert dict(params["TrimLength"]) == {"A": 110.0, "B": 120.0}
    assert params["TrimLength"].default == 100.0


def test_resolve_without_an_object_gives_only_the_default():
    params = validation.resolve_params(_type_def(_trim_def()))
    assert dict(params["TrimLength"]) == {}
    assert params["TrimLength"].for_port({"edge_key": "A"}) == 100.0


def test_resolve_accepts_a_supplied_mapping_or_one_value_for_every_port():
    type_def = _type_def(_trim_def())
    by_port = validation.resolve_params(type_def, supplied={"TrimLength": {"A": 80.0}})
    assert by_port["TrimLength"].for_port("A") == 80.0
    assert by_port["TrimLength"].for_port("B") == 100.0
    shared = validation.resolve_params(type_def, supplied={"TrimLength": 60.0})
    assert shared["TrimLength"].for_port("B") == 60.0


def test_resolve_ignores_lists_that_are_out_of_step():
    obj = _obj_with([110.0, 120.0, 130.0], ["A", "B"])
    params = validation.resolve_params(_type_def(_trim_def()), obj=obj)
    assert dict(params["TrimLength"]) == {}


def test_resolve_validates_every_port_value():
    obj = _obj_with([110.0, -5.0], ["A", "B"])
    with pytest.raises(ValueError) as excinfo:
        validation.resolve_params(_type_def(_trim_def(validation={"minimum": 0.0})), obj=obj)
    assert "TrimLength[B]" in str(excinfo.value)


# ----------------------------------------------------------------------------
# Keeping the lists in step with the ports
# ----------------------------------------------------------------------------


def test_sync_fills_a_new_object_with_the_default():
    obj = _obj_with([], [])
    assert _port_properties.sync_port_property_lists(obj, _type_def(_trim_def()), ["A", "B", "C"]) is True
    assert obj.TrimLength == [100.0, 100.0, 100.0]
    assert obj.TrimLengthEdgeKeys == ["A", "B", "C"]


def test_sync_keeps_values_by_key_when_ports_are_added_removed_or_reordered():
    obj = _obj_with([110.0, 120.0, 130.0], ["A", "B", "C"])
    _port_properties.sync_port_property_lists(obj, _type_def(_trim_def()), ["C", "A", "D"])
    assert obj.TrimLengthEdgeKeys == ["C", "A", "D"]
    assert obj.TrimLength == [130.0, 110.0, 100.0]


def test_sync_does_nothing_when_already_in_step():
    obj = _obj_with([110.0, 120.0], ["A", "B"])
    assert _port_properties.sync_port_property_lists(obj, _type_def(_trim_def()), ["A", "B"]) is False
    assert obj.TrimLength == [110.0, 120.0]


def test_sync_works_for_five_or_more_ports():
    obj = _obj_with([], [])
    keys = ["E{}".format(i) for i in range(7)]
    _port_properties.sync_port_property_lists(obj, _type_def(_trim_def()), keys)
    assert len(obj.TrimLength) == 7


def _apply(monkeypatch, obj, *properties):
    registry = SimpleNamespace(resolve_type=lambda lib_id, type_id: _type_def(*properties))
    monkeypatch.setattr(
        _type_schema.hvaclib.HVACLibraryService, "get_hvac_library_registry", staticmethod(lambda: registry)
    )
    obj.TypeSchemaPropertyNames = list(getattr(obj, "TypeSchemaPropertyNames", []))
    return _type_schema.apply_type_schema(obj, "lib", "type")


def test_schema_adds_a_value_list_and_a_hidden_key_list(monkeypatch):
    obj = FakeObj()
    assert _apply(monkeypatch, obj, _trim_def()) is True
    assert obj.getTypeIdOfProperty("TrimLength") == "App::PropertyFloatList"
    assert obj.getTypeIdOfProperty("TrimLengthEdgeKeys") == "App::PropertyStringList"
    assert obj.editor_modes["TrimLengthEdgeKeys"] == 2
    assert set(obj.TypeSchemaPropertyNames) == {"TrimLength", "TrimLengthEdgeKeys"}


def test_schema_uses_a_bool_list_for_a_per_port_switch(monkeypatch):
    obj = FakeObj()
    _apply(
        monkeypatch, obj, HVACPropertyDef(name="ShowFlange", prop_type="App::PropertyBool", default=True, per_port=True)
    )
    assert obj.getTypeIdOfProperty("ShowFlange") == "App::PropertyBoolList"


def test_schema_replaces_a_plain_property_of_the_same_name(monkeypatch):
    obj = FakeObj()
    obj.addProperty("App::PropertyLength", "TrimLength", "Dimensions", "")
    _apply(monkeypatch, obj, _trim_def())
    assert obj.getTypeIdOfProperty("TrimLength") == "App::PropertyFloatList"


def test_schema_removes_both_lists_when_the_type_no_longer_declares_them(monkeypatch):
    obj = FakeObj()
    _apply(monkeypatch, obj, _trim_def())
    _apply(monkeypatch, obj)
    assert "TrimLength" not in obj.PropertiesList
    assert "TrimLengthEdgeKeys" not in obj.PropertiesList


# ----------------------------------------------------------------------------
# API accessor
# ----------------------------------------------------------------------------


def test_port_param_reads_per_port_and_plain_properties_alike():
    port_a, port_b = {"edge_key": "A"}, {"edge_key": "B"}
    context = {"properties": {"TrimLength": PortValues({"A": 80.0}, default=100.0), "Thickness": 1.2}}
    assert HVACLibraryAPI.port_param(context, "TrimLength", port_a) == 80.0
    assert HVACLibraryAPI.port_param(context, "TrimLength", port_b) == 100.0
    assert HVACLibraryAPI.port_param(context, "Thickness", port_b) == 1.2
    assert HVACLibraryAPI.port_param(context, "Missing", port_a, default=7.0) == 7.0
