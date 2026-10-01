"""Gemini-guided travel plan refinement (Requirements 25-27).

The planner NEVER invents resources: Gemini recieves only candidate itineraries
that were built deterministically from database rows, and it is allowed only to
pick one of them (or override the ranking) using the traveller's free-text
preferences. Every price and every resource id in the response stays exactly as
it appeared in the DB-derived candidate — the backend always recomputes totals.

When Gemini is unavailable (no key / timeout / bad JSON) the caller falls back
to the deterministic best plan, so planning never blocks on the LLM.
"""
import json

from services.ai_service import call_ai, is_ai_available


def _candidate_brief(plans):
    """Compact, lossless summary of DB-derived plans with resource_ids intact."""
    out = []
    for i, p in enumerate(plans):
        items = []
        for day in p.get("dailyPlan", []):
            for it in day.get("items", []):
                items.append({
                    "type": it.get("type"),
                    "title": it.get("title"),
                    "provider": it.get("provider"),
                    "resourceId": it.get("bookableId", it.get("resourceId")),
                    "startTime": it.get("startTime"),
                    "cost": it.get("cost"),
                })
        out.append({
            "index": i,
            "planType": p.get("planType"),
            "totalCost": p.get("totalCost"),
            "optimizationScore": p.get("optimizationScore"),
            "comfortScore": p.get("comfortScore"),
            "items": items,
        })
    return out


def refine_plan_selection(parsed, plans):
    """Ask Gemini to select/adjust the best DB-derived plan.

    Returns None when unavailable so the orchestrator falls back to the
    deterministic best plan.
    """
    if not is_ai_available():
        return None

    prompt = (
        "Traveller preferences (free text): %s\n"
        "Trip: %s -> %s, %d day(s), %d traveller(s), style %s.\n\n"
        "Below are candidate itineraries the travel engine already built from "
        "registered inventory. Choose the best match for the preferences and "
        "return ONLY a JSON object with this schema:\n"
        '{"selectedIndex": <int>, "reason": "<1-2 sentence reason>", '
        '"adjustments": [{"itemIndex": <int>, "note": "<why this item matters>"}]}\n'
        "\nCandidates:\n%s"
        % (
            parsed.get("preferences", ""),
            parsed.get("origin", ""),
            parsed.get("destination", ""),
            parsed.get("durationDays", 1),
            parsed.get("travelers", 1),
            parsed.get("travelStyle", "BALANCED"),
            json.dumps(_candidate_brief(plans), default=str, indent=2),
        )
    )
    system = (
        "You are TripMind's selective-planning engine. Rules: 1) You may ONLY "
        "select among the provided candidate itineraries using their exact "
        "index — never invent resources, prices or itineraries. 2) selectedIndex "
        "must be a valid index in the candidates list. 3) Return exactly the "
        "JSON schema described, no markdown."
    )
    try:
        raw = call_ai(prompt, system)
        if not raw:
            return None
        clean = raw.strip()
        if clean.startswith("```"):
            clean = clean.strip("`")
            if clean.lower().startswith("json"):
                clean = clean[4:]
            clean = clean.strip()
        start, end = clean.find("{"), clean.rfind("}")
        if start == -1 or end == -1:
            return None
        data = json.loads(clean[start:end + 1])
        idx = int(data.get("selectedIndex") if isinstance(data.get("selectedIndex"), int)
                  else (data.get("selectedIndex") or 0))
    except Exception:
        return None

    if idx < 0 or idx >= len(plans):
        return None
    selected = plans[idx]
    reason = (data.get("reason") or "").strip() or "based on your preferences."
    itin = _find_selected_itin(selected)
    if itin is not None:
        itin["reasoning"] = (itin.get("reasoning") or []) + [
            "Gemini: %s" % reason]
    return {"selectedPlan": selected, "reason": reason}


def _find_selected_itin(plan):
    """Return the SELECTED itinerary dict or None so reasoning can be annotated."""
    return None