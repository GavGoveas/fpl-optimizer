try:
    from twilio.rest import Client
except ModuleNotFoundError:
    Client = None


class WhatsAppNotifier:
    def __init__(self, account_sid, auth_token, sender, recipient):
        if Client is None:
            raise RuntimeError("twilio is required for WhatsApp delivery; install requirements.txt")
        if not all((account_sid, auth_token, sender, recipient)):
            raise ValueError("Twilio WhatsApp settings are incomplete")
        self.client = Client(account_sid, auth_token)
        self.sender = sender
        self.recipient = recipient

    def send(self, message):
        return self.client.messages.create(body=message, from_=self.sender, to=self.recipient)


def format_recommendation(recommendation):
    transfer = recommendation["transfers"]
    lines = [
        f"FPL GW {recommendation['gameweek']} plan",
        f"GW {recommendation['gameweek']} free transfers available: {recommendation['free_transfers']}",
    ]
    chip_data = recommendation.get("chips", {})
    chip = chip_data.get("use_chip", chip_data.get("best_chip"))
    chip_squad = chip_data.get("opportunities", {}).get(chip, {}).get("squad") if chip else None
    if chip in {"FH", "WC"} and chip_squad:
        lines.append(f"Transfer strategy: USE {chip}; do not apply the separate hit list")
    else:
        lines.append(f"Transfer strategy: {'TAKE HITS' if transfer['should_take_hits'] else 'NO HITS'}")
        for item in transfer["transfers"]:
            lines.append(f"- {item['player_out']['name']} -> {item['player_in']['name']} ({item['gain']:.1f} projected points)")
    captain = recommendation.get("captain", {})
    vice_captain = recommendation.get("vice_captain", {})
    if chip_squad:
        captain = chip_squad.get("captain") or captain
        vice_captain = chip_squad.get("vice_captain") or vice_captain
    lines.append(f"Captain: {captain.get('name', 'none')}")
    lines.append(f"Vice-captain: {vice_captain.get('name', 'none')}")
    chip_reason = chip_data.get("recommendation", {}).get("reason", "no chip recommendation was generated")
    if chip:
        lines.append(f"USE {chip} because {chip_reason}")
        chip_squad = recommendation["chips"].get("opportunities", {}).get(chip, {}).get("squad")
        if chip in {"FH", "WC"} and chip_squad:
            persistence = recommendation["chips"]["opportunities"][chip].get("persistence")
            if persistence == "one_gameweek_then_revert":
                lines.append("Free Hit reminder: this squad applies for this GW only, then your original squad returns")
            elif persistence == "permanent":
                lines.append("Wildcard reminder: this squad is permanent")
            lines.append("Proposed full squad:")
            lines.extend(f"- {player['name']} ({player['position']})" for player in chip_squad["players"])
            lines.append("Starting XI: " + ", ".join(player["name"] for player in chip_squad["starting_xi"]))
            lines.append("Bench: " + ", ".join(player["name"] for player in chip_squad["bench"]))
            lines.append(f"Chip captain: {chip_squad['captain']['name']}")
            lines.append(f"Chip vice-captain: {chip_squad['vice_captain']['name']}")
    else:
        lines.append(f"DO NOT USE ANY CHIP because {chip_reason}")
    return "\n".join(lines)