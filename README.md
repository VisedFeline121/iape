# FloorFlow — Insight Engine (Person 4)

Real-time situational awareness for emergency response. Watches movement graph snapshots from Person 3, detects developing congestion and anomalies, maintains live alert state, and writes insights for Person 5 to display.

**Spec:** [`FINAL_VISION.md`](FINAL_VISION.md) · **Architecture:** [`insight_engine/DESIGN.md`](insight_engine/DESIGN.md)

---

## Integration

### For Person 3 — your output is my input

**Write to:** `movement_graphs/graph_<timestamp_ms>.json`

- One **new file per snapshot** — do not overwrite previous files
- Each file is a **complete graph at that moment**, including all `time_windows` observed so far
- `<timestamp_ms>` should match the snapshot's logical time (engine reads it from the filename)
- Engine polls every **2 seconds** by default; any write cadence ≥2s is fine

**Required JSON shape:**

```json
{
  "snapshot_ts": 1718045312000,
  "nodes": ["zone_1", "zone_2", "zone_3"],
  "edges": [
    {
      "from_zone_id": "zone_1",
      "to_zone_id": "zone_3",
      "transition_count": 12,
      "transition_probability": 0.55
    }
  ],
  "zone_stats": {
    "zone_3": { "avg_dwell_ms": 7100, "visit_count": 18 }
  },
  "time_windows": [
    {
      "window_start_ms": 1718045000000,
      "window_end_ms": 1718045300000,
      "window_graph": {
        "nodes": ["zone_1", "zone_3"],
        "edges": [
          {
            "from_zone_id": "zone_1",
            "to_zone_id": "zone_3",
            "transition_count": 8,
            "transition_probability": 0.50
          }
        ]
      }
    }
  ]
}
```

| Field | Required | Notes |
|---|---|---|
| `nodes` | yes | Zone IDs used across the session (`zone_1`, `zone_2`, …) |
| `edges` | yes | Global edge totals; can be `[]` if no movement yet |
| `zone_stats` | yes | Per-zone `avg_dwell_ms` and `visit_count` |
| `time_windows` | yes | Ordered history of per-window graphs; can be `[]` on first snapshot |
| `snapshot_ts` | recommended | Fallback if filename timestamp is unavailable |

**Reference file:** run `cd mock && python3 generate_mock_snapshots.py` once, then inspect any file in `mock/movement_graphs/`.

**Open question for integration:** per-window `zone_stats` inside each `time_windows` entry are not required today, but would improve dwell-trend detection. Confirm with Person 4 if you add them.

**Wire-up:**
```bash
# Person 3 writes to ../movement_graphs/ (or a shared folder)
# Person 4 reads from the same path:
python3 insight_engine/engine.py --graph-dir /shared/movement_graphs --out-dir /shared/anomaly_reports
```

---

### For Person 5 — my output is your input

**Read from:** `anomaly_reports/`

| File | Purpose |
|---|---|
| `insights_<timestamp_ms>.json` | **Dashboard state** — poll for the newest file each cycle |
| `events.ndjson` | **Lifecycle feed** — tail/append-read for animations and transitions |

**Consumption model:**

1. **Headline + alert list** → parse the latest `insights_*.json` (highest `snapshot_ts` or newest mtime)
2. **Escalations, new alerts, resolutions** → read new lines from `events.ndjson`
3. **On `event: "resolved"`** → remove or grey out that `alert_id` from the UI

**Per-cycle snapshot (`insights_*.json`):**

```json
{
  "snapshot_ts": 1718045312000,
  "cycle": 7,
  "elapsed_seconds": 420,
  "summary": {
    "zone_id": "global",
    "insight_type": "situation_summary",
    "severity": "warning",
    "message": "3 active alerts across 4 observed sectors. One critical situation developing in Sector 3.",
    "confidence": 1.0
  },
  "alerts": [
    {
      "id": "zone_3__congestion_forecast",
      "zone_id": "zone_3",
      "insight_type": "congestion_forecast",
      "severity": "critical",
      "message": "Sector 3 congestion confirmed over the last 20 minutes. 52 movements in against only 6 out — traffic is stacking up. Immediate intervention required.",
      "confidence": 0.87,
      "first_seen_ts": 1718045100000,
      "last_updated_ts": 1718045312000,
      "cycle_count": 4
    }
  ]
}
```

**Event line (`events.ndjson`):**

```json
{"ts": 1718045312000, "cycle": 7, "event": "escalated", "alert_id": "zone_3__congestion_forecast", "from_severity": "warning", "to_severity": "critical", "insight": { ... }}
```

Event types: `new`, `escalated`, `de_escalated`, `updated`, `resolved`

**Severity values:** `detecting`, `warning`, `critical`, `resolving`, `resolved`

Suggested UI mapping:

| Severity | Display |
|---|---|
| `detecting` | Info / muted — pattern emerging |
| `warning` | Yellow — attention required |
| `critical` | Red — immediate action |
| `resolving` | Blue/grey — improving, keep visible |
| `resolved` | Remove from active list (event only) |

**Insight types:** `congestion_forecast`, `bottleneck_risk`, `high_dwell_zone`, `anomaly`, `unexpected_transition`

**Zone labels:** messages use `Sector N` (from `zone_N`). Highlight `zone_id` on the graph.

**Wire-up:** point your file watcher or poll loop at the same `anomaly_reports/` folder Person 4 writes to.

---

## Quick start (mock demo)

**Terminal 1**
```bash
cd mock && python3 generate_mock_snapshots.py
```

**Terminal 2**
```bash
export NARRATION_BACKEND=disabled   # templates only — no API key needed
python3 insight_engine/engine.py \
  --graph-dir mock/movement_graphs \
  --out-dir mock/anomaly_reports
```

More detail: [`mock/README.md`](mock/README.md)

---

## Production wiring

| Direction | Path |
|---|---|
| **Input** (Person 3) | `movement_graphs/graph_<timestamp_ms>.json` |
| **Output** (Person 5) | `anomaly_reports/insights_<timestamp_ms>.json` + `anomaly_reports/events.ndjson` |

```bash
python3 insight_engine/engine.py \
  --graph-dir /path/to/movement_graphs \
  --out-dir /path/to/anomaly_reports
```

---

## Layout

```
insight_engine/
  engine.py        — watch loop, I/O
  detection.py     — signal extraction
  alert_state.py   — alert lifecycle
  narration.py     — message generation
mock/              — demo snapshot generator + soak test
```

---

## Setup

Python 3.10+. Core engine uses stdlib only.

```bash
pip install -r requirements.txt   # optional: openai for LLM narration
```

Full output field reference: [`mock/README.md`](mock/README.md)
