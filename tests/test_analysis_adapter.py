"""Focused tests for construction-derived analysis inputs and diagnostic labels."""

import json
from types import SimpleNamespace

import pytest

import conftest  # noqa: F401 -- installs FreeCAD/Materials stubs
from freecad.HVAC.analysis.loss import LossStatus
from freecad.HVAC.core import _analysis_adapter


def _paths_by_edge(evaluation):
    return {p.reference_edge_key: p.loss_coefficient for p in evaluation.paths}


def _path_for(evaluation, edge_key):
    return next(p for p in evaluation.paths if p.reference_edge_key == edge_key)


def test_humanize_diagnostics_prefers_number_then_label():
    segments = {
        "edge:internal": SimpleNamespace(Number="D012", Label="Supply duct", Name="Segment001"),
    }
    junctions = {
        "node:internal": SimpleNamespace(Number="", Label="Main tee", Name="Junction001"),
    }

    messages = _analysis_adapter.humanize_diagnostics(
        ["Segment 'edge:internal' meets node 'node:internal'."], segments, junctions
    )

    assert messages == ["Segment 'D012' meets node 'Main tee'."]
    assert "internal" not in messages[0]


def test_network_element_index_reaches_each_object_by_number_label_and_name():
    seg = SimpleNamespace(Number="S-1", Label="Duct 1", Name="DuctSegment001")
    other = SimpleNamespace(Number="", Label="S-1", Name="DuctSegment002")
    index = _analysis_adapter.network_element_index([seg, None, other])
    assert index["S-1"] is seg  # the first object to claim an identifier keeps it
    assert index["Duct 1"] is seg
    assert index["DuctSegment001"] is seg
    assert index["DuctSegment002"] is other


def test_link_spans_links_whole_identifiers_and_keeps_the_text():
    s1 = SimpleNamespace(Number="S-1", Label="", Name="a")
    s12 = SimpleNamespace(Number="S-12", Label="", Name="b")
    index = {"S-1": s1, "S-12": s12}
    text = "Duct 'S-12' is wider than S-1; S-1x and S-1.5 are not names."
    spans = _analysis_adapter.link_spans(text, index)
    assert "".join(piece for piece, _ in spans) == text
    assert [(piece, obj) for piece, obj in spans if obj is not None] == [("S-12", s12), ("S-1", s1)]


def test_link_spans_without_identifiers_returns_the_whole_text():
    assert _analysis_adapter.link_spans("nothing here", {}) == [("nothing here", None)]


def test_element_identifier_falls_back_to_internal_name():
    obj = SimpleNamespace(Number="", Label="", Name="Segment001")
    assert _analysis_adapter.element_identifier(obj) == "Segment001"


def test_segment_model_uses_construction_roughness_and_ignores_legacy_override(monkeypatch):
    segment = SimpleNamespace(
        Profile="Circular", Diameter=200.0, Roughness=9.9,
        SegmentKey="edge", Name="Segment001", EffectiveLength=1000.0,
        Velocity=0.0, RectangularSizingMode="UseNetworkDefault",
        TargetAspectRatio=0.0,
    )
    construction = SimpleNamespace(hydraulic_roughness=lambda default: 0.15)
    monkeypatch.setattr(_analysis_adapter, "construction_for", lambda obj: construction)

    model = _analysis_adapter._build_segment_model(segment, default_roughness_mm=0.09)

    assert model.roughness_mm == 0.15


def test_segment_model_uses_network_roughness_only_as_construction_fallback(monkeypatch):
    segment = SimpleNamespace(
        Profile="Circular", Diameter=200.0, Roughness=9.9,
        SegmentKey="edge", Name="Segment001", EffectiveLength=1000.0,
        Velocity=0.0, RectangularSizingMode="UseNetworkDefault",
        TargetAspectRatio=0.0,
    )
    construction = SimpleNamespace(hydraulic_roughness=lambda default: default)
    monkeypatch.setattr(_analysis_adapter, "construction_for", lambda obj: construction)

    model = _analysis_adapter._build_segment_model(segment, default_roughness_mm=0.09)

    assert model.roughness_mm == 0.09


