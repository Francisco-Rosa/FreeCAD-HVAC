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
Shared dynamic-property (type schema) bookkeeping for FreeCAD objects whose
available properties depend on a selected library type (DuctSegment,
DuctJunction's DuctComponent children). Internal to core/ -- not part of the
stable library_api.py surface for library/generator authors.
"""

from ..library import validation
from ..utils import hvaclib


def _declared_choices(pdef):
    """The choices a drop-down's type-def declares (`validation.enum`), as strings."""
    return [str(choice) for choice in (getattr(pdef, "validation", {}) or {}).get("enum", [])]


def _current_choices(obj, name):
    try:
        return list(obj.getEnumerationsOfProperty(name) or [])
    except Exception:
        return []


def set_enumeration_choices(obj, pdef, choices):
    """
    Give drop-down `pdef.name` exactly `choices`, keeping the current choice
    when it is still one of them, else the type-def default, else the first.
    Returns True if the choices had to be (re)set.
    """
    choices = [str(choice) for choice in choices]
    if not choices or _current_choices(obj, pdef.name) == choices:
        return False
    try:
        previous = str(getattr(obj, pdef.name))
    except Exception:
        previous = ""
    # Assigning a list sets the choices; assigning a string then picks one.
    setattr(obj, pdef.name, choices)
    default = str(getattr(pdef, "default", "") or "")
    for candidate in (previous, default, choices[0]):
        if candidate in choices:
            setattr(obj, pdef.name, candidate)
            break
    return True


def _sync_enumeration_choices(obj, pdef):
    """
    Give an enumeration property the choices its type-def declares
    (`validation.enum`), keeping the current choice when it is still one of
    them and falling back to the default otherwise. Returns True if the
    choices had to be (re)set.

    A drop-down already narrowed to some of those choices (in their declared
    order) is left as it is: the geometry backend narrows it on each build
    to what suits the fitting (core/_geometry_apply.apply_property_choices).
    Widening it here on every sync would mark the object changed each time.
    """
    choices = _declared_choices(pdef)
    if not choices:
        return False
    existing = _current_choices(obj, pdef.name)
    if existing and [choice for choice in choices if choice in existing] == existing:
        return False
    return set_enumeration_choices(obj, pdef, choices)


def _add_per_port_property(obj, pdef):
    """Add a per-port property's value list and hidden key list to `obj`. Returns True if either was added."""
    added = False
    keys_name = validation.per_port_keys_name(pdef.name)
    list_type = validation.PER_PORT_LIST_TYPES[pdef.prop_type]

    # A property left over under the same name with another type (e.g. this
    # used to be one plain value) can't hold a list: replace it.
    if pdef.name in obj.PropertiesList and obj.getTypeIdOfProperty(pdef.name) != list_type:
        obj.removeProperty(pdef.name)
    if pdef.name not in obj.PropertiesList:
        description = "{} (one value per connected port, in port order)".format(pdef.description)
        obj.addProperty(list_type, pdef.name, pdef.group, description)
        added = True
    if keys_name not in obj.PropertiesList:
        obj.addProperty(
            "App::PropertyStringList",
            keys_name,
            "HVAC",
            "Internal: which port each {} value belongs to".format(pdef.name),
        )
        added = True
    try:
        obj.setEditorMode(pdef.name, int(getattr(pdef, "editor_mode", 0) or 0))
        obj.setEditorMode(keys_name, 2)
    except Exception:
        pass
    return added


def apply_type_schema(obj, library_id, type_id, *, protected_names=()):
    """
    Add/remove/edit-mode-sync dynamic properties on `obj` to match the
    declared property schema of (library_id, type_id). Returns True if
    anything on `obj` changed.

    protected_names: property names that are permanent/core on `obj` (e.g.
    DuctSegment's Diameter/Width/Height) and must never be removed even if
    the newly-selected type doesn't declare them -- only their editor_mode
    is synced to whether the active type declares them.
    """
    reg = hvaclib.HVACLibraryService.get_hvac_library_registry()
    if not library_id or not type_id:
        return False

    type_def = reg.resolve_type(library_id, type_id)
    if type_def is None:
        return False

    changed = False
    protected = set(protected_names)
    active_prop_names = {pdef.name for pdef in (getattr(type_def, "properties", []) or [])}
    # A per-port property also owns a hidden companion list (which port each
    # value belongs to); it is added and removed together with the property.
    for pdef in getattr(type_def, "properties", []) or []:
        if getattr(pdef, "per_port", False):
            active_prop_names.add(validation.per_port_keys_name(pdef.name))
    new_names = [n for n in active_prop_names if n not in protected]

    # Remove properties left over from a *previously* selected type (e.g.
    # switching TypeId to a different model) that the newly-selected type
    # doesn't declare, so the property editor doesn't accumulate stale
    # fields across model switches. Protected names are never removed.
    old_names = list(getattr(obj, "TypeSchemaPropertyNames", []) or [])
    for name in set(old_names) - set(new_names):
        if name in obj.PropertiesList:
            try:
                obj.removeProperty(name)
                changed = True
            except Exception:
                pass

    for pdef in getattr(type_def, "properties", []) or []:
        prop_added = False

        if getattr(pdef, "per_port", False):
            # Stored as a list (one value per port) plus its companion key
            # list. They start empty; core/_port_properties.py fills them
            # once the object's ports are known.
            if _add_per_port_property(obj, pdef):
                changed = True
            continue

        if pdef.name not in obj.PropertiesList:
            obj.addProperty(pdef.prop_type, pdef.name, pdef.group, pdef.description)
            changed = True
            prop_added = True

        if pdef.prop_type == "App::PropertyEnumeration":
            # A drop-down: its choices are the type-def's own "enum" rule.
            if _sync_enumeration_choices(obj, pdef):
                changed = True

        try:
            current = getattr(obj, pdef.name)
        except Exception:
            current = None

        if getattr(pdef, "default", None) is not None:
            should_apply_default = prop_added or current in (None, "")
            if should_apply_default:
                try:
                    setattr(obj, pdef.name, pdef.default)
                    changed = True
                except Exception:
                    pass

        try:
            obj.setEditorMode(pdef.name, int(getattr(pdef, "editor_mode", 0) or 0))
        except Exception:
            pass

    # Protected (permanent) properties are never removed above -- but their
    # visibility still tracks whether the currently-active type declares
    # them, so a property that isn't relevant to this type just hides.
    for name in protected:
        if name in obj.PropertiesList:
            try:
                obj.setEditorMode(name, 0 if name in active_prop_names else 1)
            except Exception:
                pass

    if list(getattr(obj, "TypeSchemaPropertyNames", []) or []) != new_names:
        try:
            obj.TypeSchemaPropertyNames = new_names
            changed = True
        except Exception:
            pass

    return changed


def _is_user_editable(obj, prop):
    """True when the property editor lets the user change `prop` (not read-only, not hidden)."""
    try:
        mode = obj.getEditorMode(prop) or []
    except Exception:
        return True
    return "ReadOnly" not in mode and "Hidden" not in mode


def request_sync_after_edit(obj, prop, extra_names=()):
    """
    Ask `obj`'s owner network to sync after the user edits one of its
    geometry inputs straight in the property editor: a type-schema property
    (TypeSchemaPropertyNames) or one of `extra_names`. Returns True when a
    sync was requested.

    Why: a recompute rebuilds only the edited object. Its neighbours read it
    through the network sync, not through FreeCAD links: a fitting's ports
    come from its ducts' sizes, and a duct's trims come from its fittings'
    lengths. Without a sync those stay stale (a duct still trimmed to the
    old fitting length, a fitting still sized for the old duct).

    Inside an open transaction (the property editor's, while a value is
    being typed) the sync is deferred until the transaction closes.

    Edits made while the network itself is syncing, while the document is
    loading, or by the object's own execute() (computed values) are left
    alone: they are part of a rebuild already under way.
    """
    if prop not in extra_names and prop not in (getattr(obj, "TypeSchemaPropertyNames", None) or []):
        return False
    proxy = getattr(obj, "Proxy", None)
    if getattr(proxy, "_executing", False):
        return False
    doc = getattr(obj, "Document", None)
    if doc is None or getattr(doc, "Restoring", False):
        return False
    if not _is_user_editable(obj, prop):
        return False
    owner = hvaclib.getOwnerNetwork(obj)
    owner_proxy = getattr(owner, "Proxy", None) if owner is not None else None
    if owner_proxy is None or getattr(owner_proxy, "_sync_in_progress", False):
        return False
    try:
        # The property editor applies a typed value on every keystroke, inside
        # one open transaction it commits when the value is entered. Syncing
        # per keystroke made typing slow: inside a transaction the sync waits
        # for its commit (ui/Observer.py); outside one (a script) it runs now.
        if getattr(doc, "HasPendingTransaction", False) and hasattr(owner_proxy, "deferEditSync"):
            owner_proxy.deferEditSync()
        else:
            owner_proxy.requestSync(force_recompute=True)
    except Exception:
        return False
    return True
