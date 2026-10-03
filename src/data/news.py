from __future__ import annotations

import json
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests

try:
    import feedparser
except ModuleNotFoundError:
    feedparser = None


class News:
    def __init__(self, rss_urls=None, gemini_api_key=None, session=None, timeout=20, batch_size=20, max_batch_chars=24000):
        self.rss_urls = list(rss_urls or [])
        self.gemini_api_key = gemini_api_key
        self.session = session or requests.Session()
        self.timeout = float(timeout)
        self.batch_size = max(1, int(batch_size))
        self.max_batch_chars = max(1024, int(max_batch_chars))
        self.last_errors: list[dict[str, str]] = []
        self.last_retrieved_at: datetime | None = None

    def fetch_news(self):
        if feedparser is None:
            raise RuntimeError("feedparser is required to fetch RSS news; install requirements.txt")
        self.last_errors = []
        entries = []
        seen = set()
        for url in self.rss_urls:
            try:
                response = self.session.get(url, timeout=self.timeout)
                response.raise_for_status()
                retrieved = datetime.now(timezone.utc)
                feed = feedparser.parse(response.content)
                if getattr(feed, "bozo", False) and not feed.entries:
                    raise ValueError("RSS document could not be parsed")
                host = urlparse(url).hostname or "unknown"
                for entry in feed.entries:
                    published = str(entry.get("published", ""))
                    item = {
                        "title": entry.get("title", ""),
                        "link": entry.get("link", ""),
                        "published": published,
                        "published_at_utc": self._published_utc(entry),
                        "summary": entry.get("summary", ""),
                        "content": " ".join(part.get("value", "") for part in entry.get("content", [])),
                        "source": host,
                        "retrieved_at_utc": retrieved.isoformat().replace("+00:00", "Z"),
                    }
                    key = item["link"] or f"{item['title']}|{published}|{host}"
                    if key not in seen:
                        seen.add(key)
                        entries.append(item)
            except (requests.RequestException, ValueError, OSError) as error:
                self.last_errors.append({"source": urlparse(url).hostname or "unknown", "type": type(error).__name__})
        self.last_retrieved_at = datetime.now(timezone.utc)
        return entries

    def summarize_with_gemini(self, items, max_items=None, model="gemini-2.0-flash"):
        source_items = list(items or [])
        self.last_errors = list(self.last_errors)
        if not self.gemini_api_key or not source_items:
            return source_items
        chunk_limit = self.batch_size if max_items is None else max(1, int(max_items))
        enriched = [dict(item) for item in source_items]
        raw_responses = []
        start = 0
        while start < len(source_items):
            indices = self._bounded_batch_indices(source_items, start, chunk_limit)
            batch = [source_items[index] for index in indices]
            prompt = self._prompt(batch)
            try:
                response = self.session.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                    params={"key": self.gemini_api_key},
                    json={
                        "contents": [{"parts": [{"text": prompt}]}],
                        "generationConfig": {"responseMimeType": "application/json"},
                    },
                    timeout=self.timeout,
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
                if not isinstance(analyses, list):
                    raise ValueError("Gemini response omitted the analyses array")
                raw_responses.append(payload)
                for local_index, source_index in enumerate(indices):
                    analysis = analyses[local_index] if local_index < len(analyses) else {}
                    if isinstance(analysis, dict):
                        enriched[source_index]["gemini_analysis"] = analysis
                    else:
                        enriched[source_index]["gemini_analysis"] = {"status": "unknown", "confidence": 0.0}
            except (requests.RequestException, ValueError, TypeError) as error:
                self.last_errors.append({"source": "Gemini", "type": type(error).__name__})
                for source_index in indices:
                    enriched[source_index]["gemini_analysis"] = {"status": "unknown", "confidence": 0.0}
                    enriched[source_index]["gemini_error"] = type(error).__name__
            start = indices[-1] + 1
        return {"raw": raw_responses, "source_items": enriched, "errors": list(self.last_errors)}

    def _bounded_batch_indices(self, items, start, chunk_limit):
        indices = []
        size = 0
        for index in range(start, min(len(items), start + chunk_limit)):
            item_size = len(json.dumps(items[index], ensure_ascii=True))
            if indices and size + item_size > self.max_batch_chars:
                break
            indices.append(index)
            size += item_size
        return indices or [start]

    @staticmethod
    def _prompt(items):
        return (
            "Analyze every football news item in the array. Return valid JSON only as "
            "{\"analyses\":[...]} with exactly one result per input in order. Each result "
            "must include title, link, category (injury, availability, press_conference, "
            "suspension, lineup, transfer, tactical_change, other), player_names, team_names, "
            "published, status (available, doubtful, injured, suspended, ruled_out, "
            "expected_to_start, expected_to_be_benched, unknown), availability_probability "
            "(0..1 or null), minutes_probability (0..1 or null), confidence (0..1), "
            "summary, and exact supporting evidence. Do not infer beyond the article, do not "
            "discard uncertainty, and do not treat a publication timestamp as a match event.\n"
            + json.dumps(items, ensure_ascii=True)
        )

    @staticmethod
    def _published_utc(entry):
        parsed = entry.get("published_parsed") or entry.get("updated_parsed")
        if parsed is None:
            return None
        from calendar import timegm
        return datetime.fromtimestamp(timegm(parsed), timezone.utc).isoformat().replace("+00:00", "Z")

    def get_injury_updates(self, news=None):
        items = news if news is not None else self.fetch_news()
        terms = ("injury", "injured", "doubt", "fitness", "ruled out", "unavailable", "suspended")
        return [item for item in items if any(term in self._text(item) for term in terms)]

    def get_press_conference_info(self, news=None):
        items = news if news is not None else self.fetch_news()
        terms = ("press conference", "presser", "speaks to media", "manager says")
        return [item for item in items if any(term in self._text(item) for term in terms)]

    @staticmethod
    def _text(item):
        analysis = item.get("gemini_analysis", {})
        if isinstance(analysis, dict):
            analysis = " ".join(str(value) for value in analysis.values())
        return f"{item.get('title', '')} {item.get('summary', '')} {item.get('content', '')} {analysis}".lower()


NewsFetcher = News
