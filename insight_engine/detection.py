"""
Detection engine — pure functions that extract signals from a graph snapshot.

Each function returns a dict of per-zone or per-edge signals.
Nothing here touches state, filesystem, or LLM — all side-effect-free.
"""

from collections import defaultdict


# ---------------------------------------------------------------------------
# Internal math helpers
# ---------------------------------------------------------------------------

def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def _linear_regression(ys: list[float]) -> tuple[float, float]:
    """
    Returns (slope, r_squared) for equally-spaced y values.
    slope > 0 means rising. r_squared near 1 means clean trend.
    """
    n = len(ys)
    if n < 2:
        return 0.0, 0.0

    xs = list(range(n))
    x_mean = sum(xs) / n
    y_mean = sum(ys) / n

    ss_xy = sum((xs[i] - x_mean) * (ys[i] - y_mean) for i in range(n))
    ss_xx = sum((xs[i] - x_mean) ** 2 for i in range(n))
    ss_yy = sum((ys[i] - y_mean) ** 2 for i in range(n))

    if ss_xx == 0:
        return 0.0, 0.0

    slope = ss_xy / ss_xx
    r_squared = (ss_xy ** 2) / (ss_xx * ss_yy) if ss_yy > 0 else 0.0
    return slope, _clamp(r_squared)


# ---------------------------------------------------------------------------
# Signal 1: Accumulation ratio (inflow vs outflow per zone)
# ---------------------------------------------------------------------------

def compute_accumulation(edges: list[dict]) -> dict[str, dict]:
    """
    For each zone, computes inbound traffic, outbound traffic, and
    accumulation_ratio = inbound / (outbound + 1).

    A ratio >> 1 means people are arriving faster than leaving.
    """
    inbound: dict[str, int] = defaultdict(int)
    outbound: dict[str, int] = defaultdict(int)

    for edge in edges:
        inbound[edge["to_zone_id"]]   += edge["transition_count"]
        outbound[edge["from_zone_id"]] += edge["transition_count"]

    all_zones = set(inbound) | set(outbound)
    result = {}
    for zone in all_zones:
        ib = inbound.get(zone, 0)
        ob = outbound.get(zone, 0)
        result[zone] = {
            "inbound":            ib,
            "outbound":           ob,
            "accumulation_ratio": ib / (ob + 1),
        }
    return result


# ---------------------------------------------------------------------------
# Signal 2: Intra-snapshot trend (across time_windows within one snapshot)
# ---------------------------------------------------------------------------

def compute_intra_trend(time_windows: list[dict]) -> dict[str, dict]:
    """
    For each zone, computes the linear regression slope and R² of its
    inbound traffic series across the snapshot's time_windows.

    trend_score = normalized_slope * r_squared
    Only positive trends (rising traffic) produce a non-zero score.
    """
    if len(time_windows) < 2:
        return {}

    # Build per-zone inbound series across windows
    zone_series: dict[str, list[float]] = defaultdict(list)
    for window in time_windows:
        edges = window.get("window_graph", {}).get("edges", [])
        window_inbound: dict[str, int] = defaultdict(int)
        for edge in edges:
            window_inbound[edge["to_zone_id"]] += edge["transition_count"]

        # All zones seen so far need an entry (0 if absent this window)
        all_seen = set(zone_series) | set(window_inbound)
        for zone in all_seen:
            zone_series[zone].append(float(window_inbound.get(zone, 0)))

    result = {}
    for zone, series in zone_series.items():
        slope, r_sq = _linear_regression(series)
        mean_traffic = sum(series) / len(series) if series else 1.0
        # Normalize slope to be scale-free (slope relative to mean traffic)
        normalized_slope = slope / (mean_traffic + 1)
        trend_score = _clamp(normalized_slope) * r_sq if normalized_slope > 0 else 0.0
        result[zone] = {
            "series":           series,
            "slope":            slope,
            "r_squared":        round(r_sq, 3),
            "normalized_slope": round(normalized_slope, 3),
            "trend_score":      round(trend_score, 3),
        }
    return result


# ---------------------------------------------------------------------------
# Signal 3: Cross-snapshot EWMA drift (requires history from prior snapshots)
# ---------------------------------------------------------------------------

EWMA_ALPHA = 0.35  # Weight given to the latest snapshot vs running average


