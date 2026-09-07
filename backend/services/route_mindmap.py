"""Database + parameter driven travel journey flow for the Route Map.

This service builds a single continuous, connected travel pathway for an
arbitrary origin -> destination pair. It is consumed by /pages/mindmap.html and
by the AI chat flow responses.

Unlike the previous version there are no hardcoded routes, hotels or spots and
no emojis. Every stage is assembled at request time from the Mongo database:

- intercity transport options come from the *transports* collection
  (via ``available_transports``);
- hotels come from the *hotels* collection for the destination city;
- tourist spots come from the *tourist_spots* collection for the destination
  city.

Distances/durations/fares shown are whatever providers recorded; the platform
does not claim live transit availability, so figures are always descriptive.
"""

from config import TRANSPORT_TYPES
from services.mongodb import get_collection
from services.transport_service import available_transports

TYPE_GROUP = {
    "BUS": "Road",
    "TRAIN": "Rail",
    "FLIGHT": "Air",
    "CAB": "Road",
    "AUTO": "Road",
}


def _method(mode, distance, duration, route):
    return {"mode": mode, "distance": distance, "duration": duration, "route": route}


def _hotel_name(doc):
    return doc.get("name") or "Hotel"


def _spot_icon(_cat):
    return ""


def _hotel_category(doc):
    """Map a hotel's availability-weighted price into a coarse pricing band."""
    price = 0
    for rt in doc.get("roomTypes") or []:
        p = rt.get("pricePerNight") or 0
        if p > price:
            price = p
    if price <= 1500:
        return "budget"
    if price <= 3500:
        return "midrange"
    if price <= 8000:
        return "business"
    if price <= 20000:
        return "luxury"
    return "premium"


def _time(fn):
    return (fn or "").strip() or "—"


def _transport_service(t):
    """Single transport -> intercity option payload (one entry per vehicle)."""
    ttype = t.get("type", "")
    tariff = t.get("fare")
    cost = ""
    if isinstance(tariff, dict):
        for k in ("price", "baseFare", "sleeper", "seater"):
            if tariff.get(k) is not None:
                cost = "from Rs %s" % tariff[k]
                break
    elif tariff is not None:
        cost = "Rs %s" % tariff

    label = t["type"]
    if ttype == "BUS":
        label = "%s %s" % (t.get("serviceName") or "Bus", t.get("busNumber") or "")
    elif ttype == "TRAIN":
        label = "%s %s" % (t.get("trainName") or "Train", t.get("trainNumber") or "")
    elif ttype == "FLIGHT":
        label = "%s %s" % (t.get("serviceName") or "Flight", t.get("flightNumber") or "")
    elif ttype in ("CAB", "AUTO"):
        label = "%s (%s)" % (TRANSPORT_TYPES.get(ttype, {}).get("label", ttype),
                             t.get("vehicleType") or "local")

    departure = ""
    if ttype == "BUS":
        departure = "%s @ %s" % (t.get("boardingPoint") or "", _time(t.get("boardingTime")))
    elif ttype == "TRAIN":
        departure = "From %s" % (t.get("boardingStation") or "")
    elif ttype == "FLIGHT":
        departure = "%s -> %s" % (t.get("departureAirport") or "", t.get("arrivalAirport") or "")
    elif ttype in ("CAB", "AUTO"):
        departure = t.get("baseLocation") or ""

    return {
        "id": str(t["_id"]),
        "name": label.strip(),
        "note": t.get("serviceName") or "",
        "route": departure,
        "costRange": cost,
    }


def _transport_categories(origin, destination):
    """Build group-stage options, one per transport type present on the
    origin->destination corridor, each listing the real services."""
    types = {}
    for t in available_transports(origin, destination):
        ttype = t.get("type")
        if ttype not in TRANSPORT_TYPES:
            continue
        types.setdefault(ttype, []).append(t)
    order = ("FLIGHT", "TRAIN", "BUS", "CAB", "AUTO")
    out = []
    for ttype in order:
        if ttype not in types:
            continue
        svcs = types[ttype]
        classes = []
        for t in svcs:
            classes.append({
                "id": str(t["_id"]),
                "name": _transport_service(t)["name"],
                "note": (_transport_service(t)["route"] or ""),
                "costRange": _transport_service(t)["costRange"] or None,
            })
        out.append({
            "id": ttype.lower(),
            "name": TRANSPORT_TYPES[ttype]["label"],
            "note": "%s services" % TYPE_GROUP.get(ttype, "Travel"),
            "classes": classes,
        })
    return out


def _hotel_categories(destination):
    """Group destination hotels into coarse pricing bands (DB driven)."""
    hotels = get_collection("hotels").find({
        "city": {"$regex": destination, "$options": "i"},
        "status": "APPROVED",
    })
    groups = {}
    for h in hotels:
        band = _hotel_category(h)
        groups.setdefault(band, []).append(h)
    labels = {
        "budget": "Budget",
        "midrange": "Mid-Range",
        "business": "Business",
        "luxury": "Luxury",
        "premium": "Premium",
    }
    out = []
    for band, hot in groups.items():
        item = {
            "id": band,
            "name": labels.get(band, band.title()),
            "priceRange": _band_range(band),
        }
        item["hotels"] = [{
            "name": _hotel_name(h),
            "location": (h.get("location") or {}).get("name") or h.get("city") or "",
            "rating": float(h.get("starRating") or 0),
            "priceRange": _band_range(band),
            "amenities": [a for a in h.get("amenities") or [] if isinstance(a, str)][:4],
            "distanceFrom": "",
        } for h in hot]
        out.append(item)
    return out