def test_component_models_use_their_own_construction_roughness(monkeypatch):
    primary = SimpleNamespace(Name="Primary", LocalPortsJson="[]", LibraryId="", TypeId="")
    inline = SimpleNamespace(Name="Inline", LocalPortsJson="[]", LibraryId="", TypeId="")
    fallback = SimpleNamespace(Name="Fallback", LocalPortsJson="[]", LibraryId="", TypeId="")
    junction = SimpleNamespace(
        DesignFlowRate=0.0,
        Family="through",
        Proxy=SimpleNamespace(
            getPrimaryComponent=lambda: primary,
            getPortChains=lambda: {"edge": [inline, fallback]},
        ),
    )
    analysis = SimpleNamespace(
        connected_ports=[], topology="through", degree=2,
        flow_class="unknown", qualifiers={}, derived_values={},
    )
    registry = SimpleNamespace(resolve_type=lambda library_id, type_id: None)

    roughness = {"Primary": 0.12, "Inline": 0.24}
    monkeypatch.setattr(
        _analysis_adapter,
        "construction_for",
        lambda obj: SimpleNamespace(
            hydraulic_roughness=lambda default: roughness.get(obj.Name, default)
        ),
    )

    model = _analysis_adapter._build_node_model(
        "node", junction, analysis, {}, registry,
        SimpleNamespace(), {}, default_roughness_mm=0.09,
    )

    assert model.primary_component.roughness_mm == 0.12
    assert model.inline_chains["edge"][0].roughness_mm == 0.24
    assert model.inline_chains["edge"][1].roughness_mm == 0.09


def test_node_model_reads_flow_boundary_off_the_junction(monkeypatch):
    """
    NodeModel.flow_boundary must mirror DuctJunction.FlowBoundary exactly
    (defaulting to "Auto" if the property is missing, e.g. a non-terminal
    node or an older test double) -- see analysis/flow.py for how this
    tri-state replaces the old "DesignFlowRate == 0 means unset" heuristic.
    """
    monkeypatch.setattr(
        _analysis_adapter, "construction_for", lambda obj: SimpleNamespace(hydraulic_roughness=lambda default: default)
    )
    analysis = SimpleNamespace(
        connected_ports=[], topology="end", degree=1,
        flow_class="unknown", qualifiers={}, derived_values={},
    )
    registry = SimpleNamespace(resolve_type=lambda library_id, type_id: None)

    closed_junction = SimpleNamespace(DesignFlowRate=999.0, FlowBoundary="Closed", Family="", Proxy=SimpleNamespace(
        getPrimaryComponent=lambda: None, getPortChains=lambda: {},
    ))
    model = _analysis_adapter._build_node_model(
        "node", closed_junction, analysis, {}, registry, SimpleNamespace(), {}, default_roughness_mm=0.09,
    )
    assert model.flow_boundary == "Closed"
    assert model.design_flow_lps == 999.0  # preserved on the model -- flow.py is what ignores it for Closed

    no_boundary_junction = SimpleNamespace(DesignFlowRate=0.0, Family="", Proxy=SimpleNamespace(
        getPrimaryComponent=lambda: None, getPortChains=lambda: {},
    ))
    model = _analysis_adapter._build_node_model(
        "node", no_boundary_junction, analysis, {}, registry, SimpleNamespace(), {}, default_roughness_mm=0.09,
    )
    assert model.flow_boundary == "Auto"


def test_loss_evaluator_exposes_component_construction_and_roughness():
    captured = {}
    type_def = SimpleNamespace(properties=[])

    class Registry:
        @staticmethod
        def resolve_type(library_id, type_id):
            return type_def

        @staticmethod
        def call_loss(library_id, resolved_type, context):
            captured.update(context)
            return 0.3

    component = SimpleNamespace(
        LibraryId="smacna", TypeId="through_elbow_rectangular", LocalPortsJson="[]"
    )
    air = SimpleNamespace(density_kg_m3=1.204, kinematic_viscosity_m2_s=1.51e-5)
    construction = object()
    evaluator = _analysis_adapter.build_loss_evaluator(
        Registry(), component, air,
        construction=construction,
        hydraulic_roughness_mm=0.12,
    )

    assert evaluator({}) == 0.3
    assert captured["construction"] is construction
    assert captured["hydraulic_roughness_mm"] == 0.12


