# Mock Data — Person 4 (Insight Engine)

## Files

| File | Description |
|---|---|
| `input_graph.json` | Sample output from Person 3 — feed this into `insight_engine.py` |
| `output_insights.json` | Expected output from `insight_engine.py` — feed this to Person 5 |

## The Story in This Mock

- **Zone 3** is a high-traffic waiting area (triage / reception analogue)
  - Receives the most inbound transitions (32 total)
  - Has the longest dwell time (14s average)
  - Traffic into it is growing across all 3 time windows → congestion forecast
- **Zone 4 → Zone 1** is a rare, unexpected path that only appeared in the last window → anomaly + unexpected transition

## Usage

```bash
# Run the engine against this input
python3 insight_engine.py --in mock/input_graph.json

# Or write output to file
python3 insight_engine.py --in mock/input_graph.json --out mock/output_insights.json
```

## For Person 5

Your input is `output_insights.json`. Each object has:
- `zone_id` — which zone to highlight
- `insight_type` — one of: `bottleneck_risk`, `congestion_forecast`, `high_dwell_zone`, `anomaly`, `unexpected_transition`
- `confidence` — 0.0 to 1.0, use for visual intensity (color, size, opacity)
- `message` — human-readable string to display on screen
