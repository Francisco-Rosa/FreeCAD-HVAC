# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the HVAC addon.

"""
Headless IFC round trip (ROADMAP design 6.8, owner answer (f)).

Builds a small supply network in FreeCAD (an AHU-side source, a run with an
elbow, a tee, a damper and two diffusers, insulated SMACNA ducts), calculates
it, exports it to IFC twice, reopens the files with ifcopenshell and checks:

- every duct and fitting is there with the right IFC class;
- GUIDs are the same in both exports;
- every element has its ports, and the ports are connected;
- one distribution system holds the elements;
- insulation layers are separate IfcCovering elements.

Run inside freecadcmd (FreeCAD's own Python), from the repository root:

    freecadcmd tools/ifc_roundtrip.py [output folder]

Prints a JSON summary and exits non-zero when a check fails.
"""

import json
import os
import sys
import traceback

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


def _use_this_checkout():
    """Make `freecad.HVAC` mean this checkout, not an installed copy (see geometry_smoke.py)."""
    # Draft (used by the BIM exporter) crashes freecadcmd when it is first
    # imported after the HVAC modules have loaded Qt, so load it first.
    import Draft  # noqa: F401
    import FreeCAD  # noqa: F401

    import freecad

    checkout = os.path.join(REPO_ROOT, "freecad")
    freecad.__path__ = [checkout] + [path for path in freecad.__path__ if path != checkout]
    for name in [name for name in sys.modules if name == "freecad.HVAC" or name.startswith("freecad.HVAC.")]:
        del sys.modules[name]


_use_this_checkout()

# The network module pulls in the task panels, which import MatGui, a GUI-only
# module that freecadcmd refuses to load. Nothing here opens a panel, so an
# empty stand-in is enough.
if "MatGui" not in sys.modules:
    import types

    sys.modules["MatGui"] = types.ModuleType("MatGui")


def _headless_view_providers():
    """Without a GUI objects have no ViewObject: make every HVAC view provider skip a missing one."""
    import importlib
    import inspect as _inspect

    for name in (
        "freecad.HVAC.ui.NetworkViewProvider",
        "freecad.HVAC.core.Segment",
        "freecad.HVAC.core.Junction",
        "freecad.HVAC.core.Component",
        "freecad.HVAC.core.Equipment",
    ):
        module = importlib.import_module(name)
        for _attr, cls in vars(module).items():
            if not (_inspect.isclass(cls) and cls.__name__.endswith("ViewProvider")):
                continue
            original = cls.__init__

            def patched(self, vobj, *args, _original=original, **kwargs):
                if vobj is None:
                    return
                _original(self, vobj, *args, **kwargs)

            cls.__init__ = patched

    # A sync is normally scheduled on the Qt event loop, which freecadcmd
    # does not run (a QTimer there crashes it). This script syncs by calling
    # _runDeferredSync() itself, so a request only records its flags.
    from freecad.HVAC.core.Network import DuctNetwork

    def request_sync(self, initial_sync=None, force_recompute=False, rebuild_all=False):
        if initial_sync is not None:
            self._initial_sync = bool(initial_sync)
        if rebuild_all:
            self._rebuild_all = True

    DuctNetwork.requestSync = request_sync


_headless_view_providers()

import FreeCAD  # noqa: E402
import Part  # noqa: E402


def _wire(doc, name, points):
    """A Draft Wire through `points` (mm)."""
    import Draft

    wire = Draft.make_wire([FreeCAD.Vector(*p) for p in points], closed=False, face=False)
    wire.Label = name
    return wire


def build_network(doc):
    """A supply network: source -- run with an elbow -- tee -- two diffuser ends."""
    from freecad.HVAC.core.Network import DuctNetwork

    net = doc.addObject("App::DocumentObjectGroupPython", "Supply")
    DuctNetwork(net)
    net.Label = "Supply 1"
    net.DefaultLibraryId = "smacna"
    doc.recompute()

    # Main run: source at the origin, elbow at (3000, 0), tee at (3000, 3000), end at (3000, 6000).
    main = _wire(doc, "Main", [(0, 0, 3000), (3000, 0, 3000), (3000, 3000, 3000), (3000, 6000, 3000)])
    branch = _wire(doc, "Branch", [(3000, 3000, 3000), (6000, 3000, 3000)])
    doc.recompute()
    for wire in (main, branch):
        net.Proxy.addBaseObject(wire)
    net.Proxy._runDeferredSync(force_recompute=True)
    net.Proxy._runDeferredSync(force_recompute=True)
    return net


