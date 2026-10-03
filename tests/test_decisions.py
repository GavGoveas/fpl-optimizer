from datetime import datetime, timedelta, timezone

from src.optimizer.chips import ChipsOptimizer
from src.optimizer.projections import ProjectionEngine
from src.backtesting import BacktestMetrics
from src.optimizer.simulation import PlayerPointSimulator


def test_projection_uses_fixture_difficulty_and_injury_status():
    players = [
        {"id": 1, "first_name": "Fit", "second_name": "Player", "team": 1, "ep_next": "6.0", "status": "a"},
        {"id": 2, "first_name": "Injured", "second_name": "Player", "team": 2, "ep_next": "6.0", "status": "i"},
    ]
    fixtures = [{"event": 5, "team_h": 1, "team_h_difficulty": 1, "team_a": 2, "team_a_difficulty": 5}]

    result = ProjectionEngine().project(players, fixtures, gameweek=5)

    assert result[0]["expected_points"] > result[1]["expected_points"]
    assert result[1]["availability"] == 0.0
    assert "distribution" in result[0]


def test_projection_consumes_structured_news_status_and_minutes():
    player = {"id": 1, "first_name": "Fit", "second_name": "Player", "team": 1, "ep_next": "6.0", "status": "a"}
    now = datetime.now(timezone.utc)
    news = [{"published_at_utc": now.isoformat(), "gemini_analysis": {"player_names": ["Fit Player"], "status": "doubtful", "availability_probability": 0.5, "minutes_probability": 0.4}}]

    result = ProjectionEngine().project([player], [], gameweek=4, news=news, prediction_time=now)[0]

    assert result["availability"] == 0.5
    assert result["expected_minutes"] == 36.0


def test_projection_ignores_stale_or_untimestamped_news():
    player = {"id": 1, "first_name": "Fit", "second_name": "Player", "team": 1, "ep_next": "6.0", "status": "a"}
    now = datetime.now(timezone.utc)
    news = [
        {"published_at_utc": (now - timedelta(days=10)).isoformat(), "gemini_analysis": {"player_names": ["Fit Player"], "status": "ruled_out"}},
        {"gemini_analysis": {"player_names": ["Fit Player"], "status": "injured"}},
    ]

    result = ProjectionEngine().project([player], [], gameweek=4, news=news, prediction_time=now, news_freshness_hours=48)[0]

    assert result["availability"] == 1.0


def test_projection_exposes_dynamic_captain_evidence():
    player = {"id": 1, "first_name": "Fit", "second_name": "Player", "team": 1, "ep_next": "6.0", "status": "a"}
    result = ProjectionEngine().project([player], [], gameweek=4, fbref_stats={"Fit Player": {"xG": 2, "PK": 1}}, odds=[])[0]

    assert result["attacking_involvement"] > 0
    assert result["set_piece_involvement"] > 0


def test_projection_uses_fbref_and_market_odds():
    player = {"id": 1, "first_name": "Fit", "second_name": "Player", "team": 1, "team_name": "Team A", "ep_next": "6.0", "status": "a"}
    fixtures = [{"event": 5, "team_h": 1, "team_h_difficulty": 3, "team_a": 2, "team_a_difficulty": 3}]
    odds = [{"home_team": "Team A", "away_team": "Team B", "bookmakers": [{"markets": [{"key": "h2h", "outcomes": [{"name": "Team A", "price": 1.5}, {"name": "Team B", "price": 5.0}]}]}]}]

    without_enrichment = ProjectionEngine().project([player], fixtures, gameweek=5)[0]
    with_enrichment = ProjectionEngine().project([player], fixtures, gameweek=5, fbref_stats={"Fit Player": {"xG": 10, "90s": 10}}, odds=odds)[0]

    assert with_enrichment["expected_points"] == without_enrichment["expected_points"]
    assert with_enrichment["expected_goals"] is not None
    assert with_enrichment["fbref_metrics"]["xG"] == 10


def test_chip_optimizer_ranks_available_chips():
    players = [{"name": "Captain", "expected_points": 8}]
    bench = [{"name": "Bench one", "expected_points": 3}, {"name": "Bench two", "expected_points": 2}]

    result = ChipsOptimizer(players, bench, free_hit_gain=4, wildcard_gain=6).recommend_chip_usage()

    assert result["best_chip"] is None
    assert result["decision_available"] is False
    assert result["opportunities"]["BB"]["expected_gain"] == 5


