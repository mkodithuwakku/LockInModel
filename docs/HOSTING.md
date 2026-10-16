# Hosted daily dashboard

[Open LockIn](https://mkodithuwakku.github.io/LockInModel/).

GitHub Pages hosts a public, read-only version of the shared dashboard. GitHub Actions runs Python to produce the report. Your computer can be off. This is a scheduled snapshot: opening the page or selecting **Reload report** retrieves the published JSON, not a new NBA API request.

## What works online

- Switch between current Sleeper teams; each league keeps its own scoring and ownership filters.
- Browse starters/bench, search players, open profiles, inspect recent box scores and model explanations.
- View league-specific On the Rise results and data alerts.
- See a full report date/time, refresh failures, and stale-data status on desktop or mobile.
- Rosters update after the next successful scheduled import. Undrafted leagues show a draft-pending state. Earlier seasons are excluded once the current season is available.

Test Week, roster editing, account editing, and archive browsing remain in the local Flask app. The hosted interface hides those controls rather than presenting nonfunctional buttons. It never submits Sleeper actions or sends email. The existing local email automation is independent.

## Phone layout

The same GitHub Pages URL automatically switches to a phone layout at 740px and below. It includes bottom navigation for My teams, On the rise, and Data alerts; horizontally scrollable team cards; compact search; and dense roster rows with colored lineup slots, NBA team/injury labels, lock indicators, and a seven-day opponent/observed-FP strip. Starters, bench, and reserve/taxi players are grouped separately. Unknown schedules show question marks rather than pretending the player has an off day. Player details open in a scrollable bottom sheet. Navigation and dialogs account for device safe areas; the page reserves space for the bottom bar.

No mobile server, separate deployment, or app installation is required. **Reload report** still retrieves the published snapshot; phone visits do not trigger NBA requests.

The [mobile roster](screenshots/mobile-roster.png) and [player sheet](screenshots/mobile-player-detail.png) screenshots use generic sample teams and clearly labeled historical fixture data. Browser checks covered 320px, 390px, and 468px phone widths plus the 1440px desktop layout, including horizontal overflow, team switching, player search, pickup browsing, and profile dialogs. These are responsive browser checks, not physical iOS/Android device certification. The desktop README screenshots show the local Test Week workflow.

Before opening night, the grid previews the opening week and players show UPCOMING. This is a valid report with no completed score to lock, not a failed refresh. Game times are unavailable in this schedule feed; dates/opponents are shown without invented tip-off times.

## Schedule and publication

`.github/workflows/pages.yml` runs at **12:17 PM America/Edmonton**. It schedules 18:17 UTC, matching noon plus 17 minutes under Alberta’s permanent UTC−6 time. Manual runs and relevant pushes to `main` also publish. GitHub can delay scheduled workflows; Public-repository schedules may be disabled after 60 days without repository activity. This is not a guaranteed deadline service.

The workflow runs offline Python and frontend-policy tests first. It then:

1. Restores saved HTTP responses, host cooldowns, and the previous sanitized report from Actions cache.
2. Creates a temporary configuration from checked-in model defaults and `SLEEPER_USERNAME` (a repository secret). No `.env` or email settings are uploaded.
3. Imports this year's Sleeper NBA leagues, falling back to the previous season when none exist yet. No sample rosters are published as personal teams.
4. Runs shared live analysis. Completed/undrafted leagues skip NBA analysis. Drafted leagues load one cached Sleeper season schedule first; NBA Stats is skipped until a regular-season game can enter the observation cutoff.
5. Exports only allowed report fields and the four frontend assets to a fresh `dist/pages` directory.
6. Uploads that directory to Pages and deploys it with GitHub's Pages action.

Jobs serialize through one concurrency group. Network requests retain existing pacing, bounded timeouts, and cooldowns. There is no historical capture or automatic rapid retry. Actions cache is an optimization and can be evicted; on a cold run the same request pacing applies. A hosted NBA Stats outage still prevents fresh performance analysis; it no longer prevents displaying independently verified roster metadata and schedule data.

## Freshness and failure behavior

The browser suppresses lock/wait probabilities, decisions, and pickup recommendations when the report is older than six hours, has an invalid/future timestamp, or belongs to a different Edmonton date. It checks every minute and when a hidden tab becomes visible; open player details close when the report expires. Completed/drafting league statuses remain visible. Device clock accuracy matters to browser expiry.

Statistics and schedule failures produce specific alerts while preserving independent data. Missing performances suppress decisions and pickups; missing schedules suppress lock decisions while retaining observed scores. Mixed active and undrafted leagues remain visible. A roster-sync or unexpected top-level failure produces a new report with a visible failure alert and no actionable calls. Saved rosters may remain visible, but are explicitly described as potentially outdated. If no roster could be imported on a clean runner, the previous sanitized report supplies the fallback roster. Its original timestamp is retained. Player-level schedule errors are handled by the shared engine.

If tests, packaging, or deployment fail, the previous deployed site remains available and will expire in the browser. The Pages workflow log records whether refresh was successful, partial, or failed. A successful deployment of an error report is not proof of successful data retrieval.

## Public data boundary

The published report contains team/league display names, season, roster players, starter flags, lineup slots/order, NBA team and injury labels, weekly opponents and observed game FP, scoring coverage, observations, recommendations, and pickup results. Nested schedule fields are explicitly allowlisted. Treat these as public information. It contains no account username field, recipient addresses, email credentials, raw configuration, full league ownership list, or internal dataset paths. League-derived IDs are public identifiers, not credentials. Arbitrary newly added internal fields are excluded unless added to the export allowlist.

Only `dist/pages` is uploaded. `.env`, `config.local.yaml`, `state`, and raw API caches are never part of the Pages artifact. Actions caches hold public API responses and the sanitized report; they are not a secret store. Never add credentials to those paths. Headshots use locally available images when exported, otherwise NBA's image CDN, with initials if loading fails. The image CDN and optional Google Fonts are separate external requests, not NBA Stats calls.

## Setup and recovery

1. Set repository Actions secret `SLEEPER_USERNAME` to the account to publish. No Sleeper password is required.
2. In repository **Settings → Pages**, choose **GitHub Actions** as the source.
3. Run **Actions → Publish daily dashboard → Run workflow**, using `main`.
4. Check the build and deploy jobs, then open the Pages link. Confirm the displayed report timestamp and any alerts.

For a data failure, inspect provider status and wait for its cooldown before a manual rerun. For an inactive schedule, re-enable it in Actions. For a draft or transaction made after the daily snapshot, wait for the next scheduled import or manually run the workflow. Reloading the website alone does not trigger a run.

A free GitHub Pages address needs no purchased domain. Public repositories and standard hosted Actions runners are eligible for free use subject to GitHub's usage limits. Do not select larger paid runners for this workflow.

## Local verification

From the project root, export saved data without network requests:

```bash
.venv/bin/python pages.py --output dist/preview
.venv/bin/python -m http.server 8766 --bind 127.0.0.1 --directory dist
```

Open `http://127.0.0.1:8766/preview/`. The destination must be empty; use a new directory for another export. To explicitly refresh from live providers, use `pages.py --refresh` with an existing local Sleeper connection. In CI, the environment variable initializes an isolated configuration; do not set it during a local preview unless intentionally replacing the local configuration.

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m black --check *.py tests
node --test tests/pages.test.cjs
```

The Python tests check export boundaries, failed imports, successful engine routing, and nonfinite data. Node tests check expiry, historical Edmonton DST, and permanent Alberta Time. The browser uses the confirmed UTC−6 rule from November 2026 even when the device has older timezone data. Browser verification separately checks the static site at a repository subpath and the deployed public link. No test establishes future provider uptime or model accuracy.

Timezone reference: [Alberta’s new time system](https://www.alberta.ca/albertas-new-time-system-abt).

References: [Pages custom workflows](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages), [Actions schedule limitations](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule), [Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions).
