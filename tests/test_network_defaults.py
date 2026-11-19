"""
Focused tests for DuctNetwork's own default-value properties added for the
multilayer construction feature: one Materials::PropertyMaterial property
per standardized LayerRole (DefaultMaterial_<Role> -- see
library/construction.py's ALL_LAYER_ROLES/role_property_suffix), seeded with
the stock material requested for each standard role (except project-specific
fire protection) -- plus the Network.applyNetworkTypeDefaults()/
applyMaterialSelection() callbacks that read/write them. See
ARCHITECTURE.md's "Component geometry & materials" section.
"""

import conftest  # noqa: F401 -- installs FreeCAD/FreeCADGui/Part/Materials/MatGui/PySide stubs

from freecad.HVAC.core import Network as network_mod
from freecad.HVAC.core import _construction_schema
from freecad.HVAC.library.construction import (
    ALL_LAYER_ROLES, ROLE_FLOW_SURFACE, ROLE_STRUCTURAL_SHELL,
    ROLE_THERMAL_INSULATION, ROLE_ACOUSTIC_ABSORBER, ROLE_ACOUSTIC_LINER,
    ROLE_VAPOR_BARRIER, ROLE_OUTER_JACKET, role_property_suffix,
)


class FakeMaterial:
    def __init__(self, name):
        self.Name = name


class FakeNetworkObj:
    """
    Minimal stand-in for a FreeCAD DocumentObject, with Base/Geometry/
    Topology already set to dummy truthy values and Document=None, so
    DuctNetwork.setProperties()'s managed-folder creation takes its
    "already exists" branch instead of needing a real document.
    """

    def __init__(self):
        self.Document = None
        self.Name = "Network0"
        self.PropertiesList = []
        self._editor_modes = {}
        self._prop_attrs = {}
        # Pre-existing "folders" so setProperties() skips DuctManagedFolder.create().
        self.Base = object()
        self.Geometry = object()
        self.Topology = object()

    def addProperty(self, prop_type, name, group, description, attr=0):
        if name not in self.PropertiesList:
            self.PropertiesList.append(name)
            setattr(self, name, None)
        self._prop_attrs[name] = attr
        return self

    def setEditorMode(self, name, mode):
        self._editor_modes[name] = mode

    def touch(self):
        pass


def _bare_network():
    return network_mod.DuctNetwork.__new__(network_mod.DuctNetwork)


def _patch_library_lookups(monkeypatch):
    monkeypatch.setattr(
        network_mod.hvaclib.HVACLibraryService, "get_active_hvac_library", staticmethod(lambda: None)
    )


def _default_material_prop(role):
    return "DefaultMaterial_" + role_property_suffix(role)


def test_setproperties_adds_one_default_material_property_per_role(monkeypatch):
    _patch_library_lookups(monkeypatch)
    steel = FakeMaterial("Galvanized-Steel")
    wool = FakeMaterial("Nitrile-Rubber")
    open_cell = FakeMaterial("Nitrile-Rubber-Open-Cell")
    perforated = FakeMaterial("Galvanized-Steel-Perforated")
    aluminium = FakeMaterial("Aluminium")

    def fake_get_material_by_uuid(uuid):
        return {
            network_mod.hvac_materials.GALVANIZED_STEEL_UUID: steel,
            network_mod.hvac_materials.NITRILE_RUBBER_UUID: wool,
            network_mod.hvac_materials.NITRILE_RUBBER_OPEN_CELL_UUID: open_cell,
            network_mod.hvac_materials.GALVANIZED_STEEL_PERFORATED_UUID: perforated,
            network_mod.hvac_materials.ALUMINIUM_UUID: aluminium,
        }.get(uuid)

    monkeypatch.setattr(network_mod.hvac_materials, "get_material_by_uuid", fake_get_material_by_uuid)

    obj = FakeNetworkObj()
    _bare_network().setProperties(obj)

    for role in ALL_LAYER_ROLES:
        prop_name = _default_material_prop(role)
        assert prop_name in obj.PropertiesList, prop_name
        assert obj._prop_attrs[prop_name] == 16  # Prop_NoRecompute

    # Every role with a requested stock material gets its role-specific default.
    assert getattr(obj, _default_material_prop(ROLE_FLOW_SURFACE)) is steel
    assert getattr(obj, _default_material_prop(ROLE_STRUCTURAL_SHELL)) is steel
    assert getattr(obj, _default_material_prop(ROLE_THERMAL_INSULATION)) is wool
    assert getattr(obj, _default_material_prop(ROLE_ACOUSTIC_ABSORBER)) is open_cell
    assert getattr(obj, _default_material_prop(ROLE_ACOUSTIC_LINER)) is perforated
    assert getattr(obj, _default_material_prop(ROLE_VAPOR_BARRIER)) is aluminium
    assert getattr(obj, _default_material_prop(ROLE_OUTER_JACKET)) is aluminium


def test_setproperties_leaves_manually_assigned_default_materials_alone(monkeypatch):
    _patch_library_lookups(monkeypatch)
    monkeypatch.setattr(network_mod.hvac_materials, "get_material_by_uuid", lambda uuid: FakeMaterial("SHOULD_NOT_BE_USED"))

    obj = FakeNetworkObj()
    _bare_network().setProperties(obj)

    custom = FakeMaterial("Aluminium")
    setattr(obj, _default_material_prop(ROLE_STRUCTURAL_SHELL), custom)

    # A second setProperties() call (e.g. onDocumentRestored) must not
    # clobber an already-assigned default.
    _bare_network().setProperties(obj)
    assert getattr(obj, _default_material_prop(ROLE_STRUCTURAL_SHELL)) is custom


