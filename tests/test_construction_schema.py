"""
Focused tests for the shared apply_construction_schema helper
(core/_construction_schema.py): per-layer Layer_<id>_Shape/Layer_<id>_Material
dynamic property add/remove syncing driven by a type-def's declared
construction layers, and the "not yet migrated" fallback to a single
implicit layer.
"""

import conftest  # noqa: F401 -- installs FreeCAD/FreeCADGui/Part/PySide stubs

from freecad.HVAC.core import _construction_schema
from freecad.HVAC.library.construction import ConstructionLayerDef, ConstructionFeatureDef
from freecad.HVAC.library import geometry_result


class FakeDuctObj:
    """Minimal stand-in for a FreeCAD DocumentObject's dynamic-property API."""

    def __init__(self):
        self.PropertiesList = []
        self._editor_modes = {}
        self._property_statuses = []
        self.ConstructionLayerIds = []
        self.ConstructionFeatureIds = []

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

    def setPropertyStatus(self, name, status):
        self._property_statuses.append((name, status))


class _FakeTypeDef:
    def __init__(self, construction, features=None):
        self.construction = construction
        self.features = features or []


class _FakeRegistry:
    def __init__(self, type_def):
        self._type_def = type_def

    def resolve_type(self, lib_id, type_id):
        return self._type_def


def _patch_registry(monkeypatch, registry):
    monkeypatch.setattr(
        _construction_schema.hvaclib.HVACLibraryService,
        "get_hvac_library_registry",
        staticmethod(lambda: registry),
    )


def test_apply_construction_schema_adds_shape_and_material_per_layer(monkeypatch):
    construction = [
        ConstructionLayerDef(id="casing", roles=["flow_surface", "structural_shell"]),
        ConstructionLayerDef(id="insulation", roles=["thermal_insulation"]),
    ]
    obj = FakeDuctObj()
    _patch_registry(monkeypatch, _FakeRegistry(_FakeTypeDef(construction)))

    changed = _construction_schema.apply_construction_schema(obj, "smacna", "circular_straight")

    assert changed is True
    assert "Layer_casing_Shape" in obj.PropertiesList
    assert "Layer_casing_Material" in obj.PropertiesList
    assert "Layer_insulation_Shape" in obj.PropertiesList
    assert "Layer_insulation_Material" in obj.PropertiesList
    assert obj._editor_modes["Layer_casing_Shape"] == 1
    assert obj.ConstructionLayerIds == ["casing", "insulation"]


def test_apply_construction_schema_falls_back_to_a_single_implicit_layer(monkeypatch):
    # A type-def with no "construction" block at all (not yet migrated) --
    # still gets exactly one layer, matching geometry_result.normalize()'s
    # legacy {"shape": ...} wrapping under the same id.
    obj = FakeDuctObj()
    _patch_registry(monkeypatch, _FakeRegistry(_FakeTypeDef(construction=[])))

    _construction_schema.apply_construction_schema(obj, "builtin_basic", "circular_straight")

    assert obj.ConstructionLayerIds == [geometry_result.LEGACY_SHAPE_LAYER_ID]
    assert "Layer_shape_Shape" in obj.PropertiesList
    assert "Layer_shape_Material" in obj.PropertiesList


def test_apply_construction_schema_removes_layers_from_a_previous_type(monkeypatch):
    obj = FakeDuctObj()
    registry = _FakeRegistry(_FakeTypeDef([
        ConstructionLayerDef(id="casing", roles=["flow_surface"]),
        ConstructionLayerDef(id="liner", roles=["acoustic_liner"]),
    ]))
    _patch_registry(monkeypatch, registry)
    _construction_schema.apply_construction_schema(obj, "smacna", "acoustic_straight")
    assert {"Layer_casing_Shape", "Layer_liner_Shape"} <= set(obj.PropertiesList)

    # Switch TypeId to a single-layer type -- liner properties must go away.
    registry._type_def = _FakeTypeDef([ConstructionLayerDef(id="casing", roles=["flow_surface"])])
    _construction_schema.apply_construction_schema(obj, "smacna", "circular_straight")

    assert "Layer_liner_Shape" not in obj.PropertiesList
    assert "Layer_liner_Material" not in obj.PropertiesList
    assert "Layer_casing_Shape" in obj.PropertiesList
    assert obj.ConstructionLayerIds == ["casing"]


