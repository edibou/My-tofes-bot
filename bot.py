#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
בוט טלגרם לבניית טופס כדורגל.
מושך משחקים ויחסים אמיתיים של היום מ-API-Football (תוכנית חינם),
ובונה טופס לפי רמת סיכון, סכום ויחס שהמשתמש בוחר.

פרויקט להנאה/לימוד בלבד — אין באפשרות אף בוט לחזות תוצאות ספורט.
אל תסתמך על זה כדי להמר כסף אמיתי.
"""

import os
import logging
import random
from datetime import date

import requests

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)

# ------------------------------------------------------------------
# מפתחות — מוגדרים כמשתני סביבה (מוסבר במדריך ההרצה)
#   BOT_TOKEN        = הטוקן מ-BotFather
#   FOOTBALL_API_KEY = המפתח מ-API-Football (dashboard.api-football.com)
# ------------------------------------------------------------------
BOT_TOKEN = os.environ.get("BOT_TOKEN", "PASTE-YOUR-TELEGRAM-TOKEN")
FOOTBALL_API_KEY = os.environ.get("FOOTBALL_API_KEY", "")

API_BASE = "https://v3.football.api-sports.io"
API_HEADERS = {"x-apisports-key": FOOTBALL_API_KEY}

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
log = logging.getLogger(__name__)

# רשימת גיבוי אם אין מפתח API או אם השליפה נכשלה
FALLBACK_GAMES = [
    {"home": "מכבי חיפה", "away": "הפועל באר שבע", "odds": {"1": 1.7, "X": 3.4, "2": 4.5}},
    {"home": "ריאל מדריד", "away": "ברצלונה", "odds": {"1": 2.1, "X": 3.5, "2": 3.2}},
    {"home": "מנצ'סטר סיטי", "away": "ליברפול", "odds": {"1": 1.9, "X": 3.6, "2": 3.8}},
    {"home": "באיירן מינכן", "away": "דורטמונד", "odds": {"1": 1.5, "X": 4.2, "2": 5.0}},
    {"home": "יובנטוס", "away": "אינטר", "odds": {"1": 2.6, "X": 3.1, "2": 2.7}},
    {"home": "ארסנל", "away": "צ'לסי", "odds": {"1": 2.0, "X": 3.4, "2": 3.6}},
    {"home": "פ.ס.ז'", "away": "מארסיי", "odds": {"1": 1.4, "X": 4.5, "2": 6.0}},
    {"home": "נאפולי", "away": "רומא", "odds": {"1": 2.2, "X": 3.2, "2": 3.3}},
]

# מצבי השיחה
RISK, AMOUNT, ODDS = range(3)


# ------------------------------------------------------------------
# שליפת משחקים ויחסים אמיתיים מ-API-Football
# ------------------------------------------------------------------
def fetch_today_games(max_games=25):
    if not FOOTBALL_API_KEY:
        return None
    try:
        today = date.today().isoformat()
        r = requests.get(
            f"{API_BASE}/fixtures",
            headers=API_HEADERS,
            params={"date": today},
            timeout=15,
        )
        r.raise_for_status()
        fixtures = r.json().get("response", [])
        if not fixtures:
            return None

        upcoming = [
            f for f in fixtures
            if f.get("fixture", {}).get("status", {}).get("short") in ("NS", "TBD")
        ]
        chosen = (upcoming or fixtures)[:max_games]

        games = []
        for f in chosen:
            teams = f.get("teams", {})
            home = teams.get("home", {}).get("name")
            away = teams.get("away", {}).get("name")
            fid = f.get("fixture", {}).get("id")
            if not home or not away:
                continue
            odds = fetch_odds_for_fixture(fid)
            games.append({"home": home, "away": away, "odds": odds})
        return games or None
    except Exception as e:
        log.warning("fetch_today_games failed: %s", e)
        return None


def fetch_odds_for_fixture(fixture_id):
    if not fixture_id:
        return None
    try:
        r = requests.get(
            f"{API_BASE}/odds",
            headers=API_HEADERS,
            params={"fixture": fixture_id, "bet": 1},  # bet=1 => Match Winner (1X2)
            timeout=15,
        )
        r.raise_for_status()
        resp = r.json().get("response", [])
        if not resp:
            return None
        bookmakers = resp[0].get("bookmakers", [])
        if not bookmakers:
            return None
        bets = bookmakers[0].get("bets", [])
        if not bets:
            return None
        values = bets[0].get("values", [])
        odds = {}
        for v in values:
            val = v.get("value")
            if val == "Home":
                odds["1"] = float(v.get("odd"))
            elif val == "Draw":
                odds["X"] = float(v.get("odd"))
            elif val == "Away":
                odds["2"] = float(v.get("odd"))
        return odds or None
    except Exception as e:
        log.warning("fetch_odds failed for %s: %s", fixture_id, e)
        return None


# ------------------------------------------------------------------
# לוגיקת בניית הטופס
# ------------------------------------------------------------------
def build_coupon(games, risk_pct, target_odds):
    risk = max(0, min(100, risk_pct))

    n_games = 3 + round((risk / 100) * 5)   # 3 עד 8 משחקים
    n_games = min(n_games, len(games))
    chosen = random.sample(games, n_games)

    fav_bias = 1 - (risk / 100)

    picks = []
    est_odds = 1.0
    for g in chosen:
        odds = g.get("odds") or {"1": 1.8, "X": 3.4, "2": 4.0}
        by_odds = sorted(odds.items(), key=lambda kv: kv[1])
        favorite = by_odds[0]

        if random.random() < fav_bias * 0.8:
            sign, leg = favorite
        else:
            sign, leg = random.choice(by_odds[1:]) if len(by_odds) > 1 else favorite

        picks.append((f"{g['home']} - {g['away']}", sign, round(leg, 2)))
        est_odds *= leg

    est_odds = round(est_odds, 2)

    note = ""
    if target_odds > 0:
        if est_odds < target_odds * 0.7:
            note = "היחס המשוער נמוך מהיעד שלך — נסה להעלות את רמת הסיכון."
        elif est_odds > target_odds * 1.5:
            note = "היחס המשוער גבוה מהיעד שלך — נסה להוריד את רמת הסיכון."

    return picks, est_odds, note


def format_coupon(picks, amount, est_odds, target_odds, note, source_label):
    lines = ["🎫 *הטופס שלך*", f"_{source_label}_", ""]
    for i, (game, sign, leg) in enumerate(picks, 1):
        lines.append(f"{i}. {game}  →  *{sign}*  (יחס {leg})")
    lines.append("")
    lines.append(f"💰 סכום: {amount:g} ₪")
    lines.append(f"📈 יחס משוער לטופס: *~{est_odds}*")
    lines.append(f"🏆 זכייה פוטנציאלית: ~{round(amount * est_odds, 2):g} ₪")
    if target_odds > 0:
        lines.append(f"🎯 יחס שביקשת: {target_odds:g}")
    if note:
        lines += ["", f"ℹ️ {note}"]
    lines += ["", "_להנאה בלבד. אין דרך לחזות תוצאות ספורט — אל תסתמך על זה בכסף אמיתי._"]
    return "\n".join(lines)


# ------------------------------------------------------------------
# זרימת השיחה
# ------------------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "היי! אני בונה טופס כדורגל ממשחקים אמיתיים של היום.\n\n"
        "שלח /new כדי להתחיל טופס חדש."
    )


async def new_coupon(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [
            InlineKeyboardButton("🟢 נמוך (20%)", callback_data="20"),
            InlineKeyboardButton("🟡 בינוני (50%)", callback_data="50"),
        ],
        [
            InlineKeyboardButton("🟠 גבוה (75%)", callback_data="75"),
            InlineKeyboardButton("🔴 מקסימלי (95%)", callback_data="95"),
        ],
    ]
    await update.message.reply_text(
        "מה רמת הסיכון שאתה רוצה בטופס?",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return RISK


async def risk_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["risk"] = int(query.data)
    await query.edit_message_text(
        f"רמת סיכון: {query.data}%\n\nכמה כסף אתה רוצה לשים? (שלח מספר, למשל 50)"
    )
    return AMOUNT


async def amount_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().replace("₪", "").replace(",", "")
    try:
        amount = float(text)
        if amount <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("לא הבנתי את הסכום. שלח מספר חיובי, למשל 50.")
        return AMOUNT
    context.user_data["amount"] = amount
    await update.message.reply_text(
        "בערך איזה יחס (מכפיל) אתה רוצה לקבל על הכסף?\n"
        "לדוגמה: 5 = פי 5. אם לא משנה לך, שלח 0."
    )
    return ODDS


async def odds_chosen(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().replace("x", "").replace("X", "")
    try:
        target = float(text)
        if target < 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("לא הבנתי את היחס. שלח מספר, למשל 5 (או 0 אם לא משנה).")
        return ODDS

    await update.message.reply_text("שולף משחקים של היום… רגע ⏳")

    games = fetch_today_games()
    if games:
        source_label = f"משחקים אמיתיים של היום ({date.today().isoformat()})"
    else:
        games = FALLBACK_GAMES
        source_label = "רשימת גיבוי (לא נשלפו משחקי היום — בדוק מפתח API)"

    risk = context.user_data["risk"]
    amount = context.user_data["amount"]
    picks, est_odds, note = build_coupon(games, risk, target)
    msg = format_coupon(picks, amount, est_odds, target, note, source_label)

    await update.message.reply_text(msg, parse_mode="Markdown")
    await update.message.reply_text("רוצה עוד טופס? שלח /new.")
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("בוטל. שלח /new כדי להתחיל מחדש.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


def main():
    app = Application.builder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("new", new_coupon)],
        states={
            RISK: [CallbackQueryHandler(risk_chosen)],
            AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, amount_chosen)],
            ODDS: [MessageHandler(filters.TEXT & ~filters.COMMAND, odds_chosen)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv)

    print("Bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()
