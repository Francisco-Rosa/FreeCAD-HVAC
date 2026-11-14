"""Equipment model definitions of a library (library/equipment_library.py)."""

import json
from pathlib import Path

import pytest

from freecad.HVAC.library import equipment_library

LIBRARIES = Path(__file__).resolve().parents[1] / "freecad" / "HVAC" / "libraries"

GOOD = {
    "id": "box",
    "label": "Box",
    "geometry": {"backend": "generator", "module": "shared:equipment", "function": "build_fan"},
    "properties": [
        {"name": "CasingLength", "label": "Casing length", "type": "length", "default": 800.0, "min": 1.0},
        {"name": "Service", "type": "choice", "options": ["Supply", "Exhaust"], "default": "Exhaust"},
        {"name": "ExhaustPort", "type": "bool", "default": False},
    ],
}


def test_parse_model_reads_properties():
    model = equipment_library.parse_model(GOOD, "lib")
    assert (model.library_id, model.id, model.module, model.function) == ("lib", "box", "shared:equipment", "build_fan")
    assert [prop.name for prop in model.properties] == ["CasingLength", "Service", "ExhaustPort"]
    assert model.properties[1].label == "Service"  # the name stands in for a missing label


@pytest.mark.parametrize(
    "change",
    [
        {"colour": "red"},
        {"id": ""},
        {"geometry": {"backend": "static"}},
        {"properties": [{"name": "A", "type": "length", "default": 1.0, "unit": "mm"}]},
        {"properties": [{"name": "A", "type": "text", "default": "x"}]},
        {"properties": [{"name": "A", "type": "length"}]},
        {"properties": [{"name": "A", "type": "choice", "options": ["a"], "default": "b"}]},
        {
            "properties": [
                {"name": "A", "type": "bool", "default": True},
                {"name": "A", "type": "bool", "default": True},
            ]
        },
    ],
)
def test_parse_model_refuses_bad_definitions(change):
    with pytest.raises(ValueError):
        equipment_library.parse_model({**GOOD, **change}, "lib")


def test_resolve_values_defaults_overrides_and_checks():
    model = equipment_library.parse_model(GOOD, "lib")
    assert equipment_library.resolve_values(model) == {
        "CasingLength": 800.0,
        "Service": "Exhaust",
        "ExhaustPort": False,
    }
    values = equipment_library.resolve_values(model, {"CasingLength": "1200", "Service": "Supply", "ExhaustPort": 1})
    assert values == {"CasingLength": 1200.0, "Service": "Supply", "ExhaustPort": True}
    for bad in ({"CasingLength": 0.0}, {"Service": "Other"}, {"Nope": 1}):
        with pytest.raises(ValueError):
            equipment_library.resolve_values(model, bad)


def test_load_models_skips_and_reports_a_bad_file(tmp_path):
    folder = tmp_path / "equipment"
    folder.mkdir()
    (folder / "good.json").write_text(json.dumps(GOOD))
    (folder / "bad.json").write_text(json.dumps({**GOOD, "id": "other", "extra": 1}))
    (folder / "twice.json").write_text(json.dumps(GOOD))
    models, errors = equipment_library.load_models("lib", tmp_path)
    assert [model.id for model in models] == ["box"]
    assert len(errors) == 2


def test_shipped_equipment_models_load_and_name_shared_generators():
    found = []
    for manifest in LIBRARIES.glob("*/library.json"):
        library_id = json.loads(manifest.read_text())["id"]
        models, errors = equipment_library.load_models(library_id, manifest.parent)
        assert not errors
        found.extend(models)
    assert {"ahu_generic", "fan_generic"} <= {model.id for model in found}
    source = (LIBRARIES.parent / "library" / "fittings" / "equipment.py").read_text()
    for model in found:
        assert model.module == "shared:equipment"
        assert "def {}(api, values)".format(model.function) in source
        equipment_library.resolve_values(model)  # every default passes its own checks