def _band_range(band):
    return {
        "budget": "Rs 1,000 - 2,500 / night",
        "midrange": "Rs 2,500 - 5,000 / night",
        "business": "Rs 5,000 - 12,000 / night",
        "luxury": "Rs 12,000 - 25,000 / night",
        "premium": "Rs 25,000+ / night",
    }.get(band, "Varies")


def _spots(destination):
    """Destination tourist spots from the DB (min payload the UI renders)."""
    spots = get_collection("tourist_spots").find({
        "$or": [
            {"city": {"$regex": destination, "$options": "i"}},
            {"location.city": {"$regex": destination, "$options": "i"}},
        ],
        "status": "APPROVED",
    }).sort("popularity", -1)
    out = []
    for s in spots:
        loc = s.get("location") or {}
        best = ""
        times = s.get("recommendedTimes") or s.get("optimalTimes") or []
        if times:
            first = times[0]
            best = "%s - %s" % (first.get("from") or "", first.get("to") or "")
        out.append({
            "id": s["_id"],
            "name": s.get("name") or "Spot",
            "category": s.get("category") or "",
            "bestTime": best,
            "reach": _spot_reach(s, destination),
        })
    return out


def _spot_reach(spot, destination):
    """Best-effort reachability: local transport modes out of the destination."""
    loc = spot.get("location") or {}
    name = loc.get("name") or spot.get("city") or destination
    return [{
        "from": "City centre (%s)" % destination,
        "methods": [
            _method("App-based cab", "", "15-45 min", "Direct to %s" % (spot.get("name") or "")),
            _method("Local bus", "", "30-60 min", "City routes towards %s" % name),
            _method("Auto / Taxi", "", "15-40 min", "Metered / negotiated city ride"),
        ],
    }]


def get_journey_flow(origin="Coimbatore", destination="Chennai"):
    """Build a connected, DB-driven journey flow for origin -> destination."""
    trans_cats = _transport_categories(origin, destination)
    hotel_cats = _hotel_categories(destination)
    spots = _spots(destination)

    stages = [
        {
            "id": "origin",
            "title": origin,
            "subtitle": "Journey starts here. Pick a way to travel to %s." % destination,
            "type": "info",
        },
        {
            "id": "intercity",
            "title": "%s -> %s" % (origin, destination),
            "subtitle": "Choose a mode and a service to travel between the two places.",
            "type": "group",
            "info": "Live transport options loaded from approved providers. Figures are as recorded by providers.",
            "options": trans_cats or [{
                "id": "none",
                "name": "No transport available",
                "note": "No approved %s -> %s services yet." % (origin, destination),
                "classes": [],
            }],
        },
        {
            "id": "arrival",
            "title": "Arrival in %s" % destination,
            "subtitle": "Once you arrive in %s you can go to a hotel or straight to the tourist spots." % destination,
            "type": "info",
        },
        {
            "id": "branch",
            "title": "What next in %s?" % destination,
            "subtitle": "You can go to a hotel first or head straight to the sights.",
            "type": "branch",
            "options": [
                {"id": "hotel", "name": "Go to a hotel first",
                 "desc": "Drop your bags, freshen up, then explore."},
                {"id": "direct", "name": "Visit tourist spots directly",
                 "desc": "Start sightseeing immediately after arrival."},
            ],
        },
    ]

    if trans_cats:
        stages.append({
            "id": "hotel-reach",
            "title": "Reaching your stay",
            "subtitle": "Typical ways to get from your arrival point to a hotel.",
            "type": "reach",
            "depends": {"branch": "hotel"},
            "active": True,
            "from": [
                {"from": "Arrival point", "methods": [
                    _method("App-based cab", "", "15-45 min", "Direct to the hotel"),
                    _method("Auto / Taxi", "", "20-60 min", "Metered / negotiated"),
                    _method("Public transport", "", "30-75 min", "City routes to the hotel area"),
                ]},
            ],
        })

    stages.append({
        "id": "hotel-categories",
        "title": "Hotels in %s" % destination,
        "subtitle": "Pick a category, then choose a hotel (real approved properties).",
        "type": "hotels",
        "depends": {"branch": "hotel"},
        "categories": hotel_cats or [{
            "id": "no-hotel",
            "name": "No hotels yet",
            "priceRange": "",
            "hotels": [],
        }],
    })

    stages.append({
        "id": "tourist-spots",
        "title": "Tourist spots in %s" % destination,
        "subtitle": "Choose a spot, then see how to reach it from your current location.",
        "type": "spots",
        "depends": {"branch": "set"},
        "spots": spots or [{
            "id": "none",
            "name": "No spots yet",
            "category": "",
            "bestTime": "",
            "reach": [],
        }],
    })

    stages.append({
        "id": "return",
        "title": "Return / continue journey",
        "subtitle": "Keep exploring or head back to %s." % origin,
        "type": "return",
        "options": [
            {"id": "more", "name": "Visit another tourist spot",
             "desc": "Chain the next destination."},
            {"id": "back", "name": "Return to %s" % origin,
             "desc": "Travel back the way you came."},
        ],
    })

    return {
        "id": "%s-%s" % (origin.lower().replace(" ", "-"), destination.lower().replace(" ", "-")),
        "title": "%s -> %s" % (origin, destination),
        "tagline": "One continuous, connected journey. Start at %s, choose how to travel, "
                   "and follow the path to your hotel or %s's tourist spots." % (origin, destination),
        "start": origin,
        "stages": stages,
    }
