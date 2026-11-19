"""Stable edge keys (ROADMAP 6.4 a): the same before and after a save and reload."""

from types import SimpleNamespace

import FreeCAD

import conftest  # noqa: F401 -- installs FreeCAD stubs
from freecad.HVAC.utils import hvaclib


class _Doc:
    def __init__(self, objects):
        self._objects = objects

    def getObject(self, name):
        return self._objects.get(name)


def test_sketch_edge_key_uses_the_persisted_geometry_id(monkeypatch):
    sketch = SimpleNamespace(Name="Sketch", getGeometryId=lambda index: {0: 7, 1: 12}[index])
    monkeypatch.setattr(FreeCAD, "ActiveDocument", _Doc({"Sketch": sketch}), raising=False)
    monkeypatch.setattr(hvaclib, "isSketch", lambda obj: obj is sketch)
    assert hvaclib.makeLineKey("Sketch", 1) == "Sketch:g12"
    # The index can shift (geometry deleted before it); the id, and so the key, does not.
    sketch.getGeometryId = lambda index: {0: 12}[index]
    assert hvaclib.makeLineKey("Sketch", 0) == "Sketch:g12"


def test_other_edges_use_object_name_and_index(monkeypatch):
    wire = SimpleNamespace(Name="Wire")
    monkeypatch.setattr(FreeCAD, "ActiveDocument", _Doc({"Wire": wire}), raising=False)
    monkeypatch.setattr(hvaclib, "isSketch", lambda obj: False)
    assert hvaclib.makeLineKey("Wire", 2) == "Wire:e2"
    assert hvaclib.makeLineKey("Missing", 0) == "Missing:e0"
