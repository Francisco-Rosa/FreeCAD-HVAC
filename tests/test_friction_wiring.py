"""
FreeCAD-side friction wiring: the network FrictionModel property, the
segment type-def "friction" factory and the shipped flexible duct type.
"""

from types import SimpleNamespace

import pytest
from test_shipped_type_references import _load_registry

import conftest  # noqa: F401 -- installs FreeCAD/Materials stubs
from freecad.HVAC.analysis import friction as fr
from freecad.HVAC.analysis.model import SectionModel, SegmentModel
from freecad.HVAC.core import _analysis_adapter
from freecad.HVAC.library.Library import HVACLibraryRegistry


def _net(**props):
    return SimpleNamespace(**props)


def test_network_default_is_none():
    assert _analysis_adapter.network_friction_model(_net()) is None
    assert _analysis_adapter.network_friction_model(_net(FrictionModel="DarcyAltshulTsal")) is None


def test_network_colebrook_and_expression():
    model = _analysis_adapter.network_friction_model(_net(FrictionModel="DarcyColebrook"))
    assert isinstance(model, fr.DarcyWeisbach) and model.factor == fr.COLEBROOK
    model = _analysis_adapter.network_friction_model(_net(FrictionModel="Expression", FrictionExpression="2 * V"))
    assert model.evaluate(Q=0, V=3.0, Dh=1, A=1, eps=0, rho=1, nu=1, Re=0) == pytest.approx(6.0)


def test_network_table_reads_the_csv_file(tmp_path):
    path = tmp_path / "chart.csv"
    path.write_text("diameter_mm,velocity_ms,pa_per_m\n100,2,0.5\n100,4,1.8\n", encoding="utf-8")
    model = _analysis_adapter.network_friction_model(_net(FrictionModel="Table", FrictionTableFile=str(path)))
    assert isinstance(model, fr.TableFriction) and "chart.csv" in model.label


@pytest.mark.parametrize(
    "props,match",
    [
        ({"FrictionModel": "Table", "FrictionTableFile": ""}, "empty"),
        ({"FrictionModel": "Table", "FrictionTableFile": "/no/such/file.csv"}, "Cannot read"),
        ({"FrictionModel": "Expression", "FrictionExpression": "__import__('os')"}, "not allowed"),
        ({"FrictionModel": "Moody"}, "Unknown"),
    ],
)
def test_network_bad_settings_raise_readable_errors(props, match):
    with pytest.raises(ValueError, match=match):
        _analysis_adapter.network_friction_model(_net(**props))


def _seg_model():
    return SegmentModel(edge_key="e", section=SectionModel(profile="Circular", diameter_mm=200.0), length_mm=1000.0)


def test_segment_without_friction_factory_gets_the_network_model():
    reg = _load_registry()
    base = fr.DarcyWeisbach(fr.COLEBROOK)
    seg = SimpleNamespace(LibraryId="builtin_basic", TypeId="circular_straight")
    assert _analysis_adapter.segment_friction_model(reg, seg, base, _seg_model()) is base
    untyped = SimpleNamespace()
    assert _analysis_adapter.segment_friction_model(reg, untyped, base, _seg_model()) is base


def test_flex_segment_scales_the_network_model_by_fig_14_4():
    reg = _load_registry()
    type_def = reg.resolve_type("builtin_basic", "circular_flex")
    assert type_def.friction_module == "shared:friction"
    base = fr.DarcyWeisbach(fr.COLEBROOK)
    seg = SimpleNamespace(LibraryId="builtin_basic", TypeId="circular_flex", CompressionPercent=10.0)
    model = _analysis_adapter.segment_friction_model(reg, seg, base, _seg_model())
    assert isinstance(model, fr.ScaledFriction)
    assert model.base is base and model.factor == pytest.approx(fr.flex_compression_factor(10.0))


def test_flex_segment_is_manual_only():
    lib = _load_registry().get_library("builtin_basic")
    auto = lib.list_types(category="segment", family="straight_segment", profile="Circular")
    assert "circular_flex" in [t.id for t in auto]  # offered in the manual list
    flex = lib.get_type("circular_flex")
    assert "straight_segment" not in flex.family and "curved_segment" not in flex.family


def test_friction_entry_without_function_is_rejected(tmp_path):
    type_file = tmp_path / "s.json"
    type_file.write_text(
        '{"id": "s", "category": "segment", "family": ["straight_segment"], "profiles": ["Circular"],'
        ' "friction": {"module": "shared:friction"}}',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="friction"):
        HVACLibraryRegistry()._load_type_def_file(str(type_file))