# ----------------------------------------------------------------------
# LossCoefficientSource == "Custom": per-port K bypasses the library's own
# loss formula entirely -- see Component.py's CustomLossCoefficients and
# _analysis_adapter._build_custom_loss_evaluator().
# ----------------------------------------------------------------------

def _port(edge_key, flow_into_junction):
    return {"edge_key": edge_key, "flow_into_junction": flow_into_junction, "position": [0.0, 0.0, 0.0]}


class _UncalledRegistry:
    """A registry whose call_loss must never be reached in Custom mode."""

    @staticmethod
    def resolve_type(library_id, type_id):
        raise AssertionError("resolve_type must not be called for LossCoefficientSource='Custom'")

    @staticmethod
    def call_loss(library_id, type_def, context):
        raise AssertionError("call_loss must not be called for LossCoefficientSource='Custom'")


def test_custom_loss_evaluator_two_port_component():
    """A 2-port inline device: only the outlet port's own K is stored/returned, keyed by its edge_key."""
    component = SimpleNamespace(
        Name="Comp1", LossCoefficientSource="Custom",
        LocalPortsJson=json.dumps([_port("A", True), _port("B", False)]),
        CustomLossCoefficientEdgeKeys=["B"], CustomLossCoefficients=[0.42],
    )
    evaluator = _analysis_adapter.build_loss_evaluator(_UncalledRegistry(), component, air=SimpleNamespace())

    result = evaluator({})
    assert result.status == LossStatus.CUSTOM
    assert _paths_by_edge(result) == {"B": 0.42}
    path = _path_for(result, "B")
    assert path.from_edge_key == "A"
    assert path.to_edge_key == "B"


def test_custom_loss_evaluator_diverging_tee_uses_outlet_legs():
    """A 3-port diverging tee (run inlet, run outlet, branch outlet): both outlets get their own distinct K."""
    component = SimpleNamespace(
        Name="Tee1", LossCoefficientSource="Custom",
        LocalPortsJson=json.dumps([_port("run_in", True), _port("run_out", False), _port("branch", False)]),
        CustomLossCoefficientEdgeKeys=["run_out", "branch"], CustomLossCoefficients=[0.18, 1.05],
    )
    evaluator = _analysis_adapter.build_loss_evaluator(_UncalledRegistry(), component, air=SimpleNamespace())

    result = evaluator({})
    assert result.status == LossStatus.CUSTOM
    assert _paths_by_edge(result) == {"run_out": 0.18, "branch": 1.05}
    for edge_key in ("run_out", "branch"):
        path = _path_for(result, edge_key)
        assert path.from_edge_key == "run_in"
        assert path.to_edge_key == edge_key


def test_custom_loss_evaluator_converging_tee_uses_inlet_legs():
    """
    A 3-port converging tee (two inlets merging into one outlet): the old
    outlet-only convention couldn't represent this fitting's custom K at
    all (both physically distinct coefficients belong to the INLET legs).
    custom_loss_applicable_ports now returns the two inlets instead of the
    single outlet, so both get their own LossPath into the common outlet.
    """
    component = SimpleNamespace(
        Name="Tee1", LossCoefficientSource="Custom",
        LocalPortsJson=json.dumps([_port("branch_in", True), _port("run_in", True), _port("run_out", False)]),
        CustomLossCoefficientEdgeKeys=["branch_in", "run_in"], CustomLossCoefficients=[1.05, 0.18],
    )
    evaluator = _analysis_adapter.build_loss_evaluator(_UncalledRegistry(), component, air=SimpleNamespace())

    result = evaluator({})
    assert result.status == LossStatus.CUSTOM
    assert _paths_by_edge(result) == {"branch_in": 1.05, "run_in": 0.18}
    for edge_key in ("branch_in", "run_in"):
        path = _path_for(result, edge_key)
        assert path.from_edge_key == edge_key
        assert path.to_edge_key == "run_out"


