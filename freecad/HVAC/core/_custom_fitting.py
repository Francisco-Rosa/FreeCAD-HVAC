# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the HVAC addon.

"""
Custom fittings (ROADMAP 6.3), FreeCAD side.

A custom fitting is an `App::Part` holding the user's fully modelled fitting
(walls included) and one port marker per opening: a
`Part::LocalCoordinateSystem` whose origin is the centre of the opening
(moved by an optional X/Y offset in the face), Z points out of the fitting
and X along the width of a rectangular or oval opening, carrying the port's
profile and clear-air size as dynamic properties (group "HVAC Port").
`add_port()` makes one from a selected end face. The same markers, in the
same kind of App::Part, are an HVAC equipment's ports (core/Equipment.py),
so every helper here works on either container.

A Primary `DuctComponent` with `GeometrySource = Custom` and
`CustomFitting` set to that container takes its geometry from it, in one of
two ways (`CustomPlacement`):

- "Fit to node": the component owns an `App::Link` to the container. Every
  execute fits the container onto the node (library/custom_fitting.py),
  moves the link there, and reports each duct's trim as the distance from
  the node to its port, so the ducts end exactly at the port faces.
- "In place": the container stays where it was modelled and is itself the
  geometry (no link). The ducts were drawn to end on its ports, so each
  trim is only the distance from a duct's end to its port (normally 0).

A container made with make_custom_fitting() is attached "In place"
automatically when a network's ducts end on its ports (core/_auto_attach.py,
DuctNetwork.autoAttach): the ends on one container become one junction.
"""

import json

import FreeCAD
import Part

from ..library import custom_fitting as fit_math
from ..library.library_api import HVACLibraryAPI

PORT_GROUP = "HVAC Port"
PORT_PROFILES = ["Circular", "Rectangular", "Oval"]
CUSTOM_FITTING_TYPE = "HVACCustomFitting"
PLACEMENT_FIT = "Fit to node"
PLACEMENT_IN_PLACE = "In place"
PLACEMENTS = [PLACEMENT_FIT, PLACEMENT_IN_PLACE]


# ----------------------------------------------------------------------------
# Custom fitting containers
# ----------------------------------------------------------------------------


def make_custom_fitting(part):
    """
    Mark an App::Part as a custom fitting, so ducts drawn to its ports
    attach to it automatically. Safe to call again. Returns the part.
    """
    if "CustomFittingType" not in part.PropertiesList:
        part.addProperty("App::PropertyString", "CustomFittingType", "HVAC", "Internal: marks an HVAC custom fitting")
        try:
            part.setEditorMode("CustomFittingType", 2)
        except Exception:
            pass
    if part.CustomFittingType != CUSTOM_FITTING_TYPE:
        part.CustomFittingType = CUSTOM_FITTING_TYPE
    return part


def is_custom_fitting(obj):
    return getattr(obj, "CustomFittingType", "") == CUSTOM_FITTING_TYPE


def attach_in_place(comp_obj, container):
    """
    Give a junction's Primary component `container`'s geometry, in place
    (the automatic attachment of ducts drawn to its ports). Done once per
    container: a later change the user makes to the component is kept.
    Returns True when something changed.
    """
    if comp_obj is None or "GeometrySource" not in comp_obj.PropertiesList:
        return False
    if getattr(comp_obj, "AutoAttachedTo", "") == container.Name:
        return False
    comp_obj.AutoAttachedTo = container.Name
    comp_obj.CustomFitting = container
    comp_obj.CustomPlacement = PLACEMENT_IN_PLACE
    comp_obj.GeometrySource = "Custom"
    return True


# ----------------------------------------------------------------------------
# Port markers
# ----------------------------------------------------------------------------


def is_port(obj):
    return obj is not None and "PortProfile" in getattr(obj, "PropertiesList", [])


def ensure_port_properties(lcs):
    """Add the HVAC port properties to a coordinate system (idempotent)."""
    if "PortProfile" not in lcs.PropertiesList:
        lcs.addProperty("App::PropertyEnumeration", "PortProfile", PORT_GROUP, "Profile of the opening")
        lcs.PortProfile = PORT_PROFILES
        lcs.PortProfile = "Circular"
    for name, description in (
        ("PortDiameter", "Clear-air diameter of a round opening"),
        ("PortWidth", "Clear-air width of a rectangular or oval opening, along the marker's X axis"),
        ("PortHeight", "Clear-air height of a rectangular or oval opening"),
    ):
        if name not in lcs.PropertiesList:
            lcs.addProperty("App::PropertyLength", name, PORT_GROUP, description)
    if "PortName" not in lcs.PropertiesList:
        lcs.addProperty("App::PropertyString", "PortName", PORT_GROUP, "Optional name shown in messages")
    # Where the port sits relative to the centre of the opening it was made on, in the face's own X/Y.
    # Read-only here: the port panel (or set_port_offset) moves the marker and updates both together.
    for name, description in (
        ("PortOffsetX", "Offset of the port from the centre of its face, along the marker's X axis"),
        ("PortOffsetY", "Offset of the port from the centre of its face, along the marker's Y axis"),
    ):
        if name not in lcs.PropertiesList:
            lcs.addProperty("App::PropertyDistance", name, PORT_GROUP, description)
            lcs.setEditorMode(name, 1)


