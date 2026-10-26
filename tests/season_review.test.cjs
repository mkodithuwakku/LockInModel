const {test} = require('node:test');
const assert = require('node:assert/strict');
const {seasonContributors, seasonHighlights, dailyBadges} = require('../web/insights.js');
function explorerTeam() {
  const log=Array.from({length:12},(_,i)=>({player_id:'1',player:'One',date:`2026-10-${String(i+1).padStart(2,'0')}`,
    fp:i-2,baseline_fp:i>=3?0:null,baseline_games:Math.min(i,10),delta:i>=3?i-2:null,
    opponent:i%2?'NYK':'BOS',venue:i%2?'away':'home',result:i%3?'W':'L',days_since_previous:i?1:null,
    stats:{PTS:i,REB:10,AST:3,TOV:1,MIN:20,FGM:2,FGA:i+4,FG3M:1,FG3A:3,FTM:1,FTA:2},
    scoring:{PTS:i,TOV:-2},double_double:false,triple_double:false}));
  return {results:[{player_id:'1',player:'One',positions:['PG'],starter:true},{player_id:'2',player:'Missing',positions:['C'],starter:false}],
    season_review:{status:'ready',as_of:'2026-10-12',game_log:log}};
}
test('season explorer scopes every analysis to inclusive dates and known context',()=>{
  const {seasonExplorer}=require('../web/insights.js'), team=explorerTeam(), before=JSON.stringify(team);
  const full=seasonExplorer(team,{range:'season'});
  assert.equal(full.summary.games,12);assert.equal(full.players.length,2);
  assert.equal(full.players[1].total_fp,null);
  assert.equal(full.players[0].change,5);
  assert.equal(full.top_three_share,100);
  assert.equal(full.effective_contributors,1);
  assert.equal(full.distribution.reduce((n,b)=>n+b.count,0),12);
  assert.equal(full.records.worst.fp,-2);
  const week=seasonExplorer(team,{range:'7'});
  assert.equal(week.from,'2026-10-06');assert.equal(week.games.length,7);
  const filtered=seasonExplorer(team,{range:'custom',from:'2026-10-04',to:'2026-10-08',venue:'away'});
  assert.deepEqual(filtered.games.map(g=>g.date),['2026-10-04','2026-10-06','2026-10-08']);
  assert.equal(filtered.players[0].change,null);
  assert.equal(filtered.games[0].baseline_games,3); // Scope never reconstructs pregame baselines.
  assert.equal(seasonExplorer(team,{from:'2026-10-12',to:'2026-10-01'}).summary.total_fp,null);
  assert.equal(JSON.stringify(team),before);
});
test('season aggregation pools attempts, gates partial stats and quartiles, and preserves zeros',()=>{
  const {seasonAggregate}=require('../web/insights.js'), games=explorerTeam().season_review.game_log;
  const a=seasonAggregate(games);
  assert.equal(a.stats.FG_PCT,24/114*100);
  assert.equal(a.stats.AST_TOV,3);assert.equal(a.forty,0);
  assert.equal(a.stats.BLK,null);
  assert.equal(a.floor_fp,.75);assert.equal(a.ceiling_fp,6.25);
  const incomplete=seasonAggregate([games[0],{...games[1],stats:{...games[1].stats,MIN:null}}]);
  assert.equal(incomplete.stats.MIN,null);assert.equal(incomplete.stats.FP_PER_MIN,null);
  assert.equal(incomplete.coverage.MIN,1);assert.equal(incomplete.spread,null);
  const zero=seasonAggregate([{...games[0],fp:0}]);
  assert.equal(zero.total_fp,0);assert.equal(zero.average_fp,0);
  assert.equal(seasonAggregate([]).total_fp,null);
});
test('roster and archive filters handle unknown data, negative games, and CSV quoting',()=>{
  const {seasonExplorer,seasonPlayerRows,seasonLogRows,seasonCsv}=require('../web/insights.js');
  const x=seasonExplorer(explorerTeam());
  assert.equal(seasonPlayerRows(x,{minimum:1}).length,1);
  assert.equal(seasonPlayerRows(x,{position:'C'})[0].player,'Missing');
  assert.equal(seasonPlayerRows(x,{metric:'stat:TS_PCT'})[0].player,'One');
  assert.equal(seasonLogRows(x,{metric:'low_fp'})[0].fp,-2);
  assert.equal(seasonLogRows(x,{kind:'below'}).length,0);
  assert.equal(seasonLogRows(x,{search:'nyk'}).length,6);
  assert.equal(seasonLogRows(x,{metric:'fp'})[0].fp,9);
  const csv=seasonCsv([{...x.games[0],player:'=HYPERLINK(\"bad\")'}]);
  assert.match(csv,/'=HYPERLINK\(\"\"bad\"\"\)/);
  assert.match(csv,/"-2"/);
  assert.match(csv,/FP_FROM_TOV/);
});
test('comparison separates roster quality from volume and preserves missing and negative values', () => {
  const {comparisonTeams} = require('../web/insights.js');
  const comparison = {teams:[
    {team_id:'big',team_name:'Big',total_fp:1200,players:Array.from({length:12},(_,i)=>({player:String(i),games:10,average_fp:10}))},
    {team_id:'small',team_name:'Small',total_fp:700,players:Array.from({length:7},(_,i)=>({player:String(i),games:5,average_fp:20}))},
    {team_id:'negative',team_name:'Negative',total_fp:-10,players:[{player:'Bad',games:1,average_fp:-10}]},
    {team_id:'missing',team_name:'Missing',total_fp:null,players:[]},
  ]};
  const before=JSON.stringify(comparison);
  const rows=comparisonTeams(comparison);
  assert.deepEqual(rows.map(t=>t.team_id),['small','big','negative','missing']);
  assert.equal(rows[0].top_five,20); assert.equal(rows[0].depth,20);
  assert.equal(rows[2].top_five,null);
  assert.equal(comparisonTeams(comparison,'total_fp')[0].team_id,'big');
  assert.equal(JSON.stringify(comparison),before);
});
test('player rankings deduplicate shared players, filter samples and positions, and sort advanced rates', () => {
  const {comparisonPlayers} = require('../web/insights.js');
  const a={player_id:'1',player:'A',games:5,positions:['PG'],average_fp:20,stats:{TS_PCT:60,PTS:50}};
  const b={player_id:'2',player:'B',games:10,positions:['C'],average_fp:20,stats:{TS_PCT:null,PTS:200}};
  const comparison={teams:[{team_id:'one',team_name:'One',season:'2026',players:[a,b]},
    {team_id:'two',team_name:'Two',season:'2026',players:[a]}]};
  assert.deepEqual(comparisonPlayers(comparison).map(p=>p.rank),[1,1]);
  assert.deepEqual(comparisonPlayers(comparison)[0].teams,['One','Two']);
  assert.equal(comparisonPlayers(comparison,{team:'two'})[0].team_id,'two');
  assert.equal(comparisonPlayers(comparison,{minimum:10})[0].player,'B');
  assert.equal(comparisonPlayers(comparison,{position:'PG',minimum:10}).length,0);
  assert.equal(comparisonPlayers(comparison,{metric:'stat:TS_PCT'})[1].rank,null);
  assert.equal(comparisonPlayers(comparison,{metric:'pergame:PTS'})[0].player,'B');
  assert.equal(comparisonPlayers(comparison,{search:'b'})[0].player,'B');
});
test('choke what-if only uses the exact banked result and requires a strict winning margin', () => {
  const {filmSpotlight} = require('../web/insights.js');
  const film={locked:[{player_id:1,date:'2026-10-21',fp:10}],performances:[
    {player:'Banked',player_id:'1',date:'2026-10-21',fp:10,delta:-20},
    {player:'Bench',player_id:'2',date:'2026-10-21',fp:0,delta:-50},
    {player:'Wrong night',player_id:'1',date:'2026-10-22',fp:1,delta:-30},
  ]};
  assert.equal(filmSpotlight(film,19).flips[0].player,'Banked');
  assert.equal(filmSpotlight(film,20).flips.length,0);
  assert.equal(filmSpotlight(film).flips.length,0);
  assert.equal(filmSpotlight({...film,locked:[{player_id:1,date:'2026-10-21',fp:15}]},1).player,undefined);
});
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
