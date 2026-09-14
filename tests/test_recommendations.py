from src.data.fpl_api import FPLAPI
from src.notifications.whatsapp import format_recommendation
from src.config import Settings


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
        "chips": {"best_chip": None},
    })

    assert "FPL GW 5 plan" in message
    assert "GW 4 unused free transfers: 1" in message
    assert "GW 5 starting free transfers: 2" in message


def test_blank_optional_environment_values_use_defaults(monkeypatch):
    monkeypatch.setenv("CHIP_MINIMUM_GAIN", "")

    assert Settings().chip_minimum_gain == 4