def show_port(lcs):
    """Make a marker visible, so the user sees where the port went (FreeCAD creates them hidden)."""
    view = getattr(lcs, "ViewObject", None)
    if view is not None:
        try:
            view.Visibility = True
        except Exception:
            pass


def set_port_offset(lcs, offset_x, offset_y):
    """
    Move a marker to (offset_x, offset_y) from the centre of its face, in
    the marker's own X/Y (the face plane). The marker stays attached to the
    face; only its attachment offset changes, by the difference from the
    offset it had.
    """
    ensure_port_properties(lcs)
    dx = float(offset_x) - float(lcs.PortOffsetX)
    dy = float(offset_y) - float(lcs.PortOffsetY)
    if abs(dx) > 1.0e-9 or abs(dy) > 1.0e-9:
        lcs.AttachmentOffset = lcs.AttachmentOffset.multiply(
            FreeCAD.Placement(FreeCAD.Vector(dx, dy, 0.0), FreeCAD.Rotation())
        )
    lcs.PortOffsetX = float(offset_x)
    lcs.PortOffsetY = float(offset_y)


def hide_port(lcs):
    """Hide a marker again (the port panel shows them only while it is open)."""
    view = getattr(lcs, "ViewObject", None)
    if view is not None:
        try:
            view.Visibility = False
        except Exception:
            pass


SNAP_POINT_PROPERTY = "SnapPointName"
SNAP_POINT_COLOR = (1.0, 0.5, 0.0)


def snap_point(lcs):
    """The snap point object of a port marker, or None."""
    name = str(getattr(lcs, SNAP_POINT_PROPERTY, "") or "")
    doc = getattr(lcs, "Document", None)
    return doc.getObject(name) if name and doc is not None else None


def ensure_snap_point(lcs):
    """
    A Part::Vertex at the port's centre, in the same App::Part as the marker
    and attached to it (so it follows the marker when the port is moved), so
    Draft can snap a duct end onto the port: a marker has no geometry of its
    own to snap to. It stays visible when the marker is hidden. Idempotent.
    """
    point = snap_point(lcs)
    if point is None:
        doc = lcs.Document
        point = doc.addObject("Part::Vertex", "HVACPortPoint")
        container = lcs.getParentGeoFeatureGroup() if hasattr(lcs, "getParentGeoFeatureGroup") else None
        if container is not None:
            container.addObject(point)
        if SNAP_POINT_PROPERTY not in lcs.PropertiesList:
            lcs.addProperty("App::PropertyString", SNAP_POINT_PROPERTY, PORT_GROUP, "Internal: this port's snap point")
            lcs.setEditorMode(SNAP_POINT_PROPERTY, 2)
        setattr(lcs, SNAP_POINT_PROPERTY, point.Name)
        support = "AttachmentSupport" if "AttachmentSupport" in point.PropertiesList else "Support"
        setattr(point, support, [(lcs, "")])
        point.MapMode = "ObjectXY"
        view = getattr(point, "ViewObject", None)
        if view is not None:
            try:
                view.PointSize = 8.0
                view.PointColor = SNAP_POINT_COLOR
            except Exception:
                pass
    label = "{} point".format(str(getattr(lcs, "PortName", "") or lcs.Label))
    current = str(point.Label)
    if current != label and not (current.startswith(label) and current[len(label) :].isdigit()):
        point.Label = label
    return point


def port_of_snap_point(obj, ports):
    """The marker among `ports` whose snap point is `obj`, or None."""
    for lcs in ports:
        if str(getattr(lcs, SNAP_POINT_PROPERTY, "") or "") == getattr(obj, "Name", None):
            return lcs
    return None


def remove_port(lcs):
    """Delete a port marker (and its snap point)."""
    doc = getattr(lcs, "Document", None)
    if doc is not None:
        point = snap_point(lcs)
        doc.removeObject(lcs.Name)
        if point is not None:
            doc.removeObject(point.Name)


