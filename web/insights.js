/* Pure presentation helpers; never mutate synced rosters or recompute scoring. */
(function (root) {
  "use strict";
  const SLOT_POSITIONS = {
    PG: ["PG"], SG: ["SG"], SF: ["SF"], PF: ["PF"], C: ["C"],
    G: ["PG", "SG"], F: ["SF", "PF"], UTIL: ["PG", "SG", "SF", "PF", "C"],
  };
  const OUT_STATUSES = new Set(["OUT", "O", "IR", "INJURED_RESERVE", "SUSPENDED", "SUSP", "INACTIVE"]);
  const PLAYABLE = new Set(["pre_game", "in_progress", "complete", "final", "post_game"]);
  // Python's round() is banker's rounding; cents keep parity with lineup.py.
  const cents = (v) => {
    const x = v * 100, f = Math.floor(x), d = x - f;
    return d > 0.5 ? f + 1 : d < 0.5 ? f : (f % 2 === 0 ? f : f + 1);
  };
  function eligibleSlot(positions, slot) {
    return slot in SLOT_POSITIONS &&
      (slot === "UTIL" || (positions || []).some((p) => SLOT_POSITIONS[slot].includes(p)));
  }
  function optimalAssignment(slots, candidates) {
    // Rectangular maximum-weight assignment, mirroring lineup.py exactly.
    const n = slots.length, count = candidates.length;
    if (!n) return [];
    const m = count + n;
    const forbidden = candidates.reduce((sum, p) => sum + Math.abs(cents(p.projected_fp)), 0) + 1;
    const costs = slots.map((slot) =>
      candidates.map((p) => (eligibleSlot(p.positions, slot) ? -cents(p.projected_fp) : forbidden)).concat(Array(n).fill(0)));
    const u = Array(n + 1).fill(0), v = Array(m + 1).fill(0);
    const assignment = Array(m + 1).fill(0), way = Array(m + 1).fill(0);
    for (let i = 1; i <= n; i++) {
      assignment[0] = i;
      let j0 = 0;
      const minimum = Array(m + 1).fill(Infinity), used = Array(m + 1).fill(false);
      while (true) {
        used[j0] = true;
        const i0 = assignment[j0];
        let delta = Infinity, j1 = 0;
        for (let j = 1; j <= m; j++) {
          if (used[j]) continue;
          const reduced = costs[i0 - 1][j - 1] - u[i0] - v[j];
          if (reduced < minimum[j]) { minimum[j] = reduced; way[j] = j0; }
          if (minimum[j] < delta) { delta = minimum[j]; j1 = j; }
        }
        for (let j = 0; j <= m; j++) {
          if (used[j]) { u[assignment[j]] += delta; v[j] -= delta; }
          else minimum[j] -= delta;
        }
        j0 = j1;
        if (assignment[j0] === 0) break;
      }
      while (true) {
        const j1 = way[j0];
        assignment[j0] = assignment[j1];
        j0 = j1;
        if (j0 === 0) break;
      }
    }
    const result = Array(n).fill(null);
    for (let j = 1; j <= count; j++) {
      if (assignment[j]) result[assignment[j] - 1] = j - 1;
    }
    return result;
  }
  const canon = (s) =>
    String(s ?? "").normalize("NFKD").replace(/\p{M}/gu, "").toLowerCase().trim()
      .replace(/(?:,?\s+(?:jr\.?|sr\.?|ii|iii|iv))$/u, "");
  const lockMatches = (row, record) => {
    const pid = String(record.player_id ?? "");
    if (pid && (String(row.sleeper_id ?? "") === pid || String(row.player_id ?? "") === pid || String(row.player_id ?? "") === "sleeper:" + pid)) return true;
    const name = String(record.player_name ?? "");
    return name.length > 0 && canon(row.player) === canon(name);
  };
  function repinLineup(team) {
    // Re-derives the daily lineup with pinned players, mirroring recommend_lineup.
    const daily = team?.recommended_lineup;
    const locks = team?.locks;
    if (!daily || !Array.isArray(daily.slots) || !locks || typeof locks !== "object" || !Object.keys(locks).length)
      return team;
    const date = daily.date;
    const rows = team.results || [];
    const slots = daily.slots.map((s) => s.slot);
    const pinned = new Map();
    for (const record of Object.values(locks)) {
      if (!record || typeof record !== "object") continue;
      const hit = rows.findIndex((r) => lockMatches(r, record));
      if (hit < 0 || ["IR", "TAXI"].includes(rows[hit].roster_slot)) continue;
      const row = rows[hit];
      const name = row.roster_slot && slots.includes(row.roster_slot) ? row.roster_slot : record.roster_slot;
      let index = null;
      for (const candidate of [record.slot_index, row.lineup_order]) {
        if (Number.isInteger(candidate) && candidate >= 0 && candidate < slots.length && slots[candidate] === name && !pinned.has(candidate)) { index = candidate; break; }
      }
      if (index == null) index = slots.findIndex((s, i) => s === name && !pinned.has(i));
      if (index != null && index >= 0) pinned.set(index, {hit, record});
    }
    const pinnedRows = new Set([...pinned.values()].map((v) => v.hit));
    const candidates = [], bench = [], seen = new Set();
    let missing = 0, scheduled = 0, started = 0;
    rows.forEach((row, i) => {
      if (pinnedRows.has(i)) return;
      const identity = row.player_id != null && row.player_id !== "" ? String(row.player_id) : String(row.player).toLowerCase();
      if (seen.has(identity)) return;
      seen.add(identity);
      const entry = {player: row.player, player_id: row.player_id, positions: row.positions || [], current_slot: row.roster_slot, injury_status: row.injury_status};
      const profile = row.projection;
      if (profile && Number.isFinite(profile.projected_fp)) Object.assign(entry, profile);
      let reason = null;
      const todayGames = (row.week_games || []).filter((g) => g.date === date);
      if (["IR", "TAXI"].includes(row.roster_slot)) reason = "Reserve slot";
      else if (OUT_STATUSES.has(String(row.injury_status ?? "").toUpperCase().replaceAll(" ", "_"))) reason = "Unavailable: " + row.injury_status;
      else if (row.schedule_state !== "verified") { reason = "Schedule unavailable"; missing++; }
      else if (!todayGames.length) reason = "No game today";
      else if (todayGames.some((g) => !PLAYABLE.has(g.status))) { reason = "Game postponed or unconfirmed"; missing++; }
      else if (todayGames.some((g) => g.status !== "pre_game")) { reason = "Game already started or finished"; started++; }
      else {
        scheduled++;
        if (!profile || !Number.isFinite(profile.projected_fp)) { reason = "Projection unavailable"; missing++; }
        else if (!slots.some((s) => eligibleSlot(row.positions, s))) {
          reason = (row.positions || []).length ? "No eligible lineup slot" : "Position eligibility unavailable";
          if (!(row.positions || []).length) missing++;
        } else {
          entry.opponent = todayGames[0].opponent;
          entry.home = todayGames[0].home;
          candidates.push(entry);
        }
      }
      if (reason) bench.push({...entry, reason});
    });
    const pinnedEntry = (row, record) => {
      const entry = {player: row.player, player_id: row.player_id, positions: row.positions || [], current_slot: row.roster_slot, injury_status: row.injury_status};
      if (row.projection) Object.assign(entry, row.projection);
      const todayGames = (row.week_games || []).filter((g) => g.date === date);
      if (todayGames.length) { entry.opponent = todayGames[0].opponent; entry.home = todayGames[0].home; }
      const lockedFp = Number.isFinite(record.locked_fp) ? record.locked_fp : null;
      entry.projected_fp = lockedFp ?? entry.projected_fp;
      Object.assign(entry, {
        is_pinned: true, is_locked: true, locked_fp: lockedFp,
        lock_game_date: record.game_date ?? null,
        lineup_reason: "Pinned starter (locked in Sleeper)",
      });
      return entry;
    };
    const remaining = slots.filter((_, i) => !pinned.has(i));
    const assignment = remaining.length ? optimalAssignment(remaining, candidates) : [];
    const chosen = new Set(assignment.filter((i) => i !== null));
    candidates.forEach((p, i) => {
      if (!chosen.has(i)) bench.push({...p, reason: "Lower projected total or position fit"});
    });
    const merged = [];
    let cursor = 0;
    slots.forEach((slot, i) => {
      if (pinned.has(i)) {
        const {hit, record} = pinned.get(i);
        merged.push({slot, slot_index: i, ...pinnedEntry(rows[hit], record)});
        return;
      }
      const pick = assignment[cursor++];
      merged.push({slot, slot_index: i, ...(pick != null ? candidates[pick] : {player: null, projected_fp: null})});
    });
    const filled = chosen.size + pinned.size;
    const pinnedTotal = [...pinned.keys()].reduce((sum, i) => sum + (Number.isFinite(merged[i].projected_fp) ? merged[i].projected_fp : 0), 0);
    const chosenTotal = [...chosen].reduce((sum, i) => sum + candidates[i].projected_fp, 0);
    const status = missing ? "partial" : filled ? "ready" : !scheduled && !started ? "no_games" : "empty";
    const reason = {
      partial: "Best lineup among players with verified schedules and projections; some inputs are missing.",
      ready: pinned.size
        ? "Maximum projected total across eligible players and unlocked league slots."
        : "Maximum projected total across eligible players and league slots.",
      no_games: "No available roster players have a scheduled game today.",
      empty: started && !candidates.length
        ? "Today's available games have already started or finished. No remaining starts to recommend."
        : "No remaining eligible starts with a positive projected contribution.",
    }[status];
    return {
      ...team,
      recommended_lineup: {
        ...daily, status, reason, slots: merged, bench,
        filled_slots: filled, pinned_slots: pinned.size,
        total_projected_fp: (filled || !missing) ? Math.round((chosenTotal + pinnedTotal) * 100) / 100 : null,
        eligible_players: candidates.length,
      },
    };
  }
  function rosterSheet(team, useRecommendation = true) {
    const original = (team.results || []).map((p, i) => ({p, i}));
    const daily = team.recommended_lineup;
    const fallback = () => ({recommended: false, rows: original});
    if (!useRecommendation || !daily || daily.status === "unavailable" || !Array.isArray(daily.slots)) return fallback();
    const match = (entry) => original.find(({p}) => entry.player_id && p.player_id
      ? String(entry.player_id) === String(p.player_id) : entry.player === p.player);
    const assigned = new Map();
    const starters = [];
    for (const [order, slot] of daily.slots.entries()) {
      if (!slot.player) {
        starters.push({i: null, p: {player: "Unfilled", vacant: true, starter: true, roster_slot: slot.slot, lineup_order: order}});
        continue;
      }
      const row = match(slot);
      // Never display a plan against a different roster snapshot.
      if (!row || assigned.has(row.i)) return fallback();
      assigned.set(row.i, slot);
      starters.push({i: row.i, p: {...row.p, starter: true, roster_slot: slot.slot, lineup_order: order, lineup_fp: slot.projected_fp,
        is_locked: Boolean(slot.is_locked || row.p.is_locked), is_pinned: Boolean(slot.is_pinned),
        locked_fp: Number.isFinite(slot.locked_fp) ? slot.locked_fp : null,
        lock_game_date: slot.lock_game_date ?? null, lineup_reason: slot.lineup_reason ?? null}});
    }
    const others = original.filter(({i}) => !assigned.has(i)).map(({p, i}, order) => {
      const exclusion = (daily.bench || []).find(entry => match(entry)?.i === i);
      return {i, p: {...p, starter: false, roster_slot: ["IR", "TAXI"].includes(p.roster_slot) ? p.roster_slot : "BN",
        lineup_order: daily.slots.length + order, lineup_reason: exclusion?.reason || "Not selected in this snapshot"}};
    });
    return {recommended: true, rows: [...starters, ...others]};
  }
  function gameFantasy(player, game) {
    if (Number.isFinite(game.fp)) return {kind: "actual", label: "Final", value: game.fp,
      description: `Actual ${game.fp.toFixed(1)} fantasy points`};
    if (["complete", "final", "post_game"].includes(game.status))
      return {kind: "unavailable", label: "Final", value: null, description: "Final · fantasy score unavailable"};
    if (["postponed", "canceled", "cancelled"].includes(game.status))
      return {kind: "unavailable", label: game.status === "postponed" ? "PPD" : "CXL", value: null, description: "Game " + game.status};
    const projection = player.projection;
    const validDay = /^\d{4}-\d{2}-\d{2}$/.test(game.date || "") &&
      /^\d{4}-\d{2}-\d{2}$/.test(projection?.as_of || "") && game.date >= projection.as_of;
    if (player.schedule_state === "verified" && ["pre_game", "in_progress"].includes(game.status) &&
        validDay && Number.isFinite(projection?.projected_fp)) {
      return {kind: "projection", label: "Proj", value: projection.projected_fp,
        description: `Projected ${projection.projected_fp.toFixed(1)} fantasy points · per-game estimate when active, not opponent-adjusted · as of ${projection.as_of}`};
    }
    return {kind: "unavailable", label: "Proj", value: null, description: "Projection unavailable for this game"};
  }
  function performanceBaseline(player, cutoff) {
    if (player.history_source !== "prior_season" && Number.isFinite(player.fp_mean_recent)) {
      return {value: player.fp_mean_recent, source: player.baseline_source === "blended_seasons" ? "Recent average · current + prior season" : "Recent average"};
    }
    const history = (player.history || []).filter(r => Number.isFinite(r.fp) && /^\d{4}-\d{2}-\d{2}$/.test(r.date || "") && (!cutoff || r.date <= cutoff));
    if (history.length < 2) return null;
    return {value: history.reduce((sum, r) => sum + r.fp, 0) / history.length,
      source: player.history_source === "prior_season" ? "Prior-season history average" : "Stored history average"};
  }
  function performanceScore(player, value, cutoff) {
    const baseline = performanceBaseline(player, cutoff);
    if (!Number.isFinite(value) || !baseline) return {tone: "unknown", label: "Average comparison unavailable", baseline: null};
    // A 2 FP floor keeps a near-zero or negative average useful and stable.
    const band = Math.max(2, Math.abs(baseline.value) * 0.1);
    const delta = value - baseline.value;
    const tone = delta > band ? "good" : delta < -band ? "bad" : "average";
    const description = {good: "Above average", average: "Near average", bad: "Below average"}[tone];
    return {tone, baseline: baseline.value, band,
      label: `${description} · ${baseline.source.toLowerCase()} ${baseline.value.toFixed(1)} FP · near-average range ±${band.toFixed(1)} FP`};
  }
  function teamForm(players, cutoff) {
    const mean = (rows) => rows.reduce((sum, row) => sum + row.fp, 0) / rows.length;
    return players.map((player, index) => {
      const history = (player.history || [])
        .filter((row) => typeof row.fp === "number" && Number.isFinite(row.fp) &&
          /^\d{4}-\d{2}-\d{2}$/.test(row.date) && (!cutoff || row.date <= cutoff))
        .slice().sort((a, b) => a.date.localeCompare(b.date));
      const recent = history.slice(-5);
      const previous = history.slice(-10, -5);
      const average = recent.length ? mean(recent) : null;
      return { player, index, average, scores: recent.map((row) => row.fp),
        delta: recent.length === 5 && previous.length === 5 ? average - mean(previous) : null };
    }).sort((a, b) => (b.average ?? -Infinity) - (a.average ?? -Infinity) || a.index - b.index);
  }
  function sparkline(scores) {
    if (!scores.length) return '<span class="spark-empty">—</span>';
    const low = Math.min(...scores), high = Math.max(...scores);
    const points = scores.map((value, i) => [
      scores.length === 1 ? 28 : 3 + i * 50 / (scores.length - 1),
      high === low ? 15 : 26 - (value - low) * 22 / (high - low),
    ]);
    const [x, y] = points[points.length - 1];
    return `<svg viewBox="0 0 56 30" fill="none" aria-hidden="true"><path d="M0 28H56" class="spark-guide"/><polyline points="${points.map((point) => point.join(",")).join(" ")}"/><circle cx="${x}" cy="${y}" r="2.5"/></svg>`;
  }
  const badgeTypes = {
    sniper: ["🎯", "Sniper", "made threes"],
    fire: ["🔥", "On fire", "made field goals"],
    boards: ["🐷", "Board hog", "rebounds"],
    bricks: ["🧱", "Bricklayer", "missed field goals"],
    thief: ["🥷", "Thief", "steals"],
    rejection: ["🚫", "Rejection", "blocks"],
    runner: ["🏃", "Marathon man", "minutes"],
    dime: ["🪙", "Dropping dimes", "assists"],
    sandwich: ["🥪", "Meatball sub", "turnovers"],
    merchant: ["🧾", "Free-throw merchant", "made free throws"],
    heartbreak: ["💔", "Oh my goodness Valentine", "missed threes"],
    shield: ["📈", "Stock Expert", "steals + blocks"],
    creator: ["🧠", "Clean creator", "assists minus turnovers (5+ assists)"],
    magician: ["🎩", "Triple-double magic", "triple-doubles"],
    coffee: ["☕", "Double-double", "double-doubles"],
    overachiever: ["🚀", "Above expectations", "FP above projection"],
    underachiever: ["🫠", "Below expectations", "FP below projection"],
    efficient: ["⚡", "Minute maximizer", "FP/min"],
    inefficient: ["🐌", "Slow night", "FP/min (lowest)"],
  };
  Object.assign(badgeTypes, {
    careless: ["🧈", "Butterfingers", "assists minus turnovers"],
    hot_streak: ["🌶️", "Three-game heater", "games above season average"],
    cold_streak: ["🧊", "Cold spell", "games below season average"],
    win_mvp: ["🏆", "Winning effort", "FP in a win"],
    loss_mvp: ["🥀", "In vain", "FP in a loss"],
    win_low: ["🚌", "Along for the ride", "FP in a win (lowest, excluding zero)"],
    home_hero: ["🏡", "Hometown hero", "FP at home"],
    away_villain: ["🦹", "Villain", "FP away"],
    unc: ["👴", "The Unction", "FP at age 32+"],
    new_gen: ["🐣", "Young Boys FC", "FP at age 23 or younger"],
  });
  const milestoneTypes = [
    ["fg3m", "made threes", [[5,"🏹"],[10,"💸"]]],
    ["ast", "assists", [[10,"📬"],[15,"🧵"],[20,"🎼"]]],
    ["reb", "rebounds", [[10,"🧲"],[15,"🦍"],[20,"🐄"]]],
    ["blk", "blocks", [[10,"🛑"]]],
    ["stl", "steals", [[10,"🦝"]]],
    ["pts", "points", [[30,"🎬"],[40,"💎"],[50,"🌋"],[60,"☄️"],[70,"👑"]]],
  ];
  for (const [stat, label, tiers] of milestoneTypes) {
    for (const [threshold, icon] of tiers) badgeTypes[`milestone_${stat}_${threshold}`] =
      [icon, `${threshold}+ ${label}`, label];
  }
  const badgeRules = {
    creator: "Top 3 assists minus turnovers; only games with 5+ assists count, and the margin must be positive.",
    coffee: "10+ in any two of points, rebounds, assists, steals and blocks in one game. Triple-doubles also qualify.",
    magician: "10+ in any three of points, rebounds, assists, steals and blocks in one game.",
    overachiever: "Top 3 positive fantasy-point differences above a saved pregame projection. Missing forecasts are excluded.",
    underachiever: "Top 3 shortfalls below a saved pregame fantasy-point projection. Missing forecasts are excluded.",
    efficient: "Top 3 highest fantasy points per minute; any positive playing time qualifies.",
    inefficient: "Top 3 lowest fantasy points per minute, including zero and negative scores; any positive playing time qualifies.",
    careless: "The 3 lowest assists minus turnovers totals, including zero and negative margins. 2 assists − 7 turnovers = −5.",
    hot_streak: "Each of the last 3 games strictly above the current-season FP average through last night; at least 4 season games, and played last night.",
    cold_streak: "Each of the last 3 games strictly below the current-season FP average through last night; at least 4 season games, and played last night.",
    win_mvp: "Highest single-game fantasy points in a confirmed win.",
    loss_mvp: "Highest single-game fantasy points in a confirmed loss.",
    win_low: "Lowest single-game fantasy points in a confirmed win, excluding exactly zero FP. Negative FP can qualify.",
    home_hero: "Highest single-game fantasy points by a home player.",
    away_villain: "Highest single-game fantasy points by an away player.",
    unc: "Highest single-game fantasy points by a player age 32 or older on game day, using a known birth date.",
    new_gen: "Highest single-game fantasy points by a player age 23 or younger on game day, using a known birth date.",
  };
  const fantasyKeys = new Set(["overachiever", "underachiever", "efficient", "inefficient", "hot_streak", "cold_streak", "win_mvp", "loss_mvp", "win_low", "home_hero", "away_villain", "unc", "new_gen"]);
  function badgeGuide() {
    return Object.entries(badgeTypes).map(([key, [icon, name, stat]]) => ({
      key, icon, name,
      group: key.startsWith("milestone_") || ["coffee", "magician"].includes(key) ? "Milestones" : ["hot_streak", "cold_streak"].includes(key) ? "Streaks" : fantasyKeys.has(key) ? "Fantasy awards" : "Nightly leaders",
      rule: badgeRules[key] || (key.startsWith("milestone_") ? `${name} in one game. Every qualifier earns it; only the highest tier per stat is shown.` : `Top 3 most ${stat}.`),
      scope: fantasyKeys.has(key) ? "NBA · league scoring" : "NBA-wide",
    }));
  }
  function previousDate(reference) {
    const day = new Date(reference + "T12:00:00Z");
    if (!Number.isFinite(day.getTime())) return null;
    day.setUTCDate(day.getUTCDate() - 1);
    return day.toISOString().slice(0, 10);
  }
  function dailyBadges(player, reference) {
    const day = previousDate(reference);
    return (player.daily_badges || []).filter(b => badgeTypes[b.key] && b.date === day &&
      Number.isInteger(b.rank) && b.rank >= 1 && b.rank <= 3 && Number.isFinite(b.value) && (b.value > 0 || fantasyKeys.has(b.key) || b.key === "careless"))
      .map(b => {
        const [icon, name, stat] = badgeTypes[b.key];
        const value = Number(b.value.toFixed(b.key === "efficient" || b.key === "inefficient" ? 2 : 1));
        const scope = b.scope === "league_nba" ? "NBA · league scoring" : "NBA-wide";
        const coverage = Number.isInteger(b.forecast_count) ? ` · ${b.forecast_count}/${b.player_count} players with saved forecasts` : "";
        const comparison = Number.isFinite(b.actual_fp) && Number.isFinite(b.projected_fp) ? ` (${Number(b.actual_fp.toFixed(1))} actual vs ${Number(b.projected_fp.toFixed(1))} projected)` : "";
        const unranked = b.key.startsWith("milestone_") || ["hot_streak", "cold_streak"].includes(b.key);
        const rank = unranked ? "" : `${b.tied ? "Tied #" : "#"}${b.rank} `;
        const average = Number.isFinite(b.season_average) ? ` (season average ${Number(b.season_average.toFixed(1))} FP)` : "";
        return {...b, icon, name, label: `${name} · ${rank}${scope} · ${value} ${stat}${comparison}${coverage}${average} · ${b.date}`};
      });
  }
  function badgePlayer(team, playerId) {
    if (playerId == null || playerId === "") return null;
    const matches = p => p.player_id != null && String(p.player_id) === String(playerId);
    // Use only this league's details: another team may have different scoring.
    const roster = (team.results || []).find(matches);
    if (roster) return roster;
    const awards = (team.season_badges?.players || []).find(matches);
    if (!awards) return null;
    const details = (team.pickups || []).find(matches) || (team.available_players || []).find(matches);
    return {...awards, ...details, badge_profile: true};
  }
  function playerSeasonBadges(team, playerId) {
    const review = team.season_badges;
    const available = ["ready", "saved", "empty"].includes(review?.status) && playerId != null && playerId !== "";
    const player = available ? (review.players || []).find(p => String(p.player_id) === String(playerId)) : null;
    const earned = badgeGuide().filter(b => Number.isFinite(player?.counts?.[b.key]) && player.counts[b.key] > 0)
      .map(b => ({...b, count: player.counts[b.key]}))
      .sort((a, b) => b.count - a.count || a.name.localeCompare(b.name));
    return {available, earned, total: available ? player?.total ?? 0 : null,
      negative: available ? player?.negative ?? 0 : null, milestones: available ? player?.milestones ?? 0 : null,
      variety: available ? player?.variety ?? 0 : null};
  }
  function seasonBadgeLeaders(team, metric = "total", scope = "roster") {
    const roster = new Map((team.results || []).map((p, index) => ({...p, index})).filter(p => p.player_id).map(p => [String(p.player_id), p]));
    const aggregate = new Set(["total", "negative", "milestones", "variety"]);
    if (!aggregate.has(metric) && !badgeTypes[metric]) return [];
    const rows = (team.season_badges?.players || []).filter(p => scope === "nba" || roster.has(String(p.player_id)))
      .map(p => {
        const current = roster.get(String(p.player_id));
        return {...p, player: current?.player || p.player, nba_team: current?.nba_team || p.nba_team,
          index: current?.index, count: aggregate.has(metric) ? p[metric] : p.counts?.[metric]};
      }).filter(p => Number.isFinite(p.count) && p.count > 0)
      .sort((a,b) => b.count - a.count || a.player.localeCompare(b.player) || String(a.player_id).localeCompare(String(b.player_id)));
    const ranks = new Map(), ties = new Map();
    rows.forEach((p,i) => { if (!ranks.has(p.count)) ranks.set(p.count, i+1); ties.set(p.count, (ties.get(p.count) || 0)+1); });
    return rows.map(p => ({...p, rank: ranks.get(p.count), tied: ties.get(p.count)>1}));
  }
  function seasonContributors(team) {
    const observed = new Map((team.season_review?.players || []).map(p => [String(p.player_id), p]));
    return (team.results || []).map((p, index) => ({...p, ...observed.get(String(p.player_id)), index}))
      .sort((a, b) => (b.total_fp ?? -Infinity) - (a.total_fp ?? -Infinity) || a.player.localeCompare(b.player));
  }
  function seasonHighlights(players) {
    const best = (key, minGames) => players.filter(p => p.games >= minGames && Number.isFinite(p[key]))
      .sort((a, b) => b[key] - a[key] || a.player.localeCompare(b.player))[0];
    return {anchor: best("total_fp", 1), scorer: best("average_fp", 1), mover: best("change", 10), swing: best("spread", 5)};
  }
  const helpers = { badgePlayer, playerSeasonBadges, seasonBadgeLeaders, performanceBaseline, performanceScore, seasonContributors, seasonHighlights, gameFantasy, rosterSheet, repinLineup, teamForm, sparkline, dailyBadges, previousDate, badgeGuide };
  helpers._test = {optimalAssignment, eligibleSlot, lockMatches};
  if (typeof module !== "undefined" && module.exports) module.exports = helpers;
  else root.LockInInsights = helpers;
})(typeof window === "undefined" ? globalThis : window);
