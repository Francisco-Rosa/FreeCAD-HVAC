# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the HVAC addon.

"""
Geometry smoke run: build every junction type of the shipped libraries
against a set of simple synthetic nodes, and report what came out.

This is not a unit test (shape construction is out of scope for those, see
AGENTS.md). It is a quick way to see, in a real FreeCAD, whether a change to
the fitting generators broke any type, profile or node layout:

    python tools/geometry_smoke.py                 # list problems + a summary
    python tools/geometry_smoke.py --all           # list every build
    python tools/geometry_smoke.py out.json        # also save the full report as JSON

`python` here is the Python that ships with FreeCAD (on Windows,
`bin/python.exe` in the FreeCAD folder). With any other Python of the same
version, set FREECAD_BIN to FreeCAD's `bin` folder first. The script always
builds with the code of the checkout it lives in, even when another copy of
the addon is installed in FreeCAD's Mod folder.

Compare two saved reports (before/after a change) to see what moved. For
each build the report holds: valid/invalid, total volume, per-layer volume,
and the trim length returned for each port. A type's separate trim-measurement
function is also run and must give the same trims as its build.
"""

import json
import math
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


def _use_this_checkout():
    """
    Make `import FreeCAD` work and make `freecad.HVAC` mean this checkout.

    FreeCAD loads its installed addons when it starts, so a copy of this
    addon in the Mod folder would otherwise be the one that gets tested.
    """
    # Step 1: find FreeCAD itself (next to the running Python, or where FREECAD_BIN says).
    for folder in (os.environ.get("FREECAD_BIN"), os.path.dirname(sys.executable)):
        if folder and folder not in sys.path:
            sys.path.insert(0, folder)
            sys.path.insert(0, os.path.join(os.path.dirname(folder), "lib"))
    import FreeCAD  # noqa: F401

    import freecad

    # Step 2: put this checkout first and forget any copy that was already imported.
    checkout = os.path.join(REPO_ROOT, "freecad")
    freecad.__path__ = [checkout] + [path for path in freecad.__path__ if path != checkout]
    for name in [name for name in sys.modules if name == "freecad.HVAC" or name.startswith("freecad.HVAC.")]:
        del sys.modules[name]


_use_this_checkout()

from freecad.HVAC.library.Library import HVACLibraryRegistry  # noqa: E402

LIBRARIES_ROOT = os.path.join(REPO_ROOT, "freecad", "HVAC", "libraries")
LIBRARY_IDS = ("builtin_basic", "smacna")

# Cross-sections tried for each profile. "Oval tall" is an oval standing on
# its narrow side (height > width).
SECTIONS = {
    "Circular": [("", {"Diameter": 300.0})],
    "Rectangular": [("", {"Width": 400.0, "Height": 250.0})],
    "Oval": [("", {"Width": 400.0, "Height": 200.0}), (" tall", {"Width": 200.0, "Height": 400.0})],
}
SMALLER = {
    "Circular": {"Diameter": 200.0},
    "Rectangular": {"Width": 300.0, "Height": 200.0},
    "Oval": {"Width": 300.0, "Height": 150.0},
}


def _dir(angle_deg):
    a = math.radians(angle_deg)
    return (round(math.cos(a), 12), round(math.sin(a), 12), 0.0)


def _port(index, direction, profile, section, position=(0.0, 0.0, 0.0), inlet=False):
    return {
        "edge_key": "E{}".format(index),
        "position": list(position),
        "direction": list(direction),
        "profile": profile,
        "section_params": dict(section),
        "attachment": "Center",
        "user_offset": [0.0, 0.0, 0.0],
        "profile_x_axis": None,
        "flow_role": "inlet" if inlet else "outlet",
        "flow_direction": list(direction),
        "flow_into_junction": inlet,
        "segment_end": "end" if inlet else "start",
    }


def _node(family, profile, section):
    """
    A synthetic node for one classifier family: (ports, collinear index pairs).

    All ports meet at the origin and point outward, the same convention the
    real junction composer uses. Port 0 is always the inlet.
    """
    small = SMALLER[profile]
    layouts = {
        "end.terminal": ([(180, section)], []),
        "through.straight": ([(180, section), (0, section)], [(0, 1)]),
        "through.transition": ([(180, section), (0, small)], [(0, 1)]),
        "through.bend_90": ([(180, section), (90, section)], []),
        "through.bend": ([(180, section), (45, section)], []),
        "branch.tee": ([(180, section), (0, section), (90, small)], [(0, 1)]),
        "branch.lateral_tee": ([(180, section), (0, section), (45, small)], [(0, 1)]),
        "branch.wye": ([(180, section), (45, small), (-45, small)], []),
        "cross.cross": ([(180, section), (0, section), (90, small), (-90, small)], [(0, 1), (2, 3)]),
        "cross.double_wye": ([(180, section), (0, section), (45, small), (-45, small)], [(0, 1)]),
        "multiport.multiport": ([(180, section), (0, small), (72, small), (-72, small), (144, small)], [(0, 1)]),
    }
    if family == "through.offset":
        # An offset has two parallel, opposite ports whose axes are displaced sideways.
        ports = [
            _port(0, _dir(180), profile, section, position=(0.0, 0.0, 0.0), inlet=True),
            _port(1, _dir(0), profile, section, position=(0.0, 150.0, 0.0)),
        ]
        return ports, [(0, 1)]
    if family in ("branch.tee over", "branch.lateral_tee over"):
        # A tee (or lateral) whose branch passes over the run: its axis is lifted clear of the run's top face.
        ports, pairs = _node(family.split(" ")[0], profile, section)
        ports[2]["position"] = [0.0, 0.0, 450.0]
        return ports, pairs
    if family not in layouts:
        return None, None
    specs, pairs = layouts[family]
    ports = [_port(i, _dir(angle), profile, sec, inlet=(i == 0)) for i, (angle, sec) in enumerate(specs)]
    return ports, pairs


