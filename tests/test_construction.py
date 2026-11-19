"""
Tests for core/Construction.py: the semantic construction query API
(Construction.layers_with_role/flow_surface/structural_layers/
thermal_layers/acoustic_layers), and construction_for() which builds one
from a real object's own Layer_<id>_Shape/Layer_<id>_Material properties
plus its resolved type-def's declared construction. Downstream modules must
only ever query by role, never by a library-chosen layer id -- these tests
exercise arbitrary layer counts and multiple roles on one layer to make
sure that holds.
"""

import conftest  # noqa: F401 -- installs FreeCAD/FreeCADGui/Part/PySide stubs

from freecad.HVAC.core import Construction as construction_mod
from freecad.HVAC.library.construction import ConstructionLayerDef, ConstructionFeatureDef


class _Quantity:
    def __init__(self, value):
        self.Value = value

    def getValueAs(self, unit):
        return self


class _PhysicalMaterial:
    Name = "Material"

    def __init__(self, **values):
        self.values = values

    def hasPhysicalProperty(self, name):
        return name in self.values

    def getPhysicalValue(self, name):
        return _Quantity(self.values[name])


class FakeObj:
    def __init__(self, library_id, type_id, layer_ids, shapes=None, materials=None):
        self.LibraryId = library_id
        self.TypeId = type_id
        self.ConstructionLayerIds = list(layer_ids)
        self.ConstructionFeatureIds = []
        for layer_id in layer_ids:
            setattr(self, "Layer_{}_Shape".format(layer_id), (shapes or {}).get(layer_id))
            setattr(self, "Layer_{}_Material".format(layer_id), (materials or {}).get(layer_id))

    def add_feature(self, feature_id, shape=None):
        self.ConstructionFeatureIds.append(feature_id)
        setattr(self, "Feature_{}_Shape".format(feature_id), shape)


class _FakeTypeDef:
    def __init__(self, construction, features=None):
        self.construction = construction
        self.features = features or []


class _FakeRegistry:
    def __init__(self, type_def):
        self._type_def = type_def

    def resolve_type(self, lib_id, type_id):
        return self._type_def


def _patch_registry(monkeypatch, type_def):
    monkeypatch.setattr(
        construction_mod.hvaclib.HVACLibraryService,
        "get_hvac_library_registry",
        staticmethod(lambda: _FakeRegistry(type_def)),
    )


def test_single_layer_duct_flow_surface_is_also_structural(monkeypatch):
    _patch_registry(monkeypatch, _FakeTypeDef([
        ConstructionLayerDef(id="casing", roles=["flow_surface", "structural_shell"]),
    ]))
    casing_shape, casing_material = object(), object()
    obj = FakeObj("builtin_basic", "circular_straight", ["casing"],
                  shapes={"casing": casing_shape}, materials={"casing": casing_material})

    construction = construction_mod.construction_for(obj)

    flow = construction.flow_surface()
    assert flow.id == "casing"
    assert flow.shape is casing_shape
    assert flow.material is casing_material
    assert construction.structural_layers() == [flow]
    assert construction.thermal_layers() == []
    assert construction.acoustic_layers() == []


def test_casing_and_insulation_duct_separates_roles(monkeypatch):
    _patch_registry(monkeypatch, _FakeTypeDef([
        ConstructionLayerDef(id="casing", roles=["flow_surface", "structural_shell"]),
        ConstructionLayerDef(id="insulation", roles=["thermal_insulation"]),
    ]))
    obj = FakeObj("smacna", "circular_straight", ["casing", "insulation"])

    construction = construction_mod.construction_for(obj)

    assert construction.flow_surface().id == "casing"
    assert [layer.id for layer in construction.structural_layers()] == ["casing"]
    assert [layer.id for layer in construction.thermal_layers()] == ["insulation"]
    assert construction.acoustic_layers() == []


def test_acoustic_three_layer_duct_liner_is_flow_surface_not_structural(monkeypatch):
    _patch_registry(monkeypatch, _FakeTypeDef([
        ConstructionLayerDef(id="jacket", roles=["outer_jacket", "structural_shell"]),
        ConstructionLayerDef(id="absorber", roles=["acoustic_absorber"]),
        ConstructionLayerDef(id="liner", roles=["flow_surface", "acoustic_liner"]),
    ]))
    obj = FakeObj("smacna", "acoustic_circular_straight", ["jacket", "absorber", "liner"])

    construction = construction_mod.construction_for(obj)

    assert construction.flow_surface().id == "liner"
    assert [layer.id for layer in construction.structural_layers()] == ["jacket"]
    assert {layer.id for layer in construction.acoustic_layers()} == {"absorber", "liner"}
    assert construction.thermal_layers() == []


def test_layers_with_multiple_roles_are_returned_from_every_matching_query(monkeypatch):
    _patch_registry(monkeypatch, _FakeTypeDef([
        ConstructionLayerDef(id="liner", roles=["flow_surface", "acoustic_liner", "fire_protection"]),
    ]))
    obj = FakeObj("smacna", "acoustic_circular_straight", ["liner"])

    construction = construction_mod.construction_for(obj)
    liner = construction.layer("liner")

    assert liner in construction.layers_with_role("fire_protection")
    assert liner in construction.acoustic_layers()
    assert liner is construction.flow_surface()
    assert liner.has_role("acoustic_liner")
    assert not liner.has_role("thermal_insulation")


