# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the HVAC addon.

"""
Focused regression tests for four concrete defects fixed in
library/fittings/: the radiussed/mitered transition's
wrong "Length" property alias, the lateral tee's doubled branch trim, the
radius wye's size-dependent main-leg selection, and the generic terminal's
missing connection_lengths/unused Length property.

library/fittings/*.py is otherwise out of scope for unit tests (see
AGENTS.md) since it normally requires real FreeCAD/Part geometry this
sandbox doesn't have -- these tests only reach the specific code paths
that are pure vector/dict arithmetic (no BREP/BoundBox needed), or (for
the lateral tee) use a small analytic stand-in for profile_from_port/
profile_projection_bounds so the fitting's own real layout logic still
runs end-to-end without needing a real Part.Wire/BoundBox.
"""

import os

import pytest

import conftest  # noqa: F401 -- installs FreeCAD/FreeCADGui/Part/PySide stubs
from freecad.HVAC.library.fittings import _common, stars, tees, terminals, transitions, wyes
from freecad.HVAC.library.Library import HVACLibraryRegistry
from freecad.HVAC.library.library_api import HVACLibraryAPI
from freecad.HVAC.library.validation import PortValues

LIBRARIES_ROOT = os.path.join(os.path.dirname(__file__), "..", "freecad", "HVAC", "libraries")


def _port(edge_key, direction, diameter, position=(0.0, 0.0, 0.0), segment_end="start", flow_into_junction=True):
    return {
        "edge_key": edge_key,
        "position": list(position),
        "direction": list(direction),
        "profile": "Circular",
        "section_params": {"Diameter": diameter},
        "attachment": "Center",
        "user_offset": [0.0, 0.0, 0.0],
        "profile_x_axis": None,
        "flow_role": "inlet" if flow_into_junction else "outlet",
        "flow_direction": list(direction),
        "flow_into_junction": flow_into_junction,
        "segment_end": segment_end,
    }


# ----------------------------------------------------------------------
# 1. Transition parameter handling -- TransitionRadius must be read
# independently of TransitionLength (and of the never-declared "Length").
# ----------------------------------------------------------------------


def _transition_ports():
    return [
        _port("A", (-1.0, 0.0, 0.0), 200.0, segment_end="start"),
        _port("B", (1.0, 0.0, 0.0), 200.0, position=(300.0, 0.0, 0.0), segment_end="end", flow_into_junction=False),
    ]


def test_transition_radiussed_uses_transition_radius_not_length():
    # A bogus "Length" value (the never-declared alias the old code read
    # for BOTH total and radius) must be ignored entirely; only the
    # actually-declared TransitionLength/TransitionRadius apply.
    ctx = {
        "hvac_api": HVACLibraryAPI,
        "properties": {"TransitionLength": 300.0, "TransitionRadius": 500.0, "Length": 999999.0},
        "connected_ports": _transition_ports(),
    }
    ports, route = transitions._transition_radiussed_route(ctx)
    # A radius of 500 (much larger than TransitionLength=300) pushes the
    # tangent points out beyond the straight run -- if "Length" (999999)
    # had leaked into either total or radius, this would raise or produce
    # wildly different trims. Getting a finite, sane trim confirms the
    # actually-declared properties were used.
    assert all(t >= 0.0 for t in route["trim_lengths"])


def _offset_transition_ports():
    # A real lateral offset (not just opposite-collinear, which has zero
    # turn_angle and so no bend for TransitionRadius to affect at all --
    # see offset_transition_axis) so TransitionRadius actually drives the
    # bend's own feasibility.
    return [
        _port("A", (-1.0, 0.0, 0.0), 20.0, segment_end="start"),
        _port("B", (1.0, 0.0, 0.0), 20.0, position=(200.0, 300.0, 0.0), segment_end="end", flow_into_junction=False),
    ]


class _RadiusRecordingAPI:
    """The real API, recording the radius make_radiussed_path is called with."""

    def __init__(self):
        self.radii = []

    def __getattr__(self, name):
        return getattr(HVACLibraryAPI, name)

    def make_radiussed_path(self, port0, port1, length, radius):
        self.radii.append(radius)
        return {"path": None, "ports": [port0, port1], "trim_lengths": [0.0, 0.0]}


