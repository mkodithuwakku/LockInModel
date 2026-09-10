"""CLI reporting. Replay is the default; email delivery is explicit."""

import argparse
import datetime as dt
import fcntl
import hashlib
import os
from dotenv import load_dotenv
from storage import ROOT, load_cfg, write_json, read_json

load_dotenv(ROOT / ".env")
from engine import build_dashboard, today
from notify import send_email


def compose_report_grouped(teams_results, alerts=None, date=None, mode="live"):
    lines = [f"LockIn — {date or today()} ({mode})", ""]
    if alerts:
        lines += ["DATA ALERTS — REVIEW BEFORE ACTING"]
        lines += [f"- {a.get('team','Data service')}: {a['message']}" for a in alerts]
        lines.append("")
    for team in teams_results:
        lines += [
            team["team_name"]
            + (" — " + team["league_name"] if team.get("league_name") else ""),
            "",
        ]
        for row in team["results"]:
            if row.get("starter") is False:
                continue
            if not row.get("decision"):
                lines.append(
                    f"- {row['player']}: {row.get('status','REVIEW')} — {row.get('note','No recommendation available.')}"
                )
                continue
            lines.append(
                f"- {row['player']}: {row['decision']} | {row['last_game_fp']:.1f} FP on {row['last_game_date']} | {row['remaining_games_est']} games remain | lock score {row['p_lock']:.0%}"
            )
            lines.append("  " + row.get("reason", ""))
            lines += ["  Caution: " + w for w in row.get("warnings", [])]
        candidates = [
            p
            for p in team.get("pickups", [])
            if p.get("scoring_complete")
            and team.get("ownership_complete")
            and (p.get("team_gain") or 0) > 0
        ]
        if candidates:
            lines += ["", "ON THE RISE — investigate before adding"]
            for p in candidates[:3]:
                lines.append(
                    f"- {p['player']}: {p['recent_fp']:.1f} recent FP vs {p['baseline_fp']:.1f} baseline; minutes {p['baseline_minutes']:.1f} → {p['minutes']:.1f}. {p['availability']}. Potential replacement: {p['replacement']}."
                )
        lines.append("")
    lines += [
        "Lock scores are heuristic preferences, not calibrated probabilities.",
        "Lock eligible games in Sleeper before the player’s next game begins.",
    ]
    return "\n".join(lines) + "\n"