def update_ewma(
    current_inbound: dict[str, int],
    previous_ewma: dict[str, float],
) -> tuple[dict[str, float], dict[str, dict]]:
    """
    Updates the EWMA baseline for each zone given the current snapshot's
    inbound counts. Returns (new_ewma, deviation_signals).

    deviation_score = (current - ewma) / (ewma + 1)
    Positive score = above baseline (worsening).
    Negative score = below baseline (recovering or quiet).
    """
    new_ewma: dict[str, float] = {}
    deviations: dict[str, dict] = {}

    all_zones = set(current_inbound) | set(previous_ewma)
    for zone in all_zones:
        current = float(current_inbound.get(zone, 0))
        prev    = previous_ewma.get(zone, current)  # First time: baseline = current
        ewma    = EWMA_ALPHA * current + (1 - EWMA_ALPHA) * prev
        new_ewma[zone] = ewma
        deviation = (current - ewma) / (ewma + 1)
        deviations[zone] = {
            "current":        current,
            "ewma_baseline":  round(ewma, 2),
            "deviation_score": round(_clamp(deviation, -1.0, 1.0), 3),
        }

    return new_ewma, deviations


# ---------------------------------------------------------------------------
# Signal 4: Graph structure change (new/disappeared edges and zones)
# ---------------------------------------------------------------------------

def compute_structural_changes(
    current_snapshot: dict,
    previous_edge_history: set[tuple],
    previous_zone_history: dict[str, int],  # zone_id -> windows_present count
    total_prior_snapshots: int,
) -> dict:
    """
    Detects:
    - New edges that weren't seen in any prior snapshot
    - Low-probability edges that fired (unexpected_transition)
    - Zones that used to be active but have gone quiet
    """
    current_edges = {
        (e["from_zone_id"], e["to_zone_id"]): e
        for e in current_snapshot.get("edges", [])
    }
    current_edge_set = set(current_edges)
    current_zones    = set(current_snapshot.get("nodes", []))

    new_edges = [
        current_edges[key]
        for key in (current_edge_set - previous_edge_history)
    ]

    unexpected_transitions = [
        e for e in current_snapshot.get("edges", [])
        if e.get("transition_probability", 1.0) < 0.05 and e["transition_count"] > 0
    ]

    # Zones that were active before but now absent
    isolated_zones = []
    if total_prior_snapshots >= 3:
        for zone, count in previous_zone_history.items():
            presence_ratio = count / total_prior_snapshots
            if presence_ratio >= 0.6 and zone not in current_zones:
                isolated_zones.append({
                    "zone_id":        zone,
                    "presence_ratio": round(presence_ratio, 2),
                })

    return {
        "new_edges":              new_edges,
        "unexpected_transitions": unexpected_transitions,
        "isolated_zones":         isolated_zones,
        "current_edge_set":       current_edge_set,
        "current_zones":          current_zones,
    }


# ---------------------------------------------------------------------------
# Signal 5: Cross-zone cascade risk
# ---------------------------------------------------------------------------

def compute_cascade_risk(
    edges: list[dict],
    zone_urgency: dict[str, float],
    warning_threshold: float = 0.45,
) -> list[dict]:
    """
    For each zone at or above warning_threshold urgency, follows its
    highest-probability outbound edge. If the destination is also at or above
    warning_threshold, flags a cascade risk pair.
    """
    # Build outbound edge map
    best_outbound: dict[str, dict] = {}
    for edge in edges:
        zone = edge["from_zone_id"]
        if zone not in best_outbound or \
           edge["transition_probability"] > best_outbound[zone]["transition_probability"]:
            best_outbound[zone] = edge

    cascades = []
    for zone_a, urgency_a in zone_urgency.items():
        if urgency_a < warning_threshold:
            continue
        edge = best_outbound.get(zone_a)
        if not edge:
            continue
        zone_b   = edge["to_zone_id"]
        urgency_b = zone_urgency.get(zone_b, 0.0)
        if urgency_b >= warning_threshold:
            cascades.append({
                "from_zone":    zone_a,
                "to_zone":      zone_b,
                "urgency_a":    round(urgency_a, 3),
                "urgency_b":    round(urgency_b, 3),
                "via_probability": edge["transition_probability"],
            })

    return cascades


# ---------------------------------------------------------------------------
# Signal 6: Convergence (multiple high-traffic sources feeding one zone)
# ---------------------------------------------------------------------------

