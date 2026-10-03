from src.models.rules import FPLRules


class TransferOptimizer:
    """Compare legal transfer plans using supplied expected points."""

    def __init__(self, squad=None, players=None, bank=0.0, free_transfers=1, rules=None):
        self.squad = list(squad or [])
        self.players = list(players or [])
        self.bank = float(bank)
        self.free_transfers = max(0, int(free_transfers))
        self.rules = rules or FPLRules(version="FPL-default")

    @staticmethod
    def _points(player):
        return float(player.get("expected_points", player.get("projection", 0)))

    def _candidate_pairs(self):
        squad_ids = {player["id"] for player in self.squad}
        team_counts = {}
        for player in self.squad:
            team = player.get("team")
            if team is not None:
                team_counts[team] = team_counts.get(team, 0) + 1
        pairs = []
        for outgoing in self.squad:
            for incoming in self.players:
                if incoming["id"] in squad_ids or incoming["position"] != outgoing["position"]:
                    continue
                if float(incoming["price"]) > float(outgoing["price"]) + self.bank:
                    continue
                if incoming.get("team") != outgoing.get("team") and team_counts.get(incoming.get("team"), 0) >= self.rules.club_player_limit:
                    continue
                current_gain = self._points(incoming) - self._points(outgoing)
                incoming_by_event = {str(key): float(value) for key, value in (incoming.get("expected_points_by_event") or {}).items()}
                outgoing_by_event = {str(key): float(value) for key, value in (outgoing.get("expected_points_by_event") or {}).items()}
                shared_events = sorted(
                    set(incoming_by_event).intersection(outgoing_by_event),
                    key=lambda value: int(value),
                )
                future_gain_by_event = {
                    event: float(incoming_by_event[event]) - float(outgoing_by_event[event])
                    for event in shared_events
                }
                multi_gameweek_gain = current_gain + sum(future_gain_by_event.values())
                if current_gain > 0 or multi_gameweek_gain > 0:
                    pairs.append({
                        "player_out": outgoing,
                        "player_in": incoming,
                        "gain": current_gain,
                        "multi_gameweek_gain": multi_gameweek_gain,
                        "future_gain_by_event": future_gain_by_event,
                    })
        return sorted(pairs, key=lambda pair: pair["multi_gameweek_gain"], reverse=True)

    def recommend_single_transfer(self):
        pairs = self._candidate_pairs()
        return pairs[0] if pairs else None

    def recommend_multiple_transfers(self, max_transfers=None):
        selected_out = set()
        selected_in = set()
        outgoing_total = 0.0
        incoming_total = 0.0
        team_counts = {}
        for player in self.squad:
            team = player.get("team")
            if team is not None:
                team_counts[team] = team_counts.get(team, 0) + 1
        result = []
        for pair in self._candidate_pairs():
            outgoing_id = pair["player_out"]["id"]
            incoming_id = pair["player_in"]["id"]
            if outgoing_id in selected_out or incoming_id in selected_in:
                continue
            outgoing = pair["player_out"]
            incoming = pair["player_in"]
            if incoming_total + float(incoming["price"]) > outgoing_total + float(outgoing["price"]) + self.bank:
                continue
            if incoming.get("team") != outgoing.get("team") and team_counts.get(incoming.get("team"), 0) >= self.rules.club_player_limit:
                continue
            result.append(pair)
            selected_out.add(outgoing_id)
            selected_in.add(incoming_id)
            outgoing_total += float(outgoing["price"])
            incoming_total += float(incoming["price"])
            if incoming.get("team") != outgoing.get("team"):
                if outgoing.get("team") is not None:
                    team_counts[outgoing["team"]] -= 1
                if incoming.get("team") is not None:
                    team_counts[incoming["team"]] = team_counts.get(incoming["team"], 0) + 1
            if len(result) >= (max_transfers if max_transfers is not None else len(self.squad)):
                break
        return result

    def analyze_transfer_hits(self, max_transfers=None):
        candidates = self.recommend_multiple_transfers(max_transfers)
        multiweek_data_complete = all(
            bool(player.get("expected_points_by_event"))
            for player in self.squad + self.players
        )
        if not multiweek_data_complete or any(not candidate.get("future_gain_by_event") for candidate in candidates):
            return {
                "transfers": [],
                "transfer_count": 0,
                "free_transfers_used": 0,
                "hit_count": 0,
                "hit_cost": 0,
                "gross_gain": 0.0,
                "net_gain": None,
                "banked_transfer_value": None,
                "hold_baseline": None,
                "transfer_necessary": None,
                "should_take_hits": False,
                "decision_available": False,
                "reason": "multi-Gameweek scenario projections are missing for one or more candidate transfers",
            }
        best_plan = []
        best_net_gain = 0.0
        gross_gain = 0.0
        for count, transfer in enumerate(candidates, start=1):
            gross_gain += transfer["multi_gameweek_gain"]
            hit_count = max(0, count - self.free_transfers)
            hit_cost = hit_count * self.rules.transfer_hit_cost
            net_gain = gross_gain - hit_cost
            if net_gain > best_net_gain:
                best_net_gain = net_gain
                best_plan = candidates[:count]
        transfers = best_plan
        gross_gain = sum(transfer["multi_gameweek_gain"] for transfer in transfers)
        hit_count = max(0, len(transfers) - self.free_transfers)
        hit_cost = hit_count * self.rules.transfer_hit_cost
        banked_transfer_value = self._banked_transfer_value(candidates)
        hold_baseline = banked_transfer_value
        necessary = best_net_gain > hold_baseline
        if not necessary:
            transfers = []
            gross_gain = 0.0
            hit_count = 0
            hit_cost = 0.0
            best_net_gain = 0.0
        return {
            "transfers": transfers,
            "transfer_count": len(transfers),
            "free_transfers_used": min(len(transfers), self.free_transfers),
            "hit_count": hit_count,
            "hit_cost": hit_cost,
            "gross_gain": gross_gain,
            "net_gain": gross_gain - hit_cost,
            "banked_transfer_value": round(banked_transfer_value, 2),
            "hold_baseline": round(hold_baseline, 2),
            "transfer_necessary": necessary,
            "should_take_hits": necessary and hit_count > 0,
            "decision_available": True,
            "reason": None if necessary else "best multi-Gameweek plan does not exceed the roll opportunity value",
        }

    def _banked_transfer_value(self, candidates):
        """Value of preserving the transfer bank, scaled by current bank size."""
        if not candidates or self.free_transfers >= 5:
            return 0.0
        opportunities = [
            max((float(gain) for gain in candidate["future_gain_by_event"].values()), default=0.0)
            for candidate in candidates
        ]
        return max(opportunities, default=0.0) if self.free_transfers < 5 else 0.0

    def get_recommendations(self):
        analysis = self.analyze_transfer_hits()
        return {
            "recommended_transfers": analysis["transfers"],
            "transfer_strategy": "unavailable" if not analysis["decision_available"] else "take_hits" if analysis["should_take_hits"] else "use_free_transfers_only",
            "hit_analysis": analysis,
        }