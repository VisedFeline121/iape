"""
Alert state manager — tracks the full lifecycle of every alert across snapshots.

Lifecycle:  DETECTING → WARNING → CRITICAL → RESOLVING → RESOLVED

Rules:
- Escalation requires crossing the threshold on N consecutive cycles (hysteresis up)
- De-escalation requires falling below the threshold on M consecutive cycles (hysteresis down)
- A zone that briefly recovers but then worsens again escalates faster (memory of pattern)
- RESOLVED alerts are emitted once, then removed from active state
"""

import time
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Severity ladder
# ---------------------------------------------------------------------------

SEVERITY_ORDER = ["detecting", "warning", "critical", "resolving", "resolved"]

# Tunable thresholds — calibrate against real data during integration testing
# These are starting points, not gospel
SEVERITY_THRESHOLDS = {
    "detecting": 0.20,
    "warning":   0.42,
    "critical":  0.68,
}

# Hysteresis: how many consecutive cycles before escalating / de-escalating
CYCLES_TO_ESCALATE   = 2  # must stay above threshold for this many cycles
CYCLES_TO_DEESCALATE = 3  # must stay below threshold for this many cycles


def urgency_to_target_severity(urgency: float) -> str:
    if urgency >= SEVERITY_THRESHOLDS["critical"]:
        return "critical"
    if urgency >= SEVERITY_THRESHOLDS["warning"]:
        return "warning"
    if urgency >= SEVERITY_THRESHOLDS["detecting"]:
        return "detecting"
    return "none"


# ---------------------------------------------------------------------------
# Alert data structure
# ---------------------------------------------------------------------------

@dataclass
class Alert:
    id:               str       # "{zone_id}__{insight_type}"
    zone_id:          str
    insight_type:     str
    severity:         str       # detecting / warning / critical / resolving / resolved
    confidence:       float
    message:          str
    first_seen_ts:    int        # unix ms
    last_updated_ts:  int
    cycle_count:      int        # cycles this alert has been active
    escalation_streak:  int = 0  # consecutive cycles above current threshold
    deescalation_streak: int = 0 # consecutive cycles below current threshold
    prior_max_severity: str = "detecting"  # memory: how bad has this gotten before
    supporting_data:  dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# State manager
# ---------------------------------------------------------------------------

