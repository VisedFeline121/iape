# FloorFlow — Person 4: Final Vision

This document describes the finished product. Every implementation decision must be evaluated against it.
Do not anchor on the current code. Anchor on this.

---

## The Demo Moment

The judges are watching a live screen. An unknown building. No floor plan. Zones and movement lines
are materializing in real time as wireless signals come in — the system is discovering the structure
of the building on its own.

Then, live, an alert appears:

> **⚠ WARNING — Sector 4 developing bottleneck**
> Traffic has tripled in 90 seconds. Two approach paths are converging with no outflow route.
> Sector 4 is at 73% of estimated capacity. Recommend diverting flow through Sector 2.

Thirty seconds later, the alert escalates:

> **🔴 CRITICAL — Sector 4 congestion confirmed**
> Inbound traffic continues to rise. No outflow detected in the last 2 minutes.
> Immediate intervention required.

Then it resolves:

> **✓ RESOLVED — Sector 4 returning to normal**
> Traffic dropped 60% over the last 3 windows. Situation stabilizing.

Meanwhile, a separate alert:

> **🔍 ANOMALY — New route detected: Sector 6 → Sector 1**
> This path has never been observed in this session. First seen 14 seconds ago, used 4 times.
> Possible evacuation behavior or access to a previously unused area.

The judges see a system that understands what is happening in a building it has never seen before —
and tells the people who need to act, exactly what to do.

---

## What the Insight Engine Is

It is a **real-time situational awareness engine**.

It does not produce reports. It maintains a live model of developing situations and speaks
in the language of emergency operations. It tells the incident commander what is forming,
how fast, how bad, and what it implies — before it becomes a crisis.

---

## Alert Lifecycle

Every alert has a lifecycle. It is not "on" or "off."

```
DETECTING → WARNING → CRITICAL → RESOLVING → RESOLVED
```

- **DETECTING**: a signal is emerging but not yet confirmed (low confidence, informational)
- **WARNING**: the pattern is established and worsening (medium confidence, requires attention)
- **CRITICAL**: the situation is severe and active (high confidence, requires immediate action)
- **RESOLVING**: conditions are improving (confidence dropping, monitoring)
- **RESOLVED**: situation cleared — an explicit resolution event is emitted so Person 5 can clear the alert

An alert's severity escalates automatically as conditions worsen across successive snapshots.
It does not reset — a zone that briefly improves but then worsens again should escalate faster
the second time (the system has memory of the developing pattern).

---

## Alert Severity Levels

Three levels: `info`, `warning`, `critical`. Severity level is included in every emitted insight alongside `confidence`.

- **`info`** — pattern detected, not yet actionable
- **`warning`** — situation developing, warrants attention
- **`critical`** — immediate action recommended

Exact confidence boundaries are to be calibrated against real data from Person 3. Do not hardcode thresholds — make them tunable constants determined during integration testing.

---

## Cross-Zone Reasoning

The engine does not look at zones in isolation. It looks at the building as a system.

Examples of cross-zone insights the engine should be capable of:

- **Convergence alert**: multiple zones are all routing traffic to the same destination —
  the destination is about to be overwhelmed even if it looks fine right now.
- **Isolation alert**: a zone that normally receives traffic has gone quiet while its
  upstream feeders are still active — possible blockage or access loss.
- **Overflow pattern**: a congested zone suddenly starts sending traffic to a zone it
  never used before — the system is rerouting itself, which is often a precursor to
  complete congestion.
- **Cascade risk**: Zone A is warning, Zone B (downstream of A) is already at warning —
  if Zone A tips to critical, Zone B goes critical within one or two windows.

---

## The Message Voice

Every message is written as if a calm, expert operations officer is speaking to an incident
commander over comms. Not an engineer reading a log. Not a data analyst summarizing a chart.

**Rules:**
- Lead with what is happening, not what the data shows
- Include time context whenever available ("over the last 2 minutes", "in the last 3 windows")
- Include magnitude ("traffic tripled", "4× normal dwell", "used 6 times in 30 seconds")
- End with an implication or recommendation when confidence is high
- Never say "z-score", "threshold", "standard deviation", or any statistical term
- Use zone labels as Person 5 will display them — if zones are unlabeled, use "Sector N"

