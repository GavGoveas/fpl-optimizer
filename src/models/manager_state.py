from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from src.models.rules import FPLRules


class ManagerStateConflict(ValueError):
    def __init__(self, conflicts: list[str]):
        self.conflicts = conflicts
        super().__init__("; ".join(conflicts))


def canonical_chip_name(value: Any) -> str:
    normalized = str(value or "").upper().replace("_", "").replace(" ", "").replace("-", "")
    aliases = {
        "WILDCARD": "WC", "WILDCARD1": "WC", "WILDCARD2": "WC",
        "FREEHIT": "FH", "FREEHIT1": "FH", "FREEHIT2": "FH",
        "BENCHBOOST": "BB", "BBOOST": "BB",
        "TRIPLECAPTAIN": "TC", "3XCAPTAIN": "TC", "3XC": "TC",
    }
    return aliases.get(normalized, normalized)


@dataclass(frozen=True)
class TransferLedger:
    target_gameweek: int
    free_transfers_at_gameweek_start: int
    free_transfers_remaining: int
    free_transfers_for_next_gameweek: int
    transfers_made_this_gameweek: int
    transfer_hit_cost: int
    max_free_transfers: int

    @classmethod
    def reconstruct(
        cls,
        history: dict[str, Any],
        target_gameweek: int,
        *,
        max_free_transfers: int,
        initial_free_transfers: int | None = None,
        transfer_hit_cost: int | None = None,
    ) -> "TransferLedger":
        active_rules = FPLRules(version="FPL-default")
        initial_free_transfers = active_rules.initial_free_transfers if initial_free_transfers is None else int(initial_free_transfers)
        transfer_hit_cost = active_rules.transfer_hit_cost if transfer_hit_cost is None else int(transfer_hit_cost)
        if target_gameweek < 1:
            raise ValueError("target_gameweek must be a positive gameweek number")
        if max_free_transfers < initial_free_transfers or initial_free_transfers < 0:
            raise ValueError("invalid free-transfer limits")

        current = sorted(history.get("current", []), key=lambda item: int(item.get("event", 0)))
        recorded_events = {int(item.get("event", 0)) for item in current if int(item.get("event", 0)) > 0}
        if target_gameweek > 1 and not recorded_events:
            raise ManagerStateConflict(["manager transfer history is unavailable for a post-opening Gameweek"])
        if recorded_events:
            missing = [event for event in range(1, target_gameweek) if event not in recorded_events]
            if missing:
                raise ManagerStateConflict(["manager transfer history is incomplete for Gameweeks: " + ", ".join(map(str, missing))])
        chips_by_event: dict[int, set[str]] = {}
        for chip in history.get("chips", []):
            event = chip.get("event")
            if event is not None:
                chips_by_event.setdefault(int(event), set()).add(canonical_chip_name(chip.get("name")))

        available = initial_free_transfers
        transfers_this_gw = 0
        hits_this_gw = 0
        start_count = initial_free_transfers
        found_target = False
        for row in current:
            event = int(row.get("event", 0))
            if event <= 0 or event > target_gameweek:
                continue
            transfers = max(0, int(row.get("event_transfers", 0) or 0))
            chip_names = chips_by_event.get(event, set())
            chip_protected = bool(chip_names.intersection({"WC", "FH"}))
            if event == target_gameweek:
                start_count = available
                transfers_this_gw = transfers
                hits_this_gw = 0 if chip_protected else max(0, transfers - available)
                used_frees = 0 if chip_protected else min(transfers, available)
                remaining = available - used_frees
                recorded_cost = row.get("event_transfers_cost")
                reconstructed_cost = hits_this_gw * transfer_hit_cost
                if recorded_cost is not None and int(recorded_cost) != reconstructed_cost and not chip_protected:
                    raise ManagerStateConflict([
                        f"GW{event} transfer-cost conflict: history reports {recorded_cost}, ledger reconstructs {reconstructed_cost}"
                    ])
                found_target = True
                break
            used_frees = 0 if chip_protected else min(transfers, available)
            hits = 0 if chip_protected else max(0, transfers - available)
            recorded_cost = row.get("event_transfers_cost")
            if recorded_cost is not None and int(recorded_cost) != hits * transfer_hit_cost and not chip_protected:
                raise ManagerStateConflict([
                    f"GW{event} transfer-cost conflict: history reports {recorded_cost}, ledger reconstructs {hits * transfer_hit_cost}"
                ])
            available = min(max_free_transfers, available - used_frees + 1)

        if not found_target:
            start_count = available
            transfers_this_gw = 0
            hits_this_gw = 0
            remaining = available

        remaining = max(0, min(max_free_transfers, remaining))
        next_count = min(max_free_transfers, remaining + 1)
        return cls(
            target_gameweek=target_gameweek,
            free_transfers_at_gameweek_start=start_count,
            free_transfers_remaining=remaining,
            free_transfers_for_next_gameweek=next_count,
            transfers_made_this_gameweek=transfers_this_gw,
            transfer_hit_cost=hits_this_gw * transfer_hit_cost,
            max_free_transfers=max_free_transfers,
        )


