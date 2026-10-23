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
test("opponent-adjusted per-game projections take precedence over the repeated baseline", () => {
  const p=forecastPlayer();
  const weds=gameFantasy(p,{date:"2026-10-21",status:"pre_game",fp:null,opponent:"CHA",proj_fp:48.2});
  const fri=gameFantasy(p,{date:"2026-10-24",status:"pre_game",fp:null,opponent:"BOS",proj_fp:61.9});
  assert.equal(weds.kind,"projection");
  assert.equal(weds.value,48.2);
  assert.match(weds.description,/vs CHA · opponent-adjusted/);
  assert.equal(fri.value,61.9);
  assert.match(fri.description,/vs BOS · opponent-adjusted/);
  assert.notEqual(weds.value,fri.value);
});
test("tiles fall back to the per-game baseline when proj_fp is absent or invalid", () => {
  const p=forecastPlayer();
  for(const proj_fp of [undefined,null,NaN,Infinity,"55.8"]){
    const s=gameFantasy(p,{date:"2026-10-21",status:"pre_game",fp:null,opponent:"NYK",proj_fp});
    assert.equal(s.value,55.8);
    assert.match(s.description,/not opponent-adjusted/);
  }
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

test("badge guide covers every new award, all tiers, and exact trigger rules", () => {
  const {badgeGuide, dailyBadges} = require("../web/insights.js");
  const guide = badgeGuide();
  assert.equal(guide.length, 44);
  assert.equal(new Set(guide.map(b => b.key)).size, guide.length);
  for (const b of guide) {
    assert.ok(b.icon && b.name && b.rule && b.group);
    assert.equal(dailyBadges({daily_badges:[{key:b.key,date:"2025-12-25",rank:1,value:10,tied:false}]},"2025-12-26").length,1);
  }
  assert.match(guide.find(b=>b.key==="unc").rule,/fantasy points.*32/);
  assert.match(guide.find(b=>b.key==="careless").rule,/−5/);
  assert.match(guide.find(b=>b.key==="shield").rule,/one steal AND one block/);
});

test("variety cap reflects mutually exclusive age badges and known birthdays", () => {
  const {varietyCap, badgeGuide} = require("../web/insights.js");
  assert.equal(badgeGuide().length, 44);
  assert.equal(varietyCap({counts: {unc: 2}}), 43);
  assert.equal(varietyCap({counts: {new_gen: 1}}), 43);
  assert.equal(varietyCap({counts: {}, age: 20}), 43);
  assert.equal(varietyCap({counts: {}, age: 33}), 43);
  assert.equal(varietyCap({counts: {}, age: 27}), 42);
  assert.equal(varietyCap({counts: {}}), 42);
  assert.equal(varietyCap(null), 42);
});
test("signed awards render, milestones have no fake ranking, streak explains average", () => {
  const {dailyBadges} = require("../web/insights.js");
  const make = (key,value,extra={}) => dailyBadges({daily_badges:[{key,value,date:"2025-12-25",rank:1,tied:false,...extra}]},"2025-12-26")[0];
  assert.match(make("careless",-5).label, /−5|-5/);
  assert.ok(make("win_low",-2));
  assert.doesNotMatch(make("milestone_pts_70",71).label, /#1/);
  assert.match(make("hot_streak",3,{season_average:25.35}).label, /season average 25.4 FP/);
});

test("performance colours share a personal baseline and inclusive near-average band", () => {
  const {performanceScore} = require("../web/insights.js");
  const p = {fp_mean_recent:40, baseline_source:"blended_seasons"};
  assert.equal(performanceScore(p,45).tone,"good");
  assert.equal(performanceScore(p,44).tone,"average");
  assert.equal(performanceScore(p,36).tone,"average");
  assert.equal(performanceScore(p,35).tone,"bad");
  assert.match(performanceScore(p,45).label,/current \+ prior season/);
  assert.equal(performanceScore(p,null).tone,"unknown");
  assert.equal(performanceScore(p,NaN).tone,"unknown");
});
test("near-zero and negative averages retain signed, stable comparisons", () => {
  const {performanceScore} = require("../web/insights.js");
  for (const baseline of [0,-10,1]) {
    const p={fp_mean_recent:baseline};
    assert.equal(performanceScore(p,baseline+2).tone,"average");
    assert.equal(performanceScore(p,baseline-2.1).tone,"bad");
    assert.equal(performanceScore(p,baseline+2.1).tone,"good");
  }
});
test("historical comparisons use observed history, exclude future rows and never use forecasts", () => {
  const {performanceBaseline,performanceScore} = require("../web/insights.js");
  const p={history_source:"prior_season",fp_mean_recent:999,projection:{projected_fp:999},history:[{date:"2025-03-01",fp:20},{date:"2025-03-02",fp:40},{date:"2026-10-22",fp:900},{date:"2025-03-03",fp:null}]};
  assert.deepEqual(performanceBaseline(p,"2026-10-21"),{value:30,source:"Prior-season history average"});
  assert.equal(performanceScore(p,40,"2026-10-21").tone,"good");
  assert.equal(performanceScore({projection:p.projection},40).tone,"unknown");
  assert.equal(performanceScore({history:[{date:"2025-01-01",fp:9}]},9).tone,"unknown");
});
test("gamesToWatch ranks today's matchups by unique rostered players across teams", () => {
  const {gamesToWatch} = require("../web/insights.js");
  const day = "2026-10-22";
  const g = (over = {}) => ({date: day, status: "pre_game", opponent: "BOS", home: true, ...over});
  const p = (name, team, over = {}) => ({player: name, player_id: name, nba_team: team, positions: ["PG"], week_games: [g()], ...over});
  const teams = [
    {id: "a", team_name: "Alpha", results: [
      p("One", "LAL"), p("Two", "LAL"), p("Shared", "LAL"),
      p("Other", "NYK", {week_games: [g({opponent: "MIA", home: false})]}),
      p("Yesterday", "CHI", {week_games: [g({date: "2026-10-21"})]}),
    ]},
    {id: "b", team_name: "Beta", results: [
      p("Shared", "LAL"), p("Three", "BOS", {week_games: [g({opponent: "LAL", home: false})]}),
      p("Four", "MIA", {week_games: [g({opponent: "NYK", home: true, status: "in_progress"})]}),
    ]},
  ];
  const games = gamesToWatch(teams, day);
  // BOS@LAL: One, Two, Shared (deduped across both rosters), Three = 4 players.
  assert.equal(games[0].key, "BOS@LAL");
  assert.equal(games[0].players.length, 4);
  assert.deepEqual(games[0].players.find(x => x.player === "Shared").teams, ["Alpha", "Beta"]);
  // NYK@MIA is second with 2 players and carries the live status through.
  assert.equal(games[1].key, "NYK@MIA");
  assert.equal(games[1].players.length, 2);
  assert.equal(games[1].status, "in_progress");
  // Yesterday's game is excluded entirely.
  assert.equal(games.length, 2);
});