def _radiussed_radius(params):
    api = _RadiusRecordingAPI()
    transitions._transition_radiussed_route(
        {"hvac_api": api, "properties": params, "connected_ports": _offset_transition_ports()}
    )
    return api.radii[-1]


def test_transition_radiussed_radius_actually_used_not_a_dead_parameter():
    # TransitionRadius is read and passed through when it fits ...
    assert _radiussed_radius({"TransitionLength": 400.0, "TransitionRadius": 150.0}) == pytest.approx(150.0)
    assert _radiussed_radius({"TransitionLength": 400.0, "TransitionRadius": 130.0}) == pytest.approx(130.0)


def test_transition_radiussed_radius_too_large_is_reduced_to_what_fits():
    # ... and reduced to the largest radius that fits when it does not
    # (it used to raise "Radius is too large ..."), never using "Length".
    capped = _radiussed_radius({"TransitionLength": 400.0, "TransitionRadius": 2000.0, "Length": 5.0})
    assert 100.0 <= capped < 2000.0
    assert capped == pytest.approx(_radiussed_radius({"TransitionLength": 400.0, "TransitionRadius": 5000.0}))


def test_transition_radiussed_too_steep_for_the_duct_size_says_so():
    with pytest.raises(ValueError) as excinfo:
        _radiussed_radius({"TransitionLength": 20.0, "TransitionRadius": 0.0})
    assert "too steep" in str(excinfo.value)


def test_transition_length_not_read_from_legacy_length_key():
    # No TransitionLength declared at all -- "Length" must NOT be read as
    # a fallback (the old p.get("Length", p.get("TransitionLength"))
    # aliasing); the function must fall back to its own size-based default
    # instead of picking up the bogus "Length" value.
    ports = _transition_ports()
    size = max(_common._size(HVACLibraryAPI, ports[0]), _common._size(HVACLibraryAPI, ports[1]))
    ctx_with_bogus_length = {"hvac_api": HVACLibraryAPI, "properties": {"Length": 999999.0}, "connected_ports": ports}
    ctx_without_any = {"hvac_api": HVACLibraryAPI, "properties": {}, "connected_ports": ports}

    _, trim_with_bogus = transitions._transition_layout(ctx_with_bogus_length)
    _, trim_without_any = transitions._transition_layout(ctx_without_any)

    assert trim_with_bogus == trim_without_any == max(size, 100.0) / 2.0


def test_transition_mitered_uses_transition_length_not_legacy_length_key():
    ports = _transition_ports()
    ctx_with_bogus_length = {"hvac_api": HVACLibraryAPI, "properties": {"Length": 999999.0}, "connected_ports": ports}
    ctx_without_any = {"hvac_api": HVACLibraryAPI, "properties": {}, "connected_ports": ports}

    _, _, total_with_bogus, _, _, _ = transitions._transition_mitered_layout(ctx_with_bogus_length)
    _, _, total_without_any, _, _, _ = transitions._transition_mitered_layout(ctx_without_any)

    assert total_with_bogus == total_without_any


# ----------------------------------------------------------------------
# 2. Lateral tee -- TrimBranch/branch_min must be measured from the
# actual inclined run surface, not double that distance.
# ----------------------------------------------------------------------


class _AnalyticProfileAPI:
    """
    Wraps the real HVACLibraryAPI, replacing profile_from_port/
    profile_projection_bounds with an analytic stand-in for a circular
    profile (its own center position + radius) -- avoids needing a real
    Part.Wire/BoundBox (unavailable in this sandbox) while still running
    _lateral_tee_layout's own real vector-math logic end-to-end, including
    the exact branch_min calculation this test targets.
    """

    def __getattr__(self, name):
        return getattr(HVACLibraryAPI, name)

    @staticmethod
    def profile_from_port(port, offset=0.0):
        return port

    @staticmethod
    def profile_projection_bounds(profile, direction):
        center = HVACLibraryAPI.vec(profile["position"])
        radius = float(profile["section_params"]["Diameter"]) / 2.0
        center_proj = center.dot(direction)
        return center_proj - radius, center_proj + radius


