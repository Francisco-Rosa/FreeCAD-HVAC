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
    category: str               # "segment" | "junction"
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

    def get_type(self, type_id: str) -> HVACTypeDef | None:
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


class HVACLibraryRegistry:
    def __init__(self):
        self._libraries = {}
        self._active_library_id = None
        self._loaded = False

    def clear(self):
        self._libraries = {}
        self._active_library_id = None
        self._loaded = False

    def register_library(self, library: HVACLibrary):
        self._libraries[library.id] = library
        if self._active_library_id is None:
            self._active_library_id = library.id

    def get_library(self, library_id: str) -> HVACLibrary | None:
        return self._libraries.get(library_id)

    def list_libraries(self):
        return list(self._libraries.values())

    def set_active_library(self, library_id: str):
        if library_id in self._libraries:
            self._active_library_id = library_id
            return True
        return False

    def get_active_library(self) -> HVACLibrary | None:
        if self._active_library_id is None:
            return None
        return self._libraries.get(self._active_library_id)

    def ensure_loaded(self, builtin_loader=None):
        if self._loaded:
            return
        if builtin_loader:
            builtin_loader(self)
        self._loaded = True

    def resolve_type(self, library_id: str, type_id: str) -> HVACTypeDef | None:
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


_registry = HVACLibraryRegistry()


def registry() -> HVACLibraryRegistry:
    return _registry
