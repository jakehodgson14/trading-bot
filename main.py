import os
import base64
import json
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import telebot

# Load environment variables
creds_b64 = os.getenv("GOOGLE_CREDENTIALS_B64")
sheet_id = os.getenv("SHEET_ID")
telegram_token = os.getenv("TELEGRAM_TOKEN")
telegram_id = os.getenv("TELEGRAM_ID")

# Decode Google credentials
creds_json = base64.b64decode(creds_b64).decode("utf-8")
creds_dict = json.loads(creds_json)

scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
client = gspread.authorize(creds)

# Connect to sheet
sheet = client.open_by_key(sheet_id)
worksheet = sheet.sheet1

# Telegram bot setup
bot = telebot.TeleBot(telegram_token)

# Example startup message
bot.send_message(telegram_id, "🟢 Co-Pilot system online and connected to Google Sheets.")

# Simple polling loop to keep bot alive
@bot.message_handler(commands=["status"])
def status(message):
    bot.send_message(telegram_id, "✅ System is running and connected.")

bot.polling(none_stop=True)
