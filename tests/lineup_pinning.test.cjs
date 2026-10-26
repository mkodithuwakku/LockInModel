const { test } = require("node:test");
const assert = require("node:assert/strict");
const { repinLineup, rosterSheet, _test } = require("../web/insights.js");
const { optimalAssignment, eligibleSlot } = _test;

const DATE = "2026-10-21";
const game = (over = {}) => ({ date: DATE, status: "pre_game", opponent: "BOS", home: true, fp: null, ...over });
const row = (name, positions = ["PG"], over = {}) => ({
  player: name, player_id: name, positions, roster_slot: "BN",
  schedule_state: "verified", week_games: [game()], ...over,
});
const lock = (player_id, over = {}) => ({
  player_id, player_name: null, roster_slot: "PG", slot_index: 0,
  locked_fp: 62.5, game_date: "2026-10-20", locked_at: "2026-10-21T04:00:00.000Z", ...over,
});
const team = (results, locks, slots = ["PG", "SG", "BN"]) => ({
  results,
  locks,
  recommended_lineup: { date: DATE, status: "ready", slots: slots.filter(s => s !== "BN").map(slot => ({ slot, player: null })), bench: [] },
});

test("optimalAssignment mirrors the Python Hungarian port", () => {
  const players = [
    { player: "Flexible", positions: ["PG", "SG"], projected_fp: 50 },
    { player: "Point", positions: ["PG"], projected_fp: 49 },
    { player: "Wing", positions: ["SG"], projected_fp: 10 },
  ];
  assert.deepEqual(
    optimalAssignment(["PG", "SG"], players).map((i) => players[i]?.player),
    ["Point", "Flexible"],
  );
  assert.deepEqual(optimalAssignment(["C"], [{ positions: ["PG"], projected_fp: 100 }]), [null]);
  assert.ok(eligibleSlot(["SF"], "UTIL") && !eligibleSlot(["PG"], "F"));
});

test("repinLineup keeps a locked player in its Sleeper slot with banked score", () => {
  const results = [
    row("A", ["PG", "SG"], { roster_slot: "PG", lineup_order: 0, projection: { projected_fp: 90 } }),
    row("B", ["PG"], { projection: { projected_fp: 95 } }),
  ];
  const t = team(results, { A: lock("A") });
  const daily = repinLineup(t).recommended_lineup;
  const [pg, sg] = daily.slots;
  assert.equal(pg.player, "A");
  assert.ok(pg.is_pinned && pg.is_locked);
  assert.equal(pg.projected_fp, 62.5);
  assert.equal(pg.locked_fp, 62.5);
  assert.equal(pg.lineup_reason, "Pinned starter (locked in Sleeper)");
  assert.equal(sg.player, null); // B cannot fill SG; the slot stays open.
  assert.equal(daily.pinned_slots, 1);
  assert.equal(daily.total_projected_fp, 62.5);
});

test("repinLineup blocks the slot even when the locked player has no game today", () => {
  const results = [
    row("A", ["PG"], { roster_slot: "PG", lineup_order: 0, week_games: [], projection: { projected_fp: 90 } }),
    row("B", ["SF"], { projection: { projected_fp: 50 } }),
  ];
  const daily = repinLineup(team(results, { A: lock("A", { locked_fp: 33 }) }, ["PG", "UTIL", "BN"])).recommended_lineup;
  assert.equal(daily.slots[0].player, "A");
  assert.equal(daily.slots[0].projected_fp, 33);
  assert.equal(daily.slots[1].player, "B");
  assert.equal(daily.total_projected_fp, 83);
  assert.equal(daily.status, "ready");
});

