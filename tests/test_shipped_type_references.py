# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the HVAC addon.

"""
Every shipped type-def names Python functions by string (generator, trim
measurement, loss, loss variants). These tests check each of those names
really resolves to a callable, so a renamed or moved function can't leave a
type-def pointing at nothing until someone happens to use that fitting.
"""

import os

import pytest

import conftest  # noqa: F401 -- installs FreeCAD/FreeCADGui/Part/PySide stubs
from freecad.HVAC.library.Library import HVACLibraryRegistry

LIBRARIES_ROOT = os.path.join(os.path.dirname(__file__), "..", "freecad", "HVAC", "libraries")


def _load_registry():
    reg = HVACLibraryRegistry()
    reg.set_search_paths([LIBRARIES_ROOT])
    reg.ensure_loaded()
    return reg


def _function_references(type_def):
    """(role, module, function) for every function a type-def names."""
    refs = [
        ("generator", type_def.generator_module, type_def.generator_function),
        ("connection_lengths", type_def.lengths_module, type_def.lengths_function),
        ("loss", type_def.loss_module, type_def.loss_function),
        ("friction", type_def.friction_module, type_def.friction_function),
    ]
    refs.extend(("loss variant", variant.module, variant.function) for variant in type_def.loss_variants)
    refs.extend(
        ("feature " + feature.id, feature.module or "features", feature.generator)
        for feature in getattr(type_def, "features", []) or []
    )
    return [ref for ref in refs if ref[1] or ref[2]]


def test_every_flanged_layered_type_builds_its_flange_as_a_feature():
    # ROADMAP 6.2: flanges are a construction feature of their own, never fused into a layer.
    reg = _load_registry()
    missing = []
    for library_id, library in sorted(reg._libraries.items()):
        for type_def in library.list_types():
            names = {prop.name for prop in type_def.properties}
            if "FlangeThickness" not in names or not type_def.construction:
                continue
            if type_def.generator_function.endswith("_fcstd"):
                continue  # an FCStd template draws its own flanges (samples library)
            if not any(f.generator == "transverse_flange" for f in getattr(type_def, "features", []) or []):
                missing.append("{}/{}".format(library_id, type_def.id))
    assert missing == []


def _all_references():
    reg = _load_registry()
    cases = []
    for library_id, library in sorted(reg._libraries.items()):
        for type_def in library.list_types():
            for role, module, function in _function_references(type_def):
                cases.append((library_id, type_def.id, role, module, function))
    return cases


@pytest.mark.parametrize("library_id, type_id, role, module, function", _all_references())
def test_shipped_type_def_function_reference_resolves(library_id, type_id, role, module, function):
    reg = _load_registry()
    assert module and function, "{}/{}: {} needs both a module and a function".format(library_id, type_id, role)
    imported = reg.import_generator(library_id, module)
    assert callable(getattr(imported, function, None)), "{}/{}: {} '{}.{}' not found".format(
        library_id, type_id, role, module, function
    )


def test_shared_prefix_imports_from_the_shared_fittings_package():
    reg = _load_registry()
    module = reg.import_generator("builtin_basic", "shared:losses")
    assert module.__name__ == "freecad.HVAC.library.fittings.losses"


def test_shared_prefix_works_without_a_known_library():
    # A shared module doesn't belong to any one library, so the library id isn't looked up.
    module = HVACLibraryRegistry().import_generator("no_such_library", "shared:losses")
    assert callable(module.loss_elbow_generic)


@pytest.mark.parametrize("name", ["shared:", "shared:..secrets", "shared:os.path", "shared:fittings/losses"])
def test_shared_prefix_rejects_anything_but_a_plain_module_name(name):
    with pytest.raises(ValueError):
        HVACLibraryRegistry().import_generator("builtin_basic", name)
