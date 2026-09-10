# NFLStats

Green-phosphor NFL comparison matrix on GitHub Pages. Free data from nflverse, refreshed daily by a GitHub Action.

## Setup
1. Create a **public** repo, push this.
2. Settings > Pages > Source: Deploy from branch `main`, folder `/ (root)`.
3. Actions tab > "pull nfl data" > Run workflow. First run seeds `data/`.
4. Open `https://tdibella-personal.github.io/NFLStats/`.

## Using it
- Status line shows season, current week, data timestamp. Amber note means 2026 stats aren't published yet and last season is showing.
- `players` / `teams` toggles the matrix type. Switching clears it.
- Command line: type a player name, a team (`colts`, `IND`) for a roster, or `wk 3` in teams mode for that week's games. Tap a result to add a column.
- Commands: `rm 2` removes column 2, `rm` removes the last, `clear`, `copy`, `teams`, `players`.
- Tap a stat row to split it. Pick home/away, division, opp D, fav/dog, rest, roof. Brightest value in each row is the best.
- Tap a column header to remove it.
- The URL hash holds the matrix, so bookmark or share a comparison.
- `copy json` puts the whole matrix, with splits, on the clipboard. Paste into Claude to dig.

## Data
- `data/meta.json` season, current week, timestamp
- `data/schedule.json` games by week with spread, total, implied totals
- `data/teams.json` per-team stats with splits
- `data/players.json` QB/RB/WR/TE stats with splits

Stat shape: `{"t": total, "g": games, "s": {"home": [total, games], ...}}`. Per-game = t/g.
Splits: home/away, div/nondiv, opp_top/mid/bot (opponent D by points allowed), fav/dog, rest_short/norm/long, dome/outdoor.

## Local run
    pip install -r scripts/requirements.txt
    python scripts/pull.py            # auto-detects season, falls back to last season until stats exist
    SEASON=2025 python scripts/pull.py