def test_construction_exposes_material_roughness_and_thermal_u_value(monkeypatch):
    _patch_registry(monkeypatch, _FakeTypeDef([
        ConstructionLayerDef(
            id="casing", roles=["flow_surface", "structural_shell"],
            thickness_property="Thickness",
        ),
        ConstructionLayerDef(
            id="insulation", roles=["thermal_insulation"],
            thickness_property="InsulationThickness",
        ),
    ]))
    obj = FakeObj(
        "smacna", "circular_straight", ["casing", "insulation"],
        materials={
            "casing": _PhysicalMaterial(HydraulicRoughness=0.09, ThermalConductivity=50.0),
            "insulation": _PhysicalMaterial(ThermalConductivity=0.04),
        },
    )
    obj.Thickness = 1.0
    obj.InsulationThickness = 25.0

    construction = construction_mod.construction_for(obj)

    assert construction.hydraulic_roughness() == 0.09
    expected_resistance = 0.001 / 50.0 + 0.025 / 0.04
    assert abs(construction.overall_u_value() - 1.0 / expected_resistance) < 1e-9


def test_construction_physical_queries_return_caller_fallback_when_unavailable():
    construction = construction_mod.Construction([])
    assert construction.hydraulic_roughness(0.15) == 0.15
    assert construction.acoustic_impedance(default=412.0) == 412.0
    assert construction.overall_u_value(default=0.0) == 0.0


def test_hydraulic_roughness_reads_only_the_flow_surface_layer():
    outer = _PhysicalMaterial(HydraulicRoughness=0.8)
    flow = _PhysicalMaterial(HydraulicRoughness=0.12)
    construction = construction_mod.Construction([
        construction_mod.ConstructionLayer(
            id="jacket", roles=["outer_jacket"], material=outer,
        ),
        construction_mod.ConstructionLayer(
            id="liner", roles=["flow_surface"], material=flow,
        ),
    ])

    assert construction.hydraulic_roughness(0.09) == 0.12


def test_construction_for_a_not_yet_migrated_type_has_no_roles(monkeypatch):
    # Empty construction list -- construction_for() still builds one layer
    # per obj.ConstructionLayerIds (populated by apply_construction_schema's
    # single-implicit-layer fallback), just with no roles at all.
    _patch_registry(monkeypatch, _FakeTypeDef([]))
    obj = FakeObj("builtin_basic", "rectangular_straight", ["shape"])

    construction = construction_mod.construction_for(obj)

    assert construction.flow_surface() is None
    assert construction.structural_layers() == []
    assert construction.layer("shape").roles == []


def test_construction_for_object_with_no_layers_at_all(monkeypatch):
    _patch_registry(monkeypatch, _FakeTypeDef([]))
    obj = FakeObj("", "", [])

    construction = construction_mod.construction_for(obj)

    assert construction.layers() == []
    assert construction.flow_surface() is None


# ----------------------------------------------------------------------
# Construction features
# ----------------------------------------------------------------------

def test_construction_for_resolves_feature_role_and_host_layer(monkeypatch):
    _patch_registry(monkeypatch, _FakeTypeDef(
        [ConstructionLayerDef(id="casing", roles=["flow_surface", "structural_shell"])],
        features=[
            ConstructionFeatureDef(
                id="transverse_flange", role="transverse_joint", host_layer="casing",
                generator="generate_transverse_flange",
            ),
        ],
    ))
    obj = FakeObj("smacna", "circular_straight", ["casing"])
    flange_shape = object()
    obj.add_feature("transverse_flange", flange_shape)

    construction = construction_mod.construction_for(obj)

    feature = construction.feature("transverse_flange")
    assert feature.role == "transverse_joint"
    assert feature.host_layer == "casing"
    assert feature.shape is flange_shape
    assert feature in construction.features_with_role("transverse_joint")
    assert construction.features_with_role("something_else") == []


def test_construction_for_reads_enabled_and_visible_fresh_off_the_object(monkeypatch):
    # Not from a cached GeometryResult snapshot -- straight off whatever
    # property enabled_parameter/visible_parameter currently name.
    _patch_registry(monkeypatch, _FakeTypeDef(
        [ConstructionLayerDef(id="casing", roles=["flow_surface"])],
        features=[
            ConstructionFeatureDef(
                id="transverse_flange", host_layer="casing", generator="generate_transverse_flange",
                enabled_parameter="FlangeEnabled", visible_parameter="FlangeVisible",
            ),
        ],
    ))
    obj = FakeObj("smacna", "circular_straight", ["casing"])
    obj.add_feature("transverse_flange")
    obj.FlangeEnabled = False
    obj.FlangeVisible = True

    construction = construction_mod.construction_for(obj)
    feature = construction.feature("transverse_flange")

    assert feature.enabled is False
    assert feature.visible is True


def test_construction_for_defaults_enabled_and_visible_true_when_no_parameter_declared(monkeypatch):
    _patch_registry(monkeypatch, _FakeTypeDef(
        [ConstructionLayerDef(id="casing", roles=["flow_surface"])],
        features=[
            ConstructionFeatureDef(id="stiffener", host_layer="casing", generator="generate_stiffener"),
        ],
    ))
    obj = FakeObj("smacna", "circular_straight", ["casing"])
    obj.add_feature("stiffener")

    feature = construction_mod.construction_for(obj).feature("stiffener")

    assert feature.enabled is True
    assert feature.visible is True


def test_construction_for_a_type_with_no_declared_features_has_none():
    obj = FakeObj("builtin_basic", "rectangular_straight", ["shape"])
    # No _patch_registry call -- construction_for() must tolerate an
    # unresolvable type_def (library_id/type_id empty here) the same way
    # it already does for layers.
    construction = construction_mod.construction_for(obj)

    assert construction.features() == []
    assert construction.feature("anything") is None
