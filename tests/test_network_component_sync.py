"""
Focused tests for DuctNetwork's junction/component sync orchestration:
DuctNetwork.syncJunctionComponents (create/retain the Primary component with
sticky type resolution, retain each Inline component as long as its own
AttachedEdgeKey is still a real connected edge -- independent of the
junction's overall topology/degree -- and auto-delete it with a warning
otherwise) and DuctNetwork.removeGeometryObject's deletion cascade (deleting
a junction deletes its DuctComponent children).

Uses real DuctJunction/DuctComponent/DuctNetwork classes against a minimal
fake FreeCAD document, so hvaclib.isDuctJunction/isDuctComponent/
getOwnerNetwork (all isinstance/attribute-based) behave exactly as in the
real addon, and real bundled library type-defs drive selection.
"""

import json

import conftest  # noqa: F401 -- installs FreeCAD/FreeCADGui/Part/PySide stubs
import pytest

from freecad.HVAC.core import Network as network_mod
from freecad.HVAC.core.Component import DuctComponent
from freecad.HVAC.core.Junction import DuctJunction
from freecad.HVAC.utils import hvaclib


class FakeViewObject:
    def __init__(self):
        self.Visibility = True


class FakeFCObj:
    """Minimal stand-in for a FreeCAD DocumentObject: dynamic properties +
    document/name bookkeeping, enough for addProperty/setEditorMode/touch
    and doc.getObject(name) round-tripping to work."""

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

    def removeObject(self, obj):
        if obj in self.OutList:
            self.OutList.remove(obj)


class FakeDoc:
    def __init__(self):
        self._objects = {}

    def addObject(self, type_str, name):
        obj = FakeFCObj(name, self)
        self._objects[name] = obj
        return obj

    def getObject(self, name):
        return self._objects.get(name)

    def removeObject(self, name):
        self._objects.pop(name, None)


def _make_network():
    doc = FakeDoc()
    net_obj = FakeFCObj("Network0", doc)
    net_obj.Geometry = FakeGeometryFolder("Geometry0", doc)
    doc._objects[net_obj.Name] = net_obj

    net_proxy = network_mod.DuctNetwork.__new__(network_mod.DuctNetwork)
    net_proxy.Object = net_obj
    net_proxy._hidden_source_names = set()
    net_obj.Proxy = net_proxy
    return doc, net_obj, net_proxy


def _make_junction(doc, net_obj, name="Junc0", topology="through", degree=2):
    return DuctJunction.create(
        doc, name, owner=net_obj, node_id=0, node_key="N0",
        center_point=(0.0, 0.0, 0.0), degree=degree, topology=topology,
    )


def _smacna_library():
    reg = hvaclib.HVACLibraryService.get_hvac_library_registry()
    return reg.get_library("smacna")


def _circular_ports(n=2, edge_keys=None):
    keys = list(edge_keys) if edge_keys is not None else [chr(ord("A") + i) for i in range(n)]
    return [
        {"profile": "Circular", "edge_key": key, "flow_into_junction": (i == 0)}
        for i, key in enumerate(keys)
    ]


def test_creates_primary_component_when_absent():
    doc, net_obj, net_proxy = _make_network()
    junction = _make_junction(doc, net_obj)
    net_obj.Geometry.addObject(junction)
    lib = _smacna_library()

    changed = net_proxy.syncJunctionComponents(
        junction, "through", "through.straight", "Circular", _circular_ports(2),
        existing_components=[], default_lib=lib, hide_new=None,
    )

    assert changed is True
    components = [o for o in net_obj.Geometry.OutList if hvaclib.isDuctComponent(o)]
    assert len(components) == 1
    primary = components[0]
    assert primary.ComponentRole == "Primary"
    assert primary.ParentJunctionName == junction.Name
    # A plain "through.straight" request gets smacna's dedicated straight
    # joint, through_straight_generic (as in builtin_basic).
    assert primary.TypeId == "through_straight_generic"