def test_apply_construction_schema_is_a_noop_without_library_or_type_id():
    obj = FakeDuctObj()
    assert _construction_schema.apply_construction_schema(obj, "", "") is False
    assert obj.PropertiesList == []


def test_apply_construction_schema_returns_false_when_nothing_changed(monkeypatch):
    obj = FakeDuctObj()
    registry = _FakeRegistry(_FakeTypeDef([ConstructionLayerDef(id="casing", roles=["flow_surface"])]))
    _patch_registry(monkeypatch, registry)

    _construction_schema.apply_construction_schema(obj, "smacna", "circular_straight")
    changed_again = _construction_schema.apply_construction_schema(obj, "smacna", "circular_straight")

    assert changed_again is False


# ----------------------------------------------------------------------
# apply_construction_features_schema()
# ----------------------------------------------------------------------

def test_apply_construction_features_schema_adds_shape_per_feature(monkeypatch):
    features = [
        ConstructionFeatureDef(id="transverse_flange", host_layer="casing", generator="generate_transverse_flange"),
        ConstructionFeatureDef(id="stiffener", host_layer="casing", generator="generate_stiffener"),
    ]
    obj = FakeDuctObj()
    _patch_registry(monkeypatch, _FakeRegistry(_FakeTypeDef([], features=features)))

    changed = _construction_schema.apply_construction_features_schema(obj, "smacna", "circular_straight")

    assert changed is True
    assert "Feature_transverse_flange_Shape" in obj.PropertiesList
    assert "Feature_stiffener_Shape" in obj.PropertiesList
    # No Feature_<id>_Material -- features have no material of their own.
    assert "Feature_transverse_flange_Material" not in obj.PropertiesList
    assert obj._editor_modes["Feature_transverse_flange_Shape"] == 1
    assert obj.ConstructionFeatureIds == ["transverse_flange", "stiffener"]


def test_apply_construction_features_schema_with_no_declared_features_is_a_noop(monkeypatch):
    obj = FakeDuctObj()
    _patch_registry(monkeypatch, _FakeRegistry(_FakeTypeDef([], features=[])))

    changed = _construction_schema.apply_construction_features_schema(obj, "smacna", "circular_straight")

    assert changed is False
    assert obj.ConstructionFeatureIds == []
    assert not any(name.startswith("Feature_") for name in obj.PropertiesList)


def test_apply_construction_features_schema_removes_features_from_a_previous_type(monkeypatch):
    obj = FakeDuctObj()
    registry = _FakeRegistry(_FakeTypeDef([], features=[
        ConstructionFeatureDef(id="transverse_flange", host_layer="casing", generator="generate_transverse_flange"),
        ConstructionFeatureDef(id="stiffener", host_layer="casing", generator="generate_stiffener"),
    ]))
    _patch_registry(monkeypatch, registry)
    _construction_schema.apply_construction_features_schema(obj, "smacna", "circular_acoustic_straight")
    assert {"Feature_transverse_flange_Shape", "Feature_stiffener_Shape"} <= set(obj.PropertiesList)

    registry._type_def = _FakeTypeDef([], features=[
        ConstructionFeatureDef(id="transverse_flange", host_layer="casing", generator="generate_transverse_flange"),
    ])
    _construction_schema.apply_construction_features_schema(obj, "smacna", "circular_straight")

    assert "Feature_stiffener_Shape" not in obj.PropertiesList
    assert "Feature_transverse_flange_Shape" in obj.PropertiesList
    assert obj.ConstructionFeatureIds == ["transverse_flange"]


def test_apply_construction_features_schema_marks_visible_parameter_no_recompute(monkeypatch):
    obj = FakeDuctObj()
    obj.addProperty("App::PropertyBool", "FlangeVisible", "Options", "")
    features = [
        ConstructionFeatureDef(
            id="transverse_flange", host_layer="casing", generator="generate_transverse_flange",
            visible_parameter="FlangeVisible",
        ),
    ]
    _patch_registry(monkeypatch, _FakeRegistry(_FakeTypeDef([], features=features)))

    _construction_schema.apply_construction_features_schema(obj, "smacna", "circular_straight")

    assert ("FlangeVisible", "NoRecompute") in obj._property_statuses