**Good:**
> Sector 3 has absorbed 32 inbound movements in the last 5 minutes with an average stay of 14 seconds
> and no sign of outflow slowing. This zone is approaching capacity.

**Bad:**
> Zone 3 has a high dwell z-score and above-threshold inbound traffic count.

---

## System-Level Summary

At every cycle, in addition to individual alerts, the engine emits one global summary insight:

```json
{
  "zone_id": "global",
  "insight_type": "situation_summary",
  "severity": "warning",
  "message": "3 active alerts across 4 observed sectors. One critical situation developing in Sector 3. System has been running for 8 minutes across 6 snapshots.",
  "confidence": 1.0
}
```

This is what Person 5 displays as the "headline" of the dashboard.

---

## Output Contract (to Person 5)

### Per-cycle snapshot file
Written to `anomaly_reports/insights_<timestamp_ms>.json` on every cycle.

```json
{
  "snapshot_ts": 1718045312000,
  "cycle": 7,
  "elapsed_seconds": 420,
  "summary": { ...global summary insight... },
  "alerts": [
    {
      "id": "zone_3__congestion_forecast",
      "zone_id": "zone_3",
      "insight_type": "congestion_forecast",
      "severity": "critical",
      "message": "Sector 3 traffic has tripled over the last 90 seconds...",
      "confidence": 0.87,
      "first_seen_ts": 1718045100000,
      "last_updated_ts": 1718045312000,
      "cycle_count": 4
    }
  ]
}
```

### Event stream
Appended to `anomaly_reports/events.ndjson` — one line per event, every cycle.

```json
{"ts": 1718045312000, "cycle": 7, "event": "escalated", "alert_id": "zone_3__congestion_forecast", "from_severity": "warning", "to_severity": "critical", "insight": {...}}
{"ts": 1718045312000, "cycle": 7, "event": "new",       "alert_id": "zone_6__anomaly",              "insight": {...}}
{"ts": 1718045312000, "cycle": 7, "event": "resolved",  "alert_id": "zone_1__bottleneck_risk"}
```

Event types: `new`, `escalated`, `de_escalated`, `updated`, `resolved`

---

## Input Contract (from Person 3)

Person 3 continuously writes new timestamped graph snapshot files to `movement_graphs/`.
Each file is a complete graph at that moment, including all `time_windows` observed so far.

Person 4 watches `movement_graphs/` for new files (by mtime / directory listing diff),
processes each in arrival order, and maintains state across cycles.

File naming: `movement_graphs/graph_<timestamp_ms>.json`

---

## What "Done" Looks Like

- [ ] Alert lifecycle works end-to-end: an alert appears, escalates to critical, then resolves
- [ ] Cross-zone convergence detection fires correctly on mock data
- [ ] Every message passes the "incident commander" read-aloud test — no jargon, no log lines
- [ ] System-level summary is accurate and updates every cycle
- [ ] Output files are written correctly on every cycle with no crashes
- [ ] Engine runs continuously for 10 minutes on mock data with no memory leaks or drift
- [ ] All 5 insight types are triggerable from realistic input
- [ ] Resolution events fire correctly when conditions improve
- [ ] Engine handles edge cases gracefully: empty graph, single zone, missing time_windows

---

## Dependencies

Use whatever produces the best product. No blanket restrictions.

Examples of packages worth considering:
- `numpy`, `scipy` — statistics and trend analysis
- `scikit-learn` — isolation forest and other anomaly detection algorithms
- `pandas` — time-series manipulation across snapshot history
- `openai` or `anthropic` — LLM message generation in the hybrid architecture
- `watchdog` — filesystem event watching (alternative to polling)

Evaluate each dependency on its merits: does it meaningfully improve quality or reliability? If yes, use it.

---

## What Is Out of Scope

- Re-clustering signals (Person 2)
- Rebuilding the movement graph (Person 3)
- Rendering or visualizing anything (Person 5)
