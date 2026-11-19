"""Stage 3: the per-port table of the Edit Type panel (core/_port_properties.py)."""

from types import SimpleNamespace

import pytest

import conftest  # noqa: F401 -- installs FreeCAD stubs
from freecad.HVAC.core import _port_properties as pp


class Obj:
    def __init__(self, **props):
        self.__dict__.update(props)
        self.PropertiesList = list(props)


def _type_def():
    return SimpleNamespace(
        properties=[
            SimpleNamespace(
                name="TrimLength", prop_type="App::PropertyLength", per_port=True, default=50.0, description="Trim"
            ),
            SimpleNamespace(
                name="Capped", prop_type="App::PropertyBool", per_port=True, default=False, description="Cap"
            ),
            SimpleNamespace(name="Thickness", prop_type="App::PropertyLength", per_port=False, default=1.0),
        ]
    )


def _obj():
    return Obj(
        TrimLength=[10.0, 20.0, 30.0],
        TrimLengthEdgeKeys=["a", "b", "c"],
        Capped=[True],
        CappedEdgeKeys=["b"],
        Thickness=1.0,
    )


def test_table_rows_follow_the_stored_ports_and_fill_defaults():
    columns, rows = pp.port_table(_obj(), _type_def(), {"a": "D01", "c": "D03"})
    assert [c["name"] for c in columns] == ["TrimLength", "Capped"]
    assert [(r["edge_key"], r["label"]) for r in rows] == [("a", "D01"), ("b", "b"), ("c", "D03")]
    assert rows[1]["values"] == {"TrimLength": 20.0, "Capped": True}
    assert rows[0]["values"]["Capped"] is False  # no stored value: the default


def test_no_per_port_properties_gives_an_empty_table():
    td = SimpleNamespace(
        properties=[SimpleNamespace(name="Thickness", prop_type="App::PropertyLength", per_port=False)]
    )
    assert pp.port_table(Obj(Thickness=1.0), td) == ([], [])


@pytest.mark.parametrize(
    "prop_type, text, value",
    [
        ("App::PropertyLength", "12.5 mm", 12.5),
        ("App::PropertyFloat", "3", 3.0),
        ("App::PropertyInteger", " 4 ", 4),
        ("App::PropertyBool", "yes", True),
        ("App::PropertyBool", "0", False),
        ("App::PropertyBool", True, True),
    ],
)
def test_parse_cell_values(prop_type, text, value):
    assert pp.parse_port_value(prop_type, text) == value


@pytest.mark.parametrize(
    "prop_type, text", [("App::PropertyLength", "abc"), ("App::PropertyBool", "maybe"), ("App::PropertyInteger", "1.5")]
)
def test_parse_rejects_bad_text(prop_type, text):
    with pytest.raises(ValueError):
        pp.parse_port_value(prop_type, text)


def test_apply_writes_by_edge_key_only():
    obj = _obj()
    assert pp.apply_port_table(
        obj, _type_def(), {"c": {"TrimLength": 99.0}, "b": {"Capped": False}, "zz": {"TrimLength": 1.0}}
    )
    assert obj.TrimLength == [10.0, 20.0, 99.0]
    assert obj.Capped == [False]
    assert not pp.apply_port_table(obj, _type_def(), {"c": {"TrimLength": 99.0}})
