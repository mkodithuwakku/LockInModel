"""Local dashboard. Bind to loopback only; mutations require same-origin JSON."""

import datetime as dt
import secrets
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from flask import Flask, request, jsonify, send_from_directory, session
from dotenv import load_dotenv
from storage import ROOT, load_cfg, save_cfg, LOCK, read_json, write_json

load_dotenv(ROOT / ".env")
from engine import build_dashboard, today
from transport import DataUnavailable

app = Flask(__name__, static_folder=str(ROOT / "web"), static_url_path="/assets")
app.config.update(
    SECRET_KEY=secrets.token_hex(32),
    MAX_CONTENT_LENGTH=128 * 1024,
    TRUSTED_HOSTS=["localhost", "127.0.0.1"],
    SESSION_COOKIE_SAMESITE="Strict",
    SESSION_COOKIE_HTTPONLY=True,
)
pool = ThreadPoolExecutor(max_workers=1)
jobs = {}
job_lock = threading.Lock()
dashboard_cache = {}


@app.before_request
def local_only():
    if request.headers.get("Sec-Fetch-Site") == "cross-site":
        return jsonify(error="Cross-site requests are not allowed."), 403
    if request.method == "POST":
        if request.is_json and not isinstance(request.get_json(), dict):
            return jsonify(error="Expected a JSON object."), 400
        if (
            not request.is_json
            or not session.get("csrf")
            or request.headers.get("X-CSRF-Token") != session.get("csrf")
        ):
            return jsonify(error="Reload the dashboard before making changes."), 403


@app.after_request
def headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Frame-Options"] = "DENY"
    if request.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.errorhandler(ValueError)
def invalid(exc):
    return jsonify(error=str(exc)), 400


@app.errorhandler(DataUnavailable)
def unavailable(exc):
    return jsonify(error=str(exc)), 503


@app.route("/")
def index():
    return send_from_directory(ROOT / "web", "index.html")


@app.route("/api/bootstrap")
def bootstrap():
    session["csrf"] = session.get("csrf") or secrets.token_hex(24)
    from nba_api.stats.static import players

    return jsonify(
        csrf=session["csrf"],
        players=[
            {"name": p["full_name"], "id": str(p["id"])} for p in players.get_players()
        ],
        sleeper=load_cfg().get("sleeper", {}),
        fixture=read_json(ROOT / "data/fixtures/2025-26/manifest.json", {}),
    )


@app.route("/api/portrait/<int:pid>")
def portrait(pid):
    path = ROOT / "data/cache/portraits" / f"{pid}.png"
    if not path.exists():
        from flask import Response

        return Response(
            '<svg xmlns="http://www.w3.org/2000/svg" width="260" height="190" viewBox="0 0 260 190"><circle cx="130" cy="65" r="35" fill="#60708c"/><path d="M55 190v-25c0-72 150-72 150 0v25" fill="#60708c"/></svg>',
            mimetype="image/svg+xml",
        )
    return send_from_directory(path.parent, path.name, max_age=86400)


@app.route("/api/dashboard")
def dashboard():
    mode = request.args.get("mode", "replay")
    reference = request.args.get("date") or None
    if mode not in ["replay", "live"]:
        raise ValueError("Unknown data mode.")
    if mode == "live":
        cached = read_json(ROOT / "state/live-dashboard.json")
        if not cached:
            raise DataUnavailable(
                "No live report saved yet. Use Refresh live data to fetch once."
            )
        age = (
            dt.datetime.now(dt.timezone.utc)
            - dt.datetime.fromisoformat(cached["generated_at"])
        ).total_seconds()
        if cached["date"] != str(today()) or age > 21600:
            cached["alerts"].insert(
                0,
                {
                    "severity": "warning",
                    "message": "Live report is stale. Refresh before making decisions.",
                },
            )
            for team in cached["teams"]:
                for row in team["results"]:
                    row.update(
                        status="STALE",
                        decision=None,
                        p_lock=None,
                        p_wait=None,
                        note="Refresh required; this result is stale.",
                    )
        return jsonify(cached)
    from storage import CONFIG

    key = (reference, CONFIG.stat().st_mtime_ns if CONFIG.exists() else 0)
    if key not in dashboard_cache:
        value = build_dashboard("replay", reference)
        dashboard_cache.clear()
        dashboard_cache[key] = value
    return jsonify(dashboard_cache[key])


def submit(work):
    with job_lock:
        if any(j["status"] == "running" for j in jobs.values()):
            raise ValueError("Another refresh is already running.")
        ident = uuid.uuid4().hex
        jobs[ident] = {
            "status": "running",
            "message": "Working from saved responses where possible…",
        }

    def execute():
        try:
            value = work()
            jobs[ident] = {"status": "complete", "result": value}
        except Exception as exc:
            app.logger.exception("Background operation failed")
            jobs[ident] = {"status": "failed", "error": str(exc)}

    pool.submit(execute)
    return jsonify(job_id=ident), 202


@app.route("/api/jobs/<ident>")
def job(ident):
    return jsonify(
        jobs.get(
            ident,
            {"status": "failed", "error": "Operation not found; reload the dashboard."},
        )
    )


@app.route("/api/sync", methods=["POST"])
def sync():
    from sleeper import sync as sync_sleeper

    body = request.get_json()

    def work():
        result = sync_sleeper(body.get("username", ""), str(body.get("season", "2025")))
        dashboard_cache.clear()
        return result

    return submit(work)


@app.route("/api/refresh", methods=["POST"])
def refresh():
    def work():
        try:
            result = build_dashboard("live")
            write_json(ROOT / "state/live-dashboard.json", result)
            return {
                "message": "Live report refreshed. Review any data alerts before acting."
            }
        except Exception as exc:
            # Preserve last successful report; surface the failed refresh separately.
            write_json(
                ROOT / "state/last-error.json",
                {
                    "message": str(exc),
                    "at": dt.datetime.now(dt.timezone.utc).isoformat(),
                },
            )
            raise

    return submit(work)


@app.route("/api/roster", methods=["POST"])
def roster():
    body = request.get_json()
    with LOCK:
        cfg = load_cfg()
        team = next((t for t in cfg["teams"] if t["id"] == body.get("team_id")), None)
        if not team:
            raise ValueError("Team not found.")
        if team.get("source") == "sleeper":
            raise ValueError(
                "Sleeper manages this roster. Sync after making changes in Sleeper."
            )
        action = body.get("action")
        name = body.get("player", "")
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Select a player.")
        name = name.strip()
        if action == "add":
            from fetch_data import resolve_player_ids

            resolve_player_ids([name])
            if len(team["players"]) >= 40:
                raise ValueError("A local roster can contain at most 40 players.")
            if name not in team["players"]:
                team["players"].append(name)
        elif action == "remove":
            team["players"] = [n for n in team["players"] if n != name]
            team["starters"] = [n for n in team["starters"] if n != name]
        elif action == "toggle":
            if name not in team["players"]:
                raise ValueError("Player is not on this roster.")
            if name in team["starters"]:
                team["starters"].remove(name)
            else:
                team["starters"].append(name)
        else:
            raise ValueError("Unknown roster action.")
        save_cfg(cfg)
        dashboard_cache.clear()
    return jsonify(message="Roster saved. Reports use this same selection.")


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8765, threaded=True, debug=False)
