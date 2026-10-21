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

const { rosterSheet } = require("../web/insights.js");
const lineupFixture = () => ({
  results: [
    {player:"Original starter", player_id:"1", starter:true, roster_slot:"PG", positions:["PG"]},
    {player:"Better guard", player_id:"2", starter:false, roster_slot:"BN", positions:["PG", "SG"]},
    {player:"Reserve", player_id:"3", starter:false, roster_slot:"IR"},
    {player:"Center", player_id:"4", starter:true, roster_slot:"C", positions:["C"]},
  ],
  recommended_lineup: {date:"2026-10-20", status:"ready", slots:[
    {slot:"PG", player:"Better guard", player_id:2, projected_fp:50},
    {slot:"UTIL", player:"Center", player_id:"4", projected_fp:40},
    {slot:"UTIL", player:null},
  ], bench:[{player:"Original starter",player_id:"1",reason:"No game today"}]},
});
test("roster sheet promotes optimizer choices, preserves vacant slots and canonical detail indexes", () => {
  const t = lineupFixture(), before = JSON.stringify(t), view = rosterSheet(t);
  assert.equal(view.recommended, true);
  assert.deepEqual(view.rows.map(r=>r.i), [1,3,null,0,2]);
  assert.deepEqual(view.rows.map(r=>r.p.roster_slot), ["PG","UTIL","UTIL","BN","IR"]);
  assert.equal(view.rows[0].p.lineup_fp,50);
  assert.equal(view.rows[2].p.vacant,true);
  assert.equal(view.rows[3].p.starter,false);
  assert.equal(view.rows[3].p.lineup_reason,"No game today");
  assert.equal(JSON.stringify(t),before);
});
test("unavailable plans and Test Week retain original roster selection", () => {
  const t = lineupFixture();
  assert.equal(rosterSheet(t,false).recommended,false);
  assert.equal(rosterSheet(t,false).rows[0].p.starter,true);
  t.recommended_lineup.status="unavailable";
  assert.equal(rosterSheet(t).recommended,false);
});
test("missing or duplicated selected players cannot masquerade as a valid roster plan", () => {
  const t = lineupFixture();
  t.recommended_lineup.slots[0].player_id="missing";
  assert.equal(rosterSheet(t).recommended,false);
  t.recommended_lineup.slots[0].player_id="4";
  assert.equal(rosterSheet(t).recommended,false);
});
test("no-game snapshot leaves active slots empty and all real players on bench or reserve", () => {
  const t = lineupFixture();
  t.recommended_lineup = {status:"no_games",slots:[{slot:"PG",player:null}],bench:[]};
  const view = rosterSheet(t);
  assert.equal(view.recommended,true);
  assert.equal(view.rows.filter(r=>r.p.starter&&!r.p.vacant).length,0);
  assert.equal(view.rows.filter(r=>!r.p.starter).length,4);
});

const { gameFantasy } = require("../web/insights.js");
const forecastPlayer = () => ({schedule_state:"verified", projection:{projected_fp:55.8,as_of:"2026-10-21"}});
test("each upcoming matchup shows the saved per-game estimate without inventing opponent adjustments", () => {
  const p=forecastPlayer();
  for(const date of ["2026-10-21","2026-10-24","2026-10-25"]){
    const score=gameFantasy(p,{date,status:"pre_game",fp:null});
    assert.equal(score.kind,"projection");
    assert.equal(score.value,55.8);
    assert.match(score.description,/not opponent-adjusted/);
  }
});
test("observed scores, including zero and negatives, replace projected points", () => {
  for(const fp of [0,-4.5,61.2]){
    const score=gameFantasy(forecastPlayer(),{date:"2026-10-21",status:"complete",fp});
    assert.equal(score.kind,"actual");
    assert.equal(score.label,"Final");
    assert.equal(score.value,fp);
  }
});
test("missing final scores and postponed games never masquerade as projected or zero results", () => {
  for(const status of ["complete","final","post_game","postponed","canceled","cancelled"]){
    const score=gameFantasy(forecastPlayer(),{date:"2026-10-21",status,fp:null});
    assert.equal(score.kind,"unavailable");
    assert.equal(score.value,null);
  }
});
test("a present-day forecast is not backfilled into historical games", () => {
  assert.equal(gameFantasy(forecastPlayer(),{date:"2026-10-20",status:"pre_game"}).kind,"unavailable");
});
test("missing forecasts, invalid values, dates and unknown schedules remain unavailable", () => {
  const game={date:"2026-10-21",status:"pre_game"};
  for(const value of [null,undefined,NaN,Infinity,"55.8"]){
    const p=forecastPlayer();p.projection.projected_fp=value;
    assert.equal(gameFantasy(p,game).value,null);
  }
  assert.equal(gameFantasy({...forecastPlayer(),schedule_state:"unknown"},game).kind,"unavailable");
  assert.equal(gameFantasy(forecastPlayer(),{status:"pre_game"}).kind,"unavailable");
  assert.equal(gameFantasy(forecastPlayer(),{...game,status:"unknown"}).kind,"unavailable");
});
test("zero forecasts remain valid projections and in-progress games retain the saved estimate", () => {
  const p=forecastPlayer();p.projection.projected_fp=0;
  assert.equal(gameFantasy(p,{date:"2026-10-21",status:"in_progress"}).value,0);
  assert.equal(gameFantasy(p,{date:"2026-10-21",status:"pre_game"}).kind,"projection");
});

test("new daily badges label league scoring, saved forecast coverage and nonpositive low rates", () => {
  const daily = require("../web/insights.js").dailyBadges;
  const base={date:"2026-10-20",rank:1,tied:false,scope:"league_nba"};
  const result=daily({daily_badges:[
    {...base,key:"overachiever",value:12,actual_fp:32,projected_fp:20,forecast_count:60,player_count:68},
    {...base,key:"inefficient",value:-.125},
    {...base,key:"inefficient",value:0},
    {...base,key:"efficient",value:1.234},
    {...base,key:"merchant",value:10,scope:undefined},
    {...base,key:"heartbreak",value:8,scope:undefined},
  ]},"2026-10-21");
  assert.equal(result.length,6);
  assert.match(result[0].label,/32 actual vs 20 projected/);
  assert.match(result[0].label,/60\/68 players with saved forecasts/);
  assert.match(result[1].label,/-0.13 FP\/min \(lowest\)/);
  assert.equal(result[2].value,0);
  assert.match(result[3].label,/NBA · league scoring/);
  assert.equal(result[4].icon,"🧾");
  assert.equal(result[5].icon,"💔");
});
