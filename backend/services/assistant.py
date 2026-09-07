"""Action-capable AI travel assistant.

A thin Groq layer over a deterministic, server-side tool set. The model can
only *propose* an action (switch transport, pay a trip, remove a place from a
plan); every mutation is executed on a separate, re-validated endpoint
(POST /api/assistant/action) so no chat message can silently change a booking.

The whole tool layer also runs on local keyword matching, so the assistant
keeps working even when the Groq API or key is unavailable.
"""
import json
import re
from datetime import datetime

from services.mongodb import get_collection
from services.groq_service import call_ai, is_ai_available
from services.transport_service import available_transports


_TOOL_DESC = {
    "list_my_trips": "List the traveller's trips (plan/trip stage, dates, budget, payment status).",
    "get_trip": "Return one trip's details by tripId.",
    "list_bookings": "List the traveller's bookings and their payment status.",
    "view_wallet": "Show the traveller's wallet balance and recent transactions.",
    "find_alternative_transports": "Find registered, approved transports for origin->destination.",
    "change_transport": "Propose replacing a booked transport on a trip with another approved service.",
    "pay_trip": "Propose paying for all unpaid active bookings on a trip from the wallet.",
    "remove_place": "Propose removing every itinerary item that mentions a place name from a trip plan.",
}


def _brief_trips(user_id):
    out = []
    trips = get_collection("trips").find({"userId": user_id}).sort("createdAt", 1)
    for t in trips:
        delay = (t.get("delay") or {}).get("status") == "ACTIVE"
        out.append({
            "tripId": str(t["_id"]),
            "reference": t.get("reference"),
            "route": "%s -> %s" % (t.get("origin"), t.get("destination")),
            "start": t.get("startDate"),
            "status": t.get("status"),
            "paymentStatus": t.get("paymentStatus"),
            "travelers": t.get("travelers"),
            "budget": t.get("budget"),
            "activeDelay": delay,
        })
    return out


def _brief_bookings(user_id):
    out = []
    for b in get_collection("bookings").find({"userId": user_id}).sort("createdAt", -1):
        out.append({
            "reference": b.get("reference"),
            "type": b.get("type"),
            "title": b.get("itemTitle") or b.get("foodName") or b.get("reference"),
            "status": b.get("status"),
            "paymentStatus": b.get("paymentStatus"),
            "amount": round(float(b.get("total") or 0), 2),
            "date": b.get("date"),
        })
    return out[:20]


def _brief_wallet(user_id):
    from services.wallet_service import get_wallet
    w = get_wallet(user_id)
    txns = sorted(w.get("transactions") or [], key=lambda t: t.get("createdAt", ""), reverse=True)
    return {
        "balance": round(float(w.get("balance") or 0), 2),
        "totalDeposited": round(float(w.get("totalDeposited") or 0), 2),
        "totalSpent": round(float(w.get("totalSpent") or 0), 2),
        "recentTransactions": [
            {"type": t.get("type"), "amount": t.get("amount"), "desc": t.get("description"), "at": t.get("createdAt")}
            for t in txns[:5]
        ],
    }


def _owned_trip(user, trip_id):
    trip = get_collection("trips").find_one({"_id": str(trip_id or "")})
    if trip and str(trip.get("userId")) == str(user["id"]):
        return trip
    return None


def _plan_text(trip, max_items=6):
    items = []
    for it in trip.get("itineraries", []) or []:
        if it.get("status") == "SELECTED":
            items = it.get("items", [])
            break
    if not items:
        items = (trip.get("itineraries") or [{}])[0].get("items", [])
    lines = []
    for i in items[:max_items]:
        lines.append("  - %s (%s) ~Rs %s" % (i.get("title"), i.get("type"), i.get("cost") or 0))
    if len(items) > max_items:
        lines.append("  ... and %d more items" % (len(items) - max_items))
    return "\n".join(lines)


def _sys_prompt():
    tool_lines = "\n".join("  %s: %s" % (k, v) for k, v in _TOOL_DESC.items())
    return (
        "You are TripMind, an action-capable AI travel assistant for one logged-in traveller. "
        "You may PROPOSE one tool call when it directly helps the current request. Tools:\n"
        + tool_lines +
        "\nReturn ONLY a JSON object with this schema and nothing else "
        "(no markdown, no surrounding text):\n"
        "{\"reply\":\"<short helpful reply to the traveller>\","
        "\"tool\":{\"name\":\"<one of the tool names or null>\",\"args\":{...}},"
        "\"suggestions\":[\"<3 short follow-up prompts>\"]}\n"
        "If no tool is needed, set tool to null. Never invent data; rely only on context provided. "
        "For any action that changes facts (change_transport, pay_trip, remove_place) you still only "
        "PROPOSE it; execution happens only after the traveller confirms."
    )


