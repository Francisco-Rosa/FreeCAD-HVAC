# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the HVAC addon.

"""
docs/library-api.md is generated from the code (tools/api_reference.py):
it must match the public names, their docstrings and the context keys.
Regenerate it with `python3 tools/api_reference.py --write`.
"""

import importlib.util
import os

import conftest  # noqa: F401 -- installs FreeCAD/FreeCADGui/Part/PySide stubs

REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")


def _tool():
    spec = importlib.util.spec_from_file_location("api_reference", os.path.join(REPO_ROOT, "tools", "api_reference.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_api_reference_is_up_to_date():
    tool = _tool()
    with open(tool.OUTPUT, encoding="utf-8") as f:
        current = f.read()
    assert current == tool.reference_markdown(), (
        "docs/library-api.md is out of date: run `python3 tools/api_reference.py --write`"
    )


def test_every_public_name_is_in_the_reference():
    tool = _tool()
    api, loss_api, _contexts = tool._load()
    page = tool.reference_markdown()
    missing = [name for cls in (api, loss_api) for name in cls.PUBLIC if "#### `{}".format(name) not in page]
    assert missing == []
