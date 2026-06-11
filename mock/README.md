# Mock Data & Demo — Person 4 (Insight Engine)

Simulates Person 3's output so you can run and demo the insight engine without the full pipeline.

---

## Quick demo (two terminals)

**Terminal 1 — generate movement graph snapshots:**
```bash
cd mock
python3 generate_mock_snapshots.py
```

**Terminal 2 — run the insight engine:**
```bash
python3 insight_engine/engine.py \
  --graph-dir mock/movement_graphs \
  --out-dir mock/anomaly_reports
```

Clear stale snapshots before a clean demo run:
```bash
rm -f mock/movement_graphs/*.json mock/anomaly_reports/insights_*.json mock/anomaly_reports/events.ndjson
```

---

## What the mock scenario shows

| Story | Alert | Arc |
|---|---|---|
| **A — Congestion** | `zone_3__congestion_forecast` | detecting → warning → critical → resolving → resolved |
| **B — New route** | `zone_1__unexpected_transition` | Overlaps with Story A from step 3 (Sector 4 → Sector 1) |
| Background | `zone_2__high_dwell_zone` | Persistent medical-staging area (high dwell) |

Default run: **12 snapshots**, one every **3 seconds** (~36 s total).

---

## Generator options

```bash
python3 generate_mock_snapshots.py --steps 12 --interval 3   # demo (default)
python3 generate_mock_snapshots.py --steps 100 --interval 3  # 5-minute soak test
```

Traffic tables loop after 12 steps for long runs.

---

## 5-minute soak test

Runs generator + engine together for stability checking:

```bash
./mock/run_soak_test.sh
```

Or manually:
```bash
rm -f mock/movement_graphs/*.json mock/anomaly_reports/*
NARRATION_BACKEND=disabled python3 insight_engine/engine.py \
  --graph-dir mock/movement_graphs --out-dir mock/anomaly_reports --interval 1 &
python3 mock/generate_mock_snapshots.py --steps 100 --interval 3
```

---

## Output (for Person 5)

The engine writes to `mock/anomaly_reports/` (or `../anomaly_reports/` in production):

| File | Contents |
|---|---|
| `insights_<timestamp_ms>.json` | Per-cycle snapshot: `summary`, `alerts[]`, `cycle`, `elapsed_seconds` |
| `events.ndjson` | Append-only event stream: `new`, `escalated`, `de_escalated`, `updated`, `resolved` |

**Alert fields:** `id`, `zone_id`, `insight_type`, `severity`, `message`, `confidence`, `first_seen_ts`, `last_updated_ts`, `cycle_count`

**Severity values:** `detecting`, `warning`, `critical`, `resolving`, `resolved`

**Insight types:** `congestion_forecast`, `bottleneck_risk`, `high_dwell_zone`, `anomaly`, `unexpected_transition`

---

## One-shot test (single file)

```bash
python3 insight_engine/engine.py \
  --once mock/movement_graphs/graph_<timestamp_ms>.json \
  --out-dir mock/anomaly_reports
```

---

## Environment

```bash
# Use template messages only (no API key needed — recommended for demo)
export NARRATION_BACKEND=disabled

# Optional LLM narration
export OPENAI_API_KEY=sk-...
export NARRATION_MODEL=gpt-4o-mini
```

Install optional deps: `pip install -r requirements.txt`
