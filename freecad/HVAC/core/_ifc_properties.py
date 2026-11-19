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
The IFC properties of segments, components and equipment (ROADMAP design 6.8
A2, A3), in the conventions the BIM workbench's IFC exporter reads:

- `IfcType`: the class in BIM spelling ("Duct Fitting");
- group "IFC Attributes": `PredefinedType`, `ObjectType`, `Tag`, copied onto
  the IFC entity as attributes;
- `IfcProperties`: the property sets, {"name;;pset": "type;;value"};
- `IfcData`: holds `IfcUID`, the GUID the exporter writes back, so an element
  keeps its GUID from one export to the next.

The network sync calls refresh_network() at its end, and the airflow
calculation after writing its results, so the values are current whenever
the user exports. All of these are Prop_NoRecompute: writing them never
triggers a rebuild. Segment and component values are worked out here and
shown read-only; equipment values are the user's to choose.
"""

import json

import FreeCAD

from ..ifc import mapping
from ..utils import hvaclib
from ..utils import materials as hvac_materials
from .Construction import construction_for

GROUP = "IFC"
ATTRIBUTES_GROUP = "IFC Attributes"
NO_RECOMPUTE = 16

# Results the property sets carry, per object kind: (results key, property).
_SEGMENT_RESULTS = (
    ("flow_lps", "CalcFlowRate"),
    ("velocity_ms", "CalcVelocity"),
    ("friction_loss_pa", "CalcFrictionLoss"),
    ("fitting_loss_pa", "CalcFittingLoss"),
    ("total_loss_pa", "CalcTotalLoss"),
    ("static_pressure_pa", "CalcCumulativePressure"),
)
_COMPONENT_RESULTS = (
    ("flow_lps", "CalcFlowRate"),
    ("velocity_ms", "CalcVelocity"),
    ("loss_coefficient", "CalcLossCoefficient"),
    ("pressure_drop_pa", "CalcPressureDrop"),
)


def _add(obj, prop_type, name, group, description, mode):
    """Add one property if missing (Prop_NoRecompute) and set its editor mode (0 edit, 1 read-only, 2 hidden)."""
    if name not in obj.PropertiesList:
        obj.addProperty(prop_type, name, group, description, NO_RECOMPUTE)
    try:
        obj.setEditorMode(name, mode)
    except Exception:
        pass


def _set_if_changed(obj, name, value):
    if getattr(obj, name, None) != value:
        setattr(obj, name, value)


def ensure_properties(obj, editable=False):
    """Add the IFC properties to `obj`. `editable` leaves class and attributes for the user to set (equipment)."""
    mode = 0 if editable else 1
    _add(obj, "App::PropertyString", "IfcType", GROUP, "IFC class this object exports as (BIM spelling)", mode)
    _add(obj, "App::PropertyMap", "IfcProperties", GROUP, "IFC property sets this object exports with", 1)
    _add(obj, "App::PropertyMap", "IfcData", GROUP, "Internal: IFC data kept between exports (the GUID)", 2)
    _add(obj, "App::PropertyString", "PredefinedType", ATTRIBUTES_GROUP, "IFC PredefinedType", mode)
    _add(obj, "App::PropertyString", "ObjectType", ATTRIBUTES_GROUP, "IFC ObjectType (when USERDEFINED)", mode)
    _add(obj, "App::PropertyString", "Tag", ATTRIBUTES_GROUP, "IFC Tag: the documentation number", 1)


def _type_def(obj):
    library_id = getattr(obj, "LibraryId", "")
    type_id = getattr(obj, "TypeId", "")
    if not (library_id and type_id):
        return None
    reg = hvaclib.HVACLibraryService.get_hvac_library_registry()
    return reg.resolve_type(library_id, type_id)


def _parent_junction(comp_obj):
    doc = getattr(comp_obj, "Document", None)
    name = getattr(comp_obj, "ParentJunctionName", "") or ""
    return doc.getObject(name) if (doc is not None and name) else None


def _local_ports(comp_obj):
    try:
        return json.loads(getattr(comp_obj, "LocalPortsJson", "") or "[]")
    except ValueError:
        return []


def classify(obj):
    """The mapping.Classification of a DuctSegment or DuctComponent."""
    type_def = _type_def(obj)
    families = list(getattr(type_def, "family", []) or []) if type_def else []
    if hvaclib.isDuctSegment(obj):
        return mapping.element_classification("segment", families or [str(getattr(obj, "Family", "") or "")])

    junction = _parent_junction(obj)
    role = str(getattr(obj, "ComponentRole", "Primary") or "Primary")
    topology = str(getattr(type_def, "topology", "") or getattr(junction, "Topology", "") or "")
    selection = getattr(type_def, "selection", None)

    # A terminal's single port: air flowing into the node leaves the system there.
    leaves_system = None
    ports = _local_ports(obj)
    if topology == "end" and len(ports) == 1 and ports[0].get("flow_into_junction") is not None:
        leaves_system = bool(ports[0]["flow_into_junction"])

    return mapping.element_classification(
        "junction",
        families,
        node_family=str(getattr(junction, "Family", "") or "") if junction is not None else "",
        topology=topology,
        role=role,
        selection_kind=str(getattr(selection, "kind", "") or ""),
        profile=str(getattr(obj, "Profile", "") or ""),
        leaves_system=leaves_system,
    )


def _layers(obj):
    out = []
    for layer in construction_for(obj).layers():
        assigned = layer.material is not None and hvac_materials.is_material_assigned(layer.material)
        material = str(getattr(layer.material, "Name", "") or "") if assigned else ""
        out.append(
            {"id": layer.id, "roles": list(layer.roles), "material": material, "thickness_mm": layer.thickness_mm}
        )
    return out


def _results(obj, table):
    values = {key: float(getattr(obj, prop, 0.0) or 0.0) for key, prop in table if hasattr(obj, prop)}
    # Before the first calculation every result is 0: leave them all out.
    return values if any(values.values()) else {}


def _section(obj):
    section = {"profile": str(getattr(obj, "Profile", "") or "")}
    if hvaclib.isDuctSegment(obj):
        params = hvaclib.get_segment_section_params(obj)
        section.update(diameter_mm=params.get("Diameter"), width_mm=params.get("Width"), height_mm=params.get("Height"))
    return section


def properties_for(obj, network_label=""):
    """The IfcProperties map of a DuctSegment or DuctComponent."""
    segment = hvaclib.isDuctSegment(obj)
    key = getattr(obj, "SegmentKey", "") if segment else getattr(obj, "ParentJunctionName", "")
    return mapping.property_map(
        section=_section(obj),
        layers=_layers(obj),
        results=_results(obj, _SEGMENT_RESULTS if segment else _COMPONENT_RESULTS),
        source={
            "library_id": getattr(obj, "LibraryId", ""),
            "type_id": getattr(obj, "TypeId", ""),
            "key": key,
            "network": network_label,
        },
    )


def refresh(obj, network_label=""):
    """Bring the IFC properties of one DuctSegment or DuctComponent up to date."""
    ensure_properties(obj)
    classification = classify(obj)
    _set_if_changed(obj, "IfcType", mapping.bim_type_name(classification.ifc_class))
    _set_if_changed(obj, "PredefinedType", classification.predefined_type)
    _set_if_changed(obj, "ObjectType", classification.object_type)
    _set_if_changed(obj, "Tag", str(getattr(obj, "Number", "") or ""))
    props = properties_for(obj, network_label)
    if dict(getattr(obj, "IfcProperties", {}) or {}) != props:
        obj.IfcProperties = props


def refresh_network(net):
    """refresh() every segment and component of a network. Returns the number of objects refreshed."""
    proxy = getattr(net, "Proxy", None)
    # Lightweight network doubles (tests) have no object collectors.
    if not (hasattr(proxy, "collectSegmentObjects") and hasattr(proxy, "collectComponentObjects")):
        return 0
    label = str(getattr(net, "Label", "") or "")
    objects = list(proxy.collectSegmentObjects().values())
    for components in proxy.collectComponentObjects().values():
        objects.extend(components)
    for obj in objects:
        try:
            refresh(obj, label)
        except Exception as exc:
            FreeCAD.Console.PrintWarning("HVAC - IFC properties of '{}' not updated: {}\n".format(obj.Label, exc))
    return len(objects)


def ensure_equipment(equipment):
    """
    Give equipment its IFC properties, editable, defaulting to an air
    handling unit (design 6.8 A3). Values the user already set are kept.
    """
    ensure_properties(equipment, editable=True)
    if not getattr(equipment, "IfcType", ""):
        ifc_class, predefined_type = mapping.EQUIPMENT_DEFAULT
        equipment.IfcType = mapping.bim_type_name(ifc_class)
        equipment.PredefinedType = predefined_type
