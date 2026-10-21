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
const colors = [
  "#b64729",
  "#355b4d",
  "#42627a",
  "#80622d",
  "#754757",
  "#5f6645",
];
let state = {
  data: null,
  team: localStorage.getItem("lockin-team"),
  view: "team",
  filter: "all",
  search: "",
  mode: "live",
  request: 0,
  archived: false,
  csrf: "",
  busy: false,
  insightsExpanded: false,
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
function portrait(p) {
  const initials = (p.player || "")
    .split(" ")
    .map((x) => x[0])
    .slice(0, 2)
    .join("");
  const id = String(p.player_id || "");
  const imageUrl = hosted
    ? state.data?.portraits?.includes(id)
      ? `./portraits/${encodeURIComponent(id)}.png`
      : `https://cdn.nba.com/headshots/nba/latest/260x190/${encodeURIComponent(id)}.png`
    : `/api/portrait/${encodeURIComponent(id)}`;
  return `<div class="portrait"><span class="initials">${esc(initials)}</span>${/^\d+$/.test(id) ? `<img src="${imageUrl}" alt="${esc(p.player)}" loading="lazy">` : ""}</div>`;
}
function attachImageFallback() {
  document.querySelectorAll(".portrait img").forEach((img) => {
    const container = img.closest(".portrait");
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
function badge(p) {
  let [label, cls] = statuses[p.status] || ["REVIEW", "review"];
  return `<span class="status ${cls}">${p.status === "LOCK" ? "✓ " : p.status === "WAIT" ? "↗ " : ""}${label}</span>`;
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
  } catch (e) {
    if (requestId !== state.request) return;
    state.data = null;
    if (hosted) publishedSource = null;
    $("#summary").innerHTML = "";
    $("#team-insights").innerHTML = "";
  $("#recommended-lineup").innerHTML = "";
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
      (t, i) =>
        `<button class="team-nav ${t.id === state.team ? "active" : ""}" data-team="${esc(t.id)}" ${t.id === state.team ? 'aria-current="true"' : ""}><span class="team-symbol" style="--team-color:${colors[i % colors.length]}">${esc(
          t.team_name
            .split(" ")
            .map((n) => n[0])
            .slice(0, 2)
            .join(""),
        )}</span><span class="label"><strong>${esc(t.team_name)}</strong><small>${esc(t.league_name)}${t.source === "sleeper" ? " · " + esc(t.season) + (t.archived ? " · ARCHIVED" : "") : " · TEST"}</small></span></button>`,
    )
    .join("");
  $("#page-title").textContent =
    state.view === "rise"
      ? "The waiver wire."
      : state.view === "alerts"
        ? "Check the tape."
        : t.team_name;
  $("#sheet-title").innerHTML =
    state.view === "rise"
      ? "On the rise<span>.</span>"
      : state.view === "alerts"
        ? "Data report<span>.</span>"
        : "Roster sheet<span>.</span>";
  $(".sheet-instruction").textContent =
    state.view === "alerts"
      ? "Check your inputs before making a call"
      : "Select a player for the full read ↗";
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
    state.view === "rise"
      ? `Candidates for ${t.team_name}, scored under this league’s rules.`
      : state.view === "alerts"
        ? "A missing input should never become a confident recommendation."
        : `${t.results.length} players · ${t.results.filter((p) => p.starter).length} starters · ${state.mode === "test" ? "Practicing with saved performances" : "Your latest saved analysis"}`;
  $("#breadcrumb").textContent =
    state.view === "rise"
      ? "On the rise"
      : state.view === "alerts"
        ? "Data alerts"
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
  const rows = t.results.filter((p) => p.starter),
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
  $("#edit-roster").hidden = hosted || state.view !== "team";
  $("#edit-roster").textContent =
    t.source === "sleeper" ? "Synced roster" : "Edit roster";
  $("#league-scope").hidden = state.view !== "rise";
  $("#league-scope").textContent =
    state.mode === "test"
      ? "Practice candidates: only this sample roster is excluded. Historical league ownership is unknown."
      : `${t.league_name} · ${t.team_name} · ${t.ownership_complete ? "All league rosters, reserves and taxi players excluded" : "League ownership unknown"}. ${t.synced_at ? "Ownership snapshot: " + new Date(t.synced_at).toLocaleString() : ""}. Switch teams to compare a different league.`;
  renderTestControls(t);
  renderContent();
  renderInsights();
  renderLineup();
  attachImageFallback();
}
function renderLineup() {
  const t = team();
  let daily = t?.recommended_lineup;
  if (daily && !hosted && state.mode !== "test" && daily.date !== LockInPages.currentDate(new Date())) {
    daily = t.recommended_lineup = {date: LockInPages.currentDate(new Date()), status: "unavailable", reason: "Awaiting a fresh report for today's lineup.", slots: [], bench: []};
  }
  const target = $("#recommended-lineup");
  if (!t) { target.innerHTML = ""; return; }
  const slots = daily?.slots || [], bench = daily?.bench || [];
  const available = daily && daily.status !== "unavailable";
  const day = daily?.date || state.data.date;
  const dateLabel = /^\d{4}-\d{2}-\d{2}$/.test(day || "")
    ? new Date(day + "T12:00:00").toLocaleDateString(undefined, {weekday: "short", month: "short", day: "numeric"}) : "Today";
  const priorCount = slots.filter(p => p.projection_source === "prior_season").length;
  const playerRow = (p, reserve = false) => {
    const index = t.results.findIndex(r => p.player_id ? String(r.player_id) === String(p.player_id) : r.player === p.player);
    const source = p.projection_source === "prior_season" ? "Prior season" : `${p.sample_size || 0} recent games`;
    const matchup = p.opponent ? `${p.home ? "vs" : "@"} ${p.opponent}` : "";
    const context = reserve ? p.reason : [matchup, p.injury_status, p.projection_source === "prior_season" ? "Prior season" : null].filter(Boolean).join(" · ");
    const label = p.player || "Unfilled";
    return `<div class="lineup-row${p.player ? "" : " lineup-vacant"}"><span class="lineup-slot">${esc(reserve ? "—" : p.slot)}</span>
      ${p.player && index >= 0 ? `<button class="lineup-name" data-player="${index}" aria-label="${esc(label)}. Open player details."><strong title="${esc(label)}">${esc(label)}</strong><small>${esc(context)}</small></button>` : `<span class="lineup-name"><strong>${esc(label)}</strong><small>${p.player ? esc(context) : "No eligible player"}</small></span>`}
      <span class="lineup-points" title="${esc(p.player && p.projected_fp != null ? `${source}; through ${p.last_played}. League-scored baseline, not a guaranteed score.` : "No projection")}">${fmt(p.projected_fp)}</span></div>`;
  };
  target.innerHTML = `<header class="lineup-heading"><div><span class="section-label">${esc(dateLabel)}</span><h3 id="lineup-title">Recommended lineup</h3></div></header>
    ${available ? `<div class="lineup-summary"><span><strong>${fmt(daily.total_projected_fp)}</strong><small>projected FP</small></span><span class="lineup-fill">${daily.filled_slots}/${slots.length}<small>slots filled</small></span></div>
    ${daily.filled_slots ? `<div class="lineup-columns" aria-hidden="true"><span>Slot</span><span>Player / matchup</span><span>Proj.</span></div>${slots.map(p => playerRow(p)).join("")}` : `<p class="lineup-slot-list">${slots.map(p => esc(p.slot)).join(" · ")}</p>`}
    ${daily.status !== "ready" ? `<p class="lineup-message">${esc(daily.reason)}</p>` : ""}
    ${bench.length ? `<details class="lineup-bench"><summary>Not selected <span>${bench.length}</span></summary>${bench.map(p => playerRow(p, true)).join("")}</details>` : ""}` : `<p class="lineup-message">${esc(daily?.reason || "Awaiting a fresh report with league slots and projections.")}</p>`}
    <footer class="lineup-footnote">${state.mode === "test" ? "Pregame replay · before today's scores." : "Pregame snapshot · check existing Sleeper locks and tipoffs."}${priorCount ? ` ${priorCount} projection${priorCount === 1 ? " uses" : "s use"} prior-season history.` : ""}
    ${available ? `<details><summary>How this is picked</summary><p>Highest projected total using this league’s positions and eligible players scheduled that day. Estimates use league-scored, recency-weighted history before the day. Out and reserve players are excluded; questionable players are included without an injury adjustment. Unfilled slots add zero. This does not change your Sleeper lineup.</p></details>` : ""}</footer>`;
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
    <p class="insights-context">${saved ? "Saved history" : "Observed games"} · through ${esc(state.data.observation_cutoff || state.data.date)}</p>
    <div class="insight-columns" aria-hidden="true"><span>Player</span><span>Last 5</span><span>Avg FP</span></div>
    <div id="insight-players">${shown.map((p) => {
      const change = p.delta === null ? "—" : `${p.delta > 0 ? "+" : ""}${fmt(p.delta)}`;
      const tone = p.delta > 0 ? "positive" : p.delta < 0 ? "negative" : "neutral";
      const remaining = Number.isInteger(p.player.remaining_games_est) && p.player.remaining_games_est >= 0 && !saved ? `${p.player.remaining_games_est} left` : "Schedule —";
      const sample = p.scores.length ? `${p.scores.length} game${p.scores.length === 1 ? "" : "s"}` : "No history";
      return `<button class="insight-player" data-player="${p.index}" aria-label="${esc(p.player.player)}: ${p.average === null ? "no observed scores" : `${fmt(p.average)} average fantasy points over ${sample}`}. Open player details.">
        <span class="insight-name"><strong title="${esc(p.player.player)}">${esc(p.player.player)}</strong><small>${esc(p.player.roster_slot || (p.player.starter ? "START" : "BN"))} · ${sample} · ${remaining}</small></span>
        <span class="insight-trend" aria-hidden="true">${LockInInsights.sparkline(p.scores)}</span>
        <span class="insight-value"><strong>${fmt(p.average)}</strong><small class="${tone}" title="Change in average FP versus the previous five games">${change}</small></span></button>`;
    }).join("") || '<p class="insights-empty">No players on this roster.</p>'}</div>
    <footer class="insights-footer"><span>Δ vs previous 5${count ? "" : " · awaiting scores"}</span>${players.length > 5 ? `<button data-insights-toggle aria-expanded="${state.insightsExpanded}" aria-controls="insight-players">${state.insightsExpanded ? "Show fewer ↑" : `All ${players.length} players ↓`}</button>` : ""}</footer>`;
}
function renderContent() {
  let t = team();
  if (!t) return;
  const search = state.search.trim().toLowerCase();
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
          ({ p, i }) =>
            `<article class="pickup-item"><div class="pickup-heading"><button class="player-ident" data-pickup="${i}">${portrait(p)}<span><span class="player-name">${esc(p.player)}</span><span class="player-meta">${esc(p.nba_team)} · ${esc((p.positions || []).join(" / "))}</span></span></button><span class="lift">+${fmt(p.lift)} <small style="font-size:12px">FP</small></span></div><div class="pickup-metrics"><span>Last ${p.games_recent} games<b>${fmt(p.recent_fp)} FP</b></span><span>Earlier ${p.games_baseline} games<b>${fmt(p.baseline_fp)} FP</b></span><span>Minutes / game<b>${fmt(p.baseline_minutes)} → ${fmt(p.minutes)}</b></span></div><p class="pickup-context">${Math.round(p.consistency * 100)}% of recent games above baseline. ${esc(p.availability)}.${p.replacement ? ` Estimated fit: ${fmt(p.team_gain)} FP versus ${esc(p.replacement)}.` : " Position-compatible replacement not established."}</p>${p.risks.length ? `<p class="pickup-risks">${esc(p.risks.join(" "))}</p>` : ""}</article>`,
        )
        .join("") ||
      '<div class="empty">No qualifying candidates in this view.<br>Completed and undrafted leagues have no live pickup analysis.' +
        (hosted ? "" : " Use Test Week to explore sample signals.") +
        "</div>";
    attachImageFallback();
    return;
  }
  let rows = t.results
    .map((p, i) => ({ p, i }))
    .filter(
      ({ p }) =>
        (state.filter === "all" ||
          (state.filter === "starters" ? p.starter : !p.starter)) &&
        p.player.toLowerCase().includes(search),
    );
  rows.sort((a, b) => (a.p.lineup_order ?? a.i) - (b.p.lineup_order ?? b.i));
  const groups = [
    ["Starters", rows.filter(({ p }) => p.starter)],
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
  $("#content").innerHTML =
    groups
      .filter(([, group]) => group.length)
      .map(
        ([label, group]) =>
          `<section class="roster-group" aria-label="${label}"><div class="roster-group-title"><h3>${label} <span>${group.length}</span></h3><span>${esc(weekLabel)} <small>· @ away</small></span></div>${group.map(({ p, i }) => rosterRow(p, i, week)).join("")}</section>`,
      )
      .join("") ||
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
      in_progress: "Live",
      complete: "Final",
      final: "Final",
      post_game: "Final",
    }[value] || String(value || "Unconfirmed").replaceAll("_", " ")
  );
}
function rosterRow(p, i, week) {
  const slot = p.roster_slot || (p.starter ? "START" : "BN");
  const injury =
    p.injury_status && p.injury_status !== "Healthy"
      ? `<span class="injury">${esc(p.injury_status)}</span>`
      : "";
  const games = week
    .map((date, day) => {
      const onDay = (p.week_games || []).filter((g) => g.date === date);
      const known = p.schedule_state === "verified";
      const desc = !known
        ? "Schedule unavailable"
        : !onDay.length
          ? "No game scheduled"
          : onDay
              .map(
                (g) =>
                  `${g.home ? "vs" : "at"} ${g.opponent}${g.fp != null ? ` · ${fmt(g.fp)} FP` : ` · ${gameStatus(g.status)}`}`,
              )
              .join("; ");
      return `<span class="game-day ${onDay.length ? "has-game" : ""} ${date === state.data.date ? "is-today" : ""} ${!known ? "unknown" : ""}" title="${esc(date + ": " + desc)}" aria-label="${esc(date + ": " + desc)}"><small>${["M", "T", "W", "T", "F", "S", "S"][day]}</small>${onDay.map((g) => `<b>${g.home ? "" : "@"}${esc(g.opponent)}</b>${g.fp != null ? `<em>${fmt(g.fp)} FP</em>` : ""}`).join("") || `<b>${known ? "—" : "?"}</b>`}</span>`;
    })
    .join("");
  return `<div class="player-row" data-status="${esc(p.status)}" role="button" tabindex="0" data-player="${i}" aria-label="View ${esc(p.player)} details"><span class="roster-slot" data-slot="${esc(slot)}" title="Lineup slot">${esc(slot)}</span>${portrait(p)}<div class="player-ident"><div class="player-name" title="${esc(p.player)}">${esc(p.player)}</div><div class="player-meta"><span class="nba-team">${esc(p.nba_team || "FA / unknown")}</span><span>${esc((p.positions || []).join("/") || "Position unknown")}</span>${injury}</div><div class="form-line">${p.fp_mean_recent != null ? `Avg ${fmt(p.fp_mean_recent)} FP` : p.status === "UPCOMING" ? "Season starts soon" : "Open for details"}${p.remaining_games_est != null ? ` · ${p.remaining_games_est} left` : ""}</div></div><div class="player-call">${badge(p)}${p.last_game_fp != null ? `<strong>${fmt(p.last_game_fp)} <small>FP</small></strong>` : ""}${p.banked ? `<span class="banked-score">${fmt(p.banked.fp)} kept</span>` : ""}${p.can_bank ? `<button class="bank-button" data-bank="${i}">Bank score</button>` : ""}</div><div class="player-week" aria-label="Weekly games">${games}</div></div>`;
}
function showPlayer(p) {
  let h = p.history || [];
  if (p.banked)
    p = {
      ...p,
      note: `You banked ${fmt(p.banked.fp)} FP from ${p.banked.game_date}. This score stays fixed as later games are revealed. Model call when banked: ${p.banked.model_status}.`,
    };
  let last = h.slice(-10);
  let max = Math.max(1, ...last.map((r) => Math.abs(r.fp)));
  $("#player-detail").innerHTML =
    `<div class="detail-hero">${portrait(p)}<div><div class="eyebrow">${esc(p.nba_team || "PLAYER PROFILE")}</div><h2>${esc(p.player)}</h2>${p.status ? badge(p) : '<span class="status lock">ON THE RISE</span>'}</div></div><div class="detail-stats"><div class="detail-stat"><small>${p.recent_fp != null ? "Recent average" : "Latest score"}</small><b>${fmt(p.recent_fp ?? p.last_game_fp)} <small style="display:inline">FP</small></b></div><div class="detail-stat"><small>Baseline</small><b>${fmt(p.baseline_fp ?? p.fp_mean_recent)}</b></div><div class="detail-stat"><small>${p.consistency != null ? "Above baseline" : p.remaining_games_est != null ? "Remaining games" : "Scheduled this week"}</small><b>${p.consistency != null ? Math.round(p.consistency * 100) + "%" : fmt(p.remaining_games_est ?? (p.schedule_state === "verified" ? p.week_games.length : null), 0)}</b></div></div><div class="detail-reason">${esc(p.note || p.reason || p.availability + ". " + (p.replacement ? "Estimated replacement: " + p.replacement + "." : "Team fit needs review."))}</div>${p.week_games?.length ? `<div class="detail-schedule"><h3>This week</h3>${p.week_games.map((g) => `<div><span>${esc(g.date.slice(5))}</span><strong>${g.home ? "vs" : "@"} ${esc(g.opponent)}</strong><span>${g.fp != null ? fmt(g.fp) + " FP" : esc(gameStatus(g.status))}</span></div>`).join("")}<p>Schedule dates shown. Tip-off times are unavailable.</p></div>` : ""}${[...(p.warnings || []), ...(p.risks || [])].map((w) => `<p class="detail-warning">${esc(w)}</p>`).join("")}${
      last.length
        ? `<div class="section-label" style="margin-top:25px">RECENT FANTASY PRODUCTION</div><div class="chart">${last.map((r) => `<div class="bar-wrap" title="${esc(r.date)}: ${fmt(r.fp)} FP"><span>${fmt(r.fp, 0)}</span><div class="bar" style="height:${Math.max(2, (Math.abs(r.fp) / max) * 108)}px;${r.fp < 0 ? "background:var(--orange)" : ""}"></div></div>`).join("")}</div><p>Most recent games, oldest to newest. ${esc(state.data.observation_cutoff || state.data.date)} is the observation cutoff.</p><table class="history-table"><thead><tr><th>Date</th><th>MIN</th><th>PTS</th><th>REB</th><th>AST</th><th>STL</th><th>BLK</th><th>FP</th></tr></thead><tbody>${h
            .slice(-10)
            .reverse()
            .map(
              (r) =>
                `<tr><td>${esc(r.date.slice(5))}</td><td>${fmt(r.minutes, 0)}</td><td>${fmt(r.pts, 0)}</td><td>${fmt(r.reb, 0)}</td><td>${fmt(r.ast, 0)}</td><td>${fmt(r.stl, 0)}</td><td>${fmt(r.blk, 0)}</td><td>${fmt(r.fp)}</td></tr>`,
            )
            .join("")}</tbody></table>`
        : p.recent_fp != null
          ? "<p>Rise scores compare five recent games with a separate earlier baseline. They are screening signals, not probabilities of future success.</p>"
          : "<p>No observed performances available for this player in this report.</p>"
    }`;
  attachImageFallback();
  $("#player-dialog").showModal();
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
document.addEventListener("click", (e) => {
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
  b = e.target.closest("[data-team]");
  if (b) {
    state.team = b.dataset.team;
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
      render();
    }
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
  b = e.target.closest("[data-player]");
  if (b) {
    showPlayer(team().results[Number(b.dataset.player)]);
    return;
  }
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
    const lineupChanged = next.teams.some((t, i) => t.recommended_lineup?.status !== state.data.teams[i]?.recommended_lineup?.status);
    if (next.stale === state.data.stale && !lineupChanged) return;
    render();
    if (state.data.stale && $("#player-dialog").open)
      $("#player-dialog").close();
  }
  setInterval(recheckPublishedReport, 60000);
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) recheckPublishedReport();
  });
}

// Local tabs also hide yesterday's plan without requesting a live refresh.
if (!hosted) {
  function recheckLocalLineup() {
    const daily = team()?.recommended_lineup;
    if (state.data && state.mode !== "test" && daily && daily.date !== LockInPages.currentDate(new Date())) renderLineup();
  }
  setInterval(recheckLocalLineup, 60000);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) recheckLocalLineup(); });
}
