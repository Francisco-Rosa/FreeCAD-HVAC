# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the HVAC addon.

"""
Geometry sweep: build the branch and bend fittings of the shipped libraries
across branch size ratios, angles, every profile and several wall build-ups,
and report what came out.

The smoke run (tools/geometry_smoke.py) builds one node per family, which
hides fittings that only fail at some sizes or with a thick wall. This is
the acceptance check for changes to fitting geometry (design 6.6): every
case should build, except ones the layout refuses with a message.

    python tools/geometry_sweep.py                       # problems + a summary per type
    python tools/geometry_sweep.py --all                 # list every build
    python tools/geometry_sweep.py out.json              # also save the full report as JSON
    python tools/geometry_sweep.py --type branch_wye_radius --type branch_wye_mitered

Same Python and same report format as the smoke run: see its docstring.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import geometry_smoke as smoke  # noqa: E402  (sets up FreeCAD and this checkout)

RUN_SIZE = 300.0

# The fittings swept by default.
TYPE_IDS = (
    "branch_wye_radius",
    "branch_wye_mitered",
    "cross_double_wye_radius",
    "cross_double_wye_mitered",
    "branch_lateral_tee_radius",
    "branch_lateral_tee_mitered",
    "branch_tap_mitered_shoe",
    "branch_tee_radius_center",
    "branch_tee_radius_edge",
    "branch_tee_straight",
    "branch_tap_straight",
    "branch_tap_saddle",
    "branch_tap_shoe",
    "through_elbow_radius",
    "through_elbow_mitered",
)

# Wall build-ups per library: property overrides (an empty dict is the type's default wall).
WALLS = {
    "builtin_basic": [("no wall", {"Thickness": 0.0}), ("default wall", {}), ("3 mm", {"Thickness": 3.0})],
    "smacna": [("default wall", {}), ("25 mm insulation", {"InsulationThickness": 25.0})],
}

# (label, profile, tall): a tall oval stands on its narrow side.
PROFILES = [
    ("round", "Circular", False),
    ("rect", "Rectangular", False),
    ("oval", "Oval", False),
    ("tall oval", "Oval", True),
]


def _section(profile, size, tall=False):
    """A section of `size` (diameter, or the larger side of a 5:3 rectangle or oval)."""
    if profile == "Circular":
        return {"Diameter": size}
    width, height = size, round(size * 0.6)
    return {"Width": height, "Height": width} if tall else {"Width": width, "Height": height}


def _cases(type_id):
    """
    The nodes a type is swept over: (label, family, [(angle, size ratio)], collinear pairs, branch lift).
    A branch lift moves the branch axis over the run (a face-mounted tee).
    """
    out = []
    if type_id.startswith(("branch_tee", "branch_tap")):
        for ratio in (0.5, 0.75, 1.0):
            for lift in (0.0, 450.0):
                label = "tee r={:.2f}{}".format(ratio, " over" if lift else "")
                out.append((label, "tee", [(180, 1.0), (0, 1.0), (90, ratio)], [(0, 1)], lift))
    if type_id.startswith("branch_lateral"):
        for ratio in (0.5, 1.0):
            for angle in (30, 45, 60):
                label = "lateral r={:.2f} a={}".format(ratio, angle)
                out.append((label, "lateral_tee", [(180, 1.0), (0, 1.0), (angle, ratio)], [(0, 1)], 0.0))
    if type_id.startswith("branch_wye"):
        for ratio in (0.5, 0.75, 1.0):
            for angle in (30, 45, 60):
                label = "wye r={:.2f} a={}".format(ratio, angle)
                out.append((label, "wye", [(180, 1.0), (angle, ratio), (-angle, ratio)], [], 0.0))
            # Unequal legs: one at the ratio, the other the full run size.
            out.append(("wye uneven r={:.2f}".format(ratio), "wye", [(180, 1.0), (45, ratio), (-30, 1.0)], [], 0.0))
            out.append(("bullhead r={:.2f}".format(ratio), "tee", [(180, ratio), (0, ratio), (90, 1.0)], [(0, 1)], 0.0))
    if type_id.startswith("cross_double_wye"):
        for ratio in (0.5, 1.0):
            for angle in (30, 45, 60):
                label = "double wye r={:.2f} a={}".format(ratio, angle)
                specs = [(180, 1.0), (0, 1.0), (angle, ratio), (-angle, ratio)]
                out.append((label, "double_wye", specs, [(0, 1)], 0.0))
    if type_id.startswith("through_elbow"):
        for angle in (30, 60, 90, 135):
            family = "bend_90" if angle == 90 else "bend"
            out.append(("bend {}".format(angle), family, [(180, 1.0), (180 - angle, 1.0)], [], 0.0))
    return out


def run(type_ids=TYPE_IDS):
    reg = smoke.HVACLibraryRegistry()
    reg.set_search_paths([smoke.LIBRARIES_ROOT])
    reg.ensure_loaded()

    report = {}
    for library_id in smoke.LIBRARY_IDS:
        types = {type_def.id: type_def for type_def in reg.get_library(library_id).list_types()}
        for type_id in type_ids:
            type_def = types.get(type_id)
            if type_def is None:
                continue
            for label, family, specs, pairs, lift in _cases(type_id):
                for profile_label, profile, tall in PROFILES:
                    if profile not in type_def.profiles:
                        continue
                    for wall_label, properties in WALLS[library_id]:
                        ports = [
                            smoke._port(
                                i, smoke._dir(angle), profile, _section(profile, RUN_SIZE * ratio, tall), inlet=i == 0
                            )
                            for i, (angle, ratio) in enumerate(specs)
                        ]
                        if lift:
                            ports[2]["position"] = [0.0, 0.0, lift]
                        key = "{}/{} [{}] {}, {}".format(library_id, type_id, label, profile_label, wall_label)
                        report[key] = smoke.build_entry(reg, library_id, type_def, family, ports, pairs, properties)
    return report


def summary(report):
    """Print ok / cases per type."""
    totals = {}
    for key, entry in report.items():
        type_key = key.split(" [", 1)[0]
        ok, cases = totals.get(type_key, (0, 0))
        totals[type_key] = (ok + (entry["status"] == "ok"), cases + 1)
    for type_key, (ok, cases) in totals.items():
        print("{:55s} {:4d} / {:4d}".format(type_key, ok, cases))


def main(argv):
    type_ids = [argv[i + 1] for i, arg in enumerate(argv[:-1]) if arg == "--type"] or TYPE_IDS
    report = run(type_ids)
    smoke.report_and_save(report, argv)
    summary(report)


if __name__ == "__main__":
    main(sys.argv)
