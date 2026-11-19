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

"""This module implements HVAC duct description classes."""

import json
import traceback
from dataclasses import asdict

import FreeCAD

from ..analysis.sizing import SIZE_CHANGE_POLICIES
from ..core import _construction_schema, _terminal_function
from ..core.Component import DuctComponent
from ..core.Junction import DuctJunction, DuctJunctionVirtual
from ..core.NetworkParser import DuctNetworkParser
from ..core.Segment import DuctSegment
from ..library.construction import (
    ALL_LAYER_ROLES,
    ROLE_ACOUSTIC_ABSORBER,
    ROLE_ACOUSTIC_LINER,
    ROLE_FLOW_SURFACE,
    ROLE_OUTER_JACKET,
    ROLE_STRUCTURAL_SHELL,
    ROLE_THERMAL_INSULATION,
    ROLE_VAPOR_BARRIER,
    role_property_suffix,
)
from ..utils import hvaclib
from ..utils import materials as hvac_materials


class DuctManagedFolder:
    """Internal managed folder used by DuctNetwork."""

    def __init__(self, obj, owner=None, role=""):
        obj.Proxy = self
        if "OwnerNetworkName" not in obj.PropertiesList:
            # Store link as string to avoid cyclic dependency issue
            obj.addProperty("App::PropertyString", "OwnerNetworkName", "HVAC", "Owning duct network")
        if "FolderRole" not in obj.PropertiesList:
            obj.addProperty("App::PropertyString", "FolderRole", "HVAC", "Internal folder role")
        obj.OwnerNetworkName = owner.Name if owner else ""
        obj.FolderRole = role

    def onDocumentRestored(self, obj):
        obj.Proxy = self

    def execute(self, obj):
        """Required so the object can clear its touched state on recompute."""
        pass

    @staticmethod
    def getOwner(obj):
        return DuctNetwork.getOwnerNetwork(obj)

    @staticmethod
    def create(doc, name, owner, role):
        from ..ui.NetworkViewProvider import DuctManagedFolderViewProvider

        folder = doc.addObject("App::DocumentObjectGroupPython", name)
        DuctManagedFolder(folder, owner=owner, role=role)
        DuctManagedFolderViewProvider(folder.ViewObject)
        return folder


