# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the HVAC addon.

"""
HVAC equipment joining several networks (ROADMAP 6.5): an AHU with a
supply outlet and a return inlet, a fan with an intake and a discharge.

The equipment is the user's model itself: an App::Part holding the modelled
unit and one port marker per connection (the same
`Part::LocalCoordinateSystem` markers custom fittings use, see
core/_custom_fitting.py), each with an `EquipmentPortFunction`. "Create Custom
Equipment" adds the equipment properties to that App::Part, so selecting
the equipment selects its geometry and markers, and the ports sit directly
in it. (Documents from before keep a separate equipment object that links
its App::Part through `Model`; model_of() reads both.) A port is connected to one terminal of one
network, automatically, when the network's base geometry has a duct end on
the port (DuctNetwork.autoAttach, core/_auto_attach.py): routing the duct to
the port is the connection. That terminal becomes the network's
balancing terminal (its Source) and gets the `end_equipment_connection`
type, a collar carrying the fan-connection loss.

Each network is still solved on its own. After a network's airflow
calculation the equipment collects, per port, the flow and the worst path
of that network, and sums them up (`equipment_summary`).
"""

import json

import FreeCAD

from . import _auto_attach, _custom_fitting

PORT_FUNCTIONS = ["SupplyOutlet", "ReturnInlet", "OutdoorAirInlet", "ExhaustOutlet"]
# The system a network connected to each kind of port should be.
PORT_SYSTEM = {
    "SupplyOutlet": "Supply",
    "ReturnInlet": "Return",
    "OutdoorAirInlet": "OutdoorAir",
    "ExhaustOutlet": "Exhaust",
}
CONNECTION_TYPE_ID = "end_equipment_connection"
POSITION_TOLERANCE_MM = 1.0


# ----------------------------------------------------------------------------
# Pure summary
# ----------------------------------------------------------------------------


def equipment_summary(port_results, internal_pressure_drop_pa=0.0):
    """
    Totals over an equipment's ports. `port_results` is a list of dicts
    with "function", "flow_lps" and "worst_path_pa" (None when that
    network has no result yet). Returns:

        {"supply_lps", "return_lps", "outdoor_air_lps", "exhaust_lps",
         "outdoor_air_is_estimate", "supply_fan_pa", "return_fan_pa"}

    Outdoor air is the outdoor-air ports' own flow, or (no such port)
    supply minus return when the unit has both. The supply fan works
    against the unit's internal drop plus the worst supply path and the
    worst outdoor-air path; a return or exhaust fan against the worst
    return path plus the worst exhaust path. Fan figures are None until a
    supply (or return) network has been calculated.
    """

    def total(function):
        values = [r["flow_lps"] for r in port_results if r["function"] == function and r.get("flow_lps") is not None]
        return sum(values) if values else None

    def worst(function):
        values = [
            r["worst_path_pa"] for r in port_results if r["function"] == function and r.get("worst_path_pa") is not None
        ]
        return max(values) if values else None

    supply, ret = total("SupplyOutlet"), total("ReturnInlet")
    outdoor, exhaust = total("OutdoorAirInlet"), total("ExhaustOutlet")
    estimate = False
    if outdoor is None and supply is not None and ret is not None:
        outdoor, estimate = supply - ret, True

    supply_fan = None
    if worst("SupplyOutlet") is not None:
        supply_fan = float(internal_pressure_drop_pa or 0.0) + worst("SupplyOutlet") + (worst("OutdoorAirInlet") or 0.0)
    return_fan = None
    if worst("ReturnInlet") is not None or worst("ExhaustOutlet") is not None:
        return_fan = (worst("ReturnInlet") or 0.0) + (worst("ExhaustOutlet") or 0.0)
    return {
        "supply_lps": supply,
        "return_lps": ret,
        "outdoor_air_lps": outdoor,
        "exhaust_lps": exhaust,
        "outdoor_air_is_estimate": estimate,
        "supply_fan_pa": supply_fan,
        "return_fan_pa": return_fan,
    }


