from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from src.audit import RecommendationAuditStore
from src.data.fpl_api import FPLAPI
from src.data.odds_api import OddsAPI
from src.notifications.whatsapp import format_recommendation
from src.config import Settings
from src.recommendations import RecommendationService, RecommendationValidationError


class _FakeSession:
    def __init__(self, payloads):
        self.payloads = payloads

    def get(self, url, params=None, timeout=20):
        class Response:
            def __init__(self, payload):
                self.payload = payload
            def raise_for_status(self):
                return None
            def json(self):
                return self.payload
        if url.endswith("bootstrap-static/"):
            return Response({"events": [{"id": 1, "is_current": False}, {"id": 5, "is_current": True}], "elements": [], "teams": []})
        if url.endswith("entry/3193985/"):
            return Response({"current_event": 5, "name": "Manager", "last_deadline_bank": 0, "last_deadline_value": 1000})
        if url.endswith("entry/3193985/history/"):
            return Response({"current": [{"event": 1, "event_transfers": 0}, {"event": 2, "event_transfers": 1}, {"event": 3, "event_transfers": 0}, {"event": 4, "event_transfers": 2}]})
        if url.endswith("fixtures/"):
            return Response([
                {"event": 5, "team_h": 1, "team_a": 2, "team_h_difficulty": 3, "team_a_difficulty": 2},
                {"event": 6, "team_h": 3, "team_a": 4, "team_h_difficulty": 4, "team_a_difficulty": 2},
            ])
        raise AssertionError(f"Unexpected call: {url}")


def test_upcoming_free_transfers_reconstructs_banked_transfers():
    history = {
        "current": [
            {"event": 1, "event_transfers": 0},
            {"event": 2, "event_transfers": 0},
            {"event": 3, "event_transfers": 1},
        ]
    }

    assert FPLAPI.upcoming_free_transfers(history) == 3
    assert FPLAPI.remaining_free_transfers(history, 3) == 2


def test_message_labels_the_planned_gameweek():
    message = format_recommendation({
        "gameweek": 5,
        "source_gameweek": 4,
        "current_free_transfers": 1,
        "free_transfers": 2,
        "transfers": {"should_take_hits": False, "transfers": []},
        "starting_xi": [{"name": "Starter"}],
        "bench": [{"name": "Bench"}],
        "chips": {"best_chip": None},
    })

    assert "FPL GW 5 plan" in message
    assert "GW 4 unused free transfers" not in message
    assert "GW 5 free transfers available: 2" in message
    assert "Starting XI: Starter" in message
    assert "Bench order: Bench" in message


def test_message_distinguishes_holding_transfers():
    message = format_recommendation({
        "gameweek": 5,
        "free_transfers": 1,
        "transfers": {"should_take_hits": False, "transfers": []},
        "starting_xi": [],
        "bench": [],
        "chips": {"best_chip": None},
    })

    assert "Transfer strategy: HOLD TRANSFERS; no move is necessary" in message


def test_message_reports_transfer_decision_unavailable_instead_of_hold():
    message = format_recommendation({
        "gameweek": 6,
        "free_transfers": 1,
        "transfers": {
            "decision_available": False,
            "reason": "multi-Gameweek projections are missing",
            "should_take_hits": False,
            "transfers": [],
        },
        "starting_xi": [],
        "bench": [],
        "chips": {
            "use_chip": None,
            "decision_available": False,
            "recommendation": {"reason": "future chip scenarios missing"},
        },
    })

    assert "Transfer decision unavailable" in message
    assert "HOLD TRANSFERS" not in message
    assert "Chip decision unavailable" in message


def test_squad_chip_suppresses_incompatible_hit_list():
    message = format_recommendation({
        "gameweek": 5,
        "source_gameweek": 4,
        "current_free_transfers": 1,
        "free_transfers": 1,
        "transfers": {"should_take_hits": True, "transfers": [{"player_out": {"name": "Out"}, "player_in": {"name": "In"}, "gain": 8}]},
        "captain": {"name": "Old captain"},
        "vice_captain": {"name": "Old vice"},
        "chips": {
            "use_chip": "WC",
            "recommendation": {"reason": "the wildcard squad improves the projection"},
            "opportunities": {"WC": {"squad": {"players": [], "starting_xi": [], "bench": [], "captain": {"name": "New captain"}, "vice_captain": {"name": "New vice"}}}},
        },
    })

    assert "USE WC; do not apply the separate hit list" in message
    assert "Out -> In" not in message
    assert "Captain: New captain" in message


def test_transfer_plan_is_applied_before_lineup_selection():
    squad = [
        {"id": 1, "name": "Out", "position": "MID", "expected_points": 2},
        {"id": 2, "name": "Keep", "position": "MID", "expected_points": 6},
    ]
    transfers = [{"player_out": squad[0], "player_in": {"id": 3, "name": "In", "position": "MID", "expected_points": 8}}]

    updated = RecommendationService._apply_transfers(squad, transfers)

    assert [player["name"] for player in updated] == ["In", "Keep"]


def test_captain_score_uses_distribution_when_available():
    player = {"expected_points": 7, "distribution": {"mean": 9}}

    assert RecommendationService._captain_score(player) == 9


def test_message_includes_captain_candidates():
    message = format_recommendation({
        "gameweek": 5,
        "free_transfers": 1,
        "transfers": {"should_take_hits": False, "transfers": []},
        "starting_xi": [],
        "bench": [],
        "captain": {"name": "Saka"},
        "vice_captain": {"name": "Palmer"},
        "captain_candidates": [{"name": "Saka", "captain_score": 8.4}],
        "chips": {"best_chip": None},
    })
    assert "Captain candidates: Saka (8.4)" in message