def configure(net):
    """Insulate the ducts, put a damper on the branch and set the terminal flows."""
    doc = net.Document
    for seg in net.Proxy.collectSegmentObjects().values():
        seg.Diameter = 315.0
        if hasattr(seg, "InsulationThickness"):
            seg.InsulationThickness = 25.0
    junctions = net.Proxy.collectJunctionObjects()
    ends = [j for j in junctions.values() if j.Topology == "end"]
    # The end at the origin is the source (Auto); the other two are diffusers at 150 L/s.
    for junction in ends:
        at_origin = abs(junction.CenterPoint.x) < 1.0 and abs(junction.CenterPoint.y) < 1.0
        junction.FlowBoundary = "Auto" if at_origin else "Fixed"
        if not at_origin:
            junction.DesignFlowRate = 150.0
    doc.recompute()
    net.Proxy._runDeferredSync(force_recompute=True)

    # A damper on the branch leg of the tee.
    from freecad.HVAC.core.Network import DuctNetwork

    tee = next(j for j in junctions.values() if j.Topology == "branch")
    branch_edge = None
    for key in tee.ConnectedEdgeKeys:
        seg = net.Proxy.collectSegmentObjects().get(key)
        if seg is not None and doc.getObject(seg.SourceObjectName).Label == "Branch":
            branch_edge = key
    if branch_edge:
        DuctNetwork.applyAddInlineComponent(tee, branch_edge, "smacna", "through_damper_generic")
    for junction in ends:
        if abs(junction.CenterPoint.x) >= 1.0 or abs(junction.CenterPoint.y) >= 1.0:
            DuctNetwork.applyTypeSelection([junction], library_id="smacna", type_id="end_diffuser_round")
    net.Proxy._runDeferredSync(force_recompute=True)
    net.Proxy._runDeferredSync(force_recompute=True)

    from freecad.HVAC.core.AirflowSolver import AirflowSolver

    return AirflowSolver(net).solve()


def inspect(path):
    import ifcopenshell

    f = ifcopenshell.open(path)
    elements = {}
    for cls in ("IfcDuctSegment", "IfcDuctFitting", "IfcAirTerminal", "IfcDamper"):
        for e in f.by_type(cls):
            elements[e.GlobalId] = (cls, e.Name, getattr(e, "PredefinedType", None))
    ports = f.by_type("IfcDistributionPort")
    nests = {}
    for rel in f.by_type("IfcRelNests"):
        nests[rel.RelatingObject.GlobalId] = len(rel.RelatedObjects)
    connections = f.by_type("IfcRelConnectsPorts")

    # Connected ports must sit at the same point and face each other.
    import ifcopenshell.util.placement
    import numpy

    gaps, facing = [], []
    for rel in connections:
        a = ifcopenshell.util.placement.get_local_placement(rel.RelatingPort.ObjectPlacement)
        b = ifcopenshell.util.placement.get_local_placement(rel.RelatedPort.ObjectPlacement)
        gaps.append(float(numpy.linalg.norm(a[:3, 3] - b[:3, 3])))
        facing.append(float(numpy.dot(a[:3, 2], b[:3, 2])))
    systems = [(s.Name, s.LongName, s.PredefinedType) for s in f.by_type("IfcDistributionSystem")]
    groups = [len(r.RelatedObjects) for r in f.by_type("IfcRelAssignsToGroup")]
    coverings = [(c.Name, c.PredefinedType, c.ObjectType) for c in f.by_type("IfcCovering")]
    covers = sum(len(r.RelatedCoverings) for r in f.by_type("IfcRelCoversBldgElements"))
    types = [(t.is_a(), t.Name, t.PredefinedType) for t in f.by_type("IfcTypeObject")]
    storeys = {}
    for rel in f.by_type("IfcRelContainedInSpatialStructure"):
        for e in rel.RelatedElements:
            storeys.setdefault(rel.RelatingStructure.Name, set()).add(e.is_a())
    proxies = len(f.by_type("IfcBuildingElementProxy"))
    return {
        "elements": elements,
        "ports": len(ports),
        "nests": nests,
        "connections": len(connections),
        "systems": systems,
        "groups": groups,
        "coverings": coverings,
        "covers": covers,
        "types": types,
        "proxies": proxies,
        "storeys": {k: sorted(v) for k, v in storeys.items()},
        "flow_directions": sorted({p.FlowDirection for p in ports}),
        "max_port_gap": max(gaps) if gaps else None,
        "max_axis_dot": max(facing) if facing else None,
    }


