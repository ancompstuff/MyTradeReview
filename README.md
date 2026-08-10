# My Trade Review

A small reusable PyCharm/Tkinter program for reviewing Profit day trades against 1-minute WINFUT and WDOFUT data.

## What it does

- Reads the Profit operations export automatically, including the metadata lines above the real table.
- Reconstructs the true entry/exit price from `Lado` (`C` = long, `V` = short).
- Shows every trade in a sortable/filterable table.
- Double-click any trade to open a **12 x 9** candle chart.
- Chart starts up to **50 minutes before entry** (never pulls in the previous day) and ends **10 bars after exit**, where available.
- Plots:
  - 1-minute candles
  - Quantity volume
  - MA 9 and MA 20
  - rolling current-session high and low **known at that minute**
  - previous session high and low
  - exact entry and exit markers using the seconds in the trade export
- Shows objective review information: approximate MFE/MAE, realised move, capture of favourable excursion, MA alignment, day/previous-session context, trade number in the day, P/L before the trade, and time since the previous trade.
- Saves your own process grade, setup, mistake tag and notes to `output/trade_reviews.csv`.
- `Show stats` summarizes performance by instrument, side, time of day, holding time, trade number in the day, re-entry gap, and your own review grades/tags.

## Folder layout

```
MyTradeReview/
    app.py
    charting.py
    config.py
    data_loader.py
    reviews.py
    stats.py
    requirements.txt
    data/
        operations2026.csv
        WINFUT_F_0_1min.csv
        WDOFUT_F_0_1min.csv
    output/
        trade_reviews.csv   # created after your first saved review
```

## First run in PyCharm

1. Open the `MyTradeReview` folder as a PyCharm project.
2. Create/select a normal Python interpreter (Python 3.11, 3.12 or 3.13 are fine).
3. Open PyCharm Terminal and run:

   ```bash
   pip install -r requirements.txt
   ```

4. Run `app.py`.

Tkinter is included with the normal Windows Python installer, so it is not listed in `requirements.txt`.

## Updating it later

The program is deliberately file-based. When you export newer data:

1. Replace `data/operations2026.csv` with the new operations export.
2. Replace/update `data/WINFUT_F_0_1min.csv` and `data/WDOFUT_F_0_1min.csv` with 1-minute files covering the new trades.
3. Keep the same filenames, then click **Reload files** or restart the program.

Your manual reviews are separate in `output/trade_reviews.csv`, keyed to a stable trade ID, so replacing the broker export does not normally wipe your previous notes.

If you prefer different filenames, edit only the three paths near the top of `config.py`.

## Important interpretation notes

### 1. Today's high/low is not hindsight
The chart uses a rolling high and low for the session. At 10:15, for example, it shows only the high/low that had actually occurred by 10:15. Plotting the final high or low of the full day on an earlier trade would make the review look easier than it really was.

### 2. Previous session high/low
These use the complete previous trading session in the 1-minute file.

### 3. MFE and MAE are approximate
The operations file has fills to the second, but the market data is only 1-minute OHLC. The high or low of the entry/exit minute may have occurred before your entry or after your exit. The chart therefore labels these measures as approximate. For exact excursion analysis you would need tick data.

### 4. Quantity vs financial volume
The lower panel uses the Profit `Quantidade` column because it is an intuitive contract/activity measure and is less distorted by price level than financial volume. You can change this to `Volume` in `charting.py` if you prefer.

## Suggested review routine

For each trade, try to answer in this order:

1. **Was the entry decision defensible with only information available then?**
2. Was the trade with or against the MA9/MA20 structure?
3. Was entry at a useful location relative to the known session high/low or previous session levels, or was it in the middle of nowhere?
4. Did the market first move meaningfully in your favour (MFE) before the loss, suggesting stop/management may be the issue?
5. Did it move heavily against you immediately (MAE), suggesting the entry itself may be the issue?
6. Did you take only a small fraction of a large favourable move, suggesting an exit-management issue?
7. Was this a rapid re-entry after another trade? If so, was there genuinely new information, or were you reacting emotionally to the last result?
8. Grade the **process**, not the money. A losing A-grade trade is possible; so is a winning D-grade trade.

The purpose of the tags is not to diagnose you automatically. After you have reviewed a meaningful sample, `Show stats` can reveal whether particular behaviours recur and whether they are actually associated with poor results.
