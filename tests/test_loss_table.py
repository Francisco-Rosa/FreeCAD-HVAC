# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the HVAC addon.

"""LossTable: interpolation, clamping, blank cells and axis ordering."""

import pytest

from freecad.HVAC.library.loss_tables import table as t


@pytest.fixture(autouse=True)
def _isolated_registry(monkeypatch):
    # Tables made by these tests must not leak into the real registry.
    monkeypatch.setattr(t, "ALL_TABLES", {})


def _table_1d():
    return t.LossTable("T1", "one axis", [("x", [0.0, 1.0, 3.0])], [10.0, 20.0, 40.0], t.REF_UPSTREAM)


def _table_2d():
    return t.LossTable(
        "T2",
        "two axes",
        [("y", [0.0, 10.0]), ("x", [0.0, 1.0, 2.0])],
        [[0.0, 1.0, 2.0], [10.0, 11.0, 12.0]],
        t.REF_DOWNSTREAM,
    )


def test_grid_point_is_exact():
    result = _table_1d().lookup(1.0)
    assert result.value == 20.0
    assert result.exact


def test_interpolates_between_grid_points():
    assert _table_1d()(2.0) == pytest.approx(30.0)
    assert _table_2d()(5.0, 0.5) == pytest.approx(5.5)


def test_outside_range_is_clamped_and_flagged():
    table = _table_1d()
    low, high = table.lookup(-5.0), table.lookup(99.0)
    assert (low.value, low.clamped) == (10.0, True)
    assert (high.value, high.clamped) == (40.0, True)
    assert not low.exact


def test_clamp_on_any_axis_is_flagged():
    result = _table_2d().lookup(50.0, 1.0)
    assert result.value == pytest.approx(11.0)
    assert result.clamped


def test_axes_may_be_listed_descending_as_printed():
    table = t.LossTable(
        "T3",
        "descending",
        [("y", [10.0, 0.0]), ("x", [2.0, 1.0, 0.0])],
        [[12.0, 11.0, 10.0], [2.0, 1.0, 0.0]],
        t.REF_UPSTREAM,
    )
    assert table(0.0, 0.0) == 0.0
    assert table(10.0, 2.0) == 12.0
    assert table(5.0, 0.5) == pytest.approx(5.5)


def test_blank_cells_are_filled_from_the_row_and_flagged():
    table = t.LossTable(
        "T4",
        "blanks",
        [("y", [0.0, 1.0]), ("x", [0.0, 1.0, 2.0, 3.0])],
        [[None, 1.0, 2.0, None], [5.0, 6.0, 7.0, 8.0]],
        t.REF_UPSTREAM,
    )
    trailing = table.lookup(0.0, 3.0)
    assert (trailing.value, trailing.filled) == (2.0, True)
    leading = table.lookup(0.0, 0.0)
    assert (leading.value, leading.filled) == (1.0, True)
    assert table.lookup(0.0, 1.5).exact
    # Interpolating toward a blank cell touches it, so it is flagged too.
    assert table.lookup(0.0, 2.5).filled
    assert table.lookup(0.5, 3.0).filled
    assert table.lookup(1.0, 3.0).exact


def test_wrong_shape_is_rejected():
    with pytest.raises(ValueError):
        t.LossTable("T5", "bad", [("x", [0.0, 1.0])], [1.0, 2.0, 3.0], t.REF_UPSTREAM)
    with pytest.raises(ValueError):
        t.LossTable("T6", "bad", [("y", [0.0, 1.0]), ("x", [0.0, 1.0])], [[1.0, 2.0], [3.0]], t.REF_UPSTREAM)


def test_row_of_only_blanks_is_rejected():
    with pytest.raises(ValueError):
        t.LossTable("T7", "bad", [("x", [0.0, 1.0])], [None, None], t.REF_UPSTREAM)


def test_duplicate_id_and_repeated_coordinate_are_rejected():
    _table_1d()
    with pytest.raises(ValueError):
        _table_1d()
    with pytest.raises(ValueError):
        t.LossTable("T8", "bad", [("x", [0.0, 0.0])], [1.0, 2.0], t.REF_UPSTREAM)


def test_wrong_number_of_coordinates_is_rejected():
    with pytest.raises(ValueError):
        _table_2d().lookup(1.0)


def test_tables_register_by_id():
    table = _table_1d()
    assert t.ALL_TABLES["T1"] is table


def test_combine_carries_flags_from_every_lookup():
    table = _table_1d()
    result = t.combine(3.0, table.lookup(1.0), table.lookup(99.0))
    assert result.value == 3.0
    assert result.clamped and not result.filled


def test_table_family_interpolates_between_neighbouring_tables_and_clamps_outside():
    low = t.LossTable("F1", "low", [("x", [0.0, 1.0])], [0.0, 10.0], t.REF_UPSTREAM)
    high = t.LossTable("F2", "high", [("x", [0.0, 1.0])], [100.0, 110.0], t.REF_UPSTREAM)
    family = t.TableFamily("k", {2.0: high, 1.0: low})
    assert family.lookup(1.0, 0.5).value == pytest.approx(5.0)
    assert family.lookup(1.5, 0.5).value == pytest.approx(55.0)
    assert family.lookup(1.5, 0.5).exact
    outside = family.lookup(3.0, 0.5)
    assert outside.value == pytest.approx(105.0)
    assert outside.clamped
    assert family.lookup(1.5, 7.0).clamped


def test_table_rows_use_the_nearest_row_and_flag_anything_not_printed():
    a = t.LossTable("R1", "a", [("x", [0.0, 1.0])], [1.0, 2.0], t.REF_UPSTREAM)
    b = t.LossTable("R2", "b", [("x", [0.0, 1.0])], [10.0, 20.0], t.REF_UPSTREAM)
    rows = t.TableRows(("p", "q"), [((0.5, 0.5), a), ((1.0, 0.5), b)])
    exact = rows.lookup((0.5, 0.5), 1.0)
    assert (exact.value, exact.exact) == (2.0, True)
    near = rows.lookup((0.505, 0.5), 1.0)
    assert near.exact
    other = rows.lookup((0.9, 0.5), 0.0)
    assert (other.value, other.clamped) == (10.0, True)
    with pytest.raises(ValueError):
        rows.lookup((0.5,), 0.0)
