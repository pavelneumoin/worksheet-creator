import os
import telebot
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

if not TELEGRAM_BOT_TOKEN:
    print("WARNING: TELEGRAM_BOT_TOKEN is not set in .env")

# Initialize bot
bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)

from handlers import register_handlers
register_handlers(bot)

if __name__ == '__main__':
    print("Telegram bot started...")
    bot.infinity_polling()
