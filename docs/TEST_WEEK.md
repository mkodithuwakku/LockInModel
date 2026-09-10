# Test Week: play through a saved NBA week

Open **Test Week** in the sidebar. A new run starts on Monday morning, December 22, 2025. Your four original local teams are practice rosters; the normal **My teams** workspace contains Sleeper imports. The two collections cannot overwrite each other.

## Play a week

1. Choose a practice team. Inspect player histories and the model, adjust starters or the roster in the morning, and visit **On the rise** for candidate research.
2. Press **Reveal tonight’s games**. The archived performances for that date become visible in the night's box scores, player histories, and recalculated recommendations.
3. Press **Bank score** on any eligible starter to keep that player's latest completed weekly score. You may disagree with a WAIT recommendation; banking records your own choice. Data failures and incomplete scoring cannot be banked.
4. Press **Next morning**. Previously observed scores remain available; tonight's outcomes are hidden again. Remaining opportunities include today's games.
5. Continue through Sunday night. Bank any remaining scores and compare your choices with the performances that unfolded. There is no automatic banking or actual Sleeper action.

The green total counts banked starter scores only. It is not a projected total or a Sleeper matchup result. Each starter can bank one score for the week. A banked score stays fixed, even if a later game is better. Banked players cannot be removed or benched during the run. **Restart week** clears all practice choices and roster edits, restoring the saved practice templates and Monday morning. Restart resets all practice teams together.

## What is saved

The clock, starting configuration snapshot, starter/roster edits, and banked scores live in ignored `state/test-week.json`. Reloading the browser resumes the same run. Each mutation supplies a revision so double clicks or stale tabs cannot advance twice or overwrite another action. Successful analysis is computed before changed state is written atomically.

The baseline engine and pickup calculations are shared with normal reports. Morning observations end yesterday; night observations include the newly revealed day's games. The week boundary remains Monday–Sunday in both phases. No statistical input after the observation cutoff reaches the model or pickup engine.

## Practice assumptions

Practice uses the original sample scoring rules, not the unsupported foul penalties from your imported leagues. It has sample rosters, no historical league-wide ownership, and no reconstructed draft or transaction history. On the Rise labels ownership as unknown; it excludes the selected practice roster, not every team from a real historical fantasy league.

The clock advances whole nights, not live game minutes or exact lock deadlines. The simulator does not enforce all of Sleeper's transaction/lineup rules. It is an offline decision practice tool, not a recreation of an official fantasy matchup. Finalized schedules and the prior-season baseline have the limitations described in [Historical replay](HISTORICAL_REPLAY.md).

For an arbitrary end-of-day inspection without changing your practice run, the CLI still accepts `python main.py --date 2025-12-25`.
