"""
Focused test for DuctNetwork.resetObjectsToNetworkDefaults(): an explicit
"Reset to Defaults" must also re-apply the owner network's current
per-role DefaultMaterial_<Role> onto every construction layer of the
selected segment/component -- unlike
core/_construction_schema.apply_default_layer_materials() (only fills in a
material a layer doesn't have yet), this always overwrites, same "reset
always wins" convention already used here for LibraryId/TypeId. See
ARCHITECTURE.md's "Component geometry & materials" section.

Uses the same real-DuctSegment-against-a-fake-document approach as
test_network_component_sync.py, so hvaclib.isDuctSegment/getOwnerNetwork
and the real bundled smacna library type selection behave exactly as in
the real addon -- smacna's circular_straight declares a "casing"
(flow_surface/structural_shell) + "insulation" (thermal_insulation)
construction (see libraries/smacna/types/segments/circular_straight.json).
"""

import conftest  # noqa: F401 -- installs FreeCAD/FreeCADGui/Part/Materials/MatGui/PySide stubs

from freecad.HVAC.core import Network as network_mod
from freecad.HVAC.core import _construction_schema
from freecad.HVAC.core.Segment import DuctSegment
from freecad.HVAC.utils import hvaclib
from freecad.HVAC.library.construction import ROLE_STRUCTURAL_SHELL, ROLE_THERMAL_INSULATION, role_property_suffix


class FakeMaterial:
    def __init__(self, name):
        self.Name = name


class FakeViewObject:
    def __init__(self):
        self.Visibility = True


class FakeFCObj:
    """Minimal stand-in for a FreeCAD DocumentObject -- see
    test_network_component_sync.py's identical fixture for why this is
    enough for addProperty/setEditorMode/touch/doc.getObject to work."""

    def __init__(self, name, doc):
        self.Name = name
        self.Label = name
        self.Document = doc
        self.PropertiesList = []
        self._editor_modes = {}
        self.ViewObject = FakeViewObject()

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

    def touch(self):
        pass


class FakeGeometryFolder(FakeFCObj):
    def __init__(self, name, doc):
        super().__init__(name, doc)
        self.OutList = []

    def addObject(self, obj):
        if obj not in self.OutList:
            self.OutList.append(obj)


class FakeDoc:
    def __init__(self):
        self._objects = {}

    def addObject(self, type_str, name):
        obj = FakeFCObj(name, self)
        self._objects[name] = obj
        return obj

    def getObject(self, name):
        return self._objects.get(name)

    def recompute(self):
        pass


def _make_network(doc):
    net_obj = FakeFCObj("Network0", doc)
    net_obj.Geometry = FakeGeometryFolder("Geometry0", doc)
    doc._objects[net_obj.Name] = net_obj

    net_proxy = network_mod.DuctNetwork.__new__(network_mod.DuctNetwork)
    net_proxy.Object = net_obj
    net_obj.Proxy = net_proxy
    return net_obj


def _set_default_material(net_obj, role, material):
    setattr(net_obj, "DefaultMaterial_" + role_property_suffix(role), material)


def test_reset_to_defaults_overwrites_existing_layer_materials(monkeypatch):
    doc = FakeDoc()
    net_obj = _make_network(doc)
    net_obj.DefaultLibraryId = "smacna"
    net_obj.DefaultSegmentProfile = "Circular"

    default_casing = FakeMaterial("Galvanized-Steel")
    default_insulation = FakeMaterial("Nitrile-Rubber")
    _set_default_material(net_obj, ROLE_STRUCTURAL_SHELL, default_casing)
    _set_default_material(net_obj, ROLE_THERMAL_INSULATION, default_insulation)

    segment = DuctSegment.create(doc, "Segment0", owner=net_obj, key="A", source_obj=None, source_index=0)
    segment.Proxy._allow_delete = True
    # A manually-assigned material, distinct from the network's own default --
    # the whole point of this test is that "Reset to Defaults" discards it.
    segment.Layer_casing_Material = FakeMaterial("Aluminium")
    segment.Layer_insulation_Material = FakeMaterial("Glass-Wool")

    monkeypatch.setattr(network_mod.FreeCAD, "ActiveDocument", doc)
    # This fixture's segment has no real base Sketch/Wire object (source_obj
    # is None), so hvaclib.BaseCurveKind can't classify it -- force
    # "straight" so real automatic type selection resolves circular_straight
    # (a curved classification would ask for a "curved_segment" family this
    # type-def doesn't declare, an unrelated concern to what this test
    # exercises).
    monkeypatch.setattr(network_mod.hvaclib, "BaseCurveKind", lambda *a, **k: "straight")

    network_mod.DuctNetwork.resetObjectsToNetworkDefaults([segment])

    assert segment.TypeId == "circular_straight"
    assert segment.Layer_casing_Material is default_casing
    assert segment.Layer_insulation_Material is default_insulation


def test_reset_to_defaults_tolerates_no_default_material_set(monkeypatch):
    # A network whose own DefaultMaterial_<Role> properties were never
    # resolved (e.g. register_material_resources() hasn't run) must not
    # raise, and must leave the segment's existing material alone.
    doc = FakeDoc()
    net_obj = _make_network(doc)
    net_obj.DefaultLibraryId = "smacna"
    net_obj.DefaultSegmentProfile = "Circular"
    _set_default_material(net_obj, ROLE_STRUCTURAL_SHELL, None)
    _set_default_material(net_obj, ROLE_THERMAL_INSULATION, None)

    segment = DuctSegment.create(doc, "Segment0", owner=net_obj, key="A", source_obj=None, source_index=0)
    segment.Proxy._allow_delete = True
    monkeypatch.setattr(network_mod.hvaclib, "BaseCurveKind", lambda *a, **k: "straight")
    # Layer_casing_Material only exists once a type has actually been
    # selected and its construction schema applied at least once (real
    # FreeCAD property lifecycle) -- prime that first, then assign the
    # "existing" value, so the reset below finds a real property already
    # holding it rather than wiping a bare attribute addProperty() would
    # otherwise just be creating for the first time.
    segment.LibraryId = "smacna"
    segment.TypeId = "circular_straight"
    segment.Proxy.applyTypeSchema()
    existing = FakeMaterial("Aluminium")
    segment.Layer_casing_Material = existing

    monkeypatch.setattr(network_mod.FreeCAD, "ActiveDocument", doc)
    # get_material_by_uuid()'s own real-FreeCAD contract is "None if it
    # isn't (yet) known -- e.g. register_material_resources() hasn't run
    # yet" (see utils/materials.py); the stubbed Materials module (a bare
    # MagicMock, see conftest.py) can't reproduce that lookup-miss on its
    # own, so force it here to actually exercise the "no material resolves
    # at all, even the sentinel Default" path this test is named for.
    monkeypatch.setattr(_construction_schema.hvac_materials, "get_material_by_uuid", lambda uuid: None)

    network_mod.DuctNetwork.resetObjectsToNetworkDefaults([segment])  # must not raise

    assert segment.TypeId == "circular_straight"
    assert segment.Layer_casing_Material is existing
