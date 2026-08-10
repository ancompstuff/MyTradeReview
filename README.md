# My Trading Journal

A personal desktop trading journal for reviewing WINFUT and WDOFUT day trades from Nelogica Profit exports.

The program keeps a permanent master history of your trades and 1-minute market data, lets you review each operation on its surrounding chart, classify the quality of your process, draw/write directly on charts, and save annotated journal images.

## What the journal shows

The main table contains your completed trades with:

- Date and exact entry time
- Contract
- Long / short
- Quantity
- Entry and exit prices
- Holding time
- P/L
- Cumulative P/L after the trade
- Trade number within that day
- Time since the previous trade
- Process grade
- Primary review tag

Double-click a trade (or select it and click **Open selected chart**) to open its chart.

## Trade chart

Each chart contains:

- Up to 50 minutes of 1-minute candles before entry, without carrying in the previous trading day
- The full trade
- 10 bars after exit, where available
- Quantity volume aligned vertically with the candles
- RSI/IFR 14 in a thin upper band, with 70 and 30 lines
- MA 9
- MA 20
- MA 80
- Daily VWAP (thick yellow/gold line)
- Current-session high/low known at each point in time
- Previous session high/low
- Entry and exit markers
- MFE and MAE levels across the operation
- Realized move, MFE, MAE, MA9, MA20, MA80, VWAP and capture of MFE

The previous/next buttons and the keyboard Left/Right arrows move through the **current order of the table**, so filtering or sorting the table also changes the sequence you review.

### MFE / MAE limitation

Trade fills contain seconds, while the market data contains 1-minute OHLC bars. Therefore MFE and MAE are approximate when an extreme occurs inside the entry or exit minute: the data cannot prove whether that high/low occurred before or after the fill within the minute.

## Visual chart journal

Every chart has an annotation toolbar:

- **Text** — click Text, then click the price chart and type a comment
- **Pen** — click Pen, then click-drag to draw freehand
- **Arrow** — click Arrow, click the start point, then click the end point
- **Undo** — removes the most recent annotation for that trade
- **Clear** — removes all annotations for that trade after confirmation
- **Hide annotations / Show annotations** — switches between clean and annotated chart views
- **Save PNG** — saves the current chart to `output/charts/`

Annotations are saved automatically to:

`journal/chart_annotations.json`

They reappear automatically whenever you reopen that trade.

Saved PNGs are named using the trade date/time, instrument, direction and trade ID so they remain identifiable later.

## Structured trade review

The main window also keeps a structured review for every trade:

- Process grade
- Setup
- Primary mistake/tag
- Free-form notes

This is deliberately separate from chart drawings. The structured fields can later be analyzed statistically; the visual annotations capture what you actually saw on the chart.

A useful principle is to grade the **decision/process**, not merely whether the trade made money. A well-executed trade can lose, and a poor trade can make money.

## Adding new trades and market data

This version is designed as a continuing journal rather than a one-off 2026 report.

Click **Import new data** in the main window. You can select any combination of:

1. A newer Profit operations/trades CSV
2. A newer WINFUT 1-minute CSV
3. A newer WDOFUT 1-minute CSV

Leave any row blank if you are not updating that file on this occasion.

### You can update whenever you want

For example:

- every trading day
- once a week
- once a month

There is no need to import every day.

### Overlapping exports are safe

The newer file does **not** have to contain only new rows.

If a new operations export contains all of your old trades plus today's trades, import the whole file. Existing trades are recognized by their stable trade ID and ignored; only genuinely new operations are added.

WIN/WDO market bars are similarly deduplicated by their 1-minute timestamp.

After an import, daily trade numbering, day P/L and time-since-previous-trade fields are recalculated over the complete journal.

## Permanent journal files

The `journal/` directory is the important long-term data store:

- `trades_master.csv` — master list of imported operations
- `WIN_1min_master.csv` — accumulated WIN 1-minute history
- `WDO_1min_master.csv` — accumulated WDO 1-minute history
- `trade_reviews.csv` — process grades, setups, tags and notes
- `chart_annotations.json` — text, arrows and pen drawings

The original CSVs in `data/` are only source/import files. Once the master journal has been created, replacing or deleting an old source export does not delete previously imported journal records.

**Back up the entire `journal/` folder.** It is your actual journal.

