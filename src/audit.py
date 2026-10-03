from __future__ import annotations

import json
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class AuditPersistenceError(RuntimeError):
    pass


class RecommendationAuditStore:
    """Atomically persist a replayable recommendation artifact outside Git."""

    def __init__(self, directory: str | Path):
        self.directory = Path(directory)

    def persist(self, recommendation: dict[str, Any]) -> tuple[str, Path]:
        run_id = str(uuid.uuid4())
        recorded_at = datetime.now(timezone.utc)
        artifact = {
            "run_id": run_id,
            "recorded_at_utc": recorded_at.isoformat().replace("+00:00", "Z"),
            "model_version": "fpl-copilot-decision-engine-v2",
            "recommendation": recommendation,
        }
        path = self.directory / f"{recorded_at:%Y}" / f"{recorded_at:%m}" / f"{run_id}.json"
        temporary_path = None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False, newline="\n") as stream:
                temporary_path = Path(stream.name)
                json.dump(artifact, stream, ensure_ascii=True, separators=(",", ":"), allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_path, path)
        except (OSError, TypeError, ValueError) as error:
            if temporary_path:
                temporary_path.unlink(missing_ok=True)
            raise AuditPersistenceError(f"Could not persist recommendation run artifact: {error}") from error
        return run_id, path
