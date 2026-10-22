# Epic kickoff: smaller static exports and on-demand player data

**Status:** proposed; documentation only. None of this epic is implemented.

**Prepared:** October 21, 2026.

**Delivery boundary:** retain the local SQLite database, daily Mac publisher,
read-only GitHub Pages website, and existing scoring/model behavior. This document
is a handoff for a later implementation task, not authorization to start it now.

## Outcome

Open the roster with only the data needed to render it. Publish shared player
identities once, fetch larger directories and detailed history when requested,
reuse unchanged snapshots safely, and serialize public JSON compactly.

This is an export/frontend contract improvement, not a database overhaul. No
hosted database, remote API, authentication, provider subscription, new scheduler,
or change to recommendation logic is required.

## Measured starting point

Measurements taken from the October 21, 2026 published report and its local saved
counterpart. Re-measure at kickoff; these are observations, not permanent limits.

| Measurement | Observed value |
| --- | ---: |
| Published `report.json`, decoded | 3,122,257 bytes |
| Actual GitHub Pages gzip response body, from Content-Length | 205,316 bytes |
| Local saved public JSON | 3,122,057 bytes |
| Same local JSON serialized without whitespace | 1,671,145 bytes |
| Local compact JSON compressed with gzip | 164,132 bytes |
| Published teams / roster entries | 5 / 82 |
| Available-player entries summed across teams | 8,072 |
| Available-player sections, compact local JSON | 1,310,483 bytes |
| Roster result sections, compact local JSON | 298,647 bytes |
| Season badge sections, compact local JSON | 29,294 bytes |

The available-player sections contribute approximately 78% of compact report
bytes. Entries repeat across leagues; some identities are unresolved, so a set
of NBA IDs is not a reliable count of distinct directory players. Badge summaries
are comparatively small. Local gzip estimates are not measured CDN transfers.
These figures exclude HTML, scripts, styles, portraits and other image requests.

Do not use `dist/pages/report.json` as the baseline without checking its date:
that directory contained an older small preview during the audit. Measure the
actual publication and current saved public report.

## Source map and constraints

| Existing code | Relevance |
| --- | --- |
| `engine.py`, `pickups.py` | League-specific results and available-player summaries |
| `pages.py:public_report` | Explicit public-field allowlist; history currently capped at 25 games |
| `pages.py:export_site` | Static bundle, portraits, hashed asset URLs and report JSON |
| `publication.py` | Publication lock, fast-forward branch push, visibility verification and retry ledger |
| `web/app.js:api` | Currently fetches the entire report with a timestamp query and `cache: no-store` |
| `web/pages.js` | Freshness policy, schema checks and suppression of stale recommendations |
| `web/insights.js` | Form, sparklines, roster/game display, season and badge presentation |
| `tests/test_pages.py`, `tests/test_publication.py`, `tests/pages.test.cjs` | Export/privacy, delivery and frontend policy coverage |

Read [repository instructions](../../AGENTS.md), [Hosting](../HOSTING.md),
[Architecture](../ARCHITECTURE.md), [Season review](../SEASON_REVIEW.md), and
[Performance colours](../PERFORMANCE_COLOURS.md) before implementing. The roster
must remain first and immediately usable on desktop and mobile. Preserve Test
Week, local Flask behavior, stale-data safeguards, projection provenance, badge
cards for non-roster players, portraits and backdrop dismissal.

## Proposed public contract

Names below illustrate the design; finalize and document the schema before coding.

- A small mutable `manifest.json`: schema version, publication ID, original
  generated-at/published-at timestamps, refresh status, and immutable resource
  paths with content hashes and byte lengths.
- An immutable core snapshot: team summaries, roster references and essential
  per-league scores/projections, current weekly tiles, lineup slots, alerts,
  freshness metadata, and only the identities needed for the initial screen.
- Shared player-directory resources, loaded when browsing available players.
- League-scoped availability and computed-metric resources referencing shared
  identities, instead of repeating identity objects per league.
- Bounded detail/history resources loaded on opening a player card. Prefer a
  modest number of per-league or per-team shards over thousands of tiny files;
  benchmark request overhead before deciding shard boundaries.