def _local_intent(message, user, trip_id=None):
    """Deterministic fallback used when the LLM is unavailable or returns junk."""
    m = message.lower()
    trip = _owned_trip(user, trip_id) if (trip_id and user) else None

    if any(k in m for k in ["change transport", "switch transport", "change bus", "switch bus",
                            "change train", "switch train", "another transport", "different transport",
                            "replace transport"]):
        routes = [(t.get("origin"), t.get("destination"), t.get("reference"), t)
                  for t in get_collection("trips").find({"userId": user["id"]})
                  if any(b.get("type") == "TRANSPORT" and b.get("status") not in ("CANCELLED", "REJECTED")
                         for b in t.get("bookings", []) or [])]
        if not routes:
            return {"reply": "You don't have a booked transport on any trip, so there's nothing to switch.",
                    "tool": None, "suggestions": ["Show my trips", "Check wallet balance", "Plan a trip"]}
        target = trip or routes[0][3]
        opts = find_transport_options(target)
        if not opts:
            return {"reply": "No registered, approved alternative transports are available for %s -> %s."
                            % (target.get("origin"), target.get("destination")),
                    "tool": None, "suggestions": ["Show route map", "Show my trips"]}
        reply = ("I can switch the transport on trip %s (%s -> %s). Options currently registered:\n"
                 % (target.get("reference"), target.get("origin"), target.get("destination")))
        for o in opts[:5]:
            reply += "  - %s (%s) · %s · ~Rs %s\n" % (
                o.get("name"), o.get("mode"), str(o.get("transportId"))[:12] + "...", o.get("cost"))
        reply += "Confirm below to change it (old service will be refunded, difference billed to wallet)."
        return {"reply": reply, "tool": {
            "name": "change_transport",
            "args": {"trip_id": str(target["_id"]),
                     "transport_id": str(opts[0]["transportId"]),
                     "mode": opts[0]["mode"]}},
            "suggestions": ["Confirm", "Show other options", "Show my bookings"]}

    if any(k in m for k in ["pay trip", "pay my trip", "pay for trip", "complete payment",
                            "pay bookings", "pay now"]):
        if not trip:
            trips = list(get_collection("trips").find({"userId": user["id"]}))
            unpaid = [t for t in trips if (t.get("paymentStatus") or "PENDING") not in ("WALLET", "COMPLETED")]
            if not unpaid:
                return {"reply": "All your trips are already paid.", "tool": None,
                        "suggestions": ["Show my trips", "Check wallet balance"]}
            trip = unpaid[0]
        unpaid_b = [b for b in (trip.get("bookings") or [])
                    if b.get("status") not in ("CANCELLED", "REJECTED")
                    and b.get("paymentStatus") not in ("WALLET", "COMPLETED")]
        if not unpaid_b:
            return {"reply": "Trip %s already has no unpaid bookings." % trip.get("reference"),
                    "tool": None, "suggestions": ["Show my trips"]}
        total = sum(float(b.get("total") or 0) for b in unpaid_b)
        return {"reply": ("Trip %s has %d unpaid booking(s) totalling Rs %s. "
                          "Confirm to pay this from your wallet." % (trip.get("reference"), len(unpaid_b), total)),
                "tool": {"name": "pay_trip", "args": {"trip_id": str(trip["_id"])}},
                "suggestions": ["Confirm", "Show wallet balance", "Show bookings"]}

    if any(k in m for k in ["remove ", "delete ", "drop "]) and trip:
        place = _extract_place(m)
        return {"reply": 'Confirm to remove "%s" from trip %s plan?' % (place, trip.get("reference")),
                "tool": {"name": "remove_place", "args": {"trip_id": str(trip["_id"]), "place": place}},
                "suggestions": ["Confirm", "Show my trips"]}

    return None


def _extract_place(m):
    for kw in ["remove", "delete", "drop", "take out"]:
        m = m.replace(kw, " ")
    m = re.sub(r"\s+", " ", m).strip(" .,;:!?")
    return m or None