def report_lines(port_results, summary):
    """Human-readable report: one line per port, then the totals."""

    def fmt(value, unit):
        return "-" if value is None else "{:.1f} {}".format(value, unit)

    lines = [
        "{} ({}, network {}): {}, worst path {}".format(
            r["function"],
            r["port"],
            r.get("network") or "-",
            fmt(r.get("flow_lps"), "L/s"),
            fmt(r.get("worst_path_pa"), "Pa"),
        )
        for r in port_results
    ]
    lines.append(
        "Supply {}, return {}, outdoor air {}{}".format(
            fmt(summary["supply_lps"], "L/s"),
            fmt(summary["return_lps"], "L/s"),
            fmt(summary["outdoor_air_lps"], "L/s"),
            " (supply minus return)" if summary["outdoor_air_is_estimate"] else "",
        )
    )
    lines.append(
        "Supply fan static {}, return / exhaust fan static {}".format(
            fmt(summary["supply_fan_pa"], "Pa"), fmt(summary["return_fan_pa"], "Pa")
        )
    )
    return lines


# ----------------------------------------------------------------------------
# The document object
# ----------------------------------------------------------------------------


class HVACEquipment:
    """
    A unit (AHU, fan) whose ports feed terminals of one or more networks.

    New equipment is an App::Part carrying the properties of setProperties()
    (make_equipment); this proxy class is kept so documents with the older,
    separate equipment object still load.
    """

    TYPE = "HVACEquipment"

    def __init__(self, obj):
        obj.Proxy = self
        self.Object = obj
        self.setProperties(obj)

    def onDocumentRestored(self, obj):
        obj.Proxy = self
        self.Object = obj
        self.setProperties(obj)

    def dumps(self):
        return None

    def loads(self, state):
        pass

    def execute(self, obj):
        pass

    @staticmethod
    def setProperties(obj):
        def add(prop_type, name, group, description, mode=0):
            if name not in obj.PropertiesList:
                obj.addProperty(prop_type, name, group, description)
            try:
                obj.setEditorMode(name, mode)
            except Exception:
                pass

        add("App::PropertyString", "EquipmentType", "HVAC", "Internal: marks an HVAC equipment object", 2)
        if getattr(obj, "EquipmentType", "") != HVACEquipment.TYPE:
            obj.EquipmentType = HVACEquipment.TYPE
        add(
            "App::PropertyFloat",
            "InternalPressureDrop",
            "HVAC Equipment",
            "Pressure drop inside the unit at design flow, in Pa (coils, filters, casing); added to the supply fan's duty",
        )
        add(
            "App::PropertyStringList",
            "Connections",
            "HVAC",
            "Internal: one 'port marker name|network name|node key' entry per connected port",
            2,
        )
        add("App::PropertyString", "PortResultsJson", "HVAC", "Internal: per-port results of the last calculations", 2)
        for name, description in (
            ("SupplyAirflow", "Total supply airflow, L/s (last calculation)"),
            ("ReturnAirflow", "Total return airflow, L/s"),
            ("OutdoorAirflow", "Outdoor airflow, L/s: the outdoor-air ports, or supply minus return"),
            ("SupplyFanStatic", "Supply fan static pressure, Pa: internal drop + worst supply and outdoor-air paths"),
            ("ReturnFanStatic", "Return / exhaust fan static pressure, Pa: worst return and exhaust paths"),
        ):
            add("App::PropertyFloat", name, "HVAC Results", description, 1)
        add(
            "App::PropertyStringList",
            "Report",
            "HVAC Results",
            "Per-port flows and fan duties from the last calculations",
            1,
        )


def is_equipment(obj):
    return getattr(obj, "EquipmentType", "") == HVACEquipment.TYPE


def make_equipment(part):
    """
    Turn an App::Part (the modelled unit) into HVAC equipment: add the
    equipment properties to it and give every port marker already in it an
    EquipmentPortFunction. Safe to call again. Returns the part.
    """
    HVACEquipment.setProperties(part)
    for marker in _custom_fitting.container_ports(part):
        ensure_equipment_port(marker)
    return part


def create_equipment(doc, model=None, name="Equipment"):
    """Equipment from `model` (an App::Part), or from a new empty App::Part named `name`."""
    if model is None:
        model = doc.addObject("App::Part", name)
    return make_equipment(model)


def library_models():
    """
    Every equipment model of every loaded library (library/equipment_library.py),
    sorted by label. A definition that does not load is reported on the console.
    """
    from ..library import equipment_library
    from ..utils import hvaclib

    registry = hvaclib.HVACLibraryService.get_hvac_library_registry()
    models = []
    for library in registry.list_libraries():
        found, errors = equipment_library.load_models(library.id, library.root_path)
        models.extend(found)
        for error in errors:
            FreeCAD.Console.PrintWarning("HVAC - Equipment model not loaded: {}\n".format(error))
    return sorted(models, key=lambda model: model.label)