def _lateral_tee_context(trim_branch=None):
    api = _AnalyticProfileAPI()
    # All three ports coincident at the junction's own anchor point (the
    # real convention -- see composeComponents()'s own "every 2-port
    # backend treats its two given ports as coincident" docstring),
    # distinguished only by outward direction: run_a/run_b collinear along
    # X, branch perpendicular along +Y.
    run_a = _port("A", (-1.0, 0.0, 0.0), 200.0)
    run_b = _port("B", (1.0, 0.0, 0.0), 200.0, segment_end="end", flow_into_junction=False)
    branch = _port("C", (0.0, 1.0, 0.0), 200.0, segment_end="end", flow_into_junction=False)
    params = {} if trim_branch is None else {"TrimBranch": trim_branch}
    context = {
        "hvac_api": api,
        "properties": params,
        "connected_ports": [run_a, run_b, branch],
        "center_point": (0.0, 0.0, 0.0),
        "analysis": {"collinear_pairs": [{"a": 0, "b": 1}]},
    }
    return context, run_a, run_b, branch


def test_lateral_tee_branch_min_matches_run_surface_distance_not_double():
    context, run_a, run_b, branch = _lateral_tee_context(trim_branch=50.0)
    layout = tees._lateral_tee_layout(context)

    expected_branch_min = max(
        0.0, (layout["run_surface"] - HVACLibraryAPI.vec(branch["position"])).dot(layout["branch_dir"])
    )
    assert expected_branch_min == 100.0  # sanity: a real, non-degenerate distance

    expected_trim_branch = expected_branch_min + 50.0
    assert layout["trim_branch"] == expected_trim_branch
    # The old bug doubled branch_min -- make the regression explicit.
    assert layout["trim_branch"] != 2 * expected_branch_min + 50.0


def test_lateral_tee_trim_branch_grows_by_exactly_the_extra_trim_property():
    context_a, *_ = _lateral_tee_context(trim_branch=0.0)
    context_b, *_ = _lateral_tee_context(trim_branch=75.0)

    layout_a = tees._lateral_tee_layout(context_a)
    layout_b = tees._lateral_tee_layout(context_b)

    assert layout_b["trim_branch"] - layout_a["trim_branch"] == 75.0


# ----------------------------------------------------------------------
# 3. Radius wye -- the common/main leg is a geometric identity (from port
# directions), never chosen by duct size.
# ----------------------------------------------------------------------


def _wye_ports(common_diameter, branch1_diameter, branch2_diameter):
    # A real Y-shape: common leg outward +X, the two branches spread out
    # on the opposite (-X) side -- branch1/branch2's own outward
    # directions are closer to each other than either is to the common
    # leg's, exactly the geometric signal _wye_common_index relies on.
    return [
        _port("A", (1.0, 0.0, 0.0), common_diameter),
        _port("B", (-0.6, 0.8, 0.0), branch1_diameter),
        _port("C", (-0.6, -0.8, 0.0), branch2_diameter),
    ]


def test_wye_common_index_unaffected_by_which_leg_has_the_largest_duct():
    # Same physical arrangement, only the diameters change -- the common
    # leg is always port A (index 0) regardless of which leg is biggest.
    common_largest = _wye_ports(common_diameter=500.0, branch1_diameter=100.0, branch2_diameter=100.0)
    branch_largest = _wye_ports(common_diameter=50.0, branch1_diameter=900.0, branch2_diameter=100.0)
    all_equal = _wye_ports(common_diameter=200.0, branch1_diameter=200.0, branch2_diameter=200.0)

    assert wyes._wye_common_index(HVACLibraryAPI, common_largest) == 0
    assert wyes._wye_common_index(HVACLibraryAPI, branch_largest) == 0
    assert wyes._wye_common_index(HVACLibraryAPI, all_equal) == 0


def test_wye_common_index_follows_port_order_not_a_fixed_slot():
    # Rotate which index physically holds the common leg -- the function
    # must track port geometry, not always answer the same fixed index.
    ports = [
        _port("A", (-0.6, 0.8, 0.0), 100.0),
        _port("B", (-0.6, -0.8, 0.0), 100.0),
        _port("C", (1.0, 0.0, 0.0), 500.0),
    ]
    assert wyes._wye_common_index(HVACLibraryAPI, ports) == 2


# ----------------------------------------------------------------------
# 4. Generic terminal body -- geometry/measurement contract + BodyLength.
# ----------------------------------------------------------------------