def find_transport_options(trip):
    """Registered, approved alternate transports for the trip route."""
    out = []
    for t in available_transports(trip.get("origin", ""), trip.get("destination", ""))[:6]:
        fare = t.get("fare")
        if isinstance(fare, dict):
            price = fare.get("price") or fare.get("baseFare") or fare.get("pricePerKm") or 0
        else:
            price = fare or 0
        name = t.get("serviceName") or t.get("type")
        out.append({"transportId": str(t["_id"]), "mode": t.get("type"),
                    "name": name.strip(), "cost": price})
    return out


def _build_context(user, trip_id=None):
    ctx = {"traveller": {"name": user.get("name"), "email": user.get("email")}}
    ctx["trips"] = _brief_trips(user["id"])
    ctx["bookings"] = _brief_bookings(user["id"])
    ctx["wallet"] = _brief_wallet(user["id"])
    if trip_id:
        t = _owned_trip(user, trip_id)
        if t:
            ctx["activeTrip"] = {
                "reference": t.get("reference"),
                "route": "%s -> %s" % (t.get("origin"), t.get("destination")),
                "start": t.get("startDate"),
                "budget": t.get("budget"),
                "status": t.get("status"),
                "paymentStatus": t.get("paymentStatus"),
                "itinerary": _plan_text(t),
            }
    return ctx


def _parse_tool_json(raw):
    """Extract a usable tool call from the (possibly markdown-wrapped) LLM output."""
    clean = raw.strip()
    if clean.startswith("```"):
        clean = clean.strip("`")
        if clean.lower().startswith("json"):
            clean = clean[4:]
        clean = clean.strip()
    start, end = clean.find("{"), clean.rfind("}")
    if start == -1 or end == -1:
        return None
    try:
        data = json.loads(clean[start:end + 1])
    except ValueError:
        m = re.search(r'"name"\s*:\s*"([a-z_]+)"', clean[start:end + 1])
        if not m:
            return None
        return {"name": m.group(1), "args": {}}
    reply = data.get("reply") or data.get("message") or ""
    tool = data.get("tool") if isinstance(data.get("tool"), dict) else None
    if isinstance(tool, dict):
        name = tool.get("name")
        args = tool.get("args") if isinstance(tool.get("args"), dict) else {}
        if name not in _TOOL_DESC:
            tool = None
        else:
            tool = {"name": name, "args": args}
    suggestions = data.get("suggestions") if isinstance(data.get("suggestions"), list) else []
    return {"reply": reply, "tool": tool, "suggestions": [str(s) for s in suggestions[:3]]}


def handle_assistant_message(user, message, trip_id=None):
    """Return a chat response plus an optional PROPOSED action (not executed)."""
    local = _local_intent(message, user, trip_id)

    if is_ai_available():
        try:
            prompt = (
                "Traveller message: %s\n\n"
                "Current context (JSON):\n%s\n\n"
                "Decide whether a tool call is warranted and answer per the schema."
                % (message, json.dumps(_build_context(user, trip_id), default=str))
            )
            raw = call_ai(prompt, _sys_prompt())
            parsed = _parse_tool_json(raw)
            if parsed:
                tool = parsed.get("tool")
                # local fallback wins for high-confidence mutation proposals
                # so switching/payment proposals stay deterministic.
                if tool and tool.get("name") in ("change_transport", "pay_trip", "remove_place"):
                    if local and local.get("tool"):
                        tool = local["tool"]
                    else:
                        tool = None
                return {
                    "response": parsed.get("reply") or "How can I help?",
                    "suggestions": parsed.get("suggestions") or _default_suggestions(),
                    "action": _action_descriptor(tool, user) if tool else None,
                    "timestamp": datetime.utcnow().isoformat(),
                }
        except Exception:
            pass

    if local:
        return {
            "response": local["reply"],
            "suggestions": local.get("suggestions") or _default_suggestions(),
            "action": _action_descriptor(local.get("tool"), user) if local.get("tool") else None,
            "timestamp": datetime.utcnow().isoformat(),
        }

    if any(k in message.lower() for k in ["trip", "plan", "travel", "itinerary"]) and not trip_id:
        trips = _brief_trips(user["id"])
        if not trips:
            return {"response": "You haven't planned any trips yet. Head to Plan your Trip to create one.",
                    "suggestions": ["Plan a trip", "Check wallet balance"], "action": None,
                    "timestamp": datetime.utcnow().isoformat()}
        lines = "\n".join("  - %s: %s (%s, %s travelers, %s)" % (
            t["reference"], t["route"], t["status"], t["travelers"], t["paymentStatus"]) for t in trips)
        return {"response": "Here are your trips:\n" + lines,
                "suggestions": ["Show bookings", "Check wallet balance", "Pay my trip"],
                "action": None, "timestamp": datetime.utcnow().isoformat()}

    if any(k in message.lower() for k in ["wallet", "balance", "money", "funds"]):
        w = _brief_wallet(user["id"])
        return {"response": ("Your wallet balance is Rs %s. Deposited Rs %s, spent Rs %s."
                             % (w["balance"], w["totalDeposited"], w["totalSpent"])),
                "suggestions": ["Pay my trip", "Show bookings"], "action": None,
                "timestamp": datetime.utcnow().isoformat()}

    return {
        "response": ("I can check your trips, wallet and bookings, find alternative transport, "
                     "switch your booked transport, pay a trip from the wallet, or update your plan. "
                     "What would you like to do?"),
        "suggestions": _default_suggestions(),
        "action": None,
        "timestamp": datetime.utcnow().isoformat(),
    }


