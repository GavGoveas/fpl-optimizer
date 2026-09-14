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


def test_projection_uses_fbref_and_market_odds():
    player = {"id": 1, "first_name": "Fit", "second_name": "Player", "team": 1, "team_name": "Team A", "ep_next": "6.0", "status": "a"}
    fixtures = [{"event": 5, "team_h": 1, "team_h_difficulty": 3, "team_a": 2, "team_a_difficulty": 3}]
    odds = [{"home_team": "Team A", "away_team": "Team B", "bookmakers": [{"markets": [{"key": "h2h", "outcomes": [{"name": "Team A", "price": 1.5}, {"name": "Team B", "price": 5.0}]}]}]}]

    without_enrichment = ProjectionEngine().project([player], fixtures, gameweek=4)[0]["expected_points"]
    with_enrichment = ProjectionEngine().project([player], fixtures, gameweek=4, fbref_stats={"Fit Player": {"xG": 10}}, odds=odds)[0]["expected_points"]

    assert with_enrichment > without_enrichment


def test_chip_optimizer_ranks_available_chips():
    players = [{"name": "Captain", "expected_points": 8}]
    bench = [{"name": "Bench one", "expected_points": 3}, {"name": "Bench two", "expected_points": 2}]

    result = ChipsOptimizer(players, bench, free_hit_gain=4, wildcard_gain=6).recommend_chip_usage()

    assert result["best_chip"] == "TC"
    assert result["opportunities"]["BB"]["expected_gain"] == 5


def test_chip_optimizer_respects_no_available_chips():
    result = ChipsOptimizer([{"name": "Captain", "expected_points": 8}], available=set()).recommend_chip_usage()

    assert result["use_chip"] is None


def test_squad_chips_include_full_legal_squad_and_lineup():
    players = []
    team_id = 0
    for position, count in (("GKP", 2), ("DEF", 5), ("MID", 5), ("FWD", 3)):
        for index in range(count):
            players.append({"id": f"{position}{index}", "name": f"{position} {index}", "position": position, "team": team_id, "price": 5, "expected_points": 5 + index})
            team_id += 1

    result = ChipsOptimizer(players[:11], players[11:], free_hit_gain=5, wildcard_gain=5, all_players=players, budget=100).recommend_chip_usage()

    squad = result["opportunities"]["FH"]["squad"]
    assert len(squad["players"]) == 15
    assert len(squad["starting_xi"]) == 11
    assert len(squad["bench"]) == 4