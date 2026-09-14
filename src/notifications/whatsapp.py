from twilio.rest import Client


class WhatsAppNotifier:
    def __init__(self, account_sid, auth_token, sender, recipient):
        if not all((account_sid, auth_token, sender, recipient)):
            raise ValueError("Twilio WhatsApp settings are incomplete")
        self.client = Client(account_sid, auth_token)
        self.sender = sender
        self.recipient = recipient

    def send(self, message):
        return self.client.messages.create(body=message, from_=self.sender, to=self.recipient)


def format_recommendation(recommendation):
    transfer = recommendation["transfers"]
    lines = [f"FPL GW {recommendation['gameweek']} recommendation", f"Free transfers: {recommendation['free_transfers']}"]
    lines.append(f"Transfer strategy: {'TAKE HITS' if transfer['should_take_hits'] else 'NO HITS'}")
    for item in transfer["transfers"]:
        lines.append(f"- {item['player_out']['name']} -> {item['player_in']['name']} ({item['gain']:.1f} projected points)")
    chip = recommendation["chips"].get("best_chip")
    lines.append(f"Best chip opportunity: {chip or 'none'}")
    return "\n".join(lines)