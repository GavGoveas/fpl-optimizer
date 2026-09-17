from src.config import settings
from src.data.fbref import FBRef
from src.data.fpl_api import FPLAPI
from src.data.news import News
from src.data.odds_api import OddsAPI
from src.data.soccerdata import SoccerData
from src.optimizer.chips import ChipsOptimizer
from src.optimizer.projections import ProjectionEngine
from src.optimizer.transfers import TransferOptimizer


class RecommendationService:
    """Assemble live FPL state and optional enrichment into one recommendation."""

    POSITIONS = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}

    def __init__(self, fpl=None, news=None, projection_engine=None, fbref=None, soccerdata=None, odds=None):
        self.fpl = fpl or FPLAPI()
        self.news = news or News(settings.rss_urls, settings.gemini_api_key)
        self.projection_engine = projection_engine or ProjectionEngine()
        self.fbref = fbref or FBRef()
        self.soccerdata = soccerdata or SoccerData(settings.soccerdata_api_key, settings.soccerdata_url)
        self.odds = odds or OddsAPI(settings.odds_api_key, settings.odds_api_url)

    def build(self, manager_id=None, gameweek=None, news_items=None):
        manager_id = manager_id or settings.manager_id
        if manager_id is None:
            raise ValueError("FPL_MANAGER_ID must be configured")
        bootstrap = self.fpl.get_bootstrap()
        gameweek = gameweek or self.fpl.get_current_gameweek()
        manager = self.fpl.get_manager(manager_id)
        picks = self.fpl.get_manager_picks(manager_id, gameweek)["picks"]
        history = self.fpl.get_manager_history(manager_id)
        news_items = news_items if news_items is not None else self.news.fetch_news()
        classified_news = self.news.summarize_with_gemini(news_items, model=settings.gemini_model)
        if isinstance(classified_news, dict):
            news_items = classified_news["source_items"]
        enrichment = self._fetch_enrichment(gameweek)
        team_names = {team["id"]: team["name"] for team in bootstrap.get("teams", [])}
        elements = [dict(player, team_name=team_names.get(player.get("team"), "")) for player in bootstrap["elements"]]
        fixtures = self.fpl.get_current_gameweek_fixtures(gameweek)
        projected = self.projection_engine.project(
            elements, fixtures, gameweek, news_items,
            enrichment["fbref"], enrichment["odds"],
            wildcard_horizon=settings.wildcard_horizon,
        )
        by_id = {player["id"]: self._normalize(player) for player in projected}
        squad = [by_id[pick["element"]] for pick in picks]
        squad_ids = {player["id"] for player in squad}
        players = [player for player in by_id.values() if player["id"] not in squad_ids]
        current_free_transfers = self.fpl.remaining_free_transfers(history, gameweek)
        free_transfers = settings.free_transfers_override
        if free_transfers is None:
            free_transfers = current_free_transfers
        transfer_analysis = TransferOptimizer(
            squad=squad,
            players=players,
            bank=manager.get("last_deadline_bank", manager.get("bank", 0)) / 10,
            free_transfers=free_transfers,
        ).analyze_transfer_hits()
        transfer_squad = self._apply_transfers(squad, transfer_analysis["transfers"])
        starting, bench = ChipsOptimizer.select_lineup(transfer_squad)
        used_chips = {chip.get("name", "").upper().replace(" ", "_") for chip in history.get("chips", [])}
        available_chips = {chip for chip in {"TC", "BB", "FH", "WC"} if chip not in used_chips}
        all_players = list(by_id.values())
        budget = (manager.get("last_deadline_value", manager.get("value", 0)) + manager.get("last_deadline_bank", manager.get("bank", 0))) / 10
        chip_optimizer = ChipsOptimizer(
            starting,
            bench,
            available=available_chips,
            minimum_gain=settings.chip_minimum_gain,
            all_players=all_players,
            budget=budget,
        )
        free_hit_squad = chip_optimizer.build_chip_squad("expected_points")
        wildcard_squad = chip_optimizer.build_chip_squad("wildcard_expected_points")
        chip_optimizer.free_hit_squad = free_hit_squad
        chip_optimizer.wildcard_squad = wildcard_squad
        chip_optimizer.free_hit_gain = self._lineup_gain(starting, free_hit_squad["starting_xi"] if free_hit_squad else [], "expected_points")
        chip_optimizer.wildcard_gain = self._lineup_gain(starting, wildcard_squad["starting_xi"] if wildcard_squad else [], "wildcard_expected_points")
        chip_analysis = chip_optimizer.recommend_chip_usage()
        selected_chip = chip_analysis.get("use_chip")
        selected_chip_squad = chip_analysis.get("opportunities", {}).get(selected_chip, {}).get("squad") if selected_chip else None
        if selected_chip in {"FH", "WC"} and selected_chip_squad:
            starting = selected_chip_squad["starting_xi"]
            bench = selected_chip_squad["bench"]
        captain = max(starting, key=self._captain_score, default=None)
        vice_candidates = [player for player in starting if not captain or player["id"] != captain["id"]]
        vice_captain = max(vice_candidates, key=self._captain_score, default=None)
        if selected_chip_squad:
            selected_chip_squad["captain"] = captain
            selected_chip_squad["vice_captain"] = vice_captain
        captain_candidates = [
            {
                "name": player["name"],
                "position": player["position"],
                "captain_score": round(self._captain_score(player), 2),
                "expected_points": player.get("expected_points", 0),
                "expected_minutes": player.get("expected_minutes", 0),
                "fixture_difficulty": player.get("fixture_difficulty"),
                "clean_sheet_probability": player.get("clean_sheet_probability"),
                "attacking_involvement": player.get("attacking_involvement", 0),
                "set_piece_involvement": player.get("set_piece_involvement", 0),
                "anytime_goal_probability": player.get("anytime_goal_probability", 0),
            }
            for player in sorted(starting, key=self._captain_score, reverse=True)
        ]
        recommendation = {
            "manager_id": manager_id,
            "gameweek": gameweek + 1,
            "source_gameweek": gameweek,
            "manager_name": manager.get("name"),
            "current_free_transfers": current_free_transfers,
            "free_transfers": free_transfers,
            "transfers": transfer_analysis,
            "chips": chip_analysis,
            "starting_xi": starting,
            "bench": bench,
            "captain": captain,
            "vice_captain": vice_captain,
            "captain_candidates": captain_candidates,
            "sources": ["FPL API", "RSS news"] + enrichment["available_sources"],
            "source_errors": enrichment["errors"],
        }
        recommendation["validation"] = self.validate_recommendation(recommendation, fixtures, bootstrap)
        if not recommendation["validation"]["valid"]:
            raise ValueError("Recommendation validation failed: " + "; ".join(recommendation["validation"]["errors"]))
        return recommendation

    @classmethod
    def validate_recommendation(cls, recommendation, fixtures, bootstrap):
        errors = []
        starting = recommendation.get("starting_xi", [])
        bench = recommendation.get("bench", [])
        all_players = starting + bench
        player_ids = [player.get("id") for player in all_players]
        if len(starting) != 11 or len(bench) != 4:
            errors.append("lineup must contain exactly 11 starters and 4 bench players")
        if len(set(player_ids)) != len(player_ids):
            errors.append("lineup contains duplicate players")
        if not fixtures:
            errors.append("no fixtures were returned for the target gameweek")
        if not recommendation.get("captain") or recommendation["captain"].get("id") not in {player.get("id") for player in starting}:
            errors.append("captain is not in the starting XI")
        if not recommendation.get("vice_captain") or recommendation["vice_captain"].get("id") not in {player.get("id") for player in starting}:
            errors.append("vice-captain is not in the starting XI")
        transfer = recommendation.get("transfers", {})
        final_ids = set(player_ids)
        if recommendation.get("chips", {}).get("use_chip") not in {"FH", "WC"}:
            for move in transfer.get("transfers", []):
                outgoing_id = move.get("player_out", {}).get("id")
                incoming_id = move.get("player_in", {}).get("id")
                if outgoing_id in final_ids:
                    errors.append(f"transferred-out player remains in final squad: {move.get('player_out', {}).get('name', outgoing_id)}")
                if incoming_id not in final_ids:
                    errors.append(f"transferred-in player is missing from final squad: {move.get('player_in', {}).get('name', incoming_id)}")
        if recommendation.get("chips", {}).get("use_chip") == "BB":
            unavailable_bench = [
                player.get("name", "unknown") for player in bench
                if float(player.get("minutes_probability", 0) or 0) <= 0 or float(player.get("availability", 0) or 0) <= 0
            ]
            if unavailable_bench:
                errors.append("Bench Boost bench includes unavailable players: " + ", ".join(unavailable_bench))
        captain = recommendation.get("captain") or {}
        if captain.get("position") in {"DEF", "GKP"}:
            evidence = sum(float(captain.get(field, 0) or 0) for field in ("attacking_involvement", "set_piece_involvement", "anytime_goal_probability"))
            if evidence <= 0:
                errors.append("defensive captain has no live attacking, set-piece, or goal evidence")
        return {"valid": not errors, "errors": errors, "checks": {"fixtures": bool(fixtures), "lineup": len(starting) == 11 and len(bench) == 4, "captain": bool(recommendation.get("captain")), "bench_boost": recommendation.get("chips", {}).get("use_chip") != "BB" or not errors}}

    @staticmethod
    def _apply_transfers(squad, transfers):
        updated = list(squad)
        for transfer in transfers:
            outgoing_id = transfer.get("player_out", {}).get("id")
            incoming = transfer.get("player_in")
            if outgoing_id is None or not incoming:
                continue
            outgoing_index = next((index for index, player in enumerate(updated) if player.get("id") == outgoing_id), None)
            if outgoing_index is not None and not any(player.get("id") == incoming.get("id") for player in updated):
                updated[outgoing_index] = incoming
        return updated

    @staticmethod
    def _captain_score(player):
        distribution = player.get("distribution") or {}
        distribution_mean = distribution.get("mean")
        projected = float(player.get("expected_points", 0) or 0)
        base = projected if distribution_mean is None else (projected + float(distribution_mean)) / 2
        minutes = max(0.0, min(1.0, float(player.get("minutes_probability", 1) or 0)))
        fixture_difficulty = player.get("fixture_difficulty")
        fixture_factor = 1.0 if fixture_difficulty is None else max(0.7, min(1.2, 1.15 - (float(fixture_difficulty) - 1) * 0.125))
        evidence = float(player.get("attacking_involvement", 0) or 0) + float(player.get("set_piece_involvement", 0) or 0) + float(player.get("anytime_goal_probability", 0) or 0)
        if player.get("position") in {"DEF", "GKP"} and evidence <= 0:
            return 0.0
        return base * minutes * fixture_factor * (1.0 + min(0.25, float(player.get("anytime_goal_probability", 0) or 0)))

    def _fetch_enrichment(self, gameweek=None):
        values = {"fbref": {}, "odds": [], "available_sources": [], "errors": {}}
        fixtures = self.fpl.get_current_gameweek_fixtures(gameweek) if gameweek is not None else self.fpl.get_fixtures()
        providers = (("FBRef", self.fbref, "fetch_player_stats"),)
        if settings.soccerdata_api_key:
            providers += (("Soccerdata", self.soccerdata, "get_injury_updates"),)
        providers += (("Odds API", self.odds, "get_player_goal_scorer_market"),)
        for name, provider, method_name in providers:
            try:
                if name == "Odds API":
                    result = provider.get_player_goal_scorer_market(sport="soccer_epl", region="uk", fpl_fixtures=fixtures)
                elif name == "Soccerdata":
                    result = provider.get_injury_updates()
                else:
                    result = getattr(provider, method_name)()
                if name == "FBRef":
                    values["fbref"] = result or values["fbref"]
                elif name == "Odds API":
                    values["odds"] = result or values["odds"]
                values["available_sources"].append(name)
            except Exception as error:
                values["errors"][name] = str(error)
        return values

    @classmethod
    def _normalize(cls, player):
        return {
            "id": player["id"],
            "name": f"{player.get('first_name', '')} {player.get('second_name', '')}".strip(),
            "position": cls.POSITIONS[player["element_type"]],
            "price": player["now_cost"] / 10,
            "team": player["team"],
            "expected_points": player["expected_points"],
            "wildcard_expected_points": player["wildcard_expected_points"],
            "wildcard_confidence": player["wildcard_confidence"],
            "availability": player.get("availability", 1.0),
            "expected_minutes": player["expected_minutes"],
            "minutes_probability": player.get("minutes_probability"),
            "clean_sheet_probability": player.get("clean_sheet_probability"),
            "attacking_involvement": player.get("attacking_involvement", 0),
            "set_piece_involvement": player.get("set_piece_involvement", 0),
            "anytime_goal_probability": player.get("anytime_goal_probability", 0),
            "distribution": player.get("distribution", {}),
            "form": player.get("form"),
        }

    @staticmethod
    def _replacement_gain(current_players, candidate_players):
        candidates_by_position = {}
        for player in candidate_players:
            candidates_by_position.setdefault(player["position"], []).append(player)
        used = set()
        gain = 0.0
        for current in current_players:
            options = sorted(
                (player for player in candidates_by_position.get(current["position"], []) if player["id"] not in used),
                key=lambda player: player["expected_points"],
                reverse=True,
            )
            if options:
                replacement = options[0]
                difference = replacement["expected_points"] - current["expected_points"]
                if difference > 0:
                    gain += difference
                    used.add(replacement["id"])
        return round(gain, 2)

    @staticmethod
    def _lineup_gain(current_players, proposed_players, score_field="expected_points"):
        current_points = sum(player.get(score_field, 0) for player in current_players)
        proposed_points = sum(player.get(score_field, 0) for player in proposed_players)
        return round(max(0.0, proposed_points - current_points), 2)