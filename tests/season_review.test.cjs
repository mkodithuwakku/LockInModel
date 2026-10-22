const {test} = require('node:test');
const assert = require('node:assert/strict');
const {seasonContributors, seasonHighlights, dailyBadges} = require('../web/insights.js');
test('season contributors preserve detail indexes and empty roster placeholders', () => {
  const t = {results:[{player_id:'1',player:'One'}, {player_id:'2',player:'Two'}, {player_id:null,player:'Unknown'}],season_review:{players:[{player_id:'2',player:'Two',games:1,total_fp:40,average_fp:40}]}};
  const rows = seasonContributors(t);
  assert.equal(rows[0].player, 'Two'); assert.equal(rows[0].index, 1);
  assert.equal(rows.length, 3); assert.equal(rows[1].total_fp, undefined);
  assert.equal(seasonHighlights(rows).scorer.player, 'Two');
  assert.equal(seasonHighlights(rows).mover, undefined);
  assert.equal(seasonHighlights(rows).swing, undefined);
});
test('highlights enforce samples and pick metrics separately without mutating order', () => {
  const rows = [{player:'A',games:10,total_fp:300,average_fp:30,change:-3,spread:5}, {player:'B',games:5,total_fp:200,average_fp:40,change:10,spread:15}];
  const h = seasonHighlights(rows);
  assert.equal(h.anchor.player,'A'); assert.equal(h.scorer.player,'B');
  assert.equal(h.mover.player,'A'); assert.equal(h.swing.player,'B');
  assert.equal(rows[0].player,'A');
});
test('new daily indicators have accessible stat labels and expire normally', () => {
  const p = {daily_badges:['shield','creator','magician','coffee'].map(key=>({key,date:'2026-10-20',rank:1,value:1}))};
  const b = dailyBadges(p,'2026-10-21');
  assert.deepEqual(b.map(x=>x.icon),['📈','🧠','🎩','☕']);
  assert.match(b[1].label,/5\+ assists/);
  assert.match(b[3].label,/Double-double.*double-doubles/);
  assert.equal(dailyBadges(p,'2026-10-22').length,0);
});

test('season badge leaderboard filters current roster without changing NBA-earned totals', () => {
  const {seasonBadgeLeaders} = require('../web/insights.js');
  const t = {results:[{player_id:'2',player:'Current name',nba_team:'BOS'},{player_id:'3',player:'Three'}],season_badges:{players:[
    {player_id:'1',player:'Outside',total:12,negative:1,variety:6,milestones:2,counts:{sniper:4}},
    {player_id:'2',player:'Two',total:10,negative:5,variety:4,milestones:3,counts:{sniper:3}},
    {player_id:'3',player:'Three',total:10,negative:0,variety:4,milestones:3,counts:{sniper:3}},
    {player_id:'4',player:'Four',total:8,negative:1,variety:2,milestones:0,counts:{sniper:1}},
  ]}};
  const before=JSON.stringify(t);
  assert.deepEqual(seasonBadgeLeaders(t).map(p=>p.rank),[1,1]);
  assert.equal(seasonBadgeLeaders(t)[0].player,'Current name');
  assert.deepEqual(seasonBadgeLeaders(t,'total','nba').map(p=>p.rank),[1,2,2,4]);
  assert.equal(seasonBadgeLeaders(t,'sniper')[0].count,3);
  assert.equal(seasonBadgeLeaders(t,'negative').length,1);
  assert.deepEqual(seasonBadgeLeaders(t,'unknown'),[]);
  assert.equal(JSON.stringify(t),before);
  assert.deepEqual(seasonBadgeLeaders({results:[]}),[]);
});

test('badge cards resolve NBA identities outside roster, including players owned elsewhere', () => {
  const {badgePlayer} = require('../web/insights.js');
  const t = {results:[{player_id:1,player:'Roster',status:'WAIT'}],pickups:[{player_id:'2',player:'Pickup',recent_fp:20}],available_players:[{player_id:'3',player:'Available',recent_fp:0}],season_badges:{players:[
    {player_id:'1',player:'Old roster name',total:4},
    {player_id:2,player:'Two',total:3},
    {player_id:3,player:'Three',total:2},
    {player_id:'4',player:'OG Anunoby',nba_team:'NYK',total:2},
  ]}};
  const before = JSON.stringify(t);
  assert.strictEqual(badgePlayer(t,'1'),t.results[0]);
  assert.equal(badgePlayer(t,'2').recent_fp,20);
  assert.equal(badgePlayer(t,3).recent_fp,0);
  assert.equal(badgePlayer(t,4).player,'OG Anunoby');
  assert.equal(badgePlayer(t,4).badge_profile,true);
  assert.equal(badgePlayer(t,4).status,undefined);
  assert.equal(badgePlayer(t,'missing'),null);
  assert.equal(badgePlayer(t,null),null);
  assert.equal(JSON.stringify(t),before);
});

test('player badge section uses league season totals, repeats and distinct types', () => {
  const {playerSeasonBadges} = require('../web/insights.js');
  const t = {season_badges:{status:'ready',players:[{player_id:'7',total:8,negative:2,milestones:1,variety:3,counts:{sniper:5,bricks:2,coffee:1}}]}};
  const b = playerSeasonBadges(t,7);
  assert.equal(b.total,8); assert.equal(b.negative,2); assert.equal(b.milestones,1); assert.equal(b.variety,3);
  assert.deepEqual(b.earned.map(x=>[x.key,x.count]),[['sniper',5],['bricks',2],['coffee',1]]);
  assert.equal(playerSeasonBadges(t,'not-awarded').total,0);
  assert.equal(playerSeasonBadges({...t,season_badges:{...t.season_badges,status:'saved'}},7).total,8);
  assert.equal(playerSeasonBadges({season_badges:{...t.season_badges,status:'unavailable'}},7).total,null);
  assert.equal(playerSeasonBadges({},7).available,false);
  assert.equal(playerSeasonBadges(t,null).available,false);
  assert.equal(playerSeasonBadges({season_badges:{status:'empty',players:[]}},7).total,0);
  const otherLeague = {season_badges:{status:'ready',players:[{...t.season_badges.players[0],total:1,counts:{sniper:1}}]}};
  assert.equal(playerSeasonBadges(otherLeague,7).total,1);
  assert.equal(playerSeasonBadges(t,7).total,8);
});
