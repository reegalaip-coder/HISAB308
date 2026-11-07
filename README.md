# Expense bot (Telegram -> Google Sheets, runs on GitHub Actions)

Message the bot `woolworths 21.9` and it appends a row (Date, Description, Category, Cost, Currency)
to a monthly tab (e.g. `2026-11`) in your Google Sheet, then replies with a confirmation.

## One-time setup

### 1. Telegram bot
1. In Telegram, message **@BotFather** -> `/newbot` -> copy the **token**.

### 2. Google Sheet + service account
1. Create a blank Google Sheet. Copy its ID from the URL: `docs.google.com/spreadsheets/d/<SHEET_ID>/edit`.
2. Go to console.cloud.google.com -> create a project -> enable **Google Sheets API**.
3. IAM & Admin -> Service Accounts -> create one -> Keys -> Add key -> JSON. Download the file.
4. Open the Sheet -> Share -> paste the service account's email (`...@...iam.gserviceaccount.com`) as **Editor**.
5. In the Sheet: File -> Settings -> set Locale to **Australia** (so dates show as d/m/yyyy).

### 3. GitHub repo
1. Create a **private** repo and upload everything in this folder (keep `.github/workflows/bot.yml` at that path).
2. Settings -> Secrets and variables -> Actions -> New repository secret:
   - `TELEGRAM_TOKEN` = token from BotFather
   - `SHEET_ID` = the Sheet ID
   - `GOOGLE_CREDENTIALS` = paste the **entire contents** of the JSON key file
3. Actions tab -> enable workflows -> run **expense-bot** once with "Run workflow".
4. Message your bot anything. It replies with your chat ID. Add it as secret `ALLOWED_CHAT_ID`
   (this locks the bot so only you can use it). Run the workflow again.

## Using it
```
woolworths 21.9
bp wallsend 64.49
installment-51 1185 loan 3/11
tickets 53.35 general yesterday
/total        month total by category
/categories   list categories
```

## Notes
- GitHub Actions cron runs about every 5 minutes (sometimes later), so replies are not instant.
- Edit the `KEYWORDS` table at the top of `bot.py` to teach it your merchants.
- Scheduled workflows are paused after 60 days of repo inactivity on public repos; a private repo is fine, or just re-enable it.
