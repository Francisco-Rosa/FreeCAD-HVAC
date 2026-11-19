# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the HVAC addon.

################################################################################
#                                                                              #
#   Copyright (c) 2026 Francisco Rosa                                          #
#                                                                              #
#   This addon is free software; you can redistribute it and/or modify it      #
#   under the terms of the GNU Lesser General Public License as published      #
#   by the Free Software Foundation; either version 2.1 of the License, or     #
#   (at your option) any later version.                                        #
#                                                                              #
#   This addon is distributed in the hope that it will be useful,              #
#   but WITHOUT ANY WARRANTY; without even the implied warranty of             #
#   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.                       #
#                                                                              #
#   See the GNU Lesser General Public License for more details.                #
#                                                                              #
#   You should have received a copy of the GNU Lesser General Public           #
#   License along with this addon. If not, see https://www.gnu.org/licenses    #
#                                                                              #
################################################################################

"""
Adds the MEP part of an export to an IFC file the BIM workbench exporter
wrote (ROADMAP design 6.8 B2): ports, port connections, systems, type
objects, coverings and storey containment, from an IfcExportPlan.

Uses ifcopenshell only, never FreeCAD: the elements are found by the GUIDs
the exporter gave them, and covering shapes arrive as BREP text already in
the file's length unit. Everything this module creates gets a GUID derived
from a stable seed (the element's GUID plus a port key, a layer id, ...), so
exporting the same model twice gives the same GUIDs.
"""

import uuid

import ifcopenshell
import ifcopenshell.guid
import ifcopenshell.util.placement
import ifcopenshell.util.unit
import numpy

_GUID_NAMESPACE = uuid.UUID("6f1d5f0e-8a4c-4b8e-9a52-3c3b8f2e7d10")


def stable_guid(*parts):
    """An IFC GUID that only depends on `parts`."""
    seed = "|".join(str(p) for p in parts)
    return ifcopenshell.guid.compress(uuid.uuid5(_GUID_NAMESPACE, seed).hex)


def _perpendicular(z):
    """Any unit vector square to `z`, for an axis placement's X direction."""
    helper = numpy.array([0.0, 0.0, 1.0]) if abs(z[2]) < 0.9 else numpy.array([1.0, 0.0, 0.0])
    x = numpy.cross(helper, z)
    return x / numpy.linalg.norm(x)


class _Writer:
    def __init__(self, ifc_file, salt):
        self.f = ifc_file
        self.salt = salt
        self.warnings = []
        histories = ifc_file.by_type("IfcOwnerHistory")
        self.history = histories[0] if histories else None
        self.mm = 0.001 / ifcopenshell.util.unit.calculate_unit_scale(ifc_file)  # file units per mm
        self.context = self._body_context()
        self.project = (ifc_file.by_type("IfcProject") or [None])[0]
        self.building = (ifc_file.by_type("IfcBuilding") or [None])[0]

    def _body_context(self):
        contexts = self.f.by_type("IfcGeometricRepresentationSubContext")
        for context in contexts:
            if context.ContextIdentifier == "Body":
                return context
        models = [c for c in self.f.by_type("IfcGeometricRepresentationContext") if c.ContextType == "Model"]
        return models[0] if models else None

    def create(self, ifc_class, seed, **attributes):
        """Create a rooted entity with a stable GUID and the file's owner history."""
        return self.f.create_entity(
            ifc_class, GlobalId=stable_guid(self.salt, ifc_class, seed), OwnerHistory=self.history, **attributes
        )

    # -- geometry helpers ----------------------------------------------------

    def point(self, xyz):
        return self.f.createIfcCartesianPoint([float(c) for c in xyz])

    def direction(self, xyz):
        return self.f.createIfcDirection([float(c) for c in xyz])

    def port_placement(self, element, position_mm, direction):
        """A placement at the port, Z along `direction`, relative to the element's own placement."""
        z = numpy.array(direction, dtype=float)
        z = z / (numpy.linalg.norm(z) or 1.0)
        world = numpy.eye(4)
        world[:3, 0] = _perpendicular(z)
        world[:3, 1] = numpy.cross(z, world[:3, 0])
        world[:3, 2] = z
        world[:3, 3] = numpy.array(position_mm, dtype=float) * self.mm
        parent = element.ObjectPlacement
        matrix = ifcopenshell.util.placement.get_local_placement(parent) if parent is not None else numpy.eye(4)
        local = numpy.linalg.inv(matrix) @ world
        axis = self.f.createIfcAxis2Placement3D(
            self.point(local[:3, 3]), self.direction(local[:3, 2]), self.direction(local[:3, 0])
        )
        return self.f.createIfcLocalPlacement(parent, axis)


def _containers(ifc_file, element):
    return [rel for rel in ifc_file.by_type("IfcRelContainedInSpatialStructure") if element in rel.RelatedElements]


