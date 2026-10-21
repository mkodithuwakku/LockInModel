/* Pure presentation helpers; never mutate synced rosters or recompute scoring. */
(function (root) {
  "use strict";
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
      starters.push({i: row.i, p: {...row.p, starter: true, roster_slot: slot.slot, lineup_order: order, lineup_fp: slot.projected_fp}});
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
  const helpers = { performanceBaseline, performanceScore, seasonContributors, seasonHighlights, gameFantasy, rosterSheet, teamForm, sparkline, dailyBadges, previousDate, badgeGuide };
  if (typeof module !== "undefined" && module.exports) module.exports = helpers;
  else root.LockInInsights = helpers;
})(typeof window === "undefined" ? globalThis : window);