test("repinLineup fills idle roster players into open slots on a no-game day", () => {
  const results = [
    row("Locked", ["PG"], { roster_slot: "PG", lineup_order: 0, week_games: [], projection: { projected_fp: 90 } }),
    row("IdleGuard", ["SG"], { week_games: [], projection: { projected_fp: 40 } }),
    row("IdleBig", ["C"], { week_games: [], projection: { projected_fp: 30 } }),
  ];
  const daily = repinLineup(team(results, { Locked: lock("Locked") }, ["PG", "SG", "UTIL", "BN"])).recommended_lineup;
  assert.equal(daily.slots[0].player, "Locked");
  assert.equal(daily.slots[0].projected_fp, 62.5);
  assert.deepEqual(daily.slots.slice(1).map((s) => s.player), ["IdleGuard", "IdleBig"]);
  assert.ok(daily.slots[1].off_day && daily.slots[2].off_day);
  // Idle fills never count toward the projected total or filled slots.
  assert.equal(daily.filled_slots, 1);
  assert.equal(daily.total_projected_fp, 62.5);
  assert.equal(daily.bench.length, 0);
});

test("repinLineup fills open slots with played or unscheduled players too", () => {
  const results = [
    row("Playing", ["PG"], { roster_slot: "PG", lineup_order: 0, projection: { projected_fp: 50 } }),
    row("Started", ["C"], { week_games: [game({ status: "in_progress" })], projection: { projected_fp: 30 } }),
    row("NoSchedule", ["SG"], { schedule_state: "stale", week_games: [], projection: { projected_fp: 20 } }),
    row("Out", ["SF"], { injury_status: "Out", week_games: [], projection: { projected_fp: 40 } }),
    row("Reserve", ["PF"], { roster_slot: "IR", week_games: [], projection: { projected_fp: 35 } }),
  ];
  const daily = repinLineup(team(results, { Playing: lock("Playing") }, ["PG", "SG", "C", "BN"])).recommended_lineup;
  assert.deepEqual(daily.slots.map((s) => s.player), ["Playing", "NoSchedule", "Started"]);
  assert.ok(daily.slots[1].off_day && daily.slots[2].off_day);
  // Injured and reserve players never hold a slot.
  assert.deepEqual(daily.bench.map((p) => p.player).sort(), ["Out", "Reserve"]);
});

test("repinLineup re-derives the lineup even without locks", () => {
  const results = [row("A", ["PG"], { roster_slot: "PG", lineup_order: 0, projection: { projected_fp: 40 } })];
  const t = team(results, {});
  const daily = repinLineup(t).recommended_lineup;
  // No locks still gets a fresh optimizer pass; the saved team is not mutated.
  assert.equal(daily.pinned_slots, 0);
  assert.equal(daily.slots[0].player, "A");
  assert.equal(daily.filled_slots, 1);
  assert.equal(t.recommended_lineup.filled_slots, undefined);
  const stale = team(results, { Z: lock("Z") });
  const repinned = repinLineup(stale).recommended_lineup;
  assert.equal(repinned.pinned_slots, 0);
  assert.equal(repinned.slots[0].player, "A");
});

test("repinLineup drops pinned players from the candidate pool and optimizes the rest", () => {
  const results = [
    row("A", ["PG"], { roster_slot: "PG", lineup_order: 0, projection: { projected_fp: 10 } }),
    row("B", ["PG"], { projection: { projected_fp: 95 } }),
    row("C", ["SG"], { projection: { projected_fp: 60 } }),
  ];
  const daily = repinLineup(team(results, { A: lock("A", { locked_fp: 10 }) })).recommended_lineup;
  // Without pinning, B (95) would take PG. A stays; B must not appear twice.
  assert.equal(daily.slots[0].player, "A");
  assert.equal(daily.slots[1].player, "C");
  assert.equal(daily.slots.filter((s) => s.player === "B").length, 0);
});

test("rosterSheet marks pinned starters as locked for the gold badge", () => {
  const results = [
    row("A", ["PG"], { roster_slot: "PG", lineup_order: 0, is_locked: true, projection: { projected_fp: 20 } }),
  ];
  const view = rosterSheet(repinLineup(team(results, { A: lock("A") })));
  const starter = view.rows.find((r) => r.p.starter);
  assert.ok(starter.p.is_locked && starter.p.is_pinned);
  assert.equal(starter.p.lineup_reason, "Pinned starter (locked in Sleeper)");
  assert.equal(starter.p.locked_fp, 62.5);
});

