"""Architecture guards for library geometry API v2."""
import ast
from pathlib import Path

import conftest  # noqa: F401 -- installs FreeCAD/FreeCADGui/Part/PySide stubs

from freecad.HVAC.library.library_api import HVACLibraryAPI


ROOT = Path(__file__).resolve().parents[1]
LIBRARIES = ROOT / "freecad" / "HVAC" / "libraries"
FORBIDDEN_IMPORTS = {"FreeCAD", "Part"}
FORBIDDEN_LEGACY_CALLS = {
    "make_straight_shape",
    "make_curved_shape",
    "make_pipe_shell",
    "make_loft",
    "make_hollow_straight",
    "make_hollow_loft",
    "make_hollow_pipe_shell",
    "make_tee",
    "make_wye",
    "build_concentric_layers",
}
GEOMETRY_V2_METHODS = {
    "make_profile",
    "profile_from_port",
    "offset_profile",
    "extrude",
    "sweep",
    "loft",
    "revolve",
    "translate",
    "rotate",
    "make_face",
    "sample_path",
    "clip_plane",
    "trim",
    "fuse",
    "cut",
    "common",
    "reverse",
    "refine",
    "validate",
    "make_sphere",
    "make_line",
    "compound",
}


def _python_files():
    return list(LIBRARIES.rglob("*.py"))


def test_libraries_do_not_import_freecad_or_part_directly():
    offenders = []
    for path in _python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = {alias.name.split(".", 1)[0] for alias in node.names}
                if names & FORBIDDEN_IMPORTS:
                    offenders.append(str(path.relative_to(ROOT)))
            elif isinstance(node, ast.ImportFrom):
                if (node.module or "").split(".", 1)[0] in FORBIDDEN_IMPORTS:
                    offenders.append(str(path.relative_to(ROOT)))
    assert not offenders, "Library code imports FreeCAD/Part directly: " + ", ".join(sorted(set(offenders)))


def test_libraries_use_geometry_v2_not_legacy_hollow_helpers():
    offenders = []
    for path in _python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_LEGACY_CALLS:
                offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}:{node.attr}")
    assert not offenders, "Legacy geometry helper use remains:\n" + "\n".join(offenders)


def test_geometry_v2_is_on_the_public_class():
    # The methods are written in topic mixin modules (_api_*.py, owner's
    # decision of 13 November 2026); HVACLibraryAPI is still the one surface.
    assert all(callable(getattr(HVACLibraryAPI, name, None)) for name in GEOMETRY_V2_METHODS)


def test_old_split_geometry_api_module_is_removed():
    assert not (ROOT / "freecad" / "HVAC" / "library" / "_geometry_api.py").exists()


def test_legacy_duplicate_geometry_helpers_are_removed_from_public_api():
    assert not (FORBIDDEN_LEGACY_CALLS & set(dir(HVACLibraryAPI)))


def test_public_lists_match_the_api_classes():
    from freecad.HVAC.library.loss_api import HVACLossAPI

    for api in (HVACLibraryAPI, HVACLossAPI):
        public = {name for name in dir(api) if not name.startswith("_")}
        assert public == set(api.PUBLIC), (
            "{}.PUBLIC is out of date: added {}, removed {}".format(
                api.__name__, sorted(public - set(api.PUBLIC)), sorted(set(api.PUBLIC) - public)
            )
        )


def test_library_code_uses_only_public_api_names():
    from freecad.HVAC.library.loss_api import HVACLossAPI

    api_names = {"api", "HVACLibraryAPI", "loss_api", "HVACLossAPI", 'context["hvac_api"]', 'context["loss_api"]'}
    allowed = set(HVACLibraryAPI.PUBLIC) | set(HVACLossAPI.PUBLIC)
    offenders = []
    for path in list(LIBRARIES.rglob("*.py")) + list((ROOT / "freecad" / "HVAC" / "library" / "fittings").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and ast.unparse(node.value) in api_names:
                if node.attr.startswith("_") or node.attr not in allowed:
                    offenders.append("{}:{}:{}".format(path.relative_to(ROOT), node.lineno, node.attr))
    assert not offenders, "Library code uses non-public API names:\n" + "\n".join(offenders)
