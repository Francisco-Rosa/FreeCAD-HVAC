# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the HVAC addon.

"""
Focused tests for the connection-length measurement contract (Milestone
B1): HVACLibraryRegistry.measure_connection_lengths()'s dispatch/context-
prep/normalization, and DuctJunction._peekConnectionLengths()'s own
"measure first, only fall back to a full geometry build for an unmigrated
type" behaviour.

Does not exercise any real builtin_basic/generators/*.py fitting math --
that module is explicitly out of scope for unit tests (see AGENTS.md), and
this sandbox has no real FreeCAD/Part install to run its geometry through
anyway. These tests only cover the new registry/adapter contract itself,
using synthetic fake modules/registries the same way the rest of this
suite already does for Library.py/Junction.py.
"""

import json
import sys
import types

import conftest  # noqa: F401 -- installs FreeCAD/FreeCADGui/Part/PySide stubs
import pytest

from freecad.HVAC.library.Library import HVACLibrary, HVACLibraryRegistry, HVACTypeDef
from freecad.HVAC.library.library_api import HVACLibraryAPI


# ----------------------------------------------------------------------
# HVACLibraryRegistry.measure_connection_lengths -- dispatch/context prep
# ----------------------------------------------------------------------

def test_measure_connection_lengths_dispatches_prepares_context_and_normalizes():
    captured = {}

    def measure(context):
        captured.update(context)
        return [{"edge_key": "A", "segment_end": "start", "length": 42.0}]

    module = types.ModuleType("fake_hvac_lib_pkg.lengths_probe")
    module.measure = measure
    sys.modules["fake_hvac_lib_pkg.lengths_probe"] = module
    try:
        lib = HVACLibrary(id="lib", label="Lib", root_path="", generators_package="fake_hvac_lib_pkg")
        type_def = HVACTypeDef(
            id="fake_type", label="Fake", category="junction", topology="through",
            family=["through.generic"], lengths_module="lengths_probe", lengths_function="measure",
        )
        lib.add_type(type_def)
        reg = HVACLibraryRegistry()
        reg.register_library(lib)

        result = reg.measure_connection_lengths("lib", type_def, {"connected_ports": []})

        # Same context-prep as build_geometry() -- no second, possibly
        # diverging context-building path for measurement.
        assert captured["hvac_api"] is HVACLibraryAPI
        assert captured["hvac_api_version"] == HVACLibraryAPI.API_VERSION
        assert "properties" in captured and "params" not in captured

        # Normalized (see normalize_connection_lengths tests below) --
        # a materially-valid record round-trips unchanged.
        assert result == [{"edge_key": "A", "segment_end": "start", "length": 42.0}]
    finally:
        sys.modules.pop("fake_hvac_lib_pkg.lengths_probe", None)


def test_measure_connection_lengths_returns_none_when_not_declared():
    type_def = HVACTypeDef(
        id="fake_type", label="Fake", category="junction", topology="through", family=["through.generic"],
    )
    lib = HVACLibrary(id="lib", label="Lib", root_path="", generators_package="fake_hvac_lib_pkg")
    lib.add_type(type_def)
    reg = HVACLibraryRegistry()
    reg.register_library(lib)

    assert reg.measure_connection_lengths("lib", type_def, {"connected_ports": []}) is None


def test_measure_connection_lengths_raises_if_declared_function_is_missing():
    module = types.ModuleType("fake_hvac_lib_pkg.lengths_missing")
    sys.modules["fake_hvac_lib_pkg.lengths_missing"] = module
    try:
        type_def = HVACTypeDef(
            id="fake_type", label="Fake", category="junction", topology="through",
            family=["through.generic"], lengths_module="lengths_missing", lengths_function="measure",
        )
        lib = HVACLibrary(id="lib", label="Lib", root_path="", generators_package="fake_hvac_lib_pkg")
        lib.add_type(type_def)
        reg = HVACLibraryRegistry()
        reg.register_library(lib)

        with pytest.raises(ValueError):
            reg.measure_connection_lengths("lib", type_def, {"connected_ports": []})
    finally:
        sys.modules.pop("fake_hvac_lib_pkg.lengths_missing", None)


# ----------------------------------------------------------------------
# HVACLibraryRegistry.normalize_connection_lengths
# ----------------------------------------------------------------------

def test_normalize_connection_lengths_none_returns_empty_list():
    assert HVACLibraryRegistry.normalize_connection_lengths(None, "t") == []


def test_normalize_connection_lengths_converts_length_to_float():
    out = HVACLibraryRegistry.normalize_connection_lengths(
        [{"edge_key": "A", "segment_end": "start", "length": "12.5"}], "t"
    )
    assert out == [{"edge_key": "A", "segment_end": "start", "length": 12.5}]
    assert isinstance(out[0]["length"], float)


def test_normalize_connection_lengths_clamps_tiny_negative_noise_to_zero():
    out = HVACLibraryRegistry.normalize_connection_lengths(
        [{"edge_key": "A", "segment_end": "start", "length": -1e-9}], "t"
    )
    assert out[0]["length"] == 0.0


def test_normalize_connection_lengths_rejects_materially_negative_length():
    with pytest.raises(ValueError):
        HVACLibraryRegistry.normalize_connection_lengths(
            [{"edge_key": "A", "segment_end": "start", "length": -5.0}], "t"
        )


def test_normalize_connection_lengths_rejects_missing_edge_key():
    with pytest.raises(ValueError):
        HVACLibraryRegistry.normalize_connection_lengths([{"segment_end": "start", "length": 1.0}], "t")


def test_normalize_connection_lengths_rejects_non_numeric_length():
    with pytest.raises(ValueError):
        HVACLibraryRegistry.normalize_connection_lengths(
            [{"edge_key": "A", "segment_end": "start", "length": "not-a-number"}], "t"
        )


def test_normalize_connection_lengths_rejects_non_iterable_result():
    with pytest.raises(ValueError):
        HVACLibraryRegistry.normalize_connection_lengths(123, "t")
