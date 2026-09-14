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
        f"GW {recommendation['source_gameweek']} unused free transfers: {recommendation['current_free_transfers']}",
        f"GW {recommendation['gameweek']} starting free transfers: {recommendation['free_transfers']}",
    ]
    lines.append(f"Transfer strategy: {'TAKE HITS' if transfer['should_take_hits'] else 'NO HITS'}")
    for item in transfer["transfers"]:
        lines.append(f"- {item['player_out']['name']} -> {item['player_in']['name']} ({item['gain']:.1f} projected points)")
    captain = recommendation.get("captain", {})
    vice_captain = recommendation.get("vice_captain", {})
    lines.append(f"Captain: {captain.get('name', 'none')}")
    lines.append(f"Vice-captain: {vice_captain.get('name', 'none')}")
    chip_data = recommendation.get("chips", {})
    chip = chip_data.get("use_chip", chip_data.get("best_chip"))
    chip_reason = chip_data.get("recommendation", {}).get("reason", "no chip recommendation was generated")
    if chip:
        lines.append(f"USE {chip} because {chip_reason}")
    else:
        lines.append(f"DO NOT USE ANY CHIP because {chip_reason}")
    return "\n".join(lines)