- Season review/badge resources may be deferred to that tab if measurements
  justify it. Preserve badge-summary availability when opening any player card.

Use paths under the site's repository subdirectory, not domain-root paths.
Every resource reference must resolve within the intended publication. Export
only allowlisted fields in every shard; moving data into another file must not
bypass `public_report`'s privacy boundary.

### Shared identity versus league state

Share NBA/provider IDs, display name and portrait reference where their meaning
is global. Current NBA team, position and injury metadata may be shared only when
their season/source/snapshot semantics match. Historical team labels and
league-specific eligibility must not be overwritten by a current directory row.

Keep league scoring, fantasy-point history, baselines, projections, availability,
ownership completeness/timestamp, starter/slot assignment, recommendations and
fantasy badge totals scoped to the appropriate league and season. Sharing a
player identity does not imply sharing fantasy scores. Identical formula-based
data can be deduplicated only with a complete stable formula/policy/season/cutoff
key and evidence that the inputs are equivalent.

Use deterministic namespaced keys, such as `nba:<id>` and `sleeper:<id>`. Inspect
upstream identifiers for directory players lacking NBA IDs; do not collapse all
null IDs, use array positions, or assume names are unique. If identity resolution
cannot be made reliable within this epic, retain those records separately with
stable source identifiers and document the limitation. Never publish full private
ownership lists merely to reconstruct the already-public available-player list.

### On-demand loading and derived summaries

Inventory every consumer of history before removing it from the core. Recent
form, roster sparklines, performance colours and completed weekly scores currently
depend on observed history. Supply bounded, precomputed presentation summaries
where needed so the roster does not silently trigger all detail requests.
Maintain exact semantic parity, including sparse samples, negative/zero values,
prior-season blending and observation cutoffs. Do not silently shorten the form
window or recompute scoring differently in the browser.

The first click opens a card immediately with identity and a loading state, then
fills its details. Display zero awards separately from loading or unavailable
badge history. Failed detail requests leave the roster usable and offer retry.
No-history non-roster badge cards remain valid without inventing game history.
Closing the card, switching player/team, changing modes, or receiving a newer
manifest must prevent a late response from replacing the active card's contents.
Deduplicate concurrent requests; cache by publication/resource and league scope.

Available-player search/filter/sort must cover the complete selected directory,
not just already-rendered rows. Pagination cannot hide matches. Preserve ownership
unknown states, scoring-gap behavior, injury labels and snapshot dates.

### Caching without false freshness

Revalidate the small manifest with HTTP cache semantics or a bounded cache-busting
check if Pages requires it. Fetch immutable resources with normal caching, and
reuse already-loaded resources when the manifest has not changed. Do not retain
the current timestamp query on every large resource. GitHub Pages controls cache
headers: inspect real responses rather than assuming custom immutable headers.

Browser response caching and an in-memory resource map are sufficient starting
points. A service worker or persistent application database is not required.
If persistent caching is later justified, specify eviction, schema validation,
quota/error handling and treatment of removed public records first.

Cache hits and republishing assets must never reset the report's generated-at or
observation timestamps. Reapply existing freshness rules at read/display time,
including midnight/week boundaries, 26-hour expiry, invalid/future timestamps,
failed refreshes and visibility changes. A failed version check must be visible;
retained data stays dated and may not become a fresh recommendation.

### Compact serialization

Write public JSON with compact separators and deterministic ordering where
appropriate for reproducible content hashes. Preserve Unicode, precision, null,
zero and negative values. Continue rejecting NaN/Infinity. Limit the change to
public exports; do not globally minify private config, logs or state files.
Measure uncompressed and actual compressed bytes separately. Git transport may
delta-compress history; do not estimate repository growth as raw size times days.

## Publication consistency, rollout and rollback

Generate and validate all files from one frozen report before pushing. Publish
the manifest and referenced resources together, preserving normal fast-forward
history. CDN caching can still mix versions: hash-addressed resources and explicit
version checks must prevent joining incompatible snapshots.

