"""Real weather for TripMind (WeatherAPI.com).

Every value returned here comes from WeatherAPI — nothing is guessed. When the
service cannot answer (no key, quota, network, dates beyond the free forecast
window) the caller receives {"available": False, "reason": ...} and must show
"weather unavailable" instead of inventing conditions.
"""

import json
import os
import time
import urllib.parse
import urllib.request

from config import WEATHER_API_KEY

_BASE = "https://api.weatherapi.com/v1"
_CACHE_TTL = 600  # seconds
_cache = {}


def _get(path, params, timeout=7):
    query = urllib.parse.urlencode(dict(params, key=WEATHER_API_KEY))
    req = urllib.request.Request(
        "%s/%s?%s" % (_BASE, path, query),
        headers={"User-Agent": "TripMind/1.0"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _unavailable(reason):
    return {"available": False, "source": "weatherapi.com", "reason": reason,
            "city": None, "current": None, "tripForecast": None,
            "tripForecastNote": None, "summary": None}


def fetch_weather(city, start_date=None, end_date=None):
    """Current conditions + best-effort 3-day forecast for the trip window.

    Returns a dict with an honest `available` flag:
      current     - real "now" reading for the destination city
      tripForecast- real forecast days that fall inside [start_date, end_date]
                    (free plan covers ~3 days; usually None for far-off trips)
      summary     - one short line built from whichever real data exists
    """
    city = (city or "").strip()
    if not city:
        return _unavailable("No destination city to look up weather for.")
    if not WEATHER_API_KEY:
        return _unavailable("WEATHER_API_KEY is not configured.")

    cache_key = "%s|%s|%s" % (city.lower(), (start_date or "")[:10],
                              (end_date or "")[:10])
    hit = _cache.get(cache_key)
    if hit and time.time() - hit[0] < _CACHE_TTL:
        return dict(hit[1])

    try:
        cur_raw = _get("current.json", {"q": city, "aqi": "no"})
        fc_raw = _get("forecast.json", {"q": city, "days": "3"})
    except Exception as e:
        return _unavailable("Weather service call failed: %s" % e)

    loc = (cur_raw.get("location") or {})
    cur = (cur_raw.get("current") or {})
    if not cur:
        return _unavailable("Weather service returned no current conditions for '%s'." % city)

    current = {
        "tempC": float(cur.get("temp_c") or 0),
        "condition": str((cur.get("condition") or {}).get("text") or "Unknown"),
        "humidity": int(cur.get("humidity") or 0),
        "feelsC": float(cur.get("feelslike_c") or 0),
    }

    start = (start_date or "")[:10]
    end = (end_date or "")[:10]
    forecast_days = ((fc_raw.get("forecast") or {}).get("forecastday")) or []
    trip_days = []
    for day in forecast_days:
        d = str(day.get("date") or "")
        if start and end and start <= d <= end:
            day_c = (day.get("day") or {})
            hour_rain = max(
                (int((h.get("chance_of_rain") or 0))
                 for h in (day.get("hour") or [])),
                default=int(day_c.get("daily_chance_of_rain") or 0))
            trip_days.append({
                "date": d,
                "maxC": float(day_c.get("maxtemp_c") or 0),
                "minC": float(day_c.get("mintemp_c") or 0),
                "condition": str((day_c.get("condition") or {}).get("text") or "Unknown"),
                "rainChancePct": hour_rain,
            })

    result = {
        "available": True,
        "source": "weatherapi.com",
        "reason": None,
        "city": str(loc.get("name") or city),
        "current": current,
        "tripForecast": {"days": trip_days} if trip_days else None,
        "tripForecastNote": None,
        "summary": None,
    }
    if trip_days:
        warmest = max(d["maxC"] for d in trip_days)
        rainiest = max(d["rainChancePct"] for d in trip_days)
        result["summary"] = "%.0f°C / %s%s" % (
            warmest, trip_days[0]["condition"],
            " · %d%% rain possible" % rainiest if rainiest >= 40 else "")
    else:
        result["tripForecastNote"] = (
            "Free forecast covers the next 3 days only; showing current "
            "conditions in %s instead of guessing trip-date weather." % result["city"])
        result["summary"] = "%.0f°C · %s (current)" % (
            current["tempC"], current["condition"])

    _cache[cache_key] = (time.time(), result)
    return dict(result)
