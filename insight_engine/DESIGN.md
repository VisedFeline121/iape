# Insight Engine — Design Document

## Purpose

This component is Stage 4 of the FloorFlow pipeline. It receives a movement graph
from Person 3 and produces a ranked list of operational insights: bottlenecks,
anomalies, and congestion forecasts. Its output is consumed by Person 5's visualization.

---

## Position in the Pipeline

```
Person 3 (Movement Graph)
        │
        │  graph summary JSON
        ▼
 insight_engine.py          ← you are here
        │
        │  insights array JSON
        ▼
Person 5 (Visualization)
```

---

## Core Design Principle: Urgency = Severity × Rate of Change

A zone that has always been slow is less actionable than a zone that is rapidly
getting worse. The scoring model reflects this:

```
urgency = severity × (1 + trend_amplifier)
```

Where:
- **severity** — how bad the zone currently is (blend of dwell, traffic, visits)
- **trend_amplifier** — how fast it is getting worse (linear regression slope over windows)

A stable-bad zone gets a moderate urgency score.
A worsening zone gets the same severity score amplified by its growth rate.

---

## Scoring Model

### Severity (per zone)

| Component | Weight | Source | What it measures |
|---|---|---|---|
| Dwell z-score | 35% | `zone_stats.avg_dwell_ms` | How long people stay vs. average |
| Traffic z-score | 50% | Sum of `edge.transition_count` into zone | How much inbound flow vs. average |
| Relative visits | 15% | `zone_stats.visit_count` | How frequently the zone is used |

All components are normalized to [0, 1] before weighting.
Z-scores are divided by 3 before clamping (treating ±3σ as the practical extremes).

### Trend Slope

Computed via least-squares linear regression over inbound traffic counts across
all `time_windows`, in order. The raw slope is normalized by mean traffic to make
it scale-free (so a slope of 2 means the same thing regardless of absolute volume).

```
trend_slope = linear_slope(inbound_per_window) / (mean_traffic + 1)
             clamped to [-1.0, 1.0]
```

Only positive slopes amplify urgency. Zones with declining or flat traffic are
not penalized — they may be resolved issues.

### Urgency

```
urgency = clamp(severity × (1.0 + max(trend_slope, 0) × 1.5))
```

The `1.5` multiplier means a zone with maximum positive slope nearly doubles
its urgency score. Tunable in `_score_zones()`.

---

## Insight Type Selection

One insight type is emitted per zone, chosen by priority:

```
1. congestion_forecast  — trend > 0.3 AND urgency > 0.5  (actively worsening)
2. bottleneck_risk      — traffic_z > 0.6 AND urgency > 0.4  (heavy convergence)
3. high_dwell_zone      — dwell_z > 0.6  (people stuck here)
4. congestion_forecast  — trend > 0.2  (growing, even if not yet severe)
5. anomaly              — fallback for anything else above the urgency threshold
```

This avoids emitting three overlapping alerts for the same zone about the same
underlying problem.

---

## Edge-Level Anomalies

Handled in a separate pass (`_edge_anomalies`) after zone scoring, to avoid
contaminating the zone urgency model with edge-specific signals.

Two detections:

1. **Unexpected transition** — a global edge with `transition_probability < 0.05`
   that fired at least once. Confidence = `1 - (probability × 15)`.

2. **Structural anomaly** — an edge that appears in the latest `time_window`
   but was absent from all earlier windows. Fixed confidence of 0.70.

Double-reporting is suppressed: if a zone already has an `unexpected_transition`
insight from zone scoring, the edge pass skips it.

---

## Output

A JSON array sorted by `confidence` descending, deduplicated by `(zone_id, insight_type)`.

```json
[
  {
    "zone_id": "zone_3",
    "insight_type": "congestion_forecast",
    "message": "Zone 3 traffic has grown 2.8× over the last 15 minutes and is still rising — congestion is forecast if the trend continues.",
    "confidence": 0.81
  }
]
```

### Allowed `insight_type` values

| Value | Meaning |
|---|---|
| `bottleneck_risk` | Zone is a high-traffic convergence point with long dwell |
| `anomaly` | Unexpected structural or behavioral change |
| `high_dwell_zone` | Zone has unusually long average dwell time |
| `unexpected_transition` | A rare or new movement path was observed |
| `congestion_forecast` | Zone traffic is trending upward — congestion predicted |

---

## Tuning

| Parameter | Location | Effect |
|---|---|---|
| `URGENCY_THRESHOLD` | module-level constant | Minimum urgency to emit an insight. Raise to reduce noise. |
| Severity weights (0.35 / 0.50 / 0.15) | `_score_zones()` | Relative importance of dwell vs traffic vs visits |
| Trend amplifier (1.5) | `_score_zones()` | How much a rising trend boosts urgency |
| Insight type thresholds | `_select_insight_type()` | When each type is triggered |
| Edge probability cutoff (0.05) | `_edge_anomalies()` | What counts as an "unexpected" transition |

---

## Open Assumptions

| # | Assumption | Impact if wrong | Resolution |
|---|---|---|---|
| 1 | `time_windows` do not include per-window `zone_stats` | Trend analysis uses edge counts instead of dwell trends — less precise | Extend `_per_window_inbound()` to return dwell series if Person 3 adds it |
| 2 | Input is a single graph snapshot, not a stream | No statefulness needed | If Person 3 emits rolling updates, wrap `analyze()` in a polling loop |

---

## Usage

```bash
# From stdin / stdout (pipe)
python3 insight_engine.py < graph.json > insights.json

# From files
python3 insight_engine.py --in graph.json --out insights.json

# As a Python module
from insight_engine import analyze
insights = analyze(graph_dict)
```

---

## Dependencies

None beyond Python 3.10+ stdlib (`json`, `statistics`, `argparse`, `collections`).