def port_size_text(lcs):
    """A short size label for lists: "Ø 200" for a round port, "400 x 200" otherwise."""
    if str(getattr(lcs, "PortProfile", "")) == "Circular":
        return "\u00d8 {:.0f}".format(float(lcs.PortDiameter))
    return "{:.0f} x {:.0f}".format(float(lcs.PortWidth), float(lcs.PortHeight))


def container_ports(container):
    """The port markers inside a custom fitting container, in a stable order (by Label, then Name)."""
    members = list(getattr(container, "OutListRecursive", []) or [])
    ports = [obj for obj in members if is_port(obj)]
    return sorted(ports, key=lambda obj: (str(obj.Label), obj.Name))


def _section(lcs):
    profile = str(lcs.PortProfile)
    if profile == "Circular":
        return profile, {"Diameter": float(lcs.PortDiameter)}
    return profile, {"Width": float(lcs.PortWidth), "Height": float(lcs.PortHeight)}


def read_ports(container, world=False):
    """The container's ports as fit_math.CustomPort, in the container's own coordinates (or world ones)."""
    to_local = FreeCAD.Placement() if world else container.getGlobalPlacement().inverse()
    ports = []
    for lcs in container_ports(container):
        placement = to_local.multiply(lcs.getGlobalPlacement())
        profile, section = _section(lcs)
        ports.append(
            fit_math.CustomPort(
                name=str(getattr(lcs, "PortName", "") or lcs.Label),
                origin=tuple(placement.Base),
                z=tuple(placement.Rotation.multVec(FreeCAD.Vector(0, 0, 1))),
                x=None if profile == "Circular" else tuple(placement.Rotation.multVec(FreeCAD.Vector(1, 0, 0))),
                profile=profile,
                section=section,
            )
        )
    return ports


# ----------------------------------------------------------------------------
# Making a port from a face
# ----------------------------------------------------------------------------


def _opening_wire(face):
    """The air opening of an end face: its largest inner wire, or the outer wire for a face with no hole."""
    inner = [w for w in face.Wires if not w.isSame(face.OuterWire)]
    if not inner:
        return face.OuterWire
    return max(inner, key=lambda w: Part.Face(w).Area)


def _opening_size(wire, normal):
    """(profile, section, x_axis or None, centre) read off an opening wire; profile "" when it is not recognised."""
    edges = wire.Edges
    kinds = [type(edge.Curve).__name__ for edge in edges]
    if len(edges) == 1 and kinds[0] == "Circle":
        circle = edges[0].Curve
        return "Circular", {"Diameter": 2.0 * circle.Radius}, None, circle.Center
    lines = [edge for edge, kind in zip(edges, kinds) if kind in ("Line", "LineSegment")]
    arcs = [edge for edge, kind in zip(edges, kinds) if kind == "Circle"]
    centre = Part.Face(wire).CenterOfMass
    if len(edges) == 4 and len(lines) == 4:
        lengths = sorted({round(edge.Length, 6) for edge in lines})
        longest = max(lines, key=lambda edge: edge.Length)
        x_axis = (longest.Vertexes[1].Point - longest.Vertexes[0].Point).normalize()
        width = longest.Length
        height = min(lines, key=lambda edge: edge.Length).Length if len(lengths) > 1 else width
        return "Rectangular", {"Width": width, "Height": height}, x_axis, centre
    if len(lines) == 2 and len(arcs) == 2:
        radius = arcs[0].Curve.Radius
        straight = lines[0]
        x_axis = (straight.Vertexes[1].Point - straight.Vertexes[0].Point).normalize()
        return "Oval", {"Width": straight.Length + 2.0 * radius, "Height": 2.0 * radius}, x_axis, centre
    return "", {}, None, centre