def test_setproperties_defaults_missing_material_gracefully(monkeypatch):
    # register_material_resources() hasn't run / the UUID isn't known yet --
    # must not raise, just leave the property unassigned.
    _patch_library_lookups(monkeypatch)
    monkeypatch.setattr(network_mod.hvac_materials, "get_material_by_uuid", lambda uuid: None)

    obj = FakeNetworkObj()
    _bare_network().setProperties(obj)  # must not raise

    assert getattr(obj, _default_material_prop(ROLE_STRUCTURAL_SHELL)) is None


def test_setproperties_hides_internal_managed_folder_links(monkeypatch):
    """
    Base/Geometry/Topology are plain App::PropertyLink pointers to this
    network's own internal managed folders (see DuctManagedFolder) -- kept
    (never removed) so the addon's own code can still reach them, but
    hidden from the property editor since a user never needs to read or
    edit them directly (the folders themselves stay visible in the tree).
    """
    _patch_library_lookups(monkeypatch)

    obj = FakeNetworkObj()
    _bare_network().setProperties(obj)

    assert obj._editor_modes["Base"] == 2
    assert obj._editor_modes["Geometry"] == 2
    assert obj._editor_modes["Topology"] == 2


def test_apply_network_type_defaults_writes_materials_by_role():
    obj = FakeNetworkObj()
    setattr(obj, _default_material_prop(ROLE_STRUCTURAL_SHELL), None)
    setattr(obj, _default_material_prop(ROLE_THERMAL_INSULATION), None)

    steel = FakeMaterial("Galvanized-Steel")

    changed = network_mod.DuctNetwork.applyNetworkTypeDefaults(
        obj,
        default_materials_by_role={ROLE_STRUCTURAL_SHELL: steel},
    )

    assert changed is True
    assert getattr(obj, _default_material_prop(ROLE_STRUCTURAL_SHELL)) is steel
    # thermal_insulation wasn't in the dict -- must stay untouched.
    assert getattr(obj, _default_material_prop(ROLE_THERMAL_INSULATION)) is None


def test_apply_network_type_defaults_omitted_kwargs_are_a_noop():
    obj = FakeNetworkObj()
    setattr(obj, _default_material_prop(ROLE_STRUCTURAL_SHELL), FakeMaterial("Existing"))

    changed = network_mod.DuctNetwork.applyNetworkTypeDefaults(obj)

    assert changed is False
    assert getattr(obj, _default_material_prop(ROLE_STRUCTURAL_SHELL)).Name == "Existing"


# ----------------------------------------------------------------------
# applyMaterialSelection
# ----------------------------------------------------------------------

class FakeDuctObj:
    def __init__(self, casing=None, insulation=None):
        self.PropertiesList = [
            _construction_schema.material_property_name("casing"),
            _construction_schema.material_property_name("insulation"),
        ]
        setattr(self, _construction_schema.material_property_name("casing"), casing)
        setattr(self, _construction_schema.material_property_name("insulation"), insulation)


def test_apply_material_selection_sets_only_the_given_layers():
    obj1 = FakeDuctObj(casing=FakeMaterial("Old1"), insulation=FakeMaterial("Old2"))
    obj2 = FakeDuctObj(casing=FakeMaterial("Old3"), insulation=FakeMaterial("Old4"))
    new_insulation = FakeMaterial("New-Insulation")

    network_mod.DuctNetwork.applyMaterialSelection([obj1, obj2], {"insulation": new_insulation})

    assert obj1.Layer_casing_Material.Name == "Old1"  # untouched -- not in the dict
    assert obj1.Layer_insulation_Material is new_insulation
    assert obj2.Layer_casing_Material.Name == "Old3"
    assert obj2.Layer_insulation_Material is new_insulation


def test_apply_material_selection_skips_none_objects_and_missing_layers():
    class NoLayerProps:
        PropertiesList = []

    obj = NoLayerProps()
    network_mod.DuctNetwork.applyMaterialSelection([None, obj], {"casing": FakeMaterial("X")})  # must not raise
    assert not hasattr(obj, "Layer_casing_Material")


def test_apply_material_selection_empty_dict_is_a_true_noop():
    obj = FakeDuctObj(casing=FakeMaterial("Keep1"), insulation=FakeMaterial("Keep2"))
    network_mod.DuctNetwork.applyMaterialSelection([obj], {})
    assert obj.Layer_casing_Material.Name == "Keep1"
    assert obj.Layer_insulation_Material.Name == "Keep2"


# ----------------------------------------------------------------------------
# Deferred edit sync: a property edit inside an open transaction syncs once
# the transaction closes (core/_type_schema.request_sync_after_edit).
# ----------------------------------------------------------------------------


def _syncing_network():
    proxy = network_mod.DuctNetwork.__new__(network_mod.DuctNetwork)
    proxy.requests = []
    proxy.requestSync = lambda **kwargs: proxy.requests.append(kwargs)
    return proxy


def test_a_deferred_edit_syncs_once_when_its_transaction_closes():
    proxy = _syncing_network()
    proxy.deferEditSync()
    proxy.deferEditSync()
    assert proxy.requests == []
    proxy.runEditSync()
    assert proxy.requests == [{"force_recompute": True}]
    # Nothing left over for the next transaction.
    proxy.runEditSync()
    assert proxy.requests == [{"force_recompute": True}]


def test_a_transaction_closing_without_an_edit_syncs_nothing():
    proxy = _syncing_network()
    proxy.runEditSync()
    assert proxy.requests == []
