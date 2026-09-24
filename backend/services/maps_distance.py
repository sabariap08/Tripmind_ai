"""Server-side distance estimation for origin-to-destination corridors.

Uses the Google Maps Routes API (computeRoutes) when GOOGLE_MAPS_API_KEY is
configured, falling back to the haversine formula when exact coordinates are
known, and returning None when no distance can be resolved.  Results are
cached per corridor so repeated planning calls stay fast.

Debug output: every real route lookup logs a
    ========== TRIPMIND DISTANCE DEBUG ==========
block with the request coordinates, the API result and (on failure) an
explicit [TripMind] DISTANCE-ERROR line.  API keys are never logged.
"""
import json
import math
import urllib.request

from config import GOOGLE_MAPS_API_KEY

_CACHE = {}


def _haversine_km(a, b, c, d):
    for v in (a, b, c, d):
        if v is None:
            return None
    try:
        lat1, lon1, lat2, lon2 = map(math.radians, (float(a), float(b), float(c), float(d)))
    except (TypeError, ValueError):
        return None
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(h))


def _point(address=None, lat=None, lng=None):
    """Build a Routes API origin/destination waypoint.

    Prefers exact coordinates; falls back to the address string so the same
    helper works for both the fare engine and corridor lookups.
    """
    if lat is not None and lng is not None:
        try:
            la, ln = float(lat), float(lng)
        except (TypeError, ValueError):
            la, ln = None, None
        if la is not None and ln is not None:
            return {"location": {"latLng": {"latitude": la, "longitude": ln}}}
    if address:
        return {"address": address}
    return None


def _google_route_km(origin_point, destination_point):
    """Call the Routes API for two already-built waypoint dicts.

    Returns the road distance in km (rounded to 2dp) or None.  On failure an
    explicit [TripMind] DISTANCE-ERROR line is logged with the real reason so a
    UI never silently falls back to a made-up fare.
    """
    if not GOOGLE_MAPS_API_KEY:
        print("[TripMind] DISTANCE-ERROR: GOOGLE_MAPS_API_KEY is not configured; "
              "cannot measure real road distance.")
        return None
    if origin_point is None or destination_point is None:
        print("[TripMind] DISTANCE-ERROR: missing origin/destination waypoint "
              "(unknown coordinates or address).")
        return None
    try:
        body = json.dumps({
            "origin": origin_point,
            "destination": destination_point,
            "travelMode": "DRIVE",
            "units": "METRIC",
        }).encode("utf-8")
        req = urllib.request.Request(
            "https://routes.googleapis.com/directions/v2:computeRoutes",
            data=body,
            headers={
                "Content-Type": "application/json",
                "X-Goog-Api-Key": GOOGLE_MAPS_API_KEY,
                "X-Goog-FieldMask": "routes.distanceMeters,routes.duration",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        routes = data.get("routes") or []
        if not routes:
            print("[TripMind] DISTANCE-ERROR: Google returned no routes for this pair.")
            return None
        meters = routes[0].get("distanceMeters")
        if not meters:
            print("[TripMind] DISTANCE-ERROR: Google route had no distanceMeters.")
            return None
        km = round(float(meters) / 1000.0, 2)
        if km <= 0:
            print("[TripMind] DISTANCE-ERROR: Google route distance was 0.")
            return None
        return km
    except Exception as e:
        print("[TripMind] DISTANCE-ERROR: Google Routes API call failed: %s" % e)
        return None


def _cache_key(a, b, c, d):
    key = "|null|" if a is None else str(a).strip().lower()
    key += "|null|" if b is None else str(b).strip().lower()
    key += "|null|" if c is None else str(c).strip().lower()
    key += "|null|" if d is None else str(d).strip().lower()
    return key


def route_distance_km(origin, destination, origin_lat=None, origin_lng=None,
                      dest_lat=None, dest_lng=None, label="corridor",
                      log=True):
    """Best-effort driving distance between the corridor ends, in km.

    The Google Routes API is consulted first with whatever waypoint detail is
    available (coordinates trump addresses), then haversine on the supplied
    coordinates, and finally None so callers can degrade gracefully.

    Passing label (e.g. "home->boarding") makes the [TripMind] debug line
    self-describing in the terminal.
    """
    if not origin and not (origin_lat is not None and origin_lng is not None):
        return None
    if not destination and not (dest_lat is not None and dest_lng is not None):
        return None
    key = _cache_key(origin, destination, origin_lat, dest_lat)
    if key in _CACHE:
        return _CACHE[key]

    km = None
    source = None
    origin_p = _point(origin, origin_lat, origin_lng)
    dest_p = _point(destination, dest_lat, dest_lng)
    km = _google_route_km(origin_p, dest_p)
    if km is not None:
        source = "google"
    else:
        km = _haversine_km(origin_lat, origin_lng, dest_lat, dest_lng)
        if km is not None:
            source = "haversine"

    if log:
        print("========== TRIPMIND DISTANCE DEBUG ==========")
        print("[TripMind] lookup=%s" % label)
        print("[TripMind] origin=%r lat=%s lng=%s" % (origin, origin_lat, origin_lng))
        print("[TripMind] dest=%r lat=%s lng=%s" % (destination, dest_lat, dest_lng))
        if source:
            print("[TripMind] distance_km=%.2f source=%s" % (km, source))
        else:
            print("[TripMind] distance_km=UNKNOWN source=none (explicit error above)")
        print("========== TRIPMIND DISTANCE DEBUG ==========")

    if km is not None:
        km = round(float(km), 2)
    _CACHE[key] = km
    return km