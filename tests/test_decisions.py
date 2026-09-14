from src.optimizer.chips import ChipsOptimizer
from src.optimizer.projections import ProjectionEngine


def test_projection_uses_fixture_difficulty_and_injury_status():
    players = [
        {"id": 1, "first_name": "Fit", "second_name": "Player", "team": 1, "ep_next": "6.0", "status": "a"},
        {"id": 2, "first_name": "Injured", "second_name": "Player", "team": 2, "ep_next": "6.0", "status": "i"},
    ]
    fixtures = [{"event": 5, "team_h": 1, "team_h_difficulty": 1, "team_a": 2, "team_a_difficulty": 5}]

    result = ProjectionEngine().project(players, fixtures, gameweek=4)

    assert result[0]["expected_points"] > result[1]["expected_points"]
    assert result[1]["availability"] == 0.0


def test_chip_optimizer_ranks_available_chips():
    players = [{"name": "Captain", "expected_points": 8}]
    bench = [{"name": "Bench one", "expected_points": 3}, {"name": "Bench two", "expected_points": 2}]

    result = ChipsOptimizer(players, bench, free_hit_gain=4, wildcard_gain=6).recommend_chip_usage()

    assert result["best_chip"] == "TC"
    assert result["opportunities"]["BB"]["expected_gain"] == 5