def _face_at(shape, position, direction, tolerance=0.01):
    """Name of the planar face of `shape` centred on `position` and facing `direction`, or None."""
    position = FreeCAD.Vector(*position)
    direction = FreeCAD.Vector(*direction)
    for index, face in enumerate(shape.Faces):
        if face.Surface.TypeId != "Part::GeomPlane":
            continue
        if (face.CenterOfMass - position).Length > tolerance:
            continue
        u, v = face.Surface.parameter(face.CenterOfMass)
        if face.normalAt(u, v).dot(direction) > 0.999:
            return "Face{}".format(index + 1)
    return None


def create_from_model(doc, model, values=None, position=None):
    """
    Place a library equipment model in `doc` as HVAC equipment: an App::Part
    holding the unit's body (a plain solid: change a size by adding the
    model again) and one port per connection, each with its function and its
    snap point, markers hidden. `values` overrides the model's property
    defaults; `position` moves the unit. Returns the App::Part; raises
    ValueError when the values are not accepted or the model does not build.
    """
    from ..library import equipment_library
    from ..library.library_api import HVACLibraryAPI
    from ..utils import hvaclib

    resolved = equipment_library.resolve_values(model, values)
    registry = hvaclib.HVACLibraryService.get_hvac_library_registry()
    function = getattr(registry.import_generator(model.library_id, model.module), model.function, None)
    if function is None:
        raise ValueError(
            "Equipment model '{}': no function '{}' in '{}'".format(model.id, model.function, model.module)
        )
    result = function(HVACLibraryAPI, resolved)
    shape = result["shape"]
    check = HVACLibraryAPI.validate(shape, require_solid=True)
    if not check["valid"] or check["solid_count"] != 1:
        raise ValueError("Equipment model '{}' did not build one valid solid with these sizes".format(model.id))

    part = doc.addObject("App::Part", "Equipment")
    part.Label = model.label
    body = doc.addObject("Part::Feature", "EquipmentBody")
    body.Label = "{} body".format(model.label)
    body.Shape = shape
    part.addObject(body)
    make_equipment(part)
    part.addProperty("App::PropertyString", "EquipmentModel", "HVAC Equipment", "Library model this unit was made from")
    part.EquipmentModel = "{}/{}".format(model.library_id, model.id)
    part.setEditorMode("EquipmentModel", 1)
    part.InternalPressureDrop = float(result.get("internal_pressure_drop", 0.0) or 0.0)

    for port in result["ports"]:
        face_name = _face_at(shape, port["position"], port["direction"])
        if face_name is None:
            raise ValueError("Equipment model '{}': port '{}' is not on an end face".format(model.id, port["name"]))
        marker = _custom_fitting.add_port(body, face_name, container=part, name=port["name"])
        ensure_equipment_port(marker, port["function"])
        _custom_fitting.ensure_snap_point(marker)
        _custom_fitting.hide_port(marker)
    if position is not None:
        part.Placement = FreeCAD.Placement(FreeCAD.Vector(*position), FreeCAD.Rotation())
    return part


def model_of(equipment):
    """The App::Part holding an equipment's geometry and ports: the equipment itself, or an older object's Model."""
    model = getattr(equipment, "Model", None)
    return model if model is not None else equipment


def equipment_ports(equipment):
    """An equipment's port markers, in a stable order."""
    return _custom_fitting.container_ports(model_of(equipment))


def equipment_of_marker(marker):
    """The equipment a port marker belongs to, or None."""
    doc = getattr(marker, "Document", None)
    if doc is None:
        return None
    for obj in doc.Objects:
        if is_equipment(obj) and marker in equipment_ports(obj):
            return obj
    return None


class HVACEquipmentViewProvider:
    def __init__(self, vobj):
        vobj.Proxy = self

    def attach(self, vobj):
        self.Object = vobj.Object

    def dumps(self):
        return None

    def loads(self, state):
        pass

    def claimChildren(self):
        obj = getattr(self, "Object", None)
        model = getattr(obj, "Model", None) if obj is not None else None
        return [model] if model is not None else []

    def getIcon(self):
        from ..utils import hvaclib

        return hvaclib.get_icon_path("DuctsIcon.svg")


# ----------------------------------------------------------------------------
# Port markers and connections
# ----------------------------------------------------------------------------


