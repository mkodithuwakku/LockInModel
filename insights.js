/* Pure presentation helpers; never mutate synced rosters or recompute scoring. */
(function (root) {
  "use strict";
  const SLOT_POSITIONS = {
    PG: ["PG"], SG: ["SG"], SF: ["SF"], PF: ["PF"], C: ["C"],
    G: ["PG", "SG"], F: ["SF", "PF"], UTIL: ["PG", "SG", "SF", "PF", "C"],
  };
  const OUT_STATUSES = new Set(["OUT", "O", "IR", "INJURED_RESERVE", "SUSPENDED", "SUSP", "INACTIVE"]);
  const PLAYABLE = new Set(["pre_game", "in_game", "in_progress", "complete", "final", "post_game"]);
  const PLACEHOLDER_REASONS = new Set(["No game today", "Game already started or finished", "Game postponed or unconfirmed", "Schedule unavailable", "Projection unavailable"]);
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
  function repinLineup(team, active = true) {
    // Re-derives the daily lineup with pinned players, mirroring recommend_lineup.
    const daily = team?.recommended_lineup;
    if (!active || !daily || !Array.isArray(daily.slots)) return team;
    const locks = team?.locks && typeof team.locks === "object" ? team.locks : {};
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
    // Placeholder fill: healthy benched players hold open slots so the sheet
    // never renders an empty lineup. They add nothing to the projected total.
    const idle = bench.filter((p) => PLACEHOLDER_REASONS.has(p.reason));
    const open = merged.map((s, i) => (s.player == null ? i : -1)).filter((i) => i >= 0);
    if (idle.length && open.length) {
      const pool = idle.map((p) => ({...p, projected_fp: Number.isFinite(p.projected_fp) ? p.projected_fp : 0}));
      const placement = optimalAssignment(open.map((i) => merged[i].slot), pool);
      const used = new Set();
      placement.forEach((pick, j) => {
        if (pick == null) return;
        const i = open[j];
        used.add(idle[pick]);
        merged[i] = {
          slot: merged[i].slot, slot_index: i, ...idle[pick], off_day: true,
          lineup_reason: `${idle[pick].reason} — holding the slot so your roster stays visible`,
        };
      });
      if (used.size) bench.splice(0, bench.length, ...bench.filter((p) => !used.has(p)));
    }
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
    if (player.schedule_state === "verified" && ["pre_game", "in_game", "in_progress"].includes(game.status) &&
        validDay && (Number.isFinite(game.proj_fp) || Number.isFinite(projection?.projected_fp))) {
      const value = Number.isFinite(game.proj_fp) ? game.proj_fp : projection.projected_fp;
      const description = Number.isFinite(game.proj_fp)
        ? `Projected ${value.toFixed(1)} FP vs ${game.opponent} · opponent-adjusted`
        : `Projected ${value.toFixed(1)} fantasy points · per-game estimate when active, not opponent-adjusted · as of ${projection.as_of}`;
      return {kind: "projection", label: "Proj", value, description};
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
    shield: "Top 3 steals plus blocks; only games with at least one steal AND one block count.",
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
  function gamesToWatch(teams, date) {
    // Today's matchups ranked by how many rostered players are involved,
    // across every loaded team. A player rostered on two leagues counts once.
    const matchups = new Map();
    for (const team of teams || []) {
      (team.results || []).forEach((row, index) => {
        for (const g of row.week_games || []) {
          if (g.date !== date || !row.nba_team || !g.opponent) continue;
          const away = g.home ? g.opponent : row.nba_team;
          const home = g.home ? row.nba_team : g.opponent;
          const key = `${away}@${home}`;
          if (!matchups.has(key))
            matchups.set(key, {key, away, home, status: g.status, players: new Map(), spots: 0});
          const m = matchups.get(key);
          m.spots += 1;
          const rank = {in_game: 2, in_progress: 2, pre_game: 0};
          if ((rank[g.status] ?? 1) > (rank[m.status] ?? 1)) m.status = g.status;
          const pid = String(row.player_id ?? row.player);
          if (!m.players.has(pid))
            m.players.set(pid, {player: row.player, player_id: row.player_id, nba_team: row.nba_team,
              positions: row.positions || [], teams: [], fp: null, team_id: team.id, index});
          const p = m.players.get(pid);
          if (!p.teams.includes(team.team_name)) p.teams.push(team.team_name);
          if (Number.isFinite(g.fp)) p.fp = g.fp;
        }
      });
    }
    return [...matchups.values()]
      .map(m => ({...m, players: [...m.players.values()]}))
      .sort((a, b) => b.players.length - a.players.length || b.spots - a.spots || a.key.localeCompare(b.key));
  }
  function varietyCap(p) {
    // 44 badge types exist; the two age badges are mutually exclusive, so the
    // ceiling is 43. Players 24-31 or with an unknown birth date reach 42.
    const counts = p?.counts || {};
    if ((counts.unc || 0) > 0 || (counts.new_gen || 0) > 0) return 43;
    const age = p?.age;
    if (Number.isFinite(age)) return age <= 23 || age >= 32 ? 43 : 42;
    return 42;
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
      variety: available ? player?.variety ?? 0 : null,
      variety_cap: available ? varietyCap(player) : null};
  }
  function seasonBadgeLeaders(team, metric = "total", scope = "roster") {
    const roster = new Map((team.results || []).map((p, index) => ({...p, index})).filter(p => p.player_id).map(p => [String(p.player_id), p]));
    const aggregate = new Set(["total", "negative", "milestones", "variety"]);
    if (!aggregate.has(metric) && !badgeTypes[metric]) return [];
    const rows = (team.season_badges?.players || []).filter(p => scope === "nba" || roster.has(String(p.player_id)))
      .map(p => {
        const current = roster.get(String(p.player_id));
        return {...p, player: current?.player || p.player, nba_team: current?.nba_team || p.nba_team,
          index: current?.index, age: current?.age, count: aggregate.has(metric) ? p[metric] : p.counts?.[metric]};
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
  function comparisonTeams(comparison, metric = "roster_average") {
    const mean = values => values.length ? values.reduce((a,b) => a+b, 0) / values.length : null;
    const teams = (comparison?.teams || []).map(t => {
      const players = (t.players || []).filter(p => p.games > 0 && Number.isFinite(p.average_fp))
        .sort((a,b) => b.average_fp-a.average_fp || a.player.localeCompare(b.player));
      return {...t, ranked_players: players,
        roster_average: mean(players.map(p => p.average_fp)),
        top_five: players.length >= 5 ? mean(players.slice(0,5).map(p => p.average_fp)) : null,
        depth: mean(players.slice(5).map(p => p.average_fp))};
    });
    return teams.sort((a,b) => (b[metric] ?? -Infinity) - (a[metric] ?? -Infinity) || a.team_name.localeCompare(b.team_name));
  }
  function comparisonPlayers(comparison, filters = {}) {
    const unique = new Map();
    for (const t of comparison?.teams || []) {
      if (filters.team && t.team_id !== filters.team) continue;
      for (const p of t.players || []) {
        const key = `${t.season || ""}:${p.player_id}`;
        if (!unique.has(key)) unique.set(key, {...p, season:t.season, teams:[], team_id:t.team_id});
        unique.get(key).teams.push(t.team_name);
      }
    }
    const metric = filters.metric || "average_fp";
    const value = p => metric.startsWith("pergame:") ? (p.stats?.[metric.slice(8)] != null && p.games ? p.stats[metric.slice(8)]/p.games : null)
      : metric.startsWith("stat:") ? p.stats?.[metric.slice(5)] : p[metric];
    const ascending = metric === "spread";
    const rows = [...unique.values()].filter(p =>
      p.games >= (Number(filters.minimum) || 1) &&
      (!filters.position || p.positions?.includes(filters.position)) &&
      (!filters.search || p.player.toLowerCase().includes(filters.search.toLowerCase())));
    rows.sort((a,b) => {
      const av = value(a), bv = value(b);
      if (!Number.isFinite(av)) return Number.isFinite(bv) ? 1 : a.player.localeCompare(b.player);
      if (!Number.isFinite(bv)) return -1;
      return (ascending ? av-bv : bv-av) || a.player.localeCompare(b.player);
    });
    let rank = 0, last;
    return rows.map((p,i) => {
      const v = value(p);
      if (v !== last) rank = i+1;
      last = v;
      return {...p, rank:Number.isFinite(v) ? rank : null};
    });
  }
  function filmSpotlight(film, margin = null) {
    // A baseline shortfall affects the banked total only for that exact locked game.
    const candidates = (film?.performances || []).filter(p => Number.isFinite(p.delta) && p.delta < 0 &&
      (film.locked || []).some(l => String(l.player_id) === String(p.player_id) && l.date === p.date && Math.abs(l.fp-p.fp) < 0.01))
      .sort((a,b) => a.delta-b.delta || a.player.localeCompare(b.player));
    return {player:candidates[0], flips: Number.isFinite(margin) && margin >= 0
      ? candidates.filter(p => -p.delta > margin) : []};
  }
  const SEASON_STATS = ["MIN","PTS","REB","AST","STL","BLK","FG3M","TOV","FGM","FGA","FTM","FTA","FG3A","OREB","DREB","PF"];
  const average = values => values.length ? values.reduce((a,b)=>a+b,0)/values.length : null;
  function quantile(values, q) {
    if (!values.length) return null;
    const sorted = [...values].sort((a,b)=>a-b), index=(sorted.length-1)*q, low=Math.floor(index);
    return sorted[low]+(sorted[Math.ceil(index)]-sorted[low])*(index-low);
  }
  function seasonAggregate(games) {
    const n=games.length, fp=games.map(g=>g.fp), mean=average(fp), stats={}, coverage={}, scoring={};
    for(const key of SEASON_STATS) {
      const values=games.map(g=>g.stats?.[key]).filter(Number.isFinite);
      coverage[key]=values.length;
      stats[key]=n && values.length===n ? values.reduce((a,b)=>a+b,0) : null;
    }
    const ratio=(a,b,scale=1)=>Number.isFinite(a) && Number.isFinite(b) && b>0 ? a/b*scale : null;
    const sum=(a,b)=>Number.isFinite(a)&&Number.isFinite(b) ? a+b : null;
    stats.FG_PCT=ratio(stats.FGM,stats.FGA,100);
    stats.FG3_PCT=ratio(stats.FG3M,stats.FG3A,100);
    stats.FT_PCT=ratio(stats.FTM,stats.FTA,100);
    stats.EFG_PCT=ratio(sum(stats.FGM,Number.isFinite(stats.FG3M)?stats.FG3M*.5:null),stats.FGA,100);
    stats.TS_PCT=ratio(stats.PTS,Number.isFinite(stats.FGA)&&Number.isFinite(stats.FTA)?2*(stats.FGA+.44*stats.FTA):null,100);
    stats.AST_TOV=ratio(stats.AST,stats.TOV);
    const total=n?fp.reduce((a,b)=>a+b,0):null;
    stats.FP_PER_MIN=ratio(total,stats.MIN);
    stats.FP_PER36=ratio(total,stats.MIN,36);
    for(const key of ["PTS","REB","AST"]) stats[`${key}_PER36`]=ratio(stats[key],stats.MIN,36);
    stats.THREE_RATE=ratio(stats.FG3A,stats.FGA,100);
    stats.FT_RATE=ratio(stats.FTA,stats.FGA);
    stats.STOCKS=sum(stats.STL,stats.BLK);
    stats.FG_MISSES=sum(stats.FGA,stats.FGM==null?null:-stats.FGM);
    stats.FT_MISSES=sum(stats.FTA,stats.FTM==null?null:-stats.FTM);
    for(const game of games) for(const [key,value] of Object.entries(game.scoring || {})) {
      if(Number.isFinite(value)) scoring[key]=(scoring[key] || 0)+value;
    }
    const benchmarks=games.filter(g=>Number.isFinite(g.delta));
    const countKnown=key=>n && games.every(g=>typeof g[key]==="boolean") ? games.filter(g=>g[key]).length : null;
    return {games:n,total_fp:total,average_fp:mean,stats,coverage,scoring,
      median_fp:quantile(fp,.5),floor_fp:n>=5?quantile(fp,.25):null,ceiling_fp:n>=5?quantile(fp,.75):null,
      spread:n>=5?Math.sqrt(average(fp.map(v=>(v-mean)**2))):null,
      best_fp:n?Math.max(...fp):null,worst_fp:n?Math.min(...fp):null,
      recent_fp:average(fp.slice(-5)),recent_games:Math.min(n,5),
      change:n>=10?average(fp.slice(-5))-average(fp.slice(-10,-5)):null,
      forty:games.filter(g=>g.fp>=40).length,sixty:games.filter(g=>g.fp>=60).length,
      negative:games.filter(g=>g.fp<0).length,
      double_doubles:countKnown("double_double"),triple_doubles:countKnown("triple_double"),
      benchmark_games:benchmarks.length,above_baseline:benchmarks.filter(g=>g.delta>0).length,
      below_baseline:benchmarks.filter(g=>g.delta<0).length,
      baseline_delta:average(benchmarks.map(g=>g.delta))};
  }
  function seasonPeriod(date, period="week") {
    if(period==="month") return date.slice(0,7);
    if(period==="day") return date;
    const d=new Date(date+"T12:00:00Z");
    d.setUTCDate(d.getUTCDate()-((d.getUTCDay()+6)%7));
    return d.toISOString().slice(0,10);
  }
  function seasonGroups(games, key) {
    const groups=new Map();
    for(const g of games) { const value=key(g); if(!groups.has(value)) groups.set(value,[]); groups.get(value).push(g); }
    return [...groups].map(([label,entries])=>({label,entries,...seasonAggregate(entries)}));
  }
  function seasonExplorer(team, filters={}) {
    const review=team.season_review || {};
    const full=(review.game_log || []).filter(g=>Number.isFinite(g.fp)).slice()
      .sort((a,b)=>a.date.localeCompare(b.date) || String(a.player_id).localeCompare(String(b.player_id)));
    let from=filters.from || "", to=filters.to || review.as_of || "";
    if(filters.range && filters.range!=="custom") {
      from=""; to=review.as_of || full.at(-1)?.date || "";
      if(to && ["7","30"].includes(filters.range)) {
        const d=new Date(to+"T12:00:00Z");d.setUTCDate(d.getUTCDate()-Number(filters.range)+1);from=d.toISOString().slice(0,10);
      }
    }
    const games=full.filter(g=>(!from || g.date>=from) && (!to || g.date<=to) &&
      (!filters.player || String(g.player_id)===filters.player) &&
      (!filters.venue || g.venue===filters.venue) && (!filters.result || g.result===filters.result));
    const summary=seasonAggregate(games);
    const byPlayer=new Map(seasonGroups(games,g=>String(g.player_id)).map(g=>[g.label,g]));
    const seen=new Set();
    const players=(team.results || []).map((p,index)=>({...p,index})).filter(p=>{
      const id=String(p.player_id || p.player);
      if(seen.has(id) || (filters.player && String(p.player_id)!==filters.player)) return false;
      seen.add(id); return true;
    }).map(p=>{
      const group=byPlayer.get(String(p.player_id)), entries=group?.entries || [];
      let streak=0, direction=null;
      for(const g of [...entries].reverse()) {
        if(!Number.isFinite(g.delta) || g.delta===0) break;
        const sign=g.delta>0?"above":"below";
        if(direction && direction!==sign) break;
        direction=sign;streak++;
      }
      return {...p,...seasonAggregate(entries),entries,streak,streak_direction:direction,
        first_played:entries[0]?.date,last_played:entries.at(-1)?.date};
    }).sort((a,b)=>(b.total_fp ?? -Infinity)-(a.total_fp ?? -Infinity) || a.player.localeCompare(b.player));
    const positive=players.reduce((s,p)=>s+Math.max(0,p.total_fp || 0),0);
    players.forEach(p=>p.share=positive ? Math.max(0,p.total_fp || 0)/positive*100 : null);
    const roles=seasonGroups(games,g=>{
      const p=players.find(p=>String(p.player_id)===String(g.player_id));
      return ["IR","TAXI"].includes(p?.roster_slot)?"Current reserves":p?.starter?"Current starters":"Current bench";
    });
    const periods=seasonGroups(games,g=>seasonPeriod(g.date,filters.period || "week")).sort((a,b)=>a.label.localeCompare(b.label));
    const weeks=seasonGroups(games,g=>seasonPeriod(g.date)).sort((a,b)=>a.label.localeCompare(b.label));
    const splits=[
      ...seasonGroups(games,g=>g.venue==="home"?"Home":g.venue==="away"?"Away":"Venue unknown").map(g=>({...g,group:"Venue"})),
      ...seasonGroups(games,g=>g.result==="W"?"NBA wins":g.result==="L"?"NBA losses":"Result unknown").map(g=>({...g,group:"NBA result"})),
      ...seasonGroups(games,g=>g.days_since_previous==null?"No preceding appearance":g.days_since_previous===1?"Consecutive days":g.days_since_previous===2?"1 day between":g.days_since_previous>2?"2+ days between":"Same-day appearances").map(g=>({...g,group:"Player game spacing"})),
    ];
    const rankedGames=[...games].sort((a,b)=>b.fp-a.fp || a.date.localeCompare(b.date));
    const deltas=games.filter(g=>Number.isFinite(g.delta)).sort((a,b)=>b.delta-a.delta);
    const bands=[[-Infinity,0,"Below 0"],[0,10,"0–9.9"],[10,20,"10–19.9"],[20,30,"20–29.9"],[30,40,"30–39.9"],[40,50,"40–49.9"],[50,60,"50–59.9"],[60,Infinity,"60+"]];
    return {available:Array.isArray(review.game_log),full,games,from,to,summary,players,periods,weeks,roles,splits,
      days:seasonGroups(games,g=>g.date),
      opponents:seasonGroups(games,g=>g.opponent || "Unknown").sort((a,b)=>b.games-a.games || a.label.localeCompare(b.label)),
      distribution:bands.map(([low,high,label])=>({label,count:games.filter(g=>g.fp>=low && g.fp<high).length})),
      top_three_share:positive?players.slice(0,3).reduce((s,p)=>s+Math.max(0,p.total_fp || 0),0)/positive*100:null,
      effective_contributors:positive?1/players.reduce((s,p)=>s+(p.share/100)**2,0):null,
      records:{best:rankedGames[0],worst:rankedGames.at(-1),above:deltas.find(g=>g.delta>0),below:[...deltas].reverse().find(g=>g.delta<0)}};
  }
  function seasonPlayerRows(explorer, filters={}) {
    const metric=filters.metric || "total_fp";
    const value=p=>metric.startsWith("pergame:") ? (p.games && Number.isFinite(p.stats[metric.slice(8)])?p.stats[metric.slice(8)]/p.games:null)
      : metric.startsWith("stat:")?p.stats[metric.slice(5)]:p[metric];
    return explorer.players.filter(p=>(!filters.search || p.player.toLowerCase().includes(filters.search.toLowerCase())) &&
      (!filters.position || (p.positions || []).includes(filters.position)) && p.games>=(Number(filters.minimum)||0))
      .sort((a,b)=>{
        const av=value(a),bv=value(b);
        if(!Number.isFinite(av)) return Number.isFinite(bv)?1:a.player.localeCompare(b.player);
        if(!Number.isFinite(bv)) return -1;
        return (metric==="spread"?av-bv:bv-av) || a.player.localeCompare(b.player);
      });
  }
  function seasonLogRows(explorer, filters={}) {
    const search=(filters.search || "").toLowerCase();
    const rows=explorer.games.filter(g=>(!search || `${g.player} ${g.opponent || ""} ${g.date}`.toLowerCase().includes(search)) &&
      (filters.kind==="forty"?g.fp>=40:filters.kind==="below"?g.delta<0:filters.kind==="dd"?g.double_double:filters.kind==="td"?g.triple_double:true));
    const metric=filters.metric || "date";
    return rows.sort((a,b)=>{
      if(metric==="date") return b.date.localeCompare(a.date) || b.fp-a.fp;
      const av=metric==="low_fp"?a.fp:metric.startsWith("stat:")?a.stats?.[metric.slice(5)]:a[metric];
      const bv=metric==="low_fp"?b.fp:metric.startsWith("stat:")?b.stats?.[metric.slice(5)]:b[metric];
      if(!Number.isFinite(av)) return Number.isFinite(bv)?1:0;
      if(!Number.isFinite(bv)) return -1;
      return (metric==="low_fp"?a.fp-b.fp:bv-av) || b.date.localeCompare(a.date);
    });
  }
  function seasonCsv(rows) {
    const keys=["date","player","player_id","opponent","venue","result","fp","baseline_fp","baseline_games","delta","double_double","triple_double"];
    const scoring=[...new Set(rows.flatMap(g=>Object.keys(g.scoring || {})))].sort();
    const cell=value=>{
      let text=value==null?"":String(value);
      if(typeof value==="string" && /^[=+\-@\t\r\n]/.test(text)) text="'"+text;
      return `"${text.replace(/"/g,'""')}"`;
    };
    return [keys.concat(SEASON_STATS,scoring.map(k=>`FP_FROM_${k}`)),
      ...rows.map(g=>[...keys.map(k=>g[k]),...SEASON_STATS.map(k=>g.stats?.[k]),...scoring.map(k=>g.scoring?.[k])])]
      .map(row=>row.map(cell).join(",")).join("\r\n");
  }
  const helpers = { seasonExplorer, seasonAggregate, seasonPlayerRows, seasonLogRows, seasonPeriod, seasonCsv, comparisonTeams, comparisonPlayers, filmSpotlight, badgePlayer, playerSeasonBadges, seasonBadgeLeaders, performanceBaseline, performanceScore, seasonContributors, seasonHighlights, gameFantasy, rosterSheet, repinLineup, teamForm, sparkline, dailyBadges, previousDate, badgeGuide, varietyCap, lockMatches, gamesToWatch };
  helpers._test = {optimalAssignment, eligibleSlot, lockMatches};
  if (typeof module !== "undefined" && module.exports) module.exports = helpers;
  else root.LockInInsights = helpers;
})(typeof window === "undefined" ? globalThis : window);
