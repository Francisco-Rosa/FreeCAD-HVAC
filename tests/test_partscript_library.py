import json
from types import SimpleNamespace

import conftest  # noqa: F401 -- installs FreeCAD/FreeCADGui/Part/PySide stubs

from freecad.HVAC.library import partscript_shapes, validation
from freecad.HVAC.library.Library import HVACLibraryRegistry


class _Shape:
    def isNull(self):
        return False


def test_resolve_params_normalizes_and_validates():
    type_def = SimpleNamespace(
        id="round",
        properties=[
            SimpleNamespace(
                name="Diameter",
                prop_type="App::PropertyLength",
                default=100.0,
                required=True,
                validation={"exclusiveMinimum": 0.0},
            )
        ],
    )
    obj = SimpleNamespace(Diameter=250.0)
    assert validation.resolve_params(type_def, obj=obj) == {"Diameter": 250.0}


def test_resolve_params_rejects_invalid_value():
    type_def = SimpleNamespace(
        id="round",
        properties=[
            SimpleNamespace(
                name="Diameter",
                prop_type="App::PropertyLength",
                default=100.0,
                required=True,
                validation={"exclusiveMinimum": 0.0},
            )
        ],
    )
    obj = SimpleNamespace(Diameter=0.0)
    try:
        validation.resolve_params(type_def, obj=obj)
    except ValueError as exc:
        assert "Diameter" in str(exc)
    else:
        raise AssertionError("Expected validation failure")


def test_partscript_optional_validate_and_generate(tmp_path):
    script = tmp_path / "model.py"
    script.write_text(
        "HVAC_PARTSCRIPT_API = 3\n"
        "def validate(context):\n"
        "    if context['properties']['D'] <= 0: raise ValueError('D')\n"
        "def generate(context):\n"
        "    return {'layers': {'shape': {'shape': context['test_shape']}}, 'tag': 'ok'}\n"
    )
    result = partscript_shapes.execute_partscript(
        str(script), {"properties": {"D": 1.0}, "test_shape": _Shape()}
    )
    assert result["tag"] == "ok"


def test_partscript_accepts_layers_contract_with_one_real_shape_among_several(tmp_path):
    script = tmp_path / "model.py"
    script.write_text(
        "HVAC_PARTSCRIPT_API = 3\n"
        "def generate(context):\n"
        "    return {'layers': {\n"
        "        'casing': {'shape': context['test_shape']},\n"
        "        'insulation': {'shape': None},\n"
        "    }}\n"
    )
    result = partscript_shapes.execute_partscript(str(script), {"properties": {}, "test_shape": _Shape()})
    assert result["layers"]["casing"]["shape"] is not None


def test_partscript_rejects_layers_contract_with_no_real_shape_anywhere(tmp_path):
    script = tmp_path / "model.py"
    script.write_text(
        "HVAC_PARTSCRIPT_API = 3\n"
        "def generate(context):\n"
        "    return {'layers': {'casing': {'shape': None}}}\n"
    )
    try:
        partscript_shapes.execute_partscript(str(script), {"properties": {}})
    except partscript_shapes.PartScriptSchemaError as exc:
        assert "layers" in str(exc)
    else:
        raise AssertionError("Expected PartScriptSchemaError")


def test_validate_context_generic_profile_accepts_any_connected_profile():
    # Profile-agnostic placeholder types (e.g. topology marker fittings)
    # declare profiles=["Generic"] and must still accept junctions whose
    # connected ports carry a real duct profile (Circular/Rectangular/...).
    type_def = SimpleNamespace(
        id="through_marker",
        category="junction",
        topology="through",
        profiles=["Generic"],
        constraints={},
    )
    context = {
        "connected_ports": [
            {"profile": "Circular"},
            {"profile": "Rectangular"},
        ],
        "topology": "through",
    }
    validation.validate_context(type_def, context)  # must not raise


def test_validate_context_rejects_unsupported_profile_for_non_generic_type():
    type_def = SimpleNamespace(
        id="branch_wye",
        category="junction",
        topology="branch",
        profiles=["Circular"],
        constraints={},
    )
    context = {"connected_ports": [{"profile": "Rectangular"}], "topology": "branch"}
    try:
        validation.validate_context(type_def, context)
    except ValueError as exc:
        assert "Rectangular" in str(exc)
    else:
        raise AssertionError("Expected validation failure")


def test_validate_context_enforces_degree_min_constraint():
    type_def = SimpleNamespace(
        id="multiport_generic",
        category="junction",
        topology="multiport",
        profiles=[],
        constraints={"degree_min": 5},
    )
    context = {"connected_ports": [{}] * 4, "topology": "multiport"}
    try:
        validation.validate_context(type_def, context)
    except ValueError as exc:
        assert "degree" in str(exc).lower()
    else:
        raise AssertionError("Expected degree_min validation failure")


def test_type_loader_parses_geometry_and_validation(tmp_path):
    type_file = tmp_path / "round.json"
    type_file.write_text(json.dumps({
        "id": "round",
        "label": "Round",
        "category": "segment",
        "family": ["straight_segment"],
        "profiles": ["Circular"],
        "properties": [{
            "name": "Diameter",
            "prop_type": "App::PropertyLength",
            "default": 100.0,
            "validation": {"exclusiveMinimum": 0.0}
        }],
        "geometry": {"backend": "partscript", "file": "models/round.py"}
    }))

    type_def = HVACLibraryRegistry()._load_type_def_file(str(type_file))
    assert type_def.geometry.backend == "partscript"
    assert type_def.geometry.file == "models/round.py"
    assert type_def.properties[0].validation == {"exclusiveMinimum": 0.0}
