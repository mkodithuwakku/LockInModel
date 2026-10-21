"""Publish an allowlisted, read-only report. Never copy local configuration."""

import argparse
import copy
import datetime as dt
import hashlib
import json
from pathlib import Path
import shutil
import sys

from engine import build_dashboard, roster_dashboard, today
from storage import ROOT, load_cfg, read_json, write_json

REPORT_FIELDS = "mode date observation_cutoff generated_at notice refresh_status schedule_week season_start publication_id".split()
TEAM_FIELDS = (
    "id team_name league_name source season league_status archived synced_at "
    "ownership_complete unsupported_scoring ignored_scoring scoring_notes"
).split()
PLAYER_FIELDS = (
    "player player_id status decision note reason starter positions nba_team week "
    "last_game_date last_game_fp remaining_games_est fp_mean_recent fp_std_recent "
    "sample_size p_lock p_wait warnings roster_slot lineup_order injury_status schedule_state"
).split()
HISTORY_FIELDS = "date fp minutes pts reb ast stl blk tov".split()
PICKUP_FIELDS = (
    "player player_id nba_team positions last_played recent_fp baseline_fp lift lift_z "
    "minutes baseline_minutes consistency projected_fp signal_score games_recent "
    "games_baseline risks replacement team_gain availability ownership_as_of scoring_complete"
).split()
SAVED = ROOT / "state/pages-report.json"


def select(value, fields):
    return {key: copy.deepcopy(value[key]) for key in fields if key in value}


def public_report(report):
    """Explicit boundary: new internal fields are private unless allowlisted here."""
    out = select(report, REPORT_FIELDS)
    out.update(
        schema_version=1, mode="live", sleeper={}, dataset={}, teams=[], alerts=[]
    )
    for team in report.get("teams", []):
        if team.get("archived"):
            continue
        item = select(team, TEAM_FIELDS)
        item["results"] = []
        for player in team.get("results", []):
            row = select(player, PLAYER_FIELDS)
            row["week_games"] = [
                select(g, ["date", "opponent", "home", "status", "fp"])
                for g in player.get("week_games", [])
            ]
            row["history"] = [
                select(h, HISTORY_FIELDS) for h in player.get("history", [])[-25:]
            ]
            item["results"].append(row)
        item["pickups"] = [select(p, PICKUP_FIELDS) for p in team.get("pickups", [])]
        out["teams"].append(item)
    out["alerts"] = [
        select(alert, ["severity", "team", "message"])
        for alert in report.get("alerts", [])
    ]
    # Fail before deployment on NaN/Infinity or unexpected non-JSON values.
    json.dumps(out, allow_nan=False)
    return out


def unavailable(report, message):
    report = copy.deepcopy(report)
    report["refresh_status"] = "failed"
    report.setdefault("alerts", []).insert(0, {"severity": "error", "message": message})
    for team in report.get("teams", []):
        team["pickups"] = []
        for row in team["results"]:
            row.update(
                status="DATA_UNAVAILABLE",
                decision=None,
                p_lock=None,
                p_wait=None,
                note=message,
            )
    return report


def refresh_report():
    from sleeper import sync_current

    cfg = load_cfg()
    if not cfg.get("sleeper", {}).get("username"):
        raise ValueError(
            "Connect a Sleeper account locally before publishing live teams."
        )
    try:
        sync_current()
        report = build_dashboard("live")
        report["refresh_status"] = (
            "partial"
            if any(a.get("severity") == "error" for a in report["alerts"])
            else "ok"
        )
    except Exception as exc:
        # A failed provider must still publish a visible failure, without internal paths.
        print(
            f"Refresh failed ({type(exc).__name__}); publishing unavailable status.",
            file=sys.stderr,
        )
        cfg = load_cfg()
        report = roster_dashboard(cfg)
        if not report["teams"]:
            report = read_json(SAVED) or report
        report = unavailable(
            report,
            "Scheduled refresh failed. Saved rosters may be out of date; lock and pickup recommendations are withheld. The next scheduled run will try again.",
        )
    if not report.get("season_start") or report["date"] >= report["season_start"]:
        report["notice"] = (
            "Daily snapshot from your Mac, with catch-up after wake. Reload checks the published report; manage locks in Sleeper."
        )
    write_json(ROOT / "state/live-dashboard.json", report)
    report["published_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    result = public_report(report)
    result["published_at"] = report["published_at"]
    write_json(SAVED, result)
    return result


def export_site(report, destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    # Refuse reused nonempty directories so old or unrelated files cannot leak.
    if any(destination.iterdir()):
        raise ValueError("Export destination must be empty.")
    report = public_report(report) | {
        "published_at": report.get("published_at", report["generated_at"])
    }
    report["portraits"] = []
    portraits = destination / "portraits"
    portraits.mkdir()
    ids = {
        str(p.get("player_id", ""))
        for t in report["teams"]
        for p in t["results"] + t["pickups"]
    }
    for pid in sorted(ids):
        if not pid.isdigit():
            continue
        path = ROOT / "data/cache/portraits" / f"{pid}.png"
        if path.is_file() and not path.is_symlink():
            shutil.copyfile(path, portraits / path.name)
            report["portraits"].append(pid)
    html = (ROOT / "web/index.html").read_text()
    html = html.replace('href="/assets/', 'href="./').replace(
        'src="/assets/', 'src="./'
    )
    html = html.replace('href="/"', 'href="./"')
    html = html.replace('<html lang="en">', '<html lang="en" data-hosting="pages">')
    html = html.replace(
        '<script src="./app.js" defer></script>',
        '<script src="./pages.js" defer></script>\n    <script src="./app.js" defer></script>',
    )
    # Pages/browser caches can otherwise pair new HTML with an old app script.
    assets = ("app.js", "pages.js", "insights.js", "style.css", "icon.svg")
    for name in assets:
        version = hashlib.sha256((ROOT / "web" / name).read_bytes()).hexdigest()[:16]
        html = html.replace(f'./{name}"', f'./{name}?v={version}"')
    (destination / "index.html").write_text(html)
    for name in assets:
        shutil.copyfile(ROOT / "web" / name, destination / name)
    (destination / ".nojekyll").touch()
    write_json(destination / "report.json", report)
    print(
        f"Exported {len(report['teams'])} teams; refresh status: {report.get('refresh_status', 'saved')}."
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Sync Sleeper and use paced live providers",
    )
    parser.add_argument("--output", default="dist/pages")
    args = parser.parse_args()
    if args.refresh:
        report = refresh_report()
    else:
        # Local export only: same saved-data policy as the local dashboard, no requests.
        from app import app

        with app.test_client() as client:
            response = client.get("/api/dashboard?mode=live")
            if response.status_code != 200:
                raise ValueError("Saved dashboard could not be loaded.")
            report = response.get_json()
        report["notice"] = (
            "Saved report preview. The Mac publishes daily around 12:17 PM America/Edmonton, with catch-up after wake."
        )
    export_site(report, ROOT / args.output)


if __name__ == "__main__":
    main()