def main(argv):
    out_dir = argv[1] if len(argv) > 1 else os.path.join(REPO_ROOT, "tools", ".smoke")
    os.makedirs(out_dir, exist_ok=True)
    doc = FreeCAD.newDocument("IfcRoundTrip")
    net = build_network(doc)
    result = configure(net)

    # A BIM storey for the network's Level.
    import Arch

    # What the BIM Level tool makes: a BuildingPart of IFC type Building Storey.
    level = Arch.makeBuildingPart()
    level.IfcType = "Building Storey"
    level.Label = "Level 2"
    level.Placement.Base.z = 3000.0
    doc.recompute()
    net.Level = level

    from freecad.HVAC.ifc.export import export_networks

    paths = [os.path.join(out_dir, "ifc_roundtrip_{}.ifc".format(i)) for i in (1, 2)]
    reports = [export_networks([net], path) for path in paths]
    first, second = inspect(paths[0]), inspect(paths[1])

    failures = []
    classes = sorted({v[0] for v in first["elements"].values()})
    for wanted in ("IfcDuctSegment", "IfcDuctFitting", "IfcAirTerminal", "IfcDamper"):
        if wanted not in classes:
            failures.append("no {} in the file".format(wanted))
    if first["proxies"]:
        failures.append("{} IfcBuildingElementProxy elements".format(first["proxies"]))
    if set(first["elements"]) != set(second["elements"]):
        failures.append("GUIDs differ between the two exports")
    for guid in first["elements"]:
        if first["nests"].get(guid, 0) == 0:
            failures.append("element {} has no ports".format(first["elements"][guid][1]))
    if first["connections"] < len(first["elements"]) - 1:
        failures.append("only {} port connections for {} elements".format(first["connections"], len(first["elements"])))
    if len(first["systems"]) != 1 or first["groups"] != [len(first["elements"])]:
        failures.append("system membership wrong: {} {}".format(first["systems"], first["groups"]))
    if not first["coverings"] or first["covers"] != len(first["coverings"]):
        failures.append("insulation coverings missing: {}".format(first["coverings"]))
    if first["max_port_gap"] is None or first["max_port_gap"] > 0.001:
        failures.append("connected ports more than 1 mm apart: {}".format(first["max_port_gap"]))
    if first["max_axis_dot"] is None or first["max_axis_dot"] > -0.99:
        failures.append("connected ports do not face each other: {}".format(first["max_axis_dot"]))
    if "IfcDuctSegment" not in first["storeys"].get("Level 2", []) or "IfcCovering" not in first["storeys"].get(
        "Level 2", []
    ):
        failures.append("elements not in the network's Level: {}".format(first["storeys"]))
    if "SOURCE" not in first["flow_directions"] or "SINK" not in first["flow_directions"]:
        failures.append("flow directions not set: {}".format(first["flow_directions"]))

    summary = {
        "airflow_warnings": result.warnings,
        "report": {k: v for k, v in vars(reports[0]).items()},
        "first": {k: (v if k != "elements" else sorted(set(map(str, v.values())))) for k, v in first.items()},
        "failures": failures,
    }
    print(json.dumps(summary, indent=1, default=str))
    return 1 if failures else 0


if __name__ == "__main__":
    try:
        code = main(sys.argv)
    except Exception:
        traceback.print_exc()
        code = 2
    print("EXIT", code)
