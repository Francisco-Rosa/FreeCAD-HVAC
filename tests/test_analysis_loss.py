"""Unit tests for analysis/loss.py's pure LossPath/LossEvaluation/LossStatus dataclasses."""

from freecad.HVAC.analysis.loss import LossEvaluation, LossPath, LossStatus


def test_loss_path_holds_direction_and_reference():
    path = LossPath(
        from_edge_key="A", to_edge_key="B", reference_edge_key="B",
        loss_coefficient=0.5, source="smacna_elbow",
    )
    assert path.from_edge_key == "A"
    assert path.to_edge_key == "B"
    assert path.reference_edge_key == "B"
    assert path.loss_coefficient == 0.5
    assert path.source == "smacna_elbow"


def test_loss_path_allows_none_on_either_side_for_a_1port_device():
    path = LossPath(from_edge_key=None, to_edge_key="A", reference_edge_key="A", loss_coefficient=0.2)
    assert path.from_edge_key is None
    assert path.to_edge_key == "A"


def test_loss_path_is_frozen():
    path = LossPath(from_edge_key="A", to_edge_key="B", reference_edge_key="B", loss_coefficient=0.5)
    try:
        path.loss_coefficient = 1.0
        assert False, "LossPath should be immutable"
    except AttributeError:
        pass


def test_loss_evaluation_defaults_to_unsupported_and_no_paths():
    evaluation = LossEvaluation()
    assert evaluation.paths == []
    assert evaluation.status == LossStatus.UNSUPPORTED
    assert evaluation.warning is None


def test_loss_evaluation_holds_paths_status_and_warning():
    path = LossPath(from_edge_key="A", to_edge_key="B", reference_edge_key="B", loss_coefficient=0.3)
    evaluation = LossEvaluation(paths=[path], status=LossStatus.EXACT, warning="a warning")
    assert evaluation.paths == [path]
    assert evaluation.status == LossStatus.EXACT
    assert evaluation.warning == "a warning"


def test_loss_status_members_have_expected_string_values():
    assert LossStatus.EXACT.value == "exact"
    assert LossStatus.APPROXIMATION.value == "approximation"
    assert LossStatus.CUSTOM.value == "custom"
    assert LossStatus.FALLBACK.value == "fallback"
    assert LossStatus.UNSUPPORTED.value == "unsupported"
