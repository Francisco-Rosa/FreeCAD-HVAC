"""
Tests for core/_component_appearance.py: rendering every construction
layer's own Layer_<id>_Shape from its own native Layer_<id>_Material, and
every construction feature's own Feature_<id>_Shape from its host layer's
appearance (hidden layers and features are left out of the displayed
Shape), via FreeCAD's per-face
ViewObject.ShapeAppearance -- see ARCHITECTURE.md's "Component geometry &
materials" section for why the per-layer/per-feature face-count split
(len(Layer_<id>_Shape.Faces)/len(Feature_<id>_Shape.Faces)) is an exact
count derived from the same shapes Shape was built from, not a
hardcoded/guessed index.
"""

import conftest  # noqa: F401 -- installs FreeCAD/FreeCADGui/Part/Materials/PySide stubs
from freecad.HVAC.core import _component_appearance as appearance_mod
from freecad.HVAC.library.construction import ConstructionFeatureDef


class FakeShape:
    def __init__(self, n_faces, null=False):
        self.Faces = list(range(n_faces))
        self._null = null

    def isNull(self):
        return self._null


class FakeMaterial:
    def __init__(self, name=""):
        self.Name = name


class FakeObj:
    """layers: ordered list of (layer_id, shape, material) triples."""

    def __init__(self, layers, library_id="", type_id=""):
        self.LibraryId = library_id
        self.TypeId = type_id
        self.ConstructionLayerIds = [layer_id for layer_id, _, _ in layers]
        self.ConstructionFeatureIds = []
        for layer_id, shape, material in layers:
            setattr(self, "Layer_{}_Shape".format(layer_id), shape)
            setattr(self, "Layer_{}_Material".format(layer_id), material)

    def add_feature(self, feature_id, shape):
        self.ConstructionFeatureIds.append(feature_id)
        setattr(self, "Feature_{}_Shape".format(feature_id), shape)


class FakeViewObject:
    def __init__(self, obj, has_shape_appearance=True):
        self.Object = obj
        if has_shape_appearance:
            self.ShapeAppearance = None


def _patch_view_appearance(monkeypatch, mapping):
    """mapping: {material_object: appearance_or_None}, matched by identity."""
    def fake_get_view_appearance(material):
        for key, value in mapping:
            if material is key:
                return value
        return None
    monkeypatch.setattr(appearance_mod.hvac_materials, "get_view_appearance", fake_get_view_appearance)


class _FakeTypeDef:
    def __init__(self, features):
        self.features = features


class _FakeRegistry:
    def __init__(self, type_def):
        self._type_def = type_def

    def resolve_type(self, lib_id, type_id):
        return self._type_def


def _patch_features(monkeypatch, features):
    registry = _FakeRegistry(_FakeTypeDef(features))
    monkeypatch.setattr(
        appearance_mod.hvaclib.HVACLibraryService,
        "get_hvac_library_registry",
        staticmethod(lambda: registry),
    )


def test_apply_component_appearance_builds_per_face_list_in_declared_layer_order(monkeypatch):
    casing_material = FakeMaterial("Galvanized Steel")
    insulation_material = FakeMaterial("Glass Wool")
    casing_appearance = object()
    insulation_appearance = object()
    _patch_view_appearance(monkeypatch, [
        (casing_material, casing_appearance),
        (insulation_material, insulation_appearance),
    ])

    obj = FakeObj([
        ("casing", FakeShape(3), casing_material),
        ("insulation", FakeShape(2), insulation_material),
    ])
    vobj = FakeViewObject(obj)

    appearance_mod.apply_component_appearance(vobj)

    assert vobj.ShapeAppearance == [casing_appearance] * 3 + [insulation_appearance] * 2


def test_apply_component_appearance_supports_arbitrary_layer_counts(monkeypatch):
    liner_material = FakeMaterial("Perforated Steel")
    absorber_material = FakeMaterial("Mineral Wool")
    jacket_material = FakeMaterial("Aluminium")
    liner_appearance, absorber_appearance, jacket_appearance = object(), object(), object()
    _patch_view_appearance(monkeypatch, [
        (liner_material, liner_appearance),
        (absorber_material, absorber_appearance),
        (jacket_material, jacket_appearance),
    ])

    obj = FakeObj([
        ("liner", FakeShape(2), liner_material),
        ("absorber", FakeShape(1), absorber_material),
        ("jacket", FakeShape(4), jacket_material),
    ])
    vobj = FakeViewObject(obj)

    appearance_mod.apply_component_appearance(vobj)

    assert vobj.ShapeAppearance == (
        [liner_appearance] * 2 + [absorber_appearance] * 1 + [jacket_appearance] * 4
    )


