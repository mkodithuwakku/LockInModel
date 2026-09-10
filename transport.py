"""Paced, persistent JSON cache with host-wide failure cooldowns.

Cache-only reads never create a socket. Cross-process locking serializes requests.
"""

import hashlib
import json
import time
import threading
import fcntl
from pathlib import Path
from urllib.parse import urlparse
from email.utils import parsedate_to_datetime
import requests
from storage import ROOT, read_json, write_json


class DataUnavailable(RuntimeError):
    pass


class CachedHTTP:
    def __init__(
        self, directory=None, session=None, clock=time.time, sleeper=time.sleep
    ):
        self.directory = Path(directory or ROOT / "data/cache/http")
        self.directory.mkdir(parents=True, exist_ok=True)
        self.session = session or requests.Session()
        self.clock, self.sleep = clock, sleeper
        self.lock = threading.RLock()

    def get(self, url, params=None, ttl=3600, offline=False, pace=2, timeout=20):
        key = hashlib.sha256(
            json.dumps([url, params or {}], sort_keys=True).encode()
        ).hexdigest()
        path = self.directory / (key + ".json")
        with self.lock, open(self.directory / ".request.lock", "a") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                cached = read_json(path)
                if cached and self.clock() - cached["fetched_at"] < ttl:
                    return cached["data"]
                if offline:
                    raise DataUnavailable(
                        "No fresh saved response. Refresh explicitly when online."
                    )
                host = urlparse(url).netloc
                gate_path = self.directory / "cooldowns.json"
                gates = read_json(gate_path, {})
                gate = gates.get(host, {})
                now = self.clock()
                if gate.get("until", 0) > now:
                    raise DataUnavailable(
                        f'{host} is cooling down. Retry in {int(gate["until"]-now)+1} seconds; saved results remain available.'
                    )
                self.sleep(max(0, pace - (now - gate.get("last", 0))))
                headers = (
                    {
                        "User-Agent": "Mozilla/5.0",
                        "Accept": "application/json",
                        "Referer": "https://www.nba.com/",
                    }
                    if host.endswith("nba.com")
                    else {}
                )
                try:
                    response = self.session.get(
                        url, params=params, headers=headers, timeout=(5, timeout)
                    )
                    if response.status_code == 429:
                        retry = response.headers.get("Retry-After", "900")
                        try:
                            delay = max(60, float(retry))
                        except ValueError:
                            try:
                                delay = max(
                                    60,
                                    parsedate_to_datetime(retry).timestamp()
                                    - self.clock(),
                                )
                            except (ValueError, TypeError):
                                delay = 900
                        gates[host] = {
                            "last": self.clock(),
                            "until": self.clock() + delay,
                        }
                        write_json(gate_path, gates)
                        raise DataUnavailable(
                            f"{host} rate limited requests. Capture paused; retry after the cooldown."
                        )
                    response.raise_for_status()
                    data = response.json()
                    if not isinstance(data, (dict, list)):
                        raise ValueError("Unexpected JSON response")
                except DataUnavailable:
                    raise
                except (requests.RequestException, ValueError) as exc:
                    gates[host] = {"last": self.clock(), "until": self.clock() + 300}
                    write_json(gate_path, gates)
                    raise DataUnavailable(
                        f"{host} request failed ({type(exc).__name__}). Requests paused for 5 minutes."
                    ) from exc
                gates[host] = {"last": self.clock(), "until": 0}
                write_json(gate_path, gates)
                write_json(path, {"fetched_at": self.clock(), "data": data})
                return data
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)


HTTP = CachedHTTP()
