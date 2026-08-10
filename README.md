# MyTradeReview

A reusable PyCharm/Tkinter application for reviewing day trades against 1-minute WINFUT and WDOFUT market data.

The purpose of the program is not simply to label trades as winners or losers. It is designed to make each trade easy to inspect in its market context so you can distinguish entry problems, stop/management problems, exit problems, and possible overtrading/re-entry behaviour.

## Main features

### Trade table

The main window reads the Profit operations export and shows all completed trades in a sortable/filterable table, including:

- Date and entry time
- Contract
- Long / short
- Quantity
- Entry price
- Exit price
- Holding time
- P/L
- Running P/L for the day
- Trade number within the day
- Time since the previous trade
- Process grade
- Review tag

You can filter by instrument, result and review status.

Single-click a row to select/review it. Double-click a row to open its chart.

### Trade chart

Each chart is designed for a roughly 12 x 9 monitor window and shows:

- Up to 50 minutes of 1-minute data before entry
- The complete trade
- 10 bars after exit, where available
- 1-minute candlesticks
- Quantity volume
- RSI / IFR 14 in a thin panel above price
- RSI reference levels at 70 and 30
- MA 9
- MA 20
- MA 80
- Daily VWAP
- Current-session high and low as they were known at each minute
- Previous session high and low
- Entry and exit markers
- Entry and exit information boxes positioned away from the candles
- Approximate MFE and MAE horizontal levels over the trade
- A compact summary line with realised move, MFE, MAE, MA values, VWAP and capture of MFE

The price scale is deliberately kept tight around the visible candles so distant reference levels do not flatten the chart.

Vertical grid lines are shared between the RSI, price and volume panels so candles, time marks and volume bars line up visually.

### Previous / next trade navigation

Every chart has:

- `Previous trade`
- `Next trade`

You can also use the keyboard Left and Right arrow keys.

Navigation follows the current order of the table, including any filters and sorting you have applied. For example, if you filter to losing trades and sort by P/L, the chart arrows move through that displayed list rather than reverting to chronological order.

### Manual process review

For each trade you can save:

- Process grade
- Setup
- Primary mistake / behaviour tag
- Notes

These reviews are stored separately in:

```text
output/trade_reviews.csv
```

This means replacing the broker and market-data CSVs does not normally overwrite your manual reviews.

The intended distinction is important:

- A good trade can lose money.
- A poor trade can make money.

The purpose of the review fields is to judge the quality of the decision and management process, not merely the P/L outcome.

## Folder layout

```text
MyTradeReview/
    app.py
    charting.py
    config.py
    data_loader.py
    reviews.py
    stats.py
    requirements.txt
    README.md

    data/
        operations2026.csv
        WINFUT_F_0_1min.csv
        WDOFUT_F_0_1min.csv

    output/
        trade_reviews.csv
```

`.venv/` is normally also present locally after the PyCharm virtual environment is created, but it should not be committed to GitHub.

## PyCharm setup

Open the `MyTradeReview` folder as the project root.

Create a new local Virtualenv inside:

```text
MyTradeReview\.venv
```

A normal current Windows Python installation is suitable. The project has been used with Python 3.14.

After creating the environment, open the PyCharm Terminal and confirm that Python is coming from the project virtual environment:

```powershell
python -c "import sys; print(sys.executable)"
```

It should show a path similar to:

```text
F:\Documents\PyCharmProjects\GitHub\MyTradeReview\.venv\Scripts\python.exe
```

Install the required packages:

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Tkinter comes with the normal Windows Python installation and is therefore not installed through `pip`.

You can test Tkinter with:

```powershell
python -m tkinter
```

Then start the program with:

```powershell
python app.py
```

## Data files

The program expects three CSV files in `data/`:

```text
operations2026.csv
WINFUT_F_0_1min.csv
WDOFUT_F_0_1min.csv
```

The operations file is the Profit trade export.

The market files are 1-minute exports from Profit and must cover the dates of the trades you want to review.

The program reads the trade timestamps and automatically extracts only the relevant section of WIN or WDO data needed for each chart.

## Updating the data later

The project is intended to be reused continuously.

When you have newer trades:

1. Export an updated operations file from Profit.
2. Export/update the WINFUT 1-minute file.
3. Export/update the WDOFUT 1-minute file.
4. Replace the three CSVs in `data/` while keeping the same filenames.
5. Click `Reload files` in the program, or restart it.

If you prefer different filenames, change the file paths in `config.py`.

## Indicator calculations

### MA 9, MA 20 and MA 80

These are simple moving averages of the 1-minute closing price.

### RSI / IFR 14

The RSI panel uses a 14-period RSI calculation with reference lines at:

