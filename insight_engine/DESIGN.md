# Insight Engine — Design Document

**Authoritative spec:** [`FINAL_VISION.md`](../FINAL_VISION.md) — this document describes how the code implements it. If they disagree, FINAL_VISION wins.

---

## Purpose

Stage 4 of FloorFlow. A **real-time situational awareness engine** that watches movement graph snapshots from Person 3, maintains live alert state, and writes operational insights for Person 5.

It does not produce static reports. It tracks developing situations across cycles and speaks in the language of emergency operations.

---

## Position in the Pipeline

```
Person 3 (Movement Graph)
        │
        │  movement_graphs/graph_<timestamp_ms>.json  (continuous)
        ▼
 insight_engine/              ← you are here
   engine.py       — watch loop, I/O
   detection.py    — signal extraction (stateless)
   alert_state.py  — lifecycle, hysteresis, memory
   narration.py    — message generation (LLM + templates)
        │
        │  anomaly_reports/insights_<ts>.json
        │  anomaly_reports/events.ndjson
        ▼
Person 5 (Visualization)
```

---

## Module Responsibilities

| Module | Role |
|---|---|
| `engine.py` | Polls `movement_graphs/`, orchestrates each cycle, writes outputs atomically |
| `detection.py` | Pure functions: accumulation, intra-trend, EWMA drift, structural change, cascade, convergence → per-zone urgency |
| `alert_state.py` | Alert lifecycle (`detecting → warning → critical → resolving → resolved`), hysteresis, pattern memory |
| `narration.py` | Turns signals into incident-commander messages; LLM primary, templates fallback |

Detection is side-effect-free. All cross-snapshot memory lives in `engine.py` (EWMA baselines, edge history) and `alert_state.py` (active alerts).

---

## Detection Signals

Each snapshot yields a signals dict consumed by the alert state manager.

### Per-zone urgency (`detection.py` → `compute_urgency`)

Combined score in `[0, 1]`:

| Component | Weight | Source |
|---|---|---|
| Accumulation | 50% | Inbound vs outbound ratio — people arriving faster than leaving |
| Intra-trend | 25% | Linear regression slope × R² over `time_windows` inbound series |
| EWMA deviation | 25% | Current inbound vs running baseline across snapshots |

Dwell time above median applies a multiplier (long stays under congestion = more urgent).

### Cross-zone signals

| Signal | Function | What it catches |
|---|---|---|
| Convergence | `compute_convergence` | Multiple high-traffic edges feeding one destination |
| Cascade risk | `compute_cascade_risk` | Warning upstream + warning downstream on connected path |
| Structural | `compute_structural_changes` | New edges, low-probability transitions, isolated zones |

### Insight type selection (`alert_state.py` → `_select_insight_type`)

One type per zone-level alert, by priority: `congestion_forecast` → `bottleneck_risk` → `high_dwell_zone` → `anomaly`.

Structural alerts (`unexpected_transition`, new-route `anomaly`, isolation) are raised separately from edge/convergence passes.

---

## Alert Lifecycle

Every alert moves through a severity ladder, not on/off:

```
detecting → warning → critical → resolving → resolved
```

Rules (`alert_state.py`):
- **New alerts always start at `detecting`** — severity is earned over cycles, not assigned from raw urgency
- **Escalation is one step at a time** — never jumps detecting → critical in one cycle
- **Hysteresis** — `CYCLES_TO_ESCALATE` / `CYCLES_TO_DEESCALATE` consecutive cycles before step change
- **Pattern memory** — zones that previously hit a severity escalate faster on re-entry
- **Resolution** — absent signals for N cycles → `resolving` → `resolved`; explicit `resolved` event emitted

Thresholds in `SEVERITY_THRESHOLDS` are tunable constants — calibrate against real Person 3 data during integration.

---

## Narration

`narration.py` generates one message per alert create/escalation/de-escalation/resolving transition.

- **Primary:** OpenAI-compatible API (configurable via env vars)
- **Fallback:** Templates written to incident-commander standard — time context, magnitude, recommendations; no statistical jargon

Set `NARRATION_BACKEND=disabled` to use templates only (recommended for demo reliability).

---

## Output Contract

See FINAL_VISION for full schema. Summary:

**Per cycle:** `anomaly_reports/insights_<timestamp_ms>.json`
- `summary` — global situation headline (`zone_id: "global"`)
- `alerts[]` — active alerts with `id`, `severity`, `message`, `confidence`, lifecycle timestamps

**Append-only:** `anomaly_reports/events.ndjson`
- Event types: `new`, `escalated`, `de_escalated`, `updated`, `resolved`

---

## Input Contract

Person 3 writes `movement_graphs/graph_<timestamp_ms>.json`. Each file is a complete graph snapshot including cumulative `time_windows`.

Engine reads `snapshot_ts` from filename first, then JSON field, then file mtime.

---

## Tuning

| Parameter | Location | Effect |
|---|---|---|
| `SEVERITY_THRESHOLDS` | `alert_state.py` | Urgency → detecting / warning / critical boundaries |
| `CYCLES_TO_ESCALATE` / `CYCLES_TO_DEESCALATE` | `alert_state.py` | Hysteresis strength |
| Urgency weights (50 / 25 / 25) | `detection.py` → `compute_urgency` | Accumulation vs trend vs EWMA |
| `EWMA_ALPHA` | `detection.py` | Cross-snapshot baseline responsiveness |
| Convergence / cascade cutoffs | `detection.py` | Cross-zone pattern sensitivity |
| `NARRATION_*` env vars | `narration.py` | LLM backend and model |

---

## Dependencies

**Use whatever produces the best product.** No arbitrary stdlib-only restriction.

Current stack:
- **Core:** Python 3.10+ stdlib — sufficient for current detection math and I/O
- **Optional:** `openai` — LLM narration (`requirements.txt`)

Add libraries when they meaningfully improve quality or reliability:
- `numpy` / `pandas` — richer time-series if snapshot history grows large
- `scikit-learn` — isolation forest or other anomaly models if heuristics prove insufficient
- `watchdog` — replace polling if filesystem latency becomes an issue

Evaluate each on merit at integration time, not upfront.

---

## Usage

```bash
# Demo (two terminals)
cd mock && python3 generate_mock_snapshots.py
python3 insight_engine/engine.py --graph-dir mock/movement_graphs --out-dir mock/anomaly_reports

# One-shot test
python3 insight_engine/engine.py --once path/to/graph.json --out-dir anomaly_reports

# Production (Person 3's output folder)
python3 insight_engine/engine.py --graph-dir ../movement_graphs --out-dir ../anomaly_reports

# 5-minute soak test
./mock/run_soak_test.sh
```

See [`mock/README.md`](../mock/README.md) for full run instructions and Person 5 handoff details.

---

## Integration Notes

These are open questions for Person 3 integration, not design constraints:

- Whether `time_windows` will include per-window `zone_stats` (would improve dwell-trend precision)
- Real traffic levels for threshold calibration
- Exact field names if their schema differs from mock

Fix mismatches in `detection.py` input parsing when real snapshots arrive. Do not degrade the product to match a weaker input — coordinate schema with Person 3 instead.