class DuctNetwork:
    """Visualize and configure HVAC duct network in FreeCAD's 3D view."""

    CONTEXT_KEY = hvaclib.DUCT_NETWORK_CONTEXT_KEY
    FOLDER_BASE_NAME = "Base"
    FOLDER_GEOMETRY_NAME = "Geometry"
    FOLDER_TOPOLOGY_NAME = "Topology"

    def __init__(self, obj):
        obj.Proxy = self
        self.Object = obj
        self._runtime_param_cache = {}
        self._allow_internal_delete = False
        self._initial_sync = True
        self._sync_in_progress = False
        self._sync_scheduled = False
        self._sync_suspended = False
        self._hidden_source_names = set()
        self._parser = None
        self.setProperties(obj)

    def dumps(self):
        return None

    def loads(self, state):
        # Block sync to prevent premature execution during document restore
        # due to observer scheduling sync
        self._sync_suspended = True

    def onDocumentRestored(self, obj):
        obj.Proxy = self
        self.Object = obj
        self._runtime_param_cache = {}
        self._allow_internal_delete = False
        self._initial_sync = True
        self._sync_in_progress = False
        self._sync_scheduled = False
        self._sync_suspended = False
        self._hidden_source_names = set()
        self._parser = None
        self.setProperties(obj)
        self.requestSync(initial_sync=True)
        # Resotore sync suspension after document restore
        self._sync_suspended = False

    def execute(self, obj):
        """Manual recompute of the network triggers deferred synchronization."""
        if self._sync_in_progress:
            return
        self.requestSync()

    def onChanged(self, obj, prop):
        # Layer / feature visibility is display only: re-render, never rebuild.
        if prop == "ShowFeatures" or prop.startswith("ShowLayer_"):
            self.refreshAppearance()
        # The system decides every Auto terminal's function: re-classify.
        if prop == "SystemType" and not getattr(getattr(obj, "Document", None), "Restoring", False):
            try:
                self.requestSync()
            except Exception:
                pass

    def refreshAppearance(self):
        """Re-apply the per-layer / per-feature appearance of every segment and component of this network."""
        if not FreeCAD.GuiUp or getattr(self, "Object", None) is None:
            return
        from . import _component_appearance

        geometry = getattr(self.Object, "Geometry", None)
        for child in list(getattr(geometry, "OutList", []) or []):
            if not (hvaclib.isDuctSegment(child) or hvaclib.isDuctComponent(child)):
                continue
            # Rebuild the displayed compound first (outside any view update), then colour it.
            _component_appearance.refresh_display_shape(child)
            vobj = getattr(child, "ViewObject", None)
            if vobj is not None:
                _component_appearance.apply_component_appearance(vobj)

    def setProperties(self, obj):
        """Gives the object properties to HVAC ducts."""
        doc = obj.Document

        # Base folder
        if "Base" not in obj.PropertiesList:
            obj.addProperty("App::PropertyLink", "Base", "HVAC", "Base (internal)")
        if getattr(obj, "Base", None) is None and doc is not None:
            folder_base = DuctManagedFolder.create(
                doc, f"{obj.Name}_{self.FOLDER_BASE_NAME}", owner=obj, role=self.FOLDER_BASE_NAME
            )
            folder_base.Label = self.FOLDER_BASE_NAME
            obj.Base = folder_base
        elif obj.Base:
            if getattr(obj.Base, "OwnerNetworkName", "") != obj.Name:
                obj.Base.OwnerNetworkName = obj.Name
            if getattr(obj.Base, "FolderRole", "") != self.FOLDER_BASE_NAME:
                obj.Base.FolderRole = self.FOLDER_BASE_NAME

        # Geometry folder
        if "Geometry" not in obj.PropertiesList:
            obj.addProperty("App::PropertyLink", "Geometry", "HVAC", "Geometry (internal)")
        if getattr(obj, "Geometry", None) is None and doc is not None:
            folder_geometry = DuctManagedFolder.create(
                doc, f"{obj.Name}_{self.FOLDER_GEOMETRY_NAME}", owner=obj, role=self.FOLDER_GEOMETRY_NAME
            )
            folder_geometry.Label = self.FOLDER_GEOMETRY_NAME
            obj.Geometry = folder_geometry
        elif obj.Geometry:
            if getattr(obj.Geometry, "OwnerNetworkName", "") != obj.Name:
                obj.Geometry.OwnerNetworkName = obj.Name
            if getattr(obj.Geometry, "FolderRole", "") != self.FOLDER_GEOMETRY_NAME:
                obj.Geometry.FolderRole = self.FOLDER_GEOMETRY_NAME

        # Topology folder
        if "Topology" not in obj.PropertiesList:
            obj.addProperty("App::PropertyLink", "Topology", "HVAC", "Topology (internal)")
        if getattr(obj, "Topology", None) is None and doc is not None:
            folder_topology = DuctManagedFolder.create(
                doc, f"{obj.Name}_{self.FOLDER_TOPOLOGY_NAME}", owner=obj, role=self.FOLDER_TOPOLOGY_NAME
            )
            folder_topology.Label = self.FOLDER_TOPOLOGY_NAME
            obj.Topology = folder_topology
        elif obj.Topology:
            if getattr(obj.Topology, "OwnerNetworkName", "") != obj.Name:
                obj.Topology.OwnerNetworkName = obj.Name
            if getattr(obj.Topology, "FolderRole", "") != self.FOLDER_TOPOLOGY_NAME:
                obj.Topology.FolderRole = self.FOLDER_TOPOLOGY_NAME

        # Internal bookkeeping links to the managed folders above -- kept
        # (never removed) for the addon's own use, just hidden from the
        # property editor since a user never needs to read or edit them
        # directly (the folders themselves are still visible in the tree).
        for prop in ("Base", "Geometry", "Topology"):
            try:
                obj.setEditorMode(prop, 2)
            except Exception:
                pass

        # -------------------------------------------------
        # Library/type defaults for this network
        # -------------------------------------------------

        if "DefaultLibraryId" not in obj.PropertiesList:
            obj.addProperty(
                "App::PropertyString", "DefaultLibraryId", "HVAC Types", "Default HVAC library for derived geometry"
            )

        if "DefaultSegmentProfile" not in obj.PropertiesList:
            obj.addProperty(
                "App::PropertyString",
                "DefaultSegmentProfile",
                "HVAC Types",
                "Default segment profile from selected library",
            )

        if "DefaultAttachment" not in obj.PropertiesList:
            obj.addProperty(
                "App::PropertyEnumeration",
                "DefaultAttachment",
                "HVAC Types",
                "Default section attachment for new segments",
            )
            obj.DefaultAttachment = list(hvaclib.ATTACH_MAP.keys())
            obj.DefaultAttachment = "Center"

        if "DefaultOffset" not in obj.PropertiesList:
            obj.addProperty(
                "App::PropertyVector", "DefaultOffset", "HVAC Types", "Default section offset for new segments"
            )

        if "DefaultDiameter" not in obj.PropertiesList:
            obj.addProperty("App::PropertyLength", "DefaultDiameter", "HVAC Types", "Default circular duct diameter")

        if "DefaultWidth" not in obj.PropertiesList:
            obj.addProperty("App::PropertyLength", "DefaultWidth", "HVAC Types", "Default rectangular duct width")

        if "DefaultHeight" not in obj.PropertiesList:
            obj.addProperty("App::PropertyLength", "DefaultHeight", "HVAC Types", "Default rectangular duct height")

        # Materials::PropertyMaterial, not App::PropertyLinkGlobal -- see
        # the matching comment in Segment.py's setProperties(). One
        # property per standardized LayerRole (see library/construction.py)
        # -- not per library-defined layer id, since roles are the fixed,
        # small vocabulary core owns; a type's own construction layers fall
        # back to their first declared role's default here when they don't
        # specify their own default_material_uuid (see
        # core/_construction_schema.py's apply_default_layer_materials()).
        for role in ALL_LAYER_ROLES:
            prop_name = "DefaultMaterial_" + role_property_suffix(role)
            if prop_name not in obj.PropertiesList:
                obj.addProperty(
                    "Materials::PropertyMaterial",
                    prop_name,
                    "HVAC Types",
                    "Default material for construction layers playing the '{}' role".format(role),
                    16,  # Prop_NoRecompute
                )
            hvac_materials.ensure_persistable_material(obj, prop_name)

        # Display only (Stage 9 item 2): which construction layers and
        # features are drawn for every segment and component of this
        # network. A layer is drawn when any of its roles is shown; a hidden
        # one is made fully transparent (it stays pickable). Prop_NoRecompute:
        # toggling never rebuilds geometry.
        for role in ALL_LAYER_ROLES:
            prop_name = "ShowLayer_" + role_property_suffix(role)
            if prop_name not in obj.PropertiesList:
                obj.addProperty(
                    "App::PropertyBool",
                    prop_name,
                    "HVAC Display",
                    "Draw construction layers playing the '{}' role".format(role),
                    16,  # Prop_NoRecompute
                )
                setattr(obj, prop_name, True)
        # One system per network (ROADMAP 6.5): what its terminals do unless
        # a terminal's own TerminalFunction says otherwise.
        if "SystemType" not in obj.PropertiesList:
            obj.addProperty(
                "App::PropertyEnumeration",
                "SystemType",
                "Airflow",
                "The air system this network is: Supply, Return, Exhaust or OutdoorAir. Terminals left at "
                "TerminalFunction Auto take their role from it (the balancing terminal is the Source)",
            )
            obj.SystemType = list(_terminal_function.SYSTEM_TYPES)
            obj.SystemType = "Supply"

        if "ShowFeatures" not in obj.PropertiesList:
            obj.addProperty(
                "App::PropertyBool",
                "ShowFeatures",
                "HVAC Display",
                "Draw construction features (flanges, stiffeners, ...)",
                16,  # Prop_NoRecompute
            )
            obj.ShowFeatures = True

        if not getattr(obj, "DefaultLibraryId", ""):
            lib = hvaclib.HVACLibraryService.get_active_hvac_library()
            if lib:
                obj.DefaultLibraryId = lib.id

        if not getattr(obj, "DefaultSegmentProfile", ""):
            obj.DefaultSegmentProfile = hvaclib.HVACLibraryService.default_segment_profile_for_library(
                getattr(obj, "DefaultLibraryId", "")
            )

        try:
            if obj.DefaultOffset != FreeCAD.Vector(0, 0, 0):
                pass
        except Exception:
            obj.DefaultOffset = FreeCAD.Vector(0, 0, 0)

        if not getattr(obj, "DefaultDiameter", 0):
            obj.DefaultDiameter = 100.0

        if not getattr(obj, "DefaultWidth", 0):
            obj.DefaultWidth = 100.0

        if not getattr(obj, "DefaultHeight", 0):
            obj.DefaultHeight = 100.0

        # Seed the standard construction-role materials.
        # # FireProtection intentionally has no HVAC material default.
        # Its property remains the persistable unassigned sentinel.
        def _seed_role_default(role, uuid):
            prop_name = "DefaultMaterial_" + role_property_suffix(role)
            current = getattr(obj, prop_name, None)
            if hvac_materials.is_material_assigned(current):
                return
            material = hvac_materials.get_material_by_uuid(uuid)
            if material is not None:
                setattr(obj, prop_name, material)

        _seed_role_default(ROLE_STRUCTURAL_SHELL, hvac_materials.GALVANIZED_STEEL_UUID)
        _seed_role_default(ROLE_THERMAL_INSULATION, hvac_materials.NITRILE_RUBBER_UUID)
        _seed_role_default(ROLE_FLOW_SURFACE, hvac_materials.GALVANIZED_STEEL_UUID)
        _seed_role_default(ROLE_ACOUSTIC_ABSORBER, hvac_materials.NITRILE_RUBBER_OPEN_CELL_UUID)
        _seed_role_default(ROLE_ACOUSTIC_LINER, hvac_materials.GALVANIZED_STEEL_PERFORATED_UUID)
        _seed_role_default(ROLE_VAPOR_BARRIER, hvac_materials.ALUMINIUM_UUID)
        _seed_role_default(ROLE_OUTER_JACKET, hvac_materials.ALUMINIUM_UUID)

        # -------------------------------------------------
        # Air properties used for airflow/pressure-drop calculation
        # -------------------------------------------------

        if "AirDensity" not in obj.PropertiesList:
            obj.addProperty(
                "App::PropertyFloat",
                "AirDensity",
                "HVAC Air Properties",
                "Air density (kg/m3) used for pressure-drop calculation",
            )

        if "AirKinematicViscosity" not in obj.PropertiesList:
            obj.addProperty(
                "App::PropertyFloat",
                "AirKinematicViscosity",
                "HVAC Air Properties",
                "Air kinematic viscosity (m2/s) used for Reynolds number",
            )

        if "DefaultRoughness" not in obj.PropertiesList:
            obj.addProperty(
                "App::PropertyLength",
                "DefaultRoughness",
                "HVAC Air Properties",
                "Fallback absolute roughness when a construction's flow-surface material has no roughness",
            )

        if not getattr(obj, "AirDensity", 0):
            obj.AirDensity = 1.204  # standard air, 20 degC, sea level

        if not getattr(obj, "AirKinematicViscosity", 0):
            obj.AirKinematicViscosity = 1.51e-5

        if not getattr(obj, "DefaultRoughness", 0):
            obj.DefaultRoughness = 0.09  # mm, galvanized steel

        # -------------------------------------------------
        # Straight-duct friction model (analysis/friction.py). A segment
        # type that declares its own "friction" factory (e.g. a flexible
        # duct) wraps or replaces this one.
        # -------------------------------------------------

        if "FrictionModel" not in obj.PropertiesList:
            obj.addProperty(
                "App::PropertyEnumeration",
                "FrictionModel",
                "HVAC Air Properties",
                "Straight-duct friction: Darcy-Weisbach with the Altshul-Tsal or Colebrook friction factor, a "
                "friction chart from FrictionTableFile, or the formula in FrictionExpression",
            )
            obj.FrictionModel = ["DarcyAltshulTsal", "DarcyColebrook", "Table", "Expression"]
            obj.FrictionModel = "DarcyAltshulTsal"

        if "FrictionTableFile" not in obj.PropertiesList:
            obj.addProperty(
                "App::PropertyFile",
                "FrictionTableFile",
                "HVAC Air Properties",
                "CSV friction chart for FrictionModel Table: a header row with diameter_mm, velocity_ms (or "
                "flow_lps) and pa_per_m, then one row per chart point",
            )

        if "FrictionExpression" not in obj.PropertiesList:
            obj.addProperty(
                "App::PropertyString",
                "FrictionExpression",
                "HVAC Air Properties",
                "Friction rate in Pa/m for FrictionModel Expression, in Q (m3/s), V (m/s), Dh (m), A (m2), "
                "eps (m), rho (kg/m3), nu (m2/s), Re; + - * / **, sqrt, log, log10, exp, abs, min, max",
            )

        # -------------------------------------------------
        # Duct sizing (constant velocity / constant friction rate / static regain)
        # -------------------------------------------------

        if "SizingMethod" not in obj.PropertiesList:
            obj.addProperty(
                "App::PropertyEnumeration", "SizingMethod", "HVAC Duct Sizing", "Method used by the Size Ducts command"
            )
            obj.SizingMethod = [
                "ConstantVelocity",
                "ConstantFrictionRate",
                "StaticRegain",
                "PressureBalancedStaticRegain",
            ]
            obj.SizingMethod = "ConstantVelocity"
        else:
            # Re-assigning the enum's own value list (not its current
            # value) is safe at any time and picks up new options on
            # documents created before this option existed.
            obj.SizingMethod = [
                "ConstantVelocity",
                "ConstantFrictionRate",
                "StaticRegain",
                "PressureBalancedStaticRegain",
            ]

        if "SizeChangePolicy" not in obj.PropertiesList:
            obj.addProperty(
                "App::PropertyEnumeration",
                "SizeChangePolicy",
                "HVAC Duct Sizing",
                "Where Size Ducts may change a duct's size. AtStraightJunctions: wherever air passes straight "
                "through a junction (in-line nodes and the run of a tee or cross), never through a bend. "
                "AtInlineNodesOnly: only at in-line two-port nodes (a tee run keeps its size). EverySegment: "
                "every segment is sized for its own flow. A junction's AllowSizeChange can pin it",
            )
            obj.SizeChangePolicy = list(SIZE_CHANGE_POLICIES)
            obj.SizeChangePolicy = "AtStraightJunctions"
        elif hasattr(obj, "getEnumerationsOfProperty") and list(
            obj.getEnumerationsOfProperty("SizeChangePolicy") or []
        ) != list(SIZE_CHANGE_POLICIES):
            # A document saved with the old choices (AtReducers / EverySegment): AtReducers now reads
            # AtStraightJunctions, everything else keeps its value.
            old = str(obj.SizeChangePolicy)
            obj.SizeChangePolicy = list(SIZE_CHANGE_POLICIES)
            obj.SizeChangePolicy = old if old in SIZE_CHANGE_POLICIES else "AtStraightJunctions"

        if "TargetVelocity" not in obj.PropertiesList:
            obj.addProperty(
                "App::PropertyFloat",
                "TargetVelocity",
                "HVAC Duct Sizing",
                "Target duct velocity (m/s) used when SizingMethod is ConstantVelocity, and as the "
                "starting velocity for sections leaving the balancing terminal when SizingMethod is StaticRegain",
            )

        if "TargetFrictionRate" not in obj.PropertiesList:
            obj.addProperty(
                "App::PropertyFloat",
                "TargetFrictionRate",
                "HVAC Duct Sizing",
                "Target friction rate (Pa/m) used when SizingMethod is ConstantFrictionRate",
            )

        if "StaticRegainFactor" not in obj.PropertiesList:
            obj.addProperty(
                "App::PropertyFloat",
                "StaticRegainFactor",
                "HVAC Duct Sizing",
                "Fraction of velocity-pressure regain actually recovered (0-1) when SizingMethod is StaticRegain",
            )

        if "MinimumVelocity" not in obj.PropertiesList:
            obj.addProperty(
                "App::PropertyFloat",
                "MinimumVelocity",
                "HVAC Duct Sizing",
                "Velocity floor (m/s) used when SizingMethod is StaticRegain, since regain sizing alone "
                "can propose impractically large/slow ducts on small or low-velocity branches",
            )

        if "RectangularSizingMode" not in obj.PropertiesList:
            obj.addProperty(
                "App::PropertyEnumeration",
                "RectangularSizingMode",
                "HVAC Duct Sizing",
                "How the second dimension of a rectangular/oval duct is determined when sizing",
            )
            obj.RectangularSizingMode = ["FixedAspectRatio", "FixedHeight", "FixedWidth"]
            obj.RectangularSizingMode = "FixedAspectRatio"

        if "TargetAspectRatio" not in obj.PropertiesList:
            obj.addProperty(
                "App::PropertyFloat",
                "TargetAspectRatio",
                "HVAC Duct Sizing",
                "Target Width:Height ratio used when RectangularSizingMode is FixedAspectRatio",
            )

        if "SizeRoundingIncrement" not in obj.PropertiesList:
            obj.addProperty(
                "App::PropertyLength",
                "SizeRoundingIncrement",
                "HVAC Duct Sizing",
                "Computed duct sizes are rounded up to the nearest multiple of this increment",
            )

        if not getattr(obj, "TargetVelocity", 0):
            obj.TargetVelocity = 5.0

        if not getattr(obj, "TargetFrictionRate", 0):
            obj.TargetFrictionRate = 1.0

        if not getattr(obj, "StaticRegainFactor", 0):
            obj.StaticRegainFactor = 0.75

        if not getattr(obj, "MinimumVelocity", 0):
            obj.MinimumVelocity = 2.5

        if not getattr(obj, "TargetAspectRatio", 0):
            obj.TargetAspectRatio = 2.0

        if not getattr(obj, "SizeRoundingIncrement", 0):
            obj.SizeRoundingIncrement = 10.0  # mm

    def getDefaultLibraryId(self):
        net = self.Object
        lib_id = getattr(net, "DefaultLibraryId", "")
        if lib_id:
            return lib_id

        lib = hvaclib.get_active_hvac_library()
        if lib:
            return lib.id
        return ""

    def getDefaultLibrary(self):
        lib_id = self.getDefaultLibraryId()
        if not lib_id:
            return None
        reg = hvaclib.HVACLibraryService.get_hvac_library_registry()
        return reg.get_library(lib_id)

    def getDefaultSegmentProfile(self):
        net = self.Object
        profile = getattr(net, "DefaultSegmentProfile", "")
        if profile:
            return profile

        lib_id = self.getDefaultLibraryId()
        return hvaclib.HVACLibraryService.default_segment_profile_for_library(lib_id)

    def getDefaultAttachment(self):
        net = self.Object
        return str(getattr(net, "DefaultAttachment", "Center"))

    def getDefaultOffset(self):
        net = self.Object
        return FreeCAD.Vector(getattr(net, "DefaultOffset", FreeCAD.Vector(0, 0, 0)))

    ## Library defaults management

    def defaultSegmentSelection(self, kind="straight", flex=False):
        """
        Return network default segment library/profile/type.
        Used only when creating a new segment or resetting one to defaults.
        """
        library_id = self.getDefaultLibraryId()
        profile = self.getDefaultSegmentProfile()
        attachement = self.getDefaultAttachment()
        offset = self.getDefaultOffset()

        valid_profiles = hvaclib.HVACLibraryService.segment_profiles_for_library(library_id)
        if profile not in valid_profiles:
            profile = hvaclib.HVACLibraryService.default_segment_profile_for_library(library_id)

        # A spline route (flex) gets a flexible duct when the library has one for this profile.
        selection = hvaclib.HVACLibraryService.select_segment_type(
            library_id, profile, curved=(kind != "straight"), flex=flex
        )
        type_id = selection.type_def.id if selection.type_def else ""

        return {
            "library_id": library_id,
            "profile": profile,
            "type_id": type_id,
            "attachment": attachement,
            "offset": offset,
        }

    @staticmethod
    def applyNetworkTypeDefaults(
        network_obj,
        library_id=None,
        segment_profile=None,
        default_attachment=None,
        default_offset=None,
        default_diameter=None,
        default_width=None,
        default_height=None,
        default_materials_by_role=None,
    ):
        """
        Apply network-level default type settings.
        (Used as callback for command)

        default_materials_by_role: optional {role: material} -- only the
        roles actually present are written (keyed by a ROLE_* string from
        library/construction.py; see role_property_suffix() for the
        DefaultMaterial_<Role> property each maps to).
        """
        if network_obj is None:
            return

        changed = False

        if library_id is not None and getattr(network_obj, "DefaultLibraryId", "") != str(library_id):
            network_obj.DefaultLibraryId = str(library_id)
            changed = True

        if segment_profile is not None and getattr(network_obj, "DefaultSegmentProfile", "") != str(segment_profile):
            network_obj.DefaultSegmentProfile = str(segment_profile)
            changed = True

        if default_attachment is not None and str(getattr(network_obj, "DefaultAttachment", "Center")) != str(
            default_attachment
        ):
            network_obj.DefaultAttachment = str(default_attachment)
            changed = True

        if default_offset is not None and FreeCAD.Vector(
            getattr(network_obj, "DefaultOffset", FreeCAD.Vector(0, 0, 0))
        ) != FreeCAD.Vector(default_offset):
            network_obj.DefaultOffset = FreeCAD.Vector(default_offset)
            changed = True

        if (
            default_diameter is not None
            and abs(float(getattr(network_obj, "DefaultDiameter", 100.0)) - float(default_diameter)) > 1e-9
        ):
            network_obj.DefaultDiameter = float(default_diameter)
            changed = True

        if (
            default_width is not None
            and abs(float(getattr(network_obj, "DefaultWidth", 100.0)) - float(default_width)) > 1e-9
        ):
            network_obj.DefaultWidth = float(default_width)
            changed = True

        if (
            default_height is not None
            and abs(float(getattr(network_obj, "DefaultHeight", 100.0)) - float(default_height)) > 1e-9
        ):
            network_obj.DefaultHeight = float(default_height)
            changed = True

        for role, material in dict(default_materials_by_role or {}).items():
            prop_name = "DefaultMaterial_" + role_property_suffix(role)
            if not hasattr(network_obj, prop_name):
                continue
            if material is None:
                material = hvac_materials.get_unassigned_material()
            if material is not None:
                setattr(network_obj, prop_name, material)
                changed = True

        if changed:
            network_obj.touch()
            if network_obj.Document:
                network_obj.Document.recompute()

        return changed

    @staticmethod
    def resetObjectsToNetworkDefaults(objects):
        """
        Reset selected segment/junction objects to their owner network defaults.
        An object already at its defaults is left alone (not rebuilt).
        """
        doc = FreeCAD.ActiveDocument
        if doc is None:
            return

        any_changed = False

        for obj in objects or []:
            if obj is None:
                continue
            # Per object: only one that really changed is rebuilt.
            changed = False

            # A DuctJunction has no type of its own any more -- retarget to
            # its Primary DuctComponent so "reset to defaults" on a selected
            # junction node does something useful. There's no automatic
            # default for a user-added Inline component (it was a deliberate
            # choice, not something the classifier picked), so those are
            # simply skipped.
            if hvaclib.isDuctJunction(obj):
                obj = obj.Proxy.getPrimaryComponent()
                if obj is None:
                    continue
            elif hvaclib.isDuctComponent(obj) and getattr(obj, "ComponentRole", "") != "Primary":
                continue

            net = DuctNetwork.getOwnerNetwork(obj)
            if net is None:
                continue

            default_lib = net.Proxy.getDefaultLibrary()
            if default_lib is None:
                continue

            proxy = getattr(obj, "Proxy", None)

            if hvaclib.isDuctSegment(obj):
                default_profile = net.Proxy.getDefaultSegmentProfile()
                if not default_profile:
                    default_profile = hvaclib.HVACLibraryService.default_segment_profile_for_library(default_lib.id)

                kind = hvaclib.BaseCurveKind(obj.SourceObjectName, obj.SourceIndex)
                # Explicit reset always runs fresh automatic selection against
                # the network's default library -- it may replace an otherwise
                # sticky manual TypeId, unlike normal sync (see
                # HVACLibraryRegistry.resolve_sticky_type).
                selection = hvaclib.HVACLibraryService.select_segment_type(
                    default_lib.id,
                    default_profile,
                    curved=(kind != "straight"),
                    flex=hvaclib.BaseCurveIsSpline(obj.SourceObjectName, obj.SourceIndex),
                )
                default_type_id = selection.type_def.id if selection.type_def else ""

                if hasattr(obj, "LibraryId") and obj.LibraryId != default_lib.id:
                    obj.LibraryId = default_lib.id
                    changed = True

                if hasattr(obj, "Profile") and obj.Profile != default_profile:
                    obj.Profile = default_profile
                    changed = True

                if hasattr(obj, "TypeId") and obj.TypeId != default_type_id:
                    obj.TypeId = default_type_id
                    changed = True

                default_attachment = net.Proxy.getDefaultAttachment()
                if getattr(obj, "Attachment", "Center") != default_attachment:
                    obj.Attachment = default_attachment
                    changed = True

                default_offset = net.Proxy.getDefaultOffset()
                if FreeCAD.Vector(getattr(obj, "Offset", FreeCAD.Vector(0, 0, 0))) != default_offset:
                    obj.Offset = default_offset
                    changed = True

            elif hvaclib.isDuctComponent(obj):
                parent = doc.getObject(getattr(obj, "ParentJunctionName", ""))
                if parent is None:
                    continue
                topology = getattr(parent, "Topology", "")
                family_key = getattr(parent, "Family", "")
                try:
                    analysis = json.loads(getattr(parent, "AnalysisJson", "") or "{}")
                except Exception:
                    analysis = {}
                connected_ports = list(analysis.get("connected_ports", []) or [])
                profile = hvaclib.HVACLibraryService.match_profile_from_ports(connected_ports)
                match_context = {
                    "flow_class": analysis.get("flow_class", ""),
                    "qualifiers": dict(analysis.get("qualifiers", {}) or {}),
                    "derived_values": dict(analysis.get("derived_values", {}) or {}),
                }

                # Explicit reset always runs fresh automatic selection against
                # the network's default library -- see the segment branch above.
                selection = hvaclib.HVACLibraryService.select_junction_type(
                    default_lib.id,
                    topology=topology,
                    family_key=family_key,
                    profile=profile,
                    connected_ports=connected_ports,
                    context=match_context,
                )
                default_type_id = selection.type_def.id if selection.type_def else ""

                if hasattr(obj, "LibraryId") and obj.LibraryId != default_lib.id:
                    obj.LibraryId = default_lib.id
                    changed = True

                if hasattr(obj, "TypeId") and obj.TypeId != default_type_id:
                    obj.TypeId = default_type_id
                    changed = True

            if proxy and hasattr(proxy, "applyTypeSchema"):
                try:
                    changed = proxy.applyTypeSchema() or changed
                except Exception:
                    pass

            # Explicit reset always re-applies the network's current default
            # materials -- unlike apply_default_layer_materials() (only
            # fills in a material a *new* object/layer doesn't have yet),
            # this discards whatever material each construction layer
            # already had, same "reset always wins" convention as
            # LibraryId/TypeId above. Runs after applyTypeSchema() so
            # ConstructionLayerIds reflects whatever type was just reset to.
            if _construction_schema.reset_layer_materials_to_network_defaults(obj):
                changed = True

            if changed:
                any_changed = True
                try:
                    obj.touch()
                except Exception:
                    pass

        if any_changed:
            doc.recompute()

    ## Object Management

    @staticmethod
    def createObject(name):
        from ..ui.NetworkViewProvider import DuctNetworkViewProvider

        net = FreeCAD.ActiveDocument.addObject("App::DocumentObjectGroupPython", name)
        DuctNetwork(net)
        DuctNetworkViewProvider(net.ViewObject)
        return net

    def addBaseObject(self, obj):
        net = self.Object
        if not net or not obj:
            return False
        if not hasattr(net, "Base") or net.Base is None:
            return False
        if not hasattr(obj, "Document") or obj.Document is None:
            return False
        if net.Document != obj.Document:
            return False
        if not (hvaclib.isSketch(obj) or hvaclib.isWire(obj)):
            return False
        if obj in net.Base.OutList:
            return False

        net.Base.addObject(obj)
        if getattr(net, "Proxy", None):
            net.Proxy.requestSync()
        net.Document.recompute()
        return True

    def addVirtualJunctionObject(self, member_node_keys, member_points):
        obj = self.Object
        doc = obj.Document
        name = doc.getUniqueObjectName("VirtualJunction")
        vj = DuctJunctionVirtual.create(
            doc, name, owner=obj, member_node_keys=member_node_keys, member_points=member_points
        )
        obj.Topology.addObject(vj)
        return vj

    def removeBaseObject(self, obj):
        net = self.Object
        if not net or not obj:
            return False
        if not hasattr(net, "Base") or net.Base is None:
            return False
        if net.Document != getattr(obj, "Document", None):
            return False
        if obj not in net.Base.OutList:
            return False

        net.Base.removeObject(obj)
        if getattr(net, "Proxy", None):
            net.Proxy.requestSync()
        net.Document.recompute()
        return True

    def removeGeometryObject(self, obj):
        """Remove a derived geometry object from the Geometry folder and document."""
        net = self.Object
        # A junction owns its DuctComponent children -- deleting one must
        # cascade to delete them too, or they'd be left as orphaned objects
        # with a dangling ParentJunctionName.
        if hvaclib.isDuctJunction(obj) and getattr(obj, "Proxy", None):
            for comp in list(obj.Proxy.getComponents()):
                self.removeGeometryObject(comp)
        if (hvaclib.isDuctSegment(obj) or hvaclib.isDuctJunction(obj) or hvaclib.isDuctComponent(obj)) and getattr(
            obj, "Proxy", None
        ):
            obj.Proxy._allow_delete = True
        if hasattr(net, "Geometry") and net.Geometry and obj in net.Geometry.OutList:
            net.Geometry.removeObject(obj)
        net.Document.removeObject(obj.Name)
        return True

    def collectSegmentObjects(self):
        net = self.Object
        segments = {}
        geometry = getattr(net, "Geometry", None)
        if geometry is None:
            return segments
        for child in list(geometry.OutList):
            if not hvaclib.isDuctSegment(child):
                continue
            key = getattr(child, "SegmentKey", "")
            if not key and getattr(child, "SourceObjectName", ""):
                key = hvaclib.makeLineKey(child.SourceObjectName, child.SourceIndex)
            if key:
                segments[key] = child
        return segments

    def collectJunctionObjects(self):
        net = self.Object
        junctions = {}
        geometry = getattr(net, "Geometry", None)
        if geometry is None:
            return junctions
        for child in list(geometry.OutList):
            if not hvaclib.isDuctJunction(child):
                continue
            key = getattr(child, "NodeKey", "")
            if key:
                junctions[key] = child
        return junctions

    def collectComponentObjects(self):
        """{parent_junction_name: [component_obj, ...]}, Primary-first then
        Inline grouped by AttachedEdgeKey/PortSequence -- built once per
        sync so syncJunctionComponents doesn't rescan Geometry per node."""
        net = self.Object
        by_parent = {}
        geometry = getattr(net, "Geometry", None)
        if geometry is None:
            return by_parent
        for child in list(geometry.OutList):
            if not hvaclib.isDuctComponent(child):
                continue
            by_parent.setdefault(getattr(child, "ParentJunctionName", ""), []).append(child)
        for lst in by_parent.values():
            lst.sort(
                key=lambda c: (
                    0 if getattr(c, "ComponentRole", "") == "Primary" else 1,
                    getattr(c, "AttachedEdgeKey", ""),
                    int(getattr(c, "PortSequence", 0)),
                    c.Name,
                )
            )
        return by_parent

    def collectVirtualJunctionObjects(self):
        topology_objs = []
        for child in list(getattr(self.Object.Topology, "Group", []) or []):
            if hvaclib.isDuctJunctionVirtual(child):
                topology_objs.append(child)
        return topology_objs

    def getNodeGroups(self, parser):
        """
        Compile node groups from virtual junction objects and the parser's
        node ID map, plus one group per custom fitting whose ports two or more
        duct ends sit on (those ends become one junction: see autoAttach).
        """
        from . import _auto_attach

        node_groups = []

        node_id_by_key = {parser.geometric_node_key(nid): nid for nid in parser.geometric_nodes()}
        virtual_objs = self.collectVirtualJunctionObjects()

        for vj in virtual_objs:
            keys = vj.Proxy.getMemberNodeKeys()
            ids = []

            for key in keys:
                nid = node_id_by_key.get(key)
                if nid is not None:
                    ids.append(nid)

            ids = sorted(set(ids))
            if len(ids) >= 2:
                node_groups.append(ids)

        for ids in _auto_attach.fitting_groups(self._portMatches(parser)).values():
            if len(ids) >= 2:
                node_groups.append(list(ids))

        return node_groups

    def sourceFeedsAir(self):
        """
        True when this network's Source pushes air into its ducts, False when
        it draws air out: from the equipment ports connected to the network,
        else from its SystemType (_terminal_function.source_feeds_air).
        """
        from . import Equipment

        net = self.Object
        doc = net.Document
        functions = []
        for equipment in Equipment.equipment_for_network(net):
            for connection in Equipment.connections_of(equipment):
                marker = doc.getObject(connection["port"]) if connection["network"] == net.Name else None
                if marker is not None:
                    functions.append(str(getattr(marker, "EquipmentPortFunction", "") or ""))
        return _terminal_function.source_feeds_air(getattr(net, "SystemType", "Supply"), functions)

    def _portSpots(self):
        """Every equipment and custom fitting port marker in the document, as _auto_attach.PortSpot."""
        from . import Equipment, _auto_attach, _custom_fitting

        doc = self.Object.Document
        spots = []
        for obj in getattr(doc, "Objects", []):
            if Equipment.is_equipment(obj):
                kind, markers = _auto_attach.KIND_EQUIPMENT, Equipment.equipment_ports(obj)
            elif _custom_fitting.is_custom_fitting(obj):
                kind, markers = _auto_attach.KIND_FITTING, _custom_fitting.container_ports(obj)
            else:
                continue
            for marker in markers:
                try:
                    position = hvaclib.vec_to_xyz(marker.getGlobalPlacement().Base)
                except Exception:
                    continue
                spots.append(_auto_attach.PortSpot(obj.Name, kind, marker.Name, position))
        return spots

    def _portMatches(self, parser):
        """[(geometric node id, PortSpot), ...]: the open duct ends (one duct only) that sit on a port marker."""
        from . import _auto_attach

        spots = self._portSpots()
        if not spots or parser.graph is None:
            return []
        open_ends = {
            node_id: point
            for node_id, point in parser.geometric_node_point_map().items()
            if parser.graph.degree(node_id) == 1
        }
        return _auto_attach.match_open_ends(open_ends, spots)

    def autoAttach(self, parser):
        """
        Attach the equipment and custom fittings whose ports this network's
        duct ends sit on (run after syncJunctions, so the junctions exist):

        - the junction made of the ends on one custom fitting's ports takes
          that fitting's geometry in place (once; later edits are kept);
        - an end on an equipment port is connected to it (Equipment.connect),
          and connections to nodes that no longer exist are dropped.

        Returns True when anything changed.
        """
        from . import Equipment, _auto_attach, _custom_fitting

        net = self.Object
        doc = net.Document
        matches = self._portMatches(parser)
        junctions = self.collectJunctionObjects()
        changed = False

        def junction_at(geom_node_id):
            analysis_node_id = parser.analysis_node_by_geom_node.get(geom_node_id)
            if analysis_node_id is None:
                return None
            return junctions.get(parser.node_key(analysis_node_id))

        # Step 1: custom fittings -- the junction holding their ends takes their geometry.
        for owner, node_ids in _auto_attach.fitting_groups(matches).items():
            container = doc.getObject(owner)
            junction = junction_at(node_ids[0])
            if container is None or junction is None:
                continue
            if _custom_fitting.attach_in_place(junction.Proxy.getPrimaryComponent(), container):
                changed = True
                FreeCAD.Console.PrintMessage(
                    "HVAC - '{}' attached to custom fitting '{}'\n".format(junction.Label, container.Label)
                )

        # Step 2: equipment -- forget connections to nodes that are gone, then connect new ends.
        live_keys = set(junctions.keys())
        for obj in getattr(doc, "Objects", []):
            if Equipment.is_equipment(obj):
                changed = Equipment.prune_connections(obj, net.Name, live_keys) or changed
        for node_id, spot in _auto_attach.equipment_matches(matches):
            equipment = doc.getObject(spot.owner)
            marker = doc.getObject(spot.marker)
            junction = junction_at(node_id)
            if equipment is None or marker is None or junction is None:
                continue
            if getattr(junction, "Topology", "") != "end":
                continue
            if Equipment.is_connected(equipment, marker, net, junction):
                continue
            try:
                warnings = Equipment.connect(equipment, marker, junction)
            except ValueError as err:
                FreeCAD.Console.PrintWarning("HVAC - Connect to Equipment: {}\n".format(err))
                continue
            changed = True
            for warning in warnings:
                FreeCAD.Console.PrintWarning("HVAC - Connect to Equipment: {}\n".format(warning))
            FreeCAD.Console.PrintMessage(
                "HVAC - '{}' connected to {} port '{}'\n".format(junction.Label, equipment.Label, marker.Label)
            )
        return changed

    def setActive(self):
        """Set this DuctNetwork as the active container in the 3D view."""
        import FreeCADGui as Gui

        Gui.ActiveDocument.ActiveView.setActiveObject(DuctNetwork.CONTEXT_KEY, self.Object)

    @staticmethod
    def _setGeometryVisibilityDeferred(obj, visible):
        if not FreeCAD.GuiUp:
            return

        from PySide import QtCore

        def apply():
            try:
                if obj is None or getattr(obj, "Document", None) is None:
                    return
                vobj = getattr(obj, "ViewObject", None)
                if vobj is None:
                    return
                vobj.Visibility = bool(visible)
            except Exception:
                pass

        QtCore.QTimer.singleShot(0, apply)

    def _selectGeometry(self, predicate):
        """Clear the current selection, then select every Geometry-folder
        child for which predicate(child) is True. Shared by
        selectAllGeometry/selectAllSegments/selectAllComponents below."""
        import FreeCADGui as Gui

        net = self.Object
        Gui.Selection.clearSelection()

        for child in net.Geometry.OutList:
            if not predicate(child):
                continue
            try:
                Gui.Selection.addSelection(child)
            except TypeError:
                Gui.Selection.addSelection(child.Document.Name, child.Name)

    def selectAllGeometry(self):
        """Select all generated duct objects under the Geometry folder."""
        self._selectGeometry(
            lambda child: (
                hvaclib.isDuctSegment(child) or hvaclib.isDuctJunction(child) or hvaclib.isDuctComponent(child)
            )
        )

    def selectAllSegments(self):
        """Select every DuctSegment under the Geometry folder."""
        self._selectGeometry(hvaclib.isDuctSegment)

    def selectAllComponents(self):
        """Select every DuctComponent (Primary and Inline fittings) under the Geometry folder."""
        self._selectGeometry(hvaclib.isDuctComponent)

    def showAllGeometry(self):
        geometry = self.Object.Geometry
        if getattr(geometry, "ViewObject", None):
            try:
                geometry.ViewObject.Visibility = True
            except Exception:
                pass

        for obj in list(geometry.OutList):
            if hvaclib.isDuctSegment(obj) or hvaclib.isDuctJunction(obj) or hvaclib.isDuctComponent(obj):
                self._setGeometryVisibilityDeferred(obj, True)

    def hideAllGeometry(self):
        geometry = self.Object.Geometry

        if getattr(geometry, "ViewObject", None):
            try:
                geometry.ViewObject.Visibility = False
            except Exception:
                pass

        for obj in list(geometry.OutList):
            if hvaclib.isDuctSegment(obj) or hvaclib.isDuctJunction(obj) or hvaclib.isDuctComponent(obj):
                self._setGeometryVisibilityDeferred(obj, False)

    def _segmentFromBaseObject(self, seg, base_obj):
        return (
            seg is not None
            and base_obj is not None
            and hvaclib.isDuctSegment(seg)
            and getattr(seg, "SourceObjectName", "") == base_obj.Name
        )

    def showAllJunctionGeometry(self):
        # DuctJunction itself has no Shape/visual presence any more -- the
        # thing that actually needs hiding/showing while editing base
        # geometry is each junction's DuctComponent children.
        for obj in list(self.Object.Geometry.OutList):
            if hvaclib.isDuctComponent(obj):
                self._setGeometryVisibilityDeferred(obj, True)

    def hideAllJunctionGeometry(self):
        for obj in list(self.Object.Geometry.OutList):
            if hvaclib.isDuctComponent(obj):
                self._setGeometryVisibilityDeferred(obj, False)

    def showGeometryForBaseObject(self, base_obj):
        net = self.Object
        geometry = getattr(net, "Geometry", None)
        if geometry is None or base_obj is None:
            return
        for seg in list(geometry.OutList):
            if self._segmentFromBaseObject(seg, base_obj):
                self._setGeometryVisibilityDeferred(seg, True)

    def hideGeometryForBaseObject(self, base_obj):
        net = self.Object
        geometry = getattr(net, "Geometry", None)
        if geometry is None or base_obj is None:
            return
        for seg in list(geometry.OutList):
            if self._segmentFromBaseObject(seg, base_obj):
                self._setGeometryVisibilityDeferred(seg, False)

    def setBaseObjectEditing(self, base_obj, editing):
        net = self.Object
        if net is None or base_obj is None:
            return
        if editing:
            self._hidden_source_names.add(base_obj.Name)
            self.hideGeometryForBaseObject(base_obj)
            self.hideAllJunctionGeometry()
        else:
            self._hidden_source_names.discard(base_obj.Name)
            self.showGeometryForBaseObject(base_obj)
            self.showAllJunctionGeometry()

    @staticmethod
    def isBaseObject(obj):
        if obj is None:
            return False
        if not (hvaclib.isSketch(obj) or hvaclib.isWire(obj)):
            return False

        for net in hvaclib.allHVACNetworks(obj.Document):
            base = getattr(net, "Base", None)
            if base and obj in base.OutList:
                return True
        return False

    @staticmethod
    def isGeometryObject(obj):
        return hvaclib.isDuctJunction(obj) or hvaclib.isDuctSegment(obj) or hvaclib.isDuctComponent(obj)

    @staticmethod
    def getOwnerNetwork(obj):
        """Return the owning duct network document object for an internal object."""
        if DuctNetwork.isGeometryObject(obj):
            owner_name = getattr(obj, "OwnerNetworkName", "")
            doc = getattr(obj, "Document", None)
            if owner_name and doc:
                return doc.getObject(owner_name)
            return None
        elif DuctNetwork.isBaseObject(obj):
            for net in hvaclib.allHVACNetworks(obj.Document):
                base = getattr(net, "Base", None)
                if base and obj in base.OutList:
                    return net
        return None

    @staticmethod
    def getOwnerBaseObject(obj):
        """Return the base object for a given geometry object."""
        if DuctNetwork.isGeometryObject(obj):
            owner_name = getattr(obj, "SourceObjectName", "")
            doc = getattr(obj, "Document", None)
            if owner_name and doc:
                return doc.getObject(owner_name)
        return None

    # Functions for syncing object data with the network parser

    def syncVirtualJunctions(self, parser, initial_sync=False):
        """Update the MemberNodes property of virtual junction objects
        from the actual node keys from parser."""
        obj = self.Object
        for vj in self.collectVirtualJunctionObjects():
            # Use quantized point keys to look up new node keys from parser
            stored_points = vj.Proxy.getMemberPoints()
            stored_keys = vj.Proxy.getMemberNodeKeys()
            # Get quantised nodemap from parser
            geo_nodekey_map = {
                parser.geometric_node_key(id): point for (id, point) in parser.geometric_node_point_map().items()
            }
            # Find nodekeys from nodemap
            member_keys = []
            member_points = []

            # If initial_sync, use stored points to udate modified keys
            if initial_sync:
                for key, point in geo_nodekey_map.items():
                    if hvaclib.vec_in_list(point, stored_points) and not hvaclib.vec_in_list(point, member_points):
                        member_keys.append(key)
                        member_points.append(point)
            # Else use stored keys to find updated points
            else:
                for key, point in geo_nodekey_map.items():
                    if key in stored_keys and key not in member_keys:
                        member_keys.append(key)
                        member_points.append(point)

            # Update the MemberNodeKeys property with the new node keys
            vj.Proxy.updateMetadata(owner=obj, member_node_keys=member_keys, member_points=member_points)

    def syncSegments(self, parser, initial_sync=False):
        """
        Synchronize derived DuctSegment objects with the base geometry.

        Segment LibraryId / Profile / TypeId are object-owned values.
        Network defaults are only used when creating a new segment or repairing
        missing/invalid values.
        """
        net = self.Object
        doc = net.Document
        geometry = getattr(net, "Geometry", None)
        if doc is None or geometry is None:
            return False

        default_lib = self.getDefaultLibrary()
        if default_lib is None:
            return False

        changed = False
        existing_segments = self.collectSegmentObjects()
        trim_map = self.collectSegmentTrimMap()
        live_objs = set()

        for edge_ref in parser.edges():
            key = edge_ref.tag

            source_obj = doc.getObject(edge_ref.obj_name)
            if source_obj is None:
                continue

            # Edge keys are stable across a reload (hvaclib.makeLineKey), so an
            # existing segment is always found by its key.
            segment_obj = existing_segments.get(key)

            # If segment does not exist, create a new one
            if segment_obj is None:
                segment_obj = DuctSegment.create(
                    doc,
                    "{}_Seg_{}_{}".format(net.Name, source_obj.Name, edge_ref.local_index),
                    owner=net,
                    key=key,
                    source_obj=source_obj,
                    source_index=edge_ref.local_index,
                )

                # Get and set default segment properties from default library
                kind = hvaclib.BaseCurveKind(edge_ref.obj_name, edge_ref.local_index)
                defaults = self.defaultSegmentSelection(
                    kind=kind, flex=hvaclib.BaseCurveIsSpline(edge_ref.obj_name, edge_ref.local_index)
                )
                if hasattr(segment_obj, "LibraryId"):
                    segment_obj.LibraryId = defaults["library_id"]
                if hasattr(segment_obj, "Profile"):
                    segment_obj.Profile = defaults["profile"]
                if hasattr(segment_obj, "TypeId"):
                    segment_obj.TypeId = defaults["type_id"]
                if hasattr(segment_obj, "Attachment"):
                    segment_obj.Attachment = defaults["attachment"]
                if hasattr(segment_obj, "Offset"):
                    segment_obj.Offset = defaults["offset"]

                changed = True

                # If source base object is marked to be hidden, hide the created segment geometry
                if source_obj.Name in self._hidden_source_names:
                    self._setGeometryVisibilityDeferred(segment_obj, False)
                else:
                    self._setGeometryVisibilityDeferred(segment_obj, True)

            # Add the segment object to the geometry folder if not already present
            if segment_obj not in geometry.OutList:
                geometry.addObject(segment_obj)
                changed = True

            live_objs.add(segment_obj)

            # Compute start and end points based on start/end nodes
            start_node, end_node = parser.edge_nodes(edge_ref)
            raw_start_point, raw_end_point = parser.edge_line(edge_ref)
            raw_sp_vec = FreeCAD.Vector(*raw_start_point)
            raw_ep_vec = FreeCAD.Vector(*raw_end_point)
            seg_dir = raw_ep_vec.sub(raw_sp_vec)
            if seg_dir.Length <= 1e-9:
                continue
            seg_dir.normalize()
            start_point = self.resolveSegmentEndpoint(raw_sp_vec, seg_dir, segment_obj)
            end_point = self.resolveSegmentEndpoint(raw_ep_vec, seg_dir, segment_obj)

            # Get trim start/end from the trim map, if available
            trim_entry = trim_map.get(key, {})
            trim_start, trim_end = self.resolveSegmentEndTrims(trim_entry)

            # Get library ID, profile and type_id for segment, defaulting to active library if not set
            library_id = getattr(segment_obj, "LibraryId", "") or self.getDefaultLibraryId()
            profile = getattr(segment_obj, "Profile", "")
            valid_profiles = hvaclib.HVACLibraryService.segment_profiles_for_library(library_id)
            if profile not in valid_profiles:
                profile = hvaclib.HVACLibraryService.default_segment_profile_for_library(library_id)

            kind = hvaclib.BaseCurveKind(edge_ref.obj_name, edge_ref.local_index)
            family = "straight_segment" if kind == "straight" else "curved_segment"

            # Sticky registry-driven selection: retain the current TypeId if
            # it's still a compatible real model, otherwise auto-select.
            current_type_id = getattr(segment_obj, "TypeId", "")
            selection = hvaclib.HVACLibraryService.resolve_segment_type(
                library_id,
                current_type_id,
                profile,
                curved=(kind != "straight"),
                flex=hvaclib.BaseCurveIsSpline(edge_ref.obj_name, edge_ref.local_index),
            )
            type_id = selection.type_def.id if selection.type_def else ""

            # Update metadata based on updated data
            meta_changed = segment_obj.Proxy.updateMetadata(
                owner=net,
                key=key,
                source_obj=source_obj,
                source_index=edge_ref.local_index,
                start_node=start_node,
                end_node=end_node,
                start_point=hvaclib.vec_to_xyz(start_point),
                end_point=hvaclib.vec_to_xyz(end_point),
                trim_start=trim_start,
                trim_end=trim_end,
                family=family,
                type_id=type_id,
                library_id=library_id,
                profile=profile,
            )
            changed = changed or meta_changed

            # Update property schema based on type ID and library ID
            schema_changed = segment_obj.Proxy.applyTypeSchema()
            changed = changed or schema_changed

            # If parameters were cached, restore them
            cached_params = self._runtime_param_cache.pop(key, None)
            if cached_params:
                restored = self._restoreSegmentUserParams(segment_obj, cached_params)
                changed = changed or restored

            # Update label for segment object based on source object and edge index.
            # Once HVAC_RenumberNetwork has assigned this segment a Number,
            # its Label is documentation-owned by that command instead --
            # a normal sync must never overwrite a "D012 -- ..." label back
            # to the plain unnumbered form.
            if not getattr(segment_obj, "Number", ""):
                new_label = DuctSegment.labelFor(source_obj, edge_ref.local_index)
                if hvaclib.set_label(segment_obj, new_label):
                    changed = True

        # Remove old segments
        for segment_obj in list(existing_segments.values()):
            if segment_obj not in live_objs:
                seg_key = getattr(segment_obj, "SegmentKey", "")
                # Cache segment parameters for later restoration during undo
                if seg_key:
                    self._runtime_param_cache[seg_key] = self._segmentUserParams(segment_obj)
                self.removeGeometryObject(segment_obj)
                changed = True

        return changed

    def syncJunctions(self, parser, initial_sync=False, rebuild_all=False):
        """
        rebuild_all: mark every component for recompute (the first sync of a
        loaded document, a library reload); otherwise only the components of
        a junction that is new or whose classification changed are marked.

        Synchronize derived DuctJunction objects with parser nodes, and
        (via syncJunctionComponents) each junction's Primary/Inline
        DuctComponent children.

        A DuctJunction itself carries no LibraryId/TypeId any more -- see
        syncJunctionComponents for how the Primary component's type is
        resolved/retained and how the component chain is composed.
        """
        net = self.Object
        doc = net.Document
        geometry = getattr(net, "Geometry", None)
        if doc is None or geometry is None:
            return False

        changed = False
        live_objs = set()

        # Get default library for segment profiles
        default_lib = self.getDefaultLibrary()
        if default_lib is None:
            return False

        # Collect existing junctions, their components, and the segment map
        existing_junctions = self.collectJunctionObjects()
        components_by_parent = self.collectComponentObjects()
        segment_map = self.collectSegmentObjects()

        # Which way this network's Source moves air (an equipment port connected to it decides).
        feeds = self.sourceFeedsAir()

        # Inspect each node from the parser and update junction objects
        for node_id in parser.nodes():
            node_key = parser.node_key(node_id)

            # Get junction analysis
            junction_analysis = parser.build_junction_analysis(node_id, segment_map)
            if not junction_analysis:
                continue
            if junction_analysis.topology == "end":
                # The terminal's function (6.5) joins the classification, so
                # type constraints, loss variants and the Edit Type list see it.
                known = existing_junctions.get(node_key)
                junction_analysis.qualifiers["terminal_function"] = _terminal_function.resolve(
                    getattr(net, "SystemType", "Supply"),
                    getattr(known, "TerminalFunction", "Auto") if known is not None else "Auto",
                    getattr(known, "FlowBoundary", "Auto") if known is not None else "Auto",
                    junction_analysis.flow_class,
                    feeds,
                )
            analysis_dict = asdict(junction_analysis)
            analysis_json = json.dumps(analysis_dict)
            connected_ports = analysis_dict["connected_ports"]
            degree = junction_analysis.degree
            topology = junction_analysis.topology
            family = junction_analysis.family_key
            point = junction_analysis.point
            connected_edge_keys = [p.edge_key for p in junction_analysis.connected_ports]
            match_profile = hvaclib.HVACLibraryService.match_profile_from_ports(connected_ports)
            flow_class = junction_analysis.flow_class
            qualifiers = junction_analysis.qualifiers
            derived_values = junction_analysis.derived_values

            # If initial sync, the tags are regenerated hence find element based on position
            # Also update the existing junction's key in the dictionary with the modified key
            if initial_sync:
                junction_obj = None
                matched_old_key = None
                for old_key, junc in existing_junctions.items():
                    if hvaclib.vec_quant(junc.CenterPoint) == hvaclib.vec_quant(point):
                        junction_obj = junc
                        matched_old_key = old_key
                        break

                if matched_old_key is not None and matched_old_key != node_key:
                    existing_junctions.pop(matched_old_key, None)
                    existing_junctions[node_key] = junction_obj
                    # components_by_parent is keyed by the junction OBJECT's
                    # own .Name (ParentJunctionName), not by NodeKey -- that
                    # never changes across a resync, so no remapping is
                    # needed here (unlike existing_junctions, which really is
                    # keyed by NodeKey).
            # Else find element based on key
            else:
                junction_obj = existing_junctions.get(node_key)

            is_new_junction = junction_obj is None

            # If junction does not exist, create a new one
            if junction_obj is None:
                junction_obj = DuctJunction.create(
                    doc,
                    "{}_Junc_{}".format(net.Name, node_id),
                    owner=net,
                    node_id=node_id,
                    node_key=node_key,
                    center_point=point,
                    degree=degree,
                    topology=topology,
                )
                changed = True

            # Add junction to geometry folder if not already present
            if junction_obj not in geometry.OutList:
                geometry.addObject(junction_obj)
                changed = True

            live_objs.add(junction_obj)

            # Update metadata based on updated data
            meta_changed = junction_obj.Proxy.updateMetadata(
                owner=net,
                node_id=node_id,
                node_key=node_key,
                center_point=point,
                degree=degree,
                topology=topology,
                family=family,
                connected_edge_keys=connected_edge_keys,
                analysis_json=analysis_json,
            )
            changed = changed or meta_changed

            # Create/update this junction's Primary component (sticky type
            # resolution), retain its Inline components, and compose the
            # whole chain's local ports.
            components_changed = self.syncJunctionComponents(
                junction_obj,
                topology,
                family,
                match_profile,
                connected_ports,
                components_by_parent.get(junction_obj.Name, []),
                default_lib,
                hide_new=bool(self._hidden_source_names) if is_new_junction else None,
                flow_class=flow_class,
                qualifiers=qualifiers,
                derived_values=derived_values,
                rebuild=rebuild_all or initial_sync or is_new_junction or meta_changed,
            )
            changed = changed or components_changed

            # Update label for junction object based on classified family.
            # Once HVAC_RenumberNetwork has assigned this junction a Number,
            # its Label is documentation-owned by that command instead -- see
            # the matching comment in syncSegments.
            if not getattr(junction_obj, "Number", ""):
                new_label = DuctJunction.labelFor(family, node_id)
                if hvaclib.set_label(junction_obj, new_label):
                    changed = True

        # Remove old junctions
        for junction_obj in list(existing_junctions.values()):
            if junction_obj not in live_objs:
                self.removeGeometryObject(junction_obj)
                changed = True

        return changed

    def syncJunctionComponents(
        self,
        junction_obj,
        topology,
        family,
        match_profile,
        connected_ports,
        existing_components,
        default_lib,
        hide_new=None,
        flow_class="",
        qualifiers=None,
        derived_values=None,
        rebuild=False,
    ):
        """
        Create/update a junction's Primary DuctComponent (sticky type
        resolution, same registry policy the junction itself used to run
        directly) and compose the whole component chain's local ports.

        Inline components are never auto-selected/replaced here -- they're
        retained as-is (only their type schema is re-applied, in case a
        library reload changed their declared properties). Each Inline
        component is retained only while its own AttachedEdgeKey is still
        one of this junction's real edges -- if that edge disappears (a
        topology/geometry change resnapped or removed it), that component
        is deleted with a console warning rather than left silently
        orphaned. A junction losing its through/2-port shape no longer
        drops Inline components on its own -- each edge's chain is
        independent of the junction's overall topology.

        Edge keys are stable across a document reload (hvaclib.makeLineKey),
        so AttachedEdgeKey, CustomLossCoefficientEdgeKeys, CustomPortEdgeKeys
        and the per-port property key lists stay valid as stored.
        """
        net = self.Object
        doc = net.Document
        geometry = net.Geometry
        changed = False

        # Defensive: a junction should never end up with more than one
        # Primary component, but self-heal if it somehow does (e.g. a
        # document synced under a since-fixed lookup bug) rather than
        # silently treating extras as an Inline-like chain.
        primaries = [c for c in existing_components if getattr(c, "ComponentRole", "") == "Primary"]
        primary = None
        if primaries:
            primaries.sort(key=lambda c: c.Name)
            primary = primaries[0]
            extras = primaries[1:]
            if extras:
                FreeCAD.Console.PrintWarning(
                    "HVAC - Junction '{}' had {} duplicate Primary component(s); removing the extras.\n".format(
                        junction_obj.Label, len(extras)
                    )
                )
                for comp in extras:
                    self.removeGeometryObject(comp)
                changed = True

        real_edge_keys = {p.get("edge_key") for p in connected_ports}
        inline_components = [c for c in existing_components if getattr(c, "ComponentRole", "") == "Inline"]

        keep, drop = [], []
        for comp in inline_components:
            (keep if getattr(comp, "AttachedEdgeKey", "") in real_edge_keys else drop).append(comp)

        if drop:
            FreeCAD.Console.PrintWarning(
                "HVAC - Junction '{}' no longer has edge(s) {}; removing {} inline component(s).\n".format(
                    junction_obj.Label, sorted({getattr(c, "AttachedEdgeKey", "") for c in drop}), len(drop)
                )
            )
            for comp in drop:
                self.removeGeometryObject(comp)
            changed = True
        inline_components = keep

        if primary is None:
            primary = DuctComponent.create(
                doc,
                "{}_Comp0".format(junction_obj.Name),
                parent_junction=junction_obj,
                role="Primary",
                attached_edge_key="",
                port_sequence=0,
                owner_network=net,
            )
            # DuctComponent.create()'s own setProperties() seeds LibraryId
            # from the registry's global "active" library (whichever loaded
            # first) as a generic object-creation default -- override it
            # with this network's actual configured default library, the
            # same way syncSegments() does for a newly-created segment.
            if hasattr(primary, "LibraryId"):
                primary.LibraryId = default_lib.id
            changed = True
            if hide_new is not None:
                self._setGeometryVisibilityDeferred(primary, not hide_new)

        if primary not in geometry.OutList:
            geometry.addObject(primary)
            changed = True

        # Sticky registry-driven selection: retain the Primary's current
        # TypeId if it's still a compatible real model, otherwise
        # auto-select (falling back to a placeholder if no model matches).
        # This is exactly the policy DuctJunction itself used to run
        # directly before LibraryId/TypeId moved onto the Primary component.
        library_id = getattr(primary, "LibraryId", "") or default_lib.id
        current_type_id = getattr(primary, "TypeId", "")
        match_context = {
            "flow_class": flow_class,
            "qualifiers": dict(qualifiers or {}),
            "derived_values": dict(derived_values or {}),
        }
        selection = hvaclib.HVACLibraryService.resolve_junction_type(
            library_id,
            current_type_id,
            topology=topology,
            family_key=family,
            profile=match_profile,
            connected_ports=connected_ports,
            context=match_context,
        )
        type_id = selection.type_def.id if selection.type_def else ""

        meta_changed = primary.Proxy.updateMetadata(
            parent_junction=junction_obj,
            role="Primary",
            attached_edge_key="",
            port_sequence=0,
            library_id=library_id,
            type_id=type_id,
        )
        changed = changed or meta_changed

        schema_changed = primary.Proxy.applyTypeSchema()
        changed = changed or schema_changed

        # What follows (labels, re-applied inline schemas that did not change)
        # does not alter any geometry: decide the rebuild on what changed so far.
        rebuild = rebuild or changed

        # Once HVAC_RenumberNetwork has assigned this Primary component a
        # Number, its Label is documentation-owned by that command instead --
        # see the matching comment in syncSegments.
        if not getattr(primary, "Number", ""):
            new_label = DuctComponent.labelFor("Primary", selection.type_def.label if selection.type_def else "")
            if hvaclib.set_label(primary, new_label):
                changed = True

        # Inline components are retained as-is (never auto-replaced) --
        # just re-apply their schema in case their type's declared
        # properties changed underneath them (e.g. a library reload).
        for comp in inline_components:
            if comp not in geometry.OutList:
                geometry.addObject(comp)
                changed = True
            if comp.Proxy.applyTypeSchema():
                changed = True
                rebuild = True

        # Build the ordered chain and write each component's local ports
        # (only the ports that changed are written, and a written property
        # marks its component for recompute by itself).
        junction_obj.Proxy.composeComponents()

        # A component's geometry depends on its own properties and ports
        # (FreeCAD marks it when either is written) and on its junction's
        # classification, which it reads without a link. So rebuild this
        # junction's components only when that classification or the
        # component set changed, or when the caller asks for everything;
        # touching every component on every sync rebuilt the whole network
        # for any edit.
        if rebuild:
            for comp in junction_obj.Proxy.getComponents():
                comp.touch()

        return changed

    def refreshBaseDirectionOverlay(self, parser):
        obj = self.Object
        try:
            if FreeCAD.GuiUp:
                vp = obj.ViewObject.Proxy
                vp.refreshBaseDirectionArrows(parser)
        except Exception:
            FreeCAD.Console.PrintError("Error refreshing base direction overlay.\n")

    def requestSync(self, initial_sync=None, force_recompute=False, rebuild_all=False):
        """
        Schedule a sync. rebuild_all also rebuilds every fitting, whether or
        not its inputs changed (after a library reload); a normal sync only
        rebuilds what changed.
        """
        from PySide import QtCore

        if initial_sync is not None:
            self._initial_sync = bool(initial_sync)
        if rebuild_all:
            self._rebuild_all = True

        if self._sync_suspended:
            return

        if self._sync_scheduled:
            return

        self._sync_scheduled = True
        if initial_sync:
            FreeCAD.Console.PrintMessage("HVAC - Sync requested (Initial sync).\n")
        else:
            FreeCAD.Console.PrintMessage("HVAC - Sync requested.\n")
        QtCore.QTimer.singleShot(0, lambda force_recompute=force_recompute: self._runDeferredSync(force_recompute))

    def deferEditSync(self):
        """Note a property edit made inside an open transaction: runEditSync() syncs once it closes."""
        self._edit_sync_pending = True

    def runEditSync(self):
        """Run the sync deferred by deferEditSync(), if any (the transaction it waited for has closed)."""
        if not getattr(self, "_edit_sync_pending", False):
            return
        self._edit_sync_pending = False
        self.requestSync(force_recompute=True)

    def suspendSync(self):
        self._sync_suspended = True

    def resumeSync(self, request_sync=True):
        self._sync_suspended = False
        if request_sync:
            self.requestSync()

    def getParser(self, rebuild=False, set_node_groups=True):
        if self._parser is None or rebuild:
            parser = DuctNetworkParser(list(self.Object.Base.OutList))
            if set_node_groups:
                node_groups = self.getNodeGroups(parser)
                parser.set_node_groups(node_groups)
            self._parser = parser
        return self._parser

    def aggregateAllConnectionLengths(self):
        """
        Refresh every live junction's aggregate ConnectionLengthsJson from
        its component chain (see DuctJunction.aggregateConnectionLengths).
        Run after a recompute so each component's own execute() has had a
        chance to write its own ConnectionLengthsJson first.
        """
        for junction_obj in self.collectJunctionObjects().values():
            proxy = getattr(junction_obj, "Proxy", None)
            if proxy is not None and hasattr(proxy, "aggregateConnectionLengths"):
                proxy.aggregateConnectionLengths()

    def _runDeferredSync(self, force_recompute=False):
        obj = self.Object
        self._sync_scheduled = False

        if obj is None or obj.Document is None:
            return
        if self._sync_in_progress:
            return

        self._sync_in_progress = True
        rebuild_all = bool(getattr(self, "_rebuild_all", False))
        self._rebuild_all = False
        force_recompute = force_recompute or rebuild_all
        try:
            if self._initial_sync:
                # Do not run junction update on initial sync since edge tags will not be updated in segments
                # Doing so will clear all junctions since edges could not be found

                # Get parser for syncing virtual junctions
                parser = self.getParser(rebuild=True, set_node_groups=False)
                # Update VirtualJunction keys
                self.syncVirtualJunctions(parser, initial_sync=True)
                # Rebuild parser after syncing virtual junctions
                parser = self.getParser(rebuild=True)

                # Stage 1: Sync segments first to update edge data after document reload
                self.syncSegments(parser, initial_sync=True)
                obj.Document.recompute()

                # Stage 2: Sync junctions/components, so that each component's
                # execute() writes its own ConnectionLengthsJson
                self.syncJunctions(parser, initial_sync=True)
                # Ducts drawn to equipment / custom fitting ports attach to them.
                self.autoAttach(parser)
                obj.Document.recompute()
                # Aggregate each junction's ConnectionLengthsJson from its
                # now-computed component chain, for Stage 3 to consume.
                self.aggregateAllConnectionLengths()

                # Stage 3: Sync segments which consume the junction trim data
                self.syncSegments(parser, initial_sync=False)
                obj.Document.recompute()

            else:
                # Get parser
                parser = self.getParser(rebuild=True, set_node_groups=False)
                # Update VirtualJunction keys
                self.syncVirtualJunctions(parser, initial_sync=False)
                # Rebuild parser after syncing virtual junctions
                parser = self.getParser(rebuild=True)

                # Stage 1: Sync segments first to update edge data
                changed_segments = self.syncSegments(parser, initial_sync=False)
                if changed_segments or force_recompute:
                    obj.Document.recompute()

                # Stage 2: Sync junctions/components, for creating ports; so
                # that each component's execute() writes its own
                # ConnectionLengthsJson
                changed_junctions = self.syncJunctions(parser, initial_sync=False, rebuild_all=rebuild_all)
                # Ducts drawn to equipment / custom fitting ports attach to them.
                changed_junctions = self.autoAttach(parser) or changed_junctions
                if changed_junctions or force_recompute:
                    obj.Document.recompute()
                # Aggregate each junction's ConnectionLengthsJson from its
                # now-computed component chain, for Stage 3 to consume.
                self.aggregateAllConnectionLengths()

                # Stage 3: Sync segments which consume the junction trim data
                changed_segments = self.syncSegments(parser, initial_sync=False)
                if changed_segments or force_recompute:
                    obj.Document.recompute()

            self._initial_sync = False

            # Refresh visual base direction arrows using the same parser
            self.refreshBaseDirectionOverlay(parser)

        except Exception as err:
            FreeCAD.Console.PrintError(traceback.format_exc())
            FreeCAD.Console.PrintError("HVAC - Failed to update network '{}': {}\n".format(obj.Label, err))
        finally:
            self._sync_in_progress = False

    @staticmethod
    def _segmentUserParams(obj):
        return {
            "LibraryId": str(getattr(obj, "LibraryId", "")),
            "Profile": str(getattr(obj, "Profile", "")),
            "TypeId": str(getattr(obj, "TypeId", "")),
            "Attachment": str(getattr(obj, "Attachment", "Center")),
            "Offset": hvaclib.vec_to_xyz(getattr(obj, "Offset", (0, 0, 0))),
            "ProfileXAxis": hvaclib.vec_to_xyz(getattr(obj, "ProfileXAxis", (0, 0, 0))),
            "Diameter": float(getattr(obj, "Diameter", 0.0)),
            "Width": float(getattr(obj, "Width", 0.0)),
            "Height": float(getattr(obj, "Height", 0.0)),
            "InsulationThickness": float(getattr(obj, "InsulationThickness", 0.0)),
            "Roughness": float(getattr(obj, "Roughness", 0.0)),
            "Velocity": float(getattr(obj, "Velocity", 0.0)),
            "RectangularSizingMode": str(getattr(obj, "RectangularSizingMode", "UseNetworkDefault")),
            "TargetAspectRatio": float(getattr(obj, "TargetAspectRatio", 0.0)),
        }

    @staticmethod
    def _restoreSegmentUserParams(obj, params):
        if not isinstance(params, dict):
            return False

        changed = False

        def set_if_needed(prop, value):
            nonlocal changed
            try:
                if getattr(obj, prop) != value:
                    setattr(obj, prop, value)
                    changed = True
            except Exception:
                pass

        if "LibraryId" in params:
            set_if_needed("LibraryId", params["LibraryId"])
        if "Profile" in params:
            set_if_needed("Profile", params["Profile"])
        if "TypeId" in params:
            set_if_needed("TypeId", params["TypeId"])
        if "Attachment" in params:
            set_if_needed("Attachment", params["Attachment"])
        if "Offset" in params:
            set_if_needed("Offset", params["Offset"])
        if "ProfileXAxis" in params:
            set_if_needed("ProfileXAxis", params["ProfileXAxis"])
        if "Diameter" in params:
            set_if_needed("Diameter", params["Diameter"])
        if "Width" in params:
            set_if_needed("Width", params["Width"])
        if "Height" in params:
            set_if_needed("Height", params["Height"])
        if "InsulationThickness" in params:
            set_if_needed("InsulationThickness", params["InsulationThickness"])
        if "Roughness" in params:
            set_if_needed("Roughness", params["Roughness"])
        if "Velocity" in params:
            set_if_needed("Velocity", params["Velocity"])
        if "RectangularSizingMode" in params:
            set_if_needed("RectangularSizingMode", params["RectangularSizingMode"])
        if "TargetAspectRatio" in params:
            set_if_needed("TargetAspectRatio", params["TargetAspectRatio"])

        return changed

    @staticmethod
    def applyTypeSelection(objects, library_id="", type_id=""):
        """
        Apply library/type selection to selected segment/junction objects.
        (Used as callback for command)
        """
        doc = FreeCAD.ActiveDocument
        if doc is None:
            return

        nets_to_sync = set()
        reg = hvaclib.HVACLibraryService.get_hvac_library_registry()
        changed = False

        for obj in objects or []:
            if obj is None:
                continue

            # A DuctJunction carries no LibraryId/TypeId of its own -- retarget
            # to its Primary DuctComponent, so applying a type selection to a
            # selected junction node acts on "its" fitting.
            if hvaclib.isDuctJunction(obj):
                obj = obj.Proxy.getPrimaryComponent()
                if obj is None:
                    continue

            net = DuctNetwork.getOwnerNetwork(obj)
            if net is not None:
                nets_to_sync.add(net)

            if hasattr(obj, "LibraryId") and library_id:
                if obj.LibraryId != library_id:
                    obj.LibraryId = library_id
                    changed = True

            if type_id and hasattr(obj, "TypeId"):
                if obj.TypeId != type_id:
                    obj.TypeId = type_id
                    changed = True

            if hvaclib.isDuctSegment(obj):
                valid_profiles = hvaclib.HVACLibraryService.segment_profiles_for_library(obj.LibraryId)
                current_profile = getattr(obj, "Profile", "")
                if current_profile not in valid_profiles:
                    new_profile = hvaclib.HVACLibraryService.default_segment_profile_for_library(obj.LibraryId)
                    if new_profile and obj.Profile != new_profile:
                        obj.Profile = new_profile
                        changed = True

                if type_id:
                    tdef = reg.resolve_type(obj.LibraryId, type_id)
                    if tdef and getattr(tdef, "profiles", None):
                        new_profile = tdef.profiles[0]
                        if obj.Profile != new_profile:
                            obj.Profile = new_profile
                            changed = True

            proxy = getattr(obj, "Proxy", None)
            if proxy and hasattr(proxy, "applyTypeSchema"):
                try:
                    changed = proxy.applyTypeSchema() or changed
                except Exception:
                    pass

            # Touch the modified obects for recomputation
            try:
                obj.touch()
            except Exception:
                pass

        if changed:
            # Sync all affected networks
            for net in nets_to_sync:
                proxy = getattr(net, "Proxy", None)
                if proxy:
                    proxy.requestSync(force_recompute=True)

    @staticmethod
    def applyAddInlineComponent(junction, edge_key, library_id, type_id):
        """
        Create a new Inline DuctComponent on junction, attached to edge_key,
        and sync. (Used as callback for CommandEditInlineComponents' task
        panel -- TaskPanelEditInlineComponents.)
        """
        from .Component import DuctComponent

        if junction is None or not edge_key or not type_id:
            return

        net = DuctNetwork.getOwnerNetwork(junction)
        if net is None:
            return
        doc = net.Document

        # New Inline components default to the end of THIS EDGE's own chain
        # (PortSequence = that chain's current max + 10), leaving gaps so a
        # user can reorder/insert by editing PortSequence directly in the
        # property editor.
        existing_chain = junction.Proxy.getInlineComponents(edge_key)
        next_port_sequence = max((int(getattr(c, "PortSequence", 0)) for c in existing_chain), default=0) + 10
        # Name uniqueness is decoupled from edge_key/PortSequence -- an
        # edge_key can contain characters invalid in a FreeCAD object Name
        # (e.g. "Sketch001:0").
        name_index = len(junction.Proxy.getComponents())

        component = DuctComponent.create(
            doc,
            "{}_Comp{}".format(junction.Name, name_index),
            parent_junction=junction,
            role="Inline",
            attached_edge_key=edge_key,
            port_sequence=next_port_sequence,
            owner_network=net,
        )
        net.Geometry.addObject(component)
        component.LibraryId = library_id
        component.TypeId = type_id
        component.Proxy.applyTypeSchema()

        proxy = getattr(net, "Proxy", None)
        if proxy:
            proxy.requestSync(force_recompute=True)

    @staticmethod
    def applyRemoveInlineComponent(component):
        """
        Remove one Inline DuctComponent and sync. (Used as callback for
        CommandEditInlineComponents' task panel -- TaskPanelEditInlineComponents.)
        """
        if component is None:
            return

        net = DuctNetwork.getOwnerNetwork(component)
        if net is None:
            return

        proxy = getattr(net, "Proxy", None)
        if proxy is None:
            return
        proxy.removeGeometryObject(component)
        proxy.requestSync(force_recompute=True)

    @staticmethod
    def applyPlacementSelection(objects, attachment=None, offset=None, profile_x_axis=None):
        """
        Set placement for selected objects
        (Used as callback for command)
        """
        doc = FreeCAD.ActiveDocument
        if doc is None:
            return

        nets_to_sync = set()
        changed = False
        for obj in objects or []:
            if obj is None or not hvaclib.isDuctSegment(obj):
                continue

            net = DuctNetwork.getOwnerNetwork(obj)
            if net is not None:
                nets_to_sync.add(net)

            if attachment is not None and getattr(obj, "Attachment", "") != attachment:
                obj.Attachment = attachment
                changed = True
            if offset is not None and getattr(obj, "Offset", FreeCAD.Vector(0, 0, 0)) != offset:
                obj.Offset = offset
                changed = True
            if profile_x_axis is not None and getattr(obj, "ProfileXAxis", FreeCAD.Vector(0, 0, 0)) != profile_x_axis:
                obj.ProfileXAxis = profile_x_axis
                changed = True

            try:
                obj.touch()
            except Exception:
                pass
        if changed:
            for net in nets_to_sync:
                proxy = getattr(net, "Proxy", None)
                if proxy:
                    proxy.requestSync(force_recompute=True)

    @staticmethod
    def applyMaterialSelection(objects, materials):
        """
        Set Layer_<id>_Material on selected duct segment(s)/component(s)
        (used as callback for HVAC_EditMaterial). `materials` is a
        {layer_id: material} dict -- only layer ids present on a given
        object are written, so a mixed selection of different types just
        skips whichever layer ids don't apply to a given object. Unlike
        applyPlacementSelection, this never touches the object or re-syncs
        the owner network -- Layer_<id>_Material is Prop_NoRecompute, since
        picking a material never changes an object's own geometry, only its
        ViewProvider's rendered appearance.
        """
        for obj in objects or []:
            if obj is None:
                continue
            for layer_id, material in dict(materials or {}).items():
                if material is None:
                    continue
                prop_name = _construction_schema.material_property_name(layer_id)
                if prop_name in obj.PropertiesList:
                    setattr(obj, prop_name, material)

    ## Trim map generation from junctions

    def collectSegmentTrimMap(self):
        """
        Collect trim contributions from all junctions.

        Returns:
            {
                "edge_key": {
                    "start": max_length_at_start,
                    "end": max_length_at_end,
                },
                ...
            }
        """
        net = self.Object
        trim_map = {}

        geometry = getattr(net, "Geometry", None)
        if geometry is None:
            return trim_map

        for obj in list(geometry.OutList):
            if not hvaclib.isDuctJunction(obj):
                continue

            raw = getattr(obj, "ConnectionLengthsJson", "") or "[]"
            try:
                items = json.loads(raw)
            except Exception:
                continue

            if not isinstance(items, list):
                continue

            for item in items:
                if not isinstance(item, dict):
                    continue

                edge_key = str(item.get("edge_key", "") or "")
                seg_end = str(item.get("segment_end", "") or "")
                if not edge_key or seg_end not in ("start", "end"):
                    continue

                try:
                    length = float(item.get("length", 0.0) or 0.0)
                except Exception:
                    length = 0.0

                if length < 0:
                    length = 0.0

                trim_map.setdefault(edge_key, {"start": 0.0, "end": 0.0})
                trim_map[edge_key][seg_end] = max(trim_map[edge_key][seg_end], length)

        return trim_map

    @staticmethod
    def resolveSegmentEndpoint(base_point, direction, seg_obj):
        return hvaclib.compute_port_position(
            base_point,
            direction,
            hvaclib.get_segment_section_params(seg_obj),
            getattr(seg_obj, "Attachment", "Center"),
            getattr(seg_obj, "Offset", FreeCAD.Vector(0, 0, 0)),
            getattr(seg_obj, "ProfileXAxis", FreeCAD.Vector(0, 0, 0)),
        )

    @staticmethod
    def resolveSegmentEndTrims(trim_entry):
        """
        Resolve explicit end-mapped trim contribution for a segment.
        """
        if not trim_entry:
            return 0.0, 0.0

        ts = max(0.0, float(trim_entry.get("start", 0.0) or 0.0))
        te = max(0.0, float(trim_entry.get("end", 0.0) or 0.0))
        return ts, te


