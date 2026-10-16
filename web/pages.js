/* Pure report expiry policy, shared by the browser and offline Node tests. */
(function (root) {
  "use strict";
  function currentDate(now) {
    // Alberta remains UTC-6 from Nov 2026; older phones may carry stale tzdata.
    // https://www.alberta.ca/albertas-new-time-system-abt
    const zone =
      now >= new Date("2026-11-01T00:00:00Z")
        ? "Etc/GMT+6"
        : "America/Edmonton";
    const parts = new Intl.DateTimeFormat("en-CA", {
      timeZone: zone,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    }).formatToParts(now);
    const field = (type) => parts.find((p) => p.type === type).value;
    return `${field("year")}-${field("month")}-${field("day")}`;
  }
  function prepareReport(source, now = new Date()) {
    if (
      source.schema_version !== 1 ||
      !Array.isArray(source.teams) ||
      !Array.isArray(source.alerts)
    ) {
      throw new Error(
        "Published report format is invalid. No recommendations available.",
      );
    }
    const report = JSON.parse(JSON.stringify(source));
    const age = now.getTime() - Date.parse(report.generated_at);
    const stale =
      !Number.isFinite(age) ||
      age < -300000 ||
      age > 6 * 3600000 ||
      report.date !== currentDate(now);
    if (stale) {
      report.alerts.unshift({
        severity: "warning",
        message:
          "This report is out of date. Lock and pickup recommendations are hidden until a fresh scheduled report is published.",
      });
      for (const t of report.teams) {
        t.pickups = [];
        for (const p of t.results) {
          if (
            ["LEAGUE_COMPLETE", "PRE_DRAFT", "DRAFTING", "UPCOMING"].includes(
              p.status,
            )
          )
            continue;
          Object.assign(p, {
            status: "STALE",
            decision: null,
            p_lock: null,
            p_wait: null,
            note: "Report expired. Wait for a fresh scheduled report before making a decision.",
          });
        }
      }
    }
    report.stale = stale;
    return report;
  }
  const policy = { prepareReport, currentDate };
  if (typeof module !== "undefined" && module.exports) module.exports = policy;
  else root.LockInPages = policy;
})(typeof window === "undefined" ? globalThis : window);
