"""
Tests for core/_geometry_apply.py's apply_geometry_result(): the one piece
of DuctSegment.execute()/DuctComponent.execute() that writes a GeometryResult
onto each of obj.ConstructionLayerIds' own Layer_<id>_Shape property (and
each of obj.ConstructionFeatureIds' own Feature_<id>_Shape property) and
derives Shape as their compound -- shared so the two execute() methods
don't duplicate it.
"""

import conftest  # noqa: F401 -- installs FreeCAD/FreeCADGui/Part/PySide stubs

from freecad.HVAC.core import _geometry_apply
from freecad.HVAC.library import geometry_result as gr
from freecad.HVAC.library.construction import LayerGeometry, FeatureGeometry


class _Shape:
    def __init__(self, null=False):
        self._null = null

    def isNull(self):
        return self._null


class _FakeObj:
    def __init__(self, layer_ids, feature_ids=()):
        self.ConstructionLayerIds = list(layer_ids)
        self.ConstructionFeatureIds = list(feature_ids)
        self.Shape = None
        for layer_id in layer_ids:
            setattr(self, "Layer_{}_Shape".format(layer_id), None)
        for feature_id in feature_ids:
            setattr(self, "Feature_{}_Shape".format(feature_id), None)


def test_apply_geometry_result_sets_each_declared_layers_shape():
    casing_shape = _Shape()
    insulation_shape = _Shape()
    result = gr.GeometryResult(layers={
        "casing": LayerGeometry(shape=casing_shape),
        "insulation": LayerGeometry(shape=insulation_shape),
    })

    obj = _FakeObj(["casing", "insulation"])
    _geometry_apply.apply_geometry_result(obj, result)

    assert obj.Layer_casing_Shape is casing_shape
    assert obj.Layer_insulation_Shape is insulation_shape


def test_apply_geometry_result_supports_arbitrary_layer_counts():
    liner_shape = _Shape()
    absorber_shape = _Shape()
    jacket_shape = _Shape()
    result = gr.GeometryResult(layers={
        "liner": LayerGeometry(shape=liner_shape),
        "absorber": LayerGeometry(shape=absorber_shape),
        "jacket": LayerGeometry(shape=jacket_shape),
    })

    obj = _FakeObj(["liner", "absorber", "jacket"])
    _geometry_apply.apply_geometry_result(obj, result)

    assert obj.Layer_liner_Shape is liner_shape
    assert obj.Layer_absorber_Shape is absorber_shape
    assert obj.Layer_jacket_Shape is jacket_shape


def test_apply_geometry_result_builds_shape_as_compound_of_non_null_shapes_in_declared_order(monkeypatch):
    casing_shape = _Shape()
    result = gr.GeometryResult(layers={
        "casing": LayerGeometry(shape=casing_shape),
        "insulation": LayerGeometry(shape=None),
    })

    captured = {}

    def fake_make_compound(shapes):
        captured["shapes"] = list(shapes)
        return "COMPOUND"

    monkeypatch.setattr(_geometry_apply.Part, "makeCompound", fake_make_compound)

    obj = _FakeObj(["casing", "insulation"])
    _geometry_apply.apply_geometry_result(obj, result)

    # Only the non-null casing shape goes into the compound -- insulation is
    # absent (None), not a stand-in empty shape.
    assert captured["shapes"] == [casing_shape]
    assert obj.Shape == "COMPOUND"


def test_apply_geometry_result_treats_null_shape_as_absent(monkeypatch):
    null_shape = _Shape(null=True)
    result = gr.GeometryResult(layers={
        "casing": LayerGeometry(shape=null_shape),
        "insulation": LayerGeometry(shape=None),
    })

    captured = {}
    monkeypatch.setattr(
        _geometry_apply.Part, "makeCompound", lambda shapes: captured.setdefault("shapes", list(shapes))
    )

    obj = _FakeObj(["casing", "insulation"])
    _geometry_apply.apply_geometry_result(obj, result)

    assert captured["shapes"] == []