def test_custom_loss_evaluator_applies_single_port_k_unconditionally():
    """
    A degree-1 terminal (e.g. a diffuser) has only one real duct connection
    to reference a loss against, so its one K must always apply -- whatever
    its own flow_into_junction happens to be -- matching loss_api.py's own
    terminal_component_loss, which never filters its single port either.
    """
    inlet_terminal = SimpleNamespace(
        Name="Terminal1", LossCoefficientSource="Custom",
        LocalPortsJson=json.dumps([_port("A", True)]),
        CustomLossCoefficientEdgeKeys=["A"], CustomLossCoefficients=[0.6],
    )
    evaluator = _analysis_adapter.build_loss_evaluator(_UncalledRegistry(), inlet_terminal, air=SimpleNamespace())
    result = evaluator({})
    assert result.status == LossStatus.CUSTOM
    assert _paths_by_edge(result) == {"A": 0.6}
    assert _path_for(result, "A").from_edge_key == "A"
    assert _path_for(result, "A").to_edge_key is None

    outlet_terminal = SimpleNamespace(
        Name="Terminal2", LossCoefficientSource="Custom",
        LocalPortsJson=json.dumps([_port("A", False)]),
        CustomLossCoefficientEdgeKeys=["A"], CustomLossCoefficients=[0.6],
    )
    evaluator = _analysis_adapter.build_loss_evaluator(_UncalledRegistry(), outlet_terminal, air=SimpleNamespace())
    result = evaluator({})
    assert result.status == LossStatus.CUSTOM
    assert _paths_by_edge(result) == {"A": 0.6}
    assert _path_for(result, "A").from_edge_key is None
    assert _path_for(result, "A").to_edge_key == "A"


def test_loss_evaluator_switches_between_library_and_custom():
    """Flipping LossCoefficientSource must switch the evaluation path, not blend the two."""
    type_def = SimpleNamespace(properties=[])
    registry = SimpleNamespace(
        resolve_type=lambda library_id, type_id: type_def,
        call_loss=lambda library_id, resolved_type, context: 0.75,
    )
    air = SimpleNamespace(density_kg_m3=1.204, kinematic_viscosity_m2_s=1.51e-5)
    component = SimpleNamespace(
        Name="Comp1", LibraryId="smacna", TypeId="through_damper_generic",
        LossCoefficientSource="Library",
        LocalPortsJson=json.dumps([_port("A", True), _port("B", False)]),
        CustomLossCoefficientEdgeKeys=["B"], CustomLossCoefficients=[0.5],
    )

    library_evaluator = _analysis_adapter.build_loss_evaluator(registry, component, air)
    assert library_evaluator({}) == 0.75

    component.LossCoefficientSource = "Custom"
    custom_evaluator = _analysis_adapter.build_loss_evaluator(_UncalledRegistry(), component, air)
    result = custom_evaluator({})
    assert result.status == LossStatus.CUSTOM
    assert _paths_by_edge(result) == {"B": 0.5}

    component.LossCoefficientSource = "Library"
    library_evaluator_again = _analysis_adapter.build_loss_evaluator(registry, component, air)
    assert library_evaluator_again({}) == 0.75


def test_custom_loss_evaluator_accepts_zero_as_valid_explicit_k():
    component = SimpleNamespace(
        Name="Comp1", LossCoefficientSource="Custom",
        LocalPortsJson=json.dumps([_port("A", True), _port("B", False)]),
        CustomLossCoefficientEdgeKeys=["B"], CustomLossCoefficients=[0.0],
    )
    evaluator = _analysis_adapter.build_loss_evaluator(_UncalledRegistry(), component, air=SimpleNamespace())

    result = evaluator({})
    assert result.status == LossStatus.CUSTOM
    assert _paths_by_edge(result) == {"B": 0.0}


def test_custom_loss_evaluator_rejects_negative_k():
    component = SimpleNamespace(
        Name="Comp1", LossCoefficientSource="Custom",
        LocalPortsJson=json.dumps([_port("A", True), _port("B", False)]),
        CustomLossCoefficientEdgeKeys=["B"], CustomLossCoefficients=[-0.1],
    )
    with pytest.raises(ValueError):
        _analysis_adapter.build_loss_evaluator(_UncalledRegistry(), component, air=SimpleNamespace())


def test_custom_loss_evaluator_rejects_non_finite_k():
    component = SimpleNamespace(
        Name="Comp1", LossCoefficientSource="Custom",
        LocalPortsJson=json.dumps([_port("A", True), _port("B", False)]),
        CustomLossCoefficientEdgeKeys=["B"], CustomLossCoefficients=[float("inf")],
    )
    with pytest.raises(ValueError):
        _analysis_adapter.build_loss_evaluator(_UncalledRegistry(), component, air=SimpleNamespace())


