import os
import json
import base64
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import telebot

# === Load environment variables ===
creds_b64 = os.getenv("GOOGLE_CREDENTIALS_B64")
sheet_id = os.getenv("SHEET_ID")
telegram_token = os.getenv("TELEGRAM_TOKEN")
telegram_id = os.getenv("TELEGRAM_ID")

# === Debugging output ===
print("DEBUG: Checking environment variables...")
print("GOOGLE_CREDENTIALS_B64 present?", bool(creds_b64))
print("SHEET_ID:", sheet_id)
print("TELEGRAM_TOKEN present?", bool(telegram_token))
print("TELEGRAM_ID:", telegram_id)

if not creds_b64:
    raise ValueError("❌ GOOGLE_CREDENTIALS_B64 not set in environment!")

# === Decode credentials ===
creds_json = base64.b64decode(creds_b64).decode("utf-8")
creds_dict = json.loads(creds_json)

scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
client = gspread.authorize(creds)

# === Connect to Google Sheet ===
try:
    sheet = client.open_by_key(sheet_id)
    worksheet = sheet.get_worksheet(0)  # first tab
    print("✅ Connected to Google Sheet:", sheet.title)
except Exception as e:
    print("❌ Failed to connect to Google Sheet:", str(e))
    raise

# === Connect to Telegram Bot ===
bot = telebot.TeleBot(telegram_token)

try:
    bot.send_message(telegram_id, "✅ Bot deployed and connected successfully!")
    print("✅ Telegram message sent")
except Exception as e:
    print("❌ Failed to send Telegram message:", str(e))
    raise
