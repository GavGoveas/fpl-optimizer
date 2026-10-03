from datetime import datetime
from zoneinfo import ZoneInfo

from flask import Flask, jsonify

from src.config import settings
from src.data.fpl_api import FPLAPI

app = Flask(__name__)


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


@app.get("/api/schedule")
def schedule_state():
    try:
        fpl = FPLAPI()
        bootstrap = fpl.get_bootstrap()
        event = fpl.select_next_gameweek(bootstrap.get("events", []))
        if event is None:
            return jsonify({"available": False, "reason": "No upcoming FPL deadline is published"}), 503
        deadline = datetime.fromisoformat(str(event["deadline_time"]).replace("Z", "+00:00"))
        if deadline.tzinfo is None:
            return jsonify({"available": False, "reason": "FPL returned a deadline without timezone"}), 503
        local_deadline = deadline.astimezone(ZoneInfo(settings.timezone))
        fixtures = fpl.get_current_gameweek_fixtures(event["id"])
        kickoff_times = []
        for fixture in fixtures:
            value = fixture.get("kickoff_time")
            if value:
                kickoff = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
                if kickoff.tzinfo is not None:
                    kickoff_times.append(kickoff.astimezone(ZoneInfo("UTC")))
        return jsonify({
            "available": True,
            "gameweek": event["id"],
            "deadline_utc": deadline.astimezone(ZoneInfo("UTC")).isoformat().replace("+00:00", "Z"),
            "deadline_local": local_deadline.isoformat(),
            "display_timezone": settings.timezone,
            "fixture_count": len(fixtures),
            "first_fixture_utc": min(kickoff_times).isoformat().replace("+00:00", "Z") if kickoff_times else None,
            "last_fixture_utc": max(kickoff_times).isoformat().replace("+00:00", "Z") if kickoff_times else None,
        })
    except Exception:
        return jsonify({"available": False, "reason": "FPL schedule data could not be retrieved"}), 503


def main():
    app.run(host="127.0.0.1", port=5000, debug=False)


if __name__ == "__main__":
    main()
