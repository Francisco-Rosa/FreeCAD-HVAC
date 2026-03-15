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

# SPDX-License-Identifier: LGPL-2.1-or-later

import importlib
import json
import os
from dataclasses import dataclass, field

import FreeCAD


@dataclass
class HVACPropertyDef:
    name: str
    prop_type: str
    group: str = "HVAC"
    description: str = ""
    default: object = None
    editor_mode: int = 0


@dataclass
class HVACTypeDef:
    id: str
    label: str
    category: str
    family: str
    profiles: list[str] = field(default_factory=list)
    constraints: dict = field(default_factory=dict)
    properties: list[HVACPropertyDef] = field(default_factory=list)
    generator_module: str = ""
    generator_function: str = ""
    lengths_module: str = ""
    lengths_function: str = ""


@dataclass
class HVACLibrary:
    id: str
    label: str
    root_path: str
    generators_package: str
    types_by_id: dict = field(default_factory=dict)

    def add_type(self, type_def: HVACTypeDef):
        self.types_by_id[type_def.id] = type_def

    def get_type(self, type_id: str):
        return self.types_by_id.get(type_id)

    def list_types(self, category=None, family=None, profile=None):
        out = []
        for t in self.types_by_id.values():
            if category and t.category != category:
                continue
            if family and t.family != family:
                continue
            if profile and t.profiles and profile not in t.profiles:
                continue
            out.append(t)
        return out

    def list_profiles(self, category=None, family=None):
        profiles = set()
        for t in self.types_by_id.values():
            if category and t.category != category:
                continue
            if family and t.family != family:
                continue
            for p in (t.profiles or []):
                profiles.add(p)
        return sorted(profiles)

    def default_profile(self, category=None, family=None):
        profiles = self.list_profiles(category=category, family=family)
        return profiles[0] if profiles else ""


class HVACLibraryRegistry:
    def __init__(self):
        self._libraries = {}
        self._active_library_id = None
        self._loaded = False
        self._search_paths = []

    def clear(self):
        self._libraries = {}
        self._active_library_id = None
        self._loaded = False

    def register_library(self, library: HVACLibrary):
        self._libraries[library.id] = library
        if self._active_library_id is None:
            self._active_library_id = library.id

    def get_library(self, library_id: str):
        return self._libraries.get(library_id)

    def list_libraries(self):
        return list(self._libraries.values())

    def set_active_library(self, library_id: str):
        if library_id in self._libraries:
            self._active_library_id = library_id
            return True
        return False

    def get_active_library(self):
        if self._active_library_id is None:
            return None
        return self._libraries.get(self._active_library_id)

    def resolve_type(self, library_id: str, type_id: str):
        lib = self.get_library(library_id)
        if lib is None:
            return None
        return lib.get_type(type_id)

    def import_generator(self, library_id: str, module_name: str):
        lib = self.get_library(library_id)
        if lib is None:
            raise ValueError("Unknown HVAC library '{}'".format(library_id))
        full_module = "{}.{}".format(lib.generators_package, module_name)
        return importlib.import_module(full_module)

    def call_generator(self, library_id: str, type_def: HVACTypeDef, context: dict):
        module = self.import_generator(library_id, type_def.generator_module)
        func = getattr(module, type_def.generator_function)
        return func(context)

    def set_search_paths(self, paths):
        self._search_paths = [p for p in (paths or []) if p]

    def add_search_path(self, path):
        if path and path not in self._search_paths:
            self._search_paths.append(path)

    def ensure_loaded(self):
        if self._loaded:
            return
            
        self.scan_paths()
        
        if not self._libraries:
            FreeCAD.Console.PrintError(
                "HVAC: No HVAC libraries found in search paths.\n"
            )
        self._loaded = True

    def scan_paths(self):
        for root in self._search_paths:
            self.scan_path(root)

    def scan_path(self, root_path):
        if not root_path or not os.path.isdir(root_path):
            return

        for entry in sorted(os.listdir(root_path)):
            lib_dir = os.path.join(root_path, entry)
            if not os.path.isdir(lib_dir):
                continue
            try:
                lib = self.load_library_from_folder(lib_dir)
                if lib is not None:
                    self.register_library(lib)
            except Exception as e:
                FreeCAD.Console.PrintWarning(
                    "HVAC - Failed to load library from '{}': {}\n".format(lib_dir, e)
                )

    def load_library_from_folder(self, lib_dir):
        manifest_path = os.path.join(lib_dir, "library.json")
        if not os.path.isfile(manifest_path):
            return None

        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
        
        lib_id = manifest["id"]
        label = manifest.get("label", lib_id)
        generators_package = manifest["generators_package"]
        type_roots = manifest.get("type_roots", ["types"])

        library = HVACLibrary(
            id=lib_id,
            label=label,
            root_path=lib_dir,
            generators_package=generators_package,
        )

        for rel_root in type_roots:
            abs_root = os.path.join(lib_dir, rel_root)
            self._load_type_defs_from_tree(abs_root, library)

        return library

    def _load_type_defs_from_tree(self, root_dir, library):
        if not os.path.isdir(root_dir):
            return

        for dirpath, _, filenames in os.walk(root_dir):
            for fn in filenames:
                if not fn.lower().endswith(".json"):
                    continue
                fpath = os.path.join(dirpath, fn)
                type_def = self._load_type_def_file(fpath)
                library.add_type(type_def)

    def _load_type_def_file(self, filepath):
        with open(filepath, "r", encoding="utf-8") as f:
            raw = json.load(f)

        props = []
        for p in raw.get("properties", []) or []:
            props.append(
                HVACPropertyDef(
                    name=p["name"],
                    prop_type=p["prop_type"],
                    group=p.get("group", "HVAC"),
                    description=p.get("description", ""),
                    default=p.get("default", None),
                    editor_mode=int(p.get("editor_mode", 0)),
                )
            )

        gen = raw.get("generator", {}) or {}
        lengths = raw.get("connection_lengths", {}) or {}

        return HVACTypeDef(
            id=raw["id"],
            label=raw.get("label", raw["id"]),
            category=raw["category"],
            family=raw["family"],
            profiles=list(raw.get("profiles", []) or []),
            constraints=dict(raw.get("constraints", {}) or {}),
            properties=props,
            generator_module=gen.get("module", ""),
            generator_function=gen.get("function", ""),
            lengths_module=lengths.get("module", ""),
            lengths_function=lengths.get("function", ""),
        )
        

_registry = HVACLibraryRegistry()


def registry():
    return _registry
