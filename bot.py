"""Telegram -> Google Sheets expense logger. Stateless: runs from GitHub Actions."""
import json, os, re, datetime as dt
from zoneinfo import ZoneInfo

import gspread
import requests
from google.oauth2.service_account import Credentials

TOKEN = os.environ["TELEGRAM_TOKEN"].strip()
SHEET_ID = os.environ["SHEET_ID"].strip()
ALLOWED = os.environ.get("ALLOWED_CHAT_ID", "").strip()
TZ = ZoneInfo("Australia/Sydney")
API = f"https://api.telegram.org/bot{TOKEN}"
HEADERS = ["Date", "Description", "Category", "Cost", "Currency"]
CURRENCY = "AUD"

CATEGORIES = [
    "LOAN", "GENERAL", "Groceries", "PATROL/CAR",
    "ELECTRICITY/Phone/Internet", "RECREATION", "TRANSPORT/ INSURANCE",
    "SAVING-INDIA", "HEALTH/MEDICAL",
]

# Keyword in description -> category (edit freely; whole-word match, case-insensitive)
KEYWORDS = {
    "WOOLWORTHS": "Groceries", "COLES": "Groceries", "ALDI": "Groceries",
    "COSTCO": "Groceries", "BIGW": "Groceries", "KAIRALI": "Groceries",
    "BP": "PATROL/CAR", "PEARL": "PATROL/CAR", "SERVICE": "PATROL/CAR",
    "SHELL": "PATROL/CAR", "AMPOL": "PATROL/CAR", "7ELEVEN": "PATROL/CAR",
    "PARKING": "TRANSPORT/ INSURANCE", "INSURANCE": "TRANSPORT/ INSURANCE",
    "OPAL": "TRANSPORT/ INSURANCE",
    "INSTALLMENT": "LOAN", "LOAN": "LOAN", "EMI": "LOAN",
    "CHEMIST": "HEALTH/MEDICAL", "CEHMIST": "HEALTH/MEDICAL",
    "DOCTOR": "HEALTH/MEDICAL", "GP": "HEALTH/MEDICAL",
    "CARLS": "RECREATION", "MCDONALDS": "RECREATION", "KFC": "RECREATION",
    "CINEMA": "RECREATION", "SAPPHIRE": "RECREATION",
    "ELECTRICITY": "ELECTRICITY/Phone/Internet", "INTERNET": "ELECTRICITY/Phone/Internet",
    "TELSTRA": "ELECTRICITY/Phone/Internet", "OPTUS": "ELECTRICITY/Phone/Internet",
    "INDIA": "SAVING-INDIA",
}

HELP = (
    "Send an expense like:\n"
    "  woolworths 21.9\n"
    "  bp wallsend 64.49 patrol\n"
    "  tickets 53.35 general 3/11   (optional date: d/m, d/m/yyyy or 'yesterday')\n\n"
    "Category is guessed from the description; add a category (or its first letters) after the amount to override.\n"
    "Commands: /categories  /total  /help"
)


def tg(method, **params):
    r = requests.post(f"{API}/{method}", data=params, timeout=30)
    r.raise_for_status()
    return r.json()


def reply(chat_id, text):
    tg("sendMessage", chat_id=chat_id, text=text)


def match_category(text):
    t = text.lower().strip()
    if not t:
        return None
    for c in CATEGORIES:
        if c.lower() == t:
            return c
    for c in CATEGORIES:
        if c.lower().startswith(t):
            return c
    for c in CATEGORIES:
        if t in c.lower():
            return c
    return None


def guess_category(desc):
    for kw, cat in KEYWORDS.items():
        if re.search(rf"\b{re.escape(kw)}\b", desc, re.I):
            return cat
    return "GENERAL"


def parse_date(tok, today):
    if tok.lower() == "yesterday":
        return today - dt.timedelta(days=1)
    if tok.lower() == "today":
        return today
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?", tok)
    if not m:
        return None
    d, mo, y = int(m[1]), int(m[2]), m[3]
    y = today.year if not y else (int(y) + 2000 if len(y) == 2 else int(y))
    try:
        return dt.date(y, mo, d)
    except ValueError:
        return None