test("sleeper_id matches the lock record even when player_id differs", () => {
  const results = [
    row("Pascal Siakam", ["PF", "C"], {
      player_id: "nba:123", sleeper_id: "8155", roster_slot: "UTIL", lineup_order: 1,
      projection: { projected_fp: 40 },
    }),
  ];
  const daily = repinLineup(team(results, {
    "8155": lock("8155", { roster_slot: "UTIL", slot_index: 1, locked_fp: 44 }),
  }, ["PG", "UTIL", "BN"])).recommended_lineup;
  assert.equal(daily.slots[1].player, "Pascal Siakam");
  assert.equal(daily.slots[1].projected_fp, 44);
});

test("locks-core validates payloads and applies lock, unlock and week expiry", async () => {
  const { validatePayload, applyLock, emptyDocument } = await import("../shared/locks-core.cjs");
  const body = {
    league_id: "1180000000000000000", schedule_week: 3, action: "lock",
    player: { player_id: "8155", player_name: "Pascal Siakam", roster_slot: "PF", slot_index: 4, locked_fp: 41.5, game_date: "2026-10-20" },
  };
  const payload = validatePayload(body);
  assert.equal(payload.player.canonical_name, "pascal siakam");
  let doc = applyLock(emptyDocument(), payload, new Date("2026-10-21T04:00:00Z"));
  assert.equal(doc.leagues["1180000000000000000"].locks["8155"].locked_fp, 41.5);
  doc = applyLock(doc, validatePayload({ ...body, action: "unlock" }));
  assert.deepEqual(doc.leagues["1180000000000000000"].locks, {});
  // A stale week cannot overwrite the container.
  doc = applyLock(doc, validatePayload({ ...body, schedule_week: 4 }), new Date("2026-10-28T04:00:00Z"));
  assert.equal(doc.leagues["1180000000000000000"].schedule_week, 4);
  for (const bad of [
    { ...body, league_id: "" },
    { ...body, action: "hold" },
    { ...body, schedule_week: null },
    { ...body, player: null },
    { ...body, player: { player_name: " " } },
  ]) {
    assert.throws(() => validatePayload(bad));
  }
});

test("locks-core archives expiring weeks instead of dropping them", async () => {
  const { validatePayload, applyLock, emptyDocument } = await import("../shared/locks-core.cjs");
  const body = {
    league_id: "1", schedule_week: 3, action: "lock",
    player: { player_id: "p1", player_name: "One", roster_slot: "PG", slot_index: 0, locked_fp: 20 },
  };
  let doc = applyLock(emptyDocument(), validatePayload(body), new Date("2026-10-22T04:00:00Z"));
  doc = applyLock(
    doc,
    validatePayload({ ...body, schedule_week: 4, player: { ...body.player, player_id: "p2", locked_fp: 30 } }),
    new Date("2026-10-29T04:00:00Z"),
  );
  let league = doc.leagues["1"];
  assert.equal(league.schedule_week, 4);
  assert.deepEqual(Object.keys(league.locks), ["p2"]);
  assert.equal(league.history["3"].schedule_week, 3);
  assert.equal(league.history["3"].locks["p1"].locked_fp, 20);
  // Another league's stale week is archived into its own history, not deleted.
  doc = applyLock(
    doc,
    validatePayload({ league_id: "2", schedule_week: 5, action: "lock", player: { player_id: "q", player_name: "Two" } }),
    new Date("2026-11-05T04:00:00Z"),
  );
  league = doc.leagues["1"];
  assert.equal(league.schedule_week, 4);
  assert.deepEqual(league.locks, {});
  assert.equal(league.history["4"].locks["p2"].locked_fp, 30);
  assert.equal(league.history["3"].locks["p1"].locked_fp, 20);
});
