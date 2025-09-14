import os
import json
import logging
import gspread
from google.oauth2.service_account import Credentials
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# Logging for debugging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)

# === Load environment variables ===
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_ID = os.getenv("TELEGRAM_ID")
SHEET_ID = os.getenv("SHEET_ID")
GOOGLE_CREDENTIALS_JSON = os.getenv("GOOGLE_CREDENTIALS_JSON")

if not TELEGRAM_TOKEN or not TELEGRAM_ID or not SHEET_ID or not GOOGLE_CREDENTIALS_JSON:
    raise ValueError("❌ Missing one or more required environment variables.")

# === Google Sheets auth ===
creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
creds = Credentials.from_service_account_info(
    creds_dict,
    scopes=[
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ],
)
client = gspread.authorize(creds)

# Open sheet
sheet = client.open_by_key(SHEET_ID).sheet1


# === Telegram bot commands ===
async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check if bot is alive."""
    if str(update.effective_user.id) != TELEGRAM_ID:
        return  # Ignore anyone except you
    await update.message.reply_text("🫡 Systems Online | Bot is running.")


async def get_row(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Test: fetch first row from Google Sheet."""
    if str(update.effective_user.id) != TELEGRAM_ID:
        return
    row = sheet.row_values(1)
    await update.message.reply_text(f"📊 First row: {row}")


# === Main ===
def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("ping", ping))
    app.add_handler(CommandHandler("row", get_row))

    logging.info("✅ Co-Pilot online. Listening...")
    app.run_polling()


if __name__ == "__main__":
    main()