def test_apply_component_appearance_fills_missing_layer_with_default(monkeypatch):
    casing_material = FakeMaterial("Galvanized Steel")
    casing_appearance = object()
    _patch_view_appearance(monkeypatch, [(casing_material, casing_appearance)])

    default_appearance = object()
    monkeypatch.setattr(appearance_mod.FreeCAD, "Material", lambda: default_appearance)

    obj = FakeObj([
        ("casing", FakeShape(2), casing_material),
        ("insulation", FakeShape(1), None),  # no insulation material assigned
    ])
    vobj = FakeViewObject(obj)

    appearance_mod.apply_component_appearance(vobj)

    # List length must still equal the compound's total face count (3), so
    # the insulation face keeps its position, just at the default appearance.
    assert vobj.ShapeAppearance == [casing_appearance, casing_appearance, default_appearance]


def test_apply_component_appearance_does_nothing_without_any_faces():
    obj = FakeObj([("casing", None, None), ("insulation", None, None)])
    vobj = FakeViewObject(obj)

    appearance_mod.apply_component_appearance(vobj)

    assert not hasattr(vobj, "ShapeAppearance") or vobj.ShapeAppearance is None


def test_apply_component_appearance_does_nothing_when_no_layer_resolves(monkeypatch):
    monkeypatch.setattr(appearance_mod.hvac_materials, "get_view_appearance", lambda material: None)

    obj = FakeObj([("casing", FakeShape(4), FakeMaterial("Something"))])
    vobj = FakeViewObject(obj)

    appearance_mod.apply_component_appearance(vobj)

    assert vobj.ShapeAppearance is None


def test_apply_component_appearance_noop_without_shape_appearance_property():
    # Defensive: an older FreeCAD without the native per-face property must
    # not raise -- just leave the object's appearance untouched.
    obj = FakeObj([("casing", FakeShape(2), FakeMaterial("Steel"))])
    vobj = FakeViewObject(obj, has_shape_appearance=False)

    appearance_mod.apply_component_appearance(vobj)  # must not raise

    assert not hasattr(vobj, "ShapeAppearance")


def test_apply_component_appearance_treats_null_shape_as_zero_faces(monkeypatch):
    casing_material = FakeMaterial("Steel")
    casing_appearance = object()
    _patch_view_appearance(monkeypatch, [(casing_material, casing_appearance)])

    obj = FakeObj([
        ("casing", FakeShape(3), casing_material),
        ("insulation", FakeShape(5, null=True), None),
    ])
    vobj = FakeViewObject(obj)

    appearance_mod.apply_component_appearance(vobj)

    assert vobj.ShapeAppearance == [casing_appearance] * 3


def test_apply_component_appearance_guards_against_freecad_reentrancy(monkeypatch):
    """
    Regression: on real FreeCAD, querying a Materials::PropertyMaterial
    value's own appearance (e.g. hasAppearanceProperty()) can synchronously
    re-fire ViewProvider.updateData() for that same property *before* the
    original call returns -- which called apply_component_appearance()
    again, recursing until the interpreter's stack limit crashed it
    (confirmed against a real FreeCAD 1.1 install: assigning a material
    triggered thousands of nested calls before RecursionError). This must
    be a genuine no-op guard -- not just idempotent output -- so the test
    counts both get_view_appearance() calls and ShapeAppearance writes,
    which only distinguish a guarded single render from an unguarded nested
    one (both would otherwise produce the same final list).
    """
    casing_material = FakeMaterial("Steel")
    casing_appearance = object()
    calls = {"get_view_appearance": 0, "shape_appearance_writes": 0}

    def fake_get_view_appearance(material):
        calls["get_view_appearance"] += 1
        if calls["get_view_appearance"] == 1:
            # Simulate FreeCAD's reentrant updateData() firing mid-call, for
            # the very same object, before this call even returns.
            appearance_mod.apply_component_appearance(vobj)
        return casing_appearance if material is casing_material else None

    monkeypatch.setattr(appearance_mod.hvac_materials, "get_view_appearance", fake_get_view_appearance)

    class CountingViewObject(FakeViewObject):
        def __setattr__(self, name, value):
            if name == "ShapeAppearance":
                calls["shape_appearance_writes"] += 1
            super().__setattr__(name, value)

    obj = FakeObj([("casing", FakeShape(2), casing_material)])
    vobj = CountingViewObject(obj)
    calls["shape_appearance_writes"] = 0  # discount FakeViewObject.__init__'s own initial assignment

    appearance_mod.apply_component_appearance(vobj)  # must not raise/recurse

    # Guarded: the reentrant inner call bails out before calling
    # get_view_appearance() at all (1 call total, from the outer call only)
    # and renders exactly once. Unguarded, the inner call would run to
    # completion first (1 more get_view_appearance() call, 1 more write)
    # before the outer call resumed and repeated it.
    assert calls["get_view_appearance"] == 1
    assert calls["shape_appearance_writes"] == 1
    assert vobj.ShapeAppearance == [casing_appearance] * 2


