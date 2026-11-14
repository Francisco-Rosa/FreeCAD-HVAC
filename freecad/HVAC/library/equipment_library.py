# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the HVAC addon.

"""
Equipment models of a library: ready-made units (an air handling unit, a
fan) that "Add Equipment" places in a document as HVAC equipment.

A library keeps one JSON file per model in its `equipment/` folder:

    {
      "id": "ahu_generic",
      "label": "Air handling unit",
      "description": "...",
      "geometry": {"backend": "generator", "module": "shared:equipment", "function": "build_ahu"},
      "properties": [
        {"name": "CasingLength", "label": "Casing length", "type": "length", "default": 2400.0},
        {"name": "Service", "label": "Service", "type": "choice", "options": ["Supply", "Exhaust"],
         "default": "Supply"},
        {"name": "OutdoorAirPort", "label": "Outdoor air inlet", "type": "bool", "default": true}
      ]
    }

Property types: "length" (mm), "number", "pressure" (Pa), "choice" (with
"options") and "bool". The generator is called as `function(api, values)`
with HVACLibraryAPI and the resolved property values, and returns

    {"shape": <one solid>,
     "ports": [{"name", "function", "position", "direction"}, ...],
     "internal_pressure_drop": <Pa, optional>}

where each port lies on a planar end face of the solid (a collar's end),
`direction` points out of the unit and `function` is one of
core/Equipment.py's PORT_FUNCTIONS. The port's profile and size are read
from that face when the equipment is made (core/Equipment.create_from_model).

This module only reads and checks the definitions; it needs no FreeCAD.
"""

import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List

EQUIPMENT_FOLDER = "equipment"
PROPERTY_TYPES = ("length", "number", "pressure", "choice", "bool")
_MODEL_KEYS = {"id", "label", "description", "geometry", "properties"}
_PROPERTY_KEYS = {"name", "label", "type", "default", "options", "description", "min"}


@dataclass
class EquipmentProperty:
    name: str
    label: str
    type: str
    default: Any
    options: List[str] = field(default_factory=list)
    description: str = ""
    minimum: float = 0.0


@dataclass
class EquipmentModel:
    library_id: str
    id: str
    label: str
    description: str
    module: str
    function: str
    properties: List[EquipmentProperty] = field(default_factory=list)


def parse_model(data, library_id, source=""):
    """An EquipmentModel from one definition dict; raises ValueError naming what is wrong (unknown keys included)."""
    where = "Equipment model '{}'".format(source or data.get("id", "?"))
    if not isinstance(data, dict):
        raise ValueError("{}: the file must hold one JSON object".format(where))
    unknown = set(data) - _MODEL_KEYS
    if unknown:
        raise ValueError("{}: unknown key(s) {}".format(where, sorted(unknown)))
    for key in ("id", "label", "geometry"):
        if not data.get(key):
            raise ValueError("{}: '{}' is required".format(where, key))
    geometry = data["geometry"]
    if geometry.get("backend") != "generator" or not geometry.get("module") or not geometry.get("function"):
        raise ValueError("{}: geometry needs backend 'generator' with a module and a function".format(where))

    properties, names = [], set()
    for entry in data.get("properties", []) or []:
        unknown = set(entry) - _PROPERTY_KEYS
        if unknown:
            raise ValueError("{}: property has unknown key(s) {}".format(where, sorted(unknown)))
        name = str(entry.get("name", ""))
        if not name or name in names:
            raise ValueError("{}: property name '{}' is missing or used twice".format(where, name))
        names.add(name)
        kind = str(entry.get("type", ""))
        if kind not in PROPERTY_TYPES:
            raise ValueError("{}: property '{}' has unknown type '{}'".format(where, name, kind))
        if "default" not in entry:
            raise ValueError("{}: property '{}' needs a default".format(where, name))
        options = [str(option) for option in entry.get("options", []) or []]
        if kind == "choice" and (not options or str(entry["default"]) not in options):
            raise ValueError("{}: choice property '{}' needs options that include its default".format(where, name))
        properties.append(
            EquipmentProperty(
                name=name,
                label=str(entry.get("label", "") or name),
                type=kind,
                default=entry["default"],
                options=options,
                description=str(entry.get("description", "") or ""),
                minimum=float(entry.get("min", 0.0) or 0.0),
            )
        )
    return EquipmentModel(
        library_id=str(library_id),
        id=str(data["id"]),
        label=str(data["label"]),
        description=str(data.get("description", "") or ""),
        module=str(geometry["module"]),
        function=str(geometry["function"]),
        properties=properties,
    )


def load_models(library_id, library_root):
    """
    Every equipment model in a library folder, sorted by label:
    (models, errors). A bad file is reported in `errors` and skipped.
    """
    folder = os.path.join(str(library_root), EQUIPMENT_FOLDER)
    models, errors = [], []
    if not os.path.isdir(folder):
        return models, errors
    seen = set()
    for file_name in sorted(os.listdir(folder)):
        if not file_name.lower().endswith(".json"):
            continue
        path = os.path.join(folder, file_name)
        try:
            with open(path, "r", encoding="utf-8") as handle:
                model = parse_model(json.load(handle), library_id, source=file_name)
            if model.id in seen:
                raise ValueError("Equipment model id '{}' is used twice in library '{}'".format(model.id, library_id))
            seen.add(model.id)
            models.append(model)
        except (OSError, ValueError) as e:
            errors.append("{}: {}".format(path, e))
    models.sort(key=lambda model: model.label)
    return models, errors


def resolve_values(model, supplied=None) -> Dict[str, Any]:
    """
    The model's property values: each default, replaced by what was supplied
    and converted to its type. Raises ValueError for an unknown name, a
    value below the property's minimum, or a choice that is not offered.
    """
    supplied = dict(supplied or {})
    known = {prop.name for prop in model.properties}
    unknown = set(supplied) - known
    if unknown:
        raise ValueError("Equipment model '{}' has no property {}".format(model.id, sorted(unknown)))
    values = {}
    for prop in model.properties:
        raw = supplied.get(prop.name, prop.default)
        if prop.type == "bool":
            values[prop.name] = bool(raw)
        elif prop.type == "choice":
            if str(raw) not in prop.options:
                raise ValueError("{}: '{}' is not one of {}".format(prop.label, raw, prop.options))
            values[prop.name] = str(raw)
        else:
            value = float(raw)
            if value < prop.minimum:
                raise ValueError("{} must be at least {:g}".format(prop.label, prop.minimum))
            values[prop.name] = value
    return values
