"""
Mock snapshot generator — FloorFlow demo scenario.

Writes a sequence of 12 graph snapshots to movement_graphs/ and produces the
following sequence of alerts when the engine processes them:

  zone_2  — persistent 'high_dwell_zone' (medical staging area, 20 s average stay)
  zone_4  — 'anomaly' / 'unexpected_transition' at step 2 (new route discovered)
  zone_3  — 'congestion_forecast':
                cycle 2  → DETECTING (traffic starting to build)
                cycle 4  → WARNING   (trend confirmed)
                cycle 5  → WARNING   (surge: zone_4 joins as feeder)
                cycle 6  → CRITICAL  (convergence + sustained high accumulation)
                cycle 9  → RESOLVING (traffic drops sharply)
                cycle 11 → RESOLVED
  zone_3  — 'bottleneck_risk' from convergence at cycle 5
               (both zone_1 and zone_4 feeding zone_3 simultaneously)

Run this in one terminal, the engine in another:
  cd mock
  python3 generate_mock_snapshots.py
  python3 ../insight_engine/engine.py --graph-dir movement_graphs --out-dir anomaly_reports
"""

import argparse
import json
import time
from pathlib import Path

OUTPUT_DIR = Path(__file__).parent / "movement_graphs"
DEFAULT_INTERVAL_S = 3.0   # seconds between snapshots — adjust for demo pacing
DEFAULT_STEPS    = 12
WINDOW_MS        = 300_000  # 5-minute logical windows

# ---------------------------------------------------------------------------
# Traffic tables  (index = step number, 0-based)
# ---------------------------------------------------------------------------

# zone_1 → zone_3  (main inflow, grows then drops sharply during resolution)
Z1_TO_Z3  = [3,  5,  8,  12, 17, 24, 32, 38, 15,  8,  3,  0]

# zone_4 → zone_3  (secondary inflow; zone_4 appears at step 2, becomes major at step 4)
Z4_TO_Z3  = [0,  0,  0,  0,  10, 16, 20, 22,  8,  3,  0,  0]

# zone_4 → zone_1  (persistent unexpected route — low-probability, triggers anomaly)
Z4_TO_Z1  = [0,  0,  2,  2,  2,  2,  2,  2,  2,  2,  2,  0]

# zone_1 → zone_2  (steady intake into the medical staging / waiting area)
Z1_TO_Z2  = [10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10]


def _phase(step: int) -> int:
    """Loop traffic tables for soak tests longer than one demo cycle."""
    return step % len(Z1_TO_Z3)


def _at(table: list, step: int) -> int:
    return table[_phase(step)]


