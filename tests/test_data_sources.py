from src.data.fpl_api import FPLAPI
from src.data.news import News
from src.data.odds_api import OddsAPI
from src.data.soccerdata import SoccerData


class FakeResponse:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status = status

    def raise_for_status(self):
        if self.status >= 400:
            raise RuntimeError(self.status)

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return FakeResponse(self.payload)


def test_fpl_client_normalizes_bootstrap_and_manager_endpoints():
    session = FakeSession({"elements": [{"id": 1}], "teams": [{"id": 10}], "events": [{"id": 4, "is_current": True}]})
    client = FPLAPI(base_url="https://fpl.test", session=session)

    assert client.get_players() == [{"id": 1}]
    assert client.get_current_gameweek() == 4
    assert client.get_manager_picks(123, 4) == {"elements": [{"id": 1}], "teams": [{"id": 10}], "events": [{"id": 4, "is_current": True}]}


def test_optional_adapters_use_injected_sessions():
    odds_session = FakeSession([{"home_team": "A", "away_team": "B"}])
    assert OddsAPI(api_key="key", base_url="https://odds.test", session=odds_session).get_market_data() == [{"home_team": "A", "away_team": "B"}]

    soccer_session = FakeSession({"teams": []})
    assert SoccerData(api_key="key", base_url="https://soccer.test", session=soccer_session).fetch_league_data("pl") == {"teams": []}


def test_news_filters_injuries_and_press_conferences():
    news = News()
    items = [
        {"title": "Player injury update", "summary": "Ruled out"},
        {"title": "Manager presser", "summary": "Speaks to media"},
        {"title": "Match preview", "summary": "Kick-off details"},
    ]

    assert len(news.get_injury_updates(items)) == 1
    assert len(news.get_press_conference_info(items)) == 1


def test_news_keeps_full_feed_and_structured_gemini_analysis():
    news = News(gemini_api_key="key")
    items = [{"title": f"Item {index}", "summary": "Update"} for index in range(21)]

    class GeminiResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"candidates": [{"content": {"parts": [{"text": '{"analyses": [' + ",".join('{\"title\": \"ok\"}' for _ in items) + ']}'}]}}]}

    class GeminiSession:
        def post(self, *args, **kwargs):
            return GeminiResponse()

    news.session = GeminiSession()
    result = news.summarize_with_gemini(items)

    assert len(result["source_items"]) == 21
    assert result["source_items"][0]["gemini_analysis"]["title"] == "ok"