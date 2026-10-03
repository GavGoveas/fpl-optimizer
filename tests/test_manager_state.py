from datetime import datetime, timezone

import pytest

from src.data.fpl_api import FPLAPI
from src.models.manager_state import ManagerStateConflict, TransferLedger, assemble_manager_state
from src.models.rules import FPLRules
from src.optimizer.scoring import ScoringSystem


def _completed_history(transfers_by_event, costs=None, chips=None):
    costs = costs or {}
    return {
        "current": [
            {"event": event, "event_transfers": transfers, "event_transfers_cost": costs.get(event, 0)}
            for event, transfers in enumerate(transfers_by_event, start=1)
        ],
        "chips": chips or [],
    }


def test_completed_gw5_rolls_one_free_transfer_into_gw6():
    history = _completed_history([1, 1, 1, 1, 4], {5: 12})

    ledger = TransferLedger.reconstruct(history, 6, max_free_transfers=5)

    assert ledger.target_gameweek == 6
    assert ledger.free_transfers_at_gameweek_start == 1
    assert ledger.free_transfers_remaining == 1
    assert ledger.transfers_made_this_gameweek == 0


def test_target_gameweek_distinguishes_start_remaining_and_next_transfer():
    history = _completed_history([1, 1, 1, 1, 4], {5: 12})

    ledger = TransferLedger.reconstruct(history, 5, max_free_transfers=5)

    assert ledger.free_transfers_at_gameweek_start == 1
    assert ledger.free_transfers_remaining == 0
    assert ledger.free_transfers_for_next_gameweek == 1
    assert ledger.transfer_hit_cost == 12


def test_wildcard_transfers_do_not_consume_free_transfer_ledger():
    history = _completed_history([0, 0, 0, 0, 0], chips=[{"event": 5, "name": "wildcard"}])

    ledger = TransferLedger.reconstruct(history, 6, max_free_transfers=5)

    assert ledger.free_transfers_at_gameweek_start == 5


def test_ledger_blocks_transfer_cost_conflict():
    history = _completed_history([0, 0, 0, 0, 2], {5: 4})

    with pytest.raises(ManagerStateConflict, match="transfer-cost conflict"):
        TransferLedger.reconstruct(history, 5, max_free_transfers=5)


def test_ledger_blocks_missing_historical_gameweek():
    history = {"current": [{"event": 1, "event_transfers": 0}, {"event": 3, "event_transfers": 0}]}

    with pytest.raises(ManagerStateConflict, match="incomplete"):
        TransferLedger.reconstruct(history, 4, max_free_transfers=5)


def test_ledger_blocks_empty_history_after_opening_gameweek():
    with pytest.raises(ManagerStateConflict, match="history is unavailable"):
        TransferLedger.reconstruct({"current": []}, 2, max_free_transfers=5)


def test_free_transfer_count_respects_active_maximum():
    history = {"current": [{"event": event, "event_transfers": 0} for event in range(1, 9)]}

    ledger = TransferLedger.reconstruct(history, 9, max_free_transfers=3)

    assert ledger.free_transfers_at_gameweek_start == 3
    assert 0 <= ledger.free_transfers_remaining <= 3


def test_next_gameweek_comes_from_deadline_not_previous_flag():
    events = [
        {"id": 5, "finished": True, "is_previous": True, "deadline_time": "2026-09-01T10:00:00Z"},
        {"id": 6, "finished": False, "deadline_time": "2026-10-01T10:00:00Z"},
        {"id": 7, "finished": False, "deadline_time": "2026-10-08T10:00:00Z"},
    ]
    now = datetime(2026, 9, 25, tzinfo=timezone.utc)

    selected = FPLAPI.select_next_gameweek(events, now)

    assert selected["id"] == 6


def test_expired_unfinished_current_event_is_not_selected_over_next_deadline():
    events = [
        {"id": 5, "finished": False, "is_current": True, "deadline_time": "2026-09-20T10:00:00Z"},
        {"id": 6, "finished": False, "deadline_time": "2026-10-10T10:00:00Z"},
    ]
    now = datetime(2026, 10, 3, tzinfo=timezone.utc)

    selected = FPLAPI.select_next_gameweek(events, now)

    assert selected["id"] == 6


def test_versioned_scoring_distinguishes_goal_value_by_position():
    scorer = ScoringSystem(FPLRules(version="test-rules"))
    actions = {"minutes": 90, "goals": 1}

    assert scorer.calculate_points("goalkeeper", actions) == 12
    assert scorer.calculate_points("defender", actions) == 8
    assert scorer.calculate_points("midfielder", actions) == 7
    assert scorer.calculate_points("forward", actions) == 6


