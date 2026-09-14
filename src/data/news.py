try:
    import feedparser
except ModuleNotFoundError:
    feedparser = None
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
        for url in self.rss_urls:
            feed = feedparser.parse(url)
            entries.extend(
                {
                    "title": entry.get("title", ""),
                    "link": entry.get("link", ""),
                    "published": entry.get("published", ""),
                    "summary": entry.get("summary", ""),
                }
                for entry in feed.entries
            )
        return entries

    def summarize_with_gemini(self, items, max_items=20):
        if not self.gemini_api_key or not items:
            return items
        prompt = "Classify these football news items. Return concise JSON array with title, summary, category (injury, press_conference, other), player_names.\n" + str(items[:max_items])
        try:
            response = self.session.post(
                "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent",
                params={"key": self.gemini_api_key},
                json={"contents": [{"parts": [{"text": prompt}]}]},
                timeout=30,
            )
            response.raise_for_status()
            return {"raw": response.json(), "source_items": items[:max_items]}
        except requests.RequestException:
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