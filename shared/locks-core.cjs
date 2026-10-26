/* Shared lock-document logic for the serverless write endpoint.
 * Pure functions so offline Node tests cover the same rules the endpoint uses.
 */

function emptyDocument() {
  return {version: 1, updated_at: null, leagues: {}};
}

function canonicalName(name) {
  const normalized = String(name ?? "")
    .normalize("NFKD")
    .replace(/\p{M}/gu, "")
    .toLowerCase()
    .trim();
  return normalized.replace(/(?:,?\s+(?:jr\.?|sr\.?|ii|iii|iv))$/u, "");
}

function olderWeek(stored, current) {
  // Week keys only compare within the same kind (integer or week-start date).
  if (typeof stored === "number" && typeof current === "number")
    return stored < current;
  if (typeof stored === "string" && typeof current === "string")
    return stored < current;
  return false;
}

function validatePayload(body) {
  if (!body || typeof body !== "object" || Array.isArray(body))
    throw new Error("Expected a JSON lock request.");
  const league_id = String(body.league_id ?? "").trim();
  if (!/^\d+$/.test(league_id)) throw new Error("A Sleeper league id is required.");
  const action = body.action;
  if (action !== "lock" && action !== "unlock")
    throw new Error("Action must be 'lock' or 'unlock'.");
  let week = body.schedule_week;
  if (typeof week === "string") week = week.trim();
  if (!(Number.isInteger(week) || (typeof week === "string" && week.length)))
    throw new Error("A schedule week is required.");
  const player = body.player;
  if (!player || typeof player !== "object" || Array.isArray(player))
    throw new Error("A player object is required.");
  const player_name = String(player.player_name ?? "").trim();
  const player_id = String(player.player_id ?? "").trim() || null;
  if (!player_id && !canonicalName(player_name))
    throw new Error("A player id or name is required.");
  const slot_index = player.slot_index;
  const locked_fp = player.locked_fp;
  return {
    league_id,
    schedule_week: week,
    action,
    player: {
      player_id,
      player_name: player_name || null,
      canonical_name: canonicalName(player_name) || null,
      roster_slot: String(player.roster_slot ?? "").trim() || null,
      slot_index: Number.isInteger(slot_index) ? slot_index : null,
      locked_fp:
        typeof locked_fp === "number" && Number.isFinite(locked_fp)
          ? locked_fp
          : null,
      game_date: String(player.game_date ?? "").trim() || null,
    },
  };
}

const LOCK_HISTORY_WEEKS = 30;

function weekSortValue(entry) {
  const week = entry && typeof entry === "object" ? entry.schedule_week : null;
  return typeof week === "number" ? [0, week] : [1, String(week ?? "")];
}

function archiveWeek(container, newWeek, now) {
  // Expired weeks move into the league's own bounded history so the weekly
  // film review can audit past lock calls instead of losing them on rollover.
  container = {...(container || {})};
  const oldWeek = container.schedule_week;
  const history = {...(container.history || {})};
  if (oldWeek != null && container.locks && Object.keys(container.locks).length) {
    history[String(oldWeek)] = {
      schedule_week: oldWeek,
      locks: {...container.locks},
      archived_at: now.toISOString(),
    };
    const ordered = Object.entries(history).sort((a, b) => {
      const [ta, va] = weekSortValue(a[1]), [tb, vb] = weekSortValue(b[1]);
      return ta - tb || (va < vb ? -1 : va > vb ? 1 : 0);
    });
    while (ordered.length > LOCK_HISTORY_WEEKS) ordered.shift();
    for (const key of Object.keys(history)) delete history[key];
    for (const [key, value] of ordered) history[key] = value;
  }
  if (newWeek == null) container.locks = {};
  else container = {schedule_week: newWeek, locks: {}};
  container.history = history;
  return container;
}

function applyLock(doc, payload, now = new Date()) {
  const {league_id, schedule_week: week, action, player} = payload;
  const next = doc && typeof doc === "object" ? {...doc} : emptyDocument();
  const leagues = {...(next.leagues || {})};
  let container = {...(leagues[league_id] || {})};
  if (container.schedule_week !== week)
    container = archiveWeek(container, week, now);
  const records = {...(container.locks || {})};
  const key = player.player_id || player.canonical_name;
  if (action === "lock") {
    records[key] = {
      ...player,
      locked_at: now.toISOString(),
    };
  } else {
    delete records[key];
    if (player.canonical_name) delete records[player.canonical_name];
  }
  container.locks = records;
  for (const [lid, record] of Object.entries(leagues)) {
    if (record && typeof record === "object" && olderWeek(record.schedule_week, week))
      leagues[lid] = archiveWeek(record, null, now);
  }
  leagues[league_id] = container;
  next.version = 1;
  next.updated_at = now.toISOString();
  next.leagues = leagues;
  return next;
}

module.exports = {
  applyLock,
  canonicalName,
  emptyDocument,
  validatePayload,
};
