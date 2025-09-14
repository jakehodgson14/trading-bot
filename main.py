import os
import json
import base64
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import telebot

# --- Load Environment Variables ---
creds_b64 = os.getenv("GOOGLE_CREDENTIALS_B64")
SHEET_ID = os.getenv("SHEET_ID")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_ID = os.getenv("TELEGRAM_ID")

# Decode Google credentials
creds_json = base64.b64decode(creds_b64).decode("utf-8")
creds_dict = json.loads(creds_json)

# --- Google Sheets Setup ---
scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
client = gspread.authorize(creds)
sheet = client.open_by_key(SHEET_ID)

# --- Telegram Setup ---
bot = telebot.TeleBot(TELEGRAM_TOKEN)

# Example function: reply to /start
@bot.message_handler(commands=["start"])
def start_message(message):
    bot.send_message(message.chat.id, "🟢 Co-Pilot is online and connected!")

# Test: Notify you when bot launches
bot.send_message(TELEGRAM_ID, "✅ Bot deployed and connected to Google Sheets!")

# Keep bot running
bot.polling(none_stop=True)