def parse(text):
    today = dt.datetime.now(TZ).date()
    toks = text.replace(",", " ").split()
    amt_i = next((i for i, t in enumerate(toks) if re.fullmatch(r"\$?\d+(\.\d{1,2})?", t)), None)
    if amt_i is None:
        raise ValueError("I couldn't find an amount. Example: woolworths 21.9")
    cost = float(toks[amt_i].lstrip("$"))
    before, after = toks[:amt_i], toks[amt_i + 1:]
    if not before:               # "21.9 woolworths"
        before, after = after, []
    if not before:
        raise ValueError("Add a description. Example: woolworths 21.9")
    desc = " ".join(before).upper()

    date, cat_words = today, []
    for t in after:
        d = parse_date(t, today)
        if d:
            date = d
        else:
            cat_words.append(t)
    category = match_category(" ".join(cat_words)) if cat_words else None
    if cat_words and not category:
        raise ValueError(f"Unknown category '{' '.join(cat_words)}'. Send /categories to see them.")
    return date, desc, category or guess_category(desc), cost


def get_tab(sh, date):
    name = date.strftime("%Y-%m")           # one tab per month, e.g. 2026-11
    try:
        return sh.worksheet(name)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=name, rows=500, cols=8)
        ws.update(range_name="A1:E1", values=[HEADERS])
        ws.format("A1:E1", {"textFormat": {"bold": True}})
        ws.format("A:A", {"numberFormat": {"type": "DATE", "pattern": "d/m/yyyy"}})
        ws.freeze(rows=1)
        # Category dropdown for column C
        sh.batch_update({"requests": [{"setDataValidation": {
            "range": {"sheetId": ws.id, "startRowIndex": 1, "startColumnIndex": 2, "endColumnIndex": 3},
            "rule": {"condition": {"type": "ONE_OF_LIST",
                                   "values": [{"userEnteredValue": c} for c in CATEGORIES]},
                     "showCustomUi": True, "strict": False}}}]})
        return ws


def month_total(sh, date):
    ws = get_tab(sh, date)
    rows = ws.get_all_values()[1:]
    totals = {}
    for r in rows:
        if len(r) >= 4 and r[3]:
            try:
                totals[r[2]] = totals.get(r[2], 0) + float(r[3].replace(",", ""))
            except ValueError:
                pass
    lines = [f"{c}: ${v:,.2f}" for c, v in sorted(totals.items(), key=lambda x: -x[1])]
    return f"{date.strftime('%B %Y')} total: ${sum(totals.values()):,.2f}\n" + "\n".join(lines)


def main():
    creds = Credentials.from_service_account_info(
        json.loads(os.environ["GOOGLE_CREDENTIALS"]),
        scopes=["https://www.googleapis.com/auth/spreadsheets"])
    sh = gspread.authorize(creds).open_by_key(SHEET_ID)

    updates = tg("getUpdates", timeout=0, allowed_updates=json.dumps(["message"]))["result"]
    last = None
    for u in updates:
        last = u["update_id"]
        msg = u.get("message") or {}
        text = (msg.get("text") or "").strip()
        chat_id = msg.get("chat", {}).get("id")
        if not text or chat_id is None:
            continue
        if not ALLOWED:
            reply(chat_id, f"Setup: add ALLOWED_CHAT_ID = {chat_id} as a GitHub secret, then message me again.")
            continue
        if str(chat_id) != ALLOWED:
            continue
        try:
            cmd = text.split()[0].lower().split("@")[0]
            if cmd in ("/start", "/help"):
                reply(chat_id, HELP)
            elif cmd == "/categories":
                reply(chat_id, "\n".join(CATEGORIES))
            elif cmd == "/total":
                reply(chat_id, month_total(sh, dt.datetime.now(TZ).date()))
            else:
                date, desc, cat, cost = parse(text)
                get_tab(sh, date).append_row(
                    [date.isoformat(), desc, cat, cost, CURRENCY], value_input_option="USER_ENTERED")
                reply(chat_id, f"Added: {date.strftime('%-d/%-m/%Y')} | {desc} | {cat} | ${cost:,.2f} {CURRENCY}")
        except ValueError as e:
            reply(chat_id, str(e))
        except Exception as e:  # leave the update unacknowledged so it retries next run
            print("error:", e)
            last = u["update_id"] - 1
            break

    if last is not None:
        tg("getUpdates", offset=last + 1, timeout=0)   # acknowledge processed messages


if __name__ == "__main__":
    main()