def compute_convergence(
    edges: list[dict],
    zone_urgency: dict[str, float],
    min_sources: int = 2,
    min_edge_count: int = 5,
) -> list[dict]:
    """
    Finds zones that are the destination of multiple high-traffic edges
    simultaneously — a convergence point that may be overwhelmed even if
    its own urgency score isn't yet critical.
    """
    inbound_edges: dict[str, list[dict]] = defaultdict(list)
    for edge in edges:
        if edge["transition_count"] >= min_edge_count:
            inbound_edges[edge["to_zone_id"]].append(edge)

    convergences = []
    for zone, sources in inbound_edges.items():
        if len(sources) >= min_sources:
            total_inbound = sum(e["transition_count"] for e in sources)
            convergences.append({
                "zone_id":       zone,
                "source_count":  len(sources),
                "total_inbound": total_inbound,
                "sources":       [e["from_zone_id"] for e in sources],
                "current_urgency": round(zone_urgency.get(zone, 0.0), 3),
            })

    return convergences


# ---------------------------------------------------------------------------
# Composite urgency score per zone
# ---------------------------------------------------------------------------

def compute_urgency(
    zone_id: str,
    accumulation: dict,
    intra_trend: dict,
    ewma_deviation: dict,
    zone_stats: dict,
    all_dwell_values: list[float],
) -> float:
    """
    Combines all signals into a single urgency score [0, 1].

    Weights (tunable):
      50% accumulation ratio — if people cannot leave, that IS the crisis
      25% trend score (slope * R²) — worsening trajectory amplifies urgency
      25% EWMA deviation — how far current load exceeds the running baseline

    Dwell time is used as a multiplier: a zone where people linger long
    under congestion is more urgent than one with fast throughput.
    """
    acc    = accumulation.get(zone_id, {})
    trend  = intra_trend.get(zone_id, {})
    ewma   = ewma_deviation.get(zone_id, {})
    stats  = zone_stats.get(zone_id, {})

    acc_score   = _clamp(acc.get("accumulation_ratio", 0) / 5.0)
    trend_score = _clamp(trend.get("trend_score", 0.0))
    ewma_score  = _clamp(ewma.get("deviation_score", 0.0))

    base = (
        0.50 * acc_score +
        0.25 * trend_score +
        0.25 * ewma_score
    )

    # Dwell amplifier: if this zone's dwell is above median, boost urgency
    dwell = stats.get("avg_dwell_ms", 0)
    if all_dwell_values:
        sorted_dwells = sorted(all_dwell_values)
        median_dwell  = sorted_dwells[len(sorted_dwells) // 2]
        if median_dwell > 0 and dwell > median_dwell:
            dwell_ratio = min(dwell / median_dwell, 3.0)  # cap at 3×
            base = base * (1.0 + 0.2 * (dwell_ratio - 1.0))

    return round(_clamp(base), 3)


# ---------------------------------------------------------------------------
# Entry point: analyze one snapshot, given cross-snapshot state
# ---------------------------------------------------------------------------

def analyze_snapshot(
    snapshot: dict,
    ewma_state: dict[str, float],
    edge_history: set[tuple],
    zone_history: dict[str, int],
    total_prior_snapshots: int,
) -> dict:
    """
    Runs all detection signals on a single graph snapshot.
    Returns a signals dict consumed by the alert state manager.

    ewma_state, edge_history, zone_history are updated in-place.
    """
    edges        = snapshot.get("edges", [])
    zone_stats   = snapshot.get("zone_stats", {})
    time_windows = snapshot.get("time_windows", [])
    nodes        = set(snapshot.get("nodes", []))

    accumulation = compute_accumulation(edges)
    intra_trend  = compute_intra_trend(time_windows)

    current_inbound = {z: accumulation.get(z, {}).get("inbound", 0) for z in nodes}
    new_ewma, ewma_deviations = update_ewma(current_inbound, ewma_state)
    ewma_state.update(new_ewma)

    structural = compute_structural_changes(
        snapshot, edge_history, zone_history, total_prior_snapshots
    )
    edge_history.update(structural["current_edge_set"])
    for zone in structural["current_zones"]:
        zone_history[zone] = zone_history.get(zone, 0) + 1

    all_dwell_values = [
        s["avg_dwell_ms"] for s in zone_stats.values()
        if "avg_dwell_ms" in s
    ]

    zone_urgency = {
        zone: compute_urgency(
            zone, accumulation, intra_trend, ewma_deviations,
            zone_stats, all_dwell_values
        )
        for zone in (set(zone_stats) | nodes)
    }

    cascades    = compute_cascade_risk(edges, zone_urgency)
    convergence = compute_convergence(edges, zone_urgency)

    return {
        "zone_urgency":           zone_urgency,
        "accumulation":           accumulation,
        "intra_trend":            intra_trend,
        "ewma_deviations":        ewma_deviations,
        "structural":             structural,
        "cascades":               cascades,
        "convergence":            convergence,
        "zone_stats":             zone_stats,
        "snapshot_ts":            snapshot.get("snapshot_ts", 0),
    }
