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
FreeCAD-HVAC does not maintain its own material database. This module is
the thin glue to FreeCAD's own native Material subsystem (the `Materials`
module, `Materials::PropertyMaterial`, `.FCMat` cards):

  - register_material_resources(): tells FreeCAD's Material subsystem where
    this addon's `.FCMat` cards and Hydraulic model live, so they show up
    in the normal material browser/editor next to built-in, user, and
    other addons' materials -- see ARCHITECTURE.md for the full data flow.
  - get_physical_value()/get_view_appearance(): the only two ways core/
    code should ever read a `Materials::PropertyMaterial` value -- the
    native material stays authoritative for both physical properties
    (density, thermal conductivity, ...) and rendering appearance; nothing
    here duplicates or caches that data onto HVAC's own objects.

Not part of the stable library_api.py surface -- internal to core/'s own
ViewProvider glue and future physical-quantity calculations.
"""

import math
import os

import FreeCAD

from . import hvaclib

# UUIDs of this addon's own shipped cards used as network-level defaults
# (see Network.py's DefaultMaterial_StructuralShell/DefaultMaterial_
# ThermalInsulation) -- must match freecad/HVAC/Resources/Materials/Metal/
# Galvanized-Steel.FCMat and .../Insulation/Nitrile-Rubber.FCMat's own
# General.UUID.
GALVANIZED_STEEL_UUID = "7d01e7c6-c1b7-4374-b361-a00232c94d20"
NITRILE_RUBBER_UUID = "4f16dfeb-1bc6-41a8-8a40-30942e30cd2a"
NITRILE_RUBBER_OPEN_CELL_UUID = "1b7baf06-8e33-4b63-a1f1-a9a39bd3ab2e"
GALVANIZED_STEEL_PERFORATED_UUID = "31e7402b-d640-4f04-b60d-b86904ba73cf"
ALUMINIUM_UUID = "ff83dff9-a970-455c-9641-ead756d61b8a"
STAINLESS_STEEL_UUID = "108ff6fa-441d-44e2-a16b-543dbfd3a2e2"
HYDRAULIC_MODEL_UUID = "bbfee379-96b0-4995-80e2-e1725b3adfde"
FREECAD_DEFAULT_MATERIAL_UUID = "7f9fd73b-50c9-41d8-b7b2-575a030c1eeb"


def get_unassigned_material():
    """Return a real, persistable FreeCAD material used internally for None."""
    return get_material_by_uuid(FREECAD_DEFAULT_MATERIAL_UUID)


def is_unassigned_material(material):
    if material is None:
        return True
    if not getattr(material, "Name", ""):
        return True
    try:
        return str(material.UUID) == FREECAD_DEFAULT_MATERIAL_UUID
    except Exception:
        return False


def is_material_assigned(material):
    return not is_unassigned_material(material)


def get_material_by_uuid(uuid):
    """
    Look up a material by UUID via FreeCAD's own Material subsystem, or
    None if it isn't (yet) known -- e.g. register_material_resources()
    hasn't run yet, or the UUID belongs to a card that no longer exists.
    Never raises.
    """
    try:
        import Materials
        return Materials.MaterialManager().getMaterial(str(uuid))
    except Exception:
        return None


def ensure_persistable_material(obj, prop_name):
    """
    Replace an invalid/empty Materials::PropertyMaterial value with the
    registered FreeCAD Default material.

    Returns True when changed.
    """
    if obj is None or prop_name not in getattr(obj, "PropertiesList", []):
        return False
    material = getattr(obj, prop_name, None)
    # Already sentinel or a real material.
    if material is not None:
        try:
            if str(material.UUID) == FREECAD_DEFAULT_MATERIAL_UUID:
                return False
        except Exception:
            pass
        if getattr(material, "Name", ""):
            return False
    fallback = get_unassigned_material()
    if fallback is None:
        return False
    try:
        setattr(obj, prop_name, fallback)
        return True
    except Exception:
        return False


def register_material_resources():
    """
    Register freecad/HVAC/Resources/Materials with FreeCAD's Material
    subsystem, following the same convention FreeCAD's own Supplemental-
    Materials addon uses: one group per addon under ".../Mod/Material/
    Resources/Modules", with a "ModuleDir" key FreeCAD's own
    materialtools.cardutils.get_material_resources()/get_material_libraries()
    scan on top of the built-in/user/custom material directories. Idempotent
    -- safe to call on every addon load.

    ``ModuleModelDir`` also registers the addon's native Hydraulic model so
    roughness appears as an editable quantity in FreeCAD's Material Editor.
    """
    materials_path = hvaclib.get_materials_base_path()
    models_path = hvaclib.get_material_models_base_path()
    if not os.path.isdir(materials_path) or not os.path.isdir(models_path):
        return

    config = FreeCAD.ParamGet(
        "User parameter:BaseApp/Preferences/Mod/Material/Resources/Modules/FreeCAD-HVAC"
    )
    config.SetString("ModuleDir", materials_path)
    config.SetString("ModuleModelDir", models_path)
    config.SetString("ModuleIcon", hvaclib.get_icon_path("Logo.svg"))
    config.SetBool("ModuleReadOnly", True)


def _parse_color(raw):
    """A Materials::Material Color-typed appearance value's string form ("(r, g, b, a)") -> a 4-tuple of floats, or None if missing/unparseable."""
    if not raw:
        return None
    try:
        parts = [float(x) for x in str(raw).strip("()[]").split(",")]
    except (TypeError, ValueError):
        return None
    if len(parts) < 3:
        return None
    r, g, b = parts[0], parts[1], parts[2]
    a = parts[3] if len(parts) > 3 else 1.0
    return (r, g, b, a)


