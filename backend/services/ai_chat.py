from datetime import datetime
from services.mongodb import get_collection
from services.route_mindmap import get_journey_flow
from services.transport_service import available_transports

REMOVE_KEYWORDS = ["remove", "delete", "drop", "take out"]
TRANSPORT_KEYWORDS = ["transport", "train", "bus", "flight", "cab", "auto", "alternate", "alternative", "another way"]


def _flow_response(origin="Coimbatore", destination="Chennai"):
    """Mind-map output rule: return ONLY the connected travel journey flow."""
    flow = get_journey_flow(origin, destination)
    lines = [
        "TRAVEL JOURNEY FLOW",
        "",
        "START: %s" % flow["start"],
        "  |",
    ]
    for i, stage in enumerate(flow["stages"], start=1):
        if stage["type"] == "info":
            lines.append("%d. %s" % (i, stage["title"]))
        elif stage["type"] == "group":
            lines.append("%d. %s" % (i, stage["title"]))
            for o in stage["options"]:
                opt_names = [c["name"] for c in o.get("classes", [])] if o.get("classes") else [o["name"]]
                if opt_names:
                    lines.append("   %s -> %s" % (o["name"], " | ".join(opt_names)))
        elif stage["type"] == "branch":
            lines.append("%d. %s" % (i, stage["title"]))
            lines.append("   " + "  |  ".join(o["name"] for o in stage.get("options", [])))
        elif stage["type"] == "hotels":
            lines.append("%d. Hotels in %s" % (i, destination))
            lines.append("   " + "  |  ".join(c["name"] for c in stage.get("categories", [])))
        elif stage["type"] == "spots":
            lines.append("%d. Tourist spots in %s" % (i, destination))
            lines.append("   " + "  |  ".join(s["name"] for s in stage.get("spots", [])))
        elif stage["type"] == "return":
            lines.append("%d. %s" % (i, stage["title"]))
        else:
            lines.append("%d. %s" % (i, stage["title"]))
        lines.append("  |")
    lines.append("The full connected, visually traceable map is on the Route Map page.")
    return "\n".join(lines)


def _selected_itinerary(trip):
    """Return the SELECTED itinerary of a trip (items referenced by name)."""
    for it in trip.get("itineraries", []):
        if it.get("status") == "SELECTED":
            return it
    return (trip.get("itineraries") or [None])[0]


def _transport_suggestion(trip):
    """Return a list of alternate transport options for the trip's origin/destination."""
    origin = trip.get("origin", "")
    destination = trip.get("destination", "")
    out = []
    for t in available_transports(origin, destination)[:6]:
        ttype = t.get("type", "")
        fare = t.get("fare")
        if isinstance(fare, dict):
            price = (fare.get("price") or fare.get("baseFare") or 0)
            # For cabs/autos the per-km rate is the key pricing dimension.
            if not price and fare.get("pricePerKm"):
                price = fare.get("pricePerKm")
        else:
            price = fare or 0
        name = t.get("serviceName") or ttype
        if ttype == "BUS":
            name = "%s %s" % (name, t.get("busNumber") or "")
        elif ttype == "TRAIN":
            name = "%s %s" % (name, t.get("trainNumber") or "")
        elif ttype == "FLIGHT":
            name = "%s %s" % (name, t.get("flightNumber") or "")
        out.append({"mode": ttype, "name": name.strip(), "cost": price})
    return out


def _extract_place_name(message):
    """Extract a destination/place name to remove from the plan."""
    msg_lower = message.lower()
    for kw in REMOVE_KEYWORDS:
        msg_lower = msg_lower.replace(kw, " ")
    words = [w for w in msg_lower.split() if w.strip()]
    if not words:
        return None
    title = " ".join(words).strip(" .,;:!?") or None
    return title


def _remove_place_from_trip(trip_id, place):
    """Remove all itinerary items whose title contains the given place name."""
    trips = get_collection("trips")
    trip = trips.find_one({"_id": trip_id})
    if not trip:
        return None, "Trip not found."
    itinerary = _selected_itinerary(trip)
    if not itinerary:
        return None, "This trip has no itinerary to modify yet."
    items = itinerary.get("items", [])
    keep = []
    removed = []
    for item in items:
        title = (item.get("title") or "")
        if place and place.lower() in title.lower():
            removed.append(title)
        else:
            keep.append(item)
    if not removed:
        return None, "No itinerary item named '%s' was found." % place

    new_items = []
    for day in sorted({i.get("day") for i in keep}):
        day_items = [i for i in keep if i.get("day") == day]
        for idx, i in enumerate(day_items):
            i["sortOrder"] = idx
            new_items.append(i)
    new_total = sum(i.get("cost", 0) for i in keep)

    trips.update_one(
        {"_id": trip_id},
        {"$set": {
            "itineraries.$[it].items": new_items,
            "itineraries.$[it].totalCost": new_total,
            "updatedAt": datetime.utcnow().isoformat(),
        }},
        array_filters=[{"it.status": "SELECTED"}],
    )
    return {
        "removed": removed,
        "remainingItems": len(new_items),
        "newTotalCost": new_total,
    }, None


