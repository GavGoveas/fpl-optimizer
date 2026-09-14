from src.notifications.telegram import TelegramNotifier


class FakeResponse:
    def raise_for_status(self):
        pass

    def json(self):
        return {"ok": True}


class FakeSession:
    def post(self, url, **kwargs):
        self.url = url
        self.kwargs = kwargs
        return FakeResponse()


def test_telegram_notifier_sends_message():
    session = FakeSession()
    result = TelegramNotifier("token", "chat", session).send("hello")

    assert result["ok"] is True
    assert session.url.endswith("/sendMessage")
    assert session.kwargs["json"] == {"chat_id": "chat", "text": "hello"}