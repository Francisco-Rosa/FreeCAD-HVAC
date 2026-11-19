# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the HVAC addon.

"""
Per-port properties on a FreeCAD object: a type-def property marked
`"per_port": true` holds one value for each connected port, so a fitting
can have any number of ports (a plenum, a manifold, an AHU).

On the object such a property is two lists: the values themselves, and a
hidden companion (`<Name>EdgeKeys`) naming the port each value belongs to.
Matching is always by edge_key, never by position. This module keeps the
two lists in step with the object's current ports. Edge keys are stable
across a document reload (hvaclib.makeLineKey), so the stored keys stay
valid as they are.
"""

from ..library import validation


def per_port_property_defs(type_def):
    """The per-port property defs a type declares."""
    return [pdef for pdef in (getattr(type_def, "properties", []) or []) if getattr(pdef, "per_port", False)]


def sync_port_property_lists(obj, type_def, edge_keys):
    """
    Make every per-port property of `obj` hold exactly one value per current
    port, in port order. A port that already had a value keeps it; a new
    port gets the type-def default; a port that is gone loses its value.
    Returns True if anything changed.
    """
    edge_keys = [key for key in edge_keys if key]
    changed = False
    for pdef in per_port_property_defs(type_def):
        keys_name = validation.per_port_keys_name(pdef.name)
        if pdef.name not in obj.PropertiesList or keys_name not in obj.PropertiesList:
            continue
        values = list(getattr(obj, pdef.name, None) or [])
        keys = list(getattr(obj, keys_name, None) or [])
        if keys == edge_keys and len(values) == len(edge_keys):
            continue
        # Lists that disagree in length can't be matched up; start again from the default.
        stored = dict(zip(keys, values)) if len(keys) == len(values) else {}
        default = validation.normalize_property_value(pdef.prop_type, getattr(pdef, "default", None))
        setattr(obj, pdef.name, [stored.get(key, default) for key in edge_keys])
        setattr(obj, keys_name, list(edge_keys))
        changed = True
    return changed


# ----------------------------------------------------------------------------
# The per-port table of the Edit Type panel (Stage 3): one row per port, one
# column per per-port property. Plain data here; ui/TaskPanel.py draws it.
# ----------------------------------------------------------------------------


def port_table(obj, type_def, labels_by_edge=None):
    """
    (columns, rows) for `obj`'s per-port properties, or ([], []) when the
    type has none. columns: [{"name", "prop_type", "description"}]. rows:
    [{"edge_key", "label", "values": {name: value}}], in the order the
    object stores its ports (the first per-port property's key list).
    `labels_by_edge` names each port (e.g. its duct's number); the edge key
    is shown when a port has no label.
    """
    defs = [pdef for pdef in per_port_property_defs(type_def) if pdef.name in getattr(obj, "PropertiesList", [])]
    if not defs:
        return [], []
    labels_by_edge = labels_by_edge or {}
    columns = [
        {"name": pdef.name, "prop_type": pdef.prop_type, "description": getattr(pdef, "description", "")}
        for pdef in defs
    ]
    first_keys = list(getattr(obj, validation.per_port_keys_name(defs[0].name), None) or [])
    stored = {}
    for pdef in defs:
        keys = list(getattr(obj, validation.per_port_keys_name(pdef.name), None) or [])
        values = list(getattr(obj, pdef.name, None) or [])
        default = validation.normalize_property_value(pdef.prop_type, getattr(pdef, "default", None))
        by_key = dict(zip(keys, values)) if len(keys) == len(values) else {}
        stored[pdef.name] = (by_key, default)
    rows = []
    for edge_key in first_keys:
        values = {}
        for pdef in defs:
            by_key, default = stored[pdef.name]
            values[pdef.name] = validation.normalize_property_value(pdef.prop_type, by_key.get(edge_key, default))
        rows.append({"edge_key": edge_key, "label": labels_by_edge.get(edge_key) or edge_key, "values": values})
    return columns, rows


def parse_port_value(prop_type, text):
    """A table cell's text as the value a per-port property stores; raises ValueError on bad input."""
    prop_type = str(prop_type or "")
    if prop_type == "App::PropertyBool":
        if isinstance(text, bool):
            return text
        word = str(text).strip().lower()
        if word in ("1", "true", "yes", "on"):
            return True
        if word in ("0", "false", "no", "off", ""):
            return False
        raise ValueError("'{}' is not true or false".format(text))
    if prop_type.startswith("App::PropertyInteger"):
        return int(str(text).strip())
    value = float(str(text).strip().split()[0]) if str(text).strip() else 0.0
    return value


def apply_port_table(obj, type_def, edits):
    """
    Write table edits back: `edits` is {edge_key: {name: value}}. Only
    ports and properties already on the object are touched; each list keeps
    its own key order. Returns True if anything changed.
    """
    changed = False
    for pdef in per_port_property_defs(type_def):
        keys_name = validation.per_port_keys_name(pdef.name)
        if pdef.name not in obj.PropertiesList or keys_name not in obj.PropertiesList:
            continue
        keys = list(getattr(obj, keys_name, None) or [])
        values = list(getattr(obj, pdef.name, None) or [])
        if len(keys) != len(values):
            continue
        new_values = list(values)
        for index, key in enumerate(keys):
            if key in edits and pdef.name in edits[key]:
                new_values[index] = edits[key][pdef.name]
        if new_values != values:
            setattr(obj, pdef.name, new_values)
            changed = True
    return changed
