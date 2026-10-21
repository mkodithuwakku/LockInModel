/* Observed team form only: no projections or changes to league scoring. */
(function (root) {
  "use strict";
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
    sandwich: ["🥪", "Turnover sandwich", "turnovers"],
  };
  function previousDate(reference) {
    const day = new Date(reference + "T12:00:00Z");
    if (!Number.isFinite(day.getTime())) return null;
    day.setUTCDate(day.getUTCDate() - 1);
    return day.toISOString().slice(0, 10);
  }
  function dailyBadges(player, reference) {
    const day = previousDate(reference);
    return (player.daily_badges || []).filter(b => badgeTypes[b.key] && b.date === day &&
      Number.isInteger(b.rank) && b.rank >= 1 && b.rank <= 3 && Number.isFinite(b.value) && b.value > 0)
      .map(b => {
        const [icon, name, stat] = badgeTypes[b.key];
        const value = Number(b.value.toFixed(1));
        return {...b, icon, name, label: `${name} · ${b.tied ? "Tied #" : "#"}${b.rank} NBA-wide · ${value} ${stat} · ${b.date}`};
      });
  }
  const helpers = { teamForm, sparkline, dailyBadges, previousDate };
  if (typeof module !== "undefined" && module.exports) module.exports = helpers;
  else root.LockInInsights = helpers;
})(typeof window === "undefined" ? globalThis : window);