def test_sticky_primary_type_is_retained_across_syncs():
    doc, net_obj, net_proxy = _make_network()
    junction = _make_junction(doc, net_obj)
    net_obj.Geometry.addObject(junction)
    lib = _smacna_library()

    net_proxy.syncJunctionComponents(
        junction, "through", "through.straight", "Circular", _circular_ports(2),
        existing_components=[], default_lib=lib, hide_new=None,
    )
    primary = next(o for o in net_obj.Geometry.OutList if hvaclib.isDuctComponent(o))

    # Manually override to a different, still-compatible model (mirroring a
    # user's manual type-selection choice) and resync -- it must survive.
    primary.TypeId = "through_generic"
    primary.Proxy.applyTypeSchema()

    changed = net_proxy.syncJunctionComponents(
        junction, "through", "through.straight", "Circular", _circular_ports(2),
        existing_components=[primary], default_lib=lib, hide_new=None,
    )

    assert primary.TypeId == "through_generic"
    components = [o for o in net_obj.Geometry.OutList if hvaclib.isDuctComponent(o)]
    assert len(components) == 1


def test_inline_component_never_auto_replaced_when_primary_family_changes():
    doc, net_obj, net_proxy = _make_network()
    junction = _make_junction(doc, net_obj)
    net_obj.Geometry.addObject(junction)
    lib = _smacna_library()

    net_proxy.syncJunctionComponents(
        junction, "through", "through.straight", "Circular", _circular_ports(2),
        existing_components=[], default_lib=lib, hide_new=None,
    )
    primary = next(o for o in net_obj.Geometry.OutList if hvaclib.isDuctComponent(o))

    inline = DuctComponent.create(
        doc, "{}_Comp10".format(junction.Name), parent_junction=junction,
        role="Inline", attached_edge_key="B", port_sequence=10, owner_network=net_obj,
    )
    net_obj.Geometry.addObject(inline)
    inline.LibraryId = "smacna"
    inline.TypeId = "through_damper_generic"
    inline.Proxy.applyTypeSchema()

    # Resync with a DIFFERENT family (a bend instead of a straight run) --
    # the Primary's type should update, but the Inline damper must stay
    # exactly as the user left it.
    net_proxy.syncJunctionComponents(
        junction, "through", "through.bend", "Circular", _circular_ports(2),
        existing_components=[primary, inline], default_lib=lib, hide_new=None,
    )

    assert primary.TypeId != "through_transition_generic"
    assert inline.TypeId == "through_damper_generic"
    assert inline.ComponentRole == "Inline"
    components = [o for o in net_obj.Geometry.OutList if hvaclib.isDuctComponent(o)]
    assert len(components) == 2


def test_topology_change_retains_inline_when_attached_edge_still_connected(monkeypatch):
    """
    An Inline component's retention no longer depends on the junction
    staying a simple through/2-port node -- only on its OWN AttachedEdgeKey
    still being one of the junction's real connected edges. A topology
    change (a new edge C snapped in, turning this node into a branch) must
    not disturb a damper attached to edge B, which is still there.
    """
    doc, net_obj, net_proxy = _make_network()
    junction = _make_junction(doc, net_obj, topology="through", degree=2)
    net_obj.Geometry.addObject(junction)
    lib = _smacna_library()

    net_proxy.syncJunctionComponents(
        junction, "through", "through.straight", "Circular", _circular_ports(2),
        existing_components=[], default_lib=lib, hide_new=None,
    )
    primary = next(o for o in net_obj.Geometry.OutList if hvaclib.isDuctComponent(o))

    inline = DuctComponent.create(
        doc, "{}_Comp10".format(junction.Name), parent_junction=junction,
        role="Inline", attached_edge_key="B", port_sequence=10, owner_network=net_obj,
    )
    net_obj.Geometry.addObject(inline)
    inline_name = inline.Name

    junction.Topology = "branch"
    net_proxy.syncJunctionComponents(
        junction, "branch", "branch.tee", "Circular", _circular_ports(3),
        existing_components=[primary, inline], default_lib=lib, hide_new=None,
    )

    components = [o for o in net_obj.Geometry.OutList if hvaclib.isDuctComponent(o)]
    assert {c.Name for c in components} == {primary.Name, inline_name}
    assert doc.getObject(inline_name) is not None
    assert inline.ComponentRole == "Inline"


