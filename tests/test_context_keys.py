"""
Frozen context keys (ROADMAP 6.4, item 3): core builds only the documented
keys for each kind of call, and library code reads only documented keys.
"""

import ast
from pathlib import Path

import conftest  # noqa: F401 -- installs FreeCAD/Part stubs
from freecad.HVAC.library import contexts

ROOT = Path(__file__).resolve().parents[1]
HVAC = ROOT / "freecad" / "HVAC"


def _context_literal_keys(path, function_name=None):
    """Keys of every `context = {...}` dict literal in a file (optionally inside one function)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    keys = []
    scopes = [tree]
    if function_name:
        scopes = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == function_name]
        assert scopes, "{} has no function {}".format(path.name, function_name)
    for scope in scopes:
        for node in ast.walk(scope):
            if (
                isinstance(node, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "context" for t in node.targets)
                and isinstance(node.value, ast.Dict)
            ):
                keys.extend(k.value for k in node.value.keys if isinstance(k, ast.Constant))
    return keys


def test_geometry_contexts_use_documented_keys():
    keys = []
    for name in ("Segment.py", "Component.py", "Junction.py"):
        keys += _context_literal_keys(HVAC / "core" / name)
    assert keys
    allowed = contexts.GEOMETRY_CONTEXT_KEYS | contexts.CALLER_KEYS
    assert set(keys) <= allowed, sorted(set(keys) - allowed)


def test_the_registry_never_hands_the_freecad_object_to_library_code():
    from freecad.HVAC.library.Library import HVACLibraryRegistry, HVACTypeDef

    type_def = HVACTypeDef(
        id="t", label="t", category="segment", topology="generic", family=["straight_segment"], profiles=["Circular"]
    )
    prepared = HVACLibraryRegistry()._prepare_geometry_context(type_def, {"obj": object(), "properties": {}})
    assert not set(prepared) & contexts.CALLER_KEYS
    assert set(prepared) <= contexts.GEOMETRY_CONTEXT_KEYS


def test_loss_and_friction_contexts_use_documented_keys():
    adapter = HVAC / "core" / "_analysis_adapter.py"
    loss = _context_literal_keys(adapter, "build_loss_evaluator")
    friction = _context_literal_keys(adapter, "segment_friction_model")
    assert loss and friction
    assert set(loss) <= contexts.LOSS_CONTEXT_KEYS, sorted(set(loss) - contexts.LOSS_CONTEXT_KEYS)
    assert set(friction) <= contexts.FRICTION_CONTEXT_KEYS, sorted(set(friction) - contexts.FRICTION_CONTEXT_KEYS)


def test_registry_additions_are_documented():
    source = (HVAC / "library" / "Library.py").read_text(encoding="utf-8")
    added = set()
    for node in ast.walk(ast.parse(source)):
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Subscript)
            and ast.unparse(node.targets[0].value) in ("prepared", "context")
            and isinstance(node.targets[0].slice, ast.Constant)
        ):
            added.add(node.targets[0].slice.value)
    assert added <= contexts.ALL_CONTEXT_KEYS, sorted(added - contexts.ALL_CONTEXT_KEYS)


def test_library_code_reads_only_documented_keys():
    names = ("context", "ctx.context")
    offenders = []
    files = list((HVAC / "libraries").rglob("*.py")) + list((HVAC / "library" / "fittings").rglob("*.py"))
    for path in files:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            key = None
            if (
                isinstance(node, ast.Subscript)
                and ast.unparse(node.value) in names
                and isinstance(node.slice, ast.Constant)
            ):
                key = node.slice.value
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get"
                and ast.unparse(node.func.value) in names
                and node.args
                and isinstance(node.args[0], ast.Constant)
            ):
                key = node.args[0].value
            if isinstance(key, str) and key not in contexts.ALL_CONTEXT_KEYS:
                offenders.append("{}:{}:{}".format(path.relative_to(ROOT), node.lineno, key))
    assert not offenders, "Library code reads undocumented context keys:\n" + "\n".join(offenders)
