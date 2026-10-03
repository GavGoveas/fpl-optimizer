import json
import requests

from src.data.fpl_api import FPLAPI, FPLAPIError
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


def test_fpl_request_errors_do_not_expose_manager_identifiers():
    class BadSession:
        @staticmethod
        def get(url, **kwargs):
            raise requests.HTTPError(f"request failed at {url}")

    client = FPLAPI(base_url="https://fpl.test", session=BadSession())
    try:
        client.get_manager(123456789)
    except FPLAPIError as error:
        assert "123456789" not in str(error)
        assert "entry" in str(error)
    else:
        raise AssertionError("FPL request failure should raise a sanitized typed error")


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


def test_gemini_batches_every_feed_item_without_truncation():
    news = News(gemini_api_key="test-key", batch_size=7, max_batch_chars=100000)
    items = [{"title": f"Article {index}", "summary": "reported update"} for index in range(23)]

    class GeminiResponse:
        def __init__(self, count):
            self.count = count

        def raise_for_status(self):
            return None

        def json(self):
            analyses = [{"status": "unknown", "confidence": 0.0} for _ in range(self.count)]
            return {"candidates": [{"content": {"parts": [{"text": json.dumps({"analyses": analyses})}]}}]}

    class GeminiSession:
        def __init__(self):
            self.calls = []

        def post(self, url, params=None, json=None, timeout=None):
            self.calls.append(json)
            return GeminiResponse(min(7, 23 - (len(self.calls) - 1) * 7))

    session = GeminiSession()
    news.session = session
    result = news.summarize_with_gemini(items, max_items=7)

    assert len(session.calls) == 4
    assert len(result["source_items"]) == len(items)
    assert all(isinstance(item.get("gemini_analysis"), dict) for item in result["source_items"])


def test_gemini_parse_failure_is_visible_on_each_unprocessed_item():
    news = News(gemini_api_key="test-key")
    items = [{"title": "Injury update"}]

    class BadResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"candidates": [{"content": {"parts": [{"text": "not json"}]}}]}

    class BadSession:
        @staticmethod
        def post(*args, **kwargs):
            return BadResponse()

    news.session = BadSession()
    result = news.summarize_with_gemini(items)

    assert result["source_items"][0]["gemini_error"] == "JSONDecodeError"
    assert result["errors"][0]["source"] == "Gemini"