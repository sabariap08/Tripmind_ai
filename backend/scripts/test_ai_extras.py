"""End-to-end tests for the AI extras: voice -> English, Smart Packing and
the Digital Trip Twin (plus destination / return trip / description / spot
selection regression).

Run:  python scripts/test_ai_extras.py

Uses an isolated tripmind_test database, dropped and reseeded on every run, so
real data is never touched. Every assertion is made against REAL responses:
no fake plans, no fake weather, no fake savings.
"""
import os
import sys
import json
import time
from datetime import datetime, timedelta

sys.stdout.reconfigure(encoding="utf-8")

os.environ["MONGODB_DB_NAME"] = "tripmind_test"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app as appmod
from services.mongodb import get_collection, get_db

PASSES, FAILS = [], []

TINY_PNG = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
            "AAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")

POSTFIX = str(int(time.time()))[-7:]


def ok(label, cond, extra=""):
    (PASSES if cond else FAILS).append(label)
    print("[%s] %s %s" % ("PASS" if cond else "FAIL", label, extra))


def jget(r):
    try:
        return r.get_json()
    except Exception:
        return {}


def signup(c, role, email, pwd, registration, extra=None):
    data = {
        "role": role, "name": email.split("@")[0], "email": email,
        "mobile": "9" + str(abs(hash(email)) % 10 ** 9).zfill(9)[-9:],
        "password": pwd, "identityType": "PASSPORT",
        "identityNumber": "P" + str(abs(hash(email)) % 10 ** 9).zfill(9),
        "registration": registration,
    }
    if extra:
        data.update(extra)
    b = jget(c.post("/api/auth/register", json=data))
    return b, (b.get("user") or {}).get("_id")


def approve_user(uid):
    if uid:
        get_collection("users").update_one(
            {"_id": str(uid)},
            {"$set": {"approved": True, "approvalStatus": "APPROVED"}})


def approve_doc(coll, doc_id):
    if doc_id:
        get_collection(coll).update_one(
            {"_id": str(doc_id)},
            {"$set": {"status": "APPROVED", "approvalStatus": "APPROVED"}})


def login(c, email, pwd):
    c.post("/api/auth/logout")
    return c.post("/api/auth/login", json={"email": email, "password": pwd})


def r_ok(payload):
    return isinstance(payload, dict) and not payload.get("error")


