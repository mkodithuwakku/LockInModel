const { test } = require("node:test");
const assert = require("node:assert/strict");
const { teamForm, sparkline } = require("../web/insights.js");
const player = (scores) => ({ player: "Sample", history: scores.map((fp, i) => ({ date: `2025-12-${String(i + 1).padStart(2, "0")}`, fp })) });

test("form compares disjoint five-game windows, preserving roster lookup", () => {
  const roster = [player(Array(10).fill(2)), player([1, 1, 1, 1, 1, 10, 20, 30, 40, 50])];
  const copy = JSON.stringify(roster);
  const rows = teamForm(roster, "2025-12-10");
  assert.equal(rows[0].index, 1);
  assert.equal(rows[0].average, 30);
  assert.equal(rows[0].delta, 29);
  assert.equal(JSON.stringify(roster), copy);
});
test("sparse history reports its actual average without inventing a comparison", () => {
  const [row] = teamForm([player([10, 20, 30])]);
  assert.equal(row.average, 20);
  assert.equal(row.scores.length, 3);
  assert.equal(row.delta, null);
  assert.equal(teamForm([player(Array(9).fill(10))])[0].delta, null);
});
test("missing and invalid values differ from zero and negative fantasy points", () => {
  const rows = teamForm([player([null, undefined, NaN, Infinity, "40"]), player([0]), player([-5])]);
  assert.deepEqual(rows.map((row) => row.average), [0, -5, null]);
  assert.deepEqual(rows.map((row) => row.index), [1, 2, 0]);
});
test("future observations cannot leak into form and input order is irrelevant", () => {
  const p = player([10, 20, 999]);
  p.history.reverse();
  const [row] = teamForm([p], "2025-12-02");
  assert.deepEqual(row.scores, [10, 20]);
  assert.equal(row.average, 15);
});
test("empty rosters and single or constant-score charts remain usable", () => {
  assert.deepEqual(teamForm([]), []);
  for (const scores of [[], [0], [-5], [20, 20, 20], [-5, 0, 25]]) {
    assert.doesNotMatch(sparkline(scores), /NaN|Infinity|undefined/);
  }
});

test("daily badges expire by calendar date and retain human-readable ties", () => {
  const { dailyBadges, previousDate } = require("../web/insights.js");
  const p = {daily_badges: [{key:"sniper", date:"2025-12-31", rank:3, value:5, tied:true}]};
  assert.equal(previousDate("2026-01-01"), "2025-12-31");
  assert.equal(dailyBadges(p, "2026-01-01")[0].label, "Sniper · Tied #3 NBA-wide · 5 made threes · 2025-12-31");
  assert.deepEqual(dailyBadges(p, "2026-01-02"), []);
  assert.deepEqual(dailyBadges(p, "2025-12-31"), []);
  assert.deepEqual(dailyBadges({daily_badges:[{...p.daily_badges[0],key:"unknown"}]}, "2026-01-01"), []);
  assert.deepEqual(dailyBadges({daily_badges:[{...p.daily_badges[0],value:null}]}, "2026-01-01"), []);
});