def test_inline_dropped_when_its_attached_edge_disappears(monkeypatch):
    """
    If the specific edge an Inline component is attached to disappears
    (e.g. base geometry resnapped it to a different key), that Inline
    component is removed with a console warning -- independent of whatever
    happens to the junction's other edges/topology.
    """
    doc, net_obj, net_proxy = _make_network()
    junction = _make_junction(doc, net_obj, topology="through", degree=2)
    net_obj.Geometry.addObject(junction)
    lib = _smacna_library()

    net_proxy.syncJunctionComponents(
        junction, "through", "through.straight", "Circular", _circular_ports(2),
        existing_components=[], default_lib=lib, hide_new=None,
    )
    primary = next(o for o in net_obj.Geometry.OutList if hvaclib.isDuctComponent(o))

    inline = DuctComponent.create(
        doc, "{}_Comp10".format(junction.Name), parent_junction=junction,
        role="Inline", attached_edge_key="B", port_sequence=10, owner_network=net_obj,
    )
    net_obj.Geometry.addObject(inline)
    inline_name = inline.Name

    network_mod.FreeCAD.Console.PrintWarning.reset_mock()
    net_proxy.syncJunctionComponents(
        junction, "through", "through.straight", "Circular", _circular_ports(edge_keys=["A", "X"]),
        existing_components=[primary, inline], default_lib=lib, hide_new=None,
    )

    components = [o for o in net_obj.Geometry.OutList if hvaclib.isDuctComponent(o)]
    assert [c.Name for c in components] == [primary.Name]
    assert doc.getObject(inline_name) is None

    warnings = " ".join(
        str(call.args[0]) for call in network_mod.FreeCAD.Console.PrintWarning.call_args_list
    )
    assert "inline" in warnings.lower()


def test_remove_geometry_object_cascades_to_components():
    doc, net_obj, net_proxy = _make_network()
    junction = _make_junction(doc, net_obj)
    net_obj.Geometry.addObject(junction)
    lib = _smacna_library()

    net_proxy.syncJunctionComponents(
        junction, "through", "through.straight", "Circular", _circular_ports(2),
        existing_components=[], default_lib=lib, hide_new=None,
    )
    primary = next(o for o in net_obj.Geometry.OutList if hvaclib.isDuctComponent(o))
    inline = DuctComponent.create(
        doc, "{}_Comp10".format(junction.Name), parent_junction=junction,
        role="Inline", attached_edge_key="B", port_sequence=10, owner_network=net_obj,
    )
    net_obj.Geometry.addObject(inline)

    junction_name, primary_name, inline_name = junction.Name, primary.Name, inline.Name

    net_proxy.removeGeometryObject(junction)

    assert doc.getObject(junction_name) is None
    assert doc.getObject(primary_name) is None
    assert doc.getObject(inline_name) is None
    assert net_obj.Geometry.OutList == []


