# FloorFlow — Person 4: Insight, Anomaly & Prediction Engine

---

## AI Collaboration Standards (Read This First)

The goal is to **win** — not to ship the minimum viable anything.

- **Counsel first, implement on explicit request.** Propose approaches, surface tradeoffs, flag risks. Do not write code until the user says to.
- **Anchor on `FINAL_VISION.md`, not on the current code.** Before every decision, ask: does this get us closer to the demo moment described there?
- **"It's just a hackathon" is never a reason to cut corners.** The product is being built for incident commanders in active emergencies. Every decision should reflect that.
- **Highest-value decision at every turn.** When multiple approaches exist, recommend the one that makes the product most impressive, credible, and robust.
- **No made-up numbers without justification.** Thresholds, weights, and constants need a principled reason. If they need real data to validate, say so.
- **The demo cannot fail silently.** Empty output, crashes, or confidence scores that look wrong under real data are blockers.
- **Messages are what judges read.** Every `message` string must pass the incident commander read-aloud test — specific, time-aware, actionable, zero jargon.
- **Do not constrain the implementation** based on anything written in this file. The implementation spec lives in `FINAL_VISION.md`.

---

## Hackathon Context

**Technion CS Hackathon** ([cshack-technion.com](https://www.cshack-technion.com/))
Theme: **emergency response and crisis technology** — the "Golden Hour."
Partners: MADA (Israeli EMS), Lehava Unit, Airial Firefighting Unit.
Judges understand real operational contexts. They will recognize a shallow demo immediately.

---

## The Product

**FloorFlow** takes raw indoor wireless signals (UWB, BLE, Wi-Fi) from an unknown building with no floor plan and automatically discovers its operational structure — zones, movement patterns, bottlenecks, congestion.

The primary user is an **incident commander** who just walked into an unknown building — a burning structure, a disaster site, a mass-casualty scene — and needs to understand what is happening inside *right now*, with no prior map.

Person 4's insights are what appear on their screen.

---

## Pipeline

```
Person 1 → Person 2 → Person 3 → [Person 4] → Person 5
 Signal     Zone        Movement    Insight      Visualization
 Standard.  Discovery   Graph       Engine       & Demo
```

- **Person 1** — normalizes raw wireless signals into standard JSON records
- **Person 2** — clusters observations into discovered zones
- **Person 3** — builds a movement graph; continuously writes snapshots to `movement_graphs/`
- **Person 4 (YOU)** — watches `movement_graphs/`, detects anomalies, maintains live alert state, writes to `anomaly_reports/`
- **Person 5** — reads `anomaly_reports/`, visualizes the graph and alerts for the judges

---

## Authoritative Spec

Everything about what Person 4 builds — architecture, I/O contracts, alert lifecycle, detection logic, output format, dependencies, and definition of done — is in:

**[FINAL_VISION.md](./FINAL_VISION.md)**

That document is the single source of truth. This file does not override it.
