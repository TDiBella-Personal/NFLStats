#!/usr/bin/env python3
"""
Pull current-season NFL data from nflverse and write JSON for the dashboard.

Outputs (in data/):
  meta.json      season, current week, data timestamp, source season note
  schedule.json  games by week with lines and implied totals
  teams.json     per-team season stats with splits
  players.json   per-player (QB/RB/WR/TE) season stats with splits

Stat schema (teams and players):
  "stats": { "<stat>": { "t": total, "g": games, "s": { "<split>": [total, games], ... } } }
Per-game averages are derived in the frontend (t / g).

Splits (all schedule-level, no play-by-play):
  home / away
  div / nondiv
  opp_top / opp_mid / opp_bot   opponent defense tier by points allowed per game
  fav / dog                     by closing spread
  rest_short / rest_norm / rest_long   <7 / 7 / >7 days
  dome / outdoor
"""

import io
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import requests

SCHEDULE_URL = "https://github.com/nflverse/nfldata/raw/master/data/games.csv"
PLAYER_URL = "https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_{season}.csv"
TEAM_URL = "https://github.com/nflverse/nflverse-data/releases/download/stats_team/stats_team_week_{season}.csv"

OUT_DIR = Path(os.environ.get("OUT_DIR", "data"))
POSITIONS = {"QB", "RB", "WR", "TE"}

PLAYER_STATS = [
    "completions", "attempts", "passing_yards", "passing_tds", "passing_interceptions",
    "sacks_suffered", "passing_air_yards", "passing_first_downs", "passing_epa", "passing_cpoe",
    "carries", "rushing_yards", "rushing_tds", "rushing_first_downs", "rushing_epa", "rushing_fumbles_lost",
    "targets", "receptions", "receiving_yards", "receiving_tds", "receiving_air_yards",
    "receiving_yards_after_catch", "receiving_first_downs", "receiving_epa",
    "target_share", "air_yards_share", "wopr",
    "fantasy_points", "fantasy_points_ppr",
]

SPLIT_KEYS = [
    "home", "away", "div", "nondiv", "opp_top", "opp_mid", "opp_bot",
    "fav", "dog", "rest_short", "rest_norm", "rest_long", "dome", "outdoor",
]


def guess_season() -> int:
    now = datetime.now(timezone.utc)
    return now.year if now.month >= 8 else now.year - 1


def fetch_csv(url: str) -> pd.DataFrame | None:
    r = requests.get(url, timeout=60)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return pd.read_csv(io.StringIO(r.text), low_memory=False)


def num(x, nd=2):
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return None
    return round(float(x), nd)


# ---------------------------------------------------------------- schedule

def build_schedule(games: pd.DataFrame):
    """Return (games_by_week, per-team-per-game context map)."""
    by_week: dict[int, list] = {}
    ctx: dict[tuple[str, str], dict] = {}  # (game_id, team) -> split context

    for _, g in games.iterrows():
        wk = int(g.week)
        spread = num(g.spread_line, 1)   # positive = home favored
        total = num(g.total_line, 1)
        home_imp = num((total + spread) / 2, 1) if spread is not None and total is not None else None
        away_imp = num((total - spread) / 2, 1) if spread is not None and total is not None else None
        played = not pd.isna(g.home_score)
        roof = str(g.roof) if not pd.isna(g.roof) else "outdoors"
        indoor = roof in ("dome", "closed")

        row = {
            "id": g.game_id,
            "week": wk,
            "date": g.gameday,
            "time": g.gametime if not pd.isna(g.gametime) else None,
            "away": g.away_team,
            "home": g.home_team,
            "spread": spread,
            "total": total,
            "away_implied": away_imp,
            "home_implied": home_imp,
            "away_ml": num(g.away_moneyline, 0),
            "home_ml": num(g.home_moneyline, 0),
            "div": bool(g.div_game),
            "roof": roof,
            "away_rest": int(g.away_rest) if not pd.isna(g.away_rest) else None,
            "home_rest": int(g.home_rest) if not pd.isna(g.home_rest) else None,
            "away_qb": g.away_qb_name if not pd.isna(g.away_qb_name) else None,
            "home_qb": g.home_qb_name if not pd.isna(g.home_qb_name) else None,
            "played": played,
            "away_score": int(g.away_score) if played else None,
            "home_score": int(g.home_score) if played else None,
        }
        by_week.setdefault(wk, []).append(row)

        for side in ("home", "away"):
            team = g.home_team if side == "home" else g.away_team
            rest = g.home_rest if side == "home" else g.away_rest
            team_spread = None if spread is None else (-spread if side == "home" else spread)  # negative = favored
            if team_spread is None:
                fav = None
            elif team_spread < 0:
                fav = "fav"
            elif team_spread > 0:
                fav = "dog"
            else:
                fav = None
            if pd.isna(rest):
                rest_k = None
            elif rest < 7:
                rest_k = "rest_short"
            elif rest == 7:
                rest_k = "rest_norm"
            else:
                rest_k = "rest_long"
            ctx[(g.game_id, team)] = {
                "week": wk,
                "opp": g.away_team if side == "home" else g.home_team,
                "keys": [k for k in [
                    side,
                    "div" if g.div_game else "nondiv",
                    fav,
                    rest_k,
                    "dome" if indoor else "outdoor",
                ] if k],
                "spread": team_spread,
                "total": total,
                "implied": home_imp if side == "home" else away_imp,
                "played": played,
                "pf": (g.home_score if side == "home" else g.away_score) if played else None,
                "pa": (g.away_score if side == "home" else g.home_score) if played else None,
            }
    return by_week, ctx