def test_measure_terminal_body_generic_equals_body_length():
    ctx = {
        "hvac_api": HVACLibraryAPI,
        "properties": {"BodyLength": 175.0},
        "connected_ports": [_port("A", (1.0, 0.0, 0.0), 250.0)],
    }
    records = terminals.measure_terminal_body_generic(ctx)
    assert records == [{"edge_key": "A", "segment_end": "start", "length": 175.0}]


def test_build_terminal_body_generic_reports_matching_connection_length():
    ctx = {
        "hvac_api": HVACLibraryAPI,
        "properties": {"BodyLength": 175.0},
        "connected_ports": [_port("A", (1.0, 0.0, 0.0), 250.0)],
    }
    measured = terminals.measure_terminal_body_generic(ctx)
    built = terminals.build_terminal_body_generic(ctx)
    assert built["connection_lengths"] == measured == [{"edge_key": "A", "segment_end": "start", "length": 175.0}]


def test_terminal_body_generic_falls_back_to_size_based_default_without_body_length():
    port = _port("A", (1.0, 0.0, 0.0), 300.0)
    ctx = {"hvac_api": HVACLibraryAPI, "properties": {}, "connected_ports": [port]}
    records = terminals.measure_terminal_body_generic(ctx)
    expected = 0.35 * _common._size(HVACLibraryAPI, port)
    assert records == [{"edge_key": "A", "segment_end": "start", "length": expected}]


def test_generic_terminal_descriptors_declare_measurement_function():
    reg = HVACLibraryRegistry()
    reg.set_search_paths([LIBRARIES_ROOT])
    reg.ensure_loaded()
    lib = reg.get_library("builtin_basic")
    for type_id in ("end_diffuser_generic", "end_fan_source_generic", "end_intake_exhaust_generic"):
        type_def = lib.get_type(type_id)
        assert type_def.generator_function == "build_terminal_body_generic", type_id
        assert type_def.lengths_module == "shared:terminals", type_id
        assert type_def.lengths_function == "measure_terminal_body_generic", type_id
        assert any(p.name == "BodyLength" for p in type_def.properties), type_id


# ----------------------------------------------------------------------
# 5. Star fittings -- each port's own TrimPort<letter> must be honoured
# (these properties used to be declared in the type-def but never read).
# ----------------------------------------------------------------------


def _cross_context(params):
    ports = [
        _port("A", (-1.0, 0.0, 0.0), 200.0),
        _port("B", (1.0, 0.0, 0.0), 200.0, segment_end="end", flow_into_junction=False),
        _port("C", (0.0, 1.0, 0.0), 200.0, segment_end="end", flow_into_junction=False),
        _port("D", (0.0, -1.0, 0.0), 200.0, segment_end="end", flow_into_junction=False),
    ]
    return {"hvac_api": HVACLibraryAPI, "properties": params, "connected_ports": ports, "center_point": (0.0, 0.0, 0.0)}


def _lengths_by_edge(records):
    return {rec["edge_key"]: rec["length"] for rec in records}


def test_star_cross_uses_each_ports_own_trim():
    # TrimLength is a per-port property: its own value for every port, keyed by edge_key.
    params = {"TrimLength": PortValues({"A": 110.0, "B": 120.0, "C": 130.0, "D": 140.0}, default=100.0)}
    lengths = _lengths_by_edge(stars.measure_cross(_cross_context(params)))
    assert lengths == pytest.approx({"A": 110.0, "B": 120.0, "C": 130.0, "D": 140.0})


def test_star_cross_unset_port_trim_falls_back_to_size_based_default():
    # 0.6 x the largest port size (200) is the built-in default for a cross.
    params = {"TrimLength": PortValues({"A": 90.0, "B": 0.0}, default=0.0)}
    lengths = _lengths_by_edge(stars.measure_cross(_cross_context(params)))
    assert lengths == pytest.approx({"A": 90.0, "B": 120.0, "C": 120.0, "D": 120.0})


def test_star_trim_may_also_be_one_plain_value_for_every_port():
    lengths = _lengths_by_edge(stars.measure_cross(_cross_context({"TrimLength": 75.0})))
    assert lengths == pytest.approx({"A": 75.0, "B": 75.0, "C": 75.0, "D": 75.0})
