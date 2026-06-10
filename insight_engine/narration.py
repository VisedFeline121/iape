"""
Narration layer — turns structured detection signals into human-readable alert messages.

Architecture:
  - generate_message() is the single public function. Everything else is an impl detail.
  - Primary path: OpenAI API (or any OpenAI-compatible endpoint, including local ollama)
  - Fallback path: template messages — written to incident-commander standard, not placeholders
  - Swap between API and local model by changing NARRATION_BACKEND and MODEL_NAME only.

To switch to local ollama:
  NARRATION_BACKEND = "openai_compatible"
  API_BASE_URL      = "http://localhost:11434/v1"
  MODEL_NAME        = "llama3"   (or whichever model you have pulled)
  API_KEY           = "ollama"   (ollama ignores the key but the client requires one)
"""

import os
import json
import logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration — change these to switch backends, nothing else needs to change
# ---------------------------------------------------------------------------

NARRATION_BACKEND = os.getenv("NARRATION_BACKEND", "openai")   # "openai" | "openai_compatible" | "disabled"
API_BASE_URL      = os.getenv("NARRATION_API_BASE", None)       # None = default OpenAI endpoint
MODEL_NAME        = os.getenv("NARRATION_MODEL",    "gpt-4o-mini")
API_KEY           = os.getenv("OPENAI_API_KEY",     "")
API_TIMEOUT_S     = float(os.getenv("NARRATION_TIMEOUT", "3.0"))

_client = None

def _get_client():
    global _client
    if _client is not None:
        return _client
    if not API_KEY or NARRATION_BACKEND == "disabled":
        return None
    try:
        from openai import OpenAI
        kwargs = {"api_key": API_KEY, "timeout": API_TIMEOUT_S}
        if API_BASE_URL:
            kwargs["base_url"] = API_BASE_URL
        _client = OpenAI(**kwargs)
        return _client
    except ImportError:
        logger.warning("openai package not installed — narration falling back to templates")
        return None


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """You are the voice of a real-time situational awareness system deployed
in an emergency operations context. Your messages appear on an incident commander's screen
during an active response — a fire, a mass-casualty event, or a rescue in an unknown building.

Rules you must always follow:
- Write one paragraph maximum, 2-3 sentences.
- Lead with what is happening operationally, not what the data shows.
- Include specific numbers (traffic counts, dwell times, growth rates) from the data provided.
- Include time context where available ("in the last 3 windows", "over the past 2 minutes").
- End with an implication or recommended action when severity is warning or critical.
- Never use statistical terms: no "z-score", "threshold", "standard deviation", "baseline".
- Tone: calm, precise, authoritative. Not alarming, not casual.
- Never start with "I" or mention yourself or the system."""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_message(
    insight_type: str,
    zone_id: str,
    signals: dict,
    alert=None,           # existing Alert object, or None if this is a new alert
) -> str:
    """
    Generates a human-readable message for an alert.
    Tries the LLM API first; falls back to a template on any failure.
    """
    context = _build_context(insight_type, zone_id, signals, alert)

    client = _get_client()
    if client:
        try:
            result = _call_llm(client, insight_type, zone_id, context, alert)
            if result:
                return result
        except Exception as e:
            logger.warning(f"LLM narration failed for {alert}: {e} — using template")

    return _template_message(insight_type, zone_id, context, alert)


# ---------------------------------------------------------------------------
# LLM call
# ---------------------------------------------------------------------------

def _call_llm(client, insight_type: str, zone_id: str, context: dict, alert) -> str:
    severity  = alert.severity if alert else "detecting"
    label     = _zone_label(zone_id)
    user_msg  = (
        f"Generate an alert message for the following situation:\n\n"
        f"Zone: {label}\n"
        f"Alert type: {insight_type}\n"
        f"Severity: {severity}\n"
        f"Data: {json.dumps(context, indent=2)}\n\n"
        f"Write the message now."
    )

    response = client.chat.completions.create(
        model=MODEL_NAME,
        messages=[
            {"role": "system",  "content": _SYSTEM_PROMPT},
            {"role": "user",    "content": user_msg},
        ],
        max_tokens=120,
        temperature=0.4,
    )
    return response.choices[0].message.content.strip()


# ---------------------------------------------------------------------------
# Template fallback — written to incident-commander standard
# ---------------------------------------------------------------------------

