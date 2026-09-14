class TransferOptimizer:
    """Compare legal transfer plans using supplied expected points."""

    def __init__(self, squad=None, players=None, bank=0.0, free_transfers=1):
        self.squad = list(squad or [])
        self.players = list(players or [])
        self.bank = float(bank)
        self.free_transfers = max(0, int(free_transfers))

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
                if incoming.get("team") != outgoing.get("team") and team_counts.get(incoming.get("team"), 0) >= 3:
                    continue
                gain = self._points(incoming) - self._points(outgoing)
                if gain > 0:
                    pairs.append({"player_out": outgoing, "player_in": incoming, "gain": gain})
        return sorted(pairs, key=lambda pair: pair["gain"], reverse=True)

    def recommend_single_transfer(self):
        pairs = self._candidate_pairs()
        return pairs[0] if pairs else None

    def recommend_multiple_transfers(self, max_transfers=5):
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
            if incoming.get("team") != outgoing.get("team") and team_counts.get(incoming.get("team"), 0) >= 3:
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
            if len(result) >= max_transfers:
                break
        return result

    def analyze_transfer_hits(self, max_transfers=5):
        candidates = self.recommend_multiple_transfers(max_transfers)
        best_plan = []
        best_net_gain = 0.0
        gross_gain = 0.0
        for count, transfer in enumerate(candidates, start=1):
            gross_gain += transfer["gain"]
            hit_count = max(0, count - self.free_transfers)
            net_gain = gross_gain - hit_count * 4
            if net_gain > best_net_gain:
                best_net_gain = net_gain
                best_plan = candidates[:count]
        transfers = best_plan
        gross_gain = sum(transfer["gain"] for transfer in transfers)
        hit_count = max(0, len(transfers) - self.free_transfers)
        hit_cost = hit_count * 4
        return {
            "transfers": transfers,
            "transfer_count": len(transfers),
            "free_transfers_used": min(len(transfers), self.free_transfers),
            "hit_count": hit_count,
            "hit_cost": hit_cost,
            "gross_gain": gross_gain,
            "net_gain": gross_gain - hit_cost,
            "should_take_hits": hit_count > 0 and gross_gain - hit_cost > 0,
        }

    def get_recommendations(self):
        analysis = self.analyze_transfer_hits()
        return {
            "recommended_transfers": analysis["transfers"],
            "transfer_strategy": "take_hits" if analysis["should_take_hits"] else "use_free_transfers_only",
            "hit_analysis": analysis,
        }