"""End-to-end tests against a dedicated tripmind_test DB.

Run:  python scripts/e2e_test.py
Uses the Flask test client. All flows touch a fresh, isolated database so
real data is never modified. Covers:
  - registered-service booking only (no mock/fallback inventory)
  - standalone + AI-trip booking, duplicate prevention, wallet payment
  - admin propagation to transport/hotel/restaurant providers
  - one PDF + one QR per trip, verification
  - Simulate Delay propagation + Replan
  - AI assistant proposal + confirmed action execution (change transport, pay trip)
"""
import os, sys, json, time

sys.stdout.reconfigure(encoding="utf-8")

os.environ["MONGODB_DB_NAME"] = "tripmind_test"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app as appmod
from services.mongodb import get_collection, get_db

PASSES, FAILS = [], []


def ok(label, cond, extra=""):
    tag = "PASS" if cond else "FAIL"
    (PASSES if cond else FAILS).append("%s %s %s" % (tag, label, extra))
    print("[%s] %s %s" % (tag, label, extra))


def jget(r):
    try:
        return r.get_json()
    except Exception:
        return {}

POSTFIX = str(int(time.time()))[-7:]

# 1x1 transparent PNG (data URI) satisfies product/spot image requirements.
TINY_PNG = ("data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
            "AAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


def signup(c, role, email, pwd, registration, extra=None):
    data = {
        "role": role, "name": email.split("@")[0], "email": email,
        "mobile": "9" + str(abs(hash(email)) % 10 ** 9).zfill(9)[-9:],
        "password": pwd,
        "identityType": "PASSPORT",
        "identityNumber": "P" + str(abs(hash(email)) % 10 ** 9).zfill(9),
        "registration": registration,
    }
    if extra:
        data.update(extra)
    r = c.post("/api/auth/register", json=data)
    b = jget(r)
    return b, (b.get("user") or {}).get("_id")


def approve_user(user_id):
    if not user_id:
        return
    get_collection("users").update_one(
        {"_id": str(user_id)},
        {"$set": {"approved": True, "approvalStatus": "APPROVED"}})


def login(c, email, pwd):
    c.post("/api/auth/logout")
    r = c.post("/api/auth/login", json={"email": email, "password": pwd})
    return r


def uid_from(c):
    me = jget(c.get("/api/auth/me"))
    return (me.get("user") or {}).get("id")


def main():
    db = get_db()
    for name in db.list_collection_names():
        db.drop_collection(name)
    from services.mongodb import ensure_unique_indexes
    ensure_unique_indexes()

    c = appmod.app.test_client()

    # ---------------------------------------------------------------- users
    ue = "e2e_user_%s@test.in" % POSTFIX
    _, _uid = signup(c, "USER", ue, "Passw0rd@123", {})
    ok("user registration", _uid is not None, "")

    te = "e2e_transport_%s@test.in" % POSTFIX
    _, tid = signup(c, "TRANSPORT_ADMIN", te, "Passw0rd@123", {
        "companyName": "E2E Coaches %s" % POSTFIX, "serviceArea": "Tamil Nadu",
        "companyCity": "Coimbatore", "companyAddress": "KPR", "companyPhone": "9999999999"})
    approve_user(tid)

    he = "e2e_hotel_%s@test.in" % POSTFIX
    _, hid = signup(c, "HOTEL_ADMIN", he, "Passw0rd@123", {
        "hotelName": "E2E Stay %s" % POSTFIX, "hotelCategory": "Mid-Range",
        "starRating": "3", "hotelCity": "Chennai", "hotelAddress": "T Nagar",
        "contactNumber": "9999999998", "checkInTime": "12:00", "checkOutTime": "11:00",
        "totalRooms": "40"})
    approve_user(hid)

    re_ = "e2e_rest_%s@test.in" % POSTFIX
    _, rid_u = signup(c, "RESTAURANT_ADMIN", re_, "Passw0rd@123", {
        "restaurantName": "E2E Diner %s" % POSTFIX, "restaurantType": "Family",
        "restaurantCity": "Chennai", "restaurantAddress": "Mylapore",
        "contactNumber": "9999999997", "checkInTime": "09:00", "checkOutTime": "22:00"})
    approve_user(rid_u)

    se = "e2e_spot_%s@test.in" % POSTFIX
    _, sid = signup(c, "TOURIST_SPOT_ADMIN", se, "Passw0rd@123", {
        "organisationName": "E2E Heritage %s" % POSTFIX, "organisationCity": "Chennai",
        "contactNumber": "9999999996"})
    approve_user(sid)

    ge = "e2e_guide_%s@test.in" % POSTFIX
    _, gid = signup(c, "GUIDE", ge, "Passw0rd@123", {
        "guideCity": "Chennai", "languages": "English, Tamil", "specialties": "Heritage",
        "yearsExperience": "5", "pricePerHour": "700", "pricePerDay": "4000"})
    approve_user(gid)

    # ------------------------------------------------------- fixtures (catalogues)
    def approve_doc(coll, doc_id):
        get_collection(coll).update_one(
            {"_id": str(doc_id)},
            {"$set": {"status": "APPROVED", "approvalStatus": "APPROVED"}})

    # Transport admin registers a bus KPR -> Chennai (CMBT)
    r = login(c, te, "Passw0rd@123")
    ok("transport login approved", r.status_code == 200, str(jget(r)))
    r = c.post("/api/transport/register", json={
        "type": "BUS", "busNumber": "E2E-BUS-%s" % POSTFIX,
        "boardingPoint": "Coimbatore KPR", "boardingTime": "20:00",
        "droppingPoint": "Chennai CMBT", "droppingTime": "04:00",
        "totalSeats": 30, "sleeperSeats": 20, "seaterSeats": 10})
    bus = jget(r)
    ok("register bus", r.status_code == 201, str(bus))
    transport_id = (bus.get("transport") or {}).get("transportId")
    approve_doc("transports", transport_id)

    # Hotel admin registers a hotel in Chennai with rooms
    login(c, he, "Passw0rd@123")
    r = c.post("/api/hotels", json={
        "name": "E2E Grand %s" % POSTFIX, "city": "Chennai", "category": "Mid-Range",
        "address": "T Nagar", "description": "E2E test hotel",
        "amenities": ["Wi-Fi"], "roomTypes": [
            {"name": "Deluxe", "ac": True, "bedType": "Double Bed", "totalRooms": 4,
             "roomNumbers": ["101", "102", "103", "104"],
             "pricePerNight": 2500, "maxOccupancy": 2}]})
    hotel = jget(r)
    ok("register hotel", r.status_code == 201, str(hotel))
    hd = hotel.get("hotel") or {}
    hotel_id = hd.get("id") or hd.get("_id")
    room_type_id = ((hd.get("roomTypes") or [{}])[0]).get("id")
    approve_doc("hotels", hotel_id)

    # Restaurant admin adds a restaurant + food items
    login(c, re_, "Passw0rd@123")
    r = c.post("/api/restaurants", json={
        "name": "E2E Diner %s" % POSTFIX, "city": "Chennai",
        "restaurantType": "Family", "address": "Mylapore", "cuisines": ["South Indian"],
        "openingHours": [{"day": "Mon", "open": "09:00", "close": "22:00"}],
        "lat": "13.03", "lng": "80.25"})
    rest = jget(r)
    ok("register restaurant", r.status_code == 201, str(rest))
    restaurant_id = (rest.get("restaurant") or {}).get("id")
    approve_doc("restaurants", restaurant_id)
    r = c.post("/api/restaurants/%s/food-items" % restaurant_id, json={
        "name": "Idli Combo %s" % POSTFIX, "category": "Breakfast",
        "description": "E2E food", "price": 180, "available": True,
        "image": TINY_PNG, "prepTimeMinutes": 10})
    food = jget(r)
    ok("add food item", r.status_code in (200, 201), str(food)[:160])

    # Tourist spot admin adds a spot in Chennai + a tour
    login(c, se, "Passw0rd@123")
    r = c.post("/api/spots", json={
        "name": "Marina E2E %s" % POSTFIX, "city": "Chennai", "location": "Marina Beach",
        "address": "Marina", "category": "Beach", "entryFee": 50, "openTime": "06:00",
        "closeTime": "22:00", "images": [TINY_PNG] * 5, "lat": "13.05", "lng": "80.28"})
    spot = jget(r)
    ok("register spot", r.status_code == 201, str(spot)[:180])
    spot_id = (spot.get("spot") or {}).get("id") or (spot.get("spot") or {}).get("_id")
    approve_doc("tourist_spots", spot_id)
    r = c.post("/api/tours", json={
        "name": "E2E Heritage Walk %s" % POSTFIX, "city": "Chennai",
        "spotId": spot_id,
        "description": "Walk tour", "duration": 3, "cost": 899, "maxParticipants": 20,
        "availableTimes": ["09:00"], "includedServices": ["Guide", "Entry"]})
    tour = jget(r)
    ok("register tour", r.status_code == 201, str(tour)[:180])
    tour_id = (tour.get("tour") or {}).get("_id") or (tour.get("tour") or {}).get("id")
    approve_doc("tours", tour_id)

    login(c, te, "Passw0rd@123")
    get_collection("transports").update_one(
        {"_id": str(transport_id)},
        {"$set": {"status": "APPROVED", "approvalStatus": "APPROVED",
                  "schedules": [{"day": "Mon", "departure": "20:30", "arrival": "04:00"},
                                {"day": "Tue", "departure": "20:30", "arrival": "04:00"},
                                {"day": "Wed", "departure": "20:30", "arrival": "04:00"},
                                {"day": "Thu", "departure": "20:30", "arrival": "04:00"},
                                {"day": "Fri", "departure": "20:30", "arrival": "04:00"},
                                {"day": "Sat", "departure": "20:30", "arrival": "04:00"},
                                {"day": "Sun", "departure": "20:30", "arrival": "04:00"}]}})

    # Guide sets pricing + availability on the approved spot location
    login(c, ge, "Passw0rd@123")
    c.post("/api/guide/pricing", json={"pricePerHour": 700, "pricePerDay": 4000})
    c.post("/api/guide/availability", json={
        "date": "2026-10-05", "from": "09:00", "to": "17:00", "locations": ["Marina E2E %s" % POSTFIX]})
    get_collection("guide_availability").update_many(
        {"guideId": gid}, {"$set": {"status": "APPROVED"}})

    # --------------------------------------------------- no-fake-inventory guarantee
    login(c, ue, "Passw0rd@123")
    uid = uid_from(c)
    r = c.post("/api/trips", json={
        "origin": "Dreamville", "destination": "Nowhereland", "startDate": "2026-10-10",
        "endDate": "2026-10-11", "budget": 20000, "travelers": 2,
        "travelStyle": "BALANCED", "transportType": "BUS"})
    b = jget(r)
    empty_trip = b.get("tripId") or b.get("trip", {}).get("_id")
    ok("create trip (no data corridor)", r.status_code == 201, str(b))
    r = c.post("/api/trips/%s/generate" % empty_trip)
    b = jget(r)
    ok("generate returns empty (no fake services)",
       b.get("source") == "empty" and not b.get("selectedPlan"), str(b)[:200])

    # --------------------------------------------------- standalone transport duplicate
    r = c.post("/api/bookings", json={
        "type": "TRANSPORT", "transportId": transport_id, "qty": 2,
        "seatType": "SLEEPER", "date": "2026-10-05"})
    b = jget(r)
    ok("standalone transport booking", r.status_code == 201, str(b))
    st_book = b.get("booking") or {}
    r = c.post("/api/bookings", json={
        "type": "TRANSPORT", "transportId": transport_id, "qty": 1,
        "seatType": "SLEEPER", "date": "2026-10-05"})
    ok("duplicate booking rejected", r.status_code == 400, str(jget(r))[:160])
    ok("standalone booking starts PENDING",
       st_book.get("paymentStatus") == "PENDING", str(st_book.get("paymentStatus")))

    # --------------------------------------------------- payment (standalone + trip)
    c.post("/api/wallet/deposit", json={"amount": 5000})
    r = c.post("/api/bookings/%s/pay" % st_book.get("_id"))
    ok("pay standalone booking", r.status_code == 200, str(jget(r))[:120])
    b = jget(c.get("/api/bookings"))
    st_paid = next((x for x in (b.get("bookings") or []) if x.get("_id") == st_book.get("_id")), {})
    ok("standalone booking COMPLETED after pay",
       st_paid.get("paymentStatus") == "COMPLETED", str(st_paid.get("paymentStatus")))

    # --------------------------------------------------- AI trip: generate, book, pay
    r = c.post("/api/trips", json={
        "origin": "Coimbatore", "destination": "Chennai", "startDate": "2026-10-05",
        "endDate": "2026-10-07", "budget": 40000, "travelers": 2,
        "travelStyle": "BALANCED", "transportType": "BUS"})
    b = jget(r)
    trip_id = b.get("tripId")
    ok("create AI trip", r.status_code == 201, str(b))
    r = c.post("/api/trips/%s/generate" % trip_id)
    b = jget(r)
    ok("generate AI plans (db-backed)", b.get("source") in ("db", "db_all", "empty"), str(jget(r))[:200])
    r = c.post("/api/trips/%s/book" % trip_id)
    b = jget(r)
    ok("book AI trip", r.status_code == 200, str(b)[:300])
    trip_doc = get_collection("trips").find_one({"_id": trip_id})
    tb = [x for x in (trip_doc or {}).get("bookings", []) if x.get("status") != "CANCELLED"]
    types = sorted({x.get("type") for x in tb})
    ok("trip booked services present", len(tb) >= 1, "types=%s count=%d" % (types, len(tb)))
    ok("trip bookings start PENDING", all(x.get("paymentStatus") == "PENDING" for x in tb), str(types))

    # nothing paid yet -> trip payment stays PENDING
    r = c.post("/api/trips/%s/pay" % trip_id)
    b = jget(r)
    ok("trip pay completes", r.status_code == 200 and b.get("paymentStatus") == "COMPLETED", str(b)[:200])
    trip_doc = get_collection("trips").find_one({"_id": trip_id})
    ok("trip COMPLETED + bookings COMPLETED",
       trip_doc.get("paymentStatus") == "COMPLETED" and
       all(x.get("paymentStatus") == "COMPLETED" for x in trip_doc.get("bookings", []) if x.get("status") != "CANCELLED"))

    # --------------------------------------------------- one PDF + one QR per trip
    r = c.get("/api/trips/%s/token" % trip_id)
    tok = jget(r)
    ok("trip token issued", r.status_code == 200 and tok.get("token"), str(tok)[:120])
    token = tok.get("token")
    r = c.get("/api/trips/%s/ticket" % trip_id)
    ok("trip PDF generated", r.status_code == 200 and r.content_type.startswith("application/pdf"),
       "%s bytes" % len(r.data))
    r = c.get("/api/tickets/verify/%s?type=trip" % token)
    v = jget(r)
    ok("trip QR verifies", r.status_code == 200 and (v.get("trip") or v.get("status")), str(v)[:200])

    # --------------------------------------------------- admin propagation
    # Transport owner sees reservations
    login(c, te, "Passw0rd@123")
    rows = jget(c.get("/api/provider/bookings?type=TRANSPORT")).get("bookings") or []
    ok("transport admin sees seats booked", any(x.get("transportId") == transport_id for x in rows),
       "rows=%d" % len(rows))
    rows = jget(c.get("/api/provider/bookings?type=HOTEL")).get("bookings") or []
    ok("restaurant/hotel gate on transport role (empty)", not rows)
    # Hotel owner sees hotel bookings
    login(c, he, "Passw0rd@123")
    rows = jget(c.get("/api/provider/bookings?type=HOTEL")).get("bookings") or []
    ok("hotel admin sees stays", any(x.get("hotelId") == hotel_id for x in rows), "rows=%d" % len(rows))
    # Restaurant owner sees food orders
    login(c, re_, "Passw0rd@123")
    rows = jget(c.get("/api/provider/bookings?type=RESTAURANT")).get("bookings") or []
    ok("restaurant admin sees orders", any(x.get("restaurantId") == restaurant_id for x in rows),
       "rows=%d" % len(rows))

    # --------------------------------------------------- Simulate Delay + Replan
    login(c, ue, "Passw0rd@123")
    r = c.post("/api/trips/%s/simulate-delay" % trip_id, json={"delayMinutes": 120})
    ok("simulate delay", r.status_code == 200, str(jget(r))[:160])
    trip_doc = get_collection("trips").find_one({"_id": trip_id})
    ok("trip.delay ACTIVE recorded",
       trip_doc.get("delay", {}).get("status") == "ACTIVE", str(trip_doc.get("delay")))
    r = c.post("/api/trips/%s/replan" % trip_id)
    b = jget(r)
    ok("replan resolves delay", r.status_code == 200 and (b.get("revisedPlan") or b.get("plan")), str(b)[:220])
    trip_doc = get_collection("trips").find_one({"_id": trip_id})
    ok("delay now RESOLVED", trip_doc.get("delay", {}).get("status") == "RESOLVED",
       str(trip_doc.get("delay", {}).get("status")))

    # --------------------------------------------------- AI assistant
    r = c.post("/api/assistant/chat", json={
        "message": "I want to pay for my trip", "tripId": trip_id})
    b = jget(r)
    ok("assistant proposes pay action", b.get("action", {}).get("type") == "pay_trip", str(b)[:240])
    r = c.post("/api/assistant/action", json={
        "type": "pay_trip", "params": {"trip_id": trip_id}})
    b = jget(r)
    ok("assistant pay executes", r.status_code == 200, str(b)[:200])

    r = c.post("/api/assistant/chat", json={"message": "I want to switch my transport"})
    b = jget(r)
    ok("assistant proposes change_transport", b.get("action", {}).get("type") == "change_transport", str(b)[:240])
    act = b.get("action") or {}
    r = c.post("/api/assistant/action", json={"type": "change_transport",
                                              "params": act.get("params")})
    b = jget(r)
    ok("assistant switch transport executes", r.status_code == 200, str(b)[:220])
    trip_doc = get_collection("trips").find_one({"_id": trip_id})
    switched = [x for x in trip_doc.get("bookings", [])
                if x.get("switchedFrom") or x.get("switchedTo")]
    ok("switch recorded on trip", len(switched) >= 1, "switched=%d" % len(switched))

    # --------------------------------------------------- profile update (PATCH /api/users/me)
    r = c.patch("/api/users/me", json={"name": "E2E Renamed",
                                       "preferences": {"dietary": "vegetarian", "travelStyle": "BUDGET"}})
    ok("profile update", r.status_code == 200, str(jget(r)))
    me = jget(c.get("/api/auth/me")).get("user") or {}
    ok("profile persisted", me.get("name") == "E2E Renamed",
       "name=%s prefs=%s" % (me.get("name"), me.get("preferences")))

    # --------------------------------------------------- reviews routes merged under /api/trips
    r = c.get("/api/trips/%s/reviews" % trip_id)
    ok("trip reviews list", r.status_code == 200, str(jget(r))[:120])
    r = c.post("/api/trips/%s/review" % trip_id, json={"rating": 5, "comment": "Great"})
    ok("trip review submitted", r.status_code in (200, 201), str(jget(r))[:120])

    # --------------------------------------------------- mindmap flow merged under /api/mindmap
    r = c.get("/api/mindmap/flow?from=Coimbatore&to=Chennai")
    ok("mindmap journey flow", r.status_code == 200 and (jget(r).get("stages") is not None), str(jget(r))[:160])

    print("\n================ E2E RESULTS ================")
    print("PASS: %d   FAIL: %d" % (len(PASSES), len(FAILS)))
    for f in FAILS:
        print(f)
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()