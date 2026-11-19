"""Stage 9 item 2: per-network layer and feature visibility rules."""

from types import SimpleNamespace

import conftest  # noqa: F401 -- installs FreeCAD/Materials stubs
from freecad.HVAC.core import _component_appearance as appearance
from freecad.HVAC.library.construction import ALL_LAYER_ROLES


def test_everything_shown_without_a_network():
    shown, features = appearance.network_display_flags(None)
    assert shown == set(ALL_LAYER_ROLES) and features is True


def test_flags_follow_the_network_properties():
    net = SimpleNamespace(ShowLayer_ThermalInsulation=False, ShowFeatures=False)
    shown, features = appearance.network_display_flags(net)
    assert "thermal_insulation" not in shown and "structural_shell" in shown
    assert features is False


def test_layer_with_any_shown_role_is_drawn():
    shown = set(ALL_LAYER_ROLES) - {"flow_surface"}
    assert appearance.layer_shown(["flow_surface", "structural_shell"], shown)
    assert not appearance.layer_shown(["flow_surface"], shown)
    assert appearance.layer_shown([], set())  # a roleless layer is always drawn


def test_hidden_parts_and_displayed_parts_leave_out_switched_off_layers(monkeypatch):
    from types import SimpleNamespace

    from freecad.HVAC.core import _component_appearance as appearance_mod

    class Shape:
        def __init__(self, n):
            self.Faces = list(range(n))

        def isNull(self):
            return False

    net = SimpleNamespace(ShowLayer_ThermalInsulation=False, ShowFeatures=True)
    obj = SimpleNamespace(
        ConstructionLayerIds=["casing", "insulation"],
        ConstructionFeatureIds=["flange"],
        Layer_casing_Shape=Shape(4),
        Layer_insulation_Shape=Shape(4),
        Feature_flange_Shape=Shape(2),
    )
    monkeypatch.setattr(appearance_mod.hvaclib, "getOwnerNetwork", lambda o: net)
    monkeypatch.setattr(
        appearance_mod,
        "_layer_roles_by_id",
        lambda o: {"casing": ["flow_surface", "structural_shell"], "insulation": ["thermal_insulation"]},
    )
    monkeypatch.setattr(appearance_mod, "_feature_defs_by_id", lambda o: {})
    assert appearance_mod.hidden_parts(obj) == ({"insulation"}, set())
    parts = appearance_mod.displayed_parts(obj)
    assert [(kind, part_id) for kind, part_id, _shape in parts] == [("layer", "casing"), ("feature", "flange")]
    net.ShowFeatures = False
    assert appearance_mod.hidden_parts(obj) == ({"insulation"}, {"flange"})


def test_hidden_parts_hides_nothing_when_the_network_cannot_be_read(monkeypatch):
    from types import SimpleNamespace

    from freecad.HVAC.core import _component_appearance as appearance_mod

    def broken(_obj):
        raise RuntimeError("no network")

    monkeypatch.setattr(appearance_mod.hvaclib, "getOwnerNetwork", broken)
    assert appearance_mod.hidden_parts(SimpleNamespace(ConstructionLayerIds=["casing"])) == (set(), set())