def test_custom_loss_evaluator_rejects_mismatched_edge_key_and_value_list_lengths():
    component = SimpleNamespace(
        Name="Comp1", LossCoefficientSource="Custom",
        LocalPortsJson=json.dumps([_port("run_in", True), _port("run_out", False), _port("branch", False)]),
        CustomLossCoefficientEdgeKeys=["run_out", "branch"], CustomLossCoefficients=[0.5],  # only 1 value for 2 keys
    )
    with pytest.raises(ValueError):
        _analysis_adapter.build_loss_evaluator(_UncalledRegistry(), component, air=SimpleNamespace())


def test_custom_loss_evaluator_rejects_stale_edge_keys_out_of_sync_with_current_ports():
    """
    LocalPortsJson now has a new outlet (branch) CustomLossCoefficientEdgeKeys
    was never resynced for -- must fail clearly rather than silently using
    the stale mapping (e.g. dropping branch's own K entirely).
    """
    component = SimpleNamespace(
        Name="Comp1", LossCoefficientSource="Custom",
        LocalPortsJson=json.dumps([_port("run_in", True), _port("run_out", False), _port("branch", False)]),
        CustomLossCoefficientEdgeKeys=["run_out"], CustomLossCoefficients=[0.18],  # missing "branch"
    )
    with pytest.raises(ValueError):
        _analysis_adapter.build_loss_evaluator(_UncalledRegistry(), component, air=SimpleNamespace())


def test_custom_loss_evaluator_rejects_port_missing_edge_key():
    component = SimpleNamespace(
        Name="Comp1", LossCoefficientSource="Custom",
        LocalPortsJson=json.dumps([_port("A", True), {"flow_into_junction": False, "position": [0.0, 0.0, 0.0]}]),
        CustomLossCoefficientEdgeKeys=[""], CustomLossCoefficients=[0.5],
    )
    with pytest.raises(ValueError):
        _analysis_adapter.build_loss_evaluator(_UncalledRegistry(), component, air=SimpleNamespace())


def test_library_loss_behaviour_unchanged_when_source_is_library():
    """Default/explicit 'Library' source must still call reg.call_loss exactly as before this feature."""
    captured = {}
    type_def = SimpleNamespace(properties=[])

    class Registry:
        @staticmethod
        def resolve_type(library_id, type_id):
            return type_def

        @staticmethod
        def call_loss(library_id, resolved_type, context):
            captured.update(context)
            return 0.3

    component = SimpleNamespace(
        LibraryId="smacna", TypeId="through_elbow_rectangular", LocalPortsJson="[]",
        LossCoefficientSource="Library",
    )
    air = SimpleNamespace(density_kg_m3=1.204, kinematic_viscosity_m2_s=1.51e-5)
    evaluator = _analysis_adapter.build_loss_evaluator(Registry(), component, air)

    assert evaluator({}) == 0.3
    assert captured["library_id"] == "smacna"


def test_custom_fitting_loss_sees_the_custom_port_sizes():
    # ROADMAP 6.3: the loss reads the custom fitting's own openings, not the ducts'.
    ports = [
        {"edge_key": "a", "profile": "Circular", "section_params": {"Diameter": 200.0}},
        {"edge_key": "b", "profile": "Circular", "section_params": {"Diameter": 200.0}},
    ]
    comp = SimpleNamespace(
        GeometrySource="Custom",
        CustomPortMapJson=json.dumps(
            {"b": {"port": "P2", "profile": "Rectangular", "section_params": {"Width": 300.0, "Height": 150.0}}}
        ),
    )
    out = _analysis_adapter.custom_port_sections(comp, ports)
    assert out[0] == ports[0]
    assert out[1]["profile"] == "Rectangular" and out[1]["section_params"] == {"Width": 300.0, "Height": 150.0}
    assert ports[1]["profile"] == "Circular"  # the input is not modified
    library = SimpleNamespace(GeometrySource="Library", CustomPortMapJson=comp.CustomPortMapJson)
    assert _analysis_adapter.custom_port_sections(library, ports) is ports
    broken = SimpleNamespace(GeometrySource="Custom", CustomPortMapJson="{not json")
    assert _analysis_adapter.custom_port_sections(broken, ports) is ports