def _z3_outbound(step: int, total_inbound: int) -> int:
    """
    During congestion (steps 0-7) people are largely trapped — outflow is low.
    Resolution (steps 8+) is triggered by a rapid outflow surge.
    """
    p = _phase(step)
    if p >= 8:
        return max(total_inbound, 2)   # everyone leaving — net accumulation ≈ 0
    return max(total_inbound // 8, 1)  # trapped — 1 out for every 8 in


def _z3_dwell_ms(step: int) -> int:
    """Dwell grows as the zone fills up, plateaus at peak, drops during resolution."""
    p = _phase(step)
    if p <= 7:
        return 1_500 + p * 800      # 1.5 s → 7.1 s over 8 steps
    return max(7_100 - (p - 7) * 2_000, 1_500)


def make_snapshot(step: int, base_ts: int) -> dict:
    z4_active = step >= 2

    # --- Node list ---
    nodes = ["zone_1", "zone_2", "zone_3"]
    if z4_active:
        nodes.append("zone_4")

    # --- Edge list (snapshot-level: totals for this step) ---
    z3_total_in = _at(Z1_TO_Z3, step) + _at(Z4_TO_Z3, step)
    z3_out      = _z3_outbound(step, z3_total_in)

    edges = []

    # Main corridor → bottleneck
    z1_z3 = _at(Z1_TO_Z3, step)
    if z1_z3 > 0:
        edges.append({
            "from_zone_id":          "zone_1",
            "to_zone_id":            "zone_3",
            "transition_count":      z1_z3,
            "transition_probability": min(0.35 + _phase(step) * 0.04, 0.75),
        })

    # Bottleneck outflow (slow during congestion)
    if z3_out > 0:
        edges.append({
            "from_zone_id":          "zone_3",
            "to_zone_id":            "zone_1",
            "transition_count":      z3_out,
            "transition_probability": 0.15,
        })

    # Medical staging area intake (stable)
    edges.append({
        "from_zone_id":          "zone_1",
        "to_zone_id":            "zone_2",
        "transition_count":      _at(Z1_TO_Z2, step),
        "transition_probability": 0.28,
    })

    # Staging area slow discharge
    edges.append({
        "from_zone_id":          "zone_2",
        "to_zone_id":            "zone_1",
        "transition_count":      4,
        "transition_probability": 0.18,
    })

    if z4_active:
        # zone_4 → zone_1: unexpected low-probability route (persists — triggers anomaly)
        if _at(Z4_TO_Z1, step) > 0:
            edges.append({
                "from_zone_id":          "zone_4",
                "to_zone_id":            "zone_1",
                "transition_count":      _at(Z4_TO_Z1, step),
                "transition_probability": 0.03,   # < 0.05 → unexpected_transition
            })

        z4_z3 = _at(Z4_TO_Z3, step)
        if z4_z3 > 0:
            prob = 0.04 if _phase(step) == 3 else 0.20
            edges.append({
                "from_zone_id":          "zone_4",
                "to_zone_id":            "zone_3",
                "transition_count":      z4_z3,
                "transition_probability": prob,
            })

    # --- time_windows: last 3 steps' per-window edge data ---
    windows = []
    for w in range(max(0, step - 2), step + 1):
        w_z1_z3 = _at(Z1_TO_Z3, w)
        w_z4_z3 = _at(Z4_TO_Z3, w) if w >= 2 else 0
        w_edges = []
        if w_z1_z3 > 0:
            w_edges.append({
                "from_zone_id":          "zone_1",
                "to_zone_id":            "zone_3",
                "transition_count":      w_z1_z3,
                "transition_probability": min(0.35 + _phase(w) * 0.04, 0.75),
            })
        if w_z4_z3 > 0:
            w_edges.append({
                "from_zone_id":          "zone_4",
                "to_zone_id":            "zone_3",
                "transition_count":      w_z4_z3,
                "transition_probability": 0.04 if _phase(w) == 3 else 0.20,
            })
        windows.append({
            "window_start_ms": base_ts + w * WINDOW_MS,
            "window_end_ms":   base_ts + (w + 1) * WINDOW_MS,
            "window_graph": {
                "nodes": nodes,
                "edges": w_edges,
            },
        })

    # --- Zone stats ---
    zone_stats = {
        "zone_1": {
            "avg_dwell_ms": 3_000,
            "visit_count":  20 + step,
        },
        "zone_2": {
            "avg_dwell_ms": 20_000,   # medical staging — very high dwell → high_dwell_zone
            "visit_count":  12,
        },
        "zone_3": {
            "avg_dwell_ms": _z3_dwell_ms(step),
            "visit_count":  z3_total_in + 5,
        },
    }
    if z4_active:
        zone_stats["zone_4"] = {
            "avg_dwell_ms": 1_500,
            "visit_count":  3 + _at(Z4_TO_Z1, step) + _at(Z4_TO_Z3, step),
        }

    return {
        "snapshot_ts":  base_ts + step * WINDOW_MS,
        "nodes":        nodes,
        "edges":        [e for e in edges if e["transition_count"] > 0],
        "zone_stats":   zone_stats,
        "time_windows": windows,
    }


def main():
    parser = argparse.ArgumentParser(description="FloorFlow mock graph snapshot generator")
    parser.add_argument(
        "--steps", type=int, default=DEFAULT_STEPS,
        help=f"Number of snapshots to write (default: {DEFAULT_STEPS})",
    )
    parser.add_argument(
        "--interval", type=float, default=DEFAULT_INTERVAL_S,
        help=f"Seconds between snapshots (default: {DEFAULT_INTERVAL_S})",
    )
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    base_ts = int(time.time() * 1000)
    print(f"Writing {args.steps} snapshots to {OUTPUT_DIR}/")
    print(f"Interval: {args.interval}s per step  |  Ctrl-C to stop\n")

    for step in range(args.steps):
        snapshot = make_snapshot(step, base_ts)
        ts       = base_ts + step * WINDOW_MS
        path     = OUTPUT_DIR / f"graph_{ts}.json"
        path.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")

        z3_in  = _at(Z1_TO_Z3, step) + _at(Z4_TO_Z3, step)
        z3_out = _z3_outbound(step, z3_in)
        print(
            f"  step {step:2d}  →  {path.name}"
            f"   z3_in={z3_in:2d}  z3_out={z3_out:2d}"
            f"   z4={'active' if step >= 2 else 'absent'}"
        )

        if step < args.steps - 1:
            time.sleep(args.interval)

    print("\nSimulation complete.")


if __name__ == "__main__":
    main()