class AlertStateManager:
    """
    Maintains all active alerts across cycles.
    Call update() with the signals from detection.py each cycle.
    Returns a list of events: new / escalated / de_escalated / updated / resolved.
    """

    def __init__(self):
        self.active_alerts: dict[str, Alert] = {}
        self.cycle: int = 0
        self.start_ts: int = _now_ms()

    def update(
        self,
        signals: dict,
        narrate_fn,         # callable(insight_type, zone_id, signals, alert) -> str
        snapshot_ts: int,
    ) -> tuple[list[dict], list[Alert]]:
        """
        Process one cycle of signals. Returns (events, current_active_alerts).
        """
        self.cycle += 1
        events: list[dict] = []

        zone_urgency  = signals.get("zone_urgency", {})
        structural    = signals.get("structural", {})
        cascades      = signals.get("cascades", [])
        convergence   = signals.get("convergence", [])
        accumulation  = signals.get("accumulation", {})
        intra_trend   = signals.get("intra_trend", {})
        ewma          = signals.get("ewma_deviations", {})
        zone_stats    = signals.get("zone_stats", {})

        # Build the set of (zone_id, insight_type) pairs that should be active
        # this cycle, with their urgency scores
        active_this_cycle: dict[str, float] = {}  # alert_id -> urgency

        # Zone-level alerts from urgency scores
        for zone_id, urgency in zone_urgency.items():
            itype = _select_insight_type(
                zone_id, urgency, signals
            )
            if itype and urgency >= SEVERITY_THRESHOLDS["detecting"]:
                alert_id = f"{zone_id}__{itype}"
                active_this_cycle[alert_id] = urgency

        # Structural alerts: unexpected transitions
        for edge in structural.get("unexpected_transitions", []):
            zone_id  = edge["to_zone_id"]
            alert_id = f"{zone_id}__unexpected_transition"
            conf     = _clamp(1.0 - edge["transition_probability"] * 15)
            active_this_cycle[alert_id] = conf

        # Structural alerts: new edges
        for edge in structural.get("new_edges", []):
            zone_id  = edge["to_zone_id"]
            alert_id = f"{zone_id}__anomaly"
            active_this_cycle.setdefault(alert_id, 0.65)

        # Structural alerts: isolated zones
        for iz in structural.get("isolated_zones", []):
            alert_id = f"{iz['zone_id']}__anomaly"
            urgency  = _clamp(iz["presence_ratio"])
            active_this_cycle[alert_id] = max(
                active_this_cycle.get(alert_id, 0.0), urgency
            )

        # Cascade alerts — attach to the downstream zone
        for cas in cascades:
            alert_id = f"{cas['to_zone']}__bottleneck_risk"
            urgency  = _clamp((cas["urgency_a"] + cas["urgency_b"]) / 2 * 1.2)
            active_this_cycle[alert_id] = max(
                active_this_cycle.get(alert_id, 0.0), urgency
            )

        # Convergence alerts
        for conv in convergence:
            alert_id = f"{conv['zone_id']}__bottleneck_risk"
            urgency  = _clamp(conv["current_urgency"] * 1.15)
            active_this_cycle[alert_id] = max(
                active_this_cycle.get(alert_id, 0.0), urgency
            )

        # --- Process each alert that should be active this cycle ---
        for alert_id, urgency in active_this_cycle.items():
            zone_id, itype = alert_id.split("__", 1)
            target_sev = urgency_to_target_severity(urgency)

            if alert_id not in self.active_alerts:
                # New alert
                message = narrate_fn(itype, zone_id, signals, None)
                alert = Alert(
                    id=alert_id,
                    zone_id=zone_id,
                    insight_type=itype,
                    severity=target_sev,
                    confidence=urgency,
                    message=message,
                    first_seen_ts=snapshot_ts,
                    last_updated_ts=snapshot_ts,
                    cycle_count=1,
                    supporting_data=_supporting_data(
                        zone_id, itype, signals
                    ),
                )
                self.active_alerts[alert_id] = alert
                events.append(_event("new", alert, snapshot_ts, self.cycle))

            else:
                alert = self.active_alerts[alert_id]
                alert.cycle_count += 1
                alert.last_updated_ts = snapshot_ts
                old_severity = alert.severity
                new_severity = _apply_hysteresis(alert, urgency, target_sev)

                alert.confidence = urgency
                alert.supporting_data = _supporting_data(
                    zone_id, itype, signals
                )

                if new_severity != old_severity:
                    # Severity changed — regenerate message
                    alert.severity = new_severity
                    alert.message  = narrate_fn(itype, zone_id, signals, alert)

                    if SEVERITY_ORDER.index(new_severity) > SEVERITY_ORDER.index(old_severity):
                        events.append(_event(
                            "escalated", alert, snapshot_ts, self.cycle,
                            from_severity=old_severity, to_severity=new_severity
                        ))
                    else:
                        events.append(_event(
                            "de_escalated", alert, snapshot_ts, self.cycle,
                            from_severity=old_severity, to_severity=new_severity
                        ))
                else:
                    events.append(_event("updated", alert, snapshot_ts, self.cycle))

        # --- Mark alerts absent this cycle as resolving / resolved ---
        to_remove = []
        for alert_id, alert in self.active_alerts.items():
            if alert_id in active_this_cycle:
                continue

            alert.deescalation_streak += 1
            if alert.deescalation_streak >= CYCLES_TO_DEESCALATE:
                to_remove.append(alert_id)
                alert.severity = "resolved"
                events.append(_event(
                    "resolved", alert, snapshot_ts, self.cycle
                ))
            elif alert.severity != "resolving":
                prev_severity  = alert.severity
                alert.severity = "resolving"
                events.append(_event(
                    "de_escalated", alert, snapshot_ts, self.cycle,
                    from_severity=prev_severity, to_severity="resolving"
                ))

        for alert_id in to_remove:
            del self.active_alerts[alert_id]

        return events, list(self.active_alerts.values())

    def elapsed_seconds(self) -> int:
        return int((_now_ms() - self.start_ts) / 1000)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_ms() -> int:
    return int(time.time() * 1000)


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def _apply_hysteresis(alert: Alert, urgency: float, target_sev: str) -> str:
    """
    Returns the new severity after applying hysteresis rules.
    Escalation requires CYCLES_TO_ESCALATE consecutive cycles above threshold.
    De-escalation requires CYCLES_TO_DEESCALATE consecutive cycles below threshold.
    A zone that previously hit a higher severity escalates faster on re-entry.
    """
    current_idx = SEVERITY_ORDER.index(alert.severity)
    target_idx  = SEVERITY_ORDER.index(target_sev) if target_sev in SEVERITY_ORDER else 0

    if target_idx > current_idx:
        # Trying to escalate
        alert.escalation_streak   += 1
        alert.deescalation_streak  = 0
        # Escalate faster if this zone has been here before
        needed = CYCLES_TO_ESCALATE
        if alert.prior_max_severity in SEVERITY_ORDER:
            prior_idx = SEVERITY_ORDER.index(alert.prior_max_severity)
            if prior_idx >= target_idx:
                needed = max(1, CYCLES_TO_ESCALATE - 1)
        if alert.escalation_streak >= needed:
            alert.prior_max_severity = max(
                alert.severity, target_sev,
                key=lambda s: SEVERITY_ORDER.index(s) if s in SEVERITY_ORDER else 0
            )
            return target_sev
    elif target_idx < current_idx:
        # Trying to de-escalate
        alert.deescalation_streak += 1
        alert.escalation_streak    = 0
        if alert.deescalation_streak >= CYCLES_TO_DEESCALATE:
            return target_sev
    else:
        alert.escalation_streak   = 0
        alert.deescalation_streak = 0

    return alert.severity


