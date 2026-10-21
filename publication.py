"""Publish local analysis as static files; no database or credentials leave the Mac."""

import argparse
import datetime as dt
import fcntl
import os
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit
import uuid
from zoneinfo import ZoneInfo

import requests

from pages import export_site, refresh_report
from storage import ROOT, load_cfg, read_json, write_json

LABEL = "com.lockin.publish"
LEDGER = ROOT / "state/publication.json"
UTC = dt.timezone.utc


def settings(cfg):
    config = {
        "remote": "origin",
        "branch": "gh-pages",
        "hour": 12,
        "minute": 17,
        "timezone": "America/Edmonton",
        **cfg.get("publication", {}),
    }
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", config["remote"]):
        raise ValueError("Publication remote must be a Git remote name.")
    if (
        not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]*", config["branch"])
        or ".." in config["branch"]
    ):
        raise ValueError("Invalid publication branch.")
    if config["branch"] in {"main", "master"}:
        raise ValueError("Use a dedicated publication branch, not the source branch.")
    for key, maximum in (("hour", 23), ("minute", 59)):
        if type(config[key]) is not int or not 0 <= config[key] <= maximum:
            raise ValueError("Invalid publication " + key)
    ZoneInfo(config["timezone"])
    return config


def due_slot(now, config):
    """Latest scheduled date, including a missed run before today's scheduled time."""
    local = now.astimezone(ZoneInfo(config["timezone"]))
    scheduled = local.replace(
        hour=config["hour"], minute=config["minute"], second=0, microsecond=0
    )
    return str(
        (local.date() if local >= scheduled else local.date() - dt.timedelta(days=1))
    )


