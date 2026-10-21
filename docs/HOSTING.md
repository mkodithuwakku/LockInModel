# Hosted daily dashboard

[Open LockIn](https://mkodithuwakku.github.io/LockInModel/).

The Mac owns the game database and generates the daily report. GitHub Pages serves a public, read-only export from the `gh-pages` branch. There is no website database, remote model execution, or scheduled cloud data fetch. Once published, the site remains available with the Mac off; new reports require the Mac to be awake, logged in, and online.

## Daily flow

1. The local scheduler checks whether the 12:17 PM America/Edmonton publication is due.
2. `publication.py` refreshes Sleeper rosters and the shared analysis engine. Current league scoring is imported each time.
3. `data/lockin.sqlite3` retains player-game history across refreshes. Daily downloads overlap the last saved game by seven days, and a weekly full-season download reconciles older corrections. Season/game/player keys prevent duplicate observations. Failed refreshes retain saved data.
4. `pages.py` exports an explicit allowlist of report fields, HTML, JavaScript, CSS, icons, and available portraits. Private configuration, raw caches, database files, and credentials are excluded.
5. A fresh temporary staging repository commits only those files and pushes to `gh-pages`. Normal fast-forward pushes preserve publication history; no force push is used.
6. GitHub Pages builds the static branch. The publisher checks the live `report.json` for the new publication ID before recording a successful daily run.

The former `.github/workflows/pages.yml` cloud refresh has been removed. The remaining test workflow runs on source changes, not daily report pushes. The separate noon email automation is unchanged; publication sends no email and submits no Sleeper actions.

## Wake catch-up and retries

`publication.py install` installs a macOS LaunchAgent named `com.lockin.publish`. It checks at minutes 02, 17, 32, and 47, plus login. Calendar events missed during sleep are coalesced by macOS into a run after wake. The Python command computes the latest scheduled daily slot, so waking after several days produces one current report instead of replaying each missed day. Codex and Flask do not need to remain open.

A filesystem lock prevents overlapping publisher processes. `state/publication.json` records the successful slot, pending upload, published commit, and retry status. After success, further checks exit without network work. Failures retry after 15, 30, 60, 120, 240, then at most 360 minutes. The next check can confirm an already-uploaded report without repeating a successful data refresh. A partial/error report can be published to show the failure, but it does not mark the daily slot successful.

No update deadline is guaranteed: macOS must run the job, Git credentials must remain usable, providers must respond, and GitHub Pages must deploy. Catch-up cannot recover a missed fantasy decision deadline. Logging out or powering off prevents execution until the user logs in again.

## Setup

Connect the desired Sleeper account in the local dashboard first. The publisher reads `config.local.yaml`; it never replaces that file with temporary cloud defaults. Git must already authenticate to the GitHub repository through the OS credential helper.

```bash
.venv/bin/python publication.py run --force --setup-pages
.venv/bin/python publication.py install
.venv/bin/python publication.py status
```

The first command uploads an export and switches Pages to branch publication at `gh-pages` `/`. This requires repository administration access for the one-time Pages setting. Routine runs require push access only. The credential helper's output stays in memory and is never printed or saved in the report.

Defaults can be overridden under `publication` in local YAML: remote, branch, hour, minute, timezone, and optional HTTPS public URL. The source branches `main` and `master` are rejected as publication destinations. See [Configuration](CONFIGURATION.md). After moving the repository or changing its virtual environment, rerun installation so absolute paths remain valid.

## Operations and recovery

```bash
# Run a fresh report now; retains provider cooldowns and same-day database reuse.
.venv/bin/python publication.py run --force

# Inspect the most recent success, pending upload, or retry reason.
.venv/bin/python publication.py status

# Inspect the registered macOS agent.
launchctl print gui/$(id -u)/com.lockin.publish
```

Logs live at `logs/publication.log` and `logs/publication-error.log`. If the report uploaded but deployment was not confirmed, check the site's Pages build and public report timestamp; the agent will verify again after the retry interval. For network/API failures, wait for retries rather than repeatedly forcing requests. For changed Git credentials, restore access through the local credential helper. Never put tokens in YAML, remote URLs, or website files.

To uninstall the scheduler, run `launchctl bootout gui/$(id -u)/com.lockin.publish` and remove only `~/Library/LaunchAgents/com.lockin.publish.plist`. This leaves the database, saved reports, website, and email automation intact.

Back up `data/lockin.sqlite3` while no refresh is running, together with private configuration and state using your normal local backup. It is the authoritative live game store. Replay fixtures remain separately checksummed Parquet files for reproducible practice.

## Freshness and display

The browser and local dashboard suppress actionable results after 26 hours: one daily publication interval plus two hours of delay allowance. Midnight within the same fantasy week does not expire the report; a previous week expires when the next Monday begins. Invalid/future timestamps also suppress recommendations. The website checks every minute and when a hidden tab becomes visible. Expired player details close, while completed/drafting/upcoming statuses remain visible. The original snapshot date/time stays visible, and device clock accuracy affects browser expiry.

Statistics and schedule failures preserve independent roster/schedule information without inventing a lock call. Missing performances suppress decisions and pickups. Unknown scoring rules still produce scoring gaps; omitted fouls and approximated rebound splits produce informational notes. Milestone bonuses are computed per league from observations.

**Reload report** retrieves the published JSON; it does not trigger a local run. Team switching, player profiles, searches, filters, and pickup research work from the snapshot. Test Week, account connection, roster editing, and archived-league browsing remain in the local Flask app.

## Phone layout and screenshots

The same URL adapts at 740px and below, with bottom navigation, horizontally scrollable teams, compact roster rows, and player details in a bottom sheet. The existing [mobile roster](screenshots/mobile-roster.png) and [player sheet](screenshots/mobile-player-detail.png) captures show generic historical sample teams, not the current live scoring notes or publication status. They document the roster layout only. [Screenshot notes](screenshots/README.md) identify the remaining capture scope.

## Public data boundary

The exported report contains team/league names, league-derived IDs, roster players, lineup slots, NBA teams/injury labels, opponents, observed fantasy points, scoring notes, recommendations, pickup results, and publication metadata. It contains no account username field, email addresses, credentials, full ownership lists, or internal database paths. These display fields are public.

Only generated files are committed to the publishing branch. Existing images can be included; otherwise the site uses NBA's image CDN with an initials fallback. Google Fonts and the image CDN are independent browser requests. The database and local reports are not copied into GitHub Actions caches or the publishing branch.

## Verification

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m black --check *.py tests
node --test tests/pages.test.cjs
```

Tests cover scoring policies, incremental upserts, failure retention, daily due slots, wake-equivalent catch-up timing, publication deduplication, backoff, delayed deployment confirmation, and a real local Git push to a temporary bare repository to inspect the exported file boundary. The LaunchAgent property list is validated. These checks do not constitute a physical sleep/wake hardware test or establish provider uptime/model accuracy.

For a local static preview without network calls:

```bash
.venv/bin/python pages.py --output dist/preview
.venv/bin/python -m http.server 8766 --bind 127.0.0.1 --directory dist
```

Use a fresh output directory each time. Open `http://127.0.0.1:8766/preview/`.

References: [Apple scheduled jobs and sleep/wake behavior](https://developer.apple.com/library/archive/documentation/MacOSX/Conceptual/BPSystemStartup/Chapters/ScheduledJobs.html), [GitHub Pages publishing sources](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site), [Pages configuration API](https://docs.github.com/en/rest/pages/pages).
