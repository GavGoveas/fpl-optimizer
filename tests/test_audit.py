import json

from src.audit import RecommendationAuditStore


def test_audit_artifact_is_atomically_persisted_and_replayable(tmp_path):
    recommendation = {
        "gameweek": 6,
        "manager_state": {"free_transfers_remaining": 1},
        "transfers": {"transfers": []},
        "validation": {"valid": True},
    }

    run_id, path = RecommendationAuditStore(tmp_path).persist(recommendation)

    artifact = json.loads(path.read_text(encoding="utf-8"))
    assert artifact["run_id"] == run_id
    assert artifact["recommendation"] == recommendation
    assert artifact["recorded_at_utc"].endswith("Z")
    assert not list(path.parent.glob("*.tmp"))


def test_audit_artifact_rejects_nan_values(tmp_path):
    recommendation = {"projection": float("nan")}

    try:
        RecommendationAuditStore(tmp_path).persist(recommendation)
    except Exception as error:
        assert type(error).__name__ == "AuditPersistenceError"
    else:
        raise AssertionError("non-finite recommendation values must not be persisted")
