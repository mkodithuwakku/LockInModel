const { test } = require("node:test");
const assert = require("node:assert/strict");
const { prepareReport, currentDate } = require("../web/pages.js");
const fixture = () => ({
  schema_version: 1,
  date: "2026-10-15",
  generated_at: "2026-10-15T18:17:00Z",
  alerts: [],
  teams: [
    {
      results: [{ status: "LOCK", decision: "LOCK", p_lock: 0.8, p_wait: 0.2 }],
      pickups: [{ player: "Candidate" }],
    },
  ],
});
test("fresh report retains recommendations without mutating original", () => {
  const source = fixture(),
    result = prepareReport(source, new Date("2026-10-15T19:00:00Z"));
  assert.equal(result.stale, false);
  assert.equal(result.teams[0].results[0].decision, "LOCK");
  assert.equal(source.stale, undefined);
});
test("26 hour expiry removes decisions, probabilities and pickups", () => {
  const source = fixture(),
    result = prepareReport(source, new Date("2026-10-16T20:18:00Z"));
  const p = result.teams[0].results[0];
  assert.equal(p.status, "STALE");
  assert.equal(p.decision, null);
  assert.equal(p.p_lock, null);
  assert.deepEqual(result.teams[0].pickups, []);
  assert.equal(source.teams[0].results[0].decision, "LOCK");
});
test("daily report remains available across midnight", () => {
  const source = fixture();
  source.generated_at = "2026-10-16T05:45:00Z";
  assert.equal(
    prepareReport(source, new Date("2026-10-16T06:01:00Z")).stale,
    false,
  );
});
test("Edmonton date respects historical DST and permanent Alberta Time", () => {
  assert.equal(currentDate(new Date("2026-10-16T05:30:00Z")), "2026-10-15");
  assert.equal(currentDate(new Date("2025-12-16T06:30:00Z")), "2025-12-15");
  assert.equal(currentDate(new Date("2026-12-16T06:30:00Z")), "2026-12-16");
  assert.equal(currentDate(new Date("2026-12-16T05:30:00Z")), "2026-12-15");
});
test("invalid and future timestamps cannot authorize a lock", () => {
  for (const time of ["garbage", "2027-01-01T00:00:00Z"]) {
    const source = fixture();
    source.generated_at = time;
    assert.equal(
      prepareReport(source, new Date("2026-10-15T19:00:00Z")).teams[0]
        .results[0].decision,
      null,
    );
  }
});
test("unsupported report schema fails closed", () => {
  assert.throws(() => prepareReport({}), /format is invalid/);
});
test("expired offseason reports preserve season status", () => {
  const source = fixture();
  source.teams[0].results[0] = { status: "LEAGUE_COMPLETE", decision: null };
  assert.equal(
    prepareReport(source, new Date("2026-10-17T12:00:00Z")).teams[0].results[0]
      .status,
    "LEAGUE_COMPLETE",
  );
});

test("daily snapshot stays available until the next refresh plus two hour grace", () => {
  assert.equal(prepareReport(fixture(), new Date("2026-10-16T18:17:00Z")).stale, false);
  assert.equal(prepareReport(fixture(), new Date("2026-10-16T20:17:00Z")).stale, false);
  assert.equal(prepareReport(fixture(), new Date("2026-10-16T20:17:01Z")).stale, true);
});

test("previous fantasy week expires at Monday even within the daily window", () => {
  const source = fixture();
  source.date = "2026-10-18";
  source.generated_at = "2026-10-18T18:17:00Z";
  source.schedule_week = ["2026-10-12", "2026-10-18"];
  assert.equal(prepareReport(source, new Date("2026-10-19T06:01:00Z")).stale, true);
});

test("daily lineup expires at Edmonton midnight while the report stays fresh", () => {
  const source = fixture();
  source.teams[0].recommended_lineup = {date: "2026-10-15", status: "ready", slots: [{player: "A"}], bench: [], total_projected_fp: 50};
  assert.equal(prepareReport(source, new Date("2026-10-16T05:59:00Z")).teams[0].recommended_lineup.status, "ready");
  const expired = prepareReport(source, new Date("2026-10-16T06:00:00Z"));
  assert.equal(expired.stale, false);
  assert.equal(expired.teams[0].recommended_lineup.status, "unavailable");
  assert.deepEqual(expired.teams[0].recommended_lineup.slots, []);
  assert.equal(source.teams[0].recommended_lineup.slots.length, 1);
  source.refresh_status = "failed";
  assert.equal(prepareReport(source, new Date("2026-10-15T19:00:00Z")).teams[0].recommended_lineup.status, "unavailable");
});
