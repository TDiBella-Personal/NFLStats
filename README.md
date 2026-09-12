# NFLStats

NFL comparison matrix on GitHub Pages. Entities across, stats down, splits on tap. Free data from nflverse, refreshed daily by a GitHub Action.

## Setup
1. Create a **public** repo, push this.
2. Settings > Pages > Source: Deploy from branch `main`, folder `/ (root)`.
3. Actions tab > "pull nfl data" > Run workflow. First run seeds `data/`.
4. Open `https://tdibella-personal.github.io/NFLStats/`.

## Using it
- Theme swatches top right: Colts, Slate, Broadcast, Turf, Paper. Remembered on this device.
- Players / Teams switches the matrix type. Switching clears it.
- Search: a player name, or a team name to browse its roster. Position chips narrow results. Tap a result to add a column.
- Teams mode: pick a week and tap a game in the strip to add both teams.
- Totals / Per game switches every cell at once. Records (W-L, ATS, overs) always show as records.
- Tap a stat name to open it. Split chips appear right under it: home/away, division, opponent defense, fav/dog, rest, roof. Tap the name again to close.
- Bold is the best value in the row. Lower-is-better stats (interceptions, points allowed, efficiency) flip that.
- Next Gen Stats section: rush yards over expected, time to throw, separation, cushion, and more. A dash means NGS didn't publish a number (minimum attempts not met), not zero.
- Hover or long-press a stat name for a one-line definition where it isn't obvious.
- The x on a column header removes it. The URL hash holds the matrix, so bookmark a comparison.
- Copy JSON puts the matrix, with splits, on the clipboard for pasting into Claude.

## Data
- `data/meta.json` season, current week, timestamp
- `data/schedule.json` games by week with spread, total, implied totals
- `data/teams.json` per-team stats with splits, plus name, colors, and logo URL from nflverse
- `data/players.json` QB/RB/WR/TE stats with splits, including Next Gen Stats (`ngs_` keys)

Stat shape: `{"t": total, "g": games, "s": {"home": [total, games], ...}}`. Per-game = t/g.
Splits: home/away, div/nondiv, opp_top/mid/bot (opponent D by points allowed), fav/dog, rest_short/norm/long, dome/outdoor.

## Local run
    pip install -r scripts/requirements.txt
    python scripts/pull.py            # auto-detects season, falls back to last season until stats exist
    SEASON=2025 python scripts/pull.py
