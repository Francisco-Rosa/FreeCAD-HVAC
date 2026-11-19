"""
Tests for the GeometryResult/LayerGeometry contract every geometry backend
dispatch (PartScript, static, legacy generator) is normalized into by
HVACLibraryRegistry.build_geometry() -- see library/geometry_result.py.
"""

import conftest  # noqa: F401 -- installs FreeCAD/FreeCADGui/Part/PySide stubs

from freecad.HVAC.library import geometry_result as gr
from freecad.HVAC.library.construction import LayerGeometry


class _Shape:
    """Stand-in for a Part.Shape -- identity is all these tests care about."""


def test_normalize_rejects_the_removed_shape_form():
    # Stage 11: one result form. A bare {"shape": ...} dict is refused with a pointer to single_layer.
    import pytest

    with pytest.raises(TypeError, match="single_layer"):
        gr.normalize({"shape": _Shape(), "connection_lengths": [{"edge_key": "A"}]})


def test_normalize_accepts_layers_dict_with_plain_dict_values():
    casing_shape = _Shape()
    insulation_shape = _Shape()
    result = gr.normalize({
        "layers": {
            "casing": {"shape": casing_shape},
            "insulation": {"shape": insulation_shape},
        },
    })

    assert result.layers["casing"].shape is casing_shape
    assert result.layers["insulation"].shape is insulation_shape


def test_normalize_accepts_layers_dict_with_layer_geometry_values():
    casing_shape = _Shape()
    result = gr.normalize({
        "layers": {
            "casing": LayerGeometry(shape=casing_shape, roles=["structural_shell"]),
        },
    })

    assert result.layers["casing"].shape is casing_shape
    assert result.layers["casing"].roles == ["structural_shell"]


def test_normalize_does_not_invent_layers_beyond_what_the_backend_returned():
    # Only whatever roles/ids a backend actually mentions -- no forced
    # casing/insulation keys any more; arbitrary layer counts are allowed.
    result = gr.normalize({"layers": {"liner": {"shape": _Shape()}}})
    assert set(result.layers.keys()) == {"liner"}


def test_normalize_supports_arbitrary_layer_counts():
    result = gr.normalize({
        "layers": {
            "liner": {"shape": _Shape()},
            "absorber": {"shape": _Shape()},
            "jacket": {"shape": _Shape()},
        },
    })
    assert set(result.layers.keys()) == {"liner", "absorber", "jacket"}


def test_normalize_passthrough_of_a_geometry_result_returns_the_same_object():
    partial = gr.GeometryResult(layers={"casing": LayerGeometry(shape=_Shape())})
    result = gr.normalize(partial)
    assert result is partial


def test_normalize_preserves_trim_planes_and_computed_properties():
    result = gr.normalize({
        "layers": {"shape": {"shape": _Shape()}},
        "start_trim_plane_json": '{"position": [0, 0, 0]}',
        "end_trim_plane_json": None,
        "computed_properties": {"angle": 42.0},
    })
    assert result.start_trim_plane_json == '{"position": [0, 0, 0]}'
    assert result.end_trim_plane_json is None
    assert result.computed_properties == {"angle": 42.0}


def test_normalize_preserves_unknown_keys_in_extra():
    result = gr.normalize({"layers": {"shape": {"shape": _Shape()}}, "some_future_output": "value"})
    assert result.extra == {"some_future_output": "value"}


def test_normalize_never_populates_features_from_a_raw_backend_dict():
    # Unlike layers, features are never something a backend/generator
    # returns directly -- a "features" key in a raw dict is not a supported
    # part of the contract, it would just land in .extra like any other
    # unrecognized key. GeometryResult.features is only ever populated by
    # HVACLibraryRegistry.build_geometry()'s own second pass (see Library.py).
    result = gr.normalize({"layers": {"shape": {"shape": _Shape()}}})
    assert result.features == {}


def test_normalize_rejects_unsupported_raw_type():
    try:
        gr.normalize(42)
    except TypeError:
        pass
    else:
        raise AssertionError("Expected TypeError for a non-dict/GeometryResult raw value")


def test_normalize_keeps_property_choices_as_lists_of_strings():
    result = gr.normalize({"layers": {"shape": {"shape": _Shape()}}, "property_choices": {"Mode": ("A", "B")}})
    assert result.property_choices == {"Mode": ["A", "B"]}
    assert "property_choices" not in result.extra
    assert gr.normalize({"layers": {"shape": {"shape": _Shape()}}}).property_choices == {}
