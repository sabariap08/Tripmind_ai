"""Place imagery: a photo that provably belongs to the place it is shown on.

Why this module exists
----------------------
TripMind used to pick destination artwork by reusing a small pool of famous
landmark photos. That produced the reported bug directly: Kapaleeshwarar
Temple was illustrated with a photograph of the Taj Mahal, Fort St. George with
a Rajasthani fort, and an amusement park with a tropical beach. Reordering an
array would not have fixed it - the images simply did not belong to the places.

The rule this module enforces
-----------------------------
    real place photo  ->  use it
    none available    ->  use the neutral TripMind placeholder

It never substitutes a different landmark, and it never invents an association.

Provenance, not guesswork
-------------------------
Photos come from Wikimedia Commons, whose API returns the *file title* with
every result. The title is the provenance: "Marina Beach in Chennai.jpg" is
self-evidently a photo of Marina Beach, so the association can be checked
without eyeballing pixels. ``_score`` only keeps a result when a distinctive
token from the place name actually appears in the file title, which is what
stops an unrelated landmark from sneaking in under a matching category word.

Optional tiers, in order
------------------------
1. ``partner_upload`` - images the listing owner uploaded. Correct by
   construction; used as-is and never re-fetched.
2. ``google_places``  - the place's own Google photo, when a Places-capable
   key is configured (off by default: a Maps JS key is not a Places key and we
   will not pretend otherwise).
3. ``wikimedia_commons`` - verified public-domain / CC photos, cached here.
4. ``placeholder``    - the neutral branded SVG.

Caching: results are memoised in Mongo (``place_image_cache``) and in-process,
so the landing page never re-requests the same place photo.
"""
from __future__ import annotations

import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from services.mongodb import get_collection

# Neutral, deliberately generic travel/location artwork. A placeholder always
# beats a wrong photograph.
PLACEHOLDER_URL = "/img/place-placeholder.svg"
PLACEHOLDER_SOURCES = {"placeholder"}

COMMONS_ENDPOINT = "https://commons.wikimedia.org/w/api.php"
COMMONS_SEARCH = "https://commons.wikimedia.org/w/api.php"
USER_AGENT = "TripMindAI/1.0 (place imagery; +https://tripmind.example)"
CACHE_TTL_DAYS = 90
HTTP_TIMEOUT = 6.0
MAX_RESULTS = 12

# Files Commons indexes that are not usable photographs.
_BAD_EXT = (".svg", ".pdf", ".tif", ".tiff", ".ogv", ".webm", ".gif", ".djvu", ".xcf")

# Words that describe a *category* of place rather than a specific one. They
# can corroborate a match but can never establish one on their own - otherwise
# "Fort St. George" would happily accept a photo of an unrelated fort.
GENERIC_TOKENS = frozenset("""
india indian tamil nadu state district city town village country asia
beach sand sea coast shore ocean fort fortress fortification castle palace
temple gopuram shrine church cathedral mosque basilica matha mandir
lake pond reservoir river waterfalls waterfall
park garden gardens zoo amusement waterpark
hotel resort lodge homestay inn restaurant cafe food
station junction railway airport port harbour harbor bridge
road street streetview view views photo photograph image picture
hill hills mountain mountains peak valley
memorial statue statue monument st saint sri
house home building tower gopurams entrance gate
national wildlife sanctuary
""".split())

# Tokens that must never be treated as distinctive on their own.
_EXTRA_GENERIC = frozenset(["st", "saint", "sri", "new", "old", "the", "of", "and"])

# Words that legitimately appear in a Commons file title without being part of
# the place's own name. Used only by the foreign-proper-noun check, so that
# "Chennai Marina Beach" is not rejected for mentioning Chennai.
_GEO_OK = frozenset("""
chennai coimbatore ooty madurai pondicherry thanjavur tiruchirappalli
trichy tirunelveli nellai erode salem namakkal karur dindigul thanjavur
kumbakonam thani rameswaram kanniyakumari suhelnathi puducherry
tamilnadunadu tamil india indian asia
north south east west central upper lower new old
panorama panoramic view street road entrance gate front rear side
exterior interior outside inside garden gardens park lane
photograph photo picture image pic day night sunrise sunset morning evening
resort hotel lodge homestay inn restaurant cafe food court club
district state country city town village municipality corporation
committee government department tourism travel tourist visitors
wikipedia wikimedia commons file
""".split())