@dataclass(frozen=True)
class ManagerState:
    manager_id: int
    season: str
    current_gameweek: int | None
    next_gameweek: int
    current_deadline: datetime | None
    next_deadline: datetime
    deadline_timezone: str
    bank: float
    squad_value: float
    total_team_value: float
    current_squad: tuple[dict[str, Any], ...]
    purchase_prices: dict[int, float] = field(default_factory=dict)
    selling_prices: dict[int, float] = field(default_factory=dict)
    free_transfers_at_gameweek_start: int = 1
    free_transfers_remaining: int = 1
    free_transfers_for_next_gameweek: int = 1
    max_free_transfers: int = 5
    transfers_made_this_gameweek: int = 0
    transfer_hit_cost: int = 0
    chips_available: tuple[str, ...] = ()
    chips_used: tuple[dict[str, Any], ...] = ()
    wildcard_status: str = "unknown"
    free_hit_status: str = "unknown"
    bench_boost_status: str = "unknown"
    triple_captain_status: str = "unknown"
    rules_version: str = "unknown"
    state_timestamp_utc: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    source_timestamps_utc: dict[str, datetime] = field(default_factory=dict)
    conflicts: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        def serialize(value: Any) -> Any:
            if isinstance(value, datetime):
                if value.tzinfo is None:
                    raise ValueError("all state timestamps must be timezone-aware")
                return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
            if isinstance(value, tuple):
                return [serialize(item) for item in value]
            if isinstance(value, dict):
                return {str(key): serialize(item) for key, item in value.items()}
            if isinstance(value, list):
                return [serialize(item) for item in value]
            return value
        return serialize(asdict(self))