def enrich(path, plan, guids, coverings=None, levels=None, labels=None, salt=""):
    """
    Add `plan` (plan.IfcExportPlan) to the IFC file at `path` and save it.

    guids           {element id: GlobalId the exporter gave the element}
    coverings       {(element id, layer id): {"brep": BREP text, "mesh": (points,
                    triangles)}}, both in file units
    levels          {level id: {"label", "elevation_mm", "guid"}}
    labels          {element id: name}: the exporter takes names from its
                    stand-ins, whose labels FreeCAD made unique ("Duct001")
    salt            makes the derived GUIDs of systems and types unique to
                    the source document

    Returns a list of warnings.
    """
    w = _Writer(ifcopenshell.open(path), salt)
    f = w.f
    coverings = coverings or {}
    levels = levels or {}
    labels = labels or {}

    # Step 1: find the elements the exporter wrote.
    elements = {}
    for element_id in plan.element_ids:
        guid = guids.get(element_id)
        entity = None
        if guid:
            try:
                entity = f.by_guid(guid)
            except RuntimeError:
                entity = None
        if entity is None:
            w.warnings.append("{} is missing from the exported file; its ports are left out".format(element_id))
            continue
        if labels.get(element_id):
            entity.Name = labels[element_id]
        elements[element_id] = entity

    # Step 2: ports, nested under their element.
    ports = {}
    nested = {}
    for port in plan.ports:
        element = elements.get(port.element_id)
        if element is None:
            continue
        entity = w.create(
            "IfcDistributionPort",
            "{}|{}".format(element.GlobalId, port.key),
            Name=port.name,
            Description=port.key,
            ObjectPlacement=w.port_placement(element, port.position, port.direction),
            FlowDirection=port.flow_direction,
            PredefinedType="DUCT",
            SystemType=port.system_type or None,
        )
        ports[(port.element_id, port.key)] = entity
        nested.setdefault(port.element_id, []).append(entity)
    for element_id, port_entities in nested.items():
        element = elements[element_id]
        w.create("IfcRelNests", "nests|" + element.GlobalId, RelatingObject=element, RelatedObjects=port_entities)

    # Step 3: port connections.
    for c in plan.connections:
        a, b = ports.get((c.element_a, c.port_a)), ports.get((c.element_b, c.port_b))
        if a is None or b is None:
            continue
        w.create("IfcRelConnectsPorts", "connects|{}|{}".format(a.GlobalId, b.GlobalId), RelatingPort=a, RelatedPort=b)

    # Step 4: one distribution system per network, serving the building.
    for system in plan.systems:
        members = [elements[e] for e in system.member_ids if e in elements]
        entity = w.create(
            "IfcDistributionSystem",
            "system|" + system.system_id,
            Name=system.name,
            LongName=system.long_name,
            PredefinedType=system.predefined_type,
        )
        if members:
            w.create("IfcRelAssignsToGroup", "group|" + system.system_id, RelatedObjects=members, RelatingGroup=entity)
        if w.building is not None:
            w.create(
                "IfcRelServicesBuildings",
                "services|" + system.system_id,
                RelatingSystem=entity,
                RelatedBuildings=[w.building],
            )

    # Step 5: type objects, declared in the project.
    type_entities = []
    for type_plan in plan.types:
        members = [elements[e] for e in type_plan.element_ids if e in elements]
        if not members:
            continue
        attributes = {"Name": type_plan.name, "PredefinedType": type_plan.predefined_type}
        if type_plan.predefined_type == "USERDEFINED":
            attributes["ElementType"] = type_plan.element_type or type_plan.name
        try:
            entity = w.create(type_plan.ifc_class, "type|" + type_plan.type_id, **attributes)
        except Exception as exc:
            w.warnings.append("Type '{}' not written: {}".format(type_plan.name, exc))
            continue
        w.create("IfcRelDefinesByType", "typed|" + type_plan.type_id, RelatedObjects=members, RelatingType=entity)
        type_entities.append(entity)
    if type_entities and w.project is not None:
        w.create("IfcRelDeclares", "declares|types", RelatingContext=w.project, RelatedDefinitions=type_entities)

    # Step 6: storeys named by the networks' Level, then move elements into them.
    storeys = {}
    for level_id, info in levels.items():
        guid = info.get("guid") or ""
        storey = None
        if guid:
            try:
                storey = f.by_guid(guid)
            except RuntimeError:
                storey = None
        if storey is None:
            storey = _new_storey(w, level_id, info)
        storeys[level_id] = storey
    for level_id, element_ids in plan.containment.items():
        storey = storeys.get(level_id)
        if storey is None:
            continue
        _contain(w, storey, [elements[e] for e in element_ids if e in elements])

    # Step 7: coverings, beside their element in its storey and system.
    host_coverings = {}
    for covering in plan.coverings:
        element = elements.get(covering.element_id)
        geometry = coverings.get((covering.element_id, covering.layer_id))
        if element is None or not geometry:
            continue
        entity = _covering(w, element, covering, geometry)
        if entity is not None:
            host_coverings.setdefault(covering.element_id, []).append(entity)
    for element_id, coverings in host_coverings.items():
        element = elements[element_id]
        w.create(
            "IfcRelCoversBldgElements",
            "covers|" + element.GlobalId,
            RelatingBuildingElement=element,
            RelatedCoverings=coverings,
        )
        containers = _containers(f, element)
        if containers:
            _contain(w, containers[0].RelatingStructure, coverings)

    f.write(path)
    return w.warnings


