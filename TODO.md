# Person 4 — Todo List

Anchor: `FINAL_VISION.md` · Target: **16 hours** · Scope: **your engine only** (input: `movement_graphs/` → output: `anomaly_reports/`)

---

## Done

- [x] Core engine — `insight_engine/engine.py` watches `movement_graphs/`, writes `anomaly_reports/`
- [x] Detection — accumulation, intra-trend, EWMA, structural change, cascade, convergence
- [x] Alert lifecycle — `alert_state.py` with hysteresis and pattern memory
- [x] Narration — LLM path + template fallback (`narration.py`)
- [x] Output contract — `insights_<ts>.json` + `events.ndjson`
- [x] Mock generator — `mock/generate_mock_snapshots.py`
- [x] Lifecycle pacing — detecting → warning → critical, one step at a time
- [x] Urgency weights — 50% accumulation / 25% trend / 25% EWMA
- [x] `snapshot_ts` from filename
- [x] All 5 insight types triggerable on mock
- [x] Resolution events fire when conditions improve
- [x] Cross-zone convergence fires on mock

---

## Must — demo-ready (~11–13h)

These are the only items that block a credible judge demo.

- [x] **Tune mock scenario** — Story A + Story B overlap on clean 12-snapshot run
- [x] **Verify lifecycle in output** — all 5 event types; `resolving` before `resolved`
- [x] **Polish template messages** — read-aloud pass on every fallback in `narration.py`; remove jargon; time context, magnitude, and recommendations by severity
- [x] **Edge cases** — empty graph, single zone, missing `time_windows` do not crash
- [x] **5-minute continuous run** — 100 snapshots × 3s, 99 insight files, 352 events, no crashes
- [x] **Run instructions** — `mock/README.md` updated; `requirements.txt` added; `mock/run_soak_test.sh`

**Demo command:**
```bash
# Terminal 1
cd mock && python3 generate_mock_snapshots.py

# Terminal 2
python3 insight_engine/engine.py --graph-dir mock/movement_graphs --out-dir mock/anomaly_reports
```

---

## Should — if time remains (~3–5h)

Improve depth; not required for a working demo.

- [ ] **System summary accuracy** — counts and worst-sector callout match active alerts each cycle
- [ ] **Cross-zone patterns on mock** — confirm isolation, overflow/rerouting, and cascade risk fire (convergence already done)
- [ ] **Faster re-escalation** — verify in `events.ndjson` that a zone re-worsening after a dip escalates in fewer cycles
- [ ] **Startup backlog** — engine processes files already sitting in `movement_graphs/` when it starts
- [ ] **Real graph folder** — point engine at Person 3's output path; fix schema mismatches in `detection.py` / input parsing
- [ ] **Threshold pass** — tune `SEVERITY_THRESHOLDS` in `alert_state.py` once real snapshots are available

---

## Cut — skip for hackathon

Do not spend 16-hour budget here.

- LLM narration setup (templates are enough unless API key is already working)
- All four cross-zone patterns as separate on-screen demo beats
- 10-minute soak test (5 minutes is sufficient)
- `numpy` / `scipy` / `watchdog` unless a concrete bug forces it

---

## When Person 3 drops real snapshots

Person 4 actions only — no waiting on other roles.

- [ ] Point `--graph-dir` at their folder and run one full cycle
- [ ] Fix any field-name or shape mismatches
- [ ] Recalibrate thresholds against real traffic levels

---

## FINAL_VISION — Person 4 checklist

| Requirement | Status |
|---|---|
| Alert lifecycle end-to-end | Done (mock) |
| All 5 insight types triggerable | Done |
| Cross-zone convergence | Done |
| Isolation / overflow / cascade | Should |
| Messages pass read-aloud test | Done (templates) |
| System summary every cycle | Done |
| Summary accurate | Should |
| Output files every cycle, no crashes | Done (5-min soak) |
| Edge cases graceful | Done |
| Resolution events | Done |