def _select_insight_type(
    zone_id: str,
    urgency: float,
    signals: dict,
) -> Optional[str]:
    """
    Returns the most specific insight type for a zone given its signals.
    Priority: congestion_forecast > bottleneck_risk > high_dwell_zone > anomaly
    """
    trend   = signals.get("intra_trend", {}).get(zone_id, {})
    acc     = signals.get("accumulation", {}).get(zone_id, {})
    stats   = signals.get("zone_stats", {}).get(zone_id, {})

    trend_score = trend.get("trend_score", 0.0)
    acc_ratio   = acc.get("accumulation_ratio", 0.0)
    dwell       = stats.get("avg_dwell_ms", 0)

    # Compute median dwell across all zones for comparison
    all_dwells  = [
        s.get("avg_dwell_ms", 0)
        for s in signals.get("zone_stats", {}).values()
        if s.get("avg_dwell_ms", 0) > 0
    ]
    median_dwell = sorted(all_dwells)[len(all_dwells) // 2] if all_dwells else 0

    if trend_score > 0.25 and urgency >= SEVERITY_THRESHOLDS["warning"]:
        return "congestion_forecast"
    if acc_ratio > 2.5 and urgency >= SEVERITY_THRESHOLDS["warning"]:
        return "bottleneck_risk"
    if median_dwell > 0 and dwell > median_dwell * 2.0:
        return "high_dwell_zone"
    if urgency >= SEVERITY_THRESHOLDS["detecting"]:
        return "anomaly"
    return None


def _supporting_data(zone_id: str, insight_type: str, signals: dict) -> dict:
    """Extracts the key numbers that back up this alert, for message generation."""
    return {
        "accumulation":   signals.get("accumulation", {}).get(zone_id, {}),
        "intra_trend":    signals.get("intra_trend",  {}).get(zone_id, {}),
        "ewma":           signals.get("ewma_deviations", {}).get(zone_id, {}),
        "zone_stats":     signals.get("zone_stats",   {}).get(zone_id, {}),
    }


def _event(
    event_type: str,
    alert: Alert,
    ts: int,
    cycle: int,
    from_severity: str = None,
    to_severity: str = None,
) -> dict:
    e = {
        "ts":       ts,
        "cycle":    cycle,
        "event":    event_type,
        "alert_id": alert.id,
        "insight":  _alert_to_dict(alert),
    }
    if from_severity:
        e["from_severity"] = from_severity
    if to_severity:
        e["to_severity"] = to_severity
    return e


def _alert_to_dict(alert: Alert) -> dict:
    return {
        "id":              alert.id,
        "zone_id":         alert.zone_id,
        "insight_type":    alert.insight_type,
        "severity":        alert.severity,
        "confidence":      round(alert.confidence, 3),
        "message":         alert.message,
        "first_seen_ts":   alert.first_seen_ts,
        "last_updated_ts": alert.last_updated_ts,
        "cycle_count":     alert.cycle_count,
    }