class _ThroughNodeParser:
    """A single through/2-port node -- enough to drive DuctNetwork.syncJunctions
    end to end (nodes()/node_key()/build_junction_analysis()), unlike
    network_fixtures.FakeParser which only ever reports "end"/"branch"."""

    def nodes(self):
        return [0]

    def node_key(self, node_id):
        return "N0"

    def build_junction_analysis(self, node_id, segment_map):
        from freecad.HVAC.core.NetworkParser import JunctionAnalysis, JunctionPort

        ports = [
            JunctionPort(
                edge_key="A", segment_end="end", position=(0.0, 0.0, 0.0), direction=(-1.0, 0.0, 0.0),
                profile="Circular", section_params={"Diameter": 200.0}, attachment="Center",
                user_offset=(0.0, 0.0, 0.0), profile_x_axis=None,
                flow_role="inlet", flow_direction=(1.0, 0.0, 0.0), flow_into_junction=True,
            ),
            JunctionPort(
                edge_key="B", segment_end="start", position=(0.0, 0.0, 0.0), direction=(1.0, 0.0, 0.0),
                profile="Circular", section_params={"Diameter": 200.0}, attachment="Center",
                user_offset=(0.0, 0.0, 0.0), profile_x_axis=None,
                flow_role="outlet", flow_direction=(1.0, 0.0, 0.0), flow_into_junction=False,
            ),
        ]
        return JunctionAnalysis(
            topology="through", family="straight", family_tags=[], family_key="through.straight",
            flow_class="constant", qualifiers={}, derived_values={},
            connected_ports=ports, point=(0.0, 0.0, 0.0), degree=2, port_origins=[], edge_vectors=[],
            edge_angles={}, edge_eccentricities={}, collinear_pairs=[], orthogonal_pairs=[], is_coplanar=True,
        )


def test_repeated_sync_does_not_duplicate_the_primary_component():
    """
    Regression test: DuctNetwork.syncJunctions must look up a junction's
    existing components by the junction's own object Name (matching
    collectComponentObjects' ParentJunctionName-keyed dict), not by NodeKey
    -- a mismatch there meant every sync found no existing Primary and
    created a new one, without ever removing the old one. Left unfixed, two
    Primary components on an ordinary single-fitting junction wrongly makes
    it "eligible" for multi-component composition, feeding one of them
    synthetic axis-based ports as if it sat mid-chain.
    """
    doc, net_obj, net_proxy = _make_network()
    net_obj.Name = "Network0"
    # DuctNetwork.getDefaultLibraryId()'s fallback (no DefaultLibraryId set)
    # calls a module-level hvaclib.get_active_hvac_library() that doesn't
    # exist (a pre-existing, separate bug -- only
    # HVACLibraryService.get_active_hvac_library() does); sidestep it here
    # exactly like a real DuctNetwork's setProperties() already does by
    # seeding DefaultLibraryId when the object is created.
    net_obj.DefaultLibraryId = "smacna"
    parser = _ThroughNodeParser()

    net_proxy.syncJunctions(parser, initial_sync=False)
    net_proxy.syncJunctions(parser, initial_sync=False)
    net_proxy.syncJunctions(parser, initial_sync=False)

    junctions = [o for o in net_obj.Geometry.OutList if hvaclib.isDuctJunction(o)]
    assert len(junctions) == 1
    components = [o for o in net_obj.Geometry.OutList if hvaclib.isDuctComponent(o)]
    assert len(components) == 1
    assert components[0].ComponentRole == "Primary"


def _real_ports_json():
    return json.dumps({
        "connected_ports": [
            {
                "edge_key": "A", "segment_end": "end", "position": [0.0, 0.0, 0.0], "direction": [-1.0, 0.0, 0.0],
                "profile": "Circular", "section_params": {"Diameter": 300.0}, "attachment": "Center",
                "user_offset": [0.0, 0.0, 0.0], "profile_x_axis": None,
                "flow_role": "inlet", "flow_direction": [1.0, 0.0, 0.0], "flow_into_junction": True,
            },
            {
                "edge_key": "B", "segment_end": "start", "position": [0.0, 0.0, 0.0], "direction": [1.0, 0.0, 0.0],
                "profile": "Circular", "section_params": {"Diameter": 300.0}, "attachment": "Center",
                "user_offset": [0.0, 0.0, 0.0], "profile_x_axis": None,
                "flow_role": "outlet", "flow_direction": [1.0, 0.0, 0.0], "flow_into_junction": False,
            },
        ],
    })


