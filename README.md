# FloorFlow — Insight Engine (Person 4)

Real-time situational awareness for emergency response. Watches movement graph snapshots from Person 3, detects developing congestion and anomalies, maintains live alert state, and writes insights for Person 5 to display.

**Spec:** [`FINAL_VISION.md`](FINAL_VISION.md) · **Architecture:** [`insight_engine/DESIGN.md`](insight_engine/DESIGN.md)

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

---

## For Person 5

Read `anomaly_reports/` each cycle. Each insight file has a global `summary` plus an `alerts[]` array. Severity values: `detecting`, `warning`, `critical`, `resolving`, `resolved`. Event stream (`events.ndjson`) carries lifecycle changes: `new`, `escalated`, `de_escalated`, `updated`, `resolved`.
