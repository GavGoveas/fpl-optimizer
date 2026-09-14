from src.config import settings
from src.notifications.telegram import TelegramNotifier
from src.notifications.whatsapp import format_recommendation
from src.recommendations import RecommendationService


def main():
    recommendation = RecommendationService().build()
    message = format_recommendation(recommendation)
    notifier = TelegramNotifier(settings.telegram_bot_token, settings.telegram_chat_id)
    notifier.send(message)
    print(message)


if __name__ == "__main__":
    main()