def ensure_equipment_port(lcs, function=None):
    """Give a port marker its EquipmentPortFunction (and the ordinary port properties)."""
    _custom_fitting.ensure_port_properties(lcs)
    if "EquipmentPortFunction" not in lcs.PropertiesList:
        lcs.addProperty(
            "App::PropertyEnumeration",
            "EquipmentPortFunction",
            _custom_fitting.PORT_GROUP,
            "What this equipment port does: SupplyOutlet, ReturnInlet, OutdoorAirInlet or ExhaustOutlet",
        )
        lcs.EquipmentPortFunction = list(PORT_FUNCTIONS)
        lcs.EquipmentPortFunction = "SupplyOutlet"
    if function:
        lcs.EquipmentPortFunction = function


def _parse_connections(equipment):
    out = []
    for entry in list(getattr(equipment, "Connections", []) or []):
        connection = _auto_attach.parse_connection(entry)
        if connection is not None:
            out.append(connection)
    return out


def connections_of(equipment):
    """An equipment's connections: [{"port": marker name, "network": network name, "node_key": ...}, ...]."""
    return _parse_connections(equipment)


def _write_connections(equipment, connections):
    equipment.Connections = ["{}|{}|{}".format(c["port"], c["network"], c["node_key"]) for c in connections]


def connect(equipment, port_marker, junction):
    """
    Connect an equipment port (one of its port markers) to a network
    terminal. The terminal becomes the network's Source: FlowBoundary Auto,
    TerminalFunction Auto, its fitting the equipment connection collar.
    Returns a list of warnings (position or system mismatches); raises
    ValueError when the pieces cannot be connected at all.
    """
    from ..utils import hvaclib
    from .Network import DuctNetwork

    if port_marker not in equipment_ports(equipment):
        raise ValueError("'{}' is not a port marker of equipment '{}'".format(port_marker.Label, equipment.Label))
    if not hvaclib.isDuctJunction(junction) or getattr(junction, "Topology", "") != "end":
        raise ValueError("Pick an open duct end (a terminal node) to connect")
    net = DuctNetwork.getOwnerNetwork(junction)
    if net is None:
        raise ValueError("The terminal belongs to no network")
    ensure_equipment_port(port_marker)

    warnings = []
    offset = (FreeCAD.Vector(junction.CenterPoint) - port_marker.getGlobalPlacement().Base).Length
    if offset > POSITION_TOLERANCE_MM:
        warnings.append(
            "The duct end is {:.1f} mm from port '{}': move the base geometry's end point onto the port".format(
                offset, port_marker.Label
            )
        )
    wanted = PORT_SYSTEM.get(str(port_marker.EquipmentPortFunction), "")
    if wanted and str(getattr(net, "SystemType", "")) != wanted:
        warnings.append(
            "Port '{}' is a {} but network '{}' is a {} system".format(
                port_marker.Label, port_marker.EquipmentPortFunction, net.Label, getattr(net, "SystemType", "?")
            )
        )

    node_key = str(getattr(junction, "NodeKey", ""))
    connections = [
        c
        for c in _parse_connections(equipment)
        if c["port"] != port_marker.Name and not (c["network"] == net.Name and c["node_key"] == node_key)
    ]
    connections.append({"port": port_marker.Name, "network": net.Name, "node_key": node_key})
    _write_connections(equipment, connections)

    if str(getattr(junction, "FlowBoundary", "Auto")) != "Auto":
        junction.FlowBoundary = "Auto"
    if str(getattr(junction, "TerminalFunction", "Auto")) != "Auto":
        junction.TerminalFunction = "Auto"
    primary = junction.Proxy.getPrimaryComponent()
    library_id = getattr(primary, "LibraryId", "") if primary is not None else ""
    library_id = library_id or getattr(net, "DefaultLibraryId", "")
    reg = hvaclib.HVACLibraryService.get_hvac_library_registry()
    if reg.resolve_type(library_id, CONNECTION_TYPE_ID) is None:
        warnings.append(
            "Library '{}' has no {} type; the builtin_basic one is used".format(library_id, CONNECTION_TYPE_ID)
        )
        library_id = "builtin_basic"
    DuctNetwork.applyTypeSelection([junction], library_id=library_id, type_id=CONNECTION_TYPE_ID)
    return warnings


def is_connected(equipment, port_marker, net, junction):
    """True when `port_marker` is already connected to `junction` of `net`."""
    node_key = str(getattr(junction, "NodeKey", ""))
    return any(
        c["port"] == port_marker.Name and c["network"] == net.Name and c["node_key"] == node_key
        for c in _parse_connections(equipment)
    )