## First run after upgrading from the earlier MyTradeReview

Keep your existing project and current `data/` files.

On first launch, the new version automatically creates the master journal from the current:

- `data/operations2026.csv`
- `data/WINFUT_F_0_1min.csv`
- `data/WDOFUT_F_0_1min.csv`

If an older `output/trade_reviews.csv` exists and the new journal does not already contain reviews, it is copied into the new journal automatically.

## PyCharm setup

Your project should look approximately like:

```text
MyTradeReview/
    app.py
    annotations.py
    charting.py
    config.py
    data_loader.py
    journal_store.py
    reviews.py
    stats.py
    requirements.txt
    README.md
    data/
        operations2026.csv
        WINFUT_F_0_1min.csv
        WDOFUT_F_0_1min.csv
    journal/
        ... created automatically ...
    output/
        charts/
```

The virtual environment should normally be:

```text
MyTradeReview\.venv\Scripts\python.exe
```

Install requirements from the PyCharm terminal:

```powershell
python -m pip install -r requirements.txt
```

Run:

```powershell
python app.py
```

## Files required from Profit

### Operations file

The reader expects a Profit operations export containing fields such as:

- Ativo
- Abertura
- Fechamento
- Lado
- Preço Compra
- Preço Venda
- Res. Operação
- quantities, where available

`C` is interpreted as a long operation and `V` as a short operation.

### 1-minute market exports

WIN and WDO files should contain 1-minute data corresponding to the trade dates. The reader uses the first nine Profit export fields as:

- Asset
- Date
- Time
- Open
- High
- Low
- Close
- Volume
- Quantity

## Indicators

### Moving averages

MA9, MA20 and MA80 are simple moving averages of the 1-minute closing price over the complete chronological market series.

### Daily VWAP

Daily VWAP resets each session and is calculated cumulatively using:

```text
Typical price = (High + Low + Close) / 3
VWAP = cumulative(Typical price × Quantity) / cumulative(Quantity)
```

Only bars up to the current point in the session contribute to that point's VWAP.

### Current-day high/low

The day high/low lines are cumulative levels known **at that time**, not the eventual final high and low of the day. This avoids introducing hindsight into entry review.

## Recommended journal workflow

A practical review session is:

1. Filter the table to the trades you want to study.
2. Open the first chart.
3. Judge whether the entry idea was sensible with the information available at that moment.
4. Inspect location relative to VWAP, moving averages, RSI, session levels and recent price structure.
5. Compare realized move with MFE and MAE.
6. Add text/arrows/pen marks showing what you noticed.
7. Save the structured process grade/tag/notes.
8. Save a PNG when the annotated chart is worth keeping as an example.
9. Press Right Arrow or **Next trade**.

Over time, the structured reviews can be compared with P/L, holding time, trade number, re-entry gap, instrument, direction and other objective fields to identify recurring behaviors rather than relying on memory.

## GitHub and privacy

Your code can live on GitHub, but your personal trades and chart journal should generally stay local.

The supplied `.gitignore` excludes the persistent journal, CSV market/trade exports and generated chart images.

Back up the `journal/` folder separately to a private location you control.

## Confirmed MFE / MAE with 1-minute data

The journal deliberately uses **confirmed** MFE and MAE rather than pretending that the intrabar sequence is known.

The definitions are:

- Long trade: confirmed MFE = highest price confirmed while the position was open minus entry price; confirmed MAE = entry price minus lowest price confirmed while the position was open.
- Short trade: confirmed MFE = entry price minus lowest price confirmed while the position was open; confirmed MAE = highest price confirmed while the position was open minus entry price.

Because the source market files contain 1-minute OHLC bars but trade fills include seconds, the program cannot know whether the high or low of a partially held entry/exit candle occurred before entry, during the trade, or after exit. To avoid false precision, it uses:

1. the actual entry price;
2. the actual exit price; and
3. the high/low of any 1-minute candle whose **entire one-minute interval** was inside the trade.

It does **not** use the whole entry or exit candle when only part of that candle was held. This means confirmed MFE/MAE can understate the true excursion, but it will not attribute a pre-entry or post-exit candle extreme to the trade. Exact MFE/MAE would require tick or Times & Trades data covering the exact entry-to-exit timestamps.