def test_bench_boost_uses_full_dynamic_bench_value():
    result = ChipsOptimizer(
        [{"name": "Captain", "expected_points": 8}],
        [{"name": "Bench one", "expected_points": 8}, {"name": "Bench two", "expected_points": 7}],
        available={"BB"},
    ).recommend_chip_usage()

    assert result["opportunities"]["BB"]["expected_gain"] == 15
    assert result["decision_available"] is False


def test_bench_boost_subtracts_expected_auto_subs():
    starters = [{"position": "GKP", "expected_points": 2, "availability": 1, "minutes_probability": 1}]
    starters += [{"position": "DEF", "expected_points": 4, "availability": 1, "minutes_probability": 1} for _ in range(3)]
    starters += [{"position": "MID", "expected_points": 4, "availability": 1, "minutes_probability": 1} for _ in range(4)]
    starters += [{"position": "FWD", "expected_points": 4, "availability": 1, "minutes_probability": 1} for _ in range(2)]
    starters.append({"position": "FWD", "expected_points": 4, "availability": 1, "minutes_probability": 0.5})
    bench = [
        {"position": "DEF", "expected_points": 5, "availability": 1, "minutes_probability": 1},
        {"position": "MID", "expected_points": 4, "availability": 1, "minutes_probability": 1},
        {"position": "FWD", "expected_points": 3, "availability": 1, "minutes_probability": 1},
        {"position": "GKP", "expected_points": 1, "availability": 1, "minutes_probability": 1},
    ]

    result = ChipsOptimizer(starters, bench, available={"BB"}).recommend_chip_usage()

    assert result["opportunities"]["BB"]["expected_gain"] < sum(player["expected_points"] for player in bench)


def test_chip_is_used_only_when_now_beats_future_scenario():
    player = {"name": "Captain", "position": "MID", "expected_points": 8}
    now_better = ChipsOptimizer(
        [player], available={"TC"}, future_opportunities={"TC": [{"gameweek": 9, "expected_gain": 5}]}
    ).recommend_chip_usage()
    future_better = ChipsOptimizer(
        [player], available={"TC"}, future_opportunities={"TC": [{"gameweek": 9, "expected_gain": 10}]}
    ).recommend_chip_usage()

    assert now_better["use_chip"] == "TC"
    assert future_better["use_chip"] is None


def test_chip_squad_uses_distribution_aware_captain():
    player = {"id": 1, "position": "MID", "expected_points": 7, "distribution": {"mean": 9}}
    assert ChipsOptimizer.captain_score(player) == 8


def test_chip_optimizer_respects_no_available_chips():
    result = ChipsOptimizer([{"name": "Captain", "expected_points": 8}], available=set()).recommend_chip_usage()

    assert result["use_chip"] is None


def test_chip_optimizer_caps_absurd_wildcard_gain():
    players = [{"name": "Captain", "expected_points": 8}]
    optimizer = ChipsOptimizer(players, available={"WC"})
    optimizer.wildcard_squad = {"starting_xi": [{"name": "Wildcard star", "expected_points": 500, "wildcard_expected_points": 500}]}

    result = optimizer.recommend_chip_usage()

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
    assert result["opportunities"]["FH"]["persistence"] == "one_gameweek_then_revert"
    assert result["opportunities"]["WC"]["persistence"] == "permanent"


def test_projection_provides_multi_gameweek_wildcard_value():
    player = {"id": 1, "first_name": "Fit", "second_name": "Player", "team": 1, "ep_next": "6.0", "status": "a", "expected_points_by_event": {"5": 6, "6": 7, "7": 8}}
    fixtures = [
        {"event": 5, "team_h": 1, "team_h_difficulty": 2, "team_a": 2, "team_a_difficulty": 3},
        {"event": 6, "team_h": 1, "team_h_difficulty": 1, "team_a": 3, "team_a_difficulty": 4},
        {"event": 7, "team_h": 4, "team_h_difficulty": 3, "team_a": 1, "team_a_difficulty": 2},
    ]

    result = ProjectionEngine().project([player], fixtures, gameweek=5, wildcard_horizon=3)[0]

    assert result["wildcard_expected_points"] > result["expected_points"]
    assert 0.55 <= result["wildcard_confidence"] <= 1.0