def _families_for(type_def):
    """The plain (non-3d) classifier families a type-def lists, in a stable order."""
    seen = []
    for family in type_def.family:
        parts = family.split(".")
        base = ".".join(parts[:2]) if parts[0] != "end" else "end.terminal"
        if base not in seen and not family.endswith(".3d"):
            seen.append(base)
    # A type with an Attachment property is also tried with the branch passing over the run.
    if any(prop.name == "Attachment" for prop in type_def.properties):
        for base in ("branch.tee", "branch.lateral_tee"):
            if base in seen:
                seen.append(base + " over")
    return seen


def _volume(shape):
    try:
        return round(float(shape.Volume), 1)
    except Exception:
        return None


def _build_one(reg, library_id, type_def, family, profile, section):
    ports, pairs = _node(family, profile, section)
    if ports is None:
        return {"status": "skipped", "detail": "no synthetic node for family"}
    return build_entry(reg, library_id, type_def, family.split(".", 1)[1].split(" ")[0], ports, pairs)


def build_entry(reg, library_id, type_def, family, ports, pairs, properties=None):
    """
    Build one type on one synthetic node and report it: status (ok, invalid,
    error, trim-mismatch), volumes per layer and feature, trims per port.
    `family` is the classifier family without its topology (e.g. "wye").
    Also used by tools/geometry_sweep.py.
    """
    context = {
        "center_point": (0.0, 0.0, 0.0),
        "connected_ports": ports,
        "analysis": {"collinear_pairs": [{"a": a, "b": b} for a, b in pairs]},
        "family": family,
        "topology": type_def.topology,
        "type_id": type_def.id,
        "library_id": library_id,
        "properties": dict(properties or {}),
    }
    try:
        result = reg.build_geometry(library_id, type_def, context)
    except Exception as exc:
        return {"status": "error", "detail": "{}: {}".format(type(exc).__name__, exc)}

    layers = {}
    valid = True
    total = 0.0
    for layer_id, layer in result.layers.items():
        shape = layer.shape
        if shape is None or shape.isNull():
            layers[layer_id] = None
            continue
        valid = valid and bool(shape.isValid())
        volume = _volume(shape)
        layers[layer_id] = volume
        total += volume or 0.0
    trims = {rec["edge_key"]: round(float(rec["length"]), 2) for rec in (result.connection_lengths or [])}
    entry = {"status": "ok" if valid else "invalid", "volume": round(total, 1), "layers": layers, "trims": trims}
    features = {}
    for feature_id, feature in (result.features or {}).items():
        shape = feature.shape
        if shape is None or shape.isNull():
            features[feature_id] = None
            continue
        if not shape.isValid():
            entry["status"] = "invalid"
        features[feature_id] = _volume(shape)
    if features:
        entry["features"] = features
    if result.computed_properties:
        entry["computed"] = {
            name: round(float(value), 2) if isinstance(value, (int, float)) else value
            for name, value in result.computed_properties.items()
        }

    # A type with its own trim-measurement function must report exactly the
    # trims its build reports -- they are meant to share one calculation.
    if type_def.lengths_module and type_def.lengths_function:
        try:
            measured = reg.measure_connection_lengths(library_id, type_def, dict(context))
            measured = {rec["edge_key"]: round(float(rec["length"]), 2) for rec in (measured or [])}
        except Exception as exc:
            measured = "{}: {}".format(type(exc).__name__, exc)
        if measured != trims:
            entry["status"] = "trim-mismatch"
            entry["detail"] = "measure gave {}, build gave {}".format(measured, trims)
    return entry


def run():
    reg = HVACLibraryRegistry()
    reg.set_search_paths([LIBRARIES_ROOT])
    reg.ensure_loaded()

    report = {}
    for library_id in LIBRARY_IDS:
        library = reg.get_library(library_id)
        for type_def in sorted(library.list_types(), key=lambda t: t.id):
            if type_def.category != "junction":
                continue
            for family in _families_for(type_def):
                for profile in type_def.profiles:
                    for label, section in SECTIONS.get(profile, []):
                        key = "{}/{} [{}] {}{}".format(library_id, type_def.id, family, profile, label)
                        report[key] = _build_one(reg, library_id, type_def, family, profile, section)
    return report


def report_and_save(report, argv):
    """
    Print the problems in `report` (every build with --all in `argv`) and a
    summary; save the full report to the first *.json argument, if any.
    Also used by tools/geometry_sweep.py.
    """
    show_all = "--all" in argv
    counts = {}
    for key, entry in report.items():
        counts[entry["status"]] = counts.get(entry["status"], 0) + 1
        # By default only problems are listed; --all lists every build.
        if entry["status"] == "ok" and not show_all:
            continue
        if entry["status"] == "trim-mismatch":
            print("{:8s} {}  {}".format("MISMATCH", key, entry["detail"]))
        elif entry["status"] in ("ok", "invalid"):
            print(
                "{:8s} {}  volume={} layers={} trims={}".format(
                    entry["status"], key, entry["volume"], entry["layers"], entry["trims"]
                )
            )
        else:
            print("{:8s} {}  {}".format(entry["status"], key, entry["detail"]))
    print("SUMMARY", counts)

    # Optional: the first *.json argument is where to save the full report.
    out_path = next((arg for arg in argv[1:] if arg.endswith(".json")), None)
    if out_path:
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=1, sort_keys=True)
        print("saved", out_path)


def main(argv):
    report_and_save(run(), argv)


if __name__ == "__main__":
    main(sys.argv)
