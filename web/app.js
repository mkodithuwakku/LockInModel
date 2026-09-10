"use strict";
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
  "#f5b870",
  "#b59cff",
  "#75c8fc",
  "#73e1bd",
  "#ff9baf",
  "#f2d67a",
  "#b0b8fa",
];
let state = {
  data: null,
  team: localStorage.getItem("lockin-team"),
  view: "team",
  filter: "all",
  search: "",
  mode: "replay",
  csrf: "",
  busy: false,
};
const statuses = {
  LEAGUE_COMPLETE: ["SEASON FINISHED", ""],
  LOCK: ["LOCK", "lock"],
  WAIT: ["WAIT", "wait"],
  SCHEDULE_UNAVAILABLE: ["CHECK SCHEDULE", "review"],
  SCORING_INCOMPLETE: ["SCORING GAP", "review"],
  DATA_UNAVAILABLE: ["DATA ISSUE", "review"],
  UNRESOLVED: ["UNMATCHED", "review"],
  NO_GAME: ["NO GAME", ""],
  NO_HISTORY: ["NO HISTORY", ""],
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
  return `<div class="portrait"><span class="initials">${esc(initials)}</span>${p.player_id ? `<img src="/api/portrait/${encodeURIComponent(p.player_id)}" alt="${esc(p.player)}" loading="lazy">` : ""}</div>`;
}
function attachImageFallback() {
  document.querySelectorAll(".portrait img").forEach((img) => {
    img.addEventListener("error", () => img.remove(), { once: true });
    if (img.complete && !img.naturalWidth) img.remove();
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
  $("#error").hidden = true;
  state.data = null;
  $("#summary").innerHTML = "";
  $("#radar").innerHTML = "";
  $("#content").innerHTML =
    '<div class="loading"><div class="spinner"></div>Reading saved player data…</div>';
  try {
    let date = $("#replay-date").value;
    state.data = await api(
      "/api/dashboard?mode=" +
        state.mode +
        (date && state.mode === "replay" ? "&date=" + date : ""),
    );
    state.team = team()?.id;
    render();
  } catch (e) {
    state.data = null;
    $("#summary").innerHTML = "";
    $("#radar").innerHTML = "";
    $("#content").innerHTML =
      '<div class="empty">No current recommendations available.<br>Saved historical data is available in Historical replay mode.</div>';
    fail(e.message);
  }
}
function render() {
  const t = team();
  if (!t) return;
  state.team = t.id;
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
        )}</span><span class="label"><strong>${esc(t.team_name)}</strong><small>${esc(t.league_name)}${t.source === "sleeper" ? " · " + esc(t.season) : " · TEST"}</small></span></button>`,
    )
    .join("");
  $("#page-title").textContent =
    state.view === "rise"
      ? "Find your next difference-maker."
      : state.view === "alerts"
        ? "Know what’s missing."
        : t.team_name;
  $("#page-title").style.fontSize = state.view === "rise" ? "42px" : "";
  $("#league-label").textContent =
    t.league_name + (t.league_status ? " · " + t.league_status : "");
  $("#page-subtitle").textContent =
    state.view === "rise"
      ? "Players gaining ground, measured against their own baseline."
      : state.view === "alerts"
        ? "A missing input should never become a confident recommendation."
        : `${t.results.length} players · ${t.results.filter((p) => p.starter).length} starters · ${state.mode === "replay" ? "Reviewing a saved week" : "Your latest saved analysis"}`;
  $("#breadcrumb").textContent =
    state.view === "rise"
      ? "On the rise"
      : state.view === "alerts"
        ? "Data alerts"
        : "My teams";
  $("#freshness").textContent =
    "Updated " +
    new Date(state.data.generated_at).toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit",
    });
  $("#notice").innerHTML =
    `<span class="context-icon">${state.mode === "replay" ? "↺" : "◉"}</span><span>${esc(state.data.notice)}</span>`;
  $("#account-label").textContent = state.data.sleeper.username
    ? "@" + state.data.sleeper.username
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
    ["Ready to lock", locks, "Strong scores worth keeping", "var(--mint)", "✓"],
    [
      "Room to improve",
      wait,
      "Wait for another opportunity",
      "var(--purple)",
      "↗",
    ],
    [
      "Needs your attention",
      review,
      "Incomplete or unavailable data",
      "var(--amber)",
      "!",
    ],
    [
      "Rising players",
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
      b.classList.toggle("active", b.dataset.view === state.view),
    );
  $(".tabs").hidden = state.view !== "team";
  $("#edit-roster").hidden = state.view !== "team";
  $("#edit-roster").textContent =
    t.source === "sleeper" ? "Synced roster" : "Edit roster";
  renderContent();
  const start = new Date(
    (state.data.dataset.week_start || state.data.date) + "T12:00:00",
  );
  if (state.mode === "live")
    start.setDate(start.getDate() - ((start.getDay() + 6) % 7));
  $("#week-days").innerHTML = Array.from({ length: 7 }, (_, i) => {
    let d = new Date(start);
    d.setDate(d.getDate() + i);
    let iso =
      d.getFullYear() +
      "-" +
      String(d.getMonth() + 1).padStart(2, "0") +
      "-" +
      String(d.getDate()).padStart(2, "0");
    return `<div class="day ${iso === state.data.date ? "selected" : ""}">${["M", "T", "W", "T", "F", "S", "S"][i]}<b>${d.getDate()}</b></div>`;
  }).join("");
  $("#week-caption").textContent =
    state.mode === "replay"
      ? `${state.data.dataset.week_start} — ${state.data.dataset.week_end} · replay`
      : "Monday through Sunday · current week";
  $("#radar").innerHTML =
    t.pickups
      .slice(0, 3)
      .map(
        (p, i) =>
          `<button class="radar-card" data-pickup="${i}">${portrait(p)}<span><strong>${esc(p.player)}</strong><small>+${fmt(p.lift)} FP above baseline</small></span></button>`,
      )
      .join("") || '<p class="muted">No qualifying signals in this window.</p>';
  attachImageFallback();
}
function renderContent() {
  let t = team();
  if (!t) return;
  const search = state.search.toLowerCase();
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
            `<article class="pickup-item"><div class="pickup-heading"><button class="player-ident" data-pickup="${i}">${portrait(p)}<span><span class="player-name">${esc(p.player)}</span><span class="player-meta">${esc(p.nba_team)} · ${esc(p.positions.join(" / "))}</span></span></button><span class="lift">+${fmt(p.lift)} <small style="font-size:12px">FP</small></span></div><div class="pickup-metrics"><span>Last ${p.games_recent} games<b>${fmt(p.recent_fp)} FP</b></span><span>Earlier ${p.games_baseline} games<b>${fmt(p.baseline_fp)} FP</b></span><span>Minutes / game<b>${fmt(p.baseline_minutes)} → ${fmt(p.minutes)}</b></span></div><p class="pickup-context">${Math.round(p.consistency * 100)}% of recent games above baseline. ${esc(p.availability)}.${p.replacement ? ` Estimated fit: ${fmt(p.team_gain)} FP versus ${esc(p.replacement)}.` : " Position-compatible replacement not established."}</p>${p.risks.length ? `<p class="pickup-risks">${esc(p.risks.join(" "))}</p>` : ""}</article>`,
        )
        .join("") ||
      '<div class="empty">No players meet the rise criteria for this view.<br>Try another saved date or clear your search.</div>';
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
  $("#content").innerHTML =
    '<div class="table-head"><span>PLAYER</span><span>LATEST FP</span><span class="baseline-col">BASELINE</span><span>THE CALL</span></div>' +
    rows
      .map(
        ({ p, i }) =>
          `<div class="player-row" role="button" tabindex="0" data-player="${i}" aria-label="View ${esc(p.player)} details"><div class="player-ident">${portrait(p)}<div><div class="player-name">${esc(p.player)}</div><div class="player-meta">${esc(p.nba_team || "NBA")} <span>·</span> ${esc(p.positions.join("/") || "—")} <span class="slot">${p.starter ? "START" : "BENCH"}</span></div></div></div><div class="numeric">${fmt(p.last_game_fp)}<small>${p.last_game_date ? esc(p.last_game_date.slice(5)) : "No eligible game"}</small></div><div class="baseline baseline-col">${fmt(p.fp_mean_recent)}<small>${p.remaining_games_est == null ? "Schedule unconfirmed" : p.remaining_games_est + " game" + (p.remaining_games_est === 1 ? "" : "s") + " left"}</small></div><div>${badge(p)}<div class="status-note">${p.p_lock != null ? Math.round(p.p_lock * 100) + "% lock score" : p.status === "SCORING_INCOMPLETE" ? "Partial FP estimate" : "Open for details"}</div></div></div>`,
      )
      .join("") +
    (rows.length ? "" : '<div class="empty">No players in this view.</div>');
  attachImageFallback();
}
function showPlayer(p) {
  let h = p.history || [];
  let last = h.slice(-10);
  let max = Math.max(1, ...last.map((r) => Math.abs(r.fp)));
  $("#player-detail").innerHTML =
    `<div class="detail-hero">${portrait(p)}<div><div class="eyebrow">${esc(p.nba_team || "PLAYER PROFILE")}</div><h2>${esc(p.player)}</h2>${p.status ? badge(p) : '<span class="status lock">ON THE RISE</span>'}</div></div><div class="detail-stats"><div class="detail-stat"><small>${p.recent_fp != null ? "Recent average" : "Latest score"}</small><b>${fmt(p.recent_fp ?? p.last_game_fp)} <small style="display:inline">FP</small></b></div><div class="detail-stat"><small>Baseline</small><b>${fmt(p.baseline_fp ?? p.fp_mean_recent)}</b></div><div class="detail-stat"><small>${p.consistency != null ? "Above baseline" : "Remaining games"}</small><b>${p.consistency != null ? Math.round(p.consistency * 100) + "%" : fmt(p.remaining_games_est, 0)}</b></div></div><div class="detail-reason">${esc(p.note || p.reason || p.availability + ". " + (p.replacement ? "Estimated replacement: " + p.replacement + "." : "Team fit needs review."))}</div>${[...(p.warnings || []), ...(p.risks || [])].map((w) => `<p class="detail-warning">${esc(w)}</p>`).join("")}${
      last.length
        ? `<div class="section-label" style="margin-top:25px">RECENT FANTASY PRODUCTION</div><div class="chart">${last.map((r) => `<div class="bar-wrap" title="${esc(r.date)}: ${fmt(r.fp)} FP"><span>${fmt(r.fp, 0)}</span><div class="bar" style="height:${Math.max(2, (Math.abs(r.fp) / max) * 108)}px;${r.fp < 0 ? "background:var(--orange)" : ""}"></div></div>`).join("")}</div><p>Most recent games, oldest to newest. ${esc(state.data.date)} is the observation cutoff.</p><table class="history-table"><thead><tr><th>Date</th><th>MIN</th><th>PTS</th><th>REB</th><th>AST</th><th>STL</th><th>BLK</th><th>FP</th></tr></thead><tbody>${h
            .slice(-10)
            .reverse()
            .map(
              (r) =>
                `<tr><td>${esc(r.date.slice(5))}</td><td>${fmt(r.minutes, 0)}</td><td>${fmt(r.pts, 0)}</td><td>${fmt(r.reb, 0)}</td><td>${fmt(r.ast, 0)}</td><td>${fmt(r.stl, 0)}</td><td>${fmt(r.blk, 0)}</td><td>${fmt(r.fp)}</td></tr>`,
            )
            .join("")}</tbody></table>`
        : "<p>Rise scores compare five recent games with a separate earlier baseline. They are screening signals, not probabilities of future success.</p>"
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
  let b = e.target.closest("[data-team]");
  if (b) {
    state.team = b.dataset.team;
    localStorage.setItem("lockin-team", state.team);
    render();
    return;
  }
  b = e.target.closest("[data-view]");
  if (b) {
    state.view = b.dataset.view;
    render();
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
$("#mode").addEventListener("change", (e) => {
  state.mode = e.target.value;
  $("#replay-date").hidden = state.mode !== "replay";
  load();
});
$("#replay-date").addEventListener("change", load);
$("#connect").addEventListener("click", () => $("#connect-dialog").showModal());
$("#refresh").addEventListener("click", () => {
  state.mode = "live";
  $("#mode").value = "live";
  $("#replay-date").hidden = true;
  state.data = null;
  $("#summary").innerHTML = "";
  $("#radar").innerHTML = "";
  $("#content").innerHTML =
    '<div class="loading"><div class="spinner"></div>Refreshing live data. Previous decisions are hidden.</div>';
  $("#notice").textContent =
    "Live refresh in progress. No recommendations until data is verified.";
  job("/api/refresh", {});
});
$("#see-risers").addEventListener("click", () => {
  state.view = "rise";
  render();
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
    const init = await api("/api/bootstrap");
    state.csrf = init.csrf;
    $("#players").innerHTML = init.players
      .map((p) => `<option value="${esc(p.name)}"></option>`)
      .join("");
    $("#sleeper-username").value = init.sleeper.username || "";
    $("#sleeper-season").value = init.sleeper.season || "2025";
    $("#replay-date").min = init.fixture.week_start || "";
    $("#replay-date").max = init.fixture.week_end || "";
    $("#replay-date").value = init.fixture.default_date || "";
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
