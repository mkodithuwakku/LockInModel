/* Shared lock-document logic for the serverless write endpoint.
 * Pure functions so offline Node tests cover the same rules the endpoint uses.
 */

export function emptyDocument() {
  return {version: 1, updated_at: null, leagues: {}};
}

export function canonicalName(name) {
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

export function validatePayload(body) {
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

export function applyLock(doc, payload, now = new Date()) {
  const {league_id, schedule_week: week, action, player} = payload;
  const next = doc && typeof doc === "object" ? {...doc} : emptyDocument();
  const leagues = {...(next.leagues || {})};
  let container = {...(leagues[league_id] || {})};
  if (container.schedule_week !== week)
    container = {schedule_week: week, locks: {}};
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
      delete leagues[lid];
  }
  leagues[league_id] = container;
  next.version = 1;
  next.updated_at = now.toISOString();
  next.leagues = leagues;
  return next;
}
