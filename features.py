"""Opponent-aware pregame features derived strictly from prior box scores.

Every rolling aggregate for a target on date T is computed only from games with
dates strictly before T (rolling windows are shifted past the current game).
Missing context degrades to neutral values (pace/defense ratios of 1.0, league
means for player form) rather than invented matchups; the source Parquet
fixtures lack OREB/FG3A so team possessions are approximated with OREB = 0,
which is consistent across both sides of each game.
"""

import numpy as np
import pandas as pd

from game_store import split_matchup

COMPONENTS = ("PTS", "REB", "AST", "STL", "BLK", "TOV", "FG3M")
POSS_TERMS = ("FGA", "FTA", "OREB", "TOV")
POSITIONS = {"PG", "SG", "SF", "PF", "C", "G", "F"}
POSITION_ALIASES = {"GUARD": "G", "FORWARD": "F", "CENTER": "C"}
FRESH_REST_DAYS = 3  # schedule rest assumed for a first observed team game


def normalize_position(value):
    """Coarse primary-position label; unknown/missing returns None."""
    pos = str(value or "").strip().upper()
    pos = POSITION_ALIASES.get(pos, pos)
    return pos if pos in POSITIONS else None


def season_key(dates):
    """NBA season start year: October-December games open a new season."""
    dates = pd.DatetimeIndex(pd.to_datetime(dates))
    return np.where(dates.month >= 10, dates.year, dates.year - 1)


def team_game_table(games):
    """Per-(game, team) totals with Dean Oliver possessions and pace.

    Possessions estimate each team's trips with
    0.5 * ((FGA + 0.44*FTA - OREB + TOV)_team + (same)_opponent), the standard
    single-game approximation. Pace is possessions scaled to 48 minutes of team
    playing time: 48 * poss / (team_minutes / 5).
    """
    stats = ["PTS", *COMPONENTS[1:], *POSS_TERMS, "MIN"]
    missing = [s for s in stats if s not in games]
    if missing:
        # Approximation: unavailable counting stats contribute zero so minimal
        # frames still produce consistent (if underestimated) possessions.
        games = games.copy()
        for s in missing:
            games[s] = 0.0
    tg = (
        games.groupby(["GAME_ID", "TEAM_ABBREVIATION"], sort=False)
        .agg(GAME_DATE=("GAME_DATE", "first"), **{s: (s, "sum") for s in stats})
        .reset_index()
    )
    opp = tg.drop(columns=["GAME_DATE"]).add_prefix("O_")
    merged = tg.merge(opp, left_on="GAME_ID", right_on="O_GAME_ID", suffixes=("", "_o"))
    merged = merged[merged.TEAM_ABBREVIATION != merged.O_TEAM_ABBREVIATION]
    estimate = merged.FGA + 0.44 * merged.FTA - merged.OREB + merged.TOV
    opp_estimate = merged.O_FGA + 0.44 * merged.O_FTA - merged.O_OREB + merged.O_TOV
    merged["poss"] = 0.5 * (estimate + opp_estimate)
    merged["pace"] = np.where(
        merged.MIN > 0, 48.0 * merged.poss / (merged.MIN / 5.0), np.nan
    )
    merged["pts_allowed"] = merged.O_PTS
    for s in COMPONENTS:
        merged["conceded_" + s] = merged["O_" + s]
    return merged[
        [
            "GAME_ID",
            "GAME_DATE",
            "TEAM_ABBREVIATION",
            "MIN",
            "poss",
            "pace",
            "pts_allowed",
            *("conceded_" + s for s in COMPONENTS),
        ]
    ].rename(columns={"TEAM_ABBREVIATION": "team", "MIN": "team_min"})


