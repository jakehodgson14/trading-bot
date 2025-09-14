import os
import json
import base64
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import telebot
from dotenv import load_dotenv

# --- Load .env file explicitly (important for Render) ---
load_dotenv("/etc/secrets/.env")

# --- Read environment variables ---
creds_b64 = os.getenv("GOOGLE_CREDENTIALS_B64")
sheet_id = os.getenv("SHEET_ID")
telegram_token = os.getenv("TELEGRAM_TOKEN")
telegram_id = os.getenv("TELEGRAM_ID")

if not creds_b64:
    raise ValueError("❌ GOOGLE_CREDENTIALS_B64 is missing. Check your .env file!")

# --- Decode Google credentials ---
creds_json = base64.b64decode(creds_b64).decode("utf-8")
creds_dict = json.loads(creds_json)

scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]

creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
client = gspread.authorize(creds)

# --- Connect to Google Sheet ---
sheet = client.open_by_key(sheet_id)
print("✅ Connected to Google Sheet")

# --- Connect Telegram Bot ---
bot = telebot.TeleBot(telegram_token)

# simple test message to confirm it works
bot.send_message(telegram_id, "🚀 Bot deployed and running on Render!")

print("✅ Telegram bot started and ready to send messages")

# keep the bot polling
bot.polling(none_stop=True, interval=1)