# ---------------------------------------------------------------- opponent tiers

def defense_tiers(ctx: dict) -> dict[str, str]:
    """Rank teams by points allowed per game. Returns team -> opp_top/opp_mid/opp_bot.
    'opp_top' means a top-10 defense (fewest points allowed)."""
    pa: dict[str, list[int]] = {}
    for (_, team), c in ctx.items():
        if c["played"]:
            pa.setdefault(team, []).append(int(c["pa"]))
    if not pa:
        return {}
    avg = {t: sum(v) / len(v) for t, v in pa.items()}
    ranked = sorted(avg, key=avg.get)
    tiers = {}
    n = len(ranked)
    for i, t in enumerate(ranked):
        if i < 10:
            tiers[t] = "opp_top"
        elif i >= n - 10:
            tiers[t] = "opp_bot"
        else:
            tiers[t] = "opp_mid"
    return tiers


# ---------------------------------------------------------------- aggregation

def agg_stats(rows: list[dict], stat_names: list[str], ctx: dict, tiers: dict) -> dict:
    """rows: list of {game_id, team, <stats...>}. Returns stat schema dict."""
    out = {s: {"t": 0.0, "g": 0, "s": {k: [0.0, 0] for k in SPLIT_KEYS}} for s in stat_names}
    for r in rows:
        c = ctx.get((r["game_id"], r["team"]))
        if not c:
            continue
        keys = list(c["keys"])
        tier = tiers.get(c["opp"])
        if tier:
            keys.append(tier)
        for s in stat_names:
            v = r.get(s)
            if v is None or (isinstance(v, float) and pd.isna(v)):
                continue
            v = float(v)
            out[s]["t"] += v
            out[s]["g"] += 1
            for k in keys:
                out[s]["s"][k][0] += v
                out[s]["s"][k][1] += 1
    # round and drop empty splits
    for s in stat_names:
        out[s]["t"] = round(out[s]["t"], 3)
        out[s]["s"] = {k: [round(v[0], 3), v[1]] for k, v in out[s]["s"].items() if v[1] > 0}
    return out


def build_players(df: pd.DataFrame, ctx: dict, tiers: dict) -> dict:
    df = df[df.season_type.eq("REG") & df.position.isin(POSITIONS)].copy()
    players = {}
    for pid, grp in df.groupby("player_id"):
        grp = grp.sort_values("week")
        last = grp.iloc[-1]
        rows = grp[["game_id", "team"] + [c for c in PLAYER_STATS if c in grp.columns]].to_dict("records")
        stats = agg_stats(rows, [c for c in PLAYER_STATS if c in grp.columns], ctx, tiers)
        weekly = []
        for _, r in grp.iterrows():
            c = ctx.get((r.game_id, r.team), {})
            weekly.append({
                "week": int(r.week),
                "opp": r.opponent_team,
                **{s: num(r[s]) for s in ("passing_yards", "passing_tds", "passing_interceptions",
                                            "carries", "rushing_yards", "rushing_tds",
                                            "targets", "receptions", "receiving_yards", "receiving_tds",
                                            "fantasy_points_ppr") if s in grp.columns},
            })
        # drop stats that never registered for this player (WR passing, etc.)
        stats = {k: v for k, v in stats.items() if v["t"] != 0}
        weekly = [{k: v for k, v in w.items() if v is not None} for w in weekly]
        players[pid] = {
            "id": pid,
            "name": last.player_display_name,
            "short": last.player_name,
            "pos": last.position,
            "team": last.team,
            "headshot": last.headshot_url if not pd.isna(last.headshot_url) else None,
            "games": int(grp.shape[0]),
            "stats": stats,
            "weekly": weekly,
        }
    return players