def test_apply_construction_features_schema_never_marks_enabled_or_ordinary_parameters(monkeypatch):
    # enabled_parameter and every name in `parameters` must keep triggering
    # a normal recompute -- only visible_parameter gets the NoRecompute
    # treatment.
    obj = FakeDuctObj()
    obj.addProperty("App::PropertyBool", "FlangeEnabled", "Options", "")
    obj.addProperty("App::PropertyLength", "FlangeDepth", "Dimensions", "")
    features = [
        ConstructionFeatureDef(
            id="transverse_flange", host_layer="casing", generator="generate_transverse_flange",
            enabled_parameter="FlangeEnabled", parameters=["FlangeDepth"],
        ),
    ]
    _patch_registry(monkeypatch, _FakeRegistry(_FakeTypeDef([], features=features)))

    _construction_schema.apply_construction_features_schema(obj, "smacna", "circular_straight")

    assert obj._property_statuses == []


def test_apply_construction_features_schema_tolerates_visible_parameter_not_yet_added(monkeypatch):
    # If the referenced property hasn't been added yet (e.g. a test calling
    # this in isolation, without first running apply_type_schema()), this
    # must not raise -- just skip the status call.
    obj = FakeDuctObj()
    features = [
        ConstructionFeatureDef(
            id="transverse_flange", host_layer="casing", generator="generate_transverse_flange",
            visible_parameter="FlangeVisible",
        ),
    ]
    _patch_registry(monkeypatch, _FakeRegistry(_FakeTypeDef([], features=features)))

    _construction_schema.apply_construction_features_schema(obj, "smacna", "circular_straight")  # must not raise

    assert obj._property_statuses == []


# ----------------------------------------------------------------------
# apply_default_layer_materials() / reset_layer_materials_to_network_defaults()
# ----------------------------------------------------------------------

class FakeMaterial:
    def __init__(self, name):
        self.Name = name


class FakeOwner:
    def __init__(self, **role_materials):
        for role, material in role_materials.items():
            setattr(self, "DefaultMaterial_" + role, material)


def _obj_with_layers(layer_ids, materials=None):
    obj = FakeDuctObj()
    obj.ConstructionLayerIds = list(layer_ids)
    for layer_id in layer_ids:
        obj.PropertiesList.append(_construction_schema.shape_property_name(layer_id))
        obj.PropertiesList.append(_construction_schema.material_property_name(layer_id))
        setattr(obj, _construction_schema.material_property_name(layer_id), (materials or {}).get(layer_id))
    return obj


def test_apply_default_layer_materials_resolves_by_role_from_owner_network(monkeypatch):
    obj = _obj_with_layers(["casing", "insulation"])
    registry = _FakeRegistry(_FakeTypeDef([
        ConstructionLayerDef(id="casing", roles=["structural_shell"]),
        ConstructionLayerDef(id="insulation", roles=["thermal_insulation"]),
    ]))
    _patch_registry(monkeypatch, registry)
    owner = FakeOwner(StructuralShell=FakeMaterial("Galvanized-Steel"), ThermalInsulation=FakeMaterial("Nitrile-Rubber"))
    monkeypatch.setattr(_construction_schema.hvaclib, "getOwnerNetwork", lambda o: owner)

    _construction_schema.apply_default_layer_materials(obj, "smacna", "circular_straight")

    assert obj.Layer_casing_Material.Name == "Galvanized-Steel"
    assert obj.Layer_insulation_Material.Name == "Nitrile-Rubber"


def test_apply_default_layer_materials_prefers_default_material_role_over_first_listed_role(monkeypatch):
    # Regression: a layer's `roles` list is ordered for semantic-query
    # purposes (see core/Construction.py), not "most material-relevant
    # first" -- e.g. a casing layer's own roles are typically
    # ["flow_surface", "structural_shell"], but its material clearly
    # belongs to the structural_shell role. default_material_role, when the
    # layer def declares one, must win over layer_def.roles[0].
    obj = _obj_with_layers(["casing"])
    registry = _FakeRegistry(_FakeTypeDef([
        ConstructionLayerDef(
            id="casing", roles=["flow_surface", "structural_shell"],
            default_material_role="structural_shell",
        ),
    ]))
    _patch_registry(monkeypatch, registry)
    owner = FakeOwner(FlowSurface=FakeMaterial("Wrong-Role"), StructuralShell=FakeMaterial("Galvanized-Steel"))
    monkeypatch.setattr(_construction_schema.hvaclib, "getOwnerNetwork", lambda o: owner)

    _construction_schema.apply_default_layer_materials(obj, "smacna", "circular_straight")

    assert obj.Layer_casing_Material.Name == "Galvanized-Steel"


