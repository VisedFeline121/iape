"""
Mock snapshot generator — simulates Person 3's continuous output.

Writes a sequence of realistic graph snapshots to movement_graphs/,
one file every N seconds, producing a scenario where:

  - zone_3 gradually develops a bottleneck (congestion_forecast → critical)
  - zone_4 shows up as an unexpected transition in snapshot 5
  - zone_2 goes quiet after snapshot 6 (isolation anomaly)
  - zone_1 has consistent high dwell throughout

Run this in one terminal, run engine.py in another:
  python3 generate_mock_snapshots.py
  python3 ../insight_engine/engine.py --graph-dir movement_graphs --out-dir anomaly_reports
"""

import json
import os
import time
from pathlib import Path

OUTPUT_DIR    = Path(__file__).parent / "movement_graphs"
INTERVAL_S    = 3.0
BASE_TS       = int(time.time() * 1000)
WINDOW_MS     = 300_000  # 5 minutes per window


def make_snapshot(step: int) -> dict:
    """
    Builds a realistic graph snapshot for the given simulation step.
    Zone 3 traffic escalates steps 0-7, then resolves steps 8+.
    """
    ts_start = BASE_TS + step * WINDOW_MS

    # Base traffic — zone 3 accumulates more and more
    z3_traffic = min(4 + step * 3, 28)  # grows 0→28, caps at step 8
    if step >= 8:
        z3_traffic = max(28 - (step - 8) * 6, 4)  # resolves after step 8

    # Zone 2 goes quiet after step 5
    z2_active = step < 6

    # Zone 4 appears unexpectedly at step 4
    z4_active = step >= 4

    nodes = ["zone_1", "zone_2", "zone_3"]
    if z4_active:
        nodes.append("zone_4")

    edges = [
        {
            "from_zone_id": "zone_1",
            "to_zone_id":   "zone_3",
            "transition_count":      z3_traffic,
            "transition_probability": min(0.50 + step * 0.04, 0.88),
        },
        {
            "from_zone_id": "zone_3",
            "to_zone_id":   "zone_1",
            "transition_count":      max(z3_traffic // 4, 1),
            "transition_probability": 0.20,
        },
        {
            "from_zone_id": "zone_1",
            "to_zone_id":   "zone_2",
            "transition_count":      8 if z2_active else 0,
            "transition_probability": 0.35 if z2_active else 0.0,
        },
    ]

    if z4_active:
        edges.append({
            "from_zone_id": "zone_4",
            "to_zone_id":   "zone_1",
            "transition_count":      2,
            "transition_probability": 0.03,   # unexpected
        })

    # Filter zero-count edges
    edges = [e for e in edges if e["transition_count"] > 0]

    # Build time_windows: last 3 steps worth of data
    windows = []
    for w in range(max(0, step - 2), step + 1):
        w_z3 = min(4 + w * 3, 28)
        if w >= 8:
            w_z3 = max(28 - (w - 8) * 6, 4)
        windows.append({
            "window_start_ms": BASE_TS + w * WINDOW_MS,
            "window_end_ms":   BASE_TS + (w + 1) * WINDOW_MS,
            "window_graph": {
                "nodes": ["zone_1", "zone_3"],
                "edges": [
                    {
                        "from_zone_id": "zone_1",
                        "to_zone_id":   "zone_3",
                        "transition_count":      w_z3,
                        "transition_probability": min(0.50 + w * 0.04, 0.88),
                    }
                ],
            },
        })

    zone_stats = {
        "zone_1": {
            "avg_dwell_ms": 8500,
            "visit_count":  20 + step,
        },
        "zone_2": {
            "avg_dwell_ms": 3200,
            "visit_count":  12 if z2_active else 0,
        },
        "zone_3": {
            "avg_dwell_ms": 4000 + step * 800,   # dwell grows with congestion
            "visit_count":  10 + z3_traffic,
        },
    }
    if z4_active:
        zone_stats["zone_4"] = {"avg_dwell_ms": 1800, "visit_count": 3}

    return {
        "nodes":        nodes,
        "edges":        edges,
        "zone_stats":   zone_stats,
        "time_windows": windows,
        "snapshot_ts":  ts_start,
    }


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Writing snapshots to {OUTPUT_DIR}  (Ctrl+C to stop)")

    for step in range(14):
        snapshot = make_snapshot(step)
        ts       = BASE_TS + step * WINDOW_MS
        filename = OUTPUT_DIR / f"graph_{ts}.json"
        filename.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
        print(f"  Wrote {filename.name}  (step {step}, z3_traffic={snapshot['edges'][0]['transition_count']})")
        time.sleep(INTERVAL_S)

    print("Simulation complete.")


if __name__ == "__main__":
    main()
