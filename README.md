# MyTradeReview / My Trading Journal — OneNote edition

This version turns the existing Profit trade-review program into a persistent trading journal with optional Microsoft OneNote export.

## What the journal does

The desktop Python app remains the master data/analysis tool. It:

- imports Profit operations/trades CSV files;
- imports WINFUT 1-minute CSV files;
- imports WDOFUT 1-minute CSV files;
- merges later exports into persistent master files without duplicating already-imported trades or 1-minute bars;
- keeps process grades, setup labels, mistake tags and notes;
- opens the existing trade chart with RSI/IFR, volume, MA9, MA20, MA80, daily VWAP, current-session high/low, previous-session high/low, entry/exit and confirmed MFE/MAE;
- can export/update the journal in OneNote.

The normal recurring workflow is therefore:

1. Export the latest three CSV files from Profit.
2. Click **Import new data**.
3. Select whichever of the three files you are updating.
4. Leave **Update OneNote automatically after the import** ticked.
5. The master journal adds only genuinely new rows, then OneNote gets the new trade pages and refreshed daily/monthly summaries.

Overlapping exports are expected. For example, an operations CSV containing the whole of 2026 again is safe to import.

---

## OneNote structure

The exporter creates a notebook such as:

**My Trading Journal 2026**

Each month is a OneNote **Section Group**:

- `05 - May 2026`
- `06 - June 2026`
- etc.

Inside each month group:

- `00 - Monthly Summary` section
  - `Monthly Summary - 05 - May 2026` page
- one section for each trading day, e.g. `2026-05-08 - Fri`
  - `Daily Summary - 08/05/2026` page
  - `Trade 01 - WDOM26 - 09:14:15`
  - `Trade 02 - WDOM26 - 09:17:44`
  - etc.

The monthly and daily summary pages contain Profit-style performance statistics plus a table of trades.

Each trade page contains the generated chart. Use OneNote's own Draw, pen, highlighter, text and other tools to journal directly on/around the image.

### Important preservation rule

Trade pages are **create-only**. Once a trade has a OneNote page, later syncs do not overwrite it. This protects handwriting, ink and comments added in OneNote.

Monthly and daily **summary** pages are refreshed when you sync so totals and trade lists remain current.

---

## Confirmed MFE / MAE

The journal deliberately uses conservative **confirmed** MFE and MAE with 1-minute data.

The entry and exit prices are always included because those prices definitely occurred while the position existed.

A 1-minute candle high/low is used only when the complete candle interval was inside the exact entry-to-exit time. The entry and exit candles are not used wholesale if only part of those minutes was held.

This prevents a pre-entry low/high from being incorrectly labelled as MAE/MFE. Exact intrabar MFE/MAE would require tick data.

---

## First-time Python setup

From the PyCharm terminal, with the project's `.venv` active:

```powershell
python -m pip install -r requirements.txt
```

Then run:

```powershell
python app.py
```

Extra packages used by the OneNote integration are:

- `requests`
- `msal`
- `beautifulsoup4`

---

# One-time Microsoft / OneNote setup

The OneNote API requires the user to sign in. This desktop app uses Microsoft Authentication Library (MSAL) and delegated permissions. It does **not** use or store a client secret.

You need to create one Microsoft Entra app registration and paste its **Application (client) ID** into the journal.

## 1. Create the app registration

Open the Microsoft Entra admin center in your browser and create a new **App registration**.

For supported account types, choose the option that includes the Microsoft account you use with OneNote. If you use a personal Microsoft account, the registration must allow personal Microsoft accounts.

A suggested name is:

`MyTradeReview OneNote Journal`

## 2. Add desktop/mobile authentication

Under **Authentication**, add the **Mobile and desktop applications** platform / public-client configuration and add this redirect URI:

```text
http://localhost
```

If the registration has an **Allow public client flows** option, enable it for the desktop public-client application.

## 3. Add Microsoft Graph delegated permissions

Add delegated Microsoft Graph permissions:

```text
Notes.ReadWrite
User.Read
```

`Notes.ReadWrite` allows the signed-in user to read/write their OneNote notebooks. `User.Read` is used for normal signed-in-user access.

## 4. Copy the client ID

On the app registration Overview page copy:

**Application (client) ID**

It looks similar to:

```text
12345678-abcd-1234-abcd-1234567890ab
```

Do not create a client secret for this program.

## 5. Configure the journal

In the Python app click:

**OneNote setup**

Paste the client ID and choose the notebook name. The default authority is:

```text
https://login.microsoftonline.com/common
```

Then click **Save**.

## 6. First sync

Click:

**Update OneNote**

A Microsoft browser sign-in will appear. Sign in to the Microsoft account containing your OneNote notebooks and approve the requested permissions.

After successful sign-in, the authentication token cache is stored locally under `journal/` so later updates normally do not require a full sign-in again.

---

## Persistent files

The local journal uses:

```text
journal/
    trades_master.csv
    WIN_1min_master.csv
    WDO_1min_master.csv
    trade_reviews.csv
    chart_annotations.json
    onenote_settings.json
    onenote_token_cache.json
    onenote_sync.json
```

Back up the **journal** folder. It is the persistent database for this project.

`onenote_sync.json` records which local trade IDs correspond to which OneNote pages. Keeping this file prevents duplicate trade pages.

The entire `journal/` directory is intentionally excluded from Git by `.gitignore` because it contains personal trading data and authentication/cache information.

---

## Monthly/daily summary statistics

The generated summary pages include the principal metrics available from the operations CSV, including:

- result / P&L;
- gross profit;
- gross loss;
- profit factor;
- total trades;
- winners, losers and flat trades;
- winning percentage;
- average trade;
- average winner;
- average loser;
- average winner : average loser ratio;
- largest winner and loser;
- longest winning and losing streaks;
- average holding time;
- average winning/losing holding time;
- maximum contracts;
- peak-to-trough drawdown;
- largest one-trade decline.

The Profit operations CSV currently used by this project does not provide a per-operation brokerage/fees field from which the Profit report's **Custos** figure can be reconstructed reliably. OneNote therefore displays costs as unavailable rather than inventing a number.

---

## Updating the journal later

You do not need to replace files manually.

Click **Import new data** and choose:

- operations/trades export;
- WINFUT 1-minute export;
- WDOFUT 1-minute export.

You may select all three, or only the files that changed.

The importer uses stable trade IDs and timestamps to ignore duplicate trades/bars. New trades are added to the master journal. If automatic OneNote update is enabled, the app then:

1. creates any missing month section group;
2. creates any missing trading-day section;
3. creates OneNote pages only for new trades;
4. refreshes that day's summary;
5. refreshes that month's summary.

Existing OneNote trade pages are left alone so handwritten journal content remains intact.

---

## Git / branches

The source code can be committed to GitHub, but personal data should remain local.

The supplied `.gitignore` excludes:

```text
.venv/
.idea/
data/*.csv
journal/
output/charts/
```

If you are working on the `Annotable_journal` branch, check before committing:

```powershell
git branch --show-current
```

Then commit normally:

```powershell
git add .
git commit -m "Add OneNote trading journal export"
git push
```

---

## Files added for OneNote

- `onenote_export.py` — Microsoft Graph authentication, notebook hierarchy and sync.
- `onenote_settings.py` — local OneNote configuration.
- `journal_summary.py` — monthly/daily Profit-style statistics and HTML tables.
- `journal_chart_export.py` — generates clean chart PNGs for OneNote trade pages.

The existing desktop chart/review code remains available for analysis in PyCharm.
