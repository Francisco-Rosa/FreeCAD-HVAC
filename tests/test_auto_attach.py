"""Pure tests for core/_auto_attach.py: which open duct ends sit on equipment / custom fitting ports."""

from freecad.HVAC.core import _auto_attach as aa


def _spot(owner, kind, marker, position):
    return aa.PortSpot(owner, kind, marker, position)


def test_open_ends_on_ports_are_matched_within_the_tolerance():
    spots = [
        _spot("Tee", aa.KIND_FITTING, "P1", (0.0, 0.0, 0.0)),
        _spot("Tee", aa.KIND_FITTING, "P2", (500.0, 0.0, 0.0)),
        _spot("AHU", aa.KIND_EQUIPMENT, "Supply", (0.0, 1000.0, 0.0)),
    ]
    ends = {1: (0.4, 0.0, 0.0), 2: (500.0, 0.0, 0.9), 3: (0.0, 1000.0, 0.0), 4: (0.0, 1002.0, 0.0)}
    matches = aa.match_open_ends(ends, spots)
    assert [(node, spot.marker) for node, spot in matches] == [(1, "P1"), (2, "P2"), (3, "Supply")]


def test_each_port_and_each_end_is_used_once_closest_first():
    spots = [_spot("Tee", aa.KIND_FITTING, "P1", (0.0, 0.0, 0.0))]
    ends = {7: (0.8, 0.0, 0.0), 5: (0.1, 0.0, 0.0)}
    assert [(node, spot.marker) for node, spot in aa.match_open_ends(ends, spots)] == [(5, "P1")]


def test_fitting_groups_and_equipment_matches_are_split_by_kind():
    matches = [
        (4, _spot("Tee", aa.KIND_FITTING, "P2", (1.0, 0.0, 0.0))),
        (2, _spot("Tee", aa.KIND_FITTING, "P1", (0.0, 0.0, 0.0))),
        (3, _spot("Elbow", aa.KIND_FITTING, "P1", (9.0, 0.0, 0.0))),
        (9, _spot("AHU", aa.KIND_EQUIPMENT, "Supply", (5.0, 0.0, 0.0))),
    ]
    assert aa.fitting_groups(matches) == {"Tee": [2, 4], "Elbow": [3]}
    assert [(node, spot.owner) for node, spot in aa.equipment_matches(matches)] == [(9, "AHU")]


def test_live_connections_drops_only_this_networks_vanished_nodes():
    entries = ["Port1|Supply|e1_s", "Port2|Supply|e9_e", "Port3|Return|e9_e", "malformed"]
    assert aa.live_connections(entries, "Supply", {"e1_s"}) == ["Port1|Supply|e1_s", "Port3|Return|e9_e"]
    assert aa.parse_connection("a|b|c") == {"port": "a", "network": "b", "node_key": "c"}
    assert aa.parse_connection("a|b") is None