def _new_storey(w, level_id, info):
    """A storey for a Level the exported file does not have, aggregated under the building."""
    elevation = float(info.get("elevation_mm", 0.0) or 0.0) * w.mm
    parent = w.building.ObjectPlacement if w.building is not None else None
    axis = w.f.createIfcAxis2Placement3D(w.point((0.0, 0.0, elevation)), None, None)
    storey = w.create(
        "IfcBuildingStorey",
        "storey|" + level_id,
        Name=info.get("label") or level_id,
        ObjectPlacement=w.f.createIfcLocalPlacement(parent, axis),
        CompositionType="ELEMENT",
        Elevation=elevation,
    )
    if w.building is not None:
        w.create("IfcRelAggregates", "aggregates|" + level_id, RelatingObject=w.building, RelatedObjects=[storey])
    return storey


def _contain(w, storey, entities):
    """Make `storey` the only spatial container of `entities`."""
    if not entities:
        return
    for entity in entities:
        for rel in _containers(w.f, entity):
            if rel.RelatingStructure == storey:
                continue
            remaining = [e for e in rel.RelatedElements if e != entity]
            if remaining:
                rel.RelatedElements = remaining
            else:
                w.f.remove(rel)
    existing = [rel for rel in w.f.by_type("IfcRelContainedInSpatialStructure") if rel.RelatingStructure == storey]
    if existing:
        rel = existing[0]
        rel.RelatedElements = list(rel.RelatedElements) + [e for e in entities if e not in rel.RelatedElements]
    else:
        w.create(
            "IfcRelContainedInSpatialStructure",
            "contains|" + storey.GlobalId,
            RelatedElements=list(entities),
            RelatingStructure=storey,
        )


def _serialised_body(w, brep):
    """An IfcProductDefinitionShape from BREP text, or None when ifcopenshell cannot convert it."""
    from ifcopenshell import geom

    if not brep:
        return None
    # ifcopenshell 0.8 wants the schema name first; older versions took the BREP alone.
    try:
        try:
            shape = geom.serialise(w.f.schema, brep)
        except TypeError:
            shape = geom.serialise(brep)
    except Exception:
        return None
    if shape is None:
        return None
    representation = w.f.add(shape)
    for item in representation.Representations:
        item.ContextOfItems = w.context
    return representation


def _meshed_body(w, mesh):
    """An IfcProductDefinitionShape holding one triangulated face set, from (points, triangles)."""
    if not mesh or not mesh[0] or not mesh[1]:
        return None
    points, triangles = mesh
    point_list = w.f.createIfcCartesianPointList3D([[float(c) for c in p] for p in points])
    # IfcTriangulatedFaceSet indices start at 1.
    faces = w.f.createIfcTriangulatedFaceSet(point_list, None, True, [[i + 1 for i in t] for t in triangles], None)
    shape = w.f.createIfcShapeRepresentation(w.context, "Body", "Tessellation", [faces])
    return w.f.createIfcProductDefinitionShape(None, None, [shape])


def _covering(w, element, covering, geometry):
    """
    One IfcCovering, placed in world coordinates like the exporter's
    elements. `geometry` is {"brep": text, "mesh": (points, triangles)}:
    the exact BREP when ifcopenshell can convert it (swept insulation often
    cannot), else the mesh.
    """
    representation = _serialised_body(w, geometry.get("brep")) or _meshed_body(w, geometry.get("mesh"))
    if representation is None:
        w.warnings.append("Covering {} of {} has no geometry; left out".format(covering.layer_id, element.Name))
        return None
    placement = w.f.createIfcLocalPlacement(None, w.f.createIfcAxis2Placement3D(w.point((0.0, 0.0, 0.0)), None, None))
    entity = w.create(
        "IfcCovering",
        "{}|{}".format(element.GlobalId, covering.layer_id),
        Name="{} {}".format(element.Name or "", covering.object_type).strip(),
        ObjectType=covering.object_type,
        ObjectPlacement=placement,
        Representation=representation,
        PredefinedType=covering.predefined_type,
    )
    if covering.material:
        material = next((m for m in w.f.by_type("IfcMaterial") if m.Name == covering.material), None)
        material = material or w.f.createIfcMaterial(covering.material)
        w.create(
            "IfcRelAssociatesMaterial",
            "material|" + entity.GlobalId,
            RelatedObjects=[entity],
            RelatingMaterial=material,
        )
    return entity
