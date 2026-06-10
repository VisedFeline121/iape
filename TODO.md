# Person 4 — Todo List

## Coordination
- [ ] Ask Person 3: "Will `time_windows` entries include per-window `zone_stats` (avg_dwell_ms + visit_count per zone)?"
- [ ] Confirm with Person 5 how they want to consume your output (file, stdin pipe, or direct import of `analyze()`)

## Development
- [ ] Generate `insight_engine.py` using AI_README.md as the prompt
- [ ] Generate `test_graph.json` — 4 zones, 3 time windows, zone_3 trending toward congestion
- [ ] Run `insight_engine.py` against `test_graph.json` and verify output is valid JSON
- [ ] Check that messages read naturally (not like log lines)
- [ ] Check that confidence values feel realistic (not all 0.0 or 1.0)
- [ ] Make sure all 5 insight types can be triggered by tweaking test data

## Integration
- [ ] Get real output from Person 3 and pipe it into your script
- [ ] Fix any schema mismatches
- [ ] Hand off `insights.json` (or confirm import interface) to Person 5

## Demo Polish
- [ ] Make sure at least one insight tells a clear story (e.g. a zone visibly trending toward congestion)
- [ ] Re-read all `message` strings — would a hospital operations manager understand them?
- [ ] Test the full pipe: `python3 graph_builder.py | python3 insight_engine.py`
