import requests


class NotificationDeliveryError(RuntimeError):
    pass


class TelegramNotifier:
    def __init__(self, bot_token, chat_id, session=None):
        if not bot_token or not chat_id:
            raise ValueError("Telegram bot token and chat ID are required")
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.session = session or requests.Session()

    def send(self, message):
        try:
            response = self.session.post(
                f"https://api.telegram.org/bot{self.bot_token}/sendMessage",
                json={"chat_id": self.chat_id, "text": message},
                timeout=20,
            )
            response.raise_for_status()
            return response.json()
        except requests.RequestException as error:
            status = error.response.status_code if error.response is not None else None
            raise NotificationDeliveryError(f"Telegram delivery failed; HTTP status={status}") from None