# Listing kinds where a photo must additionally be free of foreign proper nouns.
# A spot ("Mahabalipuram Shore Temple") is identified by its distinctive name,
# so a title may mention a nearby city freely. A business is not: accepting
# "Grand Padappai Residency Chennai" as a photo of "Grand Chennai Residency" is
# a different real hotel, and showing it is the same class of mistake as
# showing the Taj Mahal for a Tamil temple.
_BUSINESS_KINDS = frozenset(("hotel", "restaurant", "transport", "tour"))

_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
# Commons titles are filenames. Without stripping the extension, "Chennai.jpg"
# tokenises as the proper noun "Chennai.jpg" and every result looks foreign.
_TITLE_EXT = re.compile(r"\.(?:jpe?g|png|webp|gif|tiff?|bmp|svg|og[vg]|webm|ogg|"
                         r"wav|jp2|jpx|pdf|djvu|xcf)$", re.I)

_mem_cache = {}
_mem_lock = threading.Lock()


# --------------------------------------------------------------------------- helpers
def _norm(text):
    """Lowercase, strip punctuation, collapse whitespace."""
    if not text:
        return ""
    text = str(text).lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _tokens(text):
    return [t for t in _norm(text).split(" ") if t]


def _place_key(name, city=None, district=None, state=None):
    """Stable cache key for a place. Name always leads, so two different places
    that happen to share a city never collide."""
    base = _norm(name)
    if not base:
        return ""
    return "|".join(p for p in (base, _norm(city), _norm(district)) if p)


def _is_generic(token):
    return token in GENERIC_TOKENS or token in _EXTRA_GENERIC or len(token) <= 2


def _title_words(title):
    """Capitalised words in a Commons file title, split on spaces and
    camel-case boundaries ("Murarrie", "Padappai", "WUS01478")."""
    words = []
    for chunk in re.split(r"[\s_\-/,()\[\]:]+", title or ""):
        chunk = _TITLE_EXT.sub("", chunk or "")
        if not chunk:
            continue
        words.extend(w for w in _CAMEL_BOUNDARY.split(chunk) if w)
    return words


def _foreign_proper_nouns(title, name):
    """Proper nouns in ``title`` that the place's own name does not contain.

    ``title`` is a raw Commons filename such as
    "Chennai-Fort St. George-St. Mary's Church-WUS01478.jpg". Capitalisation is
    the only provenance signal available, so a word counts as a proper noun when
    it is capitalised, alphabetic, long enough to be identifying, and is neither
    part of the place name nor in the geography/photography allow-list.

    Returns those words, or ``[]`` when the title introduces nothing new.
    """
    name_norm = _norm(name)
    foreign = []
    for index, word in enumerate(_title_words(title)):
        # Sentence-initial capitalisation carries no information.
        if index == 0 or not word[:1].isupper():
            continue
        bare = word.strip(".,")
        low = _norm(bare)
        if len(low) < 4 or not low.replace(" ", "").isalnum():
            continue
        if low in _GEO_OK or _is_generic(low.split(" ")[0]):
            continue
        if low and low in name_norm:
            continue
        foreign.append(bare)
    return foreign


