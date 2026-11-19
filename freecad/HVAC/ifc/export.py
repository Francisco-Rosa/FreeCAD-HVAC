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
IFC export of duct networks, start to finish (ROADMAP design 6.8, A5).

1. Read the networks and work out the MEP plan (collect.py, plan.py).
2. Give every exported element a temporary Part::Feature stand-in holding
   its body shape and its IFC properties. The BIM exporter reads an object's
   `Shape`, and a duct's `Shape` is the compound of its *visible* layers,
   insulation included; the stand-in has exactly the body instead. The real
   objects are never touched, apart from the GUID copied back to them.
3. Run the BIM workbench exporter on the stand-ins (IFC4).
4. Copy the GUIDs the exporter gave the stand-ins back onto the real
   objects' IfcData, then delete the stand-ins.
5. Add ports, connections, systems, types, coverings and storeys to the file
   (writer.py).
"""

import importlib
from dataclasses import dataclass, field

import FreeCAD

from . import collect as ifc_collect
from . import plan as ifc_plan

# Properties copied from an element onto its stand-in, with their types and groups.
_COPIED_PROPERTIES = (
    ("IfcType", "App::PropertyString", "IFC"),
    ("PredefinedType", "App::PropertyString", "IFC Attributes"),
    ("ObjectType", "App::PropertyString", "IFC Attributes"),
    ("Tag", "App::PropertyString", "IFC Attributes"),
    ("IfcProperties", "App::PropertyMap", "IFC"),
    ("IfcData", "App::PropertyMap", "IFC"),
)


class IfcExportError(Exception):
    """The export cannot run; the message says why and what to change."""


@dataclass
class ExportReport:
    path: str
    element_count: int = 0
    port_count: int = 0
    connection_count: int = 0
    covering_count: int = 0
    system_count: int = 0
    warnings: list = field(default_factory=list)


def _exporter():
    """The BIM workbench's exportIFC module, after checking ifcopenshell and the IFC version."""
    try:
        importlib.import_module("ifcopenshell")
    except ImportError:
        raise IfcExportError(
            "IFC export needs IfcOpenShell, which this FreeCAD does not have. See https://wiki.freecad.org/IfcOpenShell"
        ) from None
    module = None
    for name in ("importers.exportIFC", "exportIFC"):
        try:
            module = importlib.import_module(name)
            break
        except ImportError:
            continue
    if module is None:
        raise IfcExportError("The BIM workbench's IFC exporter (exportIFC) was not found")
    try:
        version = importlib.import_module("ArchIFCSchema").IfcVersion
    except Exception:
        version = "IFC4"
    if version != "IFC4":
        raise IfcExportError(
            "The BIM workbench is set to {}, which has no duct classes. Set Preferences > BIM > IFC export "
            "to IFC4 and restart FreeCAD".format(version)
        )
    return module


def _make_stand_in(doc, obj, body):
    stand_in = doc.addObject("Part::Feature", "HVACIfcExport")
    stand_in.Shape = body
    stand_in.Label = obj.Label
    for name, prop_type, group in _COPIED_PROPERTIES:
        value = getattr(obj, name, None)
        if value is None:
            continue
        stand_in.addProperty(prop_type, name, group, "")
        setattr(stand_in, name, dict(value) if prop_type == "App::PropertyMap" else value)
    if "IfcData" not in stand_in.PropertiesList:
        stand_in.addProperty("App::PropertyMap", "IfcData", "IFC", "")
    # Carry the element's colour over when there is a GUI.
    try:
        stand_in.ViewObject.ShapeColor = obj.ViewObject.ShapeColor
        stand_in.ViewObject.Visibility = False
    except Exception:
        pass
    return stand_in


def export_networks(networks, path):
    """
    Export `networks` (DuctNetwork objects of one document), with the
    equipment they connect to, to the IFC4 file `path`. Returns an
    ExportReport; raises IfcExportError when the export cannot run.
    """
    exporter = _exporter()
    networks = list(networks)
    if not networks:
        raise IfcExportError("No duct network to export")
    doc = networks[0].Document
    FreeCAD.setActiveDocument(doc.Name)

    # Step 1: read the networks and plan the MEP part.
    collected = ifc_collect.collect(networks)
    plan = ifc_plan.build_plan(collected.networks, collected.equipment, collected.levels)
    report = ExportReport(path=str(path), warnings=list(collected.warnings) + list(plan.warnings))
    exported = [e for e in plan.element_ids if e in collected.bodies]
    if not exported:
        raise IfcExportError("The networks have no ducts or fittings with a solid to export")

    # Steps 2 to 4: stand-ins, the BIM exporter, GUIDs back.
    preferences = exporter.getPreferences()
    preferences.update(
        {"SCHEMA": "IFC4", "STORE_UID": True, "EXPORT_2D": False, "FULL_PARAMETRIC": False, "CREATE_CLONES": False}
    )
    guids = {}
    stand_ins = {}
    try:
        for element_id in exported:
            stand_ins[element_id] = _make_stand_in(doc, collected.objects[element_id], collected.bodies[element_id])
        exporter.export(list(stand_ins.values()), str(path), preferences=preferences)
        for element_id, stand_in in stand_ins.items():
            guid = dict(stand_in.IfcData).get("IfcUID", "")
            if not guid:
                continue
            guids[element_id] = guid
            obj = collected.objects[element_id]
            data = dict(getattr(obj, "IfcData", {}) or {})
            if data.get("IfcUID") != guid and hasattr(obj, "IfcData"):
                data["IfcUID"] = guid
                obj.IfcData = data
    finally:
        for stand_in in stand_ins.values():
            try:
                doc.removeObject(stand_in.Name)
            except Exception:
                pass

    # Step 5: the MEP part.
    from . import writer

    # Covering shapes in the file's length unit, as the exporter scales
    # bodies: the exact BREP plus a mesh for when ifcopenshell cannot use it.
    scale = float(preferences.get("SCALE_FACTOR", 0.001))
    coverings = {}
    for key, shape in collected.coverings.items():
        scaled = shape.copy()
        scaled.scale(scale)
        points, triangles = shape.tessellate(1.0)  # 1 mm deviation
        coverings[key] = {
            "brep": scaled.exportBrepToString(),
            "mesh": ([(p.x * scale, p.y * scale, p.z * scale) for p in points], [tuple(t) for t in triangles]),
        }
    levels = {
        level_id: {"label": info["label"], "elevation_mm": info["elevation_mm"], "guid": info["guid"]}
        for level_id, info in collected.levels.items()
    }
    labels = {element_id: str(collected.objects[element_id].Label) for element_id in exported}
    report.warnings.extend(
        writer.enrich(str(path), plan, guids, coverings=coverings, levels=levels, labels=labels, salt=doc.Uid)
    )

    report.element_count = len(guids)
    report.port_count = len(plan.ports)
    report.connection_count = len(plan.connections)
    report.covering_count = len([c for c in plan.coverings if (c.element_id, c.layer_id) in coverings])
    report.system_count = len(plan.systems)
    return report