def _template_message(
    insight_type: str,
    zone_id: str,
    context: dict,
    alert,
) -> str:
    label    = _zone_label(zone_id)
    severity = alert.severity if alert else "detecting"
    acc      = context.get("accumulation_ratio", 0)
    inbound  = context.get("inbound", 0)
    dwell_s  = context.get("dwell_s", 0)
    growth   = context.get("traffic_growth_x", None)
    windows  = context.get("window_count", 0)
    series   = context.get("trend_series", [])

    time_ctx = f"across {windows} time windows" if windows > 1 else "in the current window"

    if insight_type == "congestion_forecast":
        if growth and growth > 1.1 and series:
            return (
                f"{label} traffic has grown {growth:.1f}× {time_ctx} and continues to rise. "
                f"Current inbound rate is {inbound} transitions with an accumulation ratio of {acc:.1f}:1. "
                f"{'Recommend diverting flow before this sector reaches capacity.' if severity in ('warning', 'critical') else ''}"
            ).strip()
        return (
            f"{label} is showing a consistent upward traffic trend {time_ctx}. "
            f"Inbound rate: {inbound} transitions, accumulation ratio {acc:.1f}:1. "
            f"{'Monitor closely — congestion is forecast if the trend continues.' if severity == 'warning' else 'Immediate intervention recommended.' if severity == 'critical' else ''}"
        ).strip()

    if insight_type == "bottleneck_risk":
        return (
            f"{label} is a convergence point absorbing {inbound} inbound transitions "
            f"with an average stay of {dwell_s}s and accumulation ratio {acc:.1f}:1. "
            f"{'This sector is at risk of becoming impassable — consider opening an alternative route.' if severity in ('warning', 'critical') else 'Situation developing — continue monitoring.'}"
        )

    if insight_type == "high_dwell_zone":
        return (
            f"{label} has an average dwell time of {dwell_s}s, significantly above normal {time_ctx}. "
            f"People are spending extended time here — possible obstruction, waiting area, or point of friction. "
            f"{'Recommend visual inspection of this sector.' if severity in ('warning', 'critical') else ''}"
        ).strip()

    if insight_type == "unexpected_transition":
        from_label = _zone_label(context.get("from_zone", "unknown"))
        prob       = context.get("transition_probability", 0)
        count      = context.get("transition_count", 0)
        return (
            f"Atypical movement detected from {from_label} to {label}: "
            f"{count} transitions observed at a base probability of {prob:.0%}. "
            f"This route is not part of normal flow patterns — possible rerouting, restricted access, or evacuation behavior."
        )

    if insight_type == "anomaly":
        from_label = _zone_label(context.get("from_zone", ""))
        if from_label and from_label != _zone_label(""):
            return (
                f"A new movement path from {from_label} to {label} has appeared — "
                f"this route was not observed in any earlier period. "
                f"Possible access to a previously unused area or a change in building conditions."
            )
        presence = context.get("presence_ratio", None)
        if presence is not None:
            return (
                f"{label} was active in {presence:.0%} of observed windows but has gone quiet. "
                f"Upstream feeders are still active. Possible blockage, access loss, or evacuation of this sector."
            )
        return (
            f"{label} is displaying unusual activity patterns {time_ctx}. "
            f"Deviation from session baseline detected. Recommend monitoring."
        )

    return f"{label} requires attention — unusual conditions detected {time_ctx}."


# ---------------------------------------------------------------------------
# Context builder — extracts the numbers the LLM and templates both need
# ---------------------------------------------------------------------------

def _build_context(
    insight_type: str,
    zone_id: str,
    signals: dict,
    alert,
) -> dict:
    acc_data   = signals.get("accumulation",    {}).get(zone_id, {})
    trend_data = signals.get("intra_trend",     {}).get(zone_id, {})
    ewma_data  = signals.get("ewma_deviations", {}).get(zone_id, {})
    stats      = signals.get("zone_stats",      {}).get(zone_id, {})

    inbound  = acc_data.get("inbound", 0)
    outbound = acc_data.get("outbound", 0)
    acc      = acc_data.get("accumulation_ratio", 0)
    dwell_ms = stats.get("avg_dwell_ms", 0)
    dwell_s  = round(dwell_ms / 1000) if dwell_ms else 0
    series   = trend_data.get("series", [])

    growth = None
    if len(series) >= 2 and series[0] > 0:
        growth = round(series[-1] / series[0], 2)

    ctx = {
        "zone_id":            zone_id,
        "zone_label":         _zone_label(zone_id),
        "insight_type":       insight_type,
        "severity":           alert.severity if alert else "detecting",
        "inbound":            inbound,
        "outbound":           outbound,
        "accumulation_ratio": round(acc, 2),
        "dwell_s":            dwell_s,
        "trend_score":        trend_data.get("trend_score", 0),
        "r_squared":          trend_data.get("r_squared", 0),
        "trend_series":       series,
        "traffic_growth_x":   growth,
        "window_count":       len(series),
        "ewma_deviation":     ewma_data.get("deviation_score", 0),
        "ewma_baseline":      ewma_data.get("ewma_baseline", 0),
        "cycle_count":        alert.cycle_count if alert else 1,
    }

    # Extra context for edge-level alerts
    structural = signals.get("structural", {})
    for edge in structural.get("unexpected_transitions", []):
        if edge["to_zone_id"] == zone_id:
            ctx["from_zone"]              = edge["from_zone_id"]
            ctx["transition_probability"] = edge["transition_probability"]
            ctx["transition_count"]       = edge["transition_count"]
            break
    for edge in structural.get("new_edges", []):
        if edge["to_zone_id"] == zone_id:
            ctx.setdefault("from_zone", edge["from_zone_id"])
            break
    for iz in structural.get("isolated_zones", []):
        if iz["zone_id"] == zone_id:
            ctx["presence_ratio"] = iz["presence_ratio"]
            break

    return ctx


# ---------------------------------------------------------------------------
# Zone label formatting
# ---------------------------------------------------------------------------

def _zone_label(zone_id: str) -> str:
    """
    Converts internal zone IDs to display labels.
    "zone_3" → "Sector 3", "zone_12" → "Sector 12", anything else → title-cased.
    Adjust this function once Person 5 confirms their display naming convention.
    """
    if zone_id.startswith("zone_"):
        return "Sector " + zone_id[5:]
    return zone_id.replace("_", " ").title()
