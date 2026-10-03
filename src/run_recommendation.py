import os
from datetime import datetime, timezone
import json

from src.config import settings
from src.audit import RecommendationAuditStore
from src.data.fpl_api import FPLAPIError
from src.models.manager_state import ManagerStateConflict
from src.notifications.telegram import TelegramNotifier
from src.notifications.whatsapp import format_recommendation
from src.recommendations import RecommendationService, RecommendationValidationError
from src.notifications.deadline_scheduler import DeadlineStageStore, DueStage


def main():
    scheduled = os.getenv("FPL_SCHEDULED", "false").lower() == "true"
    store = None
    stage = None
    if scheduled:
        store = DeadlineStageStore(os.getenv("FPL_SCHEDULE_STATE_PATH", ".fplcopilot/scheduler.sqlite"))
        deadline = datetime.fromisoformat(os.environ["FPL_SCHEDULE_DEADLINE"].replace("Z", "+00:00"))
        stage = DueStage(
            gameweek=int(os.environ["FPL_SCHEDULE_GAMEWEEK"]),
            deadline=deadline,
            stage_offset_minutes=int(os.environ["FPL_SCHEDULE_STAGE_OFFSET_MINUTES"]),
            deadline_key=os.environ["FPL_SCHEDULE_DEADLINE_KEY"],
            notify=os.getenv("FPL_SCHEDULE_NOTIFY", "false").lower() == "true",
        )
    try:
        if stage and datetime.now(timezone.utc) >= stage.deadline.astimezone(timezone.utc):
            raise RuntimeError("Gameweek deadline passed before scheduled recommendation execution")
        recommendation = RecommendationService().build(gameweek=stage.gameweek if stage else None)
        if not recommendation.get("validation", {}).get("valid"):
            raise RuntimeError("Recommendation failed its final validation gate")
        if stage:
            actual_deadline = datetime.fromisoformat(recommendation["manager_state"]["next_deadline"].replace("Z", "+00:00"))
            if actual_deadline.astimezone(timezone.utc) != stage.deadline.astimezone(timezone.utc):
                raise RuntimeError("FPL deadline changed between scheduler probe and recommendation build")
        message = format_recommendation(recommendation)
        if not stage or stage.notify:
            notifier = TelegramNotifier(settings.telegram_bot_token, settings.telegram_chat_id)
            notifier.send(message)
        if stage and store:
            store.complete(stage, notified=stage.notify)
        print(message)
    except (RecommendationValidationError, ManagerStateConflict, FPLAPIError) as error:
        if isinstance(error, RecommendationValidationError):
            run_id = error.run_id
            failures = error.errors
        elif isinstance(error, ManagerStateConflict):
            failure = {"manager_state_conflicts": error.conflicts}
            run_id, _ = RecommendationAuditStore(settings.run_artifact_dir).persist(failure)
            failures = error.conflicts
        else:
            failure = {"critical_source_failure": "authoritative FPL source unavailable", "error_type": type(error).__name__}
            run_id, _ = RecommendationAuditStore(settings.run_artifact_dir).persist(failure)
            failures = ["authoritative FPL data unavailable"]
        safe_message = (
            "FPL automation stopped: critical data validation did not pass. "
            "No transfers, captain, or chip advice was sent. "
            f"Run ID: {run_id}. Validation issues: {len(failures)}."
        )
        if not stage or stage.notify:
            TelegramNotifier(settings.telegram_bot_token, settings.telegram_chat_id).send(safe_message)
        if stage and store:
            store.complete(stage, notified=stage.notify)
        print(json.dumps({"run_id": run_id, "status": "blocked", "validation_issue_count": len(failures)}))
    except Exception:
        if stage and store:
            store.release(stage)
        raise


if __name__ == "__main__":
    main()