def test_projection_uses_exact_event_and_counts_double_fixtures():
    player = {"id": 1, "first_name": "Double", "second_name": "Player", "team": 1, "ep_next": "8.0", "status": "a"}
    fixtures = [
        {"event": 5, "team_h": 1, "team_h_difficulty": 2, "team_a": 3, "team_a_difficulty": 4},
        {"event": 5, "team_h": 4, "team_h_difficulty": 3, "team_a": 1, "team_a_difficulty": 2},
        {"event": 6, "team_h": 1, "team_h_difficulty": 2, "team_a": 5, "team_a_difficulty": 3},
    ]

    result = ProjectionEngine().project([player], fixtures, gameweek=5, wildcard_horizon=2)[0]

    assert result["fixture_count"] == 2
    assert result["expected_points"] > 0
    assert result["clean_sheet_probability"] is None


def test_projection_does_not_assign_adjacent_event_or_invent_blank_fixture():
    player = {"id": 1, "first_name": "Blank", "second_name": "Player", "team": 1, "ep_next": "8.0", "status": "a", "expected_points_by_event": {"6": 4}}
    fixtures = [{"event": 6, "team_h": 1, "team_h_difficulty": 2, "team_a": 2, "team_a_difficulty": 3}]

    result = ProjectionEngine().project([player], fixtures, gameweek=5, wildcard_horizon=2)[0]

    assert result["fixture_count"] == 0
    assert result["expected_points"] == 0
    assert result["wildcard_expected_points"] == 4


def test_projection_estimates_minutes_from_historical_starts():
    player = {"id": 1, "first_name": "Regular", "second_name": "Starter", "team": 1, "ep_next": "6.0", "minutes": 360, "starts": 4, "status": "a"}

    result = ProjectionEngine().project([player], [], gameweek=4)[0]

    assert result["expected_minutes"] == 90


def test_lineup_selects_best_legal_formation():
    squad = [{"id": "g", "position": "GKP", "expected_points": 4}]
    squad += [{"id": f"d{index}", "position": "DEF", "expected_points": 3 + index} for index in range(5)]
    squad += [{"id": f"m{index}", "position": "MID", "expected_points": 3 + index} for index in range(5)]
    squad += [{"id": f"f{index}", "position": "FWD", "expected_points": 3 + index} for index in range(3)]
    starters, bench = ChipsOptimizer.select_lineup(squad)
    assert len(starters) == 11
    assert len(bench) == 3


def test_squad_optimizer_finds_global_budget_optimum():
    players = []
    player_id = 0
    for position, count in (("GKP", 2), ("DEF", 5), ("MID", 5), ("FWD", 3)):
        for _ in range(count):
            players.append({"id": player_id, "position": position, "team": player_id, "price": 1, "expected_points": 0})
            player_id += 1
    players.extend([
        {"id": 20, "position": "MID", "team": 18, "price": 11, "expected_points": 14},
        {"id": 21, "position": "MID", "team": 19, "price": 6, "expected_points": 13},
        {"id": 22, "position": "MID", "team": 20, "price": 6, "expected_points": 13},
    ])

    squad = ChipsOptimizer.build_best_squad(players, budget=25)

    assert len(squad) == 15
    assert {21, 22}.issubset({player["id"] for player in squad})


def test_backtest_metrics_are_calculated():
    result = BacktestMetrics.evaluate([2, 4, 6], [1, 5, 7])
    assert result["count"] == 3
    assert result["mae"] == 1.0


def test_simulator_does_not_invent_player_events_without_scenarios():
    distribution = PlayerPointSimulator().simulate({"id": 1, "expected_points": 8})
    assert distribution == {"available": False, "source": None, "sample_count": 0}


def test_simulator_summarizes_supplied_reproducible_scenarios():
    distribution = PlayerPointSimulator().simulate({"simulation_samples": [0, 5, 10, 20]})
    assert distribution["available"] is True
    assert distribution["sample_count"] == 4
    assert distribution["mean"] == 8.75
    assert distribution["probability_20_plus"] == 0.25