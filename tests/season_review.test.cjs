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
  assert.deepEqual(b.map(x=>x.icon),['🛡️','🧠','🎩','☕']);
  assert.match(b[1].label,/5\+ assists/);
  assert.match(b[3].label,/Double-double.*double-doubles/);
  assert.equal(dailyBadges(p,'2026-10-22').length,0);
});
