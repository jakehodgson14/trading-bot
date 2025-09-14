#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Early test-ready Co-Pilot master script (Render/Web Service friendly).
"""

import os
import json
import time
import logging
import threading
from datetime import datetime
import pytz

import pandas as pd
import numpy as np
import yfinance as yf
import gspread
from google.oauth2 import service_account
from telegram import Bot, Update, ParseMode
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
SHEET_ID = os.environ.get("SHEET_ID", "").strip()
GOOGLE_CREDS = os.environ.get("GOOGLE_CREDS", "").strip()
ALLOWED_USER_ID = 7010825012
TZ = pytz.timezone("Europe/London")

TAB_COCKPIT = "Cockpit"
TAB_DASHBOARD = "Dashboard"
TAB_FAILSAFE = "FailSafe_Log"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("copilot")

def get_gspread_client():
    info = json.loads(GOOGLE_CREDS)
    creds = service_account.Credentials.from_service_account_info(
        info,
        scopes=[
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ],
    )
    return gspread.authorize(creds)

def open_sheet():
    gc = get_gspread_client()
    return gc.open_by_key(SHEET_ID)

def now_uk():
    return datetime.now(TZ)

def update_prices_and_pl(sh):
    ws = sh.worksheet(TAB_COCKPIT)
    rows = ws.get_all_values()
    if not rows or len(rows) < 2:
        return
    headers = rows[0]
    tick_idx = headers.index("Ticker")
    entry_idx = headers.index("Entry Price")
    shares_idx = headers.index("Shares")
    curr_idx = headers.index("Current Price")
    amt_idx = headers.index("Amount Invested")
    pl_gbp_idx = headers.index("P/L (£)")
    pl_pct_idx = headers.index("P/L (%)")

    total_invested = 0.0
    current_value_total = 0.0
    for r, row in enumerate(rows[1:], start=2):
        ticker = row[tick_idx].strip()
        if not ticker:
            continue
        try:
            entry = float(row[entry_idx])
            shares = float(row[shares_idx])
            invested = float(row[amt_idx])
        except:
            continue
        try:
            yt = yf.Ticker(ticker)
            hist = yt.history(period="1d")
            price = float(hist["Close"].iloc[-1]) if not hist.empty else entry
        except:
            price = entry
        current_value = shares * price if shares else 0.0
        if not invested and shares and entry:
            invested = shares * entry
        pl_gbp = current_value - invested
        pl_pct = (pl_gbp / invested * 100.0) if invested else 0.0
        total_invested += invested
        current_value_total += current_value
        ws.update_cell(r, curr_idx+1, round(price, 2))
        ws.update_cell(r, pl_gbp_idx+1, round(pl_gbp, 2))
        ws.update_cell(r, pl_pct_idx+1, round(pl_pct, 2))

    total_pl_gbp = current_value_total - total_invested
    total_pl_pct = (total_pl_gbp / total_invested * 100.0) if total_invested else 0.0
    ws_dash = sh.worksheet(TAB_DASHBOARD)
    ws_dash.update("A2:D2", [[round(total_invested,2), round(current_value_total,2), round(total_pl_gbp,2), round(total_pl_pct,2)]])

def send_safe(bot: Bot, text: str):
    try:
        bot.send_message(chat_id=ALLOWED_USER_ID, text=text, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        log.warning("Telegram send failed: %s", e)

def cmd_start(update: Update, context: CallbackContext):
    send_safe(context.bot, "🫡 Co-Pilot online. Use /ping, /dashboard, /report")

def cmd_ping(update: Update, context: CallbackContext):
    send_safe(context.bot, f"🫡 Systems Online | Time: {now_uk().strftime('%H:%M:%S %Z')}")

def cmd_dashboard(update: Update, context: CallbackContext):
    sh = open_sheet()
    ws = sh.worksheet(TAB_DASHBOARD)
    vals = ws.get_all_values()
    if len(vals) >= 2 and len(vals[1]) >= 4:
        invested, cur, pl_gbp, pl_pct = vals[1][:4]
        msg = f"📊 Portfolio Totals\nTotal Invested: £{invested}\nCurrent Value: £{cur}\nTotal P/L: £{pl_gbp} ({pl_pct}%)"
    else:
        msg = "📊 Dashboard not ready yet."
    send_safe(context.bot, msg)

def cmd_report(update: Update, context: CallbackContext):
    sh = open_sheet()
    ws = sh.worksheet(TAB_COCKPIT)
    rows = ws.get_all_values()
    if len(rows) < 2:
        send_safe(context.bot, "No trades in Cockpit yet.")
        return
    headers = rows[0]
    tick_idx = headers.index("Ticker")
    curr_idx = headers.index("Current Price")
    pl_idx = headers.index("P/L (%)")
    lines = ["📋 *Active Trades (top 10)*"]
    for r in rows[1:11]:
        if r[tick_idx]:
            lines.append(f"- {r[tick_idx]}: £{r[curr_idx]} | P/L {r[pl_idx]}%")
    send_safe(context.bot, "\n".join(lines))

def schedule_loop(bot: Bot):
    while True:
        try:
            sh = open_sheet()
            update_prices_and_pl(sh)
        except Exception as e:
            log.warning("Loop error: %s", e)
        time.sleep(300)

def main():
    bot = Bot(token=TELEGRAM_TOKEN)
    updater = Updater(token=TELEGRAM_TOKEN, use_context=True)
    dp = updater.dispatcher
    dp.add_handler(CommandHandler("start", cmd_start))
    dp.add_handler(CommandHandler("ping", cmd_ping))
    dp.add_handler(CommandHandler("dashboard", cmd_dashboard))
    dp.add_handler(CommandHandler("report", cmd_report))
    threading.Thread(target=schedule_loop, args=(bot,), daemon=True).start()
    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