def add_port(body, face_name, container=None, name="", offset_x=0.0, offset_y=0.0):
    """
    Create a port marker on `body`'s planar end face `face_name`: a
    Part::LocalCoordinateSystem attached to the face (FlatFace), with an
    attachment offset that puts its origin on the centre of the opening
    (plus `offset_x` / `offset_y` along the marker's X / Y, in the face),
    Z out of the fitting and X along the opening's width; its profile and
    size are read from the opening. The marker goes into `container` (an
    App::Part), else into the App::Part holding `body`, else a new
    "CustomFitting" App::Part that `body` is moved into. The marker is
    made visible. Returns the marker.
    An opening whose shape is not recognised gets profile Circular and size
    0, to be set by hand (a console warning says so).
    """
    doc = body.Document
    face = body.Shape.getElement(face_name)
    if not isinstance(face.Surface, Part.Plane):
        raise ValueError("A port needs a planar end face; '{}' is not planar".format(face_name))

    if container is None:
        container = next((obj for obj in body.InList if obj.TypeId == "App::Part"), None)
    if container is None:
        container = doc.addObject("App::Part", "CustomFitting")
        container.addObject(body)

    lcs = doc.addObject("Part::LocalCoordinateSystem", "HVACPort")
    container.addObject(lcs)
    lcs.AttachmentSupport = [(body, face_name)]
    lcs.MapMode = "FlatFace"
    doc.recompute()

    # Where the face attachment put it, and where the port should be (all global).
    attached = lcs.Placement
    global_face = face.copy()
    normal = global_face.normalAt(*global_face.Surface.parameter(global_face.CenterOfMass))
    probe = global_face.CenterOfMass + normal * 1.0e-3
    if body.Shape.isInside(probe, 1.0e-6, True):
        normal = normal * -1.0
    profile, section, x_axis, centre = _opening_size(_opening_wire(global_face), normal)
    if x_axis is None:
        x_axis = attached.Rotation.multVec(FreeCAD.Vector(1, 0, 0))
        x_axis = (x_axis - normal * x_axis.dot(normal)).normalize()
    y_axis = normal.cross(x_axis)
    rotation = FreeCAD.Rotation(x_axis, y_axis, normal, "ZXY")
    origin = centre + x_axis * float(offset_x) + y_axis * float(offset_y)
    wanted = FreeCAD.Placement(origin, rotation)
    lcs.AttachmentOffset = attached.inverse().multiply(wanted)
    ensure_port_properties(lcs)
    lcs.PortOffsetX = float(offset_x)
    lcs.PortOffsetY = float(offset_y)
    if profile:
        lcs.PortProfile = profile
        if profile == "Circular":
            lcs.PortDiameter = section["Diameter"]
        else:
            lcs.PortWidth = section["Width"]
            lcs.PortHeight = section["Height"]
    else:
        FreeCAD.Console.PrintWarning(
            "HVAC - Custom fitting port '{}': the opening is not round, rectangular or a slot; "
            "set PortProfile and its size by hand\n".format(lcs.Label)
        )
    if name:
        lcs.PortName = name
    show_port(lcs)
    doc.recompute()
    return lcs


# ----------------------------------------------------------------------------
# Fitting a component's custom geometry onto its node
# ----------------------------------------------------------------------------


def is_custom(comp_obj):
    return str(getattr(comp_obj, "GeometrySource", "Library") or "Library") == "Custom"


def is_in_place(comp_obj):
    return str(getattr(comp_obj, "CustomPlacement", PLACEMENT_FIT) or PLACEMENT_FIT) == PLACEMENT_IN_PLACE


def _duct_ends(local_ports):
    ends = []
    for port in local_ports:
        x_axis = port.get("profile_x_axis")
        ends.append(
            fit_math.DuctEnd(
                edge_key=str(port.get("edge_key", "")),
                direction=tuple(HVACLibraryAPI.xyz(HVACLibraryAPI.vec(port["direction"]))),
                x=tuple(HVACLibraryAPI.xyz(HVACLibraryAPI.vec(x_axis))) if x_axis is not None else None,
                profile=str(port.get("profile", "") or ""),
                section=dict(port.get("section_params", {}) or {}),
                position=tuple(HVACLibraryAPI.xyz(HVACLibraryAPI.vec(port["position"]))),
            )
        )
    return ends


def _overrides(comp_obj, ports):
    """CustomPortEdgeKeys: entry i names the edge key custom port i must go on (empty = automatic)."""
    keys = list(getattr(comp_obj, "CustomPortEdgeKeys", []) or [])
    return {key: index for index, key in enumerate(keys[: len(ports)]) if key}


def fit_component(comp_obj, local_ports):
    """(container, ports, FitResult) for a custom Primary component on its current ports; raises on any problem."""
    container = getattr(comp_obj, "CustomFitting", None)
    if container is None:
        raise ValueError("GeometrySource is Custom but CustomFitting is not set")
    if not local_ports:
        raise ValueError("The component has no ports yet")
    # In place, the container stays put: compare its ports with the duct ends in world coordinates.
    if is_in_place(comp_obj):
        ports = read_ports(container, world=True)
        result = fit_math.fit_in_place(ports, _duct_ends(local_ports), _overrides(comp_obj, ports))
        return container, ports, result
    ports = read_ports(container)
    node = HVACLibraryAPI.xyz(HVACLibraryAPI.vec(local_ports[0]["position"]))
    result = fit_math.fit(ports, _duct_ends(local_ports), node, _overrides(comp_obj, ports))
    return container, ports, result