def send_daily(subject, body, cfg, force=False):
    """At-most-one automatic attempt per day, including ambiguous SMTP failures."""
    directory = ROOT / "state"
    directory.mkdir(exist_ok=True)
    with open(directory / "email.lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        path = directory / "email-delivery.json"
        ledger = read_json(path, {})
        key = str(today())
        if key in ledger and not force:
            return "Already attempted today; no duplicate email sent."
        sender = cfg.get("notify", {}).get("from_email") or os.getenv("EMAIL_USER")
        recipient = cfg.get("notify", {}).get("to_email") or os.getenv("EMAIL_USER")
        if not sender or not recipient or not os.getenv("EMAIL_APP_PASSWORD"):
            raise ValueError(
                "Email settings incomplete. Configure sender, recipient and app password locally."
            )
        review = read_json(ROOT / "state/credential-review.json", {})
        if (
            review.get("blocked_password_sha256")
            == hashlib.sha256(os.environ["EMAIL_APP_PASSWORD"].encode()).hexdigest()
        ):
            raise ValueError(
                "The configured email app password was publicly committed. Revoke it and replace EMAIL_APP_PASSWORD before enabling delivery."
            )
        ledger[key] = {
            "status": "sending",
            "body_sha256": hashlib.sha256(body.encode()).hexdigest(),
        }
        write_json(path, ledger)
        try:
            send_email(subject, body, recipient, sender)
        except Exception:
            ledger[key]["status"] = "delivery_uncertain"
            write_json(path, ledger)
            raise RuntimeError(
                "Email delivery failed or is uncertain. Automatic retry suppressed to avoid duplicates."
            )
        ledger[key]["status"] = "sent"
        write_json(path, ledger)
        return "Email delivered."


def new_pickup_alerts(report, ledger, now):
    """Only alert again after 72 hours or a material signal improvement."""
    import copy

    selected = copy.deepcopy(report)
    updates = {}
    for team in selected["teams"]:
        candidates = []
        for p in team.get("pickups", []):
            if (
                not team.get("ownership_complete")
                or not p.get("scoring_complete")
                or (p.get("team_gain") or 0) <= 0
            ):
                continue
            key = team["id"] + ":" + p["player_id"]
            old = ledger.get(key, {})
            if (
                not old
                or now - old["at"] >= 72 * 3600
                or p["signal_score"] >= old["score"] + 10
                or p["projected_fp"] >= old["projection"] + 3
            ):
                candidates.append(p)
                if len(candidates) >= 3:
                    break
        team["pickups"] = candidates
        for p in candidates:
            updates[team["id"] + ":" + p["player_id"]] = {
                "at": now,
                "score": p["signal_score"],
                "projection": p["projected_fp"],
            }
    return selected, updates


def run(live=False, reference=None, send=False, daily=False):
    cfg = load_cfg()
    mode = "live" if live else "replay"
    if send and not live:
        raise ValueError("Historical replay cannot send email.")
    if daily and read_json(ROOT / "state/email-delivery.json", {}).get(str(today())):
        return "Already attempted today; no API calls or email repeated."
    alerts = []
    if live and cfg.get("sleeper"):
        from sleeper import sync_current

        try:
            sync_current()
            cfg = load_cfg()
        except Exception as exc:
            alerts.append(
                {
                    "severity": "error",
                    "message": "Sleeper refresh failed; saved rosters may be stale. "
                    + str(exc),
                }
            )
        synced = [
            t
            for t in cfg["teams"]
            if t.get("source") == "sleeper" and not t.get("archived")
        ]
        if synced:
            cfg["teams"] = synced
        if (
            synced
            and all(
                t.get("league_status") in {"complete", "pre_draft", "drafting"}
                for t in synced
            )
            and not alerts
        ):
            return "No connected leagues are in season. No NBA requests or offseason email sent."
    try:
        report = build_dashboard(mode, reference, cfg=cfg)
        report["alerts"] = alerts + report["alerts"]
    except Exception as exc:
        if not live:
            raise
        report = {
            "teams": [],
            "alerts": alerts
            + [
                {
                    "severity": "error",
                    "message": "Analysis unavailable: "
                    + str(exc)
                    + ". No lock recommendations issued.",
                }
            ],
            "mode": "live",
            "date": str(today()),
            "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        }
    import time

    ledger = read_json(ROOT / "state/pickup-alerts.json", {})
    email_report, updates = new_pickup_alerts(report, ledger, time.time())
    body = compose_report_grouped(
        email_report["teams"], report["alerts"], report["date"], mode
    )
    write_json(ROOT / "state" / f"{mode}-report.json", report)
    if live:
        write_json(ROOT / "state/live-dashboard.json", report)
    (ROOT / "state" / f"{mode}-report.txt").write_text(body)
    print(body)
    if send:
        result = send_daily("LockIn daily report — " + str(today()), body, cfg)
        if result == "Email delivered.":
            ledger.update(updates)
            write_json(ROOT / "state/pickup-alerts.json", ledger)
        return result
    return "Report saved locally. No email sent."


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--live", action="store_true", help="Fetch live data explicitly")
    p.add_argument("--date", help="Historical replay date within the captured week")
    p.add_argument(
        "--send",
        action="store_true",
        help="Send today’s live report and data alerts by email",
    )
    p.add_argument(
        "--daily",
        action="store_true",
        help="Skip repeated daily work and duplicate email",
    )
    args = p.parse_args()
    print(run(args.live, args.date, args.send, args.daily))
