# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the HVAC addon.

"""
LossTable: one printed fitting-loss table, with clamped linear interpolation.

Pure Python (no FreeCAD, no numpy) so every table can be unit-tested on its
own. A table is written down the way it is printed: named axes, outermost
first, and a nested list of coefficients. A cell the source leaves blank
("--") is written as None.

A lookup never fails just because a point is off the printed grid. Instead
it says so, and the caller (HVACLossAPI) turns that into a status/warning:

- `clamped`: a coordinate was outside the table's printed range, so the
  nearest edge value was used.
- `filled`: the point touched a blank cell, which was filled with the
  nearest printed value in the same row.
"""

from dataclasses import dataclass

# Every table registers itself here by id (e.g. "14-10B"), so tests and docs
# can list what has been digitised.
ALL_TABLES = {}

# Which duct's velocity pressure a table's coefficient multiplies.
REF_UPSTREAM = "upstream"
REF_DOWNSTREAM = "downstream"


@dataclass(frozen=True)
class Lookup:
    """Result of one table lookup: the coefficient plus how trustworthy the point was."""

    value: float
    clamped: bool = False
    filled: bool = False

    @property
    def exact(self):
        """True when the point was inside the printed table and touched no blank cell."""
        return not (self.clamped or self.filled)


def _fill_row(row):
    """
    Replace the blanks (None) of one innermost row with the nearest printed
    value, preferring the one before it. Returns (filled_row, blank_mask).
    """
    if all(value is None for value in row):
        raise ValueError("A table row has no printed value at all")
    mask = [value is None for value in row]
    filled = list(row)
    last = None
    for i, value in enumerate(filled):
        if value is None:
            filled[i] = last
        else:
            last = value
    # Leading blanks have no value before them: take the first one after.
    following = None
    for i in range(len(filled) - 1, -1, -1):
        if filled[i] is None:
            filled[i] = following
        else:
            following = filled[i]
    return [float(value) for value in filled], mask


def _reorder(values, order):
    return [values[i] for i in order]


class LossTable:
    """
    One printed loss-coefficient table.

    table_id:  the source's own id, e.g. "14-10B".
    title:     the source's own title for the fitting.
    axes:      [(name, [coordinates...]), ...] outermost axis first. The
               coordinates may be listed in either direction, as printed.
    values:    nested lists matching `axes`; None marks a blank cell.
    reference: REF_UPSTREAM or REF_DOWNSTREAM -- whose velocity pressure the
               coefficient multiplies, as stated at the top of the table.
    profiles:  duct profiles the table is printed for ("Circular", ...).
    """

    def __init__(self, table_id, title, axes, values, reference, profiles=()):
        self.table_id = str(table_id)
        self.title = str(title)
        self.reference = reference
        self.profiles = tuple(profiles)
        self.axis_names = [name for name, _ in axes]

        # Step 1: sort every axis ascending, reordering the values to match.
        coords = [[float(c) for c in axis_coords] for _, axis_coords in axes]
        self._check_shape(values, [len(c) for c in coords])
        for depth, axis_coords in enumerate(coords):
            if len(set(axis_coords)) != len(axis_coords):
                raise ValueError("Table {}: axis '{}' repeats a coordinate".format(table_id, self.axis_names[depth]))
            order = sorted(range(len(axis_coords)), key=lambda i: axis_coords[i])
            coords[depth] = [axis_coords[i] for i in order]
            values = self._reorder_depth(values, order, depth)
        self.coords = coords

        # Step 2: fill blanks along the innermost axis, remembering where they were.
        self._values, self._blank = self._fill(values, len(coords))

        if self.table_id in ALL_TABLES:
            raise ValueError("Loss table id '{}' is defined twice".format(self.table_id))
        ALL_TABLES[self.table_id] = self

    # -- construction helpers ------------------------------------------------

    def _check_shape(self, values, sizes):
        if len(values) != sizes[0]:
            raise ValueError(
                "Table {}: expected {} entries along '{}', found {}".format(
                    self.table_id, sizes[0], self.axis_names[len(self.axis_names) - len(sizes)], len(values)
                )
            )
        if len(sizes) > 1:
            for sub in values:
                self._check_shape(sub, sizes[1:])

    @classmethod
    def _reorder_depth(cls, values, order, depth):
        if depth == 0:
            return _reorder(values, order)
        return [cls._reorder_depth(sub, order, depth - 1) for sub in values]

    @classmethod
    def _fill(cls, values, depth):
        if depth == 1:
            return _fill_row(values)
        filled, masks = [], []
        for sub in values:
            f, m = cls._fill(sub, depth - 1)
            filled.append(f)
            masks.append(m)
        return filled, masks

    # -- lookup --------------------------------------------------------------

    @staticmethod
    def _bracket(x, coords):
        """(index_low, index_high, fraction, clamped) for x along one sorted axis."""
        if x <= coords[0]:
            return 0, 0, 0.0, x < coords[0]
        if x >= coords[-1]:
            last = len(coords) - 1
            return last, last, 0.0, x > coords[-1]
        for i in range(len(coords) - 1):
            if coords[i] <= x <= coords[i + 1]:
                # Exactly on the upper grid point: report that point alone,
                # so its lower neighbour (possibly a blank cell) plays no part.
                if x == coords[i + 1]:
                    return i + 1, i + 1, 0.0, False
                span = coords[i + 1] - coords[i]
                return i, i + 1, (x - coords[i]) / span, False
        raise AssertionError("unreachable: x is inside the axis range")

    def _interpolate(self, point, depth, values, blank):
        low, high, fraction, clamped = self._bracket(point[depth], self.coords[depth])
        if depth == len(self.coords) - 1:
            if low == high or fraction == 0.0:
                return values[low], clamped, blank[low]
            value = values[low] + fraction * (values[high] - values[low])
            return value, clamped, blank[low] or blank[high]

        v0, c0, f0 = self._interpolate(point, depth + 1, values[low], blank[low])
        if low == high or fraction == 0.0:
            return v0, clamped or c0, f0
        v1, c1, f1 = self._interpolate(point, depth + 1, values[high], blank[high])
        return v0 + fraction * (v1 - v0), clamped or c0 or c1, f0 or f1

    def lookup(self, *point):
        """Interpolate the table at `point` (one coordinate per axis, outermost first)."""
        if len(point) != len(self.coords):
            raise ValueError(
                "Table {} needs {} coordinates ({}), got {}".format(
                    self.table_id, len(self.coords), ", ".join(self.axis_names), len(point)
                )
            )
        value, clamped, filled = self._interpolate([float(x) for x in point], 0, self._values, self._blank)
        return Lookup(value=value, clamped=clamped, filled=filled)

    def __call__(self, *point):
        """The interpolated coefficient alone, for callers that don't need the flags."""
        return self.lookup(*point).value

    def __repr__(self):
        return "LossTable({!r}, axes={})".format(self.table_id, self.axis_names)