def handle_ai_chat(trip_id, message):
    msg_lower = message.lower()
    trip = None
    if trip_id:
        trip = get_collection("trips").find_one({"_id": trip_id})

    flow_keywords = [
        "travel flow", "transport flow", "route map", "journey map",
        "mind map", "travel route", "journey flow", "how to reach",
        "show flow", "journey", "roadmap", "route to", "route from",
    ]
    if any(kw in msg_lower for kw in flow_keywords):
        origin = (trip or {}).get("origin", "Coimbatore")
        destination = (trip or {}).get("destination", "Chennai")
        return {
            "response": _flow_response(origin, destination),
            "suggestions": [
                "Open the Route Map",
                "Show me transport options",
                "Which hotels are available?",
                "List the tourist spots",
            ],
            "timestamp": datetime.utcnow().isoformat(),
        }

    # Plan modification: remove a place from the itinerary.
    remove_match = any(kw in msg_lower for kw in REMOVE_KEYWORDS)
    if remove_match and trip:
        place = _extract_place_name(message)
        result, err = _remove_place_from_trip(trip_id, place)
        if err:
            return {
                "response": err,
                "suggestions": ["Remove another place", "Show me the updated plan", "Add a place back"],
                "timestamp": datetime.utcnow().isoformat(),
            }
        removed = ", ".join(result["removed"])
        total = result["newTotalCost"]
        return {
            "response": "Removed from the plan: %s. The itinerary now has %d items. "
                        "Updated total cost is Rs %s." % (removed, result["remainingItems"], total),
            "suggestions": ["Show me the updated plan", "Remove hotel", "Suggest transport"],
            "timestamp": datetime.utcnow().isoformat(),
        }

    # Alternate transport suggestion (validated against the real transport DB).
    trip_transport = bool(trip) and any(w in msg_lower for w in ["alternate", "alternative", "another "])
    if (any(w in msg_lower for w in TRANSPORT_KEYWORDS) or trip_transport) and trip:
        opts = _transport_suggestion(trip)
        if opts:
            lines = ["Alternate transport options for %s -> %s:" % (trip.get("origin"), trip.get("destination"))]
            for o in opts:
                lines.append("- %s (%s): Rs %s" % (o["name"], o["mode"], o["cost"]))
            return {
                "response": "\n".join(lines),
                "suggestions": ["Book the cheapest", "Show more options", "Remove a place"],
                "timestamp": datetime.utcnow().isoformat(),
            }
        return {
            "response": "No alternate approved transport is currently available for %s -> %s."
                        % (trip.get("origin"), trip.get("destination")),
            "suggestions": ["Show the route map", "Show transport options", "Help me plan"],
            "timestamp": datetime.utcnow().isoformat(),
        }

    # Generic dialectic responses (budget/food/delay/comfort) remain helpful.
    if any(w in msg_lower for w in ["reduce", "cheaper", "save", "budget"]):
        response = "I can help you reduce costs! Consider switching to budget-friendly flights and hotels. Would you like me to generate a budget-optimized plan?"
        suggestions = ["Generate budget plan", "Show cheaper hotels", "Reduce activity costs"]
    elif any(w in msg_lower for w in ["hotel", "stay", "accommodation"]):
        response = "Looking at hotel options for your trip. Your current selection is a great balance of comfort and value. Want to explore alternatives?"
        suggestions = ["Upgrade hotel", "Downgrade to budget", "Show hotel details"]
    elif any(w in msg_lower for w in ["vegetarian", "food", "restaurant", "diet"]):
        response = "I'll note your vegetarian preference! All restaurant recommendations will be filtered for vegetarian options."
        suggestions = ["Show veg restaurants", "Update food preference", "Add dietary restrictions"]
    elif any(w in msg_lower for w in ["delay", "what if", "reschedule"]):
        response = "If there's a flight delay, I can automatically replan your itinerary. Use the 'Simulate Delay' feature on your trip page to see how it works."
        suggestions = ["Simulate 3hr delay", "Simulate 5hr delay", "View replan options"]
    elif any(w in msg_lower for w in ["comfort", "upgrade", "premium"]):
        response = "Want to upgrade to a more comfortable experience? I can suggest premium flights, 5-star hotels, and exclusive activities."
        suggestions = ["Upgrade to premium", "Show premium options", "Compare plans"]
    elif any(w in msg_lower for w in ["budget", "cost", "spending", "price"]):
        if trip:
            est = trip.get("totalEstimatedCost", 0)
            budget = trip.get("budget", 0)
            response = "Your trip budget is Rs %s and estimated cost is Rs %s. %s" % (
                budget, est,
                "You have Rs %s remaining." % int(budget - est) if budget > est else "You are slightly over budget.")
        else:
            response = "Please select a trip first to see budget details."
        suggestions = ["View cost breakdown", "Optimize costs", "Switch to budget plan"]
    else:
        response = "I'm your AI travel assistant! I can help with trip planning, cost optimization, delay replanning, and food preferences. What would you like to know?"
        suggestions = ["Plan a trip", "Check budget", "Simulate delay", "Food preferences"]

    return {
        "response": response,
        "suggestions": suggestions,
        "timestamp": datetime.utcnow().isoformat(),
    }