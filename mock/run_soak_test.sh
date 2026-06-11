#!/usr/bin/env bash
# 5-minute continuous run: mock generator + insight engine together.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STEPS="${1:-100}"
INTERVAL="${2:-3}"

echo "Soak test: ${STEPS} steps × ${INTERVAL}s ≈ $(( STEPS * INTERVAL / 60 )) min"

rm -f "$ROOT/mock/movement_graphs/"*.json
rm -f "$ROOT/mock/anomaly_reports/insights_"*.json
rm -f "$ROOT/mock/anomaly_reports/events.ndjson"

export NARRATION_BACKEND=disabled

python3 "$ROOT/insight_engine/engine.py" \
  --graph-dir "$ROOT/mock/movement_graphs" \
  --out-dir "$ROOT/mock/anomaly_reports" \
  --interval 1 &
ENGINE_PID=$!

cleanup() {
  kill "$ENGINE_PID" 2>/dev/null || true
  wait "$ENGINE_PID" 2>/dev/null || true
}
trap cleanup EXIT

sleep 1

python3 "$ROOT/mock/generate_mock_snapshots.py" --steps "$STEPS" --interval "$INTERVAL"

INSIGHTS=$(ls -1 "$ROOT/mock/anomaly_reports/insights_"*.json 2>/dev/null | wc -l)
EVENTS=$(wc -l < "$ROOT/mock/anomaly_reports/events.ndjson" 2>/dev/null || echo 0)

echo ""
echo "Soak complete."
echo "  Insight files written: $INSIGHTS"
echo "  Event lines appended:  $EVENTS"

if [[ "$INSIGHTS" -lt "$(( STEPS - 2 ))" ]]; then
  echo "  WARNING: expected ~${STEPS} insight files — check engine logs"
  exit 1
fi