def test_fpl_rules_accept_provider_scoring_and_free_transfer_limits():
    rules = FPLRules.from_bootstrap({
        "game_settings": {"season": "dynamic", "max_free_transfers": 3},
        "element_types": [{"singular_name_short": "DEF", "scoring": {"goals_scored": 8}}],
        "scoring_rules": [{"key": "assists", "points": 5}],
    })

    assert rules.version == "FPL-dynamic"
    assert rules.max_free_transfers == 3
    assert rules.source == "official_fpl_api"
    assert rules.score_player("DEF", {"minutes": 90, "goals": 1, "assists": 1}) == 15


def test_live_bootstrap_schema_derives_extra_free_transfer_cap_and_lineup_bounds():
    bootstrap = {
        "game_settings": {"max_extra_free_transfers": 4, "squad_team_limit": 3},
        "scoring_rules": None,
        "element_types": [
            {"singular_name_short": "GKP", "squad_select": 2, "squad_min_play": 1, "squad_max_play": 1},
            {"singular_name_short": "DEF", "squad_select": 5, "squad_min_play": 3, "squad_max_play": 5},
            {"singular_name_short": "MID", "squad_select": 5, "squad_min_play": 2, "squad_max_play": 5},
            {"singular_name_short": "FWD", "squad_select": 3, "squad_min_play": 1, "squad_max_play": 3},
        ],
    }

    rules = FPLRules.from_bootstrap(bootstrap)

    assert rules.max_free_transfers == 5
    assert rules.club_player_limit == 3
    assert rules.squad_quotas == {"GKP": 2, "DEF": 5, "MID": 5, "FWD": 3}
    assert rules.formation_minimums == {"DEF": 3, "MID": 2, "FWD": 1}
    assert rules.scoring_source == "central_default"


def test_season_is_derived_from_authoritative_event_deadlines():
    bootstrap = {
        "events": [
            {"id": 1, "deadline_time": "2026-08-15T10:00:00Z"},
            {"id": 38, "deadline_time": "2027-05-23T10:00:00Z"},
        ],
        "game_settings": {},
    }

    assert FPLRules.from_bootstrap(bootstrap).version.startswith("FPL-2026/2027")


def test_manager_state_blocks_conflicting_or_incomplete_pick_state():
    bootstrap = {
        "events": [{"id": 6, "deadline_time": "2026-10-01T10:00:00Z", "is_next": True}],
        "chips": [],
        "game_settings": {"season": "2026"},
    }
    picks = {"picks": [{"element": index} for index in range(14)], "entry_history": {"event": 6}}

    with pytest.raises(ManagerStateConflict, match="expected 15"):
        assemble_manager_state(
            manager_id=1,
            bootstrap=bootstrap,
            manager={"bank": 0, "value": 1000},
            picks_payload=picks,
            history={"current": []},
            target_gameweek=6,
            display_timezone="Asia/Kolkata",
            source_timestamp=datetime.now(timezone.utc),
            rules=FPLRules.from_bootstrap(bootstrap),
        )


def test_manager_state_assembles_dynamic_deadlines_ledger_prices_and_chips():
    bootstrap = {
        "events": [
            {"id": 5, "deadline_time": "2026-09-20T10:00:00Z", "is_current": True, "finished": True},
            {"id": 6, "deadline_time": "2026-09-27T10:00:00Z", "is_next": True, "finished": False},
        ],
        "chips": [
            {"name": "wildcard", "number": 2, "start_event": 1, "stop_event": 38},
            {"name": "freehit", "number": 1, "start_event": 1, "stop_event": 38},
            {"name": "bboost", "number": 1, "start_event": 1, "stop_event": 38},
            {"name": "3xcaptain", "number": 1, "start_event": 1, "stop_event": 38},
        ],
        "game_settings": {"season": "test-season", "max_free_transfers": 5},
    }
    picks = {
        "picks": [{"element": index, "purchase_price": 50, "selling_price": 51} for index in range(15)],
        "entry_history": {"event": 6, "bank": 0, "value": 1000, "event_transfers": 0},
    }
    history = _completed_history([1, 1, 1, 1, 4], {5: 12}, chips=[{"event": 1, "name": "bboost"}])

    state = assemble_manager_state(
        manager_id=123,
        bootstrap=bootstrap,
        manager={"id": 123, "current_event": 5, "bank": 0, "value": 1000, "name": "private"},
        picks_payload=picks,
        history=history,
        target_gameweek=6,
        display_timezone="Asia/Kolkata",
        source_timestamp=datetime.now(timezone.utc),
        rules=FPLRules.from_bootstrap(bootstrap),
    )

    serialized = state.to_dict()
    assert state.next_gameweek == 6
    assert state.free_transfers_at_gameweek_start == 1
    assert state.free_transfers_remaining == 1
    assert state.free_transfers_for_next_gameweek == 2
    assert state.bank == 0
    assert state.purchase_prices[0] == 5
    assert "WC" in state.chips_available
    assert serialized["next_deadline"].endswith("Z")