def connected_port(junction):
    """
    The equipment port marker an open duct end (a DuctJunction) is
    connected to, or None.
    """
    from .Network import DuctNetwork

    net = DuctNetwork.getOwnerNetwork(junction)
    doc = getattr(junction, "Document", None)
    if net is None or doc is None:
        return None
    node_key = str(getattr(junction, "NodeKey", "") or "")
    for equipment in equipment_for_network(net):
        for c in _parse_connections(equipment):
            if c["network"] == net.Name and c["node_key"] == node_key:
                return doc.getObject(c["port"])
    return None


def port_context(component):
    """
    The equipment port a Primary component's end is connected to, as the
    library's context key "equipment_port": a port-like dict ({"profile",
    "section_params", "profile_x_axis", "position"}, read off the port marker, which
    takes them from the equipment's collar face), or None when the
    component is not on an end connected to an equipment port.
    """
    if getattr(component, "ComponentRole", "") != "Primary":
        return None
    doc = getattr(component, "Document", None)
    junction = doc.getObject(getattr(component, "ParentJunctionName", "") or "") if doc is not None else None
    if junction is None or getattr(junction, "Topology", "") != "end":
        return None
    marker = connected_port(junction)
    if marker is None or not _custom_fitting.is_port(marker):
        return None
    profile, section = _custom_fitting.port_section(marker)
    placement = marker.getGlobalPlacement()
    x_axis = placement.Rotation.multVec(FreeCAD.Vector(1, 0, 0))
    # The marker's centre: where the duct actually meets the port, which an
    # Attachment / Offset on the duct can move off the duct's own axis.
    centre = placement.Base
    return {
        "profile": profile,
        "section_params": section,
        "profile_x_axis": (x_axis.x, x_axis.y, x_axis.z),
        "position": (centre.x, centre.y, centre.z),
    }


def prune_connections(equipment, network_name, live_node_keys):
    """
    Drop `equipment`'s connections to nodes of network `network_name` that
    no longer exist (a duct end moved off the port). Returns True when any
    was dropped.
    """
    entries = list(getattr(equipment, "Connections", []) or [])
    keep = _auto_attach.live_connections(entries, network_name, live_node_keys)
    if keep == entries:
        return False
    equipment.Connections = keep
    return True


def equipment_for_network(net):
    """The equipment objects with at least one port connected to `net`."""
    doc = getattr(net, "Document", None)
    if doc is None:
        return []
    return [
        obj
        for obj in getattr(doc, "Objects", [])
        if is_equipment(obj) and any(c["network"] == net.Name for c in _parse_connections(obj))
    ]


def update_from_airflow(net, result):
    """
    After `net`'s airflow calculation (an AirflowSolveResult): store, for
    every equipment port connected to it, the terminal's flow and the
    network's worst path, then refresh the equipment's totals and report.
    Ports on other networks keep their last values.
    """
    junctions = net.Proxy.collectJunctionObjects()
    for equipment in equipment_for_network(net):
        try:
            stored = json.loads(getattr(equipment, "PortResultsJson", "") or "{}")
        except ValueError:
            stored = {}
        doc = equipment.Document
        for connection in _parse_connections(equipment):
            marker = doc.getObject(connection["port"])
            if marker is None:
                continue
            entry = {
                "port": marker.Label,
                "function": str(getattr(marker, "EquipmentPortFunction", "") or "SupplyOutlet"),
                "network": connection["network"],
                "flow_lps": None,
                "worst_path_pa": None,
            }
            if connection["network"] == net.Name:
                junction = junctions.get(connection["node_key"])
                for component in result.components:
                    match = next((j for j in component.junctions if j.obj is junction), None) if junction else None
                    if match is not None:
                        entry["flow_lps"] = float(match.total_flow_lps)
                        entry["worst_path_pa"] = float(component.critical_pressure_pa)
                        break
            else:
                entry = dict(stored.get(connection["port"], entry), port=marker.Label, function=entry["function"])
            stored[connection["port"]] = entry
        port_results = [stored[c["port"]] for c in _parse_connections(equipment) if c["port"] in stored]
        summary = equipment_summary(port_results, float(getattr(equipment, "InternalPressureDrop", 0.0) or 0.0))
        equipment.PortResultsJson = json.dumps(stored, sort_keys=True)
        equipment.SupplyAirflow = summary["supply_lps"] or 0.0
        equipment.ReturnAirflow = summary["return_lps"] or 0.0
        equipment.OutdoorAirflow = summary["outdoor_air_lps"] or 0.0
        equipment.SupplyFanStatic = summary["supply_fan_pa"] or 0.0
        equipment.ReturnFanStatic = summary["return_fan_pa"] or 0.0
        equipment.Report = report_lines(port_results, summary)