def test_apply_default_layer_materials_prefers_explicit_layer_uuid_over_role(monkeypatch):
    obj = _obj_with_layers(["liner"])
    registry = _FakeRegistry(_FakeTypeDef([
        ConstructionLayerDef(id="liner", roles=["acoustic_liner"], default_material_uuid="some-uuid"),
    ]))
    _patch_registry(monkeypatch, registry)
    monkeypatch.setattr(
        _construction_schema.hvac_materials, "get_material_by_uuid",
        lambda uuid: FakeMaterial("Perforated-Steel") if uuid == "some-uuid" else None,
    )

    def _fail_if_called(obj):
        raise AssertionError("must not resolve the owner network when an explicit UUID is declared")
    monkeypatch.setattr(_construction_schema.hvaclib, "getOwnerNetwork", _fail_if_called)

    _construction_schema.apply_default_layer_materials(obj, "smacna", "acoustic_straight")

    assert obj.Layer_liner_Material.Name == "Perforated-Steel"


def test_apply_default_layer_materials_never_overwrites_an_already_assigned_material(monkeypatch):
    existing = FakeMaterial("Stainless-Steel")
    obj = _obj_with_layers(["casing"], materials={"casing": existing})
    registry = _FakeRegistry(_FakeTypeDef([ConstructionLayerDef(id="casing", roles=["structural_shell"])]))
    _patch_registry(monkeypatch, registry)
    owner = FakeOwner(StructuralShell=FakeMaterial("Galvanized-Steel"))
    monkeypatch.setattr(_construction_schema.hvaclib, "getOwnerNetwork", lambda o: owner)

    _construction_schema.apply_default_layer_materials(obj, "smacna", "circular_straight")

    assert obj.Layer_casing_Material is existing


def test_apply_default_layer_materials_never_resolves_owner_when_no_layer_needs_it(monkeypatch):
    """
    A not-yet-migrated type (empty construction list, no ConstructionLayerDef
    for its implicit "shape" layer) must never trigger owner-network
    resolution at all -- that lazily imports core/Network.py, which is heavy
    and GUI-only, so paying that cost when nothing needs a role default
    would be wasteful (and, in this addon's own test suite, would blow up
    because Network.py needs a real `pivy` install this suite doesn't stub).
    """
    obj = _obj_with_layers([geometry_result.LEGACY_SHAPE_LAYER_ID])
    registry = _FakeRegistry(_FakeTypeDef([]))
    _patch_registry(monkeypatch, registry)

    def _fail_if_called(o):
        raise AssertionError("must not resolve the owner network")
    monkeypatch.setattr(_construction_schema.hvaclib, "getOwnerNetwork", _fail_if_called)

    _construction_schema.apply_default_layer_materials(obj, "builtin_basic", "circular_straight")  # must not raise


def test_reset_layer_materials_to_network_defaults_overwrites_existing_material(monkeypatch):
    obj = _obj_with_layers(["casing"], materials={"casing": FakeMaterial("Old-Choice")})
    obj.LibraryId = "smacna"
    obj.TypeId = "circular_straight"
    registry = _FakeRegistry(_FakeTypeDef([ConstructionLayerDef(id="casing", roles=["structural_shell"])]))
    _patch_registry(monkeypatch, registry)
    owner = FakeOwner(StructuralShell=FakeMaterial("Galvanized-Steel"))
    monkeypatch.setattr(_construction_schema.hvaclib, "getOwnerNetwork", lambda o: owner)

    changed = _construction_schema.reset_layer_materials_to_network_defaults(obj)

    assert changed is True
    assert obj.Layer_casing_Material.Name == "Galvanized-Steel"
