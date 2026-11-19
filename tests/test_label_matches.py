"""hvaclib.label_matches: a sync must not rewrite a label FreeCAD only made unique."""

from freecad.HVAC.utils import hvaclib


def test_same_label_matches():
    assert hvaclib.label_matches("Tee - Straight [Primary]", "Tee - Straight [Primary]")


def test_freecad_uniqueness_suffix_matches():
    assert hvaclib.label_matches("Tee - Straight [Primary]015", "Tee - Straight [Primary]")


def test_other_label_does_not_match():
    assert not hvaclib.label_matches("Tee - Radius [Primary]", "Tee - Straight [Primary]")
    assert not hvaclib.label_matches("Tee - Straight [Primary] copy", "Tee - Straight [Primary]")
    assert not hvaclib.label_matches("Tee", "Tee - Straight [Primary]")
