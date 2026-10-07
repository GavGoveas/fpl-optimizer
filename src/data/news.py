try:
    import feedparser
except ModuleNotFoundError:
    feedparser = None
import json
import requests


class News:
    def __init__(self, rss_urls=None, gemini_api_key=None, session=None):
        self.rss_urls = list(rss_urls or [])
        self.gemini_api_key = gemini_api_key
        self.session = session or requests.Session()

    def fetch_news(self):
        if feedparser is None:
            raise RuntimeError("feedparser is required to fetch RSS news; install requirements.txt")
        entries = []
        seen = set()
        for url in self.rss_urls:
            feed = feedparser.parse(url)
            for entry in feed.entries:
                item = {
                    "title": entry.get("title", ""),
                    "link": entry.get("link", ""),
                    "published": entry.get("published", ""),
                    "summary": entry.get("summary", ""),
                    "content": " ".join(
                        part.get("value", "") for part in entry.get("content", [])
                    ),
                }
                key = item["link"] or f"{item['title']}|{item['published']}"
                if key not in seen:
                    seen.add(key)
                    entries.append(item)
        return entries

    def summarize_with_gemini(self, items, max_items=None, model="gemini-3.6-flash"):
        if not self.gemini_api_key or not items:
            return items
        source_items = list(items if max_items is None else items[:max_items])
        prompt = (
            "Analyze every football news item below. Return valid JSON only as an object "
            "with an analyses array in the same order. For each item include: title, "
            "link, category (injury, availability, press_conference, suspension, "
            "lineup, transfer, odds, other), player_names, team_names, published, "
            "status (available, doubtful, injured, suspended, ruled_out, expected_to_start, "
            "expected_to_be_benched, unknown), minutes_probability (0 to 1 or null), "
            "confidence (0 to 1), summary, and evidence. Preserve uncertainty and do "
            "not infer a player status when the article does not support it.\n"
            + json.dumps(source_items, ensure_ascii=True)
        )
        try:
            response = self.session.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                params={"key": self.gemini_api_key},
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {"responseMimeType": "application/json"},
                },
                timeout=30,
            )
            response.raise_for_status()
            payload = response.json()
            text = "".join(
                part.get("text", "")
                for candidate in payload.get("candidates", [])
                for part in candidate.get("content", {}).get("parts", [])
            )
            parsed = json.loads(text)
            analyses = parsed.get("analyses", []) if isinstance(parsed, dict) else []
            enriched = []
            for index, item in enumerate(source_items):
                analysis = analyses[index] if index < len(analyses) and isinstance(analyses[index], dict) else {}
                enriched.append(dict(item, gemini_analysis=analysis, gemini_raw=text))
            return {"raw": payload, "source_items": enriched}
        except (requests.RequestException, ValueError, json.JSONDecodeError):
            return items

    def get_injury_updates(self, news=None):
        items = news if news is not None else self.fetch_news()
        terms = ("injury", "injured", "doubt", "fitness", "ruled out", "unavailable")
        return [item for item in items if any(term in self._text(item) for term in terms)]

    def get_press_conference_info(self, news=None):
        items = news if news is not None else self.fetch_news()
        terms = ("press conference", "presser", "speaks to media", "manager says")
        return [item for item in items if any(term in self._text(item) for term in terms)]

    @staticmethod
    def _text(item):
        return f"{item.get('title', '')} {item.get('summary', '')}".lower()


NewsFetcher = News