def _parse_float(raw):
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def get_physical_value(material, name):
    """
    A material's own physical property (e.g. "Density", "ThermalConductivity",
    "SpecificHeat") as a plain float, in FreeCAD's internal unit system
    (kg/mm^3 for density, consistent with every other quantity in this
    addon). Returns None if the material is unassigned, doesn't model this
    property at all, or the card never gave it a real value (FreeCAD
    reports an unset-but-modeled property as NaN, not missing).
    """
    if not is_material_assigned(material):
        return None
    if not material.hasPhysicalProperty(name):
        return None
    try:
        value = material.getPhysicalValue(name)
    except Exception:
        return None
    if value is None:
        return None
    try:
        number = float(getattr(value, "Value", value))
    except (TypeError, ValueError):
        return None
    if math.isnan(number):
        return None
    return number


def get_physical_value_as(material, name, unit=None):
    """Return a native physical property converted to ``unit`` when possible.

    Real FreeCAD quantities expose ``getValueAs``.  Lightweight material
    implementations (including library clients and tests) often expose a
    plain number instead; those values are treated as already being in the
    requested unit.  ``None`` has the same meaning as in
    :func:`get_physical_value`.
    """
    if not is_material_assigned(material):
        return None
    try:
        if not material.hasPhysicalProperty(name):
            return None
        value = material.getPhysicalValue(name)
        if value is None:
            return None
        if unit and hasattr(value, "getValueAs"):
            value = value.getValueAs(unit)
        number = float(getattr(value, "Value", value))
    except Exception:
        return None
    return None if math.isnan(number) else number


def get_hydraulic_roughness_mm(material):
    """Absolute roughness in mm from a material card, or None if undeclared."""
    for property_name in ("HydraulicRoughness", "Roughness"):
        value = get_physical_value_as(material, property_name, "mm")
        if value is not None and value >= 0.0:
            return value


def get_view_appearance(material):
    """
    Build a FreeCAD.Material() rendering struct (the plain App::Material
    value ViewObject.ShapeAppearance/DiffuseColor actually consume) from a
    Materials::Material database material's own AppearanceModels. The
    native material stays authoritative -- this is only a one-way,
    read-only conversion for the ViewProvider to hand to FreeCAD's own
    rendering properties; nothing is written back onto the material.

    Returns None if the material is unassigned or declares no usable
    DiffuseColor at all (nothing meaningful to render with).
    """
    if not is_material_assigned(material):
        return None
    if not material.hasAppearanceProperty("DiffuseColor"):
        return None

    color = _parse_color(material.getAppearanceValue("DiffuseColor"))
    if color is None:
        return None

    appearance = FreeCAD.Material()
    appearance.DiffuseColor = color

    if material.hasAppearanceProperty("AmbientColor"):
        ambient = _parse_color(material.getAppearanceValue("AmbientColor"))
        if ambient is not None:
            appearance.AmbientColor = ambient
    if material.hasAppearanceProperty("EmissiveColor"):
        emissive = _parse_color(material.getAppearanceValue("EmissiveColor"))
        if emissive is not None:
            appearance.EmissiveColor = emissive
    if material.hasAppearanceProperty("SpecularColor"):
        specular = _parse_color(material.getAppearanceValue("SpecularColor"))
        if specular is not None:
            appearance.SpecularColor = specular
    if material.hasAppearanceProperty("Shininess"):
        shininess = _parse_float(material.getAppearanceValue("Shininess"))
        if shininess is not None:
            appearance.Shininess = shininess
    if material.hasAppearanceProperty("Transparency"):
        transparency = _parse_float(material.getAppearanceValue("Transparency"))
        if transparency is not None:
            appearance.Transparency = transparency

    return appearance