def test_validation_rejects_inconsistent_transfer_lineup():
    starter = [{"id": 1, "name": "Out", "position": "MID"}]
    recommendation = {
        "starting_xi": starter,
        "bench": [],
        "captain": starter[0],
        "vice_captain": starter[0],
        "transfers": {"transfers": [{"player_out": {"id": 1, "name": "Out"}, "player_in": {"id": 2, "name": "In"}}]},
        "chips": {"use_chip": None},
    }

    result = RecommendationService.validate_recommendation(recommendation, [{"event": 5}], {"events": []})

    assert result["valid"] is False
    assert any("lineup" in error for error in result["errors"])


def test_validation_accepts_available_bench_boost_players():
    starting = ([{"id": 0, "position": "GKP", "availability": 1.0}]
                + [{"id": index, "position": "DEF", "availability": 1.0} for index in range(1, 5)]
                + [{"id": index, "position": "MID", "availability": 1.0} for index in range(5, 9)]
                + [{"id": index, "position": "FWD", "availability": 1.0} for index in range(9, 11)])
    bench = [
        {"id": 11, "position": "GKP", "availability": 1.0, "minutes_probability": 0.8},
        {"id": 12, "position": "MID", "availability": 1.0, "minutes_probability": 0.8},
        {"id": 13, "position": "FWD", "availability": 1.0, "minutes_probability": 0.8},
        {"id": 14, "position": "DEF", "availability": 1.0, "minutes_probability": 0.8},
    ]
    for player in starting + bench:
        player["distribution"] = {"available": True, "mean": 5.0, "sample_count": 1000}
    captain = starting[5]
    recommendation = {
        "starting_xi": starting,
        "bench": bench,
        "captain": captain,
        "vice_captain": starting[6],
        "transfers": {"transfers": [], "decision_available": True},
        "chips": {"use_chip": "BB", "decision_available": True},
        "captain_decision_available": True,
        "scoring_rules_source": "official_fpl_api",
    }

    result = RecommendationService.validate_recommendation(recommendation, [{"event": 5}], {"events": []})

    assert result["valid"] is True


def test_offline_end_to_end_build_validates_and_persists_run(tmp_path):
    event = {
        "id": 1,
        "deadline_time": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat().replace("+00:00", "Z"),
        "is_next": True,
        "finished": False,
    }
    positions = [(1, 2), (2, 5), (3, 5), (4, 3)]
    elements = []
    picks = []
    element_id = 1
    for position_id, count in positions:
        for index in range(count):
            elements.append({
                "id": element_id,
                "first_name": f"First{element_id}",
                "second_name": f"Player{element_id}",
                "team": element_id,
                "element_type": position_id,
                "now_cost": 50,
                "ep_next": str(3 + index + position_id),
                "status": "a",
                "chance_of_playing_next_round": 100,
                "minutes": 900,
                "starts": 10,
            })
            picks.append({"element": element_id, "purchase_price": 50, "selling_price": 50})
            element_id += 1
    bootstrap = {
        "events": [event],
        "teams": [{"id": team, "name": f"Team {team}"} for team in range(1, 21)],
        "elements": elements,
        "element_types": [],
        "chips": [{"name": name, "number": 1, "start_event": 1, "stop_event": 38} for name in ("wildcard", "freehit", "bboost", "3xcaptain")],
        "game_settings": {"season": "end-to-end-test", "max_free_transfers": 5},
    }
    fixtures = [{"event": 1, "team_h": team, "team_a": 20, "team_h_difficulty": 3, "team_a_difficulty": 3} for team in range(1, 16)]

    class FakeFPL:
        last_retrieved_at = datetime.now(timezone.utc)

        @staticmethod
        def select_next_gameweek(events):
            return events[0]

        @staticmethod
        def get_bootstrap():
            return bootstrap

        @staticmethod
        def get_manager(manager_id):
            return {"id": manager_id, "name": "Test", "bank": 0, "value": 1000, "current_event": None}

        @staticmethod
        def get_manager_history(manager_id):
            return {"current": [], "chips": []}

        @staticmethod
        def get_manager_picks(manager_id, gameweek):
            return {"picks": picks, "entry_history": {"event": gameweek, "bank": 0, "value": 1000, "event_transfers": 0}}

        @staticmethod
        def get_current_gameweek_fixtures(gameweek):
            return fixtures

    class FakeNews:
        @staticmethod
        def fetch_news():
            return []

        @staticmethod
        def summarize_with_gemini(items, model):
            return items

    class OfflineService(RecommendationService):
        def _fetch_enrichment(self, gameweek=None):
            return {"fbref": {}, "odds": [], "available_sources": [], "errors": {}}

    service = OfflineService(fpl=FakeFPL(), news=FakeNews(), audit_store=RecommendationAuditStore(tmp_path))

    try:
        service.build(manager_id=321)
    except RecommendationValidationError as error:
        artifact_path = Path(error.artifact_path)
        artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
        assert artifact["run_id"] == error.run_id
        assert any("distributions" in item for item in error.errors)
        assert any("event-indexed" in item for item in error.errors)
        assert artifact_path.exists()
    else:
        raise AssertionError("a run without outcome distributions and future forecasts must not emit advice")


def test_blank_optional_environment_values_use_defaults(monkeypatch):
    monkeypatch.setenv("GEMINI_MODEL", "")

    assert Settings().gemini_model == "gemini-2.0-flash"