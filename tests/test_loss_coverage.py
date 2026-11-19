# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the HVAC addon.

"""
Every selectable junction type of the shipped libraries has a loss wired,
and docs/loss-coverage.md is up to date (regenerate it with
`python3 tools/loss_coverage.py --write`).
"""

import importlib.util
import os

import conftest  # noqa: F401 -- installs FreeCAD/FreeCADGui/Part/PySide stubs

REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")


def _tool():
    spec = importlib.util.spec_from_file_location("loss_coverage", os.path.join(REPO_ROOT, "tools", "loss_coverage.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_selectable_junction_type_has_a_loss():
    tool = _tool()
    missing = [
        (lib, type_id) for lib, type_id, _p, _k, text in tool.coverage_rows(tool.load_registry()) if "MISSING" in text
    ]
    assert missing == [], "junction types with no loss wired: {}".format(missing)


def test_the_loss_coverage_page_is_up_to_date():
    tool = _tool()
    with open(tool.OUTPUT, encoding="utf-8") as f:
        current = f.read()
    assert current == tool.coverage_page(tool.load_registry()), (
        "docs/loss-coverage.md is out of date: run `python3 tools/loss_coverage.py --write`"
    )


def test_tee_shaped_types_route_a_bullhead_tee_to_the_bullhead_loss():
    # A tee whose common flow is on the branch leg has no straight-through
    # leg; the ordinary tee loss would pick one arbitrarily.
    tool = _tool()
    registry = tool.load_registry()
    library = registry.get_library("builtin_basic")
    for type_def in library.list_types():
        if type_def.category != "junction" or type_def.selection.kind != "model":
            continue
        if not any(f.startswith("branch.tee") and not f.endswith((".plenum", ".bullhead")) for f in type_def.family):
            continue
        bullhead = [
            v
            for v in type_def.loss_variants
            if (v.constraints.get("qualifiers") or {}).get("common_leg", {}).get("enum") == ["branch"]
        ]
        assert len(bullhead) == 2, type_def.id
