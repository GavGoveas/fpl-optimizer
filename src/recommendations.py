from src.config import settings
from src.audit import RecommendationAuditStore
from src.data.fbref import FBRef
from src.data.fpl_api import FPLAPI
from src.data.news import News
from src.data.odds_api import OddsAPI
from src.data.soccerdata import SoccerData
from src.optimizer.chips import ChipsOptimizer
from src.optimizer.projections import ProjectionEngine
from src.optimizer.transfers import TransferOptimizer
from src.models.manager_state import ManagerStateConflict, assemble_manager_state
from src.models.rules import FPLRules


class RecommendationValidationError(RuntimeError):
    def __init__(self, errors, run_id, artifact_path):
        self.errors = list(errors)
        self.run_id = run_id
        self.artifact_path = str(artifact_path)
        super().__init__(f"Critical recommendation validation failed; no advice emitted; run_id={run_id}; failure_count={len(self.errors)}")


class RecommendationService:
    """Assemble live FPL state and optional enrichment into one recommendation."""

    POSITIONS = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}

    def __init__(self, fpl=None, news=None, projection_engine=None, fbref=None, soccerdata=None, odds=None, audit_store=None):
        self.fpl = fpl or FPLAPI()
        self.news = news or News(settings.rss_urls, settings.gemini_api_key)
        self.projection_engine = projection_engine or ProjectionEngine()
        self.fbref = fbref or FBRef()
        self.soccerdata = soccerdata or SoccerData(settings.soccerdata_api_key, settings.soccerdata_url)
        self.odds = odds or OddsAPI(settings.odds_api_key, settings.odds_api_url)
        self.audit_store = audit_store or RecommendationAuditStore(settings.run_artifact_dir)

    def build(self, manager_id=None, gameweek=None, news_items=None):
        manager_id = manager_id or settings.manager_id
        if manager_id is None:
            raise ValueError("FPL_MANAGER_ID must be configured")
        bootstrap = self.fpl.get_bootstrap()
        if gameweek is None:
            event = self.fpl.select_next_gameweek(bootstrap.get("events", []))
            gameweek = event.get("id") if event else None
        if gameweek is None:
            raise ManagerStateConflict(["no upcoming actionable Gameweek was found from authoritative FPL deadlines"])
        manager = self.fpl.get_manager(manager_id)
        history = self.fpl.get_manager_history(manager_id)
        picks_payload = self.fpl.get_manager_picks(manager_id, gameweek)
        picks = picks_payload["picks"]
        rules = FPLRules.from_bootstrap(bootstrap)
        source_timestamp = getattr(self.fpl, "last_retrieved_at", None)
        if source_timestamp is None:
            from datetime import datetime, timezone
            source_timestamp = datetime.now(timezone.utc)
        manager_state = assemble_manager_state(
            manager_id=manager_id,
            bootstrap=bootstrap,
            manager=manager,
            picks_payload=picks_payload,
            history=history,
            target_gameweek=gameweek,
            display_timezone=settings.timezone,
            source_timestamp=source_timestamp,
            rules=rules,
        )
        news_errors = []
        if news_items is None:
            try:
                news_items = self.news.fetch_news()
            except Exception as error:
                news_items = []
                news_errors.append({"source": "RSS", "type": type(error).__name__})
        news_errors.extend(getattr(self.news, "last_errors", []))
        classified_news = self.news.summarize_with_gemini(news_items, model=settings.gemini_model)
        if isinstance(classified_news, dict):
            news_items = classified_news["source_items"]
            news_errors.extend(classified_news.get("errors", []))
        enrichment = self._fetch_enrichment(gameweek)
        team_names = {team["id"]: team["name"] for team in bootstrap.get("teams", [])}
        elements = [dict(player, team_name=team_names.get(player.get("team"), "")) for player in bootstrap["elements"]]
        fixtures = self.fpl.get_current_gameweek_fixtures(gameweek)
        projected = self.projection_engine.project(
            elements, fixtures, gameweek, news_items,
            enrichment["fbref"], enrichment["odds"],
            wildcard_horizon=settings.wildcard_horizon,
            news_freshness_hours=settings.news_freshness_hours,
        )
        by_id = {player["id"]: self._normalize(player) for player in projected}
        squad = [by_id[pick["element"]] for pick in picks]
        squad_ids = {player["id"] for player in squad}
        players = [player for player in by_id.values() if player["id"] not in squad_ids]
        current_free_transfers = manager_state.free_transfers_remaining
        free_transfers = manager_state.free_transfers_remaining
        transfer_analysis = TransferOptimizer(
            squad=squad,
            players=players,
            bank=manager_state.bank,
            free_transfers=free_transfers,
            rules=rules,
        ).analyze_transfer_hits()
        transfer_squad = self._apply_transfers(squad, transfer_analysis["transfers"])
        starting, bench = ChipsOptimizer.select_lineup(transfer_squad, rules=rules)
        available_chips = set(manager_state.chips_available)
        all_players = list(by_id.values())
        budget = manager_state.total_team_value
        chip_optimizer = ChipsOptimizer(
            starting,
            bench,
            available=available_chips,
            all_players=all_players,
            budget=budget,
            rules=rules,
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
        distribution_candidates = [player for player in starting if (player.get("distribution") or {}).get("available")]
        captain = max(distribution_candidates, key=self._captain_score, default=None)
        vice_candidates = [player for player in distribution_candidates if not captain or player["id"] != captain["id"]]
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
            for player in sorted(distribution_candidates, key=self._captain_score, reverse=True)
        ]
        recommendation = {
            "manager_id": manager_id,
            "gameweek": gameweek,
            "source_gameweek": manager_state.current_gameweek,
            "manager_name": manager.get("name"),
            "manager_state": manager_state.to_dict(),
            "rules_version": rules.version,
            "rules_source": rules.source,
            "scoring_rules_source": rules.scoring_source,
            "warnings": sorted(
                {item.get("source", "news") for item in news_errors}
                | set(enrichment["errors"])
                | ({"scoring_rules_fallback"} if rules.scoring_source != "official_fpl_api" else set())
                | ({"multi_gameweek_transfer_forecasts_missing"} if not transfer_analysis.get("decision_available", True) else set())
            ),
            "data_freshness": {"fpl_api": source_timestamp.isoformat().replace("+00:00", "Z")},
            "current_free_transfers": current_free_transfers,
            "free_transfers": free_transfers,
            "transfers": transfer_analysis,
            "chips": chip_analysis,
            "starting_xi": starting,
            "bench": bench,
            "captain": captain,
            "vice_captain": vice_captain,
            "captain_candidates": captain_candidates,
            "captain_decision_available": bool(captain and vice_captain),
            "sources": ["FPL API", "RSS news"] + enrichment["available_sources"],
            "source_errors": {**enrichment["errors"], "news": news_errors},
        }
        recommendation["validation"] = self.validate_recommendation(recommendation, fixtures, bootstrap)
        if not recommendation["validation"]["valid"]:
            run_id, artifact_path = self.audit_store.persist({
                "gameweek": recommendation.get("gameweek"),
                "manager_state": recommendation.get("manager_state"),
                "rules_version": recommendation.get("rules_version"),
                "source_errors": recommendation.get("source_errors"),
                "warnings": recommendation.get("warnings"),
                "validation": recommendation["validation"],
            })
            raise RecommendationValidationError(recommendation["validation"]["errors"], run_id, artifact_path)
        run_id, artifact_path = self.audit_store.persist(recommendation)
        recommendation["run_id"] = run_id
        recommendation["artifact_path"] = str(artifact_path)
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
        unverified_availability = sum(player.get("availability") is None for player in all_players)
        if unverified_availability:
            errors.append(f"lineup contains {unverified_availability} players with unresolved availability")
        if not fixtures:
            errors.append("no fixtures were returned for the target gameweek")
        target_gameweek = recommendation.get("gameweek")
        if target_gameweek is not None and not any(fixture.get("event") == target_gameweek for fixture in fixtures):
            errors.append("fixture slate does not contain the recommendation Gameweek")
        if not recommendation.get("captain") or recommendation["captain"].get("id") not in {player.get("id") for player in starting}:
            errors.append("captain is not in the starting XI")
        if not recommendation.get("vice_captain") or recommendation["vice_captain"].get("id") not in {player.get("id") for player in starting}:
            errors.append("vice-captain is not in the starting XI")
        if not recommendation.get("captain_decision_available", True):
            errors.append("captain/vice analysis requires player outcome distributions")
        if any(not (player.get("distribution") or {}).get("available") for player in all_players):
            errors.append("lineup scenario distributions are missing for one or more players")
        transfer = recommendation.get("transfers", {})
        if not transfer.get("decision_available", True):
            errors.append("transfer analysis requires event-indexed multi-Gameweek forecasts")
        final_ids = set(player_ids)
        if recommendation.get("chips", {}).get("use_chip") not in {"FH", "WC"}:
            for move in transfer.get("transfers", []):
                outgoing_id = move.get("player_out", {}).get("id")
                incoming_id = move.get("player_in", {}).get("id")
                if outgoing_id in final_ids:
                    errors.append("transferred-out player remains in final squad")
                if incoming_id not in final_ids:
                    errors.append("transferred-in player is missing from final squad")
        if recommendation.get("chips", {}).get("use_chip") == "BB":
            unavailable_bench = [
                player.get("name", "unknown") for player in bench
                if float(player.get("minutes_probability", 0) or 0) <= 0 or float(player.get("availability", 0) or 0) <= 0
            ]
            if unavailable_bench:
                errors.append(f"Bench Boost bench includes {len(unavailable_bench)} unavailable players")
        captain = recommendation.get("captain") or {}
        if captain.get("position") in {"DEF", "GKP"}:
            evidence = sum(float(captain.get(field, 0) or 0) for field in ("attacking_involvement", "set_piece_involvement", "anytime_goal_probability"))
            if evidence <= 0:
                errors.append("defensive captain has no live attacking, set-piece, or goal evidence")
        manager_state = recommendation.get("manager_state")
        if manager_state:
            max_transfers = manager_state.get("max_free_transfers")
            ft_values = (
                manager_state.get("free_transfers_at_gameweek_start"),
                manager_state.get("free_transfers_remaining"),
                manager_state.get("free_transfers_for_next_gameweek"),
            )
            if max_transfers is not None and any(value is None or value < 0 or value > max_transfers for value in ft_values):
                errors.append("manager free-transfer ledger violates active bounds")
            if manager_state.get("next_gameweek") != target_gameweek:
                errors.append("manager state Gameweek conflicts with recommendation Gameweek")
            if not manager_state.get("next_deadline"):
                errors.append("authoritative Gameweek deadline is missing")
        position_counts = {position: sum(player.get("position") == position for player in all_players) for position in ("GKP", "DEF", "MID", "FWD")}
        if len(all_players) == 15 and position_counts != {"GKP": 2, "DEF": 5, "MID": 5, "FWD": 3}:
            errors.append("squad does not meet FPL position quotas")
        club_counts = {}
        for player in all_players:
            club = player.get("team")
            if club is not None:
                club_counts[club] = club_counts.get(club, 0) + 1
        if any(count > 3 for count in club_counts.values()):
            errors.append("squad exceeds the FPL per-club player limit")
        available = recommendation.get("manager_state", {}).get("chips_available")
        selected = recommendation.get("chips", {}).get("use_chip")
        if not recommendation.get("chips", {}).get("decision_available", True):
            errors.append("chip opportunity-cost scenarios are unavailable")
        if recommendation.get("scoring_rules_source") != "official_fpl_api":
            errors.append("active season scoring rules are unavailable from an authoritative source")
        if selected and available is not None and selected not in available:
            errors.append("selected chip is not available according to manager state")
        return {
            "valid": not errors,
            "errors": errors,
            "checks": {
                "fixtures": bool(fixtures),
                "lineup": len(starting) == 11 and len(bench) == 4,
                "captain": bool(recommendation.get("captain")),
                "bench_boost": recommendation.get("chips", {}).get("use_chip") != "BB" or not errors,
                "manager_state": not any("manager" in error for error in errors),
                "chip_availability": not any("chip" in error for error in errors),
            },
        }

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
        base = projected if distribution_mean is None else float(distribution_mean)
        availability = max(0.0, min(1.0, float(player.get("availability", 1) or 0)))
        evidence = float(player.get("attacking_involvement", 0) or 0) + float(player.get("set_piece_involvement", 0) or 0) + float(player.get("anytime_goal_probability", 0) or 0)
        if player.get("position") in {"DEF", "GKP"} and evidence <= 0:
            return 0.0
        return base * availability

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
                    if result:
                        values["fbref"] = result
                    elif getattr(provider, "last_error", None):
                        values["errors"][name] = provider.last_error
                elif name == "Odds API":
                    values["odds"] = result or values["odds"]
                if result:
                    values["available_sources"].append(name)
            except Exception as error:
                values["errors"][name] = {"type": type(error).__name__, "message": self._safe_error_message(str(error))}
        return values

    @staticmethod
    def _safe_error_message(message):
        import re
        message = re.sub(r"(?i)(api[_-]?key|token|authorization|password|secret)([\s=:]+)[^\s&,;]+", r"\1\2[REDACTED]", message)
        return re.sub(r"(?i)([?&](?:key|token|api_key)=)[^&\s]+", r"\1[REDACTED]", message)

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
            "expected_points_by_event": player.get("expected_points_by_event", {}),
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