def fit_problem(container, primary):
    """
    Why `container` cannot be fitted onto the junction of Primary component
    `primary` ("Fit to node"), or "" when it can: the same fit the component
    would run, on the ports the junction has now. Works for any number of
    ports, an end node (one duct) included.
    """
    try:
        local_ports = json.loads(getattr(primary, "LocalPortsJson", "") or "[]")
    except ValueError:
        local_ports = []
    if not local_ports:
        return "the junction has no ports yet"
    ports = read_ports(container)
    if len(ports) != len(local_ports):
        return "{} duct(s), the fitting has {} port(s)".format(len(local_ports), len(ports))
    try:
        node = HVACLibraryAPI.xyz(HVACLibraryAPI.vec(local_ports[0]["position"]))
        fit_math.fit(ports, _duct_ends(local_ports), node)
    except (fit_math.CustomFitError, KeyError, TypeError, ValueError) as e:
        return str(e)
    return ""


def trim_records(local_ports, result):
    """connection_lengths records (edge_key, segment_end, length) from a fit."""
    return HVACLibraryAPI.build_trim_rec_from_port_lengths(
        [(port, max(0.0, result.trims.get(port.get("edge_key"), 0.0))) for port in local_ports]
    )


def measure(comp_obj, local_ports):
    """{(edge_key, segment_end): trim} without touching the link (DuctJunction's trim peek)."""
    _container, _ports, result = fit_component(comp_obj, local_ports)
    return {(rec["edge_key"], rec["segment_end"]): rec["length"] for rec in trim_records(local_ports, result)}


def port_map(ports, result):
    """{edge_key: {"port", "profile", "section_params"}}: which custom port each duct meets, for the loss."""
    return {
        edge_key: {"port": ports[index].name, "profile": ports[index].profile, "section_params": ports[index].section}
        for edge_key, index in result.mapping.items()
    }


def placement_of(result):
    """The link placement for a fit: custom frame -> world."""
    r = result.rotation
    matrix = FreeCAD.Matrix(
        r[0][0], r[0][1], r[0][2], result.translation[0],
        r[1][0], r[1][1], r[1][2], result.translation[1],
        r[2][0], r[2][1], r[2][2], result.translation[2],
        0.0, 0.0, 0.0, 1.0,
    )  # fmt: skip
    return FreeCAD.Placement(matrix)


def owned_link(comp_obj):
    name = str(getattr(comp_obj, "CustomLinkName", "") or "")
    doc = getattr(comp_obj, "Document", None)
    return doc.getObject(name) if (name and doc is not None) else None


def ensure_link(comp_obj, container):
    """The component's own App::Link to `container`, created on first use."""
    link = owned_link(comp_obj)
    if link is None:
        link = comp_obj.Document.addObject("App::Link", comp_obj.Name + "_Custom")
        comp_obj.CustomLinkName = link.Name
        link.Label = "{} (custom)".format(comp_obj.Label)
    if link.LinkedObject != container:
        link.LinkedObject = container
    return link


def remove_link(comp_obj):
    link = owned_link(comp_obj)
    if link is not None:
        try:
            comp_obj.Document.removeObject(link.Name)
        except Exception:
            pass
    if getattr(comp_obj, "CustomLinkName", ""):
        comp_obj.CustomLinkName = ""


def apply(comp_obj, local_ports):
    """
    Fit, move the link (none in place: the container itself is the
    geometry), and write the component's ConnectionLengthsJson,
    CustomPortMapJson and CustomFitWarnings. Returns the FitResult; raises
    on a fit problem (the caller reports it as GeometryError).
    """
    container, ports, result = fit_component(comp_obj, local_ports)
    if is_in_place(comp_obj):
        remove_link(comp_obj)
    else:
        link = ensure_link(comp_obj, container)
        placement = placement_of(result)
        if not link.Placement.isSame(placement, 1e-9):
            link.Placement = placement

    lengths_json = json.dumps(trim_records(local_ports, result))
    if getattr(comp_obj, "ConnectionLengthsJson", "") != lengths_json:
        comp_obj.ConnectionLengthsJson = lengths_json
    map_json = json.dumps(port_map(ports, result), sort_keys=True)
    if getattr(comp_obj, "CustomPortMapJson", "") != map_json:
        comp_obj.CustomPortMapJson = map_json
    if list(getattr(comp_obj, "CustomFitWarnings", []) or []) != result.warnings:
        comp_obj.CustomFitWarnings = result.warnings
    for warning in result.warnings:
        FreeCAD.Console.PrintWarning("HVAC - Custom fitting '{}': {}\n".format(comp_obj.Label, warning))
    return result
