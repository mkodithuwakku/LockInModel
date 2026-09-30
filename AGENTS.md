# Project instructions

These instructions apply to the entire repository.

## Keep the README current

Treat `README.md` as a living, portfolio-quality walkthrough of the implemented
project. Review it for every code, dependency, configuration, or workflow change.
Update affected sections in the same change; documentation is part of completion,
not a separate follow-up task.

- Keep features, architecture, API/data flow, persistence, scoring/model behavior,
  setup commands, configuration, tests, and limitations consistent with the code.
- Update linked guides in `docs/` when their details change. Avoid conflicting
  descriptions between the README and those guides.
- When the visible workflow changes, refresh affected screenshots in
  `docs/screenshots/`. If a replacement cannot be captured, remove or clearly label
  the outdated image and document the screen/state that needs capturing.
- Preserve the short recruiter overview and technical interview material:
  meaningful decisions, tradeoffs, challenges, and a concrete implementation deep dive.
- Verify claims against source files and configuration. Distinguish implemented,
  tested, and planned behavior. Do not invent personal motivation, ownership history,
  measured accuracy, performance, deployment, or security guarantees.
- Preserve model/replay limitations and data provenance. Lock scores and pickup
  scores are heuristics; a working replay does not establish predictive accuracy.
- Never include credentials, private configuration, or personal account details in
  documentation or screenshots.

Before finishing, check local Markdown links and referenced files, validate changed
commands where practical, and run checks appropriate to the code change. Summarize
documentation updates and validation in the handoff. If a change has no effect
on documented behavior, explain that briefly instead of adding a meaningless
README edit. Documentation-only changes do not require new application tests.

These instructions govern future work in this repository; they do not create a
background README generator or scheduled task.