def assemble_manager_state(
    *,
    manager_id: int,
    bootstrap: dict[str, Any],
    manager: dict[str, Any],
    picks_payload: dict[str, Any],
    history: dict[str, Any],
    target_gameweek: int,
    display_timezone: str,
    source_timestamp: datetime,
    rules: FPLRules,
) -> ManagerState:
    if source_timestamp.tzinfo is None:
        raise ValueError("source_timestamp must be timezone-aware")
    events = bootstrap.get("events", [])
    target = next((event for event in events if event.get("id") == target_gameweek), None)
    if target is None or not target.get("deadline_time"):
        raise ManagerStateConflict([f"authoritative deadline unavailable for GW{target_gameweek}"])
    deadline = datetime.fromisoformat(str(target["deadline_time"]).replace("Z", "+00:00"))
    if deadline.tzinfo is None:
        raise ManagerStateConflict([f"GW{target_gameweek} deadline is missing timezone information"])

    current_event = next((event for event in events if event.get("is_current") and not event.get("finished")), None)
    if current_event is None:
        current_event = max((event for event in events if event.get("finished")), key=lambda event: int(event.get("id", 0)), default=None)
    current_deadline = None
    if current_event and current_event.get("deadline_time"):
        current_deadline = datetime.fromisoformat(str(current_event["deadline_time"]).replace("Z", "+00:00"))
        if current_deadline.tzinfo is None:
            raise ManagerStateConflict(["current Gameweek deadline is not timezone-aware"])

    conflicts = []
    picks = picks_payload.get("picks", [])
    if len(picks) != 15:
        conflicts.append(f"manager picks contain {len(picks)} players; expected 15")
    ids = [pick.get("element") for pick in picks]
    if len(set(ids)) != len(ids):
        conflicts.append("manager picks contain duplicate player IDs")
    pick_history = picks_payload.get("entry_history") or {}
    pick_event = pick_history.get("event")
    if pick_event is not None and int(pick_event) != target_gameweek:
        conflicts.append(f"manager picks are for GW{pick_event}, requested GW{target_gameweek}")
    if manager.get("id") is not None and int(manager["id"]) != int(manager_id):
        conflicts.append("manager entry endpoint returned a different manager ID")
    if conflicts:
        raise ManagerStateConflict(conflicts)

    ledger = TransferLedger.reconstruct(
        history,
        target_gameweek,
        max_free_transfers=rules.max_free_transfers,
            initial_free_transfers=rules.initial_free_transfers,
            transfer_hit_cost=rules.transfer_hit_cost,
    )
    history_row = next((row for row in history.get("current", []) if int(row.get("event", 0)) == target_gameweek), None)
    pick_transfers = pick_history.get("event_transfers")
    if history_row and pick_transfers is not None and int(pick_transfers) != int(history_row.get("event_transfers", 0) or 0):
        conflicts.append("manager picks and manager history disagree on transfers made this Gameweek")
    if pick_event is not None and int(pick_event) == target_gameweek:
        for manager_key, picks_key, label in (("bank", "bank", "bank"), ("value", "value", "squad value")):
            manager_value = manager.get(manager_key)
            picks_value = pick_history.get(picks_key)
            if manager_value is not None and picks_value is not None and int(manager_value) != int(picks_value):
                conflicts.append(f"manager entry and picks disagree on {label}")
    if conflicts:
        raise ManagerStateConflict(conflicts)

    chips_used = tuple(history.get("chips", []))
    used_counts = Counter(canonical_chip_name(chip.get("name")) for chip in chips_used)
    chip_catalog = bootstrap.get("chips", [])
    capacity: Counter[str] = Counter()
    active_catalog: dict[str, list[dict[str, Any]]] = {}
    for chip in chip_catalog:
        canonical = canonical_chip_name(chip.get("name"))
        if canonical:
            capacity[canonical] += max(1, int(chip.get("number", 1) or 1))
            active_catalog.setdefault(canonical, []).append(chip)
    available = []
    for canonical, total in capacity.items():
        active = active_catalog[canonical]
        in_window = any(
            (chip.get("start_event") is None or target_gameweek >= int(chip["start_event"]))
            and (chip.get("stop_event") is None or target_gameweek <= int(chip["stop_event"]))
            for chip in active
        )
        if in_window and used_counts[canonical] < total:
            available.append(canonical)

    purchase_prices = {int(pick["element"]): float(pick.get("purchase_price", 0)) / 10 for pick in picks if pick.get("purchase_price") is not None}
    selling_prices = {int(pick["element"]): float(pick.get("selling_price", 0)) / 10 for pick in picks if pick.get("selling_price") is not None}
    bank_tenths = manager.get("bank")
    value_tenths = manager.get("value")
    if bank_tenths is None or value_tenths is None:
        raise ManagerStateConflict(["manager bank or squad value is missing from authoritative entry state"])
    bank = float(bank_tenths) / 10
    squad_value = float(value_tenths) / 10
    season_value = bootstrap.get("game_settings", {}).get("season") or bootstrap.get("season")
    if not season_value:
        season_years = sorted({
            datetime.fromisoformat(str(event["deadline_time"]).replace("Z", "+00:00")).year
            for event in events
            if event.get("deadline_time")
        })
        season_value = f"{season_years[0]}/{season_years[-1]}" if season_years else "unknown"
    season = str(season_value)
    return ManagerState(
        manager_id=manager_id,
        season=season,
        current_gameweek=int(current_event["id"]) if current_event else None,
        next_gameweek=target_gameweek,
        current_deadline=current_deadline,
        next_deadline=deadline,
        deadline_timezone=display_timezone,
        bank=bank,
        squad_value=squad_value,
        total_team_value=bank + squad_value,
        current_squad=tuple(dict(pick) for pick in picks),
        purchase_prices=purchase_prices,
        selling_prices=selling_prices,
        free_transfers_at_gameweek_start=ledger.free_transfers_at_gameweek_start,
        free_transfers_remaining=ledger.free_transfers_remaining,
        free_transfers_for_next_gameweek=ledger.free_transfers_for_next_gameweek,
        max_free_transfers=ledger.max_free_transfers,
        transfers_made_this_gameweek=ledger.transfers_made_this_gameweek,
        transfer_hit_cost=ledger.transfer_hit_cost,
        chips_available=tuple(available),
        chips_used=chips_used,
        wildcard_status="available" if "WC" in available else "used_or_unavailable",
        free_hit_status="available" if "FH" in available else "used_or_unavailable",
        bench_boost_status="available" if "BB" in available else "used_or_unavailable",
        triple_captain_status="available" if "TC" in available else "used_or_unavailable",
        rules_version=rules.version,
        state_timestamp_utc=source_timestamp.astimezone(timezone.utc),
        source_timestamps_utc={"fpl_api": source_timestamp.astimezone(timezone.utc)},
    )
