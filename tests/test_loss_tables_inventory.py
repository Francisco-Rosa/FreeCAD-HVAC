# SPDX-License-Identifier: LGPL-2.1-or-later
# SPDX-FileNotice: Part of the HVAC addon.

"""
Inventory of the digitised SMACNA tables: every fitting letter of Tables
14-10 to 14-18 must be either a registered LossTable or one of the letters
the source gives no table for.
"""

import importlib

import pytest

from freecad.HVAC.library.loss_tables import table as t

for _module in (
    "elbows",
    "transitions",
    "junctions_converging",
    "junctions_diverging",
    "entries_exits",
    "obstructions",
    "straight_through",
):
    importlib.import_module("freecad.HVAC.library.loss_tables." + _module)

# Letters the source prints under each table number (it skips "O" in 14-14).
PRINTED_LETTERS = {
    "14-10": "ABCDEFGHIJKL",
    "14-11": "ABCDEFGHIJ",
    "14-12": "ABC",
    "14-13": "ABCDEFGHI",
    "14-14": "ABCDEFGHIJKLMNPQRSTUVWXYZ",
    "14-15": "ABCDEFGHI",
    "14-16": "ABCDEFGHIJ",
    "14-17": "AB",
    "14-18": "ABCDEFGHIJKL",
}

# Fittings that have no table of their own: the source gives a formula, a
# single constant (kept as a module constant) or a pointer to another table.
NO_OWN_TABLE = {
    "14-10L",  # use a similar elbow
    "14-11C",
    "14-11D",  # equivalent angle, then 14-11 B
    "14-15H",  # constant
    "14-15I",  # uses 14-15 G
    "14-16I",
    "14-16J",  # constants
    "14-18I",  # one printed point, kept as a constant
}


def _registered_letters(number):
    prefix = number
    return {
        table_id[len(prefix)]
        for table_id in t.ALL_TABLES
        if table_id.startswith(prefix) and len(table_id) > len(prefix)
    }


@pytest.mark.parametrize("number", sorted(PRINTED_LETTERS))
def test_every_printed_fitting_is_digitised_or_accounted_for(number):
    registered = _registered_letters(number)
    for letter in PRINTED_LETTERS[number]:
        fitting = number + letter
        if fitting in NO_OWN_TABLE:
            assert letter not in registered, "{} is listed as having no table but one is registered".format(fitting)
        else:
            assert letter in registered, "{} has not been digitised".format(fitting)


def test_table_14_9_is_digitised():
    assert "14-9" in t.ALL_TABLES


def test_every_table_states_its_reference_velocity():
    assert t.ALL_TABLES
    for table in t.ALL_TABLES.values():
        assert table.reference in (t.REF_UPSTREAM, t.REF_DOWNSTREAM), table.table_id
