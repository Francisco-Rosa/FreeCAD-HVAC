import conftest  # noqa: F401 -- installs FreeCAD/FreeCADGui/Part/PySide stubs
from conftest import FakeVector

from freecad.HVAC.library import static_shapes


class _FakeShape:
    def __init__(self):
        self.read_calls = []
        self.import_brep_calls = []

    def read(self, path):
        self.read_calls.append(path)

    def importBrep(self, path):
        self.import_brep_calls.append(path)

    def isNull(self):
        return False

    def transformShape(self, *a, **k):
        pass


def test_read_shape_uses_generic_read_for_step(tmp_path, monkeypatch):
    # Part.Shape has no importStep() method (confirmed against FreeCAD's own
    # TopoShapePy source) -- STEP/STP files must go through the generic
    # read() entry point, the same one IGES/BREP auto-detection uses.
    step_file = tmp_path / "model.step"
    step_file.write_text("not a real step file, just needs to exist")

    fake_shape = _FakeShape()
    monkeypatch.setattr(static_shapes.Part, "Shape", lambda: fake_shape)

    shape = static_shapes._read_shape(str(tmp_path / "descriptor.json"), {"file": "model.step"})

    assert shape is fake_shape
    assert fake_shape.read_calls == [str(step_file)]
    assert fake_shape.import_brep_calls == []


def test_read_shape_uses_import_brep_for_brep(tmp_path, monkeypatch):
    brep_file = tmp_path / "model.brep"
    brep_file.write_text("not a real brep file, just needs to exist")

    fake_shape = _FakeShape()
    monkeypatch.setattr(static_shapes.Part, "Shape", lambda: fake_shape)

    static_shapes._read_shape(str(tmp_path / "descriptor.json"), {"file": "model.brep"})

    assert fake_shape.import_brep_calls == [str(brep_file)]
    assert fake_shape.read_calls == []


def test_context_origin_center_point_ignores_attachment_offset():
    # "center_point" is the raw, unadjusted topology node -- it must resolve
    # to context["center_point"] regardless of any connected port's own
    # (Attachment/Offset-adjusted) position.
    class _FakeApi:
        @staticmethod
        def vec(v):
            return v

    context = {"center_point": "RAW_NODE"}
    runtime_ports = [{"position": "ADJUSTED_PORT_POSITION"}]

    origin = static_shapes._context_origin(context, _FakeApi, runtime_ports, "center_point", 0)

    assert origin == "RAW_NODE"


def test_context_origin_runtime_port_tracks_attachment_offset():
    # "runtime_port" must resolve to the port's own position, which
    # NetworkParser.py computes via the same compute_port_position() call
    # used for the connected segment's own rendered (Attachment/Offset
    # -adjusted) endpoint -- this is what makes a static descriptor track
    # a connected segment's Attachment/Offset, unlike "center_point".
    class _FakeApi:
        @staticmethod
        def vec(v):
            return v

        @staticmethod
        def port_position(port):
            return port["position"]

    context = {"center_point": "RAW_NODE"}
    runtime_ports = [{"position": "ADJUSTED_PORT_POSITION"}]

    origin = static_shapes._context_origin(context, _FakeApi, runtime_ports, "runtime_port", 0)

    assert origin == "ADJUSTED_PORT_POSITION"


def test_build_transform_defaults_junction_origin_to_runtime_port(monkeypatch):
    # Regression: the default (when a descriptor omits placement.origin_context
    # entirely) must be "runtime_port", not "center_point" -- otherwise a
    # junction placed via a static descriptor silently stops following a
    # connected segment's Attachment/Offset, while every other junction
    # generator (which anchors on api.port_position(...)) keeps tracking it.
    captured = {}

    def fake_context_origin(context, api, runtime_ports, mode, anchor_index):
        captured["mode"] = mode
        return "ORIGIN"

    class _FakeApi:
        @staticmethod
        def vec(v):
            return v

        @staticmethod
        def port_direction(port):
            return (0.0, 0.0, 1.0)

        @staticmethod
        def port_profile_x_axis(port):
            return None

        @staticmethod
        def make_profile_frame(direction, preferred_x=None, origin=None):
            class _Frame:
                def inverse(self):
                    return self

                def multiply(self, other):
                    return self

            return _Frame(), None, None, None

    monkeypatch.setattr(static_shapes, "_context_origin", fake_context_origin)

    desc = {"placement": {}}  # no origin_context declared
    context = {"connected_ports": [{"position": "P"}]}
    static_shapes._build_transform(desc, context, _FakeApi, [{"position": "P"}])

    assert captured["mode"] == "runtime_port"


def test_build_static_geometry_rejects_connection_lengths_for_segment_context(tmp_path, monkeypatch):
    descriptor_path = tmp_path / "descriptor.json"
    descriptor_path.write_text("{}")

    fake_shape = _FakeShape()
    monkeypatch.setattr(static_shapes, "_load_descriptor", lambda path: {
        "source": {"file": "model.step"},
        "outputs": {"connection_lengths": {"P1": 10.0}},
    })
    class _FakeTransform:
        def toMatrix(self):
            return None

    monkeypatch.setattr(static_shapes, "_read_shape", lambda path, source: fake_shape)
    monkeypatch.setattr(static_shapes, "_build_transform", lambda *a, **k: _FakeTransform())
    monkeypatch.setattr(static_shapes, "_validate_ports", lambda *a, **k: None)

    class _FakeApi:
        @staticmethod
        def single_layer(context, shape, **extra):
            return dict({"layers": {"shape": {"shape": shape}}}, **extra)

        @staticmethod
        def vec(v):
            return FakeVector(v)

        @staticmethod
        def unit(v):
            return v.normalize()

    # Segment-style context: no "connected_ports" key.
    context = {
        "hvac_api": _FakeApi,
        "start_point": (0.0, 0.0, 0.0),
        "end_point": (1.0, 0.0, 0.0),
    }

    try:
        static_shapes.build_static_geometry(str(descriptor_path), context)
    except static_shapes.StaticDescriptorError as exc:
        assert "junction" in str(exc).lower()
    else:
        raise AssertionError("Expected StaticDescriptorError for segment-context connection_lengths")