def test_is_trigger_property_reflects_the_objects_own_construction_layers():
    obj = FakeObj([("casing", None, None), ("liner", None, None)])

    assert appearance_mod.is_trigger_property(obj, "Layer_casing_Shape")
    assert appearance_mod.is_trigger_property(obj, "Layer_liner_Material")
    assert not appearance_mod.is_trigger_property(obj, "Layer_absorber_Shape")
    assert not appearance_mod.is_trigger_property(obj, "SomeUnrelatedProperty")


# ----------------------------------------------------------------------
# Construction features
# ----------------------------------------------------------------------

def test_visible_feature_inherits_its_host_layers_appearance(monkeypatch):
    casing_material = FakeMaterial("Galvanized Steel")
    casing_appearance = object()
    _patch_view_appearance(monkeypatch, [(casing_material, casing_appearance)])
    _patch_features(monkeypatch, [
        ConstructionFeatureDef(id="transverse_flange", host_layer="casing", generator="generate_transverse_flange"),
    ])

    obj = FakeObj([("casing", FakeShape(3), casing_material)], library_id="smacna", type_id="circular_straight")
    obj.add_feature("transverse_flange", FakeShape(2))
    vobj = FakeViewObject(obj)

    appearance_mod.apply_component_appearance(vobj)

    assert vobj.ShapeAppearance == [casing_appearance] * 3 + [casing_appearance] * 2


def test_non_visible_feature_is_left_out_of_the_displayed_shape(monkeypatch):
    casing_material = FakeMaterial("Galvanized Steel")
    casing_appearance = object()
    _patch_view_appearance(monkeypatch, [(casing_material, casing_appearance)])
    _patch_features(monkeypatch, [
        ConstructionFeatureDef(
            id="transverse_flange", host_layer="casing", generator="generate_transverse_flange",
            visible_parameter="FlangeVisible",
        ),
    ])

    obj = FakeObj([("casing", FakeShape(3), casing_material)], library_id="smacna", type_id="circular_straight")
    obj.add_feature("transverse_flange", FakeShape(2))
    obj.FlangeVisible = False
    vobj = FakeViewObject(obj)

    appearance_mod.apply_component_appearance(vobj)

    # The hidden flange is not drawn transparent (FreeCAD would then draw the whole
    # selected object transparent): it is left out, so only the casing's faces get an entry.
    assert vobj.ShapeAppearance == [casing_appearance] * 3
    assert [part_id for _kind, part_id, _shape in appearance_mod.displayed_parts(obj)] == ["casing"]


def test_feature_defaults_to_visible_when_no_visible_parameter_declared(monkeypatch):
    casing_material = FakeMaterial("Galvanized Steel")
    casing_appearance = object()
    _patch_view_appearance(monkeypatch, [(casing_material, casing_appearance)])
    _patch_features(monkeypatch, [
        ConstructionFeatureDef(id="transverse_flange", host_layer="casing", generator="generate_transverse_flange"),
    ])

    obj = FakeObj([("casing", FakeShape(1), casing_material)], library_id="smacna", type_id="circular_straight")
    obj.add_feature("transverse_flange", FakeShape(1))
    vobj = FakeViewObject(obj)

    appearance_mod.apply_component_appearance(vobj)

    assert vobj.ShapeAppearance == [casing_appearance, casing_appearance]


def test_is_trigger_property_includes_feature_shape_and_visible_parameter(monkeypatch):
    _patch_features(monkeypatch, [
        ConstructionFeatureDef(
            id="transverse_flange", host_layer="casing", generator="generate_transverse_flange",
            visible_parameter="FlangeVisible",
        ),
    ])
    obj = FakeObj([("casing", None, None)], library_id="smacna", type_id="circular_straight")
    obj.add_feature("transverse_flange", None)

    assert appearance_mod.is_trigger_property(obj, "Feature_transverse_flange_Shape")
    assert appearance_mod.is_trigger_property(obj, "FlangeVisible")
    assert not appearance_mod.is_trigger_property(obj, "FlangeDepth")
