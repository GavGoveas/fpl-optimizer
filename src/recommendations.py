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
        classified_news = self.news.summarize_with_gemini(news_items)
        if isinstance(classified_news, dict):
            news_items = classified_news["source_items"]
        enrichment = self._fetch_enrichment()
        projected = self.projection_engine.project(
            bootstrap["elements"], self.fpl.get_fixtures(), gameweek, news_items,
            enrichment["fbref"], enrichment["odds"],
        )
        by_id = {player["id"]: self._normalize(player) for player in projected}
        squad = [by_id[pick["element"]] for pick in picks]
        squad_ids = {player["id"] for player in squad}
        players = [player for player in by_id.values() if player["id"] not in squad_ids]
        free_transfers = self.fpl.upcoming_free_transfers(history)
        transfer_analysis = TransferOptimizer(
            squad=squad,
            players=players,
            bank=manager.get("last_deadline_bank", manager.get("bank", 0)) / 10,
            free_transfers=free_transfers,
        ).analyze_transfer_hits()
        starter_ids = {pick["element"] for pick in picks if pick.get("position", 99) <= 11}
        starting = [player for player in squad if player["id"] in starter_ids]
        bench = [player for player in squad if player["id"] not in starter_ids]
        chip_analysis = ChipsOptimizer(starting, bench).recommend_chip_usage()
        return {
            "manager_id": manager_id,
            "gameweek": gameweek + 1,
            "source_gameweek": gameweek,
            "manager_name": manager.get("name"),
            "free_transfers": free_transfers,
            "transfers": transfer_analysis,
            "chips": chip_analysis,
            "sources": ["FPL API", "RSS news"] + enrichment["available_sources"],
            "source_errors": enrichment["errors"],
        }

    def _fetch_enrichment(self):
        values = {"fbref": {}, "odds": [], "available_sources": [], "errors": {}}
        providers = (("FBRef", self.fbref, "fetch_player_stats"), ("Odds API", self.odds, "get_market_data"))
        if settings.soccerdata_api_key:
            providers += (("Soccerdata", self.soccerdata, "get_injury_updates"),)
        for name, provider, method_name in providers:
            try:
                result = getattr(provider, method_name)()
                key = "fbref" if name == "FBRef" else "odds" if name == "Odds API" else None
                if key:
                    values[key] = result or values[key]
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
            "form": player.get("form"),
        }