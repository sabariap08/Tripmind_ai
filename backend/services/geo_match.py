"""Place-name matching that cannot match the wrong place.

The bug this replaces
---------------------
Catalogue lookups used ``{"$regex": city, "$options": "i"}`` -- an *unanchored,
unescaped* substring match against the raw user string. That single pattern
appears in eight places and it is why a Coimbatore -> Chennai trip came back
with Ooty Lake and Kovai Kondattam:

    "Chennai"  matches  "Chennai Gate", "Chennai Egmore"
    "Salem"    matches  "Thiruchengode near Salem"
    "Ooty"     matches  any record that merely mentions Ooty
    ".*term.*" (in the chatbot)  matches  almost everything

Because ``_gather_db_data`` feeds these results straight into the AI planner as
the *only* candidate set, the model was never given the chance to do better: it
was asked to plan a Chennai trip out of a bag of wrong-city places. No amount of
prompt work fixes a wrong candidate set, so the filter has to be right first.

What a place name means here
----------------------------
A listing can carry the place in several fields (``city``, ``location.city``,
``location.district``, ``location.name``, ``name``), each optional and each
written by a different partner. So "does this listing belong to Chennai" is a
question about a *set* of fields, not one field. This module:

* anchors and escapes the term, so the pattern is literal and exact;
* accepts a handful of genuinely-equivalent spellings (case, whitespace,
  punctuation, "The Nilgiris"/"Nilgiris") rather than a blind prefix match;
* treats a listing as *in place* when any of its location fields matches;
* can report listings that are merely *nearby* (same district / same state,
  within a radius) separately, so the planner can offer an excursion honestly
  instead of silently smuggling in Ooty.

Deliberate non-goal: no fuzzy string similarity. "Coimbatore" and "Kovai" are
the same city to a human, but silently rewriting one into the other would let a
wrong place through - which is the exact failure we are removing.
"""
from __future__ import annotations

import math
import re

# Equivalent names for the same place. Kept explicit and small: every entry
# here is a name a Tamil Nadu listing legitimately uses in the field.
PLACE_ALIASES = {
    "the nilgiris": {"nilgiris"},
    "nilgiris": {"nilgiris", "the nilgiris"},
    "kovai": {"coimbatore", "kovai"},
    "coimbatore": {"coimbatore", "kovai"},
    "trichy": {"tiruchirappalli", "trichy"},
    "tiruchirappalli": {"tiruchirappalli", "trichy"},
    "tn": {"tamil nadu"},
    "tamilnadu": {"tamil nadu"},
}

# Names that mean "the whole journey" rather than a sightseeing destination.
# Matching against these would defeat destination scoping entirely.
NOT_A_DESTINATION = {
    "india", "tamilnadu", "tamil nadu", "tn", "all", "any", "anywhere",
    "multiple", "various", "nationwide", "country",
}

_WORD_SPLIT = re.compile(r"[^a-z0-9]+")


def norm(value):
    """Lowercase, strip punctuation, collapse whitespace."""
    if not value:
        return ""
    return _WORD_SPLIT.sub(" ", str(value).lower()).strip()


def variants(value):
    """Every spelling of ``value`` that still means the same place."""
    base = norm(value)
    if not base:
        return []
    out = {base}
    out |= PLACE_ALIASES.get(base, set())
    for alt in PLACE_ALIASES.get(base, ()):  # symmetric lookup
        out |= PLACE_ALIASES.get(alt, set())
    return sorted(v for v in out if v)


def is_destination(value):
    """False for tokens that must never be used to scope sightseeing."""
    return norm(value) not in NOT_A_DESTINATION


def _exact_query(values):
    """An anchored, escaped matcher for any spelling of the given places.

    Uses compiled patterns rather than ``{"$regex": ...}`` documents: Mongo
    rejects a document nested inside ``$in``, and a compiled pattern is the
    portable form that works in both an ``$in`` list and on its own.
    """
    patterns = []
    for value in values:
        for spelling in variants(value):
            pattern = re.compile("^%s$" % re.escape(spelling), re.IGNORECASE)
            if not any(p.pattern == pattern.pattern for p in patterns):
                patterns.append(pattern)
    if not patterns:
        return None
    if len(patterns) == 1:
        return patterns[0]
    return {"$in": patterns}


# Location fields a listing may use, most specific first.
_LOCATION_FIELDS = ("location.city", "location.district", "city", "district")


def place_query(value, fields=None, include_state=False, state=None):
    """Mongo filter selecting documents that belong to ``value``.

    ``fields`` limits which location fields are considered. ``include_state``
    additionally matches the state, which is only appropriate when the caller
    genuinely wants a statewide search rather than a destination-scoped one.
    """
    fields = fields or _LOCATION_FIELDS
    if not norm(value):
        # The caller passed something that normalises to nothing (empty, or
        # punctuation only such as ".*" / ".."). Returning {} here would mean
        # "no filter", i.e. the whole catalogue - which is exactly the leak
        # this module exists to close. Match nothing instead.
        #
        # The sentinel has to be `$exists: True` on a field no document can
        # have. `$exists: False` is the *inverse* of "match nothing": because
        # no document carries this field, it is true for every document and
        # the filter silently returns the entire catalogue again.
        return {"__tm_match_nothing__": {"$exists": True}}
    exact = _exact_query([value])
    if exact is None:
        return {"__tm_match_nothing__": {"$exists": True}}
    ors = [{field: exact} for field in fields]
    if include_state and state:
        state_q = _exact_query([state])
        if state_q is not None:
            ors.append({"location.state": state_q})
    if len(ors) == 1:
        return ors[0]
    return {"$or": ors}


def matches_place(doc, value, fields=None):
    """True when this listing belongs to ``value``."""
    fields = fields or _LOCATION_FIELDS
    wanted = set(variants(value))
    if not wanted:
        return False
    for field in fields:
        node = doc
        for part in field.split("."):
            if not isinstance(node, dict):
                node = None
                break
            node = node.get(part)
        if norm(node) in wanted:
            return True
    return False


def _haversine_km(lat1, lng1, lat2, lng2):
    try:
        lat1, lng1, lat2, lng2 = (float(x) for x in (lat1, lng1, lat2, lng2))
    except (TypeError, ValueError):
        return None
    radius = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * radius * math.asin(min(1.0, math.sqrt(a)))


def coordinates(doc):
    loc = doc.get("location") if isinstance(doc.get("location"), dict) else {}
    lat = loc.get("lat", doc.get("lat"))
    lng = loc.get("lng", doc.get("lng"))
    try:
        return float(lat), float(lng)
    except (TypeError, ValueError):
        return None, None


def nearby(doc, value, reference, radius_km=60.0):
    """Nearby-excursion test: same state, within ``radius_km`` of the place.

    Used to *label* an out-of-city attraction as an excursion rather than to
    admit it silently. The caller decides whether the user's trip allows it.
    A listing with no coordinates is never "nearby" - we cannot prove it, and
    guessing is how the wrong place gets in.
    """
    ref_lat, ref_lng = coordinates(reference)
    lat, lng = coordinates(doc)
    if ref_lat is None or lat is None:
        return False
    ref_state = norm((reference.get("location") or {}).get("state"))
    doc_state = norm((doc.get("location") or {}).get("state"))
    if ref_state and doc_state and ref_state != doc_state:
        return False
    distance = _haversine_km(ref_lat, ref_lng, lat, lng)
    return distance is not None and distance <= radius_km