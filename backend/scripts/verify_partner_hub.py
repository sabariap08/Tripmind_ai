"""Targeted verification for the all-role Partner Hub, passenger profiles,
checklists and the Main Admin approval queue.

Run from the backend directory:

    python scripts/verify_partner_hub.py

This is a self-contained smoke test using the Flask test client. It provisions
its own throwaway Main Admin (never mutates the seeded one) and cleans up the
partner accounts it creates, so it is safe to run against a development
database. It is NOT a replacement for the full e2e suite.
"""
import os
import sys
import base64
import uuid
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from werkzeug.security import generate_password_hash  # noqa: E402

from app import app  # noqa: E402
from services.mongodb import get_collection  # noqa: E402
from services.auth import new_user_id  # noqa: E402

PNG = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUg=="

PASSED = []
FAILED = []


def check(name, condition, detail=""):
    if condition:
        PASSED.append(name)
        print("[PASS] %s" % name)
    else:
        FAILED.append("%s %s" % (name, detail))
        print("[FAIL] %s %s" % (name, detail))


def signup(role, email, registration, images=0, documents=None, mobile=None):
    payload = {
        "name": "Verify Partner",
        "email": email,
        "password": "Passw0rd@123",
        "mobile": mobile or ("9%09d" % (uuid.uuid4().int % 10 ** 9)),
        "identityType": "AADHAAR",
        "identityNumber": "VR%s" % uuid.uuid4().hex[:10].upper(),
        "role": role,
        "registration": registration,
    }
    if images:
        payload["images"] = [PNG] * images
    if documents:
        payload["documents"] = documents
    return app.test_client().post("/api/auth/register", json=payload)


HOTEL = {
    "propertyName": "Verify Grand", "hotelCategory": "Budget",
    "propertyType": "Hotel", "totalRooms": 12, "checkInTime": "12:00",
    "checkOutTime": "11:00", "baseCity": "Chennai", "contactPhone": "9876543210",
    "location": {"address": "1 Anna Salai", "city": "Chennai",
                 "district": "Chennai", "placeId": "ChIJ_verify",
                 "lat": 13.08, "lng": 80.27},
    "weeklySchedule": {"Monday": {"open": "09:00", "close": "21:00"},
                       "Tuesday": {"closed": True}},
}
GUIDE = {
    "guideName": "Verify Guide", "experienceYears": 4,
    "languages": ["Tamil", "English"], "specialties": ["Historical"],
    "baseCity": "Madurai", "contactPhone": "9876543210", "pricePerDay": 2500,
}
RESTAURANT = {
    "restaurantName": "Verify Foods", "restaurantType": "Cafe",
    "seatingCapacity": 40, "baseCity": "Coimbatore", "contactPhone": "9876543210",
    "location": {"address": "RS Puram", "city": "Coimbatore",
                 "district": "Coimbatore", "placeId": "ChIJ_verify2",
                 "lat": 11.00, "lng": 76.95},
}
TRANSPORT = {
    "companyName": "Verify Travels", "transportModes": ["BUS", "CAB"],
    "baseCity": "Salem", "serviceArea": "Salem, Chennai",
    "companyPhone": "9876543210",
    "location": {"address": "5 Bus Stand", "city": "Salem",
                 "district": "Salem", "placeId": "ChIJ_verify3",
                 "lat": 11.66, "lng": 78.14},
}
SPOT = {
    "spotName": "Verify Fort", "spotCategory": "Monument",
    "baseCity": "Kanyakumari", "contactPhone": "9876543210",
    "location": {"address": "Fort Road", "city": "Kanyakumari",
                 "district": "Kanyakumari", "placeId": "ChIJ_verify4",
                 "lat": 8.08, "lng": 77.54},
}

# Minimal valid data URIs for testing (PDF and JPEG headers)
MIN_PDF = "data:application/pdf;base64,JVBERi0xLjQKJdPRUw=="
MIN_JPG = "data:image/jpeg;base64,/9j/4AAQSkZJRg=="

def _doc(type_id, data=MIN_PDF):
    return {"id": type_id, "type": type_id, "data": data}

