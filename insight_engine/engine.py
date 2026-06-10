"""
FloorFlow — Insight, Anomaly & Prediction Engine
Main entry point.

Watches movement_graphs/ for new snapshot files from Person 3.
On each new file: runs detection, updates alert state, writes outputs to anomaly_reports/.

Usage:
  python3 engine.py                              # watch with defaults
  python3 engine.py --graph-dir ../movement_graphs --out-dir ../anomaly_reports
  python3 engine.py --interval 2                 # poll every 2 seconds
  python3 engine.py --once graph.json            # one-shot mode for testing
"""

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

from detection   import analyze_snapshot
from alert_state import AlertStateManager, _alert_to_dict
from narration   import generate_message

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stderr,
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# File naming — change INPUT_GLOB if Person 3 uses a different pattern
# ---------------------------------------------------------------------------

INPUT_GLOB       = "*.json"           # matches any JSON file in movement_graphs/
OUTPUT_SNAPSHOT  = "insights_{ts}.json"
OUTPUT_EVENTS    = "events.ndjson"


# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------

def _write_snapshot(out_dir: Path, alerts: list, events: list, state: AlertStateManager, snapshot_ts: int):
    critical = sum(1 for a in alerts if a.severity == "critical")
    warning  = sum(1 for a in alerts if a.severity == "warning")
    total    = len(alerts)

    if critical:
        summary_sev = "critical"
    elif warning:
        summary_sev = "warning"
    elif total:
        summary_sev = "detecting"
    else:
        summary_sev = "info"

    if total:
        worst = max(alerts, key=lambda a: a.confidence)
        summary_msg = (
            f"{total} active alert{'s' if total != 1 else ''} across the monitored area. "
            f"{'One critical situation' if critical else 'One developing situation'} "
            f"in {worst.zone_id.replace('zone_', 'Sector ')}. "
            f"System running for {state.elapsed_seconds()}s across {state.cycle} snapshots."
        )
    else:
        summary_msg = (
            f"No active alerts. System nominal. "
            f"Running for {state.elapsed_seconds()}s across {state.cycle} snapshots."
        )

    payload = {
        "snapshot_ts":     snapshot_ts,
        "cycle":           state.cycle,
        "elapsed_seconds": state.elapsed_seconds(),
        "summary": {
            "zone_id":      "global",
            "insight_type": "situation_summary",
            "severity":     summary_sev,
            "message":      summary_msg,
            "confidence":   1.0,
        },
        "alerts": [_alert_to_dict(a) for a in alerts],
    }

    filename = out_dir / OUTPUT_SNAPSHOT.format(ts=snapshot_ts)
    _atomic_write(filename, json.dumps(payload, indent=2))
    logger.info(f"Wrote {filename.name} — {total} alerts ({critical} critical, {warning} warning)")


def _append_events(out_dir: Path, events: list):
    if not events:
        return
    events_file = out_dir / OUTPUT_EVENTS
    lines = "\n".join(json.dumps(e, separators=(",", ":")) for e in events) + "\n"
    with open(events_file, "a") as f:
        f.write(lines)


def _atomic_write(path: Path, content: str):
    """Write to a temp file then rename — prevents Person 5 reading a partial file."""
    tmp = path.with_suffix(".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


# ---------------------------------------------------------------------------
# Directory watcher
# ---------------------------------------------------------------------------

class DirectoryWatcher:
    """
    Watches a directory for new JSON files. Yields each new file path in
    chronological order (by mtime). Does not re-process already-seen files.
    """

    def __init__(self, watch_dir: Path):
        self.watch_dir = watch_dir
        self._seen: set[str] = set()

    def poll(self) -> list[Path]:
        """Returns newly appeared files since last call, sorted by mtime."""
        try:
            files = sorted(
                self.watch_dir.glob(INPUT_GLOB),
                key=lambda p: p.stat().st_mtime,
            )
        except OSError:
            return []

        new_files = [f for f in files if f.name not in self._seen]
        for f in new_files:
            self._seen.add(f.name)
        return new_files


# ---------------------------------------------------------------------------
# Core processing loop
# ---------------------------------------------------------------------------

def process_snapshot(
    snapshot: dict,
    state_manager: AlertStateManager,
    engine_state: dict,
    out_dir: Path,
    snapshot_ts: int,
):
    signals = analyze_snapshot(
        snapshot=snapshot,
        ewma_state=engine_state["ewma"],
        edge_history=engine_state["edge_history"],
        zone_history=engine_state["zone_history"],
        total_prior_snapshots=engine_state["total_snapshots"],
    )
    engine_state["total_snapshots"] += 1

    events, active_alerts = state_manager.update(
        signals=signals,
        narrate_fn=generate_message,
        snapshot_ts=snapshot_ts,
    )

    _write_snapshot(out_dir, active_alerts, events, state_manager, snapshot_ts)
    _append_events(out_dir, events)

    for ev in events:
        sev = ev.get("insight", {}).get("severity", "")
        logger.info(
            f"  [{ev['event'].upper():12}] {ev['alert_id']}  severity={sev}"
        )


def run_watch(graph_dir: Path, out_dir: Path, interval: float):
    out_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"Watching {graph_dir}  →  {out_dir}  (poll every {interval}s)")

    watcher       = DirectoryWatcher(graph_dir)
    state_manager = AlertStateManager()
    engine_state  = {
        "ewma":             {},
        "edge_history":     set(),
        "zone_history":     {},
        "total_snapshots":  0,
    }

    while True:
        new_files = watcher.poll()
        for path in new_files:
            try:
                snapshot = json.loads(path.read_text(encoding="utf-8"))
                snapshot_ts = int(path.stat().st_mtime * 1000)
                logger.info(f"Processing {path.name}")
                process_snapshot(snapshot, state_manager, engine_state, out_dir, snapshot_ts)
            except Exception as e:
                logger.error(f"Failed to process {path.name}: {e}")

        time.sleep(interval)


def run_once(graph_path: Path, out_dir: Path):
    """One-shot mode — process a single file and exit. Useful for testing."""
    out_dir.mkdir(parents=True, exist_ok=True)
    snapshot    = json.loads(graph_path.read_text(encoding="utf-8"))
    snapshot_ts = int(time.time() * 1000)
    state_manager = AlertStateManager()
    engine_state  = {
        "ewma":            {},
        "edge_history":    set(),
        "zone_history":    {},
        "total_snapshots": 0,
    }
    process_snapshot(snapshot, state_manager, engine_state, out_dir, snapshot_ts)
    logger.info("Done.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="FloorFlow — Insight, Anomaly & Prediction Engine"
    )
    parser.add_argument(
        "--graph-dir", default="../movement_graphs",
        help="Directory to watch for graph snapshots from Person 3 (default: ../movement_graphs)",
    )
    parser.add_argument(
        "--out-dir", default="../anomaly_reports",
        help="Directory to write insights and events to (default: ../anomaly_reports)",
    )
    parser.add_argument(
        "--interval", type=float, default=2.0,
        help="Polling interval in seconds (default: 2.0)",
    )
    parser.add_argument(
        "--once", metavar="FILE",
        help="Process a single graph file and exit (for testing)",
    )
    args = parser.parse_args()

    graph_dir = Path(args.graph_dir)
    out_dir   = Path(args.out_dir)

    if args.once:
        run_once(Path(args.once), out_dir)
    else:
        if not graph_dir.exists():
            logger.warning(f"graph-dir {graph_dir} does not exist yet — will keep checking")
        try:
            run_watch(graph_dir, out_dir, args.interval)
        except KeyboardInterrupt:
            logger.info("Stopped.")


if __name__ == "__main__":
    main()
