# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the HVAC addon.

"""
Side versus face-mounted taps: measuring how far the branch axis passes from
the run axis, and deciding the attachment from it. Shape construction is
out of scope (see AGENTS.md); these tests stop at the numbers.
"""

import pytest

import conftest  # noqa: F401 -- installs FreeCAD/FreeCADGui/Part/PySide stubs
from freecad.HVAC.library.fittings import taps
from freecad.HVAC.library.library_api import HVACLibraryAPI


class _AnalyticProfileAPI:
    """The real API, with circular profiles measured analytically instead of from a Part wire."""

    def __getattr__(self, name):
        return getattr(HVACLibraryAPI, name)

    @staticmethod
    def profile_from_port(port, offset=0.0):
        return port

    @staticmethod
    def profile_projection_bounds(profile, direction):
        center = HVACLibraryAPI.vec(profile["position"])
        radius = float(profile["section_params"]["Diameter"]) / 2.0
        along = center.dot(direction)
        return along - radius, along + radius


def _port(edge_key, direction, diameter, position=(0.0, 0.0, 0.0)):
    return {
        "edge_key": edge_key,
        "position": list(position),
        "direction": list(direction),
        "profile": "Circular",
        "section_params": {"Diameter": diameter},
        "profile_x_axis": None,
        "segment_end": "start",
    }


def _offsets(branch_height, run_diameter=300.0, branch_diameter=200.0):
    api = _AnalyticProfileAPI()
    run_a = _port("A", (-1.0, 0.0, 0.0), run_diameter)
    run_b = _port("B", (1.0, 0.0, 0.0), run_diameter)
    branch = _port("C", (0.0, 1.0, 0.0), branch_diameter, position=(0.0, 0.0, branch_height))
    return taps._attachment_offsets(api, run_a, run_b, branch)


# ----------------------------------------------------------------------------
# Measuring the offset
# ----------------------------------------------------------------------------


def test_axes_that_meet_have_no_offset():
    assert _offsets(0.0) is None


def test_offset_is_the_distance_between_the_axes_with_each_ducts_half_size():
    offsets = _offsets(400.0)
    assert offsets["offset"] == pytest.approx(400.0)
    assert offsets["run_half"] == pytest.approx(150.0)
    assert offsets["branch_half"] == pytest.approx(100.0)
    assert tuple(round(c, 6) for c in (offsets["up"].x, offsets["up"].y, offsets["up"].z)) == (0.0, 0.0, 1.0)


def test_a_branch_below_the_run_points_the_other_way():
    offsets = _offsets(-400.0)
    assert offsets["offset"] == pytest.approx(400.0)
    assert offsets["up"].z == pytest.approx(-1.0)


def test_closest_points_do_not_depend_on_where_the_branch_line_ends():
    api = _AnalyticProfileAPI()
    run_a, run_b = _port("A", (-1.0, 0.0, 0.0), 300.0), _port("B", (1.0, 0.0, 0.0), 300.0)
    branch = _port("C", (0.0, 1.0, 0.0), 200.0, position=(50.0, 700.0, 400.0))
    offsets = taps._attachment_offsets(api, run_a, run_b, branch)
    assert offsets["offset"] == pytest.approx(400.0)
    assert (offsets["q_run"].x, offsets["q_run"].y, offsets["q_run"].z) == pytest.approx((50.0, 0.0, 0.0))
    assert (offsets["q_branch"].x, offsets["q_branch"].y, offsets["q_branch"].z) == pytest.approx((50.0, 0.0, 400.0))


# ----------------------------------------------------------------------------
# Deciding the attachment
# ----------------------------------------------------------------------------


def test_auto_is_a_side_tap_when_the_axes_meet():
    assert taps.attachment_mode("Auto", None) == "Side"
    assert taps.attachment_mode(None, None) == "Side"


def test_auto_is_a_side_tap_while_the_branch_stays_within_the_run_depth():
    # Run half 150, branch half 100: an offset up to 50 keeps the branch inside.
    assert taps.attachment_mode("Auto", _offsets(50.0)) == "Side"


def test_auto_is_face_mounted_once_the_branch_is_clear_of_the_run_surface():
    # Clear from an offset of 250 (150 + 100) upward, either side of the run.
    assert taps.attachment_mode("Auto", _offsets(250.0)) == "Face"
    assert taps.attachment_mode("Auto", _offsets(-400.0)) == "Face"


def test_auto_builds_a_branch_crossing_the_run_edge_as_a_side_tap():
    # Moved in to fit and jogged back to its own axis (taps.branch_jog), not refused.
    assert taps.attachment_mode("Auto", _offsets(120.0)) == "Side"


def test_face_cannot_be_forced_while_the_branch_crosses_the_run_edge():
    with pytest.raises(ValueError) as excinfo:
        taps.attachment_mode("Face", _offsets(120.0))
    assert "130.0 mm further away" in str(excinfo.value)


def test_side_can_be_forced_while_the_branch_still_touches_the_run():
    assert taps.attachment_mode("Side", _offsets(120.0)) == "Side"


def test_side_cannot_be_forced_when_the_branch_passes_clear_of_the_run():
    with pytest.raises(ValueError):
        taps.attachment_mode("Side", _offsets(400.0))


def test_face_cannot_be_forced_when_the_branch_is_not_clear():
    with pytest.raises(ValueError):
        taps.attachment_mode("Face", None)
    with pytest.raises(ValueError) as excinfo:
        taps.attachment_mode("Face", _offsets(120.0))
    assert "130.0 mm" in str(excinfo.value)


def test_unknown_attachment_is_rejected():
    with pytest.raises(ValueError):
        taps.attachment_mode("Top", _offsets(400.0))