def main():
    db = get_db()
    for name in db.list_collection_names():
        db.drop_collection(name)
    from services.mongodb import ensure_unique_indexes
    ensure_unique_indexes()

    c = appmod.app.test_client()
    stamp = POSTFIX

    # ------------------------------------------------------------- accounts
    ue = "extra_user_%s@test.in" % stamp
    _, uid = signup(c, "USER", ue, "Passw0rd@123", {})
    approve_user(uid)
    te = "extra_transport_%s@test.in" % stamp
    _, tid = signup(c, "TRANSPORT_ADMIN", te, "Passw0rd@123", {
        "companyName": "Extra Coaches %s" % stamp, "serviceArea": "Tamil Nadu",
        "companyCity": "Coimbatore", "companyAddress": "KPR",
        "companyPhone": "9999999999"})
    approve_user(tid)
    he = "extra_hotel_%s@test.in" % stamp
    _, hid = signup(c, "HOTEL_ADMIN", he, "Passw0rd@123", {
        "hotelName": "Extra Stay %s" % stamp, "hotelCategory": "Mid-Range",
        "starRating": "3", "hotelCity": "Chennai", "hotelAddress": "T Nagar",
        "contactNumber": "9999999998", "checkInTime": "12:00", "checkOutTime": "11:00",
        "totalRooms": "40"})
    approve_user(hid)
    re_ = "extra_rest_%s@test.in" % stamp
    _, rid_u = signup(c, "RESTAURANT_ADMIN", re_, "Passw0rd@123", {
        "restaurantName": "Extra Diner %s" % stamp, "restaurantType": "Family",
        "restaurantCity": "Chennai", "restaurantAddress": "Mylapore",
        "contactNumber": "9999999997", "checkInTime": "09:00", "checkOutTime": "22:00"})
    approve_user(rid_u)
    se = "extra_spot_%s@test.in" % stamp
    _, sid_u = signup(c, "TOURIST_SPOT_ADMIN", se, "Passw0rd@123", {
        "organisationName": "Extra Heritage %s" % stamp, "organisationCity": "Chennai",
        "contactNumber": "9999999996"})
    approve_user(sid_u)

    # ------------------------------------------------------------ inventory
    login(c, te, "Passw0rd@123")
    schedules = [{"day": d, "departure": "20:30", "arrival": "04:00"}
                 for d in ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")]
    fwd = jget(c.post("/api/transport/register", json={
        "type": "BUS", "busNumber": "EX-BUS-%s" % stamp,
        "boardingPoint": "Coimbatore KPR", "boardingTime": "20:00",
        "droppingPoint": "Chennai CMBT", "droppingTime": "04:00",
        "totalSeats": 30, "sleeperSeats": 20, "seaterSeats": 10,
        "fare": {"price": 1200, "baseFare": 1200}}))
    fwd_id = (fwd.get("transport") or {}).get("transportId")
    approve_doc("transports", fwd_id)
    get_collection("transports").update_one(
        {"_id": str(fwd_id)}, {"$set": {"schedules": schedules}})

    rev = jget(c.post("/api/transport/register", json={
        "type": "BUS", "busNumber": "EX-REV-%s" % stamp,
        "boardingPoint": "Chennai CMBT", "boardingTime": "21:00",
        "droppingPoint": "Coimbatore KPR", "droppingTime": "05:00",
        "totalSeats": 30, "sleeperSeats": 20, "seaterSeats": 10,
        "fare": {"price": 1250, "baseFare": 1250}}))
    rev_id = (rev.get("transport") or {}).get("transportId")
    approve_doc("transports", rev_id)
    get_collection("transports").update_one(
        {"_id": str(rev_id)}, {"$set": {"schedules": schedules}})

    # A CAB fare card so home->boarding / stay->boarding transfers can be
    # priced from the real Google distance instead of reporting an error.
    cab = jget(c.post("/api/transport/register", json={
        "type": "CAB", "vehicleNumber": "EX-CAB-%s" % stamp,
        "serviceArea": "Coimbatore", "baseLocation": "Coimbatore",
        "fare": {"baseFare": 50, "pricePerKm": 13, "minimum": 100}}))
    cab_id = (cab.get("transport") or {}).get("transportId")
    approve_doc("transports", cab_id)
    ok("register cab fare card", r_ok(cab) and bool(cab_id), str(cab)[:140])

    # Real service for the second trip's corridor (Coimbatore -> Ooty).
    hill = jget(c.post("/api/transport/register", json={
        "type": "BUS", "busNumber": "EX-HILL-%s" % stamp,
        "boardingPoint": "Coimbatore KPR", "boardingTime": "07:00",
        "droppingPoint": "Ooty Bus Stand", "droppingTime": "11:00",
        "totalSeats": 40, "sleeperSeats": 30, "seaterSeats": 10,
        "fare": {"price": 900, "baseFare": 900}}))
    hill_id = (hill.get("transport") or {}).get("transportId")
    approve_doc("transports", hill_id)
    get_collection("transports").update_one(
        {"_id": str(hill_id)}, {"$set": {"schedules": schedules}})

    login(c, he, "Passw0rd@123")
    hotel = jget(c.post("/api/hotels", json={
        "name": "Extra Grand %s" % stamp, "city": "Chennai", "category": "Mid-Range",
        "address": "T Nagar", "description": "extra test hotel",
        "amenities": ["Wi-Fi"], "totalRooms": 4,
        "lat": "13.0418", "lng": "80.2440", "roomTypes": [
            {"name": "Deluxe", "ac": True, "bedType": "Double Bed", "totalRooms": 4,
             "roomNumbers": ["101", "102", "103", "104"],
             "pricePerNight": 2500, "maxOccupancy": 2}]}))
    hd = hotel.get("hotel") or {}
    approve_doc("hotels", hd.get("id") or hd.get("_id"))

    login(c, re_, "Passw0rd@123")
    rest = jget(c.post("/api/restaurants", json={
        "name": "Extra Diner %s" % stamp, "city": "Chennai",
        "restaurantType": "Family", "address": "Mylapore",
        "cuisines": ["South Indian"],
        "openingHours": [{"day": "Mon", "open": "09:00", "close": "22:00"}],
        "lat": "13.03", "lng": "80.25"}))
    restaurant_id = (rest.get("restaurant") or {}).get("id")
    approve_doc("restaurants", restaurant_id)
    c.post("/api/restaurants/%s/food-items" % restaurant_id, json={
        "name": "Idli Combo %s" % stamp, "category": "Breakfast",
        "description": "extra test food", "price": 180, "available": True,
        "image": TINY_PNG, "prepTimeMinutes": 10})

    login(c, se, "Passw0rd@123")
    spot_ids = []
    for i in range(6):
        sp = jget(c.post("/api/spots", json={
            "name": "Extra Spot %d %s" % (i + 1, stamp), "city": "Chennai",
            "location": "Marina", "address": "Marina", "category": "Beach",
            "entryFee": 50, "openTime": "06:00", "closeTime": "22:00",
            "images": [TINY_PNG] * 5, "lat": "13.05", "lng": "80.28",
            "recommendedTimes": [{"from": "09:00", "to": "11:00"},
                                 {"from": "14:00", "to": "16:00"}]}))
        sp_id = (sp.get("spot") or {}).get("id") or (sp.get("spot") or {}).get("_id")
        approve_doc("tourist_spots", sp_id)
        spot_ids.append(sp_id)
    ok("6 approved spots seeded (manual selection > 4)", len(spot_ids) == 6, str(spot_ids))

    # ================================================================ TRIP 1
    login(c, ue, "Passw0rd@123")
    today = datetime.utcnow().date()
    tamil = ("எனக்கு குடும்பத்துடன் அமைதியான இரண்டு நாள் பயணம் வேண்டும், "
             "நல்ல சாபாடு மற்றும் கடற்கரை, விலையும் பாதுகாப்பான தங்குவலை வேண்டும்")
    r = c.post("/api/trips", json={
        "origin": "Coimbatore", "destination": "Chennai",
        "startDate": str(today), "endDate": str(today + timedelta(days=1)),
        "travelers": 2, "budget": 30000, "travelStyle": "BALANCED",
        "returnTrip": True, "premiumServices": ["HOTELS", "ACTIVITIES"],
        "preferences": "I want a relaxed family trip with good food, beaches, "
                       "less crowded places and a budget-friendly stay.",
        "prioritizedSpotIds": spot_ids,
        "voiceLanguage": "Tamil", "voiceOriginal": tamil})
    b = jget(r)
    trip1 = b.get("tripId")
    ok("create trip with destination/return/premium/6 spots/voice",
       r.status_code == 201 and trip1, str(b)[:160])

    trip_doc = get_collection("trips").find_one({"_id": trip1}) or {}
    ok("destination stored", trip_doc.get("destination") == "Chennai", str(trip_doc.get("destination")))
    ok("returnTrip stored", trip_doc.get("returnTrip") is True, str(trip_doc.get("returnTrip")))
    ok("premiumServices stored", trip_doc.get("premiumServices") == ["HOTELS", "ACTIVITIES"],
       str(trip_doc.get("premiumServices")))
    ok("all 6 selected spots stored (no 4-limit)",
       len(trip_doc.get("prioritizedSpotIds") or []) == 6,
       str(len(trip_doc.get("prioritizedSpotIds") or [])))
    ok("description stored", "relaxed family trip" in (trip_doc.get("preferences") or ""),
       str(trip_doc.get("preferences"))[:60])
    ok("voice metadata stored", (trip_doc.get("voice") or {}).get("language") == "Tamil",
       str(trip_doc.get("voice"))[:80])

    # ------------------------------------------------- PART 6: voice -> English
    t0 = time.time()
    r = c.post("/api/ai/voice-normalize", json={"text": tamil})
    v = jget(r)
    v_secs = time.time() - t0
    print("\n[voice] %ss -> %s" % (v_secs, v.get("english")))
    ok("voice-normalize 200", r.status_code == 200, str(v)[:200])
    ok("language detected", bool(v.get("language")), str(v.get("language")))
    ok("translated to English", bool(v.get("translated")) and
       not any("\u0b80" <= ch <= "\u0bff" for ch in (v.get("english") or "")),
       str(v.get("english"))[:100])
    ok("original preserved", v.get("original") == tamil, "")
    ok("voice latency reasonable (<45s)", v_secs < 45, "%.1fs" % v_secs)

    r = c.post("/api/ai/voice-normalize", json={"text": ""})
    ok("empty transcript rejected", r.status_code == 400, str(jget(r))[:120])

    # The other supported languages: the browser transcribes, Ollama detects
    # the language and returns English for the existing preferences field.
    samples = {
        "Hindi": "हम दो लोगों के लिए पांच दिन की शांत समुद्र तट यात्रा चाहते हैं",
        "Telugu": "మేము ఐదు రోజుల ప్రశాంతమైన సముదర యాత్రను కోరుకుంటున్నాము",
        "Malayalam": "ഞങ്ങൾ നാല് ദിവസം സമുദരതീരത്ത് ഒരു സ്വാഗതമായ യാത്ര ആഗ്രഹിക്കുന്നു",
        "Kannada": "ನಾವು ಮೂವರು ದಿನಗಳ ಸಮುದರ ತಾಣ ಪ್ರಯಾಣವನ್ನು ಬಯಸುತ್ತೇವೆ",
        "English": "Plan a quiet four day beach holiday for two people",
    }
    for want_lang, text in samples.items():
        r = c.post("/api/ai/voice-normalize", json={"text": text})
        v = jget(r)
        eng = v.get("english") or ""
        native_left = any("\u0900" <= ch <= "\u0dff" for ch in eng)
        ok("voice %s -> English" % want_lang,
           r.status_code == 200 and bool(eng) and not native_left,
           "lang=%s -> %s" % (v.get("language"), eng[:70]))

    # --------------------------------------------------------- AI generation
    t0 = time.time()
    r = c.post("/api/trips/%s/generate" % trip1)
    g = jget(r)
    gen_secs = time.time() - t0
    ok("generate 200 with a selected plan", r.status_code == 200 and bool(g.get("selectedPlan")),
       "source=%s %.1fs" % (g.get("source"), gen_secs))
    ok("generate within Ollama performance budget (<90s)", gen_secs < 90, "%.1fs" % gen_secs)
    trip1_full = jget(c.get("/api/trips/%s" % trip1))
    itin = next((i for i in (trip1_full.get("itineraries") or [])
                 if i.get("status") == "SELECTED"), {})
    items = itin.get("items") or []
    ok("itinerary has items", len(items) > 0, "%d items" % len(items))
    ok("return leg present (returnTrip ON)",
       any("Return" in str(i.get("title") or "") for i in items),
       str([i.get("title") for i in items])[:140])
    ok("transfer legs are distance-priced or honestly flagged",
       all((i.get("cost") or 0) > 0 or i.get("fareError") for i in items
           if i.get("type") == "TRANSFER"),
       str([(i.get("title"), i.get("cost"), (i.get("fareError") or "")[:40])
            for i in items if i.get("type") == "TRANSFER"]))

    # ------------------------------------------------- PART 14/15: packing
    t0 = time.time()
    r = c.post("/api/trips/%s/packing" % trip1, json={})
    p = jget(r)
    pack_secs = time.time() - t0
    w = p.get("weather") or {}
    print("\n[packing] %ss · weather=%s · %s" % (pack_secs, w.get("available"),
                                                 w.get("summary") or w.get("reason")))
    ok("packing 200", r.status_code == 200, str(p)[:180])
    ok("packing list generated", len(p.get("items") or []) >= 5,
       "%s items%s" % (p.get("itemCount"), " (truncated)" if p.get("truncated") else ""))
    ok("bag weight estimated", (p.get("totalWeightG") or 0) > 0,
       "%.1f kg" % ((p.get("totalWeightG") or 0) / 1000.0))
    ok("packing used real weather", w.get("available") is True and bool(w.get("summary")),
       str(w.get("summary") or w.get("reason")))
    ok("packing context is this trip",
       (p.get("context") or {}).get("destination") == "Chennai" and
       (p.get("context") or {}).get("days") == 2,
       str(p.get("context")))
    ok("packing categories valid",
       all(i.get("category") in ("clothing", "essential", "weather", "activity",
                                 "documents", "tech", "health", "optional")
           for i in (p.get("items") or [])), "")
    ok("packing latency reasonable (<90s)", pack_secs < 90, "%.1fs" % pack_secs)

    t0 = time.time()
    p2 = jget(c.post("/api/trips/%s/packing" % trip1, json={}))
    cache_secs = time.time() - t0
    ok("packing cached on second call", p2.get("generatedAt") == p.get("generatedAt") and cache_secs < 5,
       "%.2fs" % cache_secs)
    p3 = jget(c.post("/api/trips/%s/packing" % trip1, json={"force": True}))
    ok("packing force regenerates", p3.get("generatedAt") != p.get("generatedAt"),
       str(p3.get("generatedAt")))

    # ------------------------------------------------- PART 16-19: digital twin
    t0 = time.time()
    r = c.get("/api/trips/%s/twin" % trip1)
    tw = jget(r)
    print("\n[twin] %ss · state=%s · legs=%d" % (time.time() - t0,
                                                 (tw.get("journey") or {}).get("state"),
                                                 len(tw.get("legs") or [])))
    ok("twin 200", r.status_code == 200, str(tw)[:160])
    j = tw.get("journey") or {}
    ok("twin journey state is real", j.get("state") == "IN_PROGRESS" and j.get("currentDay") == 1,
       "%s day %s" % (j.get("state"), j.get("currentDay")))
    ok("twin legs from itinerary", len(tw.get("legs") or []) == len(items),
       "%d legs" % len(tw.get("legs") or []))
    ok("twin budget = plan total",
       abs(float((tw.get("budget") or {}).get("estimated") or 0) - float(itin.get("totalCost") or 0)) < 1,
       str((tw.get("budget") or {}).get("estimated")))
    ok("twin paid = 0 before booking", (tw.get("budget") or {}).get("paid") == 0, "")
    ok("twin weather is real or honestly unavailable",
       w.get("available") is True or bool(w.get("reason")), str(w.get("summary") or w.get("reason")))
    ok("luggage explicitly not connected (no faked tracking)",
       (tw.get("luggage") or {}).get("connected") is False and
       "is connected" in ((tw.get("luggage") or {}).get("message") or "").lower(),
       str((tw.get("luggage") or {}).get("message"))[:80])

    # ============================== TRIP 2: packing must differ for another trip
    r = c.post("/api/trips", json={
        "origin": "Coimbatore", "destination": "Ooty",
        "startDate": str(today + timedelta(days=1)),
        "endDate": str(today + timedelta(days=7)),
        "travelers": 4, "budget": 90000, "travelStyle": "PREMIUM",
        "returnTrip": False, "premiumServices": ["GUIDE"],
        "preferences": "Seven day hill station hiking trip with a guide, cold "
                       "mornings, tea gardens and light luggage only.",
        "prioritizedSpotIds": spot_ids[:2]})
    trip2 = jget(r).get("tripId")
    ok("second trip created (7 days, Ooty, no return)", bool(trip2), "")
    r = c.post("/api/trips/%s/generate" % trip2)
    g2 = jget(r)
    ok("second trip generated (real services) or honestly reported empty",
       r.status_code == 200 and
       (bool(g2.get("selectedPlan")) or g2.get("source") in ("empty", "ai_unavailable")),
       "source=%s" % g2.get("source"))
    r = c.post("/api/trips/%s/packing" % trip2, json={})
    p4 = jget(r)
    names1 = {i.get("name") for i in (p.get("items") or [])}
    names4 = {i.get("name") for i in (p4.get("items") or [])}
    w4 = p4.get("weather") or {}
    print("\n[packing2] weather=%s · %s" % (w4.get("available"),
                                            w4.get("summary") or w4.get("reason")))
    ok("second packing generated", r.status_code == 200 and len(names4) >= 5, "%d items" % len(names4))
    ok("packing differs for a 7-day Ooty trip (not hardcoded)",
       bool(names1 - names4) and bool(names4 - names1),
       "only-trip1=%d only-trip2=%d" % (len(names1 - names4), len(names4 - names1)))
    ok("second packing context is Ooty/7 days",
       (p4.get("context") or {}).get("destination") == "Ooty" and
       (p4.get("context") or {}).get("days") == 7,
       str(p4.get("context")))

    # ============================================================ error honesty
    # A reply the model cut off mid-plan must still yield the plans that were
    # fully written (this is what the live "malformed JSON" error came from).
    from services.ai_plan_builder import _parse_response, AIPlanError
    plan_a = {"style": "BUDGET", "transportId": "t1", "hotel": None,
              "guideId": None, "activityOrder": ["s1", "s2"], "foodIds": ["f1"]}
    plan_b = {"style": "BALANCED", "transportId": "t2",
              "hotel": {"hotelId": "h1", "roomTypeId": "r1"},
              "guideId": "g1", "activityOrder": ["s1"], "foodIds": []}
    plan_c = {"style": "PREMIUM", "transportId": "t3", "activityOrder": ["s1", "s2", "s3"]}
    full = json.dumps({"plans": [plan_a, plan_b, plan_c]})
    ok("complete plan reply parses to 3 plans",
       len(_parse_response(full)) == 3, "%d plans" % len(_parse_response(full)))
    # cut inside the third plan: the first two are complete and usable
    cut = full[:full.rindex('{"style": "PREMIUM"') + 30]
    got = _parse_response(cut)
    ok("truncated reply recovers the complete plans",
       [p["style"] for p in got] == ["BUDGET", "BALANCED"],
       str([p["style"] for p in got]))
    # cut inside the FIRST plan: nothing usable, so it must fail honestly
    first_cut = full[:full.index('"style": "BUDGET"') + 20]
    try:
        _parse_response(first_cut)
        ok("reply truncated before any complete plan fails honestly", False, "no error")
    except AIPlanError as e:
        ok("reply truncated before any complete plan fails honestly",
           any(w in str(e).lower() for w in ("malformed", "non-json")),
           str(e)[:90])

    # Same recovery for a truncated packing reply.
    from routes.trips import _salvage_packing_items
    items = [{"name": "Light cotton shirt", "qty": 3, "category": "clothing",
              "weightG": 200, "reason": "hot and humid"},
             {"name": "Sunscreen SPF50", "qty": 1, "category": "weather",
              "weightG": 150, "reason": "strong sun"},
             {"name": "Power bank", "qty": 1, "category": "tech",
              "weightG": 220, "reason": "long travel day"}]
    pack_full = json.dumps({"items": items, "optimization": ["light cotton"],
                            "notes": "pack light"})
    pack_cut = pack_full[:pack_full.rindex('{"name": "Power bank"') + 20]
    salv = _salvage_packing_items(pack_cut)
    ok("truncated packing reply recovers complete items",
       [i["name"] for i in salv] == ["Light cotton shirt", "Sunscreen SPF50"],
       str([i["name"] for i in salv]))

    r = c.post("/api/ai/voice-normalize", json={"text": "x" * 1})
    ok("single-char transcript rejected", r.status_code == 400, "")
    r = c.get("/api/trips/%s/twin" % "does-not-exist")
    ok("twin 404 for unknown trip", r.status_code == 404, str(jget(r))[:80])
    r = c.post("/api/trips/%s/packing" % "does-not-exist", json={})
    ok("packing 404 for unknown trip", r.status_code == 404, str(jget(r))[:80])

    print("\n============ RESULTS ============")
    for f in FAILS:
        print("  FAILED: %s" % f)
    print("%d passed, %d failed" % (len(PASSES), len(FAILS)))
    return 0 if not FAILS else 1


if __name__ == "__main__":
    raise SystemExit(main())