class FeatureBuilder:
    """Precomputed rolling aggregates over historical player-games.

    targets passed to ``features_for`` need PLAYER_ID, GAME_DATE (the future
    game date), and either MATCHUP (to derive opponent + home) or OPPONENT /
    IS_HOME columns. ``cutoff`` is exclusive: only games strictly before it may
    contribute statistics. Schedule metadata (dates, opponents, venues) for
    games on/after the cutoff is legitimately pregame information.
    """

    def __init__(
        self, games, positions=None, window=15, decay=0.92, lookback=10, schedule=None
    ):
        self.window, self.decay, self.lookback = window, decay, lookback
        self._schedule = schedule
        games = games.copy()
        games["GAME_DATE"] = pd.to_datetime(games.GAME_DATE)
        games["PLAYER_ID"] = games.PLAYER_ID.astype(str)
        if "MATCHUP" in games:
            parsed = games.MATCHUP.map(split_matchup)
            games["HOME"] = [p[0] for p in parsed]
            games["OPP"] = [p[1] for p in parsed]
        else:
            games["HOME"] = games.get("IS_HOME", 0)
            games["OPP"] = games.get("OPPONENT")
        self._positions = {
            str(k): normalize_position(v) for k, v in (positions or {}).items()
        }
        if "POSITION" in games:
            games["POS"] = games.POSITION.map(normalize_position)
        else:
            games["POS"] = games.PLAYER_ID.map(lambda p: self._positions.get(p))
        if "TEAM_ABBREVIATION" not in games:
            games["TEAM_ABBREVIATION"] = None
        games["SEASON_YR"] = season_key(games.GAME_DATE)
        for s in COMPONENTS:
            games[s] = pd.to_numeric(games[s], errors="coerce")
        self.games = games.sort_values(["GAME_DATE", "GAME_ID", "PLAYER_ID"])
        self._build_team_state()
        self._build_league_state()
        self._build_pos_state()
        self._build_player_index()

    # -- internal rolling tables -------------------------------------------------

    def _build_team_state(self):
        tg = team_game_table(self.games).sort_values("GAME_DATE")
        tg = tg.reset_index(drop=True)
        if tg.empty:
            tg = pd.DataFrame(
                columns=[
                    "GAME_ID",
                    "GAME_DATE",
                    "team",
                    "team_min",
                    "poss",
                    "pace",
                    "pts_allowed",
                    *("conceded_" + s for s in COMPONENTS),
                    "defrtg",
                    "prev_pace",
                    *("concede_rate_" + s for s in COMPONENTS),
                ]
            )
            tg["GAME_DATE"] = pd.to_datetime(tg.GAME_DATE)
            self.team_games = tg
            self._team_rows = {}
            return
        out = []
        for team, block in tg.groupby("team", sort=False):
            block = block.sort_values("GAME_DATE").reset_index(drop=True)
            prev = block.shift(1)
            for col in ("poss", "pts_allowed", *("conceded_" + s for s in COMPONENTS)):
                block["prev_sum_" + col] = (
                    prev[col].rolling(self.window, min_periods=1).sum()
                )
            block["prev_pace"] = prev["pace"].rolling(self.window, min_periods=1).mean()
            out.append(block)
        tg = pd.concat(out, ignore_index=True)
        tg["defrtg"] = 100.0 * tg.prev_sum_pts_allowed / tg.prev_sum_poss
        for s in COMPONENTS:
            tg["concede_rate_" + s] = (
                100.0 * tg["prev_sum_conceded_" + s] / tg.prev_sum_poss
            )
        self.team_games = tg
        # As-of lookup: for each team, metric rows indexed by that game's date.
        self._team_rows = {t: b.reset_index(drop=True) for t, b in tg.groupby("team")}

    def _build_league_state(self):
        tg = self.team_games.sort_values(["GAME_DATE", "GAME_ID"])
        daily = tg.groupby("GAME_DATE").agg(
            pace_sum=("pace", "sum"),
            pace_n=("pace", "count"),
            poss=("poss", "sum"),
            pts=("pts_allowed", "sum"),
        )
        # Strictly-before-date cumulative league state.
        cum = daily.cumsum().shift(1)
        league = pd.DataFrame(
            {
                "GAME_DATE": daily.index,
                "league_pace": cum.pace_sum / cum.pace_n,
                "league_defrtg": 100.0 * cum.pts / cum.poss,
            }
        )
        player_daily = self.games.groupby("GAME_DATE")[
            [s for s in COMPONENTS] + ["PLAYER_ID"]
        ].agg({s: "sum" for s in COMPONENTS} | {"PLAYER_ID": "count"})
        player_cum = player_daily.cumsum().shift(1)
        for s in COMPONENTS:
            league["league_mean_" + s] = player_cum[s] / player_cum.PLAYER_ID
        self.league = league.reset_index(drop=True)
        self.league["GAME_DATE"] = pd.to_datetime(self.league.GAME_DATE)
        self._league_dates = self.league.GAME_DATE.to_numpy()

    def _build_pos_state(self):
        games = self.games[self.games.POS.notna() & self.games.OPP.notna()]
        self.pos_state = {}
        self._league_pos = {}
        self._pos_state_frame = pd.DataFrame()
        if games.empty:
            return
        rows = (
            games.groupby(["GAME_ID", "OPP", "POS"], sort=False)[list(COMPONENTS)]
            .sum()
            .reset_index()
        )
        dates = self.games[["GAME_ID", "GAME_DATE"]].drop_duplicates("GAME_ID")
        rows = rows.merge(dates, on="GAME_ID", how="left").sort_values("GAME_DATE")
        state = {}
        blocks = []
        for (opp, pos), block in rows.groupby(["OPP", "POS"], sort=False):
            block = block.sort_values("GAME_DATE").reset_index(drop=True)
            prev = block.shift(1)
            for s in COMPONENTS:
                block["pos_mean_" + s] = (
                    prev[s].rolling(self.window, min_periods=1).mean()
                )
            state[(opp, pos)] = block
            blocks.append(block)
        self.pos_state = state
        self._pos_state_frame = pd.concat(blocks, ignore_index=True)
        # Expanding league mean per position of per-game conceded stats.
        league_pos = {}
        for pos, block in rows.groupby("POS", sort=False):
            daily = block.groupby("GAME_DATE")[list(COMPONENTS)].agg(["sum", "count"])
            cum_sum = daily.xs("sum", axis=1, level=1).cumsum().shift(1)
            cum_n = daily.xs("count", axis=1, level=1).iloc[:, 0].cumsum().shift(1)
            league_pos[pos] = pd.DataFrame(
                {
                    "GAME_DATE": daily.index,
                    **{s: cum_sum[s] / cum_n for s in COMPONENTS},
                }
            ).reset_index(drop=True)
        self._league_pos = league_pos

    def _build_player_index(self):
        stats = list(COMPONENTS) + ["MIN"]
        players = {}
        for pid, block in self.games.groupby("PLAYER_ID", sort=False):
            block = block.sort_values("GAME_DATE")
            players[pid] = {
                "dates": block.GAME_DATE.to_numpy(),
                "season_yr": season_key(block.GAME_DATE),
                "stats": block[stats].to_numpy(dtype=float),
                "team": block.TEAM_ABBREVIATION.to_numpy(),
            }
        self._players = players
        self._team_dates = {
            t: np.sort(b.GAME_DATE.to_numpy())
            for t, b in self.team_games.groupby("team")
        }
        if self._schedule is not None and len(self._schedule):
            # Scheduled-but-unplayed dates count toward rest: a Friday target
            # must see Wednesday's game even though no box score exists yet.
            extra = self._schedule.copy()
            extra["GAME_DATE"] = pd.to_datetime(extra.GAME_DATE)
            for t, block in extra.groupby("TEAM_ABBREVIATION"):
                base = self._team_dates.get(t, np.array([], dtype="datetime64[ns]"))
                self._team_dates[t] = np.union1d(base, block.GAME_DATE.to_numpy())

    # -- shared lookup helpers ---------------------------------------------------

    def _team_metrics(self, team, date):
        """Rolling opponent metrics for `team` using games strictly before date."""
        block = self._team_rows.get(team)
        if block is None:
            return None
        idx = (
            np.searchsorted(block.GAME_DATE.to_numpy(), np.datetime64(date), "left") - 1
        )
        if idx < 0:
            return None
        return block.iloc[idx]

    def _league_metrics(self, date):
        idx = np.searchsorted(self._league_dates, np.datetime64(date), "left") - 1
        if idx < 0:
            return None
        return self.league.iloc[idx]

    def _pos_concede(self, opp, pos, date):
        block = self.pos_state.get((opp, pos))
        if block is None:
            return None
        idx = (
            np.searchsorted(block.GAME_DATE.to_numpy(), np.datetime64(date), "left") - 1
        )
        if idx < 0:
            return None
        return block.iloc[idx]

    def _league_pos_mean(self, pos, date):
        block = self._league_pos.get(pos)
        if block is None or block.empty:
            return None
        idx = (
            np.searchsorted(block.GAME_DATE.to_numpy(), np.datetime64(date), "left") - 1
        )
        if idx < 0:
            return None
        return block.iloc[idx]

    def _rest_days(self, team, target_date, fallback=FRESH_REST_DAYS):
        dates = self._team_dates.get(team)
        if dates is None:
            return fallback
        idx = np.searchsorted(dates, np.datetime64(target_date), "left") - 1
        if idx < 0:
            return fallback
        gap = int((np.datetime64(target_date) - dates[idx]) / np.timedelta64(1, "D"))
        return max(0, gap - 1)

    def _player_form(self, pid, cutoff):
        """Decayed recent means and same-season means from games before cutoff."""
        entry = self._players.get(str(pid))
        if entry is None:
            return None
        dates = entry["dates"]
        idx = np.searchsorted(dates, np.datetime64(cutoff), "left")
        stats = entry["stats"][:idx]
        if idx == 0:
            return {"n": 0}
        recent = stats[max(0, idx - self.lookback) : idx]
        weights = self.decay ** np.arange(len(recent) - 1, -1, -1, dtype=float)
        recent_mean = np.average(recent, axis=0, weights=weights)
        same_season = stats[entry["season_yr"][:idx] == entry["season_yr"][idx - 1]]
        season_mean = same_season.mean(axis=0)
        return {
            "n": idx,
            "recent": recent_mean,  # COMPONENTS order then MIN
            "season": season_mean,
        }

    def _row_features(self, pid, target_date, team, opp, home, pos, cutoff):
        out = {
            "PLAYER_ID": str(pid),
            "GAME_DATE": target_date,
            "is_home": 1.0 if home else 0.0,
        }
        league = self._league_metrics(cutoff)
        form = self._player_form(pid, cutoff)
        for i, s in enumerate(COMPONENTS):
            neutral = (
                getattr(league, "league_mean_" + s, np.nan)
                if league is not None
                else np.nan
            )
            out["recent_mean_" + s] = (
                float(form["recent"][i]) if form and form.get("n") else neutral
            )
            out["season_mean_" + s] = (
                float(form["season"][i]) if form and form.get("n") else neutral
            )
        out["recent_min"] = (
            float(form["recent"][-1]) if form and form.get("n") else np.nan
        )
        metrics = self._team_metrics(opp, cutoff)
        pace_team = self._team_metrics(team, cutoff)
        league_pace = (
            getattr(league, "league_pace", np.nan) if league is not None else np.nan
        )
        paces = [
            getattr(r, "prev_pace", np.nan)
            for r in (pace_team, metrics)
            if r is not None
        ]
        if paces and np.isfinite(league_pace) and league_pace > 0:
            expected = np.nanmean(paces)
            out["pace_mult"] = (
                float(expected / league_pace) if np.isfinite(expected) else 1.0
            )
        else:
            out["pace_mult"] = 1.0
        defrtg = getattr(metrics, "defrtg", np.nan) if metrics is not None else np.nan
        league_defrtg = (
            getattr(league, "league_defrtg", np.nan) if league is not None else np.nan
        )
        out["defrtg_rel"] = (
            float(defrtg / league_defrtg)
            if np.isfinite(defrtg) and np.isfinite(league_defrtg) and league_defrtg > 0
            else 1.0
        )
        conceded = self._pos_concede(opp, pos, cutoff)
        league_pos = self._league_pos_mean(pos, cutoff) if pos else None
        for i, s in enumerate(COMPONENTS):
            c = (
                getattr(conceded, "pos_mean_" + s, np.nan)
                if conceded is not None
                else np.nan
            )
            m = getattr(league_pos, s, np.nan) if league_pos is not None else np.nan
            out["pos_ratio_" + s] = (
                float(c / m) if np.isfinite(c) and np.isfinite(m) and m > 0 else 1.0
            )
        rest = self._rest_days(team, target_date)
        out["rest_days"] = float(rest)
        out["b2b"] = 1.0 if rest == 0 else 0.0
        return out

    def features_for(self, targets, cutoff=None):
        """Feature rows for not-yet-played targets using stats before cutoff.

        ``cutoff`` is exclusive and defaults to each target's own GAME_DATE,
        which yields the same strictly-before-T features used in training.
        """
        records = []
        for _, row in targets.iterrows():
            target_date = pd.Timestamp(row["GAME_DATE"])
            cut = pd.Timestamp(
                cutoff if cutoff is not None else row.get("AS_OF", target_date)
            )
            matchup = row.get("MATCHUP")
            home, opp = (
                split_matchup(matchup)
                if matchup
                else (
                    int(row.get("IS_HOME", 0)),
                    row.get("OPPONENT") or row.get("OPP"),
                )
            )
            team = row.get("TEAM_ABBREVIATION")
            if not team and matchup:
                team = str(matchup).split(" vs. ")[0].split(" @ ")[0].strip()
            pos = row.get("POS") or row.get("POSITION")
            pos = normalize_position(pos) or self._positions.get(str(row["PLAYER_ID"]))
            records.append(
                self._row_features(
                    str(row["PLAYER_ID"]), target_date, team, opp, home, pos, cut
                )
            )
        return pd.DataFrame(records, index=targets.index)

    def training_matrix(self):
        """Per-game feature frame where each row uses only strictly-prior games."""
        games = self.games.reset_index(drop=True)
        out = games[
            [
                "GAME_ID",
                "PLAYER_ID",
                "GAME_DATE",
                "SEASON_YR",
                "HOME",
                "OPP",
                "POS",
                "TEAM_ABBREVIATION",
            ]
        ].copy()
        for s in COMPONENTS:
            out[s] = games[s]
        stats = list(COMPONENTS) + ["MIN"]
        # Decayed recent means via lagged accumulation per player.
        grouped = games.groupby("PLAYER_ID", sort=False)
        for i, s in enumerate(stats):
            num = pd.Series(0.0, index=games.index)
            den = pd.Series(0.0, index=games.index)
            w = 1.0
            for lag in range(1, self.lookback + 1):
                shifted = grouped[s].shift(lag)
                num = num + w * shifted.fillna(0.0)
                den = den + w * shifted.notna()
                w *= self.decay
            col = "recent_min" if s == "MIN" else "recent_mean_" + s
            out[col] = np.where(den > 0, num / den.clip(lower=1e-9), np.nan)
        # Same-season expanding mean (strictly prior rows).
        for s in COMPONENTS:
            cum = games.groupby(["PLAYER_ID", "SEASON_YR"], sort=False)[s].cumsum()
            cnt = games.groupby(["PLAYER_ID", "SEASON_YR"], sort=False).cumcount()
            out["season_mean_" + s] = np.where(cnt > 0, (cum - games[s]) / cnt, np.nan)
        # Team schedule context: rest from the team's previous game.
        tg = self.team_games[["GAME_ID", "team", "GAME_DATE"]].copy()
        if tg.empty:
            tg["rest_days"] = pd.Series(dtype=float)
        else:
            tg["prev_date"] = tg.groupby("team")["GAME_DATE"].shift(1)
            tg["rest_days"] = (
                ((tg.GAME_DATE - tg.prev_date).dt.days - 1)
                .clip(lower=0)
                .fillna(FRESH_REST_DAYS)
            )
        out = out.merge(
            tg[["GAME_ID", "team", "rest_days"]],
            left_on=["GAME_ID", "TEAM_ABBREVIATION"],
            right_on=["GAME_ID", "team"],
            how="left",
        )
        out["b2b"] = (out.rest_days == 0).astype(float)
        out["is_home"] = out.HOME.astype(float)
        # Opponent rolling metrics as of this game date.
        metrics_cols = ["team", "GAME_DATE", "defrtg", "prev_pace"] + [
            "concede_rate_" + s for s in COMPONENTS
        ]
        opp_metrics = self.team_games[metrics_cols].rename(
            columns={"team": "OPP", "prev_pace": "opp_pace"}
        )
        out = out.merge(opp_metrics, on=["OPP", "GAME_DATE"], how="left")
        own_pace = self.team_games[["team", "GAME_DATE", "prev_pace"]].rename(
            columns={"team": "TEAM_ABBREVIATION", "prev_pace": "own_pace"}
        )
        out = out.merge(own_pace, on=["TEAM_ABBREVIATION", "GAME_DATE"], how="left")
        out = out.merge(self.league, on="GAME_DATE", how="left")
        pace_ratio = out[["own_pace", "opp_pace"]].mean(axis=1) / out.league_pace
        out["pace_mult"] = pd.to_numeric(pace_ratio, errors="coerce").fillna(1.0)
        out["pace_mult"] = out.pace_mult.replace([np.inf, -np.inf], 1.0)
        defrtg_ratio = out.defrtg / out.league_defrtg
        out["defrtg_rel"] = pd.to_numeric(defrtg_ratio, errors="coerce").fillna(1.0)
        out["defrtg_rel"] = out.defrtg_rel.replace([np.inf, -np.inf], 1.0)
        # Positional concessions: rolling stats the opponent allowed per game to
        # the player's position, divided by the league's expanding mean for that
        # position; both sides strictly predate the target game.
        if not self._pos_state_frame.empty:
            out = out.merge(
                self._pos_state_frame[
                    ["GAME_ID", "OPP", "POS", *("pos_mean_" + s for s in COMPONENTS)]
                ],
                on=["GAME_ID", "OPP", "POS"],
                how="left",
            )
            for pos, lblock in self._league_pos.items():
                mask = out.POS == pos
                if not mask.any():
                    continue
                for s in COMPONENTS:
                    league_map = dict(zip(lblock.GAME_DATE, lblock[s]))
                    out.loc[mask, "league_pos_" + s] = out.loc[mask, "GAME_DATE"].map(
                        league_map
                    )
            for s in COMPONENTS:
                conceded = out["pos_mean_" + s]
                lmean = out["league_pos_" + s]
                out["pos_ratio_" + s] = np.where(
                    conceded.notna() & lmean.notna() & (lmean > 0),
                    conceded / lmean.where(lmean > 0),
                    1.0,
                )
        else:
            for s in COMPONENTS:
                out["pos_ratio_" + s] = 1.0
        # Neutral fills for missing context and empty player history.
        for s in COMPONENTS:
            for col in ("recent_mean_" + s, "season_mean_" + s):
                out[col] = out[col].fillna(out["league_mean_" + s]).fillna(0.0)
        out["recent_min"] = out.recent_min.fillna(0.0)
        out["rest_days"] = out.rest_days.fillna(FRESH_REST_DAYS)
        for s in COMPONENTS:
            out["pos_ratio_" + s] = out["pos_ratio_" + s].fillna(1.0)
        return out.drop(columns=["league_pace", "league_defrtg"], errors="ignore")
