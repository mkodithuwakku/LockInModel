# Known issues and remaining work

## Corrected in this implementation

- Bonus flags now survive normalization and scoring; threshold and stacking cases are tested.
- Empty/failed schedules no longer become zero remaining games or confident LOCKs.
- The UI and reports share canonical YAML; the disconnected Tkinter selection path was replaced.
- `.env`, virtual environments, editor files, and runtime state were removed from tracking and ignored.
- HTTP calls are cached, paced, time-bounded, and protected by persistent failure cooldowns.
- Historical capture and offline replay exist, with explicit time and prior policies.
- Repeated email attempts are suppressed, including uncertain SMTP delivery outcomes.
- Constant/tiny rarity variance no longer creates artificial extreme rarity signals.

## Credential and Git history handling

The repository is public, and the configured email app password matched the one committed in its original history. The local guard blocks that password. Revoke and replace it in Google; Git cleanup cannot revoke a credential.

Removing secrets from the current tree is separate from purging historical commits. The cleaned `modernize-dashboard` branch has been pushed and its reachable history scanned for the exposed credential and private paths. The existing public `main` still contains the original history. Replacing it requires a deliberate coordinated update; do not merge the original history back into the cleaned branch. Old clones and provider caches may still retain historical contents, so credential rotation is essential regardless of branch cleanup.

Local credentials, imports, cache files, and `.venv` remain on the computer; removing them from tracking does not delete those local files.

## Functional limitations

| Area | Limitation |
| --- | --- |
| League scoring | Technical/flagrant foul penalties are unavailable; affected teams show partial FP and no lock decision |
| Sleeper lock state | Read-only rosters are imported, but existing lock selections are not; the app does not submit actions |
| Live availability | NBA Stats timed out during this session; historical operation is verified, live provider availability is not guaranteed |
| Offseason | Completed leagues produce no active recommendations; new-season rosters must exist before meaningful live analysis |
| Historical schedules | Finalized schedule and last observed team assignment, not timestamped historical schedule/transaction snapshots |
| Historical ownership | Current import or sample roster; availability claims are not historical |
| Injury/role context | Minutes are observed; historical injuries, upcoming absences, and lineup news are not modeled |
| Pickup projection | Hand-tuned conservative estimate, not a fitted/calibrated forecast |
| Position fit | Shared position compatibility; no full roster-slot optimization or waiver-budget strategy |
| Local configuration | Atomic writes, but no cross-process configuration transaction lock; one editor process is intended |
| Deployment | Local loopback app only; no public authentication, production server, or hosting configuration |
| Runtime | Existing Python 3.9/LibreSSL environment retained; modern runtime and dependency upgrade remains desirable |
| License | No project license chosen |

## Priorities after this release

1. Replace the exposed credential and finish coordinated public-history cleanup.
2. Add a reliable source for missing foul penalties or an explicit user-approved scoring policy for affected leagues.
3. Verify live inputs when the next leagues and games become active.
4. Evaluate the lock and pickup policies across multiple held-out weeks.
5. Add richer injury/role context and precise historical roster/schedule snapshots where useful.

There are no established accuracy, profit, win-rate, or production-scale claims.