```text
70
30
```

It is intended as context rather than as an automatic trading signal.

### Daily VWAP

VWAP resets at the beginning of each trading session.

For each 1-minute bar the program uses typical price:

```text
(High + Low + Close) / 3
```

weighted by the `Quantity` field from the Profit export.

The cumulative daily VWAP is therefore:

```text
cumulative(TypicalPrice × Quantity) / cumulative(Quantity)
```

The chart is intended to display VWAP as a prominent thick yellow line so it is visually distinct from the moving averages.

### Session high / low

The current-day high and low are rolling values.

For example, a chart at 10:15 only shows the high and low that had occurred by 10:15. It does not use the eventual final high or low of the day.

This avoids introducing hindsight into the trade review.

### Previous-session high / low

These are calculated from the complete previous trading session contained in the 1-minute file.

## MFE and MAE

MFE = Maximum Favourable Excursion.

It measures the largest favourable price movement reached while the trade was open.

MAE = Maximum Adverse Excursion.

It measures the largest adverse movement reached while the trade was open.

The chart draws horizontal MFE and MAE levels across the operation and extends them a few bars to the right so they are easy to compare with the entry and exit.

### Important limitation

The operations file contains fill times to the second, while the market data is only 1-minute OHLC data.

Therefore MFE and MAE are approximate.

For example, the high of the 10:15 candle might have occurred at 10:15:05 while your trade entered at 10:15:45. One-minute data cannot determine that ordering.

Exact MFE/MAE would require tick-level market data.

## Volume panel

The lower panel currently plots Profit's `Quantity` field.

This provides a useful visual measure of activity and is also the weighting used for the daily VWAP calculation.

## Compact chart summary

The bottom of the chart is intentionally kept minimal.

It reports the most useful objective trade-management numbers, including:

- Realised price move
- MFE
- MAE
- MA 9
- MA 20
- MA 80
- VWAP
- Percentage of MFE captured

This keeps the chart focused on the actual price action rather than filling the window with text.

## Show Stats

The `Show stats` button provides summary analysis of the trade history, including comparisons such as:

- WIN vs WDO
- Long vs short
- Time of day
- Holding time
- Trade number within the day
- Time since the preceding trade
- Process grades
- Review tags

The statistical breakdown is intended to identify behaviours worth investigating. It should not automatically be interpreted as causation.

For example, if rapid re-entries perform badly, the next step is to inspect those trades to determine whether the issue was emotional re-entry, poor setup selection, market conditions, tight stops, or something else.

## Suggested trade-review routine

A useful order is:

1. Look at the chart without focusing on the P/L first.
2. Ask whether the entry was defensible using only information available at that moment.
3. Check the surrounding price structure.
4. Check MA 9, MA 20 and MA 80 context.
5. Check whether price was above, below or interacting with daily VWAP.
6. Check RSI context, but do not treat 70/30 mechanically as buy/sell signals.
7. Check current-day and previous-session high/low levels.
8. Examine MAE: did the trade immediately move against the entry?
9. Examine MFE: did the idea work before the trade eventually failed or was exited?
10. Compare the realised move with MFE to judge exit efficiency.
11. Check whether this was a rapid re-entry after the previous trade.
12. Assign a process grade and mistake/setup tag.
13. Add a short note only when it captures something useful that the objective fields do not.

The central question is:

> Was the trading decision and management good given what was knowable at the time?

That is more useful than simply asking whether the trade won or lost.

## GitHub

For a private GitHub repository, the following should normally be excluded in `.gitignore`:

```gitignore
.venv/
__pycache__/
*.pyc
.idea/

data/*.csv
output/*.csv
```

This keeps your local market data, actual trade history and personal review notes out of GitHub while still version-controlling the program itself.

## Files most likely to be edited

### `config.py`

Use this for file paths and general application settings.

### `charting.py`

Use this for chart appearance, indicators, colours, line thicknesses and layout.

### `data_loader.py`

Handles parsing and preparation of the operations and 1-minute market files.

### `stats.py`

Contains the summary analysis shown by `Show stats`.

### `reviews.py`

Handles saving/loading your manual review fields.

## Current aim of the project

The program is intended to answer questions such as:

- Are entries the main problem, or trade management?
- Are stops repeatedly too tight relative to normal MAE?
- Do winning ideas get exited too early relative to MFE?
- Are trades being taken in poor locations relative to VWAP and important session levels?
- Is performance different when MA structure is aligned with the trade?
- Are later trades in the day worse than earlier trades?
- Are rapid re-entries or repeated attempts causing avoidable losses?
- Are particular setups consistently good or bad?

The objective is to turn a large trade history into a practical, trade-by-trade review process rather than an abstract backtest.