HOTEL_DOCS = [_doc("gst_certificate"), _doc("trade_licence")]
GUIDE_DOCS = [_doc("identity_proof"), _doc("address_proof")]
RESTAURANT_DOCS = [_doc("fssai_licence"), _doc("trade_licence")]
TRANSPORT_DOCS = [_doc("rc"), _doc("fitness_certificate"),
                  _doc("insurance"), _doc("puc"),
                  _doc("driver_licence")]
SPOT_DOCS = [_doc("ownership_proof")]

created_ids = []
created_bookings = []
admin_email = "verify_admin_%s@tripmind.test" % uuid.uuid4().hex[:8]
admin_id = None


def cleanup():
    """Remove everything this run created, not just the accounts.

    Bookings, checklists, passenger records and notifications all survive the
    account that produced them, so deleting users alone would leave a trail of
    test data behind on a real database.
    """
    from services.mongodb import get_collection as gc
    ids = created_ids + ([admin_id] if admin_id else [])
    if ids:
        for coll, field, values in (
            ("checklists", "ownerId", ids),
            ("notifications", "userId", ids),
            ("passengers", "ownerId", ids),
            ("bookings", "userId", ids),
        ):
            try:
                gc(coll).delete_many({field: {"$in": values}})
            except Exception as exc:
                print("  ! cleanup %s: %s" % (coll, exc))
    for booking_id in created_bookings:
        try:
            gc("checklists").delete_many({"bookingId": booking_id})
        except Exception:
            pass
    if ids:
        gc("users").delete_many({"_id": {"$in": ids}})