def _score(title, name, city, district, kind="spot"):
    """How well does this file title belong to this place?

    Returns ``(score, ok)``. ``ok`` is False whenever the title is not
    demonstrably about this place, which is the guard that prevents a
    famous-but-wrong landmark from being shown.

    Three rules, in order of confidence:

    1. The full place name appears verbatim in the title - accept outright.
       "Chennai Marina Beach in 2022.jpg" for "Marina Beach".
    2. Otherwise the title must be *geographically corroborated*: it has to name
       the place's own city or district. Without this, "Marina Deck" (a Chennai
       restaurant) matched "Marina Bay Sands, Singapore" and "Marina Gateway"
       matched a Mumbai bridge, because both contain the word "marina".
    3. For businesses, the title may not introduce a proper noun the place name
       does not contain, which is what separates this hotel from a different
       hotel in the same city.
    """
    title_tokens = set(_tokens(title))
    if not title_tokens:
        return 0.0, False

    name_tokens = _tokens(name)
    if not name_tokens:
        return 0.0, False

    distinctive = [t for t in name_tokens if not _is_generic(t)]
    corroborating = [t for t in name_tokens if _is_generic(t)]

    # Rule 1: the full name appearing verbatim is the strongest signal.
    #
    # It is *not* strong enough for a name built entirely from generic words:
    # "City Park" is a substring of "File:City Park Kolkata.jpg", so the
    # verbatim test alone would happily illustrate a Chennai listing with a
    # Kolkata park. Such names must fall through to the city check instead.
    if distinctive and _norm(name) and _norm(name) in _norm(title):
        if kind in _BUSINESS_KINDS and _foreign_proper_nouns(title, name):
            return 0.0, False
        return 6.0, True

    hit_distinctive = sum(1 for t in distinctive if t in title_tokens)
    hit_generic = sum(1 for t in corroborating if t in title_tokens)
    hit_city = 1 if _norm(city) and _norm(city) in title_tokens else 0
    hit_district = 1 if _norm(district) and _norm(district) in title_tokens else 0

    # A place made only of generic words ("City Park") cannot be identified by
    # title alone, so we require the city as well before accepting anything.
    if distinctive:
        if hit_distinctive == 0:
            return 0.0, False
    else:
        if not (hit_city or hit_district):
            return 0.0, False

    # Rule 2: without a verbatim hit, demand geographic corroboration. This is
    # the difference between "a photo of a Marina somewhere" and "a photo of
    # this Marina". Combined with the generic-name check above it is also what
    # rejects a generic name paired with the wrong city.
    if not (hit_city or hit_district):
        return 0.0, False

    # Rule 3: a business must not borrow a photo of a different business.
    if kind in _BUSINESS_KINDS and _foreign_proper_nouns(title, name):
        return 0.0, False

    score = (2.0 * hit_distinctive) + (0.5 * hit_generic) + hit_city + hit_district
    # Prefer real photographs of the place itself over incidental mentions.
    if hit_distinctive:
        score += 1.0
    return score, True


# --------------------------------------------------------------------- commons client
def _commons_search(query, limit=MAX_RESULTS):
    params = {
        "action": "query",
        "format": "json",
        "formatversion": "2",
        "generator": "search",
        "gsrnamespace": "6",          # File: namespace only
        "gsrsearch": query,
        "gsrlimit": str(limit),
        "prop": "imageinfo",
        "iiprop": "url|size|extmetadata",
        "iiurlwidth": "800",
    }
    url = COMMONS_SEARCH + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                               "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return []
    pages = (data.get("query") or {}).get("pages") or []
    return pages if isinstance(pages, list) else []


def _licence(info):
    meta = info.get("extmetadata") or {}
    lic = ((meta.get("LicenseShortName") or {}).get("value") or "").strip()
    artist = ((meta.get("Artist") or {}).get("value") or "").strip()
    artist = re.sub(r"<[^>]+>", "", artist)[:120]
    return {"license": lic, "author": artist}


def fetch_verified_images(name, city=None, district=None, state=None, limit=5, kind="spot"):
    """Search Commons and keep only results whose title belongs to the place."""
    queries = []
    if city:
        queries.append("%s %s" % (name, city))
    queries.append(name)
    if district and district not in (city, state):
        queries.append("%s %s" % (name, district))

    seen_urls = set()
    scored = []
    for query in queries:
        for page in _commons_search(query):
            title = page.get("title") or ""
            if not title or any(title.lower().endswith(e) for e in _BAD_EXT):
                continue
            info = (page.get("imageinfo") or [{}])[0]
            thumb = info.get("thumburl") or info.get("url")
            if not thumb or thumb in seen_urls:
                continue
            # Skip anything too small to be a usable card image.
            if int(info.get("thumbwidth") or 0) < 500:
                continue
            score, ok = _score(title, name, city, district, kind=kind)
            if not ok:
                continue
            seen_urls.add(thumb)
            scored.append({
                "url": thumb,
                "title": title,
                "score": score,
                "provider": "wikimedia_commons",
                **_licence(info),
            })
        if len(scored) >= limit * 2:
            break

    scored.sort(key=lambda r: (-r["score"], r["title"]))
    out = []
    for row in scored[:limit]:
        row.pop("score", None)
        out.append(row)
    return out


# ------------------------------------------------------------------------- caching
_MISS = object()


