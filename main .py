import os
import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import telebot

# --- Load Environment Variables ---
GOOGLE_CREDENTIALS_JSON = os.getenv("GOOGLE_CREDENTIALS_JSON")
SHEET_ID = os.getenv("SHEET_ID")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_ID = os.getenv("TELEGRAM_ID")

# --- Google Sheets Setup ---
creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
client = gspread.authorize(creds)
sheet = client.open_by_key(SHEET_ID).sheet1

# --- Telegram Setup ---
bot = telebot.TeleBot(TELEGRAM_TOKEN)

# --- Example Functionality ---
def send_update(message):
    bot.send_message(TELEGRAM_ID, f"📊 Update: {message}")

# --- Example Main Loop ---
if __name__ == "__main__":
    send_update("Bot is live and connected to Google Sheets!")