def _action_descriptor(tool, user):
    if not tool:
        return None
    name, args = tool["name"], tool["args"]
    if name == "change_transport":
        trip_id = args.get("trip_id")
        t = get_collection("trips").find_one({"_id": str(trip_id or "")})
        if not t or str(t.get("userId")) != str(user["id"]):
            return None
        return {"type": "change_transport", "label": "Confirm transport change",
                "params": {"trip_id": trip_id, "transport_id": args.get("transport_id")}}
    if name == "pay_trip":
        trip_id = args.get("trip_id")
        t = get_collection("trips").find_one({"_id": str(trip_id or "")})
        if not t or str(t.get("userId")) != str(user["id"]):
            return None
        return {"type": "pay_trip", "label": "Confirm payment from wallet",
                "params": {"trip_id": trip_id}}
    if name == "remove_place":
        trip_id = args.get("trip_id")
        t = get_collection("trips").find_one({"_id": str(trip_id or "")})
        if not t or str(t.get("userId")) != str(user["id"]):
            return None
        place = args.get("place")
        if not place:
            return None
        return {"type": "remove_place", "label": "Confirm removal",
                "params": {"trip_id": trip_id, "place": place}}
    return None


def _default_suggestions():
    return ["Show my trips", "Check wallet balance", "Find alternative transport", "Pay my trip"]


def execute_action(user, action_type, params):
    """Execute a confirmed assistant action. Server re-validates everything."""
    params = params or {}
    trip_id = params.get("trip_id")
    trip = _owned_trip(user, trip_id) if (trip_id and user) else None

    if action_type == "change_transport":
        if not trip:
            return {"error": "Trip not found."}, 404
        from services.booking_service import switch_transport
        transport_id = params.get("transport_id")
        trip, new_booking, err = switch_transport(trip, user, transport_id)
        if err:
            return {"error": err}, 400
        return {
            "message": "Transport switched on trip %s. New booking %s (Rs %s). Old booking refunded / difference billed."
                       % (trip.get("reference"), new_booking.get("reference"), new_booking.get("total")),
            "booking": new_booking,
        }, 200

    if action_type == "pay_trip":
        if not trip:
            return {"error": "Trip not found."}, 404
        from services.booking_service import pay_trip_bookings
        updated, trip, errors = pay_trip_bookings(trip, user)
        if errors and not any(b.get("paymentStatus") in ("WALLET", "COMPLETED") for b in updated):
            return {"error": "; ".join(errors)}, 400
        return {
            "message": "Trip %s marked %s%s." % (
                trip.get("reference"), trip.get("paymentStatus"),
                (" (some bookings failed: %s)" % "; ".join(errors)) if errors else ""),
            "paymentStatus": trip.get("paymentStatus"),
        }, 200

    if action_type == "remove_place":
        if not trip:
            return {"error": "Trip not found."}, 404
        from services.ai_chat import _remove_place_from_trip
        place = params.get("place")
        result, err = _remove_place_from_trip(str(trip["_id"]), place)
        if err:
            return {"error": err}, 400
        return {"message": "Removed: %s. New cost: Rs %s." % (
            ", ".join(result["removed"]), result["newTotalCost"])}, 200

    return {"error": "Unknown assistant action."}, 400