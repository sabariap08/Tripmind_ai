"""Server-side distance estimation for origin-to-destination corridors.

Uses the Google Maps Routes API (computeRoutes) when GOOGLE_MAPS_API_KEY is
configured, falling back to the haversine formula when exact coordinates are
known, and returning None when no distance can be resolved.  Results are
cached per corridor so repeated planning calls stay fast.
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


def _google_route_km(origin, destination):
    if not GOOGLE_MAPS_API_KEY:
        return None
    try:
        body = json.dumps({
            "origin": {"address": origin},
            "destination": {"address": destination},
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
            return None
        meters = routes[0].get("distanceMeters")
        if not meters:
            return None
        km = round(float(meters) / 1000.0, 2)
        return km if km > 0 else None
    except Exception:
        return None


def route_distance_km(origin, destination, origin_lat=None, origin_lng=None,
                      dest_lat=None, dest_lng=None):
    """Best-effort driving distance between the corridor ends, in km.

    The Google Routes API is consulted first (it accepts place names like
    "Chennai"), then haversine on the supplied coordinates, and finally None
    so callers can degrade gracefully.
    """
    if not origin or not destination:
        return None
    key = str(origin).strip().lower() + "\x1f" + str(destination).strip().lower()
    if key in _CACHE:
        return _CACHE[key]
    km = _google_route_km(origin, destination)
    if km is None:
        km = _haversine_km(origin_lat, origin_lng, dest_lat, dest_lng)
    if km is not None:
        km = round(float(km), 2)
    _CACHE[key] = km
    return km