def test_apply_geometry_result_defaults_missing_shapes_to_empty_part_shape(monkeypatch):
    result = gr.GeometryResult(layers={
        "casing": LayerGeometry(shape=None),
        "insulation": LayerGeometry(shape=None),
    })

    monkeypatch.setattr(_geometry_apply.Part, "Shape", lambda: "EMPTY_SHAPE")
    monkeypatch.setattr(_geometry_apply.Part, "makeCompound", lambda shapes: list(shapes))

    obj = _FakeObj(["casing", "insulation"])
    _geometry_apply.apply_geometry_result(obj, result)

    assert obj.Layer_casing_Shape == "EMPTY_SHAPE"
    assert obj.Layer_insulation_Shape == "EMPTY_SHAPE"
    assert obj.Shape == []


def test_apply_geometry_result_skips_layer_ids_missing_from_the_result(monkeypatch):
    # A layer id declared on obj but not present in result.layers at all
    # (e.g. a generator that failed to return one of its declared layers)
    # is treated the same as a null shape, not an error.
    result = gr.GeometryResult(layers={"casing": LayerGeometry(shape=_Shape())})

    monkeypatch.setattr(_geometry_apply.Part, "Shape", lambda: "EMPTY_SHAPE")
    monkeypatch.setattr(_geometry_apply.Part, "makeCompound", lambda shapes: list(shapes))

    obj = _FakeObj(["casing", "insulation"])
    _geometry_apply.apply_geometry_result(obj, result)

    assert obj.Layer_insulation_Shape == "EMPTY_SHAPE"


# ----------------------------------------------------------------------
# Construction features -- folded into the same compound, after layers
# ----------------------------------------------------------------------

def test_apply_geometry_result_sets_each_declared_features_shape():
    casing_shape = _Shape()
    flange_shape = _Shape()
    result = gr.GeometryResult(
        layers={"casing": LayerGeometry(shape=casing_shape)},
        features={"transverse_flange": FeatureGeometry(shape=flange_shape)},
    )

    obj = _FakeObj(["casing"], feature_ids=["transverse_flange"])
    _geometry_apply.apply_geometry_result(obj, result)

    assert obj.Feature_transverse_flange_Shape is flange_shape


def test_apply_geometry_result_compounds_features_after_layers_in_declared_order(monkeypatch):
    casing_shape = _Shape()
    flange_shape = _Shape()
    stiffener_shape = _Shape()
    result = gr.GeometryResult(
        layers={"casing": LayerGeometry(shape=casing_shape)},
        features={
            "transverse_flange": FeatureGeometry(shape=flange_shape),
            "stiffener": FeatureGeometry(shape=stiffener_shape),
        },
    )

    captured = {}
    monkeypatch.setattr(
        _geometry_apply.Part, "makeCompound", lambda shapes: captured.setdefault("shapes", list(shapes))
    )

    obj = _FakeObj(["casing"], feature_ids=["transverse_flange", "stiffener"])
    _geometry_apply.apply_geometry_result(obj, result)

    assert captured["shapes"] == [casing_shape, flange_shape, stiffener_shape]


def test_apply_geometry_result_gives_a_disabled_feature_an_empty_shape_and_excludes_it_from_the_compound(monkeypatch):
    # A disabled feature has no entry in result.features at all (see
    # library/Library.py's build_geometry()) -- must be treated exactly
    # like a missing/absent layer, not an error.
    casing_shape = _Shape()
    result = gr.GeometryResult(
        layers={"casing": LayerGeometry(shape=casing_shape)},
        features={},
    )

    monkeypatch.setattr(_geometry_apply.Part, "Shape", lambda: "EMPTY_SHAPE")
    captured = {}
    monkeypatch.setattr(
        _geometry_apply.Part, "makeCompound", lambda shapes: captured.setdefault("shapes", list(shapes))
    )

    obj = _FakeObj(["casing"], feature_ids=["transverse_flange"])
    _geometry_apply.apply_geometry_result(obj, result)

    assert obj.Feature_transverse_flange_Shape == "EMPTY_SHAPE"
    assert captured["shapes"] == [casing_shape]