def _run_full_sync_round(net_proxy, junction, lib):
    """Mimic one _runDeferredSync pass for a single junction: compose the
    chain, run each component's own execute() (standing in for a real
    FreeCAD recompute), then aggregate -- exactly the sequence
    Network.py's syncJunctionComponents + aggregateAllConnectionLengths
    drive in the real addon. connected_ports is derived from the SAME
    AnalysisJson composeComponents() itself reads (mirroring how
    syncJunctions() derives both from one shared JunctionAnalysis), so
    Inline retention (keyed on real edge_keys) stays consistent with it.
    """
    existing = junction.Proxy.getComponents()
    analysis = json.loads(getattr(junction, "AnalysisJson", "") or "{}")
    connected_ports = analysis.get("connected_ports") or [{"profile": "Circular", "edge_key": "A"}, {"profile": "Circular", "edge_key": "B"}]
    net_proxy.syncJunctionComponents(
        junction, "through", "through.straight", "Circular", connected_ports,
        existing_components=existing, default_lib=lib, hide_new=None,
    )
    for comp in junction.Proxy.getComponents():
        comp.Proxy.execute(comp)
    junction.Proxy.aggregateConnectionLengths()


def test_adding_inline_component_updates_aggregate_segment_trims():
    """
    Regression check for the "Add Inline Component" flow: after adding an
    Inline damper to an existing single-fitting through junction and
    re-running sync, the junction's aggregate ConnectionLengthsJson must
    still cover exactly the two real edges (A, B) -- and the trim on
    whichever side the damper landed on must grow to make room for the
    damper's own body, not stay exactly as it was with only the Primary.
    """
    doc, net_obj, net_proxy = _make_network()
    junction = _make_junction(doc, net_obj)
    junction.AnalysisJson = _real_ports_json()
    junction.ConnectedEdgeKeys = ["A", "B"]
    net_obj.Geometry.addObject(junction)
    lib = _smacna_library()

    # Primary only: sync, compose, execute, aggregate.
    _run_full_sync_round(net_proxy, junction, lib)
    primary = next(o for o in net_obj.Geometry.OutList if hvaclib.isDuctComponent(o))
    assert primary.TypeId == "through_straight_generic"

    lengths_before = {
        item["edge_key"]: item["length"] for item in json.loads(junction.ConnectionLengthsJson)
    }
    assert set(lengths_before.keys()) == {"A", "B"}

    # Add an Inline damper on edge B, exactly like CommandAddInlineComponent does.
    existing_chain = junction.Proxy.getInlineComponents("B")
    next_port_sequence = max((int(getattr(c, "PortSequence", 0)) for c in existing_chain), default=0) + 10
    inline = DuctComponent.create(
        doc, "{}_Comp{}".format(junction.Name, next_port_sequence),
        parent_junction=junction, role="Inline", attached_edge_key="B", port_sequence=next_port_sequence, owner_network=net_obj,
    )
    net_obj.Geometry.addObject(inline)
    inline.LibraryId = "smacna"
    inline.TypeId = "through_damper_generic"
    inline.Proxy.applyTypeSchema()

    # Resync (this is what requestSync(force_recompute=True) ultimately
    # drives): compose the now-2-component chain, execute each component,
    # aggregate.
    _run_full_sync_round(net_proxy, junction, lib)

    components = junction.Proxy.getComponents()
    assert [c.ComponentRole for c in components] == ["Primary", "Inline"]
    for comp in components:
        assert comp.Shape is not None

    lengths_after = {
        item["edge_key"]: item["length"] for item in json.loads(junction.ConnectionLengthsJson)
    }
    assert set(lengths_after.keys()) == {"A", "B"}

    # The damper is attached to edge B -- that side's aggregate trim must
    # grow to include the damper's own body length; the A side (still just
    # the Primary's own left face) is unaffected.
    assert lengths_after["A"] == pytest.approx(lengths_before["A"])
    assert lengths_after["B"] > lengths_before["B"]