class TableFamily:
    """
    Several tables of the same fitting that differ by one more parameter the
    source does not print on a regular grid (e.g. one block per As/Ac, each
    block with its own list of Ab/Ac rows).

    `tables` maps that parameter's value to its table. A lookup interpolates
    between the two neighbouring tables, and is clamped (and flagged) outside
    the first and last one.
    """

    def __init__(self, parameter, tables):
        self.parameter = str(parameter)
        self._keys = sorted(float(key) for key in tables)
        self._tables = {float(key): table for key, table in tables.items()}

    def lookup(self, key, *point):
        low, high, fraction, clamped = LossTable._bracket(float(key), self._keys)
        first = self._tables[self._keys[low]].lookup(*point)
        if low == high or fraction == 0.0:
            return Lookup(first.value, first.clamped or clamped, first.filled)
        second = self._tables[self._keys[high]].lookup(*point)
        value = first.value + fraction * (second.value - first.value)
        return Lookup(value, clamped or first.clamped or second.clamped, first.filled or second.filled)


class TableRows:
    """
    A table whose rows are a handful of specific fittings (each identified by
    a combination of ratios, e.g. Ab/As = 0.5 with Ab/Ac = 0.5) rather than
    points on an axis one could interpolate along.

    `rows` is a list of (key_tuple, table). A lookup uses the row whose key
    is nearest to the requested one. Unless the request matches a printed
    row (within `tolerance` on every ratio), the result is flagged as
    clamped, since the source has no data for that combination.
    """

    def __init__(self, key_names, rows, tolerance=0.02):
        self.key_names = tuple(key_names)
        self._rows = [(tuple(float(k) for k in key), table) for key, table in rows]
        self.tolerance = float(tolerance)

    def lookup(self, key, *point):
        key = tuple(float(k) for k in key)
        if len(key) != len(self.key_names):
            raise ValueError("Expected {} row ratios ({})".format(len(self.key_names), ", ".join(self.key_names)))

        def distance(row_key):
            # Relative distance, so a ratio of 2.0 and one of 0.25 weigh the same.
            return max(abs(a - b) / max(abs(b), 1.0e-9) for a, b in zip(key, row_key))

        row_key, table = min(self._rows, key=lambda row: distance(row[0]))
        result = table.lookup(*point)
        matched = distance(row_key) <= self.tolerance
        return Lookup(result.value, result.clamped or not matched, result.filled)


def combine(value, *lookups):
    """
    A Lookup for a coefficient computed from several table lookups (e.g. a
    base coefficient times a correction factor): `value` with the flags of
    every lookup that went into it.
    """
    return Lookup(
        value=float(value),
        clamped=any(lookup.clamped for lookup in lookups),
        filled=any(lookup.filled for lookup in lookups),
    )
