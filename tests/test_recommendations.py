from src.data.fpl_api import FPLAPI
from src.data.odds_api import OddsAPI
from src.notifications.whatsapp import format_recommendation
from src.config import Settings
from src.recommendations import RecommendationService


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

    assert RecommendationService._captain_score(player) == 8


def test_blank_optional_environment_values_use_defaults(monkeypatch):
    monkeypatch.setenv("CHIP_MINIMUM_GAIN", "")

    assert Settings().chip_minimum_gain == 4