def git(*args, cwd=ROOT, check=True):
    result = subprocess.run(
        ["/usr/bin/git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=120,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "Never"},
    )
    if check and result.returncode:
        # Never log credential-helper output or a URL that may contain a token.
        raise RuntimeError(
            "Git "
            + args[0]
            + " failed. Check repository access and local Git credentials."
        )
    return result


def repository(config):
    remote = git("remote", "get-url", config["remote"]).stdout.strip()
    match = re.fullmatch(
        r"(?:https://github.com/|git@github.com:)([\w.-]+/[\w.-]+?)(?:\.git)?", remote
    )
    if not match:
        raise ValueError(
            "Publication requires a GitHub origin URL without embedded credentials."
        )
    repo = match[1]
    owner, name = repo.split("/")
    default = f"https://{owner}.github.io/" + (
        "" if name.lower() == f"{owner}.github.io".lower() else name + "/"
    )
    url = config.get("url", default).rstrip("/") + "/"
    if (
        urlsplit(url).scheme != "https"
        or urlsplit(url).username
        or urlsplit(url).password
    ):
        raise ValueError("Publication URL must be HTTPS without credentials.")
    return remote, repo, url


def github_session():
    """Use the existing OS Git credential helper without writing or printing secrets."""
    result = subprocess.run(
        ["/usr/bin/git", "credential", "fill"],
        cwd=ROOT,
        input="protocol=https\nhost=github.com\n\n",
        text=True,
        capture_output=True,
        timeout=30,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "Never"},
    )
    fields = dict(
        line.split("=", 1) for line in result.stdout.splitlines() if "=" in line
    )
    if result.returncode or not fields.get("password"):
        raise RuntimeError(
            "GitHub API credentials unavailable. Authenticate Git with the macOS keychain first."
        )
    session = requests.Session()
    session.headers.update(
        {
            "Authorization": "Bearer " + fields["password"],
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
    )
    return session


def configure_pages(config):
    """Explicit one-time switch to branch publication, after the branch exists."""
    _, repo, url = repository(config)
    with github_session() as session:
        response = session.put(
            f"https://api.github.com/repos/{repo}/pages",
            json={
                "build_type": "legacy",
                "source": {"branch": config["branch"], "path": "/"},
            },
            timeout=30,
        )
        if response.status_code != 204:
            raise RuntimeError(
                f"Pages configuration failed (HTTP {response.status_code}). Check repository administration access."
            )
    return url


def publish_report(report, config):
    remote, _, _ = repository(config)
    # A fresh staging repository has no path to local configuration or the database.
    # Preserve publication history and use a normal fast-forward push; never force.
    with tempfile.TemporaryDirectory(prefix="lockin-publish-") as directory:
        directory = Path(directory)
        git("init", "-b", config["branch"], cwd=directory)
        git("remote", "add", "origin", remote, cwd=directory)
        exists = git(
            "ls-remote",
            "--exit-code",
            "origin",
            "refs/heads/" + config["branch"],
            cwd=directory,
            check=False,
        )
        if exists.returncode == 0:
            git(
                "fetch",
                "--depth=1",
                "origin",
                "refs/heads/" + config["branch"],
                cwd=directory,
            )
            git("reset", "--mixed", "FETCH_HEAD", cwd=directory)
        elif exists.returncode != 2:
            raise RuntimeError("Could not inspect the publication branch.")
        site = directory / "site"
        export_site(report, site)
        for path in site.iterdir():
            shutil.move(str(path), directory / path.name)
        site.rmdir()
        git("add", "--all", cwd=directory)
        git(
            "-c",
            "user.name=LockIn publisher",
            "-c",
            "user.email=lockin-publisher@users.noreply.github.com",
            "commit",
            "-m",
            "Publish local report " + report["generated_at"],
            cwd=directory,
        )
        commit = git("rev-parse", "HEAD", cwd=directory).stdout.strip()
        git("push", "origin", "HEAD:refs/heads/" + config["branch"], cwd=directory)
        return commit


def visible(url, publication_id):
    try:
        response = requests.get(
            url + "report.json",
            params={"publication": publication_id, "check": time.time_ns()},
            headers={"Cache-Control": "no-cache"},
            timeout=(5, 15),
        )
        return (
            response.status_code == 200
            and response.json().get("publication_id") == publication_id
        )
    except (requests.RequestException, ValueError, AttributeError):
        return False


def await_visible(url, publication_id, seconds=120):
    deadline = time.monotonic() + seconds
    while True:
        if visible(url, publication_id):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(min(5, max(0, deadline - time.monotonic())))


def run(force=False, setup=False, now=None):
    now = now or dt.datetime.now(UTC)
    config = settings(load_cfg())
    slot = due_slot(now, config)
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with open(LEDGER.with_suffix(".lock"), "a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return "Publication already running."
        state = read_json(LEDGER, {})
        if not force and state.get("successful_slot", "") >= slot:
            return "Daily publication already completed."
        if (
            not force
            and state.get("retry_after")
            and now < dt.datetime.fromisoformat(state["retry_after"])
        ):
            return "Waiting for publication retry window."
        try:
            _, _, url = repository(config)
            pending = state.get("pending") or {}
            if (
                not force
                and pending.get("slot") == slot
                and visible(url, pending["id"])
            ):
                state.update(
                    published_at=now.isoformat(), published_commit=pending["commit"]
                )
                if pending["refresh_status"] == "ok":
                    state.update(
                        successful_slot=slot,
                        failures=0,
                        retry_after=None,
                        error=None,
                        pending=None,
                    )
                    write_json(LEDGER, state)
                    return "Previously uploaded report is now live."
            # Ensure the permanent store exists even before opening night.
            from game_store import GameStore

            GameStore()
            report = refresh_report()
            report["publication_id"] = uuid.uuid4().hex
            report["published_at"] = now.isoformat()
            commit = publish_report(report, config)
            state["pending"] = {
                "id": report["publication_id"],
                "slot": slot,
                "commit": commit,
                "refresh_status": report["refresh_status"],
            }
            write_json(LEDGER, state)
            if setup:
                configure_pages(config)
            if not await_visible(url, report["publication_id"]):
                raise RuntimeError(
                    "Report uploaded, but Pages publication is not confirmed yet. The next scheduled check will verify it."
                )
            state.update(
                published_at=now.isoformat(), published_commit=commit, pending=None
            )
            if report["refresh_status"] != "ok":
                raise RuntimeError(
                    "Published a report with data alerts. A later scheduled run will retry the failed refresh."
                )
            state.update(successful_slot=slot, failures=0, retry_after=None, error=None)
            write_json(LEDGER, state)
            return "Daily report published and verified: " + url
        except Exception as exc:
            failures = state.get("failures", 0) + 1
            state.update(
                failures=failures,
                error=str(exc),
                attempted_at=now.isoformat(),
                retry_after=(
                    now + dt.timedelta(minutes=min(15 * 2 ** min(failures - 1, 5), 360))
                ).isoformat(),
            )
            write_json(LEDGER, state)
            raise


def launch_agent(root, python, home):
    return {
        "Label": LABEL,
        "ProgramArguments": [str(python), str(root / "publication.py"), "run"],
        "WorkingDirectory": str(root),
        "RunAtLoad": True,
        # Calendar events missed during sleep coalesce into a run after wake.
        # Check every 15 minutes; run() performs work only when due or retrying.
        "StartCalendarInterval": [{"Minute": minute} for minute in (2, 17, 32, 47)],
        "ProcessType": "Background",
        "StandardOutPath": str(root / "logs/publication.log"),
        "StandardErrorPath": str(root / "logs/publication-error.log"),
        "EnvironmentVariables": {
            "PATH": "/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin:/opt/homebrew/bin",
            "HOME": str(home),
            "PYTHONUNBUFFERED": "1",
            "GIT_TERMINAL_PROMPT": "0",
        },
    }


def install():
    if sys.platform != "darwin":
        raise ValueError("Automatic wake catch-up installation requires macOS.")
    root, home = ROOT.resolve(), Path.home()
    # Keep the venv executable path, not its resolved system-interpreter symlink.
    python = Path(sys.executable).absolute()
    (root / "logs").mkdir(exist_ok=True)
    target = home / "Library/LaunchAgents" / (LABEL + ".plist")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(plistlib.dumps(launch_agent(root, python, home)))
    target.chmod(0o600)
    domain = "gui/" + str(os.getuid())
    subprocess.run(["launchctl", "bootout", domain + "/" + LABEL], capture_output=True)
    subprocess.run(
        ["launchctl", "bootstrap", domain, str(target)], check=True, capture_output=True
    )
    return "Installed daily publication and wake catch-up: " + str(target)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["run", "install", "status"])
    parser.add_argument(
        "--force",
        action="store_true",
        help="Refresh and publish even if today's slot succeeded",
    )
    parser.add_argument(
        "--setup-pages",
        action="store_true",
        help="Switch GitHub Pages to the publication branch after upload",
    )
    args = parser.parse_args()
    try:
        if args.command == "install":
            message = install()
        elif args.command == "status":
            import json

            message = json.dumps(read_json(LEDGER, {}), indent=2)
        else:
            message = run(args.force, args.setup_pages)
        print(dt.datetime.now(UTC).isoformat(), message, flush=True)
    except Exception as exc:
        print(dt.datetime.now(UTC).isoformat(), str(exc), file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
