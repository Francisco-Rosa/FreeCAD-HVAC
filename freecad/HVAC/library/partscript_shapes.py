# SPDX-License-Identifier: LGPL-2.1-or-later
"""
The "partscript" geometry backend: loads a plain Python file (a PartScript)
and calls its generate(context) function to build a shape in code, as an
alternative to the static BREP/STEP backend. execute_partscript() is the
entry point, called from Library.py's build_geometry -- it loads/caches the
script module, then checks it honours the expected contract (API version,
generate()/validate() signatures, a real non-empty Part.Shape back) before
handing its result back to the caller.
"""

import hashlib
import importlib.util
import os
import sys


class PartScriptError(Exception):
    pass


class PartScriptSchemaError(PartScriptError):
    pass


_MODULE_CACHE = {}
_PARTSCRIPT_API_VERSION = 3


def _module_signature(path):
    """Cheap "has this file changed?" fingerprint -- modified time + size, no hashing the contents."""
    stat = os.stat(path)
    return stat.st_mtime_ns, stat.st_size


def _load_module(script_path):
    """
    Import a PartScript as a Python module, reusing the cached one if the
    file hasn't changed since last time (checked via _module_signature) --
    so editing a PartScript on disk and re-syncing picks up the change
    without restarting FreeCAD.
    """
    path = os.path.realpath(script_path)
    if not os.path.isfile(path):
        raise PartScriptSchemaError("PartScript file not found: '{}'".format(path))

    signature = _module_signature(path)
    cached = _MODULE_CACHE.get(path)
    if cached is not None and cached[0] == signature:
        return cached[1]

    module_name = "_freecad_hvac_partscript_{}".format(hashlib.sha1(path.encode("utf-8")).hexdigest())
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise PartScriptSchemaError("Cannot load PartScript '{}'".format(path))

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise

    _MODULE_CACHE[path] = (signature, module)
    return module


def clear_cache():
    _MODULE_CACHE.clear()


def execute_partscript(script_path, context):
    """Load a PartScript and run it, enforcing its contract (see module docstring) at every step."""
    module = _load_module(script_path)

    # Step 1: the script must declare the API version it was written for.
    version = int(getattr(module, "HVAC_PARTSCRIPT_API", _PARTSCRIPT_API_VERSION))
    if version != _PARTSCRIPT_API_VERSION:
        raise PartScriptSchemaError(
            "PartScript '{}' requires API {}; loader supports {}".format(script_path, version, _PARTSCRIPT_API_VERSION)
        )

    # Step 2: an optional validate(context) gets first refusal -- it can
    # raise its own, more specific error before generate() ever runs.
    validator = getattr(module, "validate", None)
    if validator is not None:
        if not callable(validator):
            raise PartScriptSchemaError("PartScript validate must be callable")
        validator(context)

    # Step 3: generate(context) is required and must build the shape.
    generator = getattr(module, "generate", None)
    if not callable(generator):
        raise PartScriptSchemaError("PartScript '{}' must define generate(context)".format(script_path))

    result = generator(context)
    if hasattr(result, "isNull"):
        # A bare shape is one solid: it goes on the type's first layer.
        result = context["hvac_api"].single_layer(context, result)
    if not isinstance(result, dict):
        raise PartScriptSchemaError(
            "PartScript '{}' must return Part.Shape or a {{\"layers\": ...}} dict".format(script_path)
        )

    # Step 4: the result must hold at least one real, non-empty shape in
    # result["layers"] (the one result form; see library/geometry_result.py).
    # Never hardcodes a layer id -- a PartScript names its own construction
    # layers however it likes.
    if "layers" not in result:
        raise PartScriptSchemaError(
            'PartScript \'{}\' must return {{"layers": ...}} (the {{"shape": ...}} form was removed)'.format(
                script_path
            )
        )
    shapes = [
        layer_value.get("shape") if isinstance(layer_value, dict) else getattr(layer_value, "shape", None)
        for layer_value in dict(result.get("layers") or {}).values()
    ]
    if not any(hasattr(s, "isNull") and not s.isNull() for s in shapes if s is not None):
        raise PartScriptSchemaError(
            "PartScript '{}' did not return a real Part.Shape in any of result['layers']".format(script_path)
        )

    return dict(result)