def build_teams(tdf: pd.DataFrame, ctx: dict, tiers: dict) -> dict:
    tdf = tdf[tdf.season_type.eq("REG")].copy()
    # derived per-game team stats
    tdf["plays"] = tdf.attempts + tdf.carries + tdf.sacks_suffered
    tdf["total_yards"] = tdf.passing_yards + tdf.rushing_yards - tdf.sack_yards_lost
    tdf["giveaways"] = tdf.passing_interceptions + tdf.fumbles_lost_total
    tdf["takeaways"] = tdf.def_interceptions + tdf.fumble_recovery_opp
    tdf["to_margin"] = tdf.takeaways - tdf.giveaways

    # points and betting outcomes come from the schedule context
    def game_ctx(r):
        return ctx.get((r.game_id, r.team), {})

    tdf["pf"] = tdf.apply(lambda r: game_ctx(r).get("pf"), axis=1)
    tdf["pa"] = tdf.apply(lambda r: game_ctx(r).get("pa"), axis=1)
    tdf["margin"] = tdf.pf - tdf.pa
    tdf["implied"] = tdf.apply(lambda r: game_ctx(r).get("implied"), axis=1)
    tdf["pf_vs_implied"] = tdf.pf - tdf.implied

    def cover(r):
        c = game_ctx(r)
        if not c.get("played") or c.get("spread") is None:
            return None
        m = c["pf"] - c["pa"] + c["spread"]  # spread negative if favored
        return 1.0 if m > 0 else (0.5 if m == 0 else 0.0)

    def over(r):
        c = game_ctx(r)
        if not c.get("played") or c.get("total") is None:
            return None
        s = c["pf"] + c["pa"]
        return 1.0 if s > c["total"] else (0.5 if s == c["total"] else 0.0)

    tdf["ats"] = tdf.apply(cover, axis=1)
    tdf["ou_over"] = tdf.apply(over, axis=1)
    tdf["win"] = tdf.margin.apply(lambda m: None if pd.isna(m) else (1.0 if m > 0 else (0.5 if m == 0 else 0.0)))

    stat_names = [
        "pf", "pa", "margin", "win", "ats", "ou_over", "pf_vs_implied",
        "plays", "total_yards", "passing_yards", "rushing_yards", "attempts", "carries",
        "passing_tds", "rushing_tds", "passing_first_downs", "rushing_first_downs",
        "passing_epa", "rushing_epa", "sacks_suffered", "def_sacks",
        "giveaways", "takeaways", "to_margin", "penalties", "penalty_yards",
    ]
    teams = {}
    for team, grp in tdf.groupby("team"):
        grp = grp.sort_values("week")
        rows = grp[["game_id", "team"] + stat_names].to_dict("records")
        stats = agg_stats(rows, stat_names, ctx, tiers)
        # yards per play as a ratio of totals, not an average of ratios
        if stats["plays"]["t"]:
            stats["yards_per_play"] = {
                "t": round(stats["total_yards"]["t"] / stats["plays"]["t"], 3),
                "g": stats["plays"]["g"],
                "s": {k: [round(stats["total_yards"]["s"][k][0] / v[0], 3), v[1]]
                      for k, v in stats["plays"]["s"].items() if v[0]},
                "ratio": True,
            }
        teams[team] = {
            "id": team,
            "games": int(grp.shape[0]),
            "def_tier": tiers.get(team),
            "form": [
                {"week": int(r.week), "opp": r.opponent_team, "pf": num(r.pf, 0), "pa": num(r.pa, 0),
                 "w": "W" if r.win == 1 else ("T" if r.win == 0.5 else "L"),
                 "ats": None if pd.isna(r.ats) else ("C" if r.ats == 1 else ("P" if r.ats == 0.5 else "X"))}
                for _, r in grp.iterrows() if not pd.isna(r.pf)
            ],
            "stats": stats,
        }
    return teams


# ---------------------------------------------------------------- main

def main():
    target = int(os.environ.get("SEASON", guess_season()))
    print(f"target season {target}")

    games_all = fetch_csv(SCHEDULE_URL)
    pdf = fetch_csv(PLAYER_URL.format(season=target))
    tdf = fetch_csv(TEAM_URL.format(season=target))

    season = target
    note = None
    if pdf is None or tdf is None:
        fallback = target - 1
        note = f"{target} stats not published yet, using {fallback}"
        print(note)
        season = fallback
        pdf = fetch_csv(PLAYER_URL.format(season=season))
        tdf = fetch_csv(TEAM_URL.format(season=season))
        if pdf is None or tdf is None:
            sys.exit("no stat files available")

    games = games_all[(games_all.season == season) & (games_all.game_type == "REG")].copy()
    by_week, ctx = build_schedule(games)
    tiers = defense_tiers(ctx)
    teams = build_teams(tdf, ctx, tiers)
    players = build_players(pdf, ctx, tiers)

    played_weeks = [w for w, gs in by_week.items() if any(g["played"] for g in gs)]
    current_week = (max(played_weeks) + 1) if played_weeks else 1
    current_week = min(current_week, max(by_week))

    meta = {
        "season": season,
        "target_season": target,
        "note": note,
        "current_week": current_week,
        "weeks": sorted(by_week),
        "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "teams": sorted(teams),
        "players_count": len(players),
        "splits": SPLIT_KEYS,
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    dump = lambda name, obj: (OUT_DIR / name).write_text(json.dumps(obj, separators=(",", ":"), allow_nan=False))
    dump("meta.json", meta)
    dump("schedule.json", {str(k): v for k, v in sorted(by_week.items())})
    dump("teams.json", teams)
    dump("players.json", players)
    for f in sorted(OUT_DIR.glob("*.json")):
        print(f"{f.name:15} {f.stat().st_size/1024:8.1f} KB")
    print(f"season {season} week {current_week} teams {len(teams)} players {len(players)}")


if __name__ == "__main__":
    main()
