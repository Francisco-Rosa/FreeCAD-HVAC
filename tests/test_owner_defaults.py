"""
Focused tests for DuctSegment.applyOwnerDefaults(): a newly-created segment
picks up its owner network's DefaultAttachment/DefaultOffset/DefaultDiameter/
DefaultWidth/DefaultHeight unless it already has its own value.

Construction-layer material defaults no longer happen here -- which layers
exist depends on a type this object hasn't been given yet at construction
time (TypeId is still unset), so they're applied by
core/_construction_schema.py's apply_default_layer_materials(), called from
applyTypeSchema() every time the construction schema is (re)established --
see tests/test_construction_schema.py for that behavior. DuctComponent no
longer has an applyOwnerDefaults() of its own at all (it used to exist only
to apply the old two-slot casing/insulation material defaults).
"""

import conftest  # noqa: F401 -- installs FreeCAD/FreeCADGui/Part/Materials/MatGui/PySide stubs

from freecad.HVAC.core import Segment as segment_mod


class FakeOwner:
    def __init__(self):
        self.DefaultAttachment = "Center"
        self.DefaultOffset = None  # falls back to FreeCAD.Vector(0,0,0) inside applyOwnerDefaults
        self.DefaultDiameter = 100.0
        self.DefaultWidth = 100.0
        self.DefaultHeight = 100.0


class FakeSegmentObj:
    def __init__(self):
        self.Diameter = 0.0
        self.Width = 0.0
        self.Height = 0.0
        self.ProfileXAxis = None
        self.Attachment = None
        self.Offset = None


def _bare_segment():
    return segment_mod.DuctSegment.__new__(segment_mod.DuctSegment)


def test_segment_applies_owner_default_dimensions_when_unassigned():
    owner = FakeOwner()
    obj = FakeSegmentObj()

    _bare_segment().applyOwnerDefaults(obj, owner)

    assert obj.Diameter == 100.0
    assert obj.Width == 100.0
    assert obj.Height == 100.0
    assert obj.Attachment == "Center"


def test_segment_never_overwrites_its_own_already_assigned_dimensions():
    owner = FakeOwner()
    owner.DefaultDiameter = 250.0
    obj = FakeSegmentObj()
    obj.Diameter = 150.0

    _bare_segment().applyOwnerDefaults(obj, owner)

    assert obj.Diameter == 150.0


def test_segment_owner_defaults_noop_without_an_owner():
    obj = FakeSegmentObj()
    _bare_segment().applyOwnerDefaults(obj, None)  # must not raise
    assert obj.Diameter == 0.0