def _cache_get(key):
    """Return the cached list, or ``_MISS``.

    The distinction between "never looked up" and "looked up, nothing found"
    matters: both are false-y as plain lists, so returning ``[]`` for the
    latter would make the resolver re-query Commons on *every* page render for
    every place that has no photo. That is exactly the load the cache exists to
    avoid, so a distinct sentinel is returned instead.
    """
    if not key:
        return _MISS
    now = time.time()
    with _mem_lock:
        hit = _mem_cache.get(key)
    if hit is not None and now - hit[0] < CACHE_TTL_DAYS * 86400:
        return list(hit[1])
    try:
        doc = get_collection("place_image_cache").find_one({"_id": key})
    except Exception:
        return _MISS
    if not doc:
        return _MISS
    fetched = doc.get("fetchedAtTs") or 0
    if now - fetched > CACHE_TTL_DAYS * 86400:
        return _MISS
    value = list(doc.get("images") or [])
    with _mem_lock:
        _mem_cache[key] = (fetched, value)
    return value


def _cache_put(key, images, name, city, district):
    if not key:
        return
    now = time.time()
    with _mem_lock:
        _mem_cache[key] = (now, images)
    try:
        get_collection("place_image_cache").update_one(
            {"_id": key},
            {"$set": {
                "name": name, "city": city, "district": district,
                "images": images, "fetchedAtTs": now,
                "fetchedAt": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(now)),
            }},
            upsert=True,
        )
    except Exception:
        # A cache write must never break a page render.
        pass


def clear_cache(name=None, city=None, district=None):
    key = _place_key(name, city, district)
    with _mem_lock:
        if key:
            _mem_cache.pop(key, None)
        else:
            _mem_cache.clear()
    if key:
        try:
            get_collection("place_image_cache").delete_one({"_id": key})
        except Exception:
            pass


# ------------------------------------------------------------------- public resolve
def resolve_place_images(doc, kind="spot", limit=5, use_cache=True, prefer_record=True):
    """Return the images that may be shown for one listing.

    ``doc`` is a spot / hotel / restaurant / transport document. The result is
    ``{"images": [...], "source": ..., "title": ...}`` where ``source`` is one
    of partner_upload / google_places / wikimedia_commons / placeholder, so the
    UI can label the picture honestly instead of implying it is something it is
    not.
    """
    name = doc.get("name") or doc.get("serviceName") or doc.get("trainName") or ""
    loc = doc.get("location") if isinstance(doc.get("location"), dict) else {}
    city = doc.get("city") or loc.get("city") or ""
    district = doc.get("district") or loc.get("district") or ""
    state = doc.get("state") or loc.get("state") or ""
    if not name and kind == "spot":
        # Spots sometimes only carry a free-text location label.
        name = re.sub(r",.*$", "", (loc.get("name") or "")).strip()

    result = {"images": [], "source": "placeholder", "title": None,
              "name": name, "city": city, "district": district}

    # Tier 1 - the listing owner's own upload. Correct by construction.
    if prefer_record:
        own = [u for u in (doc.get("images") or []) if isinstance(u, str) and u.strip()]
        if own:
            result["images"] = own[:limit]
            result["source"] = "partner_upload"
            return result

    if not name:
        return result

    key = _place_key(name, city, district)
    if use_cache:
        cached = _cache_get(key)
        if cached is not _MISS:
            # A hit that is an empty list is a *negative* cache entry: this
            # place was looked up and genuinely has no verified photo. Honour it
            # so the placeholder renders instantly instead of re-querying.
            result["images"] = cached[:limit]
            if cached:
                result["source"] = "wikimedia_commons"
                result["title"] = (cached[0] or {}).get("title")
            else:
                result["source"] = "placeholder"
            return result

    images = fetch_verified_images(name, city, district, state, limit=limit, kind=kind)
    _cache_put(key, images, name, city, district)
    if images:
        result["images"] = images
        result["source"] = "wikimedia_commons"
        result["title"] = images[0].get("title")
    return result


def attach_to_listing(doc, kind="spot", limit=5, force=False):
    """Re-point a stored listing at verified imagery.

    ``force`` re-queries even when the record already carries images, which is
    how the legacy mismatched landmark photos get repaired.
    """
    resolved = resolve_place_images(doc, kind=kind, limit=limit,
                                    use_cache=not force, prefer_record=not force)
    return resolved["images"], resolved["source"]


def placeholder_for(doc):
    return PLACEHOLDER_URL
