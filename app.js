"use strict";
const hosted = document.documentElement.dataset.hosting === "pages";
let publishedSource = null;
const $ = (s) => document.querySelector(s);
const esc = (v) =>
  String(v ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const fmt = (v, d = 1) => (v == null ? "—" : Number(v).toFixed(d));
let state = {
  data: null,
  team: localStorage.getItem("lockin-team"),
  view: "team",
  filter: "all",
  search: "",
  availableLimit: 30,
  mode: "live",
  request: 0,
  archived: false,
  csrf: "",
  busy: false,
  insightsExpanded: false,
  badgeScope: "nba",
  badgeMetric: "total",
  reviewTab: "review",
  compareMetric: "roster_average",
  compareFilters: {team:"", position:"", minimum:1, metric:"average_fp", search:""},
  filmMargins: {},
  filmFilter: "all",
  seasonContexts: {},
};
const statuses = {
  BANKED: ["BANKED", "lock"],
  PRE_DRAFT: ["AWAITING DRAFT", ""],
  DRAFTING: ["DRAFTING", ""],
  LEAGUE_COMPLETE: ["SEASON FINISHED", ""],
  LOCK: ["LOCK", "lock"],
  WAIT: ["WAIT", "wait"],
  SCHEDULE_UNAVAILABLE: ["CHECK SCHEDULE", "review"],
  SCORING_INCOMPLETE: ["SCORING GAP", "review"],
  DATA_UNAVAILABLE: ["DATA ISSUE", "review"],
  UNRESOLVED: ["UNMATCHED", "review"],
  NO_GAME: ["NO GAME", ""],
  NO_HISTORY: ["NO HISTORY", ""],
  UPCOMING: ["UPCOMING", "upcoming"],
  STALE: ["STALE DATA", "review"],
};
const team = () =>
  state.data?.teams.find((t) => t.id === state.team) || state.data?.teams[0];
function portrait(p, nbaWide = false) {
  const initials = (p.player || "")
    .split(" ")
    .map((x) => x[0])
    .slice(0, 2)
    .join("");
  const id = String(p.player_id || "");
  const imageUrl = hosted || nbaWide
    ? hosted && state.data?.portraits?.includes(id)
      ? `./portraits/${encodeURIComponent(id)}.png`
      : `https://cdn.nba.com/headshots/nba/latest/260x190/${encodeURIComponent(id)}.png`
    : `/api/portrait/${encodeURIComponent(id)}`;
  return `<div class="portrait"><span class="initials">${esc(initials)}</span>${/^\d+$/.test(id) ? `<img src="${imageUrl}" alt="${esc(p.player)}" loading="lazy">` : ""}</div>`;
}
// Stable NBA IDs keep provider abbreviations independent of logo URLs.
const nbaTeamIds = {
  ATL: 1610612737, BOS: 1610612738, CLE: 1610612739, NOP: 1610612740,
  CHI: 1610612741, DAL: 1610612742, DEN: 1610612743, GSW: 1610612744,
  HOU: 1610612745, LAC: 1610612746, LAL: 1610612747, MIA: 1610612748,
  MIL: 1610612749, MIN: 1610612750, BKN: 1610612751, NYK: 1610612752,
  ORL: 1610612753, IND: 1610612754, PHI: 1610612755, PHX: 1610612756,
  POR: 1610612757, SAC: 1610612758, SAS: 1610612759, OKC: 1610612760,
  TOR: 1610612761, UTA: 1610612762, MEM: 1610612763, WAS: 1610612764,
  DET: 1610612765, CHA: 1610612766,
};
function nbaTeamLabel(value) {
  const abbreviation = String(value || "").trim().toUpperCase();
  const aliases = { GS: "GSW", NY: "NYK", NO: "NOP", SA: "SAS", PHO: "PHX", BRK: "BKN" };
  const canonical = aliases[abbreviation] || abbreviation;
  const id = Object.hasOwn(nbaTeamIds, canonical) ? nbaTeamIds[canonical] : null;
  return `<span class="nba-team">${id ? `<img class="nba-team-logo" src="https://cdn.nba.com/logos/nba/${id}/primary/D/logo.svg" alt="" aria-hidden="true" width="14" height="14" loading="lazy" decoding="async" referrerpolicy="no-referrer">` : ""}${esc(abbreviation || "FA / unknown")}</span>`;
}
// Small header accents, kept separate from green/yellow/red performance colours.
const nbaTeamAccents = {
  ATL: "#e56372", BOS: "#56ae86", BKN: "#aab4bd", CHA: "#51bac4", CHI: "#df6272",
  CLE: "#c57f91", DAL: "#559ed8", DEN: "#d7b66b", DET: "#eb7382", GSW: "#e2bf59",
  HOU: "#e66577", IND: "#d8b966", LAC: "#e27483", LAL: "#b391da", MEM: "#81a9d6",
  MIA: "#dd6983", MIL: "#76ac8c", MIN: "#6dabb5", NOP: "#b6a171", NYK: "#ec9a64",
  OKC: "#62b7de", ORL: "#64abe0", PHI: "#669fdb", PHX: "#cb96dc", POR: "#dc717b",
  SAC: "#a68ac9", SAS: "#bec7cb", TOR: "#df7582", UTA: "#9a91d2", WAS: "#7b9bbf",
};
const nbaTeamAliases = {GS: "GSW", NY: "NYK", NO: "NOP", SA: "SAS", PHO: "PHX", BRK: "BKN"};
function teamAccent(value) {
  const code = String(value || "").trim().toUpperCase();
  return nbaTeamAccents[nbaTeamAliases[code] || code] || "#b39acb";
}
function playerPerformance(p, value) {
  return LockInInsights.performanceScore(p, value, state.data.observation_cutoff || state.data.date);
}
function performanceNumber(p, value, suffix = "") {
  const score = playerPerformance(p, value);
  return `<span class="performance-score" data-performance="${score.tone}" title="${esc(score.label)}" aria-label="${esc(fmt(value) + ' FP · ' + score.label)}">${fmt(value)}${suffix}</span>`;
}
function performanceLegend(p) {
  const baseline = LockInInsights.performanceBaseline(p, state.data.observation_cutoff || state.data.date);
  if (!baseline) return '<p class="performance-note">Game colours need a usable personal average. Missing comparisons stay neutral.</p>';
  const band = Math.max(2, Math.abs(baseline.value) * .1);
  return `<div class="performance-legend"><span data-performance="good">● Above</span><span data-performance="average">● Near</span><span data-performance="bad">● Below</span><small>${esc(baseline.source)}: ${fmt(baseline.value)} FP · near = ±${fmt(band)} FP</small></div><p class="performance-note">Colours compare completed games with this report’s personal average (±10%, minimum 2 FP). Green flags a strong game to review; the lock call also weighs remaining chances and uncertainty.</p>`;
}
function teamPicture(t) {
  const initials = t.team_name.trim().split(/\s+/).map(n => n[0]).slice(0, 2).join("");
  let url = null;
  try {
    const parsed = new URL(t.team_avatar_url);
    if (parsed.protocol === "https:" && parsed.host === "sleepercdn.com" &&
        /^\/(uploads|avatars)\//.test(parsed.pathname) && !parsed.username && !parsed.password)
      url = parsed.href;
  } catch (_) { /* Local/sample teams can have no photo. */ }
  return `<span class="team-symbol" aria-hidden="true"><span class="initials">${esc(initials)}</span>${url ? `<img src="${esc(url)}" alt="" referrerpolicy="no-referrer" decoding="async">` : ""}</span>`;
}
function attachImageFallback() {
  document.querySelectorAll(".portrait img, .team-symbol img, .nba-team-logo").forEach((img) => {
    const container = img.closest(".portrait, .team-symbol, .nba-team");
    const loaded = () => container.classList.add("is-loaded");
    const failed = () => {
      container.classList.remove("is-loaded");
      img.remove();
    };
    img.addEventListener("load", loaded, { once: true });
    img.addEventListener("error", failed, { once: true });
    if (img.complete) {
      if (img.naturalWidth) loaded();
      else failed();
    }
  });
}
function rowStatus(p) {
  if (p.is_locked) return "LOCKED";
  if (p.status === "WAIT" && p.last_game_fp != null &&
      playerPerformance(p, p.last_game_fp).tone === "bad") return "WAIT_LOW";
  return p.status;
}
function badge(p) {
  if (p.is_locked)
    return `<span class="status locked-in" title="You marked this player locked in Sleeper">LOCKED</span>`;
  const [label, cls] = statuses[p.status] || ["REVIEW", "review"];
  const tone = rowStatus(p) === "WAIT_LOW" ? "wait wait-low" : cls;
  return `<span class="status ${tone}">${p.status === "LOCK" ? "✓ " : p.status === "WAIT" ? "↗ " : ""}${label}</span>`;
}
function toast(message) {
  $("#toast").textContent = message;
  $("#toast").hidden = false;
  setTimeout(() => ($("#toast").hidden = true), 5500);
}
function fail(message) {
  $("#error").textContent = message;
  $("#error").hidden = false;
}
async function api(path, body) {
  if (hosted) {
    if (body || !path.startsWith("/api/dashboard?"))
      throw new Error(
        "This published dashboard is read-only. Manage your teams in Sleeper.",
      );
    const response = await fetch(`./report.json?check=${Date.now()}`, {
      cache: "no-store",
    });
    if (!response.ok)
      throw new Error(
        "Could not load the published report. Please reload shortly.",
      );
    const source = await response.json();
    const result = LockInPages.prepareReport(source);
    publishedSource = source;
    return result;
  }
  let response = await fetch(path, {
    method: body ? "POST" : "GET",
    headers: body
      ? { "Content-Type": "application/json", "X-CSRF-Token": state.csrf }
      : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  let data = await response.json();
  if (!response.ok)
    throw new Error(data.error || "Request failed. Please try again.");
  return data;
}
async function load() {
  const requestId = ++state.request;
  document
    .querySelectorAll(".nav")
    .forEach((b) =>
      b.classList.toggle(
        "active",
        b.dataset.view === (state.mode === "test" ? "test" : state.view),
      ),
    );
  $("#test-controls").hidden = state.mode !== "test";
  $("#error").hidden = true;
  state.data = null;
  $("#summary").innerHTML = "";
  $("#team-insights").innerHTML = "";
    $("#recommended-lineup").innerHTML = "";
    $("#recommended-lineup").hidden = true;
  $("#content").innerHTML =
    '<div class="loading"><div class="spinner"></div>Reading saved player data…</div>';
  try {
    const data = await api(
      state.mode === "test"
        ? "/api/test-week"
        : "/api/dashboard?mode=live&archived=" + Number(state.archived),
    );
    if (requestId !== state.request) return;
    state.data = data;
    state.team = team()?.id;
    render();
    syncLocks();
  } catch (e) {
    if (requestId !== state.request) return;
    state.data = null;
    if (hosted) publishedSource = null;
    $("#summary").innerHTML = "";
    $("#team-insights").innerHTML = "";
    $("#recommended-lineup").innerHTML = "";
    $("#recommended-lineup").hidden = true;
    $("#content").innerHTML = hosted
      ? '<div class="empty">The published report could not be loaded. Try Reload report.</div>'
      : '<div class="empty">No current recommendations available.<br>Use Test Week to practice with saved historical data.</div>';
    fail(e.message);
  }
}
function render() {
  if (hosted && publishedSource)
    state.data = LockInPages.prepareReport(publishedSource);
  if (!state.data) return;
  state.data.alerts = state.data.alerts.filter(a => a.severity !== "info");
  const t = team();
  $("#test-controls").hidden = state.mode !== "test";
  $("#archive-control").hidden = hosted || state.mode === "test";
  $("#mode-label").textContent = hosted
    ? "DAILY REPORT · READ ONLY"
    : state.mode === "test"
      ? "TEST WEEK · OFFLINE"
      : "LIVE WORKSPACE";
  $(".right-rail").hidden = !t || state.view !== "team";
  $(".content-layout").classList.toggle("without-insights", !t || state.view !== "team");
  if (!t) {
    $("#team-insights").innerHTML = "";
    $("#recommended-lineup").innerHTML = "";
    $("#recommended-lineup").hidden = true;
    $("#notice").textContent = state.data.notice || "Waiting for a report.";
    $("#freshness").textContent =
      "Report " + new Date(state.data.generated_at).toLocaleString();
    $("#alert-count").textContent = state.data.alerts.length;
    if (state.data.alerts.length)
      fail(state.data.alerts.map((a) => a.message).join(" "));
    $("#team-list").innerHTML = "";
    $("#team-count").textContent = "0";
    $("#page-title").textContent = "Your next season starts here.";
    $("#page-subtitle").textContent = hosted
      ? "No leagues available in the latest published report."
      : "Sync Sleeper to load your leagues, or open Test Week to practice.";
    $("#content").innerHTML =
      '<div class="empty">No leagues in this view.</div>';
    return;
  }
  state.team = t.id;
  $("#team-count").hidden = state.mode === "test";
  $("#team-count").textContent = state.data.teams.length;
  $("#alert-count").textContent = state.data.alerts.length;
  $("#team-list").innerHTML = state.data.teams
    .map(
      (t) =>
        `<button class="team-nav ${t.id === state.team ? "active" : ""}" data-team="${esc(t.id)}" ${t.id === state.team ? 'aria-current="true"' : ""}>${teamPicture(t)}<span class="label"><strong>${esc(t.team_name)}</strong><small>${esc(t.league_name)}${t.source === "sleeper" ? " · " + esc(t.season) + (t.archived ? " · ARCHIVED" : "") : " · TEST"}</small></span></button>`,
    )
    .join("");
  $("#page-title").textContent =
    state.view === "review" ? "Your season." : state.view === "rise"
      ? "The waiver wire."
      : state.view === "alerts"
        ? "Check the tape."
        : state.view === "games"
          ? "Games to watch."
          : state.view === "badges"
            ? "Season awards."
            : t.team_name;
  $("#sheet-title").innerHTML =
    state.view === "review" ? "Season review<span>.</span>" : state.view === "rise"
      ? "On the rise<span>.</span>"
      : state.view === "alerts"
        ? "Data report<span>.</span>"
        : state.view === "games"
          ? "Tonight's slate<span>.</span>"
          : state.view === "badges"
            ? "Badge race<span>.</span>"
            : "Roster sheet<span>.</span>";
  $(".sheet-instruction").textContent =
    state.view === "review" ? "Every team. The players behind the numbers." : state.view === "alerts"
      ? "Check your inputs before making a call"
      : state.view === "games"
        ? "Ranked by how many of your players are involved"
        : state.view === "badges"
          ? "Season-long awards · switch teams to compare leagues"
          : state.view === "rise" ? "Search all available players" : "Select a player for the full read ↗";
  $("#edition-date").textContent = new Date(state.data.date + "T12:00:00")
    .toLocaleDateString("en-US", {
      month: "short",
      day: "2-digit",
      year: "numeric",
    })
    .toUpperCase();
  $("#league-label").textContent =
    t.league_name + (t.league_status ? " · " + t.league_status : "");
  $("#page-subtitle").textContent =
    state.view === "review" ? "Season production, scored for each league." : state.view === "rise"
      ? `Candidates for ${t.team_name}, scored under this league’s rules.`
      : state.view === "alerts"
        ? "A missing input should never become a confident recommendation."
        : state.view === "games"
          ? "Today's matchups involving your rostered players, across every team."
          : state.view === "badges"
            ? `Season awards scored under ${t.team_name}’s rules.`
            : `${t.results.length} players · ${sheetView().rows.filter(({p}) => p.starter && !p.vacant).length} ${sheetView().recommended ? "recommended starters" : state.mode === "test" ? "starters" : "synced starters"} · ${state.mode === "test" ? "Practicing with saved performances" : "Your latest saved analysis"}`;
  $("#breadcrumb").textContent =
    state.view === "review" ? "Season review" : state.view === "rise"
      ? "On the rise"
      : state.view === "alerts"
        ? "Data alerts"
        : state.view === "games"
          ? "Games to watch"
          : state.view === "badges"
            ? "Badge race"
            : "My teams";
  $("#breadcrumb").textContent =
    (state.mode === "test" ? "Test Week / " : "") +
    $("#breadcrumb").textContent;
  $("#freshness").textContent =
    (hosted && state.data.stale ? "Outdated · " : "Report · ") +
    new Date(state.data.generated_at).toLocaleString([], {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  $("#notice").innerHTML =
    `<span class="context-icon">${state.mode === "test" ? "↺" : "◉"}</span><span>${esc(state.data.notice)}${hosted && state.data.stale ? " This report is outdated; current recommendations are unavailable." : hosted && state.data.refresh_status === "failed" ? " The latest refresh failed. Review Data alerts." : ""}</span>`;
  const account = state.data.sleeper.username || state.account?.username;
  $("#account-label").textContent = account
    ? "@" + account
    : "Import your leagues";
  const rows = sheetView().rows.filter(({p}) => p.starter && !p.vacant).map(({p}) => p),
    locks = rows.filter((p) => p.status === "LOCK").length,
    wait = rows.filter((p) => p.status === "WAIT").length,
    review = rows.filter((p) =>
      [
        "SCHEDULE_UNAVAILABLE",
        "DATA_UNAVAILABLE",
        "SCORING_INCOMPLETE",
        "UNRESOLVED",
        "STALE",
      ].includes(p.status),
    ).length;
  const stats = [
    ["Lock", locks, "Scores worth keeping", "var(--mint)", "01"],
    ["Wait", wait, "Wait for another opportunity", "var(--purple)", "↗"],
    ["Review", review, "Incomplete or unavailable data", "var(--amber)", "!"],
    [
      "On the rise",
      t.pickups.length,
      "Signals to investigate",
      "var(--orange)",
      "↗",
    ],
  ];
  $("#summary").innerHTML = stats
    .map(
      ([label, n, caption, color, icon]) =>
        `<div class="stat-card" style="--accent:${color}"><div class="stat-label">${label}<span>${icon}</span></div><div class="stat-number">${n.toString().padStart(2, "0")}</div><p class="stat-caption">${caption}</p></div>`,
    )
    .join("");
  document
    .querySelectorAll(".nav")
    .forEach((b) =>
      b.classList.toggle(
        "active",
        b.dataset.view === "test"
          ? state.mode === "test"
          : b.dataset.view === state.view &&
              (state.mode !== "test" || state.view !== "team"),
      ),
    );
  $(".tabs").hidden = state.view !== "team";
  $(".sheet-heading .section-label").textContent =
    state.view === "review" ? "THE SEASON /"
    : state.view === "games" ? "THE SLATE /"
    : state.view === "badges" ? "THE RACE /"
    : "YOUR LINEUP";
  $(".panel-toolbar").hidden = state.view === "review" || state.view === "badges";
  $("#edit-roster").hidden = hosted || state.view !== "team";
  $("#edit-roster").textContent =
    t.source === "sleeper" ? "Synced roster" : "Edit roster";
  $("#league-scope").hidden = state.view !== "rise";
  $("#league-scope").textContent =
    state.mode === "test"
      ? "Practice candidates: only this sample roster is excluded. Historical league ownership is unknown."
      : `${t.ownership_complete ? "All league rosters, IR and taxi excluded" : "League ownership unknown"}${t.synced_at ? " · Synced " + new Date(t.synced_at).toLocaleString() : ""}.`;
  renderTestControls(t);
  renderContent();
  renderInsights();
  renderLineup();
  attachImageFallback();
}
function seasonBadgePanel(t) {
  const review = t.season_badges || {}, scope = state.badgeScope, metric = state.badgeMetric;
  const guide = LockInInsights.badgeGuide();
  const leaders = key => LockInInsights.seasonBadgeLeaders(t, key, scope);
  const summary = [["total", "🏅", "Most badges"], ["negative", "🌪️", "Chaos leader"], ["milestones", "🏔️", "Milestone machine"], ["variety", "🗂️", "Most variety"]];
  const name = (p, withPortrait = true) => `<button class="badge-race-player" data-badge-player="${esc(p.player_id)}" aria-label="View ${esc(p.player)} player card">${withPortrait ? portrait(p, true) : ""}<span>${esc(p.player)}</span></button>`;
  const rows = leaders(metric).filter(p => p.rank <= 10);
  const metricName = summary.find(([key]) => key === metric)?.[2] || guide.find(b => b.key === metric)?.name || "Badges";
  return `<div class="review-section-heading"><h3 id="badge-race-title">Leaderboards</h3><span>${esc(review.season || t.season || "Season")} · season totals</span></div>
    <p class="review-scope">${scope === "roster" ? "Current roster’s season awards, including games before joining." : "All observed NBA players, using this league’s scoring."} One count per badge earned per game night; ties count equally.</p>
    <div class="badge-race-controls"><label>Players<select id="badge-race-scope"><option value="roster" ${scope === "roster" ? "selected" : ""}>My roster</option><option value="nba" ${scope === "nba" ? "selected" : ""}>NBA-wide</option></select></label><label>Leaderboard<select id="badge-race-metric"><optgroup label="Season totals">${summary.map(([key,icon,title])=>`<option value="${key}" ${metric===key ? "selected" : ""}>${icon} ${title}</option>`).join("")}</optgroup><optgroup label="Each badge">${guide.map(b=>`<option value="${b.key}" ${metric===b.key ? "selected" : ""}>${b.icon} ${esc(b.name)}</option>`).join("")}</optgroup></select></label></div>
    ${review.status === "saved" || state.data.stale || state.data.refresh_status === "failed" ? '<p class="review-pending">Saved award totals. Waiting for a successful refresh.</p>' : ""}
    <div class="badge-race-highlights">${summary.map(([key,icon,title])=>{
      const all=leaders(key), first=all[0], tied=all.filter(p=>p.rank===1);
      return `<article><span class="review-kicker">${icon} ${title}</span>${first ? `<div>${name(first)}</div><b>${key === "variety" ? `${first.count}/${LockInInsights.varietyCap(first)}` : first.count} <small>${key === "variety" ? "different badges" : first.count === 1 ? "award" : "awards"}</small></b>${tied.length>1 ? `<small title="${esc(tied.map(p=>p.player).join(", "))}">Tied with ${tied.length-1} ${tied.length===2 ? "player" : "players"}</small>` : ""}` : '<p>No awards yet</p>'}</article>`;
    }).join("")}</div>
    <div class="badge-race-heading"><h4>${esc(metricName)}</h4><span>Top 10 places · ties included</span></div>
    <ol class="badge-race-list">${rows.map(p=>`<li><span class="badge-race-rank">${p.tied ? "T" : ""}${p.rank}</span><div>${name(p)}<small>${nbaTeamLabel(p.nba_team)} · ${p.total} total · ${p.variety}/${LockInInsights.varietyCap(p)} ${p.variety === 1 ? "type" : "types"}</small></div><b>${metric === "variety" ? `${p.count}/${LockInInsights.varietyCap(p)}` : p.count}<small>${metric === "variety" ? "types" : p.count === 1 ? "award" : "awards"}</small></b></li>`).join("")}</ol>
    ${!rows.length ? `<p class="review-pending">${review.status === "unavailable" ? "Badge history is unavailable in this report." : "No qualifying awards recorded for this selection yet."}</p>` : ""}
    <details class="badge-race-categories"><summary>Leaders for all ${guide.length} badges</summary>${guide.map(b=>{
      const top=leaders(b.key).filter(p=>p.rank===1);
      return `<div><span title="${esc(b.rule)}">${b.icon} ${esc(b.name)}</span><span>${top.length ? top.map(p=>name(p, false)).join(" · ") : "—"}</span><b>${top[0]?.count || "—"}</b></div>`;
    }).join("")}</details>
    <details class="badge-race-rules"><summary>Coverage & counting</summary><p>${review.tracked_days || 0} NBA game nights · ${review.player_games || 0} observed player games${review.first_date ? ` · ${esc(review.first_date)} to ${esc(review.last_date)}` : ""}. Totals cover stored observations through ${esc(review.as_of || "the last refresh")}.</p><p>Negative indicators: ${(review.negative_keys || []).map(key=>guide.find(b=>b.key===key)?.name).filter(Boolean).map(esc).join(", ") || "Not available"}. A high fantasy score in a loss is not a negative badge.</p><p>Milestones include double-/triple-doubles and stat thresholds. Only the highest stat tier earned that night counts. Variety counts distinct badge types. A qualifying streak earns a badge on every qualifying game night.</p><p>Projection comparisons need saved pregame forecasts: ${review.forecast_player_games || 0}/${review.player_games || 0} observed player games have matching snapshots. Historical awards can be rebuilt from stored results; missing pregame forecasts are never invented. Corrections replace previous awards, and changing league scoring recalculates a separate season tally.</p></details>`;
}
function seasonSummaryHtml(t) {
  const r = t.season_review || {}, players = LockInInsights.seasonContributors(t);
  const highlights = LockInInsights.seasonHighlights(players);
  const number = (n, digits = 1) => Number.isFinite(n) ? n.toLocaleString(undefined, {maximumFractionDigits: digits}) : "—";
  const gamesLabel = n => `${n} ${n === 1 ? "game" : "games"}`;
  const date = d => d ? new Date(d + "T12:00:00").toLocaleDateString(undefined, {month: "short", day: "numeric"}) : "—";
  const metric = (label, value, detail = "") => `<div class="review-metric"><span>${esc(label)}</span><strong>${esc(value)}</strong>${detail ? `<small>${esc(detail)}</small>` : ""}</div>`;
  const person = p => `<button class="review-person" data-player="${p.index}">${portrait(p)}<span><strong>${esc(p.player)}</strong><small>${nbaTeamLabel(p.nba_team)} ${esc((p.positions || []).join(" / "))}</small></span></button>`;
  const highlight = (label, p, value, detail, placeholder) => `<article class="review-highlight"><span class="review-kicker">${label}</span>${p ? `${person(p)}<strong class="review-highlight-value">${esc(value)}</strong><p>${esc(detail)}</p>` : `<p class="review-pending">${placeholder}</p>`}</article>`;
  const weeks = (r.weeks || []).filter(w => Number.isFinite(w.average_fp));
  const low = Math.min(0, ...weeks.map(w => w.average_fp)), high = Math.max(1, ...weeks.map(w => w.average_fp));
  const y = v => 126 - (v - low) / (high - low) * 108;
  const points = weeks.map((w, i) => [weeks.length === 1 ? 300 : 12 + i * 576 / (weeks.length - 1), y(w.average_fp)]);
  const chart = `<svg class="review-chart" viewBox="0 0 600 144" role="img" aria-label="Weekly fantasy points per player appearance. Exact values in weekly details below."><path class="review-chart-guide" d="M0 ${y(0)}H600"/><polyline points="${points.map(p => p.join(",")).join(" ")}"/>${points.map(([x, py], i) => `<circle cx="${x}" cy="${py}" r="4"><title>${esc(date(weeks[i].date))}: ${number(weeks[i].average_fp)} FP per appearance, ${weeks[i].games} appearances</title></circle>`).join("")}</svg>`;
  return `<div class="season-review">
    <div class="review-section-heading"><h3>${esc(t.team_name)}</h3><span>${esc(r.season || t.season || "Season")} · through ${esc(date(r.as_of))}</span></div>
    <p class="review-scope">Current roster’s observed season production, including games before joining. Not Sleeper locked scores or standings. Each team uses its own scoring formula.</p>
    ${r.status !== "ready" ? `<div class="review-empty">${r.status === "unavailable" ? "Season statistics are unavailable in this report." : "No season games recorded for this roster yet."} Players remain listed below; the next successful refresh fills their numbers.</div>` : ""}
    <div class="review-metrics">${metric("Roster fantasy points", number(r.total_fp), `${r.appearances || 0} player appearances`)}${metric("FP / appearance", number(r.fp_per_game), "Per player, per game")}${metric("Players with games", `${r.covered_players || 0} / ${r.roster_count ?? t.results.length}`, "Observed this season")}${metric("Top 3 contribution", r.top_three_share == null ? "—" : number(r.top_three_share) + "%", "Share of positive player FP totals")}</div>
    <div class="review-stats">${[["PTS","Points"],["REB","Rebounds"],["AST","Assists"],["STL","Steals"],["BLK","Blocks"],["FG3M","Threes"],["TOV","Turnovers"],["FG_PCT","FG %"],["FT_PCT","FT %"]].map(([key, label]) => metric(label, number(r.stats?.[key], key.endsWith("PCT") ? 1 : 0))).join("")}</div>
    <div class="review-section-heading"><h3>Key players</h3><span>Season leaders · small samples labeled</span></div>
    <div class="review-highlights">${highlight("Season anchor", highlights.anchor, number(highlights.anchor?.total_fp) + " FP", `${number(highlights.anchor?.share)}% of positive roster FP · ${gamesLabel(highlights.anchor?.games)}`, "A completed game starts the season totals.")}${highlight("Per-game leader", highlights.scorer, number(highlights.scorer?.average_fp) + " FP / game", `${gamesLabel(highlights.scorer?.games)}${highlights.scorer?.games < 5 ? " · early sample" : ""}`, "No observed performances yet.")}${highlight("Form leader", highlights.mover, (highlights.mover?.change > 0 ? "+" : "") + number(highlights.mover?.change) + " FP", "Last 5 average vs previous 5", "Needs 10 season games to compare two five-game windows.")}${highlight("Biggest swings", highlights.swing, number(highlights.swing?.spread) + " FP spread", `Game-to-game standard deviation · ${gamesLabel(highlights.swing?.games)}`, "Needs 5 season games to measure variability.")}</div>
    <section class="review-weekly" aria-labelledby="review-weekly-title"><div class="review-section-heading"><h3 id="review-weekly-title">Weekly production</h3><span>FP / player appearance</span></div>${weeks.length ? `${chart}<div class="review-chart-labels"><span>${esc(date(weeks[0].date))}</span><span>${weeks.length === 1 ? "One observed week" : esc(date(weeks.at(-1).date))}</span></div><details><summary>Weekly details · ${weeks.length} ${weeks.length === 1 ? "week" : "weeks"}</summary><div class="review-week-table"><table><thead><tr><th>Week of</th><th>Roster FP</th><th>FP / app.</th><th>Apps.</th></tr></thead><tbody>${weeks.map(w => `<tr><th>${esc(date(w.date))}</th><td>${number(w.total_fp)}</td><td>${number(w.average_fp)}</td><td>${w.games}</td></tr>`).join("")}</tbody></table></div></details>` : `<p class="review-pending">Weekly history will appear as season games are recorded.</p>`}</section>
    <div class="review-section-heading"><h3>Season contributors <small>${players.length}</small></h3><span>Sorted by total fantasy points</span></div>
    <div class="review-contributors">${players.map(p => `<article class="review-contributor">${person(p)}<div class="review-player-metrics">${metric("Total FP", number(p.total_fp))}${metric("FP / game", number(p.average_fp))}${metric(`Last ${p.recent_games || "5"}`, number(p.recent_fp))}${metric("Games", p.games ? number(p.games, 0) : "—")}</div><div class="review-contribution"><span style="width:${Math.max(0, Math.min(100, p.share || 0))}%;background:${teamAccent(p.nba_team)}"></span></div></article>`).join("")}</div>
    <p class="review-footnote">Bars show each player’s share of positive fantasy-point totals. — means no observed data. Last 5 averages use up to five season games; prior-season projection history is excluded. The badge race has its own tab.</p>
  </div>`;
}

function seasonContext(t=team()) {
  return state.seasonContexts[t.id] ||= {
    range:"season",from:"",to:"",player:"",venue:"",result:"",period:"week",
    trendMetric:"average_fp",tableView:"production",minimum:0,position:"",search:"",
    metric:"total_fp",logSearch:"",logKind:"all",logMetric:"date",logLimit:40,
  };
}
function seasonSelect(key, label, options, value, group="context") {
  return `<label>${esc(label)}<select data-season-${group}="${key}">${Object.entries(options).map(([k,v])=>`<option value="${esc(k)}" ${String(value)===k?"selected":""}>${esc(v)}</option>`).join("")}</select></label>`;
}
const seasonSigned = n => n == null ? "—" : `${n>0?"+":""}${fmt(n)}`;
const seasonTone = n => n>0?"stat-positive":n<0?"stat-negative":"";
const seasonNumber = (n,d=1) => Number.isFinite(n)?n.toLocaleString(undefined,{maximumFractionDigits:d}):"—";
function seasonTable(label, headers, rows) {
  return `<div class="compare-table-wrap season-table-wrap" tabindex="0" role="region" aria-label="${esc(label)}"><table class="compare-table"><thead><tr>${headers.map(h=>`<th scope="col">${h}</th>`).join("")}</tr></thead><tbody>${rows || `<tr><td colspan="${headers.length}">No observations match this selection.</td></tr>`}</tbody></table></div>`;
}
function seasonReviewHtml(t) {
  const r=t.season_review || {}, c=seasonContext(t);
  if(!Array.isArray(r.game_log) || (r.status==="ready" && !r.game_log.length)) return `<p class="review-empty">This saved report has summary statistics only. A data refresh adds the season explorer and complete game history.</p>${seasonSummaryHtml(t)}`;
  const roster=Object.fromEntries((t.results || []).filter(p=>p.player_id).map(p=>[p.player_id,p.player]));
  return `<div class="season-review season-explorer">
    <div class="season-intro"><div><span class="review-kicker">The season, under a microscope</span><h3>${esc(t.team_name)}</h3><p>${esc(r.season || t.season || "Season")} · observations through ${esc(r.as_of || state.data.date)} · your league’s scoring</p></div><span class="season-scope-chip">Current roster</span></div>
    <p class="review-scope">Explore the production, patterns and people behind your season. Includes these players’ games before joining your roster; historical ownership, Sleeper standings and locked totals are separate.</p>
    ${r.status==="unavailable"?'<p class="review-empty">Season scoring is unavailable. Missing statistics or unsupported rules must be resolved before this report can be calculated.</p>':""}
    <div class="season-toolbar">
      ${seasonSelect("range","Time window",{season:"Full season","7":"Last 7 days","30":"Last 30 days",custom:"Custom dates"},c.range)}
      ${seasonSelect("player","Player focus",{"":"Entire roster",...roster},c.player)}
      ${seasonSelect("venue","Venue",{"":"Home + away",home:"Home",away:"Away"},c.venue)}
      ${seasonSelect("result","NBA result",{"":"All results",W:"NBA wins",L:"NBA losses"},c.result)}
      ${c.range==="custom"?`<label>From<input type="date" data-season-context="from" value="${esc(c.from)}" max="${esc(r.as_of || "")}"></label><label>Through<input type="date" data-season-context="to" value="${esc(c.to)}" max="${esc(r.as_of || "")}"></label>`:""}
      <button class="season-reset" data-season-reset>Reset view</button>
    </div>
    <nav class="season-jumps" aria-label="Jump to season analysis">${[["pulse","Season pulse"],["dna","Scoring DNA"],["trends","Trends"],["roster","Roster lab"],["matrix","Weekly map"],["splits","Situational splits"],["records","Record book"],["logs","Game archive"]].map(([id,label])=>`<a href="#season-${id}">${label}</a>`).join("")}</nav>
    <div id="season-explorer-body">${seasonDashboardHtml(t)}</div>
  </div>`;
}
function seasonDashboardHtml(t) {
  const c=seasonContext(t), x=LockInInsights.seasonExplorer(t,c), s=x.summary;
  const metric=(label,value,detail="")=>`<article class="season-stat"><span>${label}</span><strong>${value}</strong><small>${detail}</small></article>`;
  const heading=(id,kicker,title,detail="")=>`<div class="review-section-heading" id="season-${id}"><div><span class="review-kicker">${kicker}</span><h3>${title}</h3></div>${detail?`<span>${detail}</span>`:""}</div>`;
  if(!x.games.length) return `<div class="review-empty"><h3>${x.from && x.to && x.from>x.to?"The start date is after the end date.":"No observed games in this selection."}</h3><p>Try a broader time window or reset the player, venue and result filters. No games is not a zero-point performance.</p></div>
    <div class="season-empty-roster">${(t.results || []).map(p=>`<article>${comparisonPerson(p,t.id)}<small>No matching season observations</small></article>`).join("")}</div>`;
  const covered=x.players.filter(p=>p.games), anchor=covered[0];
  const movers=covered.filter(p=>p.change!=null).sort((a,b)=>b.change-a.change), mover=movers[0];
  const bestDay=[...x.days].sort((a,b)=>b.total_fp-a.total_fp)[0];
  const statPerGame=k=>s.games && Number.isFinite(s.stats[k])?s.stats[k]/s.games:null;
  const known=s.benchmark_games;
  return `
    <div class="season-selection-note" aria-live="polite">${esc(x.from || x.games[0].date)} – ${esc(x.to || x.games.at(-1).date)} · ${x.games.length} player appearances · ${x.days.length} observed nights · ${c.player?"Single-player focus":"Entire roster"}${c.venue?` · ${esc(c.venue)}`:""}${c.result?` · NBA ${c.result==="W"?"wins":"losses"}`:""}</div>
    ${heading("pulse","01 / The big picture","Your season pulse","All panels follow the filters above")}
    <div class="season-stat-grid">${metric("Fantasy production",seasonNumber(s.total_fp),"Total FP · volume matters")}${metric("FP per appearance",fmt(s.average_fp),"Every observed player-game")}${metric("Players with games",`${covered.length} / ${x.players.length}`,"Within the selected scope")}${metric("40+ FP games",`${s.forty} <em>/ ${s.games}</em>`,`${fmt(s.forty/s.games*100)}% of appearances`)}${metric("Double / triple doubles",`${s.double_doubles ?? "—"} <em>/ ${s.triple_doubles ?? "—"}</em>`,"Triple-doubles also count as doubles")}${metric("FP per observed night",fmt(s.total_fp/x.days.length),`${x.days.length} nights · schedule dependent`)}</div>
    <div class="season-stories">
      <article><span class="review-kicker">Carrying the load</span>${comparisonPerson(anchor,t.id)}<strong>${fmt(anchor.share)}<small>% of positive roster FP</small></strong><p>The top three supply ${fmt(x.top_three_share)}%. Concentration is equivalent to ${fmt(x.effective_contributors)} equal contributors.</p></article>
      <article><span class="review-kicker">The form watch</span>${mover?`${comparisonPerson(mover,t.id)}<strong class="${seasonTone(mover.change)}">${seasonSigned(mover.change)}<small>FP/G · last five vs previous five</small></strong><p>${mover.change>0?"Your strongest recent improvement in this selection.":mover.change<0?"Even the strongest eligible trend is declining.":"The strongest eligible trend is flat."} ${mover.games} observed games.</p>`:'<h4>Let the sample grow.</h4><p>Ten games per player unlock two five-game windows. Short histories stay visible without an invented trend.</p>'}</article>
      <article><span class="review-kicker">The benchmark check</span><strong class="${seasonTone(s.baseline_delta)}">${seasonSigned(s.baseline_delta)}<small>FP per game vs preceding baseline</small></strong><p>${s.above_baseline} above · ${s.below_baseline} below · ${known-s.above_baseline-s.below_baseline} level, across ${known}/${s.games} games with a baseline. Uses 3–10 earlier season appearances, never later results.</p></article>
    </div>
    ${heading("dna","02 / Where your points come from","Your scoring DNA","Actual league weights, including deductions")}
    <div class="season-dna-grid"><article class="season-panel"><h4>Fantasy-point sources</h4>${seasonScoringBars(s.scoring,t.season_review?.scoring_rules)}<div class="season-scoring-total"><span>Net production</span><b>${seasonNumber(s.total_fp)} FP</b></div><p class="season-help">Bars compare absolute contributions; rose bars subtract points. Bonuses are separate and can stack.</p>${(t.season_review?.scoring_notes || []).map(n=>`<p class="season-help">${esc(n)}</p>`).join("")}</article>
    <article class="season-panel"><h4>The box-score fingerprint</h4><div class="season-box-grid">${[["PTS","Points"],["REB","Rebounds"],["AST","Assists"],["STL","Steals"],["BLK","Blocks"],["FG3M","Threes"],["TOV","Turnovers"],["MIN","Minutes"]].map(([k,label])=>metric(label,fmt(statPerGame(k)),`${seasonNumber(s.stats[k],0)} total · ${s.coverage[k]}/${s.games} covered`)).join("")}</div><p class="season-help">Large values are per appearance. Totals require complete inputs; missing box stats stay blank.</p></article></div>
    <div class="season-efficiency-strip">${[["FG_PCT","FG%"],["FG3_PCT","3P%"],["FT_PCT","FT%"],["EFG_PCT","eFG%"],["TS_PCT","TS%"],["AST_TOV","AST / TO"],["FP_PER_MIN","FP / min"]].map(([k,label])=>metric(label,fmt(s.stats[k],k.includes("PCT")?1:2))).join("")}</div>
    ${heading("trends","03 / The shape of the season","Momentum, week by week","Volume and efficiency tell different stories")}
    ${seasonTrendHtml(x,c)}
    <div class="season-dna-grid"><article class="season-panel"><h4>Your performance distribution</h4><p class="season-help">Every appearance has one place. These are fixed FP bands under your league’s formula.</p><div class="season-histogram">${x.distribution.map(b=>`<div><b>${b.count}</b><span><i style="height:${b.count/Math.max(1,...x.distribution.map(b=>b.count))*100}%"></i></span><small>${b.label}</small></div>`).join("")}</div><div class="season-mini-metrics">${metric("Median",fmt(s.median_fp),"Middle observed score")}${metric("Middle 50%",`${fmt(s.floor_fp)}–${fmt(s.ceiling_fp)}`,"25th–75th percentiles · 5+ games")}${metric("60+ FP nights",s.sixty,`${s.negative} negative-FP games`)}</div></article>
    <article class="season-panel"><h4>How the roster is built</h4>${seasonTable("Production by current roster role",["Current role","GP","Total FP","FP/G"],x.roles.map(r=>`<tr><th>${esc(r.label)}</th><td>${r.games}</td><td>${seasonNumber(r.total_fp)}</td><td>${fmt(r.average_fp)}</td></tr>`).join(""))}<p class="season-help">Groups use today’s starter, bench and reserve labels. These are not historical lineup starts or points left on your bench.</p><div class="season-mini-metrics">${metric("Busiest scoring night",seasonNumber(bestDay.total_fp),`${esc(bestDay.label)} · ${bestDay.games} appearances`)}${metric("Average game spread",fmt(s.spread),"Pooled standard deviation · 5+ games")}</div></article></div>
    ${heading("roster","04 / The roster laboratory","Every player, every dimension","League-scored · missing histories remain visible")}
    <div class="season-toolbar season-local-controls">
      <label>Find a player<input type="search" data-season-roster="search" value="${esc(c.search)}" placeholder="Player name"></label>
      ${seasonSelect("position","Position",{"":"All positions",PG:"PG",SG:"SG",SF:"SF",PF:"PF",C:"C"},c.position,"roster")}
      ${seasonSelect("minimum","Minimum games",{"0":"Include missing","1":"1+","5":"5+","10":"10+","20":"20+"},c.minimum,"roster")}
      ${seasonSelect("metric","Sort by",{total_fp:"Total FP",average_fp:"FP / game",recent_fp:"Last five",change:"Form change",spread:"Consistency (lowest SD)",floor_fp:"Floor",ceiling_fp:"Ceiling","stat:TS_PCT":"True shooting","stat:EFG_PCT":"Effective FG%","stat:AST_TOV":"Assist / turnover","stat:FP_PER_MIN":"FP / minute","stat:PTS_PER36":"Points / 36 min",...Object.fromEntries(["PTS","REB","AST","STL","BLK","FG3M","TOV","STOCKS","OREB","DREB","PF"].map(k=>[`pergame:${k}`,`${k==="STOCKS"?"Steals + blocks":k} / game`]))},c.metric,"roster")}
      ${seasonSelect("tableView","Statistics",{production:"Production",shooting:"Shooting & efficiency",reliability:"Reliability & form",all:"All statistics"},c.tableView,"roster")}
    </div><div id="season-roster-table">${seasonRosterHtml(t,x)}</div>
    <p class="season-help">Recent form and quartiles use the selected window. Floor/ceiling and spread need 5 games; form change needs 10. Streaks compare each game with its own preceding baseline, not a future season average. Focus a player to update every panel.</p>
    ${heading("matrix","05 / Your weekly map","Who showed up, and when?","FP per appearance · colour vs each player’s selected-window mean")}
    ${seasonMatrixHtml(t,x)}
    ${heading("splits","06 / The conditions","Where does this roster thrive?","Observed NBA context · small samples are visible")}
    ${seasonSplitsHtml(x)}
    ${heading("records","07 / The record book","The nights you remember","Extremes within your selected window")}
    ${seasonRecordsHtml(t,x)}
    ${heading("logs","08 / The full archive","Every game behind the numbers","Full stored season · not the 25-game player-card limit")}
    <div class="season-toolbar season-local-controls"><label>Search the archive<input type="search" data-season-log="logSearch" value="${esc(c.logSearch)}" placeholder="Player, opponent or date"></label>
      ${seasonSelect("logKind","Performances",{all:"All games",forty:"40+ FP",below:"Below prior baseline",dd:"Double-doubles",td:"Triple-doubles"},c.logKind,"log")}
      ${seasonSelect("logMetric","Sort games",{date:"Newest first",fp:"Highest FP",low_fp:"Lowest FP",delta:"Largest baseline lift",...Object.fromEntries(["PTS","REB","AST","STL","BLK","FG3M","TOV","MIN","OREB","DREB","PF"].map(k=>[`stat:${k}`,`Most ${k==="FG3M"?"3PM":k}`]))},c.logMetric,"log")}
      <button class="season-reset" data-season-csv>Download filtered CSV</button>
    </div><div id="season-game-table">${seasonGamesHtml(t,x)}</div>
    <details class="season-method"><summary>Definitions, sample rules and the limits of this view</summary><p>All counts are observed NBA player-games for the current roster, including games before joining. They are not Sleeper matchup points, transaction history, a win/loss record for your fantasy team, or projected results. Date filters are inclusive; last 7/30 days end at the report’s observation cutoff.</p><p>eFG% = (FGM + 0.5 × 3PM) / FGA. TS% = PTS / (2 × (FGA + 0.44 × FTA)). Both are attempt-weighted percentages. AST/TO and FP/min require positive denominators. Per-36 stats normalize observed production to 36 minutes; they are not playing-time projections. 3PA share is 3PA / FGA, and FT rate is FTA / FGA. Stocks are steals + blocks. Missing or imputed inputs remain blank. Category totals require every selected game’s input; coverage appears in the box-score fingerprint.</p><p>Effective contributors = 1 / sum of squared positive player-total shares. It describes concentration as an equivalent number of equal contributors. No positive totals means no share estimate. Full-season baselines use 3–10 strictly earlier observed games, even when you narrow the display filters. Recent form, medians and quartiles instead use only the selected games. No injury duration, games missed, usage rate or on/off rating is inferred from absent records.</p></details>`;
}
function seasonScoringBars(scoring, rules=[]) {
  const entries=Object.entries(scoring).sort((a,b)=>Math.abs(b[1])-Math.abs(a[1]));
  const max=Math.max(1,...entries.map(([,v])=>Math.abs(v)));
  return entries.map(([key,value])=>`<div class="season-source ${seasonTone(value)}"><span>${esc(key)}<small>${fmt(rules.find(r=>r.stat===key)?.weight,2)} FP / unit</small></span><div><i style="width:${Math.abs(value)/max*100}%"></i></div><b>${seasonSigned(value)}</b></div>`).join("") || '<p class="season-help">Scoring components are unavailable.</p>';
}
function seasonTrendHtml(x,c) {
  const periods=x.periods, metric=c.trendMetric, low=Math.min(0,...periods.map(p=>p[metric])), high=Math.max(1,...periods.map(p=>p[metric]));
  const y=v=>146-(v-low)/(high-low)*120;
  const points=periods.map((p,i)=>[periods.length===1?360:24+i*672/(periods.length-1),y(p[metric])]);
  const rows=periods.map((p,i)=>`<tr><th>${esc(p.label)}</th><td>${p.games}</td><td>${new Set(p.entries.map(g=>g.player_id)).size}</td><td>${seasonNumber(p.total_fp)}</td><td>${fmt(p.average_fp)}</td><td class="${seasonTone(i?p.average_fp-periods[i-1].average_fp:null)}">${i?seasonSigned(p.average_fp-periods[i-1].average_fp):"—"}</td><td>${p.forty}</td><td>${p.double_doubles ?? "—"}</td></tr>`).join("");
  return `<article class="season-panel season-trend"><div class="season-chart-heading"><div><span class="review-kicker">${c.period==="week"?"Weekly":"Monthly"} production</span><strong>${seasonNumber(x.summary.total_fp)} <small>FP across ${periods.length} observed ${c.period==="week"?"weeks":"months"}</small></strong></div><div class="season-toolbar">${seasonSelect("period","Group by",{week:"Week (Monday)",month:"Month"},c.period)}${seasonSelect("trendMetric","Chart metric",{average_fp:"FP per appearance",total_fp:"Total FP"},c.trendMetric)}</div></div>
    <svg class="season-trend-chart" viewBox="0 0 720 174" role="img" aria-label="${esc(metric==="total_fp"?"Total fantasy points":"Fantasy points per appearance")} by observed ${c.period}. Exact values in the table below."><path class="season-chart-axis" d="M20 ${y(0)}H700"/><polyline points="${points.map(p=>p.join(",")).join(" ")}"/>${points.map(([px,py],i)=>`<circle cx="${px}" cy="${py}" r="4"><title>${esc(periods[i].label)}: ${fmt(periods[i][metric])} FP · ${periods[i].games} appearances</title></circle>`).join("")}<text x="20" y="14">${fmt(high)} FP</text></svg>
    <div class="review-chart-labels"><span>${esc(periods[0]?.label)}</span><span>${esc(periods.at(-1)?.label)}</span></div>
    <details class="season-method"><summary>Open ${c.period==="week"?"weekly":"monthly"} totals & changes</summary>${seasonTable("Period production details",["Period starts","GP","Players","Total FP","FP/G","Δ FP/G","40+","DD"],rows)}</details><p class="season-help">Only periods with observed games are plotted. Partial periods and gaps are not full weeks or zeroes; changes compare consecutive observed periods.</p></article>`;
}
function seasonRosterHtml(t,x=LockInInsights.seasonExplorer(t,seasonContext(t))) {
  const c=seasonContext(t), players=LockInInsights.seasonPlayerRows(x,c);
  const production=[["GP",p=>p.games],["Total FP",p=>seasonNumber(p.total_fp)],["FP/G",p=>fmt(p.average_fp)],["Share",p=>p.share==null?"—":fmt(p.share)+"%"],...["MIN","PTS","REB","AST","STL","BLK","FG3M","TOV","STOCKS","OREB","DREB","PF"].map(k=>[`${k==="FG3M"?"3PM":k==="STOCKS"?"STL+BLK":k}/G`,p=>fmt(p.games&&p.stats[k]!=null?p.stats[k]/p.games:null)])];
  const shooting=[["FGM/FGA",p=>p.stats.FGM==null||p.stats.FGA==null?"—":`${seasonNumber(p.stats.FGM,0)}/${seasonNumber(p.stats.FGA,0)}`],["3PM/3PA",p=>p.stats.FG3M==null||p.stats.FG3A==null?"—":`${seasonNumber(p.stats.FG3M,0)}/${seasonNumber(p.stats.FG3A,0)}`],["FTM/FTA",p=>p.stats.FTM==null||p.stats.FTA==null?"—":`${seasonNumber(p.stats.FTM,0)}/${seasonNumber(p.stats.FTA,0)}`],...Object.entries({FG_PCT:"FG%",FG3_PCT:"3P%",FT_PCT:"FT%",EFG_PCT:"eFG%",TS_PCT:"TS%",AST_TOV:"AST/TO",FP_PER_MIN:"FP/min",THREE_RATE:"3PA share %",FT_RATE:"FTA/FGA",FP_PER36:"FP/36",PTS_PER36:"PTS/36",REB_PER36:"REB/36",AST_PER36:"AST/36",FG_MISSES:"FG misses",FT_MISSES:"FT misses"}).map(([k,label])=>[label,p=>fmt(p.stats[k],["AST_TOV","FP_PER_MIN","FT_RATE"].includes(k)?2:1)])];
  const reliability=[["GP",p=>p.games],["Last 5",p=>fmt(p.recent_fp)],["Δ form",p=>`<span class="${seasonTone(p.change)}">${seasonSigned(p.change)}</span>`],["Median",p=>fmt(p.median_fp)],["Floor",p=>fmt(p.floor_fp)],["Ceiling",p=>fmt(p.ceiling_fp)],["Spread",p=>fmt(p.spread)],["Best",p=>fmt(p.best_fp)],["Worst",p=>fmt(p.worst_fp)],["40+ rate",p=>p.games?fmt(p.forty/p.games*100)+"%":"—"],["DD / TD",p=>`${p.double_doubles ?? "—"} / ${p.triple_doubles ?? "—"}`],["Streak",p=>p.streak?`${p.streak} ${p.streak_direction}`:"—"],["Last played",p=>esc(p.last_played || "—")]];
  const columns=c.tableView==="shooting"?[production[0],...shooting]:c.tableView==="reliability"?reliability:c.tableView==="all"?[...production,...shooting,...reliability.slice(1)]:production;
  return `<p class="compare-result-count">${players.length} players · scroll horizontally for every statistic · player names open their profile</p>${seasonTable("Season roster laboratory",["Player",...columns.map(([label])=>label),"Explore"],players.map(p=>`<tr><th scope="row">${comparisonPerson(p,t.id)}<div class="season-roster-spark">${p.entries.length>1?seasonMiniSpark(p.entries.map(g=>g.fp)):""}<small>${p.games?`${p.games} observed games`:"No matching history"}</small></div></th>${columns.map(([,value])=>`<td>${value(p)}</td>`).join("")}<td>${p.player_id?`<button class="season-focus" data-season-focus="${esc(p.player_id)}">Focus →</button>`:"—"}</td></tr>`).join(""))}`;
}
function seasonMiniSpark(values) {
  const recent=values.slice(-10), low=Math.min(...recent), high=Math.max(...recent), span=high-low || 1;
  return `<svg viewBox="0 0 84 22" aria-label="Last ${recent.length} selected game scores" role="img"><polyline points="${recent.map((v,i)=>`${i*84/(recent.length-1 || 1)},${20-(v-low)/span*18}`).join(" ")}"/></svg>`;
}
function seasonMatrixHtml(t,x) {
  const headers=["Player",...x.weeks.map(w=>esc(w.label.slice(5)))];
  return `${seasonTable("Player by week production heatmap",headers,x.players.map(p=>`<tr><th>${comparisonPerson(p,t.id)}</th>${x.weeks.map(w=>{
    const entries=w.entries.filter(g=>String(g.player_id)===String(p.player_id));
    if(!entries.length) return '<td class="season-heat-empty">—</td>';
    const mean=entries.reduce((s,g)=>s+g.fp,0)/entries.length, delta=mean-p.average_fp;
    const tone=Math.abs(delta)<=Math.max(2,Math.abs(p.average_fp)*.1)?"level":delta>0?"above":"below";
    return `<td class="season-heat" data-tone="${tone}" title="${esc(w.label)}: ${fmt(mean)} FP/G over ${entries.length} games; ${seasonSigned(delta)} vs selected-window mean"><b>${fmt(mean)}</b><small>${entries.length} GP</small></td>`;
  }).join("")}</tr>`).join(""))}<p class="season-help"><span class="stat-positive">Green: above personal mean</span> · <span class="stat-negative">Rose: below</span> · neutral within ±10% (minimum 2 FP). A dash means no observed games. Each cell includes its sample size.</p>`;
}
function seasonSplitsHtml(x) {
  const row=(g,label)=>`<tr><th>${label}</th><td>${g.games}</td><td>${fmt(g.average_fp)}</td><td>${seasonNumber(g.total_fp)}</td>${["MIN","PTS","REB","AST"].map(k=>`<td>${fmt(g.stats[k]!=null?g.stats[k]/g.games:null)}</td>`).join("")}<td>${fmt(g.stats.TS_PCT)}%</td><td>${fmt(g.stats.FP_PER_MIN,2)}</td></tr>`;
  const columns=["Split","GP","FP/G","Total FP","MIN/G","PTS/G","REB/G","AST/G","TS%","FP/min"];
  return `${seasonTable("Situational performance splits",columns,x.splits.map(g=>row(g,`${esc(g.label)}<small>${esc(g.group)}</small>`)).join(""))}
    <p class="season-help">Wins/losses describe NBA game results, not your fantasy matchup. Spacing measures days between this player’s observed appearances; it is not a verified team rest or injury classification. Unknown context stays in its own row.</p>
    <details class="season-method season-opponents"><summary>Opponent scouting · ${x.opponents.filter(g=>g.label!=="Unknown").length} known opponents</summary>${seasonTable("Production by NBA opponent",["Opponent",...columns.slice(1)],x.opponents.map(g=>row(g,esc(g.label))).join(""))}<p class="season-help">Descriptive results against opponents; roster mix and small samples affect every comparison.</p></details>`;
}
function seasonRecordsHtml(t,x) {
  const record=(title,g,value,note)=>`<article class="season-record"><span class="review-kicker">${title}</span>${g?`${comparisonPerson(g,t.id)}<strong>${value}</strong><p>${esc(g.date)} · ${g.venue==="away"?"@":g.venue==="home"?"vs":""} ${esc(g.opponent || "opponent unknown")}<br>${note}</p>`:'<p class="season-help">Not enough qualifying observations.</p>'}</article>`;
  const r=x.records;
  const categories=[["PTS","Scoring"],["REB","Glass cleaner"],["AST","Playmaker"],["STL","Ball hawk"],["BLK","Rim protector"],["FG3M","From deep"]];
  return `<div class="season-records">${record("Highest game",r.best,fmt(r.best?.fp)+" FP","Best observed single-game score")}${record("Lowest game",r.worst,fmt(r.worst?.fp)+" FP","Lowest observed score; no DNPs invented")}${record("Biggest step up",r.above,seasonSigned(r.above?.delta)+" FP",`${fmt(r.above?.fp)} actual vs ${fmt(r.above?.baseline_fp)} prior baseline`)}${record("Biggest letdown",r.below,seasonSigned(r.below?.delta)+" FP",`${fmt(r.below?.fp)} actual vs ${fmt(r.below?.baseline_fp)} prior baseline`)}</div>
    <div class="review-section-heading"><h3>The category leaders</h3><span>Totals in this selection · ties noted</span></div><div class="season-category-leaders">${categories.map(([key,title])=>{
      const eligible=x.players.filter(p=>p.games && p.stats[key]!=null).sort((a,b)=>b.stats[key]-a.stats[key]);
      const p=eligible[0], tied=p?eligible.filter(q=>q.stats[key]===p.stats[key]):[];
      return `<article><span class="review-kicker">${title} · ${key==="FG3M"?"3PM":key}</span>${p?`${comparisonPerson(p,t.id)}<strong>${seasonNumber(p.stats[key],0)} <small>${fmt(p.stats[key]/p.games)} / game</small></strong><p>${p.games} games${tied.length>1?` · tied with ${tied.slice(1).map(q=>esc(q.player)).join(", ")}`:""}</p>`:'<p class="season-help">No complete stat coverage.</p>'}</article>`;
    }).join("")}</div>`;
}
function seasonGamesHtml(t,x=LockInInsights.seasonExplorer(t,seasonContext(t))) {
  const c=seasonContext(t), rows=LockInInsights.seasonLogRows(x,{search:c.logSearch,kind:c.logKind,metric:c.logMetric});
  const visible=rows.slice(0,c.logLimit);
  return `<p class="compare-result-count">Showing ${visible.length} of ${rows.length} matching appearances · CSV includes every match</p>${seasonTable("Full season game archive",["Date","Player","Matchup","NBA","FP","Prior avg","Δ FP",...["MIN","PTS","REB","AST","STL","BLK","3PM","TOV"],"FG","3P","FT","Milestones"],visible.map(g=>`<tr><td>${esc(g.date)}</td><th>${comparisonPerson(g,t.id)}</th><td>${g.venue==="home"?"vs":g.venue==="away"?"@":"—"} ${esc(g.opponent || "Unknown")}</td><td>${esc(g.result || "—")}</td><td><b>${fmt(g.fp)}</b></td><td title="${g.baseline_games} earlier appearances">${fmt(g.baseline_fp)}</td><td class="${seasonTone(g.delta)}">${seasonSigned(g.delta)}</td>${["MIN","PTS","REB","AST","STL","BLK","FG3M","TOV"].map(k=>`<td>${fmt(g.stats?.[k],k==="MIN"?1:0)}</td>`).join("")}${[["FGM","FGA"],["FG3M","FG3A"],["FTM","FTA"]].map(([m,a])=>`<td>${g.stats?.[m]!=null&&g.stats?.[a]!=null?`${fmt(g.stats[m],0)}/${fmt(g.stats[a],0)}`:"—"}</td>`).join("")}<td>${g.triple_double?"TD · DD":g.double_double?"DD":"—"}</td></tr>`).join(""))}${rows.length>c.logLimit?`<button class="season-load-more" data-season-more>Show 40 more appearances (${rows.length-c.logLimit} remaining)</button>`:""}`;
}

const REVIEW_TABS = [
  ["review", "Season review"],
  ["compare", "Compare teams"],
  ["film", "Shaqtin' a fool"],
];
function reviewTabsHtml() {
  return `<div class="review-tabs" role="tablist" aria-label="Season review sections">${REVIEW_TABS.map(
    ([key, label]) =>
      `<button role="tab" class="tab review-tab ${state.reviewTab === key ? "active" : ""}" data-review-tab="${key}" aria-selected="${state.reviewTab === key}">${esc(label)}</button>`,
  ).join("")}</div>`;
}
function renderReviewHub(t) {
  const body =
    state.reviewTab === "compare"
      ? teamComparisonHtml()
      : state.reviewTab === "film"
        ? filmReviewHtml(t)
        : seasonReviewHtml(t);
  $("#content").innerHTML = `<div class="review-hub">${reviewTabsHtml()}${body}</div>`;
  attachImageFallback();
}
function teamComparisonHtml() {
  const comparison = state.data?.comparison || { teams: [] };
  const teams = LockInInsights.comparisonTeams(comparison, state.compareMetric);
  const metrics = {roster_average:"Roster average", fp_per_game:"FP / appearance", top_five:"Top-five average", depth:"Depth average", total_fp:"Total FP"};
  const control = (key, label, values, value) => `<label>${label}<select data-compare="${key}">${Object.entries(values).map(([v,l]) => `<option value="${esc(v)}" ${String(value) === v ? "selected" : ""}>${esc(l)}</option>`).join("")}</select></label>`;
  const maximum = Math.max(1,...teams.map(t => t[state.compareMetric] || 0));
  const insight = (label, key, description) => {
    const leader = [...teams].filter(t=>Number.isFinite(t[key])).sort((a,b)=>b[key]-a[key])[0];
    if (!leader) return "";
    const tied = teams.filter(t=>t[key] === leader[key]);
    return `<article class="compare-insight"><span class="review-kicker">${label}</span><strong>${fmt(leader[key])}<small> ${key === "total_fp" ? "FP" : "FP/G"}</small></strong><b>${tied.map(t=>esc(t.team_name)).join(" · ")}</b><p>${description}</p></article>`;
  };
  const rows = teams.map(tm => {
    const value = tm[state.compareMetric];
    const rank = value == null ? "—" : teams.findIndex(t => t[state.compareMetric] === value)+1;
    return `<tr><td class="compare-rank">${rank}</td><th scope="row"><strong>${esc(tm.team_name)}</strong><small>${esc(tm.league_name || "")}</small></th>
      <td class="compare-score"><b>${fmt(value)}</b><span class="compare-meter"><i style="width:${Math.max(0,(value || 0)/maximum*100)}%"></i></span></td>
      ${["roster_average","fp_per_game","top_five","depth","total_fp"].map(k=>`<td>${fmt(tm[k])}</td>`).join("")}
      <td>${tm.appearances ?? "—"}</td><td>${tm.covered_players ?? "—"}/${tm.roster_count ?? "—"}</td></tr>`;
  }).join("");
  const leaders = teams.filter(t => (t.players || t.leaders || []).length).map(tm =>
    `<article class="review-highlight compare-team-card"><span class="review-kicker">${esc(tm.team_name)}</span>
      <div class="compare-card-score">${fmt(tm.roster_average)} <small>roster average FP</small></div>
      ${(tm.ranked_players.length ? tm.ranked_players : tm.leaders || []).slice(0,3).map(p =>
        `<div class="compare-leader">${comparisonPerson(p,tm.team_id)}<div><b>${fmt(p.average_fp)} <small>FP/G</small></b><small>${p.games} games · ${fmt(p.total_fp)} FP</small></div></div>`).join("")}
      <p class="compare-card-note">Top 3 by total supply ${fmt(tm.top_three_share)}% of positive season FP · ${tm.covered_players}/${tm.roster_count} players observed</p></article>`).join("");
  return `<div class="season-review compare-view">
    <div class="review-section-heading"><div><span class="review-kicker">Your roster laboratory</span><h3>More players ≠ a better team.</h3></div><span>${teams.length} teams · ${esc(comparison.weights_label || "default scoring")}</span></div>
    <p class="review-scope">Every player gets equal weight in the roster average, regardless of games played. Same scoring across your current rosters. Small samples and missing histories can move the order.</p>
    <div class="compare-insights">${insight("Best roster average","roster_average","Equal weight per observed player. No bonus for simply carrying more players.")}${insight("Strength beyond the stars","depth","Average after the top five scorers. A look at the rest of your roster.")}${insight("Volume leader","total_fp","Most accumulated FP. Roster size and extra appearances help this number.")}</div>
    <div class="compare-controls">${control("ranking","Rank teams by",metrics,state.compareMetric)}<span>Separate quality from volume.</span></div>
    <div class="compare-table-wrap" tabindex="0" role="region" aria-label="Team rankings, scroll for more stats"><table class="compare-table"><thead><tr><th>#</th><th>Team</th><th>${metrics[state.compareMetric]}</th><th>Roster avg</th><th>FP / app</th><th>Top 5 avg</th><th>Depth avg</th><th>Total FP</th><th>Apps</th><th>Coverage</th></tr></thead><tbody>${rows || '<tr><td colspan="10">No teams to compare yet.</td></tr>'}</tbody></table></div>
    <details class="compare-method"><summary>What makes this comparison fair?</summary><p>Roster average is the mean of covered players' individual FP averages. FP / appearance weights every played game equally. Top-five average compares five best per-game scorers (needs five covered players); depth averages everyone after those five. Reserve players count. Missing histories are excluded; zero-point games count. Total FP still rewards larger rosters and busier schedules. This is observed production, not standings or a forecast.</p><p>${teams.map(t=>`${esc(t.team_name)}: ${esc(t.season || "season unavailable")} · through ${esc(t.as_of || state.data.date)}`).join(" · ")}</p></details>
    ${leaders ? `<div class="review-section-heading"><h3>The engines of each team</h3><span>Leaders by FP per game · same scoring</span></div><div class="review-highlights">${leaders}</div>` : ""}
    <div class="review-section-heading"><h3>Beyond the fantasy score</h3><span>Per appearance · attempt-weighted shooting</span></div>
    <div class="compare-table-wrap" tabindex="0" role="region" aria-label="Team advanced statistics"><table class="compare-table"><thead><tr><th>Team</th>${["PTS","REB","AST","STL","BLK","3PM","TOV","eFG%","TS%","AST/TO","FP/min"].map(k=>`<th>${k}</th>`).join("")}</tr></thead><tbody>${teams.map(t=>`<tr><th>${esc(t.team_name)}</th>${["PTS","REB","AST","STL","BLK","FG3M","TOV"].map(k=>`<td>${fmt(t.appearances && t.stats?.[k] != null ? t.stats[k]/t.appearances : null)}</td>`).join("")}${["EFG_PCT","TS_PCT","AST_TOV","FP_PER_MIN"].map(k=>`<td>${fmt(t.stats?.[k],2)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>
    <div class="review-section-heading"><h3>Every player. Every roster.</h3><span>Shared players counted once per season</span></div>
    <div class="compare-controls">
      <label>Find a player<input data-compare="search" type="search" placeholder="Search players" value="${esc(state.compareFilters.search)}"></label>
      ${control("team","Fantasy team",{"":"All teams",...Object.fromEntries(teams.map(t=>[t.team_id,t.team_name]))},state.compareFilters.team)}
      ${control("position","Position",{"":"All positions",PG:"PG",SG:"SG",SF:"SF",PF:"PF",C:"C"},state.compareFilters.position)}
      ${control("minimum","Minimum games",{"1":"1+ games","5":"5+ games","10":"10+ games","20":"20+ games"},state.compareFilters.minimum)}
      ${control("metric","Sort players by",{average_fp:"FP / game",total_fp:"Total FP",recent_fp:"Last five FP",change:"Form change",floor_fp:"Floor (25th %ile)",ceiling_fp:"Ceiling (75th %ile)",spread:"Consistency (lowest SD)","stat:TS_PCT":"True shooting %","stat:EFG_PCT":"Effective FG %","stat:AST_TOV":"Assist / turnover","stat:FP_PER_MIN":"FP / minute",...Object.fromEntries(["PTS","REB","AST","STL","BLK","FG3M","TOV","MIN"].map(k=>[`pergame:${k}`,`${k === "FG3M" ? "3PM" : k} / game`]))},state.compareFilters.metric)}
    </div>
    <div id="comparison-player-results">${comparisonPlayersHtml()}</div>
    <p class="review-scope">Floor / ceiling are observed quartiles; spread is standard deviation (5+ games). Form compares the latest five with the preceding five (10+ games). eFG% = (FGM + 0.5 × 3PM) / FGA; TS% = PTS / (2 × (FGA + 0.44 × FTA)). Missing inputs stay blank.</p>
  </div>`;
}
function comparisonPerson(p, teamId) {
  const target = state.data.teams.find(t=>t.id === teamId);
  const index = target?.results?.findIndex(r=>String(r.player_id) === String(p.player_id)) ?? -1;
  const content = `${portrait(p)}<span><strong>${esc(p.player)}</strong><small>${esc((p.positions || []).join(" / "))}${p.nba_team ? ` · ${esc(p.nba_team)}` : ""}</small></span>`;
  return index >= 0 ? `<button class="compare-person" data-watch="${esc(teamId)}:${index}">${content}</button>` : `<div class="compare-person">${content}</div>`;
}
function comparisonPlayersHtml() {
  const players = LockInInsights.comparisonPlayers(state.data?.comparison, state.compareFilters);
  return `<p class="compare-result-count">${players.length} players · all values use default scoring</p><div class="compare-table-wrap" tabindex="0" role="region" aria-label="Player rankings, scroll for advanced statistics"><table class="compare-table compare-player-table"><thead><tr>${["#","Player / fantasy teams","GP","FP/G","Total","Last 5","Δ form","Floor","Ceiling","Spread","MIN","PTS","REB","AST","STL","BLK","3PM","TOV","eFG%","TS%","AST/TO","FP/min"].map(k=>`<th>${k}</th>`).join("")}</tr></thead><tbody>${players.map(p=>`<tr><td class="compare-rank">${p.rank ?? "—"}</td><th>${comparisonPerson(p,p.team_id)}<small>${p.teams.map(esc).join(" · ")}</small></th><td>${p.games}</td>${["average_fp","total_fp","recent_fp","change","floor_fp","ceiling_fp","spread"].map(k=>`<td ${k === "change" ? `class="${p[k] > 0 ? "stat-positive" : p[k] < 0 ? "stat-negative" : ""}"` : ""}>${fmt(p[k])}</td>`).join("")}${["MIN","PTS","REB","AST","STL","BLK","FG3M","TOV"].map(k=>`<td>${fmt(p.stats?.[k] != null && p.games ? p.stats[k]/p.games : null)}</td>`).join("")}${["EFG_PCT","TS_PCT","AST_TOV","FP_PER_MIN"].map(k=>`<td>${fmt(p.stats?.[k],2)}</td>`).join("")}</tr>`).join("") || '<tr><td colspan="22">No players match these filters. Older reports need a data refresh to include full comparison stats.</td></tr>'}</tbody></table></div>`;
}
function filmReviewHtml(t) {
  const f = t.film_review || {};
  const number = (n, digits = 1) =>
    Number.isFinite(n)
      ? n.toLocaleString(undefined, { maximumFractionDigits: digits })
      : "—";
  const date = (d) =>
    d
      ? new Date(d + "T12:00:00").toLocaleDateString(undefined, {
          month: "short",
          day: "numeric",
        })
      : "—";
  const metric = (label, value, detail = "") =>
    `<div class="review-metric"><span>${esc(label)}</span><strong>${esc(value)}</strong>${detail ? `<small>${esc(detail)}</small>` : ""}</div>`;
  const weekLabel =
    f.week?.start && f.week?.end
      ? `${date(f.week.start)} – ${date(f.week.end)}${f.week.key != null ? ` · week ${esc(f.week.key)}` : ""}`
      : "This week";
  if (f.status !== "ready") {
    const note =
      f.status === "unavailable"
        ? f.note || "Lock review is unavailable in this report."
        : "No recorded locks or completed roster games to review for this week yet.";
    return `<div class="season-review film-view">
      <div class="review-section-heading"><h3>Shaqtin' a fool</h3><span>${esc(t.team_name)} · ${weekLabel}</span></div>
      <p class="review-scope">A hindsight audit of this week's lock calls against each roster player's best game.</p>
      <div class="review-empty">${esc(note)}</div>
    </div>`;
  }
  const mistakeCard = (m) => {
    const timing = m.kind === "timing";
    const title = timing ? "Right player, wrong night" : "Wrong call";
    const body = timing
      ? `Locked ${m.locked_fp} FP into ${m.slot} on ${date(m.locked_date)}; ${m.better_player || m.player}'s ${number(m.better_fp)} FP on ${date(m.better_date)} was the play.`
      : `Locked ${m.player}'s ${m.locked_fp} FP into ${m.slot} on ${date(m.locked_date)}; ${m.better_player || "a teammate"}'s ${number(m.better_fp)} FP on ${date(m.better_date)} was open.`;
    const maximum = Math.max(1,Math.abs(m.locked_fp),Math.abs(m.better_fp || 0));
    return `<article class="film-mistake"><div class="film-card-heading"><span class="review-kicker">${title}</span><b class="film-cost">−${number(m.cost_fp)} FP</b></div>
      <div class="film-versus">${comparisonPerson(m,t.id)}<span aria-hidden="true">→</span>${comparisonPerson({player:m.better_player,player_id:m.better_player_id},t.id)}</div>
      <div class="film-score-line"><span>Locked</span><i style="width:${Math.max(0,m.locked_fp/maximum*100)}%"></i><b>${number(m.locked_fp)}</b></div>
      <div class="film-score-line is-better"><span>Best option</span><i style="width:${Math.max(0,(m.better_fp || 0)/maximum*100)}%"></i><b>${number(m.better_fp)}</b></div><p>${esc(body)}</p></article>`;
  };
  return `<div class="season-review film-view">
    <div class="review-section-heading"><h3>Shaqtin' a fool</h3><span>${esc(t.team_name)} · ${weekLabel}</span></div>
    <p class="review-scope">What actually got locked plus the best legal fill of the open slots, versus the perfect hindsight lineup from everyone's best game this week. Heuristic replay — not a judgment of the calls available at the time.</p>
    <div class="review-metrics">${metric("Retained FP", number(f.retained_fp), "Locked scores + optimal fill")}${metric("Perfect week", number(f.oracle_fp), "Hindsight-optimal lineup")}${metric("Left on table", number(f.regret_fp), "Points the locks gave up")}${metric("Efficiency", f.efficiency == null ? "—" : number(f.efficiency) + "%", "Retained vs perfect")}</div>
    ${!(f.locked || []).length ? '<p class="review-pending">No recorded locks: retained and perfect use the same hindsight fill. This is not a measured perfect decision record.</p>' : ""}
    <section class="film-choke"><div><span class="review-kicker">The what-if desk</span><h3>Choke artist</h3><p>Which banked game fell furthest below that player's preceding-game average?</p></div>
      <label>Final loss margin (optional)<input id="film-margin" type="number" min="0" step="0.1" placeholder="e.g. 8.5 FP" value="${esc(state.filmMargins[filmMarginKey(t)] ?? "")}"></label>
      <div id="film-spotlight">${filmSpotlightHtml(t)}</div>
    </section>
    <div class="review-section-heading"><h3>Mistakes <small>${(f.mistakes || []).length}</small></h3><span>${f.clean_count || 0} of ${f.locked_count || 0} locks were clean</span></div>
    <p class="review-scope">Each cost tests one lock independently; costs can overlap and should not be added together.</p>
    ${(f.mistakes || []).length ? `<div class="film-mistakes">${f.mistakes.map(mistakeCard).join("")}</div>` : `<p class="review-pending">Every recorded lock held up against the week’s hindsight best. Nothing to roast.</p>`}
    ${filmWeekHtml(t)}
    ${(f.locked || []).length ? `<details class="film-tape"><summary>The tape · ${f.locked.length} recorded locks</summary><div class="film-tape-list">${f.locked.map((l) => `<div><span>${esc(l.slot)}</span><strong>${esc(l.player)}</strong><b>${number(l.fp)} <small>FP</small></b><small>${esc(date(l.date))}</small></div>`).join("")}</div></details>` : ""}
  </div>`;
}
function filmMarginKey(t) { return `${t.id}:${t.film_review?.week?.start || ""}`; }
function filmSpotlightHtml(t) {
  const f = t.film_review || {};
  const raw = state.filmMargins[filmMarginKey(t)];
  const margin = raw !== "" && raw != null && Number(raw) >= 0 ? Number(raw) : null;
  const {player:p, flips} = LockInInsights.filmSpotlight(f,margin);
  if (!p) return `<p class="review-pending">No banked game with a verified below-baseline result yet. Needs a matching recorded lock and at least three earlier games. A rough bench night does not cost your banked total.</p>`;
  return `<div class="film-spotlight-player">${comparisonPerson(p,t.id)}<strong class="stat-negative">${fmt(p.delta)} <small>FP vs baseline</small></strong></div>
    <p>${esc(p.date)} · ${fmt(p.fp)} FP banked vs ${fmt(p.baseline_fp)} FP across ${p.baseline_games} preceding games.</p>
    <p>${margin == null ? "Enter a final loss margin to explore whether a return to baseline could have changed the result." : flips.length ? `At the entered ${fmt(margin)} FP loss margin, ${flips.map(x=>esc(x.player)+" ("+esc(x.date)+")").join(", ")} could each hypothetically flip the result by reaching their baseline.` : `No qualifying banked shortfall exceeds the entered ${fmt(margin)} FP margin. Matching the margin would only tie.`}</p>
    <small>What-if only: holds every other locked score fixed. Opponent totals and matchup completion are not verified here. A historical average is not a pregame forecast.</small>`;
}
function filmWeekHtml(t) {
  const f = t.film_review || {}, games = f.performances || [];
  if (!games.length) return '<p class="review-pending">Game-by-game tape is not included in this saved report. Refresh the data to add the weekly breakdown.</p>';
  const start = f.week?.start;
  const days = start ? Array.from({length:7},(_,i)=>{const d=new Date(start+"T12:00:00Z");d.setUTCDate(d.getUTCDate()+i);return d.toISOString().slice(0,10);}) : [...new Set(games.map(g=>g.date))];
  const signed = value => value == null ? "—" : `${value > 0 ? "+" : ""}${fmt(value)}`;
  const tone = value => value > 0 ? "stat-positive" : value < 0 ? "stat-negative" : "";
  const daily = days.map(date => {
    const entries = games.filter(g=>g.date === date), matched = entries.filter(g=>Number.isFinite(g.delta));
    const delta = matched.length ? matched.reduce((sum,g)=>sum+g.delta,0)/matched.length : null;
    return {date,entries,matched,delta};
  });
  const max = Math.max(1,...daily.map(d=>Math.abs(d.delta || 0)));
  const locked = p => (f.locked || []).some(l=>String(l.player_id) === String(p.player_id) && l.date === p.date);
  const filtered = games.filter(p=>state.filmFilter === "below" ? p.delta < 0 : state.filmFilter === "locked" ? locked(p) : true)
    .sort((a,b)=>(a.delta ?? Infinity)-(b.delta ?? Infinity) || a.date.localeCompare(b.date));
  return `<div class="review-section-heading"><h3>A week on the rollercoaster</h3><span>Average FP above / below prior baseline</span></div>
    <div class="film-week">${daily.map(d=>`<article><small>${new Date(d.date+"T12:00:00").toLocaleDateString(undefined,{weekday:"short",month:"short",day:"numeric"})}</small><strong class="${tone(d.delta)}">${signed(d.delta)}</strong><div class="film-day-bar ${tone(d.delta)}"><i style="height:${Math.abs(d.delta || 0)/max*100}%"></i></div><span>${d.entries.length ? `${d.entries.length} appearances` : "No observed games"}</span><small>${d.matched.length}/${d.entries.length} with baseline</small></article>`).join("")}</div>
    <div class="review-section-heading"><h3>The lowlights ledger</h3><label class="film-filter">Show <select id="film-filter">${Object.entries({all:"All performances",below:"Below baseline",locked:"Banked games"}).map(([v,l])=>`<option value="${v}" ${state.filmFilter===v?"selected":""}>${l}</option>`).join("")}</select></label></div>
    <div class="compare-table-wrap" tabindex="0" role="region" aria-label="Weekly player performance ledger"><table class="compare-table"><thead><tr><th>Player</th><th>Night</th><th>FP</th><th>Prior avg</th><th>Δ FP</th><th>PTS</th><th>REB</th><th>AST</th><th>TOV</th><th>Context</th></tr></thead><tbody>${filtered.map(p=>`<tr><th>${comparisonPerson(p,t.id)}</th><td>${esc(p.date.slice(5))}</td><td>${fmt(p.fp)}</td><td>${fmt(p.baseline_fp)}<small> · ${p.baseline_games} GP</small></td><td class="${tone(p.delta)}">${signed(p.delta)}</td>${["pts","reb","ast","tov"].map(k=>`<td>${fmt(p[k],0)}</td>`).join("")}<td><span class="film-context ${locked(p) ? "is-banked" : ""}">${locked(p) ? "Banked" : "Observed"}</span></td></tr>`).join("") || '<tr><td colspan="10">No performances match this filter.</td></tr>'}</tbody></table></div>
    <p class="review-scope">Bench and reserve games are included as observed performances. Baselines use 3–10 strictly earlier stored games; missing baselines remain blank. The day bars average only games with a baseline. Underperformance is not automatically a lock mistake.</p>`;
}

function sheetView() {
  return LockInInsights.rosterSheet(
    LockInInsights.repinLineup(team() || {}, state.mode !== "test"),
    state.mode !== "test",
  );
}
const lockIcon =
  '<svg viewBox="0 0 16 16" aria-hidden="true"><rect x="3" y="7" width="10" height="7" rx="1.5"/><path d="M5.5 7V5a2.5 2.5 0 0 1 5 0v2"/></svg>';
function lockEndpoint() {
  const configured = document
    .querySelector('meta[name="lockin-lock-endpoint"]')
    ?.content?.trim();
  return configured || (hosted ? null : "/api/lock");
}

function canLock(p, i) {
  const t = team();
  const row = t?.results?.[i];
  return state.mode === "live" && t?.source === "sleeper" && row?.starter === true && !p.vacant;
}
function lockButton(p, i) {
  if (!canLock(p, i)) return "";
  const locked = Boolean(p.is_locked);
  return `<button class="lock-toggle${locked ? " is-locked" : ""}" data-lock="${i}" aria-pressed="${locked}" title="${locked ? "Locked in Sleeper — tap to remove the flag" : "Mark locked in Sleeper"}" aria-label="${locked ? "Remove lock flag" : "Mark locked"}: ${esc(p.player)}">${lockIcon}${locked ? '<span class="lock-chip">LOCKED</span>' : ""}</button>`;
}
async function postLock(endpoint, passcode, payload) {
  const headers = {"Content-Type": "application/json"};
  if (endpoint.startsWith("/")) headers["X-CSRF-Token"] = state.csrf;
  else if (passcode) headers["x-lockin-passcode"] = passcode;
  const response = await fetch(endpoint, {
    method: "POST",
    headers,
    body: JSON.stringify(payload),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(data.error || "Could not save the lock. Try again.");
    error.status = response.status;
    throw error;
  }
  return data;
}
async function toggleLock(i) {
  const t = team();
  const row = t?.results?.[i];
  if (!row || !canLock(row, i)) return;
  const locking = !row.is_locked;
  const key = String(row.sleeper_id || row.player_id || row.player);
  const lastGame = [...(row.week_games || [])].reverse().find(g => Number.isFinite(g.fp));
  const player = {
    player_id: row.sleeper_id ? String(row.sleeper_id) : null,
    player_name: row.player,
    roster_slot: row.roster_slot,
    slot_index: Number.isInteger(row.lineup_order) ? row.lineup_order : null,
    locked_fp: locking && lastGame ? lastGame.fp : null,
    game_date: locking && lastGame ? lastGame.date : null,
  };
  // hosted render() rebuilds state.data from publishedSource, so both layers
  // carry the optimistic flag; snapshots restore on failure.
  const targets = [t];
  const sourceTeam = hosted
    ? publishedSource?.teams?.find((x) => x.id === t.id)
    : null;
  if (sourceTeam) targets.push(sourceTeam);
  const snapshots = targets.map((x) => ({team: x, locks: x.locks ? {...x.locks} : {}, locked: x.results?.[i]?.is_locked}));
  for (const x of targets) {
    const locks = {...(x.locks || {})};
    if (locking) locks[key] = player;
    else delete locks[key];
    x.locks = locks;
    if (x.results?.[i]) x.results[i].is_locked = locking;
  }
  render();
  const revert = () => {
    for (const {team: x, locks, locked} of snapshots) {
      x.locks = locks;
      if (x.results?.[i]) x.results[i].is_locked = locked;
    }
    render();
  };
  const endpoint = lockEndpoint();
  if (!endpoint) {
    toast(locking ? "Marked locked on this device only." : "Lock flag removed on this device.");
    return;
  }
  const payload = {
    league_id: t.league_id,
    schedule_week: state.data?.locks_week,
    action: locking ? "lock" : "unlock",
    player,
  };
  try {
    // Open endpoints never need a passcode; a 401 means one is configured.
    try {
      await postLock(endpoint, localStorage.getItem("lockin_passcode") || "", payload);
    } catch (e) {
      if (e.status !== 401) throw e;
      const passcode =
        window.prompt("Enter your LockIn passcode to sync this lock:")?.trim() || "";
      if (!passcode) {
        revert();
        return;
      }
      localStorage.setItem("lockin_passcode", passcode);
      try {
        await postLock(endpoint, passcode, payload);
      } catch (retry) {
        if (retry.status === 401) localStorage.removeItem("lockin_passcode");
        throw retry;
      }
    }
    toast(locking ? "Locked in — pinned for this week." : "Lock flag removed.");
  } catch (e) {
    revert();
    toast(e.message || "Could not save the lock. Change reverted.");
  }
}
// Pull the latest committed lock document so phone-made locks appear on
// every device before the next daily publish, without waiting for it.
async function syncLocks() {
  const endpoint = lockEndpoint();
  if (!hosted || state.mode !== "live" || !endpoint || endpoint.startsWith("/"))
    return;
  let doc;
  try {
    const response = await fetch(endpoint, { cache: "no-store" });
    if (!response.ok) return;
    doc = await response.json();
  } catch {
    return;
  }
  const leagues = doc?.leagues;
  if (!leagues || typeof leagues !== "object") return;
  const week = state.data?.locks_week;
  let changed = false;
  for (const t of state.data?.teams || []) {
    const record = leagues[String(t.league_id)];
    const remoteLocks =
      record && String(record.schedule_week) === String(week)
        ? { ...(record.locks || {}) }
        : {};
    if (JSON.stringify(remoteLocks) === JSON.stringify(t.locks || {})) continue;
    const targets = new Set([
      t,
      publishedSource?.teams?.find((x) => x.id === t.id),
    ]);
    targets.delete(undefined);
    for (const target of targets) {
      target.locks = { ...remoteLocks };
      for (const row of target.results || [])
        row.is_locked = Object.values(remoteLocks).some((r) =>
          LockInInsights.lockMatches(row, r),
        );
    }
    changed = true;
  }
  if (changed) render();
}
function renderLineup() {
  $("#practice-lineup").hidden = state.mode !== "test" || state.view !== "team";
  if (!$("#practice-lineup").hidden) renderPracticeLineup();
  const t = team(), daily = LockInInsights.repinLineup(t || {}, state.mode !== "test").recommended_lineup;
  const target = $("#recommended-lineup");
  target.hidden = state.view !== "team" || state.mode === "test";
  if (!t || target.hidden) { target.innerHTML = ""; return; }
  const available = sheetView().recommended;
  const day = daily?.date || state.data.date;
  const dateLabel = /^\d{4}-\d{2}-\d{2}$/.test(day || "")
    ? new Date(day + "T12:00:00").toLocaleDateString(undefined, {weekday: "short", month: "short", day: "numeric"}) : "Saved report";
  target.innerHTML = `<div class="roster-plan-heading"><div><span class="section-label">${esc(dateLabel)} · LATEST REFRESH</span><h3 id="lineup-title">${available ? "Recommended lineup" : "Synced roster"}</h3></div>
    ${available ? `<div class="roster-plan-total"><strong>${fmt(daily.total_projected_fp)}</strong><span>projected FP · ${daily.filled_slots}/${daily.slots.length} slots</span></div>` : ""}</div>
    ${!available || daily.status !== "ready" ? `<p class="lineup-message">${esc(available ? daily.reason : (daily?.status === "unavailable" ? daily.reason : "No matching recommended lineup in this report. Showing the saved roster."))}</p>` : ""}
    <details class="roster-plan-method"><summary>Snapshot details</summary><p>Lineup for ${esc(day)}, saved ${esc(new Date(state.data.generated_at).toLocaleString())}. It stays here until the next data refresh.${state.data.stale || state.data.refresh_status === "failed" ? " This is an older saved plan; refresh before using it for a new day." : ""} Add or drop players in Sleeper, then refresh and publish from your Mac.</p><p>Maximizes projected FP across this league’s position slots and players eligible to start at refresh time. Out and reserve players are excluded. Questionable players are included without an injury adjustment. Empty slots add zero. This does not change your Sleeper lineup.</p></details>`;
}
function renderPracticeLineup() {
  const t = team();
  let daily = t?.recommended_lineup;
  const target = $("#practice-lineup");
  if (!t) { target.innerHTML = ""; return; }
  const slots = daily?.slots || [], bench = daily?.bench || [];
  const available = daily && daily.status !== "unavailable";
  const day = daily?.date || state.data.date;
  const dateLabel = /^\d{4}-\d{2}-\d{2}$/.test(day || "")
    ? new Date(day + "T12:00:00").toLocaleDateString(undefined, {weekday: "short", month: "short", day: "numeric"}) : "Today";
  const priorCount = slots.filter(p => p.projection_source === "prior_season").length;
  const playerRow = (p, reserve = false) => {
    const index = t.results.findIndex(r => p.player_id ? String(r.player_id) === String(p.player_id) : r.player === p.player);
    const source = projectionSource(p);
    const matchup = p.opponent ? `${p.home ? "vs" : "@"} ${p.opponent}` : "";
    const context = reserve ? p.reason : [matchup, p.injury_status, p.projection_source && p.projection_source !== "current_season" ? projectionSource(p) : null].filter(Boolean).join(" · ");
    const label = p.player || "Unfilled";
    return `<div class="lineup-row${p.player ? "" : " lineup-vacant"}"><span class="lineup-slot">${esc(reserve ? "—" : p.slot)}</span>
      ${p.player && index >= 0 ? `<button class="lineup-name" data-player="${index}" aria-label="${esc(label)}. Open player details."><strong title="${esc(label)}">${esc(label)}</strong><small>${esc(context)}</small></button>` : `<span class="lineup-name"><strong>${esc(label)}</strong><small>${p.player ? esc(context) : "No eligible player"}</small></span>`}
      <span class="lineup-points" title="${esc(p.player && p.projected_fp != null ? `${source}${p.last_played ? "; through " + p.last_played : ""}. League-scored estimate, not a guaranteed score.` : "No projection")}">${fmt(p.projected_fp)}</span></div>`;
  };
  target.innerHTML = `<header class="lineup-heading"><div><span class="section-label">${esc(dateLabel)}</span><h3 id="practice-lineup-title">Recommended lineup</h3></div></header>
    ${available ? `<div class="lineup-summary"><span><strong>${fmt(daily.total_projected_fp)}</strong><small>projected FP</small></span><span class="lineup-fill">${daily.filled_slots}/${slots.length}<small>slots filled</small></span></div>
    ${daily.filled_slots ? `<div class="lineup-columns" aria-hidden="true"><span>Slot</span><span>Player / matchup</span><span>Proj.</span></div>${slots.map(p => playerRow(p)).join("")}` : `<p class="lineup-slot-list">${slots.map(p => esc(p.slot)).join(" · ")}</p>`}
    ${daily.status !== "ready" ? `<p class="lineup-message">${esc(daily.reason)}</p>` : ""}
    ${bench.length ? `<details class="lineup-bench"><summary>Not selected <span>${bench.length}</span></summary>${bench.map(p => playerRow(p, true)).join("")}</details>` : ""}` : `<p class="lineup-message">${esc(daily?.reason || "Awaiting a fresh report with league slots and projections.")}</p>`}
    <footer class="lineup-footnote">${state.mode === "test" ? "Pregame replay · before today's scores." : "Pregame snapshot · check existing Sleeper locks and tipoffs."}${priorCount ? ` ${priorCount} projection${priorCount === 1 ? " uses" : "s use"} prior-season history.` : ""}
    ${available ? `<details><summary>How this is picked</summary><p>Highest projected total using this league’s positions and eligible players scheduled that day. Estimates use league-scored history before the day, blending prior-season games into small current-season samples. Sleeper / RotoWire forecasts cover missing current history. Out and reserve players are excluded; questionable players are included without an injury adjustment. Unfilled slots add zero. This does not change your Sleeper lineup.</p></details>` : ""}</footer>`;
}
function renderInsights() {
  const t = team();
  if (!t) return;
  const players = LockInInsights.teamForm(t.results, state.data.observation_cutoff);
  const count = players.filter((p) => p.average !== null).length;
  const shown = state.insightsExpanded ? players : players.slice(0, 5);
  const saved = state.data.stale || state.data.refresh_status === "failed" ||
    t.results.some((p) => ["STALE", "DATA_UNAVAILABLE"].includes(p.status));
  $("#team-insights").innerHTML = `
    <header class="insights-heading"><div><span class="section-label">TEAM INSIGHTS</span><h3 id="insights-title">Recent form</h3></div><span class="insights-count">${count}/${players.length}<small>with history</small></span></header>
    <p class="insights-context">${t.results.some(p => p.history_source === "prior_season") ? "Latest stored games · prior seasons included" : `${saved ? "Saved history" : "Observed games"} · through ${esc(state.data.observation_cutoff || state.data.date)}`}</p>
    <div class="insight-columns" aria-hidden="true"><span>Player</span><span>Last 5</span><span>Avg FP</span></div>
    <div id="insight-players">${shown.map((p) => {
      const change = p.delta === null ? "—" : `${p.delta > 0 ? "+" : ""}${fmt(p.delta)}`;
      const tone = p.delta > 0 ? "positive" : p.delta < 0 ? "negative" : "neutral";
      const remaining = Number.isInteger(p.player.remaining_games_est) && p.player.remaining_games_est >= 0 && !saved ? `${p.player.remaining_games_est} left` : !saved && p.player.schedule_state === "verified" ? `${p.player.week_games.length} this week` : "Schedule unknown";
      const sample = p.scores.length ? `${p.scores.length} game${p.scores.length === 1 ? "" : "s"}` : "No history";
      return `<button class="insight-player" data-player="${p.index}" aria-label="${esc(p.player.player)}: ${p.average === null ? "no observed scores" : `${fmt(p.average)} average fantasy points over ${sample}`}. Open player details.">
        <span class="insight-name"><strong title="${esc(p.player.player)}">${esc(p.player.player)}</strong><small>${esc(p.player.roster_slot || (p.player.starter ? "START" : "BN"))} · ${sample} · ${p.player.history_source === "prior_season" ? "Prior season" : remaining}</small></span>
        <span class="insight-trend" aria-hidden="true" style="color:${teamAccent(p.player.nba_team)}">${LockInInsights.sparkline(p.scores)}</span>
        <span class="insight-value"><strong>${fmt(p.average)}</strong><small class="${tone}" title="Change in average FP versus the previous five games">${change}</small></span></button>`;
    }).join("") || '<p class="insights-empty">No players on this roster.</p>'}</div>
    <footer class="insights-footer"><span>Δ vs previous 5${count ? "" : " · awaiting scores"}</span>${players.length > 5 ? `<button data-insights-toggle aria-expanded="${state.insightsExpanded}" aria-controls="insight-players">${state.insightsExpanded ? "Show fewer ↑" : `All ${players.length} players ↓`}</button>` : ""}</footer>`;
}
function renderGames() {
  const games = LockInInsights.gamesToWatch(state.data?.teams || [], state.data?.date);
  const search = state.search.trim().toLowerCase();
  const shown = games
    .map((m) => ({
      ...m,
      players: m.players.filter(
        (p) =>
          !search ||
          p.player.toLowerCase().includes(search) ||
          String(p.nba_team || "").toLowerCase().includes(search) ||
          p.teams.some((name) => String(name || "").toLowerCase().includes(search)),
      ),
    }))
    .filter((m) => m.players.length);
  const rostered = games.reduce((n, m) => n + m.players.length, 0);
  const dateLabel = /^\d{4}-\d{2}-\d{2}$/.test(state.data?.date || "")
    ? new Date(state.data.date + "T12:00:00").toLocaleDateString(undefined, {
        weekday: "long",
        month: "short",
        day: "numeric",
      })
    : "Today";
  $("#content").innerHTML = `<div class="watch-board">
    <div class="review-section-heading"><h3>Games to watch</h3><span>${esc(dateLabel)} · ${games.length} ${games.length === 1 ? "matchup" : "matchups"} · ${rostered} rostered players</span></div>
    <p class="review-scope">Today's games ranked by how many of your players are involved, across every loaded team. A player rostered on multiple teams counts once. Schedules come from the latest report; tip-off times are unavailable.</p>
    ${
      shown.length
        ? shown
            .map(
              (m, rank) => `<article class="watch-card">
      <div class="watch-card-head">
        <span class="watch-rank">${rank + 1}</span>
        <div class="watch-teams">${nbaTeamLabel(m.away)}<span class="watch-at">at</span>${nbaTeamLabel(m.home)}</div>
        <span class="watch-status" data-status="${esc(m.status)}">${esc(gameStatus(m.status))}</span>
        <b class="watch-count">${m.players.length}<small> ${m.players.length === 1 ? "player" : "players"}</small></b>
      </div>
      <div class="watch-players">${m.players
        .map(
          (p) => `<button class="watch-player" data-watch="${esc(p.team_id)}:${p.index}" style="--team-accent:${teamAccent(p.nba_team)}">${portrait(p)}<span class="watch-player-id"><strong>${esc(p.player)}</strong><small>${esc((p.positions || []).join("/") || "NBA")} · ${nbaTeamLabel(p.nba_team)}${p.teams.length ? ` · ${esc(p.teams.join(" · "))}` : ""}</small></span>${p.fp != null ? `<b class="watch-fp">${fmt(p.fp)}<small> FP</small></b>` : ""}</button>`,
        )
        .join("")}</div>
    </article>`,
            )
            .join("")
        : `<div class="empty">${
            games.length
              ? "No players match that search."
              : "<strong>No games to watch.</strong><p>No rostered players are scheduled today. Matchups appear here on days your players take the floor.</p>"
          }</div>`
    }
  </div>`;
  attachImageFallback();
}
function renderContent() {
  let t = team();
  if (!t) return;
  const search = state.search.trim().toLowerCase();
  if (state.view === "review") { renderReviewHub(t); return; }
  if (state.view === "badges") {
    $("#content").innerHTML = `<div class="season-review"><section id="season-badge-board" class="season-badge-board" aria-labelledby="badge-race-title">${seasonBadgePanel(t)}</section></div>`;
    attachImageFallback();
    return;
  }
  if (state.view === "games") { renderGames(); return; }
  if (state.view === "alerts") {
    $("#content").innerHTML =
      state.data.alerts
        .map(
          (a) =>
            `<div class="alert-item"><strong>${esc(a.team || "Data service")}</strong>${esc(a.message)}</div>`,
        )
        .join("") ||
      '<div class="empty">No data failures reported for this analysis.</div>';
    return;
  }
  if (state.view === "rise") {
    $("#content").innerHTML =
      t.pickups
        .map((p, i) => ({ p, i }))
        .filter(({ p }) => p.player.toLowerCase().includes(search))
        .map(
          ({ p, i }) => pickupCard(p, i, t),
        )
        .join("") ||
      '<div class="empty">No qualifying candidates in this view.<br>Completed and undrafted leagues have no live pickup analysis.' +
        (hosted ? "" : " Use Test Week to explore sample signals.") +
        "</div>";
    const rankedNames = new Set((t.pickups || []).map(p => p.player.toLowerCase()));
    const available = (t.available_players || []).filter(p =>
      !rankedNames.has(p.player.toLowerCase()) && p.player.toLowerCase().includes(search));
    if (available.length) {
      if (!t.pickups.some(p => p.player.toLowerCase().includes(search))) $("#content").innerHTML = "";
      $("#content").innerHTML += `<section class="available-pool" aria-label="Unrostered players"><div class="available-heading"><h2>Available players <small>${available.length}</small></h2><span>Unranked</span></div><p class="available-note">Up to 5 games · trend needs 10. Missing stats show —. NBA rosters first.</p><div class="available-list">${available.slice(0, state.availableLimit).map(p => `<article class="available-row"><div class="player-ident">${portrait(p)}<span><span class="player-name">${esc(p.player)}</span><span class="player-meta">${nbaTeamLabel(p.nba_team)} ${esc(p.positions.join(" / "))}${p.injury_status ? ` · ${esc(p.injury_status)}` : ""}</span></span></div><div class="available-stats"><span title="${p.games_recent ? `Average of ${p.games_recent} observed game(s)` : "No observed games"}">Recent FP<b>${fmt(p.recent_fp)}</b></span><span>Baseline<b>${fmt(p.baseline_fp)}</b></span><span>Trend<b>${p.lift > 0 ? "+" : ""}${fmt(p.lift)}</b></span></div></article>`).join("")}</div>${available.length > state.availableLimit ? `<button class="available-more" data-available-more>Show more players (${available.length - state.availableLimit})</button>` : ""}</section>`;
    }
    attachImageFallback();
    return;
  }
  const sheet = sheetView();
  $('[data-filter="starters"]').textContent = sheet.recommended ? "Lineup" : "Starters";
  let rows = sheet.rows
    .filter(
      ({ p }) =>
        (state.filter === "all" ||
          (state.filter === "starters" ? p.starter : !p.starter)) &&
        p.player.toLowerCase().includes(search),
    );
  rows.sort((a, b) => (a.p.lineup_order ?? a.i) - (b.p.lineup_order ?? b.i));
  const groups = [
    [sheet.recommended ? "Recommended lineup" : state.mode === "test" ? "Starters" : "Synced starters", rows.filter(({ p }) => p.starter)],
    [
      "Bench",
      rows.filter(
        ({ p }) => !p.starter && !["IR", "TAXI"].includes(p.roster_slot),
      ),
    ],
    [
      "Injured reserve / taxi",
      rows.filter(
        ({ p }) => !p.starter && ["IR", "TAXI"].includes(p.roster_slot),
      ),
    ],
  ];
  const week = displayWeek();
  const weekLabel = week.length
    ? new Date(week[0] + "T12:00:00").toLocaleDateString("en-US", {
        month: "short",
        day: "numeric",
      }) +
      "–" +
      new Date(week[6] + "T12:00:00").toLocaleDateString("en-US", {
        day: "numeric",
      })
    : "Schedule";
  const sections = groups
    .filter(([, group]) => group.length)
    .map(
      ([label, group]) =>
        `<section class="roster-group" aria-label="${label}"><div class="roster-group-title"><h3>${label} <span>${group.filter(({p}) => !p.vacant).length}${group.some(({p}) => p.vacant) ? "/" + group.length : ""}</span></h3><span>${esc(weekLabel)} <small>· FP · @ away</small></span></div>${group.every(({p}) => p.vacant) ? `<div class="roster-empty-slots" aria-label="Unfilled lineup slots">${group.map(({p}) => `<span class="roster-slot" data-slot="${esc(p.roster_slot)}">${esc(p.roster_slot)}</span>`).join("")}<small>No eligible starts in this snapshot</small></div>` : group.map(({ p, i }) => rosterRow(p, i, week)).join("")}</section>`,
    );
  const swap = swapCard(t);
  if (swap) sections.splice(sections.length ? 1 : 0, 0, swap);
  $("#content").innerHTML =
    sections.join("") ||
    `<div class="empty">${!t.results.length && t.league_status === "pre_draft" ? "<strong>Waiting for the draft.</strong><p>Your roster appears after the next sync.</p>" : "No players in this view."}</div>`;
  attachImageFallback();
}
function displayWeek() {
  const start = new Date(
    (state.data.schedule_week?.[0] || state.data.date) + "T12:00:00",
  );
  if (!state.data.schedule_week)
    start.setDate(start.getDate() - ((start.getDay() + 6) % 7));
  return Array.from({ length: 7 }, (_, i) => {
    const date = new Date(start);
    date.setDate(date.getDate() + i);
    return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
  });
}
function gameStatus(value) {
  return (
    {
      pre_game: "Scheduled",
      in_game: "Live",
      in_progress: "Live",
      complete: "Final",
      final: "Final",
      post_game: "Final",
    }[value] || String(value || "Unconfirmed").replaceAll("_", " ")
  );
}
function projectionSource(p) {
  return {current_season: "Recent games", blended_seasons: "Current + prior season", prior_season: "Prior season", sleeper_rotowire: "Sleeper / RotoWire"}[p?.projection_source] || "Saved estimate";
}
function projectedBox(p) {
  const s = p?.projected_stats || {};
  return ["PTS", "REB", "AST"].filter(k => s[k] != null).map(k => `${fmt(s[k])} ${k}`).join(" · ");
}
function projectionDetail(p) {
  const q = p.projection;
  if (!q) return p.projection_note ? `<section class="projection-detail"><h3>Projection unavailable</h3><p>${esc(p.projection_note)}</p></section>` : "";
  const saved = state.data.stale || state.data.refresh_status === "failed";
  const stats = ["MIN", "PTS", "REB", "AST", "STL", "BLK", "TOV", "FG3M", "FGM", "FGA", "FTM", "FTA"];
  return `<section class="projection-detail"><header><h3>Projected per game</h3><strong>${fmt(q.projected_fp)} <small>FP</small></strong></header><p>${esc(projectionSource(q))} · as of ${esc(q.as_of)}${saved ? " · saved snapshot" : ""}</p>
    <div class="projected-stat-grid">${stats.map(k => `<div><small>${k === "FG3M" ? "3PM" : k}</small><strong>${fmt(q.projected_stats?.[k])}</strong></div>`).join("")}</div>
    <p>Per-game estimate when active; availability is shown separately. Weekly game tiles repeat this baseline for each matchup, without opponent adjustments.</p>
    ${q.projection_source === "blended_seasons" ? `<p>${q.current_season_games} current-season + ${q.prior_season_games} prior-season games. Prior games fill the ${q.projection_window_games}-game window until enough current-season games are available; newer games carry more weight.</p>` : ""}
    ${q.last_played ? `<p>${q.sample_size} games in the recent window · last played ${esc(q.last_played)}.</p>` : `<p>Current-season forecast updated ${esc(q.source_updated_at?.slice(0,10) || q.as_of)}.</p>`}
    ${(team()?.scoring_notes || []).length ? `<details><summary>Scoring method</summary><p>${team().scoring_notes.map(esc).join(" ")}</p></details>` : ""}</section>`;
}
function rosterRow(p, i, week) {
  if (p.vacant) return `<div class="roster-vacancy"><span class="roster-slot" data-slot="${esc(p.roster_slot)}">${esc(p.roster_slot)}</span><span>Unfilled<small>No eligible player in this snapshot</small></span><span>—</span></div>`;
  const slot = p.roster_slot || (p.starter ? "START" : "BN");
  const injury =
    p.injury_status && p.injury_status !== "Healthy"
      ? `<span class="injury">${esc(p.injury_status)}</span>`
      : "";
  const games = week.map((date, day) => {
    const onDay = (p.week_games || []).filter(g => g.date === date);
    const known = p.schedule_state === "verified";
    const weekday = ["M", "T", "W", "T", "F", "S", "S"][day];
    const entries = onDay.map(g => ({game: g, score: LockInInsights.gameFantasy(p, g)}));
    const desc = entries.length ? entries.map(({game, score}) =>
      `${game.home ? "vs" : "at"} ${game.opponent} · ${score.description}${score.kind === "actual" ? " · " + playerPerformance(p, score.value).label : ""}`).join("; ")
      : known ? "No game scheduled" : "Schedule unavailable";
    return `<span class="game-day ${onDay.length ? "has-game" : ""} ${date === state.data.date ? "is-today" : ""} ${!known ? "unknown" : ""}" title="${esc(date + ": " + desc)}" aria-label="${esc(date + ": " + desc)}">${entries.map(({game, score}) =>
      `<span class="game-matchup"><small>${weekday}</small><b>${game.home ? "" : "@"}${esc(game.opponent)}</b></span><em class="game-score" data-kind="${score.kind}" data-performance="${score.kind === "actual" ? playerPerformance(p, score.value).tone : "unknown"}"><span>${score.label}</span> ${fmt(score.value)}</em>`).join("") ||
      `<span class="game-matchup"><small>${weekday}</small><b>${known ? "—" : "?"}</b></span>`}</span>`;
  }).join("");
  return `<div class="player-row" data-status="${esc(rowStatus(p))}" role="button" tabindex="0" data-player="${i}" aria-label="View ${esc(p.player)} details"><span class="roster-slot" data-slot="${esc(slot)}" title="Lineup slot">${esc(slot)}</span>${portrait(p)}<div class="player-ident"><div class="player-name-line"><div class="player-name" title="${esc(p.player)}">${esc(p.player)}</div>${dailyBadgeStrip(p)}</div><div class="player-meta">${nbaTeamLabel(p.nba_team)}<span>${esc((p.positions || []).join("/") || "Position unknown")}</span>${injury}</div><div class="form-line">${p.projection ? `Proj ${fmt(p.lineup_fp ?? p.projection.projected_fp)} FP · ${esc(projectionSource(p.projection))}` : p.fp_mean_recent != null ? `Avg ${fmt(p.fp_mean_recent)} FP` : p.projection_note ? "Projection unavailable · open details" : p.status === "UPCOMING" ? "Awaiting season results" : "Open for details"}${p.remaining_games_est != null ? ` · ${p.remaining_games_est} left` : ""}</div>${p.projection ? `<div class="roster-projected-stats">${esc(projectedBox(p.projection))}</div>` : ""}${p.lineup_reason ? `<div class="roster-bench-reason">${esc(p.lineup_reason)}</div>` : ""}</div><div class="player-call">${lockButton(p, i)}${badge(p)}${p.last_game_fp != null ? `<strong>${performanceNumber(p, p.last_game_fp, " <small>FP</small>")}</strong>` : ""}${p.banked ? `<span class="banked-score">${fmt(p.banked.fp)} kept</span>` : ""}${p.can_bank ? `<button class="bank-button" data-bank="${i}">Bank score</button>` : ""}</div><div class="player-week" aria-label="Weekly games and fantasy points">${games}</div></div>`;
}
function pickupCard(p, i, t) {
  const index = (t.results || []).findIndex(r=>r.player === p.replacement);
  const drop = index >= 0 ? t.results[index] : {player:p.replacement};
  const positive = Number.isFinite(p.team_gain) && p.team_gain > 0;
  const replacement = p.replacement ? `<div class="pickup-replacement">
      <span class="swap-sign ${positive ? "stat-negative" : ""}" aria-hidden="true">${positive ? "−" : "↔"}</span>
      ${index >= 0 ? `<button class="compare-person" data-player="${index}">` : '<div class="compare-person">'}${portrait(drop)}<span><small>${positive ? "Drop candidate" : "Roster comparison"}</small><strong>${esc(p.replacement)}</strong></span>${index >= 0 ? "</button>" : "</div>"}
      <b class="${positive ? "stat-positive" : "stat-negative"}">${p.team_gain > 0 ? "+" : ""}${fmt(p.team_gain)}<small>estimated fit FP</small></b></div>` : '<div class="pickup-replacement"><small>No position-compatible replacement established.</small></div>';
  return `<article class="pickup-item compact-pickup">
    <div class="pickup-heading"><span class="swap-sign stat-positive" aria-hidden="true">+</span><button class="player-ident" data-pickup="${i}">${portrait(p)}<span><small class="pickup-action">Add candidate</small><span class="player-name">${esc(p.player)}</span><span class="player-meta">${esc(p.nba_team)} · ${esc((p.positions || []).join(" / "))}</span></span></button><span class="lift">${p.lift > 0 ? "+" : ""}${fmt(p.lift)}<small>FP trend</small></span></div>
    <div class="pickup-metrics"><span>Last ${p.games_recent} games<b>${fmt(p.recent_fp)} <small>FP</small></b></span><span>Earlier ${p.games_baseline}<b>${fmt(p.baseline_fp)} <small>FP</small></b></span><span>Minutes / game<b>${fmt(p.baseline_minutes)} → ${fmt(p.minutes)}</b></span></div>
    ${replacement}
    <div class="pickup-footnote"><span>${Number.isFinite(p.consistency) ? `${Math.round(p.consistency*100)}% above baseline · ` : ""}${esc(p.availability || "Availability unknown")}</span>
      ${p.risks?.length ? `<details><summary>${p.risks.length} sample / scoring notes</summary><p class="pickup-risks">${esc(p.risks.join(" "))}</p></details>` : ""}</div>
  </article>`;
}
function swapCard(t) {
  const swap = t?.swap_suggestion;
  if (!swap) return "";
  const heading = `<section class="roster-group" aria-label="Add and drop suggestion"><div class="roster-group-title"><h3>Add / drop</h3><span>Waiver check · this week + next</span></div>`;
  if (swap.status === "suggest" && swap.add && swap.drop) {
    const pickupIndex = (t.pickups || []).findIndex(
      (p) => swap.add.player_id && String(p.player_id) === String(swap.add.player_id),
    );
    const dropIndex = (t.results || []).findIndex((r) => r.player === swap.drop.player);
    const addName = pickupIndex >= 0
      ? `<button class="swap-name" data-pickup="${pickupIndex}">${esc(swap.add.player)}</button>`
      : `<strong>${esc(swap.add.player)}</strong>`;
    const dropName = dropIndex >= 0
      ? `<button class="swap-name" data-player="${dropIndex}">${esc(swap.drop.player)}</button>`
      : `<strong>${esc(swap.drop.player)}</strong>`;
    const dropRow = dropIndex >= 0 ? t.results[dropIndex] : null;
    const move = (kind, sign, label, who, name, meta, sub) => `<div class="swap-move swap-${kind}">
      <span class="swap-sign" aria-hidden="true">${sign}</span>
      ${portrait({player: who.player, player_id: who.player_id})}
      <div class="swap-side"><small>${esc(label)}</small>${name}<span>${meta}</span><small>${sub}</small></div>
    </div>`;
    return `${heading}<article class="swap-card" data-status="suggest">
      ${move("add", "+", "ADD · On the Rise", swap.add, addName, `${nbaTeamLabel(swap.add.nba_team)} ${esc((swap.add.positions || []).join("/"))} · ~${fmt(swap.add.projected_fp)} FP/g`, `${swap.add.remaining_games} left this week${swap.add.plays_today ? " · plays tonight" : ""}`)}
      ${move("drop", "−", "DROP", {player: swap.drop.player, player_id: swap.drop.player_id || dropRow?.player_id}, dropName, `~${fmt(swap.drop.value)} FP/g · ${esc((swap.drop.positions || []).join("/"))}`, `${swap.drop.remaining_games} left this week${swap.drop.plays_today ? " · plays tonight" : ""}`)}
      <p class="swap-note"><b class="swap-net">Net ${swap.net_fp > 0 ? "+" : ""}${fmt(swap.net_fp)} FP</b> · ${esc(swap.explanation)}${swap.add.availability ? ` ${esc(swap.add.availability)}.` : ""}</p>
    </article></section>`;
  }
  return `${heading}<article class="swap-card" data-status="hold"><p class="swap-note"><b>Hold your roster.</b> ${esc(swap.explanation || "No waiver move clears the long-run bar in this snapshot.")}</p></article></section>`;
}
function playerDailyBadges(p) {
  if (state.data?.stale || state.data?.refresh_status === "failed") return [];
  const reference = state.mode === "test" ? state.data.date : LockInPages.currentDate(new Date());
  return LockInInsights.dailyBadges(p, reference);
}
function dailyBadgeStrip(p) {
  const badges = playerDailyBadges(p);
  if (!badges.length) return "";
  return `<span class="daily-badges" aria-label="${esc(badges.map(b => b.label).join('; '))}">${badges.slice(0, 3).map(b => `<span class="daily-badge" title="${esc(b.label)}" aria-hidden="true">${b.icon}</span>`).join("")}${badges.length > 3 ? `<small title="${esc(badges.slice(3).map(b => b.label).join('; '))}">+${badges.length - 3}</small>` : ""}</span>`;
}
function dailyBadgeDetails(p) {
  const badges = playerDailyBadges(p);
  if (!badges.length) return "";
  return `<section class="daily-badge-details" aria-label="Previous-night badges"><div class="daily-badge-heading">Last night's badges <span>${esc(badges[0].date)}</span></div>${badges.map(b => `<div><span aria-hidden="true">${b.icon}</span><span>${esc(b.label.split(' · ').slice(0, -1).join(' · '))}</span></div>`).join("")}</section>`;
}
function playerBadgeSection(p) {
  const review = team().season_badges || {};
  const badges = LockInInsights.playerSeasonBadges(team(), p.player_id);
  const totals = [["total", "Total", "All awards earned"], ["negative", "Chaos", "Negative indicators"], ["milestones", "Milestones", "Double-doubles, triple-doubles and stat thresholds"], ["variety", "Variety", "Distinct badge types earned, out of the types this player can reach. Age badges need a qualifying birthday."]];
  const saved = review.status === "saved" || state.data.stale || state.data.refresh_status === "failed";
  return `<section class="player-season-badges" aria-labelledby="player-badges-title"><header><h3 id="player-badges-title">Season badges</h3><span>${esc(review.season || team().season || "Season")}${saved ? " · saved" : ""}</span></header>
    ${badges.available ? `<dl class="player-badge-totals">${totals.map(([key,label,description]) => `<div title="${description}"><dt>${label}</dt><dd>${key === "variety" ? `${badges.variety}/${badges.variety_cap}` : badges[key].toLocaleString()}</dd></div>`).join("")}</dl>
    ${badges.earned.length ? `<details class="player-badge-collection"><summary>Earned badges <span>${badges.variety}/${badges.variety_cap} types</span></summary><ul>${badges.earned.map(b => `<li title="${esc(b.rule)}"><span aria-hidden="true">${b.icon}</span><span>${esc(b.name)}</span><b aria-label="${b.count} ${b.count === 1 ? "award" : "awards"}">×${b.count}</b></li>`).join("")}</ul><p>Chaos counts negative indicators; variety counts distinct types out of ${badges.variety_cap} reachable for this player — the two age badges never both qualify. Milestones include double-/triple-doubles and stat thresholds. One award per badge per game night.</p></details>` : '<p>No badges recorded for this player yet.</p>'}
    <p class="player-badge-coverage">${review.as_of ? `Through ${esc(review.as_of)} · ` : ""}This league’s scoring · stored season games</p>` : '<p>Season badge history is unavailable in this report.</p>'}</section>`;
}
function showPlayer(p) {
  if (!p) return;
  const hasPerformance = !p.badge_profile || p.recent_fp != null || p.history?.length || p.projection;

  $("#player-dialog").style.setProperty("--team-accent", teamAccent(p.nba_team));
  let h = p.history || [];
  if (p.banked)
    p = {
      ...p,
      note: `You banked ${fmt(p.banked.fp)} FP from ${p.banked.game_date}. This score stays fixed as later games are revealed. Model call when banked: ${p.banked.model_status}.`,
    };
  let last = h.slice(-10);
  let max = Math.max(1, ...last.map((r) => Math.abs(r.fp)));
  $("#player-detail").innerHTML =
    `<div class="detail-hero">${portrait(p, !!p.badge_profile)}<div><div class="eyebrow">${p.nba_team ? nbaTeamLabel(p.nba_team) : "PLAYER PROFILE"}</div><h2>${esc(p.player)}</h2>${p.status ? badge(p) : p.badge_profile ? '<span class="detail-profile-label">NBA player</span>' : '<span class="status lock">ON THE RISE</span>'}${p.injury_status && p.injury_status !== "Healthy" ? `<span class="injury">${esc(p.injury_status)}</span>` : ""}</div></div>${hasPerformance ? `<div class="detail-stats"><div class="detail-stat"><small>${p.projection ? "Projected per game" : p.recent_fp != null ? "Recent average" : "Latest score"}</small><b>${p.projection || p.recent_fp != null ? fmt(p.projection?.projected_fp ?? p.recent_fp) : performanceNumber(p, p.last_game_fp)} <small style="display:inline">FP</small></b></div><div class="detail-stat"><small>${p.projection ? (p.history_source === "prior_season" ? "Last prior-season game" : "Last observed game") : "Baseline"}</small><b>${p.projection ? (h.length ? performanceNumber(p, p.last_game_fp ?? h[h.length - 1].fp) : "No games") : fmt(p.baseline_fp ?? p.fp_mean_recent)}</b></div><div class="detail-stat"><small>${p.consistency != null ? "Above baseline" : p.remaining_games_est != null ? "Remaining games" : "Scheduled this week"}</small><b>${p.consistency != null ? Math.round(p.consistency * 100) + "%" : fmt(p.remaining_games_est ?? (p.schedule_state === "verified" ? p.week_games.length : null), 0)}</b></div></div><div class="detail-reason">${esc(p.note || p.reason || (p.badge_profile ? "Observed performance using this league’s scoring." : (p.availability || "Availability unknown") + ". " + (p.replacement ? "Estimated replacement: " + p.replacement + "." : "Team fit needs review.")))}</div>` : ""}${playerBadgeSection(p)}${p.baseline_source === "blended_seasons" ? `<p class="projection-note">Lock baseline: ${p.baseline_current_season_games} current-season + ${p.baseline_prior_season_games} prior-season games. Older games provide context; only this week’s completed score can be locked.</p>` : ""}${dailyBadgeDetails(p)}${projectionDetail(p)}${p.week_games?.length ? `<div class="detail-schedule"><h3>This week</h3>${p.week_games.map((g) => `<div><span>${esc(g.date.slice(5))}</span><strong>${g.home ? "vs" : "@"} ${esc(g.opponent)}</strong><span>${g.fp != null ? performanceNumber(p, g.fp, " FP") : esc(gameStatus(g.status))}</span></div>`).join("")}<p>Schedule dates shown. Tip-off times are unavailable.</p></div>` : ""}${[...(p.warnings || []), ...(p.risks || [])].map((w) => `<p class="detail-warning">${esc(w)}</p>`).join("")}${
      last.length
        ? `<div class="section-label" style="margin-top:25px">${p.history_source === "prior_season" ? "PRIOR-SEASON FANTASY PRODUCTION" : "RECENT FANTASY PRODUCTION"}</div>${performanceLegend(p)}<div class="chart">${last.map((r) => `<div class="bar-wrap" data-performance="${playerPerformance(p, r.fp).tone}" title="${esc(r.date)}: ${fmt(r.fp)} FP · ${esc(playerPerformance(p, r.fp).label)}" aria-label="${esc(r.date)}: ${fmt(r.fp)} FP · ${esc(playerPerformance(p, r.fp).label)}"><span>${fmt(r.fp, 0)}</span><div class="bar" style="height:${Math.max(2, (Math.abs(r.fp) / max) * 108)}px;"></div></div>`).join("")}</div><p>Most recent games, oldest to newest. ${esc(state.data.observation_cutoff || state.data.date)} is the observation cutoff.</p><table class="history-table"><thead><tr><th>Date</th><th>MIN</th><th>PTS</th><th>REB</th><th>AST</th><th>STL</th><th>BLK</th><th>FP</th></tr></thead><tbody>${h
            .slice(-10)
            .reverse()
            .map(
              (r) =>
                `<tr><td>${esc(r.date.slice(5))}</td><td>${fmt(r.minutes, 0)}</td><td>${fmt(r.pts, 0)}</td><td>${fmt(r.reb, 0)}</td><td>${fmt(r.ast, 0)}</td><td>${fmt(r.stl, 0)}</td><td>${fmt(r.blk, 0)}</td><td>${performanceNumber(p, r.fp)}</td></tr>`,
            )
            .join("")}</tbody></table>`
        : p.signal_score != null
          ? "<p>Rise scores compare five recent games with a separate earlier baseline. They are screening signals, not probabilities of future success.</p>"
          : p.badge_profile ? "<p class=\"performance-note\">Game-by-game performance is not included for this player in this report.</p>" : "<p>No observed performances available for this player in this report.</p>"
    }`;
  attachImageFallback();
  $("#player-dialog").showModal();
  $("#player-dialog").scrollTop = 0;
}
async function job(path, body) {
  if (state.busy) return;
  state.busy = true;
  $("#refresh").disabled = true;
  $("#sync-form button").disabled = true;
  try {
    let j = await api(path, body);
    toast("Refresh started. Saved responses will be reused.");
    let result;
    do {
      await new Promise((r) => setTimeout(r, 1200));
      result = await api("/api/jobs/" + j.job_id);
    } while (result.status === "running");
    if (result.status === "failed") throw new Error(result.error);
    toast(result.result.message || "Refresh complete.");
    if ($("#connect-dialog").open) $("#connect-dialog").close();
    await load();
  } catch (e) {
    if (!state.data)
      $("#content").innerHTML =
        '<div class="empty">Refresh unavailable. No current recommendations issued.</div>';
    fail(e.message);
    toast(e.message);
  } finally {
    state.busy = false;
    $("#refresh").disabled = false;
    $("#sync-form button").disabled = false;
  }
}
function editRoster() {
  let t = team();
  if (t.source === "sleeper") {
    toast(
      "This roster is managed by Sleeper. Sync after adding or dropping players there.",
    );
    return;
  }
  $("#roster-editor").innerHTML = t.results
    .map(
      (p, i) =>
        `<div class="roster-edit-row"><label><input type="checkbox" data-toggle="${i}" ${p.starter ? "checked" : ""}>${esc(p.player)}</label><span class="muted" style="font-size:10px">${p.starter ? "Starter" : "Bench"}</span><button class="remove" data-remove="${i}">Remove</button></div>`,
    )
    .join("");
  if (!$("#roster-dialog").open) $("#roster-dialog").showModal();
}
async function changeRoster(action, player) {
  if (state.mode === "test") {
    await testAction(action, player);
    editRoster();
    return;
  }
  try {
    await api("/api/roster", { team_id: team().id, action, player });
    await load();
    editRoster();
    toast("Roster saved.");
  } catch (e) {
    toast(e.message);
  }
}
// Close player details when a mouse press or touch starts outside the card.
const playerDialog = $("#player-dialog");

document.addEventListener("pointerdown", (e) => {
  if (!playerDialog.open || e.button !== 0) return;

  const rect = playerDialog.getBoundingClientRect();
  const outside =
    e.clientX < rect.left ||
    e.clientX > rect.right ||
    e.clientY < rect.top ||
    e.clientY > rect.bottom;

  if (outside) {
    e.preventDefault();
    playerDialog.close();
  }
}, true);
document.addEventListener("click", (e) => {
  if(e.target.closest("[data-season-reset]")) {
    delete state.seasonContexts[team().id]; renderContent();
    $("[data-season-context='range']")?.focus({preventScroll:true});
    return;
  }
  const seasonFocus=e.target.closest("[data-season-focus]");
  if(seasonFocus) {
    seasonContext().player=seasonFocus.dataset.seasonFocus;seasonContext().logLimit=40;
    renderContent();$(".season-explorer").scrollIntoView({block:"start"});
    $("[data-season-context='player']")?.focus({preventScroll:true});
    return;
  }
  if(e.target.closest("[data-season-more]")) {
    seasonContext().logLimit+=40;$("#season-game-table").innerHTML=seasonGamesHtml(team());
    attachImageFallback();return;
  }
  if(e.target.closest("[data-season-csv]")) {
    const c=seasonContext(), x=LockInInsights.seasonExplorer(team(),c);
    const rows=LockInInsights.seasonLogRows(x,{search:c.logSearch,kind:c.logKind,metric:c.logMetric});
    const url=URL.createObjectURL(new Blob([LockInInsights.seasonCsv(rows)],{type:"text/csv;charset=utf-8;"}));
    const a=document.createElement("a");a.href=url;a.download="lockin-season-games.csv";a.click();
    setTimeout(()=>URL.revokeObjectURL(url),1000);return;
  }
  let b = e.target.closest("[data-test-action]");
  if (b) {
    testAction(b.dataset.testAction);
    return;
  }
  b = e.target.closest("[data-bank]");
  if (b) {
    testAction("bank", team().results[Number(b.dataset.bank)].player);
    return;
  }
  b = e.target.closest("[data-lock]");
  if (b) {
    toggleLock(Number(b.dataset.lock));
    return;
  }
  b = e.target.closest("[data-team]");
  if (b) {
    state.team = b.dataset.team;
    state.availableLimit = 30;
    localStorage.setItem("lockin-team", state.team);
    render();
    return;
  }
  b = e.target.closest("[data-view]");
  if (b) {
    if (window.matchMedia("(max-width: 740px)").matches)
      $("#main-content").scrollIntoView({ block: "start" });
    if (b.dataset.view === "test" || b.dataset.view === "team") {
      state.mode = b.dataset.view === "test" ? "test" : "live";
      state.view = "team";
      state.search = "";
      $("#search").value = "";
      load();
    } else {
      state.view = b.dataset.view;
      if (["review", "badges"].includes(state.view) && state.mode === "test") { state.mode = "live"; load(); return; }
      render();
    }
    return;
  }
  b = e.target.closest("[data-review-tab]");
  if (b) {
    state.reviewTab = b.dataset.reviewTab;
    renderContent();
    return;
  }
  b = e.target.closest("[data-filter]");
  if (b) {
    state.filter = b.dataset.filter;
    document
      .querySelectorAll(".tab")
      .forEach((x) => x.classList.toggle("active", x === b));
    renderContent();
    return;
  }
  b = e.target.closest("[data-insights-toggle]");
  if (b) {
    state.insightsExpanded = !state.insightsExpanded;
    renderInsights();
    $("[data-insights-toggle]")?.focus({ preventScroll: true });
    return;
  }
  b = e.target.closest("[data-badge-player]");
  if (b) {
    showPlayer(LockInInsights.badgePlayer(team(), b.dataset.badgePlayer));
    return;
  }
  b = e.target.closest("[data-player]");
  if (b) {
    showPlayer(team().results[Number(b.dataset.player)]);
    return;
  }
  b = e.target.closest("[data-watch]");
  if (b) {
    const [tid, idx] = b.dataset.watch.split(":");
    const target = (state.data?.teams || []).find((x) => x.id === tid);
    if (!target) return;
    if (state.team !== tid) {
      state.team = tid;
      render();
    }
    showPlayer(target.results[Number(idx)]);
    return;
  }
  b = e.target.closest("[data-available-more]");
  if (b) { state.availableLimit += 30; renderContent(); return; }
  b = e.target.closest("[data-pickup]");
  if (b) {
    showPlayer(team().pickups[Number(b.dataset.pickup)]);
    return;
  }
  b = e.target.closest(".close");
  if (b) b.closest("dialog").close();
  b = e.target.closest("[data-remove]");
  if (b)
    changeRoster("remove", team().results[Number(b.dataset.remove)].player);
});
document.addEventListener("keydown", (e) => {
  if ((e.key === "Enter" || e.key === " ") && e.target.matches(".player-row")) {
    e.preventDefault();
    e.target.click();
  }
});
$("#roster-editor").addEventListener("change", (e) => {
  if (e.target.matches("[data-toggle]"))
    changeRoster(
      "toggle",
      team().results[Number(e.target.dataset.toggle)].player,
    );
});
$("#search").addEventListener("input", (e) => {
  state.search = e.target.value;
  state.availableLimit = 30;
  renderContent();
});
$("#show-archived").addEventListener("change", (e) => {
  state.archived = e.target.checked;
  load();
});
$("#connect").addEventListener("click", () => $("#connect-dialog").showModal());
$("#refresh").addEventListener("click", async () => {
  if (hosted) {
    $("#refresh").disabled = true;
    await load();
    $("#refresh").disabled = false;
    return;
  }
  state.mode = "live";
  state.view = "team";
  state.data = null;
  $("#summary").innerHTML = "";
  $("#team-insights").innerHTML = "";
    $("#recommended-lineup").innerHTML = "";
    $("#recommended-lineup").hidden = true;
  $("#content").innerHTML =
    '<div class="loading"><div class="spinner"></div>Refreshing live data. Previous decisions are hidden.</div>';
  $("#notice").textContent =
    "Live refresh in progress. No recommendations until data is verified.";
  job("/api/refresh", {});
});
$("#edit-roster").addEventListener("click", editRoster);
$("#sync-form").addEventListener("submit", (e) => {
  e.preventDefault();
  job("/api/sync", {
    username: $("#sleeper-username").value,
    season: $("#sleeper-season").value,
  });
});
$("#add-form").addEventListener("submit", (e) => {
  e.preventDefault();
  changeRoster("add", $("#add-name").value);
  $("#add-name").value = "";
});
(async () => {
  try {
    if (hosted) {
      for (const selector of [
        "#connect",
        "#mobile-connect",
        "#archive-control",
        "#edit-roster",
        '[data-view="test"]',
      ])
        $(selector).hidden = true;
      $("#refresh").textContent = "↻ Reload report";
      await load();
      return;
    }
    const init = await api("/api/bootstrap");
    state.csrf = init.csrf;
    state.account = init.sleeper;
    $("#players").innerHTML = init.players
      .map((p) => `<option value="${esc(p.name)}"></option>`)
      .join("");
    $("#sleeper-username").value = init.sleeper.username || "";
    $("#sleeper-season").value = init.current_season;
    await load();
  } catch (e) {
    fail(e.message);
  }
})();

document
  .querySelector("#mobile-connect")
  .addEventListener("click", () =>
    document.querySelector("#connect-dialog").showModal(),
  );

function renderTestControls(t) {
  if (state.mode !== "test") return;
  const sim = state.data.simulation;
  const label = new Date(sim.date + "T12:00:00").toLocaleDateString([], {
    weekday: "long",
    month: "short",
    day: "numeric",
  });
  const night = sim.phase === "night";
  $("#test-controls").innerHTML =
    `<div class="test-clock"><div><span class="eyebrow">THE REPLAY ROOM / PRACTICE WEEK</span><h2>${esc(label)} <small>${night ? "After the games" : "Morning"}</small></h2><p>${sim.finished ? "Week complete. Bank any remaining scores or restart for another run." : night ? "Tonight’s performances are revealed. Review the model and bank scores before moving on." : "Tonight’s performances are hidden. Make your decisions, then reveal the games."}</p></div><div class="test-total"><strong>${fmt(t.banked_total || 0)}</strong><span>FP banked · ${t.banked_count || 0}/${t.results.filter((p) => p.starter).length} starters</span></div></div><div class="test-actions"><button class="primary" data-test-action="advance" ${sim.finished || state.busy ? "disabled" : ""}>${night ? "Next morning →" : "Reveal tonight’s games ▷"}</button><button class="subtle" data-test-action="reset" ${state.busy ? "disabled" : ""}>Restart week</button><span>Progress saves locally · no live requests</span></div>${night ? `<details class="night-results"><summary>Tonight’s box scores · ${t.night_results.length} roster players</summary><div class="night-grid">${t.night_results.map((p) => `<div><strong>${esc(p.player)}</strong><b>${fmt(p.fp)} FP</b><small>${fmt(p.pts, 0)} PTS · ${fmt(p.reb, 0)} REB · ${fmt(p.ast, 0)} AST · ${fmt(p.minutes, 0)} MIN</small></div>`).join("") || "No completed games for this roster tonight."}</div></details>` : ""}`;
}
async function testAction(action, player) {
  if (state.busy || !state.data?.simulation) return;
  const requestId = ++state.request;
  const selectedTeam = team().id;
  state.busy = true;
  renderTestControls(team());
  try {
    const data = await api("/api/test-week", {
      action,
      player,
      team_id: selectedTeam,
      revision: state.data.simulation.revision,
    });
    if (requestId !== state.request) return;
    state.data = data;
    render();
    toast(
      action === "bank"
        ? "Score banked for this practice week."
        : action === "reset"
          ? "New run: Monday morning."
          : "Practice week saved.",
    );
  } catch (e) {
    fail(e.message);
  } finally {
    state.busy = false;
    if (state.mode === "test" && state.data) renderTestControls(team());
  }
}

// Recheck expiry even if a tab stays open across midnight or a device sleeps.
if (hosted) {
  function recheckPublishedReport() {
    if (!state.data || !publishedSource) return;
    const next = LockInPages.prepareReport(publishedSource);
    const badgesExpired = !!document.querySelector(".daily-badges, .daily-badge-details") && state.data.date !== LockInPages.currentDate(new Date());
    if (next.stale === state.data.stale && !badgesExpired) return;
    render();
    if ((state.data.stale || badgesExpired) && $("#player-dialog").open)
      $("#player-dialog").close();
  }
  setInterval(recheckPublishedReport, 60000);
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) recheckPublishedReport();
  });
}

// Daily fun badges expire; the dated lineup snapshot remains until refresh.
if (!hosted) {
  function recheckLocalLineup() {
    if (state.data && state.mode !== "test" && state.data.date !== LockInPages.currentDate(new Date())) {
      if (document.querySelector(".daily-badges, .daily-badge-details")) {
        renderContent();
        if ($("#player-dialog").open) $("#player-dialog").close();
      }
    }
  }
  setInterval(recheckLocalLineup, 60000);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) recheckLocalLineup(); });
}

$("#badge-guide-open").addEventListener("click", () => {
  const items = LockInInsights.badgeGuide();
  $("#badge-guide-content").innerHTML = ["Nightly leaders", "Milestones", "Fantasy awards", "Streaks"].map(group =>
    `<section class="badge-guide-group"><h3>${esc(group)}</h3><div class="badge-guide-grid">${items.filter(b => b.group === group).map(b => `<article class="badge-guide-item"><span class="badge-guide-icon" aria-hidden="true">${b.icon}</span><div><h4>${esc(b.name)}</h4><p>${esc(b.rule)}</p>${b.scope === "NBA · league scoring" ? '<small>League scoring</small>' : ''}</div></article>`).join("")}</div></section>`
  ).join("");
  $("#badge-guide-dialog").showModal();
});

document.addEventListener("change", e => {
  if(e.target.matches("[data-season-context]")) {
    const key=e.target.dataset.seasonContext, c=seasonContext();
    c[key]=e.target.value;c.logLimit=40;
    renderContent();
    $(`[data-season-context="${key}"]`)?.focus({preventScroll:true});
    return;
  }
  if(e.target.matches("[data-season-roster], [data-season-log]")) {
    updateSeasonLocal(e.target);return;
  }
  if (e.target.matches("[data-compare]")) {
    const key = e.target.dataset.compare;
    if (key === "ranking") { state.compareMetric=e.target.value; renderContent(); $(`[data-compare="${key}"]`)?.focus({preventScroll:true}); }
    else { state.compareFilters[key]=e.target.value; $("#comparison-player-results").innerHTML=comparisonPlayersHtml(); attachImageFallback(); }
    return;
  }
  if (e.target.id === "film-filter") {
    state.filmFilter=e.target.value;
    renderContent();
    $("#film-filter")?.focus({preventScroll:true});
    return;
  }
  if (!["badge-race-scope", "badge-race-metric"].includes(e.target.id)) return;
  const id = e.target.id;
  if (id === "badge-race-scope") state.badgeScope = e.target.value === "nba" ? "nba" : "roster";
  else state.badgeMetric = e.target.value;
  $("#season-badge-board").innerHTML = seasonBadgePanel(team());
  attachImageFallback();
  $("#" + id)?.focus({preventScroll:true});
});
document.addEventListener("input", e => {
  if(e.target.matches("input[data-season-roster], input[data-season-log]")) {
    updateSeasonLocal(e.target);return;
  }
  if (e.target.dataset.compare === "search") {
    state.compareFilters.search=e.target.value;
    $("#comparison-player-results").innerHTML=comparisonPlayersHtml();
    attachImageFallback();
  }
  if (e.target.id === "film-margin") {
    state.filmMargins[filmMarginKey(team())]=e.target.value;
    $("#film-spotlight").innerHTML=filmSpotlightHtml(team());
    attachImageFallback();
  }
});
function updateSeasonLocal(input) {
  const c=seasonContext(), roster=!!input.dataset.seasonRoster;
  c[input.dataset.seasonRoster || input.dataset.seasonLog]=input.value;
  if(roster) $("#season-roster-table").innerHTML=seasonRosterHtml(team());
  else {c.logLimit=40;$("#season-game-table").innerHTML=seasonGamesHtml(team());}
  attachImageFallback();
}
