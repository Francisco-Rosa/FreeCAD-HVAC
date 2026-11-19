# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the HVAC addon.

"""
HVACLibraryAPI's standard-fitting entry points: name lookup and dispatch
only. The fittings' own shape construction is out of scope (see AGENTS.md).
"""

import importlib

import pytest

import conftest  # noqa: F401 -- installs FreeCAD/FreeCADGui/Part/PySide stubs
from freecad.HVAC.library.library_api import HVACLibraryAPI


@pytest.mark.parametrize("name", sorted(HVACLibraryAPI.STANDARD_FITTINGS))
def test_every_standard_fitting_name_resolves_to_real_functions(name):
    module_name, build, measure = HVACLibraryAPI.STANDARD_FITTINGS[name]
    module = importlib.import_module("freecad.HVAC.library.fittings.{}".format(module_name))
    assert callable(getattr(module, build))
    assert callable(getattr(module, measure))


def test_unknown_standard_fitting_lists_the_known_names():
    with pytest.raises(ValueError) as excinfo:
        HVACLibraryAPI.build_fitting("elbwo", {})
    assert "elbwo" in str(excinfo.value)
    assert "elbow_mitered" in str(excinfo.value)


def _terminal_context(params):
    port = {
        "edge_key": "A",
        "position": [0.0, 0.0, 0.0],
        "direction": [1.0, 0.0, 0.0],
        "profile": "Circular",
        "section_params": {"Diameter": 300.0},
        "profile_x_axis": None,
        "segment_end": "start",
    }
    return {"hvac_api": HVACLibraryAPI, "properties": params, "connected_ports": [port]}


def test_measure_fitting_dispatches_to_the_named_fitting():
    records = HVACLibraryAPI.measure_fitting("terminal_body", _terminal_context({"BodyLength": 120.0}))
    assert records == [{"edge_key": "A", "segment_end": "start", "length": 120.0}]


def test_build_and_measure_go_to_different_functions(monkeypatch):
    from freecad.HVAC.library.fittings import terminals

    monkeypatch.setattr(terminals, "build_terminal_body_generic", lambda context: "built")
    monkeypatch.setattr(terminals, "measure_terminal_body_generic", lambda context: "measured")
    assert HVACLibraryAPI.build_fitting("terminal_body", {}) == "built"
    assert HVACLibraryAPI.measure_fitting("terminal_body", {}) == "measured"


def test_build_layered_fitting_passes_everything_to_the_shared_finisher(monkeypatch):
    from freecad.HVAC.library.fittings import _common

    seen = {}

    def fake_finish(context, envelope, lengths, port_roles):
        seen.update(context=context, envelope=envelope, lengths=lengths, port_roles=port_roles)
        return "result"

    monkeypatch.setattr(_common, "_finish", fake_finish)
    envelope = object()
    out = HVACLibraryAPI.build_layered_fitting({"k": 1}, envelope, [1], {"A": "Branch"})
    assert out == "result"
    assert seen == {"context": {"k": 1}, "envelope": envelope, "lengths": [1], "port_roles": {"A": "Branch"}}