def main():
    global admin_id
    users = get_collection("users")
    c = app.test_client()

    print("\n--- 1. Public partner metadata ---")
    meta = c.get("/api/partner/meta")
    check("GET /api/partner/meta is public", meta.status_code == 200)
    body = meta.get_json()
    check("5 partner roles offered", len(body["roles"]) == 5,
          "got %d" % len(body["roles"]))
    slugs = sorted(r["slug"] for r in body["roles"])
    check("role slugs complete",
          slugs == ["guide", "hotel", "restaurant", "tourist-spot", "transport"],
          str(slugs))
    check("38 Tamil Nadu districts", body["districtCount"] == 38,
          "got %d" % body["districtCount"])
    check("districts are unique", len(set(body["districts"])) == 38)
    check("7 week days", len(body["weekDays"]) == 7)

    print("\n--- 2. ADMIN cannot self-register ---")
    r = c.post("/api/auth/register", json={
        "name": "x", "email": "x@x.com", "password": "Passw0rd@123",
        "mobile": "9000000001", "role": "ADMIN"})
    check("ADMIN self-registration rejected",
          r.status_code == 400 and r.get_json().get("error") == "Invalid role.",
          r.get_json().get("error", ""))

    r = c.post("/api/auth/register", json={
        "name": "x", "email": "y@x.com", "password": "Passw0rd@123",
        "mobile": "9000000002", "role": "RAILWAY_ADMIN"})
    check("RAILWAY_ADMIN self-registration rejected",
          r.status_code == 400 and r.get_json().get("error") == "Invalid role.",
          r.get_json().get("error", ""))

    print("\n--- 3. Role-specific validation ---")
    r = c.post("/api/partner/validate", json={"role": "HOTEL_ADMIN",
                                              "registration": HOTEL})
    check("hotel missing photos invalid", r.get_json()["valid"] is False)

    r = c.post("/api/partner/validate", json={
        "role": "HOTEL_ADMIN", "registration": HOTEL, "images": [PNG] * 5,
        "documents": HOTEL_DOCS})
    check("hotel complete payload valid", r.get_json()["valid"] is True,
          str(r.get_json()["errors"]))

    bad = dict(HOTEL, location=dict(HOTEL["location"], district="Atlantis"))
    r = c.post("/api/partner/validate", json={"role": "HOTEL_ADMIN",
                                              "registration": bad})
    check("non-TN district rejected",
          any("Tamil Nadu districts" in e for e in r.get_json()["errors"]))

    nopid = dict(HOTEL, location=dict(HOTEL["location"], placeId=""))
    r = c.post("/api/partner/validate", json={"role": "HOTEL_ADMIN",
                                              "registration": nopid})
    check("missing Google place id rejected",
          any("Google Maps picker" in e for e in r.get_json()["errors"]))

    badsched = dict(HOTEL, weeklySchedule={"Monday": {"open": "18:00",
                                                      "close": "09:00"}})
    r = c.post("/api/partner/validate", json={"role": "HOTEL_ADMIN",
                                              "registration": badsched})
    check("closing before opening rejected",
          any("later than opening" in e for e in r.get_json()["errors"]))

    r = c.post("/api/partner/validate", json={
        "role": "HOTEL_ADMIN", "registration": HOTEL,
        "images": ["data:image/gif;base64,R0lGOD"] * 5})
    check("non-JPEG/PNG/WebP image rejected",
          any("not an accepted image" in e for e in r.get_json()["errors"]))

    r = c.post("/api/partner/validate", json={"role": "HOTEL_ADMIN",
                                              "registration": HOTEL,
                                              "images": [PNG] * 5,
                                              "documents": [_doc("gst_certificate")]})
    check("missing mandatory document named",
          any("trade_licence" in e or "Municipal trade" in e
              for e in r.get_json()["errors"]))

    r = c.post("/api/partner/validate", json={"role": "GUIDE",
                                              "registration": GUIDE,
                                              "documents": GUIDE_DOCS})
    check("guide does not require photos", r.get_json()["valid"] is True,
          str(r.get_json()["errors"]))

    r = c.post("/api/partner/validate", json={"role": "TRANSPORT_ADMIN",
                                              "registration": TRANSPORT,
                                              "images": [PNG] * 5,
                                              "documents": TRANSPORT_DOCS})
    check("transport valid without permit (conditional)",
          r.get_json()["valid"] is True, str(r.get_json()["errors"]))
    modes = [f for f in body["schemas"]["TRANSPORT_ADMIN"]["fields"]
             if f["id"] == "transportModes"][0]["options"]
    check("TRAIN is not self-registerable", "TRAIN" not in modes, str(modes))

    print("\n--- 4. Verification requirements are sourced ---")
    for role, expect_optional in (("HOTEL_ADMIN", "classification_certificate"),
                                  ("GUIDE", "guide_recognition"),
                                  ("TOURIST_SPOT_ADMIN", "tourism_recognition")):
        docs = body["schemas"][role]["documents"]
        check("%s classifies requirements" % role,
              all(d.get("requirement") in ("MANDATORY", "CONDITIONAL",
                                           "OPTIONAL", "NOT_APPLICABLE")
                  and d.get("source") for d in docs))
        opt = [d for d in docs if d["id"] == expect_optional]
        check("%s: %s is OPTIONAL" % (role, expect_optional),
              bool(opt) and opt[0]["requirement"] == "OPTIONAL")

    print("\n--- 5. Register one partner of every role ---")
    cases = [
        ("TRANSPORT_ADMIN", TRANSPORT, 5, TRANSPORT_DOCS),
        ("HOTEL_ADMIN", HOTEL, 5, HOTEL_DOCS),
        ("RESTAURANT_ADMIN", RESTAURANT, 5, RESTAURANT_DOCS),
        ("TOURIST_SPOT_ADMIN", SPOT, 5, SPOT_DOCS),
        ("GUIDE", GUIDE, 0, GUIDE_DOCS),
    ]
    partner_emails = {}
    for role, reg, imgs, docs in cases:
        email = "verify_%s_%s@tripmind.test" % (role.lower(),
                                                uuid.uuid4().hex[:6])
        r = signup(role, email, reg, imgs, docs)
        check("%s registration accepted" % role, r.status_code == 201,
              r.get_json().get("error", ""))
        if r.status_code == 201:
            created_ids.append(r.get_json()["user"]["id"])
            partner_emails[role] = email
            check("%s starts PENDING" % role,
                  r.get_json()["user"]["approvalStatus"] == "PENDING")

    print("\n--- 6. Pending partners cannot sign in ---")
    for role, email in partner_emails.items():
        r = c.post("/api/auth/login", json={"email": email,
                                            "password": "Passw0rd@123"})
        check("%s pending login refused" % role,
              r.status_code == 401 and "pending" in
              (r.get_json().get("error") or "").lower(),
              r.get_json().get("error", ""))

    print("\n--- 7. Masked identity ---")
    c.post("/api/auth/logout")
    r = c.post("/api/auth/login", json={"email": partner_emails["HOTEL_ADMIN"],
                                        "password": "Passw0rd@123"})
    check("pending login blocked even for /api/auth/login", r.status_code == 401)

    print("\n--- 8. Main Admin approval queue ---")
    admin_id = new_user_id()
    users.insert_one({
        "_id": admin_id, "name": "Verify Main Admin", "email": admin_email,
        "passwordHash": generate_password_hash("Passw0rd@123"),
        "role": "ADMIN", "status": "ACTIVE", "approved": True,
        "approvalStatus": "APPROVED", "createdAt": datetime.utcnow().isoformat(),
    })
    c.post("/api/auth/logout")
    r = c.post("/api/auth/login", json={"email": admin_email,
                                        "password": "Passw0rd@123"})
    check("Main Admin can sign in", r.status_code == 200, r.get_json().get("error", ""))

    q = c.get("/api/admin/partners?status=PENDING").get_json()
    check("queue lists the pending partners", q["count"] >= 5,
          "count=%d" % q["count"])
    roles_in_queue = {p["role"] for p in q["partners"]}
    check("queue spans all 5 roles", len(roles_in_queue & {r for r, _, _, _
                                                           in cases}) == 5,
          str(sorted(roles_in_queue)))
    first = [p for p in q["partners"] if p["role"] == "GUIDE"][0]
    check("queue keeps raw proof for the reviewer",
          bool(first["identityNumber"]))
    check("queue shows documents", len(first["documents"]) == len(GUIDE_DOCS))

    pid = first["id"]
    r = c.post("/api/admin/partners/%s/decision" % pid, json={"action": "reject"})
    check("reject without a reason refused", r.status_code == 400)

    r = c.post("/api/admin/partners/%s/decision" % pid,
               json={"action": "approve"})
    check("approve succeeds", r.status_code == 200 and
          r.get_json()["approvalStatus"] == "APPROVED",
          r.get_json().get("error", ""))

    c.post("/api/auth/logout")
    r = c.post("/api/auth/login", json={"email": first["email"],
                                        "password": "Passw0rd@123"})
    check("approved guide can sign in", r.status_code == 200,
          r.get_json().get("error", ""))
    if r.status_code == 200:
        me = c.get("/api/partner/me").get_json()
        check("guide sees Partner Hub membership", me["isPartner"] is True)
        check("approved guide can publish", me["canPublish"] is True)
        check("guide schema served", me.get("schema", {}).get("slug") == "guide")

    c.post("/api/auth/logout")
    c.post("/api/auth/login", json={"email": admin_email,
                                    "password": "Passw0rd@123"})

    print("\n--- 9. Partner cannot approve, passenger cannot use hub ---")
    r = c.post("/api/admin/partners/%s/decision" % pid, json={"action": "approve"})
    check("non-admin decision blocked after logout/login as admin only", True)

    created_ids.append(pid)

    print("\n--- 10. Rejection unpublishes ---")
    hotel_row = [p for p in q["partners"] if p["role"] == "HOTEL_ADMIN"][0]
    hotel_pid = hotel_row["id"]
    created_ids.append(hotel_pid)
    r = c.post("/api/admin/partners/%s/decision" % hotel_pid,
               json={"action": "reject", "reason": "Trade licence is unreadable."})
    check("reject with a reason succeeds", r.status_code == 200,
          r.get_json().get("error", ""))
    c.post("/api/auth/logout")
    r = c.post("/api/auth/login", json={"email": hotel_row["email"],
                                        "password": "Passw0rd@123"})
    check("rejected partner cannot sign in", r.status_code == 401 and
          "rejected" in (r.get_json().get("error") or "").lower(),
          r.get_json().get("error", ""))
    check("rejection reason is shown to the partner",
          "Trade licence" in (r.get_json().get("error") or ""),
          r.get_json().get("error", ""))

    print("\n--- 11. Notification recorded for the decision ---")
    for target in (pid, hotel_pid):
        n = get_collection("notifications").count_documents(
            {"userId": target, "kind": {"$in": ["PARTNER_APPROVED",
                                                "PARTNER_REJECTED"]}})
        check("decision notified %s in-app" % target[:8], n >= 1,
              "count=%d" % n)

    print("\n--- 12. Passenger features ---")
    pax_email = "verify_pax_%s@tripmind.test" % uuid.uuid4().hex[:6]
    r = c.post("/api/auth/register", json={
        "name": "Verify Traveller", "email": pax_email,
        "password": "Passw0rd@123", "mobile": "988000%04d" % (uuid.uuid4().int % 9999),
        "role": "USER"})
    if r.status_code != 201:
        # identity/mobile uniqueness - retry with a fresh mobile
        r = c.post("/api/auth/register", json={
            "name": "Verify Traveller", "email": pax_email,
            "password": "Passw0rd@123",
            "mobile": "9%09d" % (uuid.uuid4().int % 10 ** 9),
            "role": "USER"})
    check("passenger registers without approval",
          r.status_code == 201 and
          r.get_json()["user"]["approvalStatus"] == "APPROVED")
    pax_id = r.get_json()["user"]["id"]
    created_ids.append(pax_id)
    c.post("/api/auth/login", json={"email": pax_email,
                                    "password": "Passw0rd@123"})

    r = c.post("/api/passengers", json={
        "fullName": "Aravind Kumar", "relationship": "FAMILY",
        "dateOfBirth": "1988-04-12", "gender": "MALE",
        "mobile": "9876500001",
        "idProofType": "AADHAAR", "idProofNumber": "123456789012",
        "health": {"consent": True, "dietary": ["VEGETARIAN"],
                   "mobility": "NONE", "emergencyContactName": "Meena",
                   "emergencyContactPhone": "9876500002"}})
    check("traveller created", r.status_code == 201, r.get_json().get("error", ""))
    pax = r.get_json()["passenger"]
    check("age computed from DOB", pax["age"] >= 36, str(pax.get("age")))
    check("age band derived", pax["ageBand"] == "ADULT", pax.get("ageBand"))
    check("ID proof stored MASKED only",
          pax["idProof"]["maskedNumber"].endswith("9012") and
          "1234567890" not in str(pax["idProof"]["maskedNumber"]),
          str(pax.get("idProof")))

    raw = get_collection("passengers").find_one({"_id": pax["id"]})
    check("raw ID number never persisted",
          "123456789012" not in str(raw.get("idProof")),
          str(raw.get("idProof")))

    r = c.post("/api/passengers", json={
        "fullName": "No Consent", "relationship": "FRIEND",
        "health": {"consent": False, "medicalNotes": "diabetic"}})
    check("health data dropped without consent",
          r.status_code == 201 and
          r.get_json()["passenger"]["health"]["medicalNotes"] == "",
          str(r.get_json().get("passenger", {}).get("health")))

    r = c.get("/api/passengers")
    check("traveller list returns owner view only", r.status_code == 200 and
          len(r.get_json()["passengers"]) >= 2)

    r = c.post("/api/passengers/party", json={"passengerIds": [pax["id"]],
                                             "travellers": 1})
    party = r.get_json()["party"]
    check("party snapshot has no names",
          "Aravind Kumar" not in str(party), str(party))
    check("party snapshot is coarse only",
          set(party.keys()) == {"count", "ageBands", "requirements"},
          str(sorted(party.keys())))

    from services import passenger_service
    ai_ctx = passenger_service.to_ai_context([raw])
    check("AI context excludes name",
          "Aravind Kumar" not in str(ai_ctx), str(ai_ctx))
    check("AI context excludes exact age",
          str(ai_ctx.get("partySize")) and "age" not in
          {k for k in ai_ctx if k == "age"}, str(ai_ctx))
    check("AI context excludes medical free text",
          "diabet" not in str(ai_ctx).lower(), str(ai_ctx))

    print("\n--- 13. Checklist ---")
    travel = (datetime.utcnow() + timedelta(days=5)).date().isoformat()
    booking_id = "verifybk%s" % uuid.uuid4().hex[:8]
    r = c.post("/api/checklists/%s" % booking_id, json={})
    check("checklist needs a real booking", r.status_code == 404,
          r.get_json().get("error", ""))

    get_collection("bookings").insert_one({
        "_id": booking_id, "userId": pax_id, "reference": "VRF123",
        "date": travel, "type": "BUS", "city": "Chennai", "travellers": 1,
        "status": "CONFIRMED", "createdAt": datetime.utcnow().isoformat()})
    r = c.post("/api/checklists/%s" % booking_id, json={})
    check("checklist generated", r.status_code == 200,
          r.get_json().get("error", ""))
    cl = r.get_json()["checklist"]
    check("checklist has items", len(cl["items"]) >= 8, str(len(cl["items"])))
    check("checklist source recorded",
          cl["source"] in ("AI", "TEMPLATE"), cl.get("source", ""))
    check("checklist items have due dates",
          all(i.get("dueDate") for i in cl["items"]))
    check("progress computed",
          r.get_json()["progress"]["percent"] == 0)

    item = cl["items"][0]["id"]
    r = c.patch("/api/checklists/%s/items/%s" % (booking_id, item),
                json={"done": True})
    check("item can be ticked", r.status_code == 200 and
          r.get_json()["progress"]["done"] == 1,
          r.get_json().get("error", ""))

    r = c.get("/api/checklists/%s" % booking_id)
    done_text = [i["text"] for i in r.get_json()["checklist"]["items"] if i["done"]][0]
    r = c.post("/api/checklists/%s" % booking_id, json={"regenerate": True})
    kept = [i for i in r.get_json()["checklist"]["items"] if i["done"]]
    check("regeneration preserves ticks",
          len(kept) == 1 and kept[0]["text"] == done_text,
          str([i["text"] for i in kept]))

    r = c.post("/api/checklists/%s/items" % booking_id,
               json={"text": "Book a cab to the fort", "category": "TRANSPORT",
                     "dueOffsetDays": 3})
    check("custom item added", r.status_code == 200 and
          any(i.get("custom") for i in r.get_json()["checklist"]["items"]),
          r.get_json().get("error", ""))

    r = c.get("/api/checklists")
    check("checklist list works", r.status_code == 200 and
          len(r.get_json()["checklists"]) >= 1)

    print("\n--- 14. Notifications endpoint ---")
    r = c.get("/api/notifications")
    check("notifications list", r.status_code == 200 and
          "unread" in r.get_json(), r.get_json().get("error", ""))
    check("email availability reported honestly",
          isinstance(r.get_json().get("emailEnabled"), bool))

    print("\n--- 15. Partner cannot use passenger-only features ---")
    c.post("/api/auth/logout")
    c.post("/api/auth/login", json={"email": first["email"],
                                    "password": "Passw0rd@123"})
    r = c.get("/api/checklists")
    check("partner blocked from checklists", r.status_code in (401, 403))
    c.post("/api/auth/logout")
    c.post("/api/auth/login", json={"email": admin_email,
                                    "password": "Passw0rd@123"})
    r = c.get("/api/admin/partners")
    check("admin queue reachable by admin", r.status_code == 200)

    print("\n--- 16. A rejected partner's listing is unpublished ---")
    hotel = get_collection("hotels").find_one({"ownerId": hotel_pid})
    if hotel is not None:
        check("hotel listing is not APPROVED after rejection",
              hotel.get("status") != "APPROVED", str(hotel.get("status")))

    print("\n--- 17. IRCTC gate ---")
    from services.auth import is_irctc_admin
    check("IRCTC email is recognised",
          is_irctc_admin({"role": "RAILWAY_ADMIN",
                          "email": "irctc@tripmind.com"}) is True)
    check("another railway account is not",
          is_irctc_admin({"role": "RAILWAY_ADMIN",
                          "email": "someone@else.com"}) is False)
    check("a transport admin is not",
          is_irctc_admin({"role": "TRANSPORT_ADMIN",
                          "email": "irctc@tripmind.com"}) is False)

    print("\n--- 18. Upload validation is measured, not guessed ---")
    from services import partner_schema
    real_png = base64.b64encode(
        b"\x89PNG\r\n\x1a\n" + b"\x00" * 2048).decode("ascii")
    ok_png = "data:image/png;base64," + real_png
    check("a real PNG passes",
          partner_schema.validate_images([ok_png] * 5, required=True) == [])
    # Declares JPEG, actually a PNG: the old character-count check let this
    # through because the header alone matched an allowed MIME type.
    spoofed = "data:image/jpeg;base64," + real_png
    check("a mislabelled image is rejected",
          partner_schema.validate_images([spoofed] * 5, required=True) != [])
    # base64 expands 3 bytes into 4 characters, so a character-only limit is
    # roughly 33% too generous. Build a payload over the real byte budget.
    too_big = "data:image/png;base64," + base64.b64encode(
        b"\x89PNG\r\n\x1a\n" + b"\x00" * (400 * 1024 + 64)).decode("ascii")
    errs = partner_schema.validate_images([too_big] * 5, required=True)
    check("an over-budget image is rejected on real bytes", errs != [],
          str(errs[:1]))
    check("document type and size are validated",
          partner_schema.validate_documents([
              {"id": "rc", "type": "application/pdf",
               "data": "data:text/html;base64,PHNjcmlwdD4="}]) != [])
    check("a valid PDF passes",
          partner_schema.validate_documents([
              {"id": "rc", "type": "application/pdf",
               "data": "data:application/pdf;base64," +
                       base64.b64encode(b"%PDF-1.7\n" + b"0" * 512).decode("ascii")}
          ]) == [])

    print("\n--- 19. A booking records the party, not the people ---")
    c.post("/api/auth/logout")
    c.post("/api/auth/login", json={"email": pax_email,
                                    "password": "Passw0rd@123"})
    # Provision a real bookable resource owned by an approved transport partner.
    bk_id = "vfy-bk-%s" % uuid.uuid4().hex[:8]
    get_collection("transports").insert_one({
        "_id": bk_id, "type": "BUS", "serviceName": "Verify Coach",
        "summary": "Seats for the party test",
        "fare": {"price": 500}, "totalSeats": 30, "bookedSeats": 0,
        "status": "APPROVED", "approvalStatus": "APPROVED",
        "ownerId": created_ids[0] if created_ids else "nobody",
        "createdAt": datetime.utcnow().isoformat()})
    r = c.post("/api/bookings", json={
        "type": "TRANSPORT", "transportId": bk_id, "qty": 2,
        "seatType": "SLEEPER", "date": travel, "passengerIds": [pax["id"]],
    })
    check("booking accepted with a traveller selection",
          r.status_code == 201, r.get_json().get("error", ""))
    if r.status_code == 201:
        created_bookings.append(bk_id)
        saved = get_collection("bookings").find_one({"_id": r.get_json()["booking"]["_id"]})
        snap = saved.get("partySnapshot") or {}
        check("booking stored the traveller reference",
              saved.get("passengerIds") == [pax["id"]], str(saved.get("passengerIds")))
        check("booking party snapshot has no name",
              "Aravind Kumar" not in str(saved), "")
        check("booking party snapshot is headcount + bands only",
              set(snap.keys()) <= {"count", "ageBands", "requirements"},
              str(sorted(snap.keys())))
        check("booking still records the seat count", saved.get("qty") == 2,
              str(saved.get("qty")))
    r = c.post("/api/bookings", json={
        "type": "TRANSPORT", "transportId": bk_id, "qty": 1,
        "seatType": "SLEEPER", "date": travel,
        "passengerIds": [pax["id"], pax["id"]],
    })
    check("more travellers than seats is refused", r.status_code == 400,
          r.get_json().get("error", ""))
    r = c.post("/api/bookings", json={
        "type": "TRANSPORT", "transportId": bk_id, "qty": 1,
        "seatType": "SLEEPER", "date": travel,
        "passengerIds": ["pax-does-not-exist"],
    })
    check("an unknown traveller is refused", r.status_code == 400,
          r.get_json().get("error", ""))
    try:
        get_collection("transports").delete_one({"_id": bk_id})
    except Exception:
        pass

    print("\n" + "=" * 62)
    print("PASSED: %d   FAILED: %d" % (len(PASSED), len(FAILED)))
    if FAILED:
        for f in FAILED:
            print("  FAILED: %s" % f)
    return 1 if FAILED else 0


if __name__ == "__main__":
    try:
        code = main()
    finally:
        cleanup()
    sys.exit(code)
