"""
Stub out the FreeCAD/FreeCADGui/Part/Materials/MatGui/PySide modules that
freecad.HVAC.core.* imports at module scope, so those modules can be
imported and unit-tested without a real FreeCAD installation.

The freecad.HVAC.analysis package (tested in test_physics.py/test_analysis_*.py)
has no FreeCAD dependency at all; everything else in this addon does, so any
test that needs freecad.HVAC.core.AirflowSolver relies on this stubbing.
"""

import sys
from unittest.mock import MagicMock


class FakeVector:
    """Minimal real 3D vector, standing in for FreeCAD.Vector's arithmetic
    (a bare MagicMock can't support dot()/normalize() meaningfully)."""

    def __init__(self, x=0.0, y=0.0, z=0.0):
        if hasattr(x, "x") and hasattr(x, "y") and hasattr(x, "z"):
            self.x, self.y, self.z = float(x.x), float(x.y), float(x.z)
        elif isinstance(x, (tuple, list)):
            self.x = float(x[0])
            self.y = float(x[1])
            self.z = float(x[2]) if len(x) > 2 else 0.0
        else:
            self.x, self.y, self.z = float(x), float(y), float(z)

    def dot(self, other):
        return self.x * other.x + self.y * other.y + self.z * other.z

    def cross(self, other):
        return FakeVector(
            self.y * other.z - self.z * other.y,
            self.z * other.x - self.x * other.z,
            self.x * other.y - self.y * other.x,
        )

    @property
    def Length(self):
        return (self.x ** 2 + self.y ** 2 + self.z ** 2) ** 0.5

    def normalize(self):
        length = self.Length
        if length > 0:
            self.x /= length
            self.y /= length
            self.z /= length
        return self

    def __sub__(self, other):
        return FakeVector(self.x - other.x, self.y - other.y, self.z - other.z)

    def __add__(self, other):
        return FakeVector(self.x + other.x, self.y + other.y, self.z + other.z)

    def __mul__(self, scalar):
        return FakeVector(self.x * scalar, self.y * scalar, self.z * scalar)

    def __rmul__(self, scalar):
        return self.__mul__(scalar)

    def __neg__(self):
        return FakeVector(-self.x, -self.y, -self.z)

    def __eq__(self, other):
        return isinstance(other, FakeVector) and (self.x, self.y, self.z) == (other.x, other.y, other.z)

    def __repr__(self):
        return "FakeVector({}, {}, {})".format(self.x, self.y, self.z)


for _name in ("FreeCAD", "FreeCADGui", "Part", "Mesh", "Materials", "MatGui", "PySide", "PySide.QtWidgets", "PySide.QtCore"):
    if _name not in sys.modules:
        sys.modules[_name] = MagicMock(name=_name)
sys.modules["FreeCAD"].Qt.translate = lambda *a, **k: (a[1] if len(a) > 1 else "")
sys.modules["FreeCAD"].Vector = FakeVector

# freecad.HVAC.library.Library <-> freecad.HVAC.library.library_api <->
# freecad.HVAC.utils.hvaclib form an import cycle that only resolves cleanly
# when utils.hvaclib is the *first* of the three to start importing (see
# Library.py/library_api.py/hvaclib.py for the exact chain). Priming it here,
# once, lets any test module import library_api/Library.py directly without
# tripping over "partially initialized module" errors.
import freecad.HVAC.utils.hvaclib  # noqa: E402,F401