# =================================================
# General functions
# =================================================


def create_new_duct_network(name="DuctNetwork", set_active=True):
    """Create new duct network"""
    # Create new duct netowork and create default folders
    net = DuctNetwork.createObject(name)
    FreeCAD.Console.PrintMessage("HVAC - New DuctNetwork created")
    if set_active:
        # Set as active network and enable edit mode
        activate_duct_network(net, set_edit=False)


def activate_duct_network(net, set_edit=False):
    if hvaclib.isDuctNetwork(net):
        net.Proxy.setActive()
        # Set network to edit mode
        if set_edit:
            import FreeCADGui as Gui

            Gui.ActiveDocument.setEdit(net.Name)
        else:
            pass
        hvaclib.refreshState()


def modify_duct_network(net):
    """Modify the selected HVAC duct network object"""
    # Set as active network and enable edit mode
    activate_duct_network(net, set_edit=True)
    FreeCAD.Console.PrintMessage("HVAC - Edit DuctNetwork completed")


def delete_duct_networks(nets, remove_internal_only=False):
    """Delete the selected HVAC duct network object"""
    doc = FreeCAD.ActiveDocument
    for net in nets:
        if net.Document != doc:
            continue

        if hasattr(net, "Proxy") and net.Proxy:
            net.Proxy._allow_internal_delete = True

        if hasattr(net, "Geometry") and net.Geometry:
            for obj in list(net.Geometry.OutList):
                net.Proxy.removeGeometryObject(obj)
            doc.removeObject(net.Geometry.Name)

        if hasattr(net, "Base") and net.Base:
            for obj in list(net.Base.OutList):
                net.Base.removeObject(obj)
            doc.removeObject(net.Base.Name)

        if not remove_internal_only:
            doc.removeObject(net.Name)
    hvaclib.refreshState()
    FreeCAD.Console.PrintMessage("HVAC - Deleted selected {} DuctNetwork(s)".format(len(nets)))