Define a bounded retention policy for prior immutable resources so an already-open
tab can finish loading details after a deployment. Size the retention window to
the supported report lifetime plus a documented margin. Handle an older missing
resource by revalidating the manifest and requesting a coherent snapshot, not by
silently joining new details into an old roster. Retention is not permission to
keep removed sensitive data indefinitely. Document rollback and retention cleanup.

Upgrade publication visibility verification to check the manifest identity and
required resources before marking delivery successful. Distinguish successful
asset delivery from a successful data refresh. Preserve locks, retries, pending
uploads, provider-failure behavior, and prior-season/current-season boundaries.

Use an explicit versioned schema and test old clients. Choose a temporary v1
compatibility export or a documented coordinated transition; if dual publishing,
measure its temporary total-size cost and define its removal milestone. Keep
legacy cached pages from silently misreading v2. A rollback must restore a matching
HTML/script/manifest/resource set without forcing Git history.

## Ordered implementation backlog

| Ticket | Work and completion evidence | Depends on |
| --- | --- | --- |
| EXP-01 | Record current payload sections, duplicate identities, request waterfall, rendered parity and representative long-season fixture; agree schema and budgets | None |
| EXP-02 | Add allowlisted shared identity/resource exporter and stable unresolved-ID strategy; prove league/season isolation and field privacy | EXP-01 |
| EXP-03 | Add compact deterministic serialization, content-addressed files and manifest; validate references/hashes and compatibility path | EXP-02 |
| EXP-04 | Add frontend resource loader, request deduplication, version-aware caching, error/retry and race handling | EXP-03 |
| EXP-05 | Move available directory and detail history to on-demand requests; preserve core summaries and all player-card workflows | EXP-04 |
| EXP-06 | Extend publisher verification, retention/cleanup, migration and rollback tests | EXP-03, EXP-05 |
| EXP-07 | Compare performance/semantics, update README and guides/screenshots, deploy and verify selected version | EXP-06 |

Implementation should happen in reviewable increments. Do not ship a partially
converted reader/writer contract. Keep optional extra optimizations out of the
critical path unless the measurements demonstrate a need.

## Acceptance criteria and verification

- On the same five-team fixture, aim for at least 50% less decoded initial JSON
  than today's compact monolith, excluding deferred resources. Record the result,
  not just a claim. Document any budget adjustment before accepting the change.
- Total canonical snapshot bytes decrease with no missing user-visible records;
  report temporary compatibility files and retained snapshots separately.
- Initial roster load requests no complete available-player directory or detailed
  history. Opening the relevant view fetches the required resources once; an
  unchanged manifest causes no repeat large application fetch in the same session.
- Repeated reload measurements distinguish browser memory/disk cache from network
  transfer. Record request counts, compressed bytes, JSON parsing/rendering timing,
  device/browser and throttling settings; do not invent performance targets met.
- League-specific FP, badges and availability match v1 for the same input. Test
  identical names, missing NBA IDs, numeric/string IDs, trades, multiple formulas,
  archived leagues and local/Test Week behavior.
- Test 404, malformed JSON, corrupt hash, unknown schema, manifest failure,
  partial deployment, expired cache, old tab, rollback, simultaneous requests,
  rapid team/player switching, and closing a card during its request.
- Every exported file passes privacy checks. No raw DB, credentials, account
  configuration, private ownership list or unsafe external resource path appears.
- Verify roster-first layout at 320px, 390px and desktop widths; preserve keyboard
  focus, loading announcements, outside-click/tap dismissal, portraits/fallbacks,
  expandable badge counts, directory search and recent form.
- Run existing Python tests, formatter check and Node tests plus meaningful new
  contract/publication/loader regressions. Refresh affected generic screenshots,
  check Markdown links and document measured before/after results and rollback.

## Ready-to-start handoff

Start by reading this document and the current exporter, loader and publisher;
inspect the working tree for other changes. Reproduce the baseline without
refreshing providers unnecessarily or changing the live DB. Write down the
chosen identity schema, shard boundaries, freshness/cache policy and compatibility
strategy, then implement EXP-01 onward. Preserve the public read-only boundary
and all scoring semantics. Reconsider a hosted backend only for a separate
requirement such as accounts, writes or frequent interactive historical queries.
