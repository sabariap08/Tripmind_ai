import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import app as appmod

c = appmod.app.test_client()


def show(label, status, body):
    print(f"[{status}] {label}")
    if isinstance(body, dict):
        e = body.get("error")
        if e:
            print("   error:", e)
    s = json.dumps(body, ensure_ascii=False)
    print("   ", s[:220])


# 1. login as USER
r = c.post("/api/auth/login", json={"email": "user@tripmind.test", "password": "User@12345"})
b = r.get_json()
show("login user", r.status_code, b)

# 2. role-gate check: user tries /api/admin/stats -> 403
r = c.get("/api/admin/stats")
show("user@admin/stats (expect 403)", r.status_code, r.get_json())

# 3. create trip KPR -> Chennai by train
r = c.post("/api/trips", json={
    "origin": "KPR", "destination": "Chennai", "startDate": "2026-09-20",
    "endDate": "2026-09-22", "budget": 50000, "travelers": 2,
    "travelStyle": "BALANCED", "transportType": "TRAIN"})
b = r.get_json()
show("create trip", r.status_code, b)
trip_id = b.get("tripId")

# 4. generate -> uses DB catalogue (train + spots + guide)
r = c.post(f"/api/trips/{trip_id}/generate")
b = r.get_json()
show("generate (db-backed)", r.status_code, b)
if b.get("selectedPlan"):
    p = b["selectedPlan"]
    print("   source:", b.get("source"), "| transport:", p.get("transport", {}).get("type"),
          "| totalCost:", p.get("totalCost"), "| spots:", len([a for a in p.get("activities", []) if a.get("spotId")]),
          "| guide:", any("Guided" in a.get("title", "") for a in p.get("activities", [])))
    print("   ml:", json.dumps(b.get("ml", {}), ensure_ascii=False)[:240])

# 5. transport search for corridor
r = c.get("/api/transport/search?origin=KPR&destination=Chennai")
b = r.get_json()
show("transport search KPR->Chennai", r.status_code, b)
if b.get("transports"):
    print("   found:", [(t["type"], t["serviceName"]) for t in b["transports"]])

# 6. spots list
r = c.get("/api/spots")
b = r.get_json()
show("spots list", r.status_code, b)
if b.get("spots"):
    print("   count:", len(b["spots"]), "| first:", b["spots"][0]["name"])

# 7. guides browse Chennai with a date
r = c.get("/api/guides/browse?location=Chennai")
b = r.get_json()
show("guides browse", r.status_code, b)
if b.get("guides"):
    print("   guide:", b["guides"][0]["name"], b["guides"][0].get("pricing"))

# 8. book transport by user
transports = c.get("/api/transport/search?origin=KPR&destination=Chennai&type=TRAIN").get_json()["transports"]
if transports:
    tid = transports[0]["transportId"]
    r = c.post("/api/bookings", json={"type": "TRANSPORT", "transportId": tid,
                                      "qty": 2, "seatType": "SL", "date": "2026-09-20",
                                      "passengers": [{"name": "Arjun"}, {"name": "Priya"}]})
    b = r.get_json()
    show("book train seats (2)", r.status_code, b)

# 9. admin login + stats
c.post("/api/auth/logout")
r = c.post("/api/auth/login", json={"email": "admin@tripmind.test", "password": "Admin@12345"})
show("login admin", r.status_code, r.get_json())
r = c.get("/api/admin/stats")
b = r.get_json()
show("admin stats", r.status_code, b)
print("   users:", b.get("users"), "transports:", b.get("transports"),
      "spots:", b.get("spots"), "bookings:", b.get("bookings"), "revenue:", b.get("revenue"))

# 10. admin approves view of transports (all)
r = c.get("/api/transport/list")
b = r.get_json()
print("[transport/list by admin] count:", len(b.get("transports", [])))

# 11. transport admin flow: register a new bus with invalid seats -> 400
c.post("/api/auth/logout")
c.post("/api/auth/login", json={"email": "transport@tripmind.test", "password": "Transport@12345"})
r = c.post("/api/transport/register", json={"type": "BUS", "busNumber": "TN38-XX-0001",
    "boardingPoint": "KPR", "boardingTime": "20:00", "droppingPoint": "Chennai CMBT",
    "droppingTime": "04:00", "totalSeats": 20, "sleeperSeats": 12, "seaterSeats": 12})
show("register bus bad seats (expect 400)", r.status_code, r.get_json())

# 12. tourist admin: add guide location (authorized by tourist admin)
c.post("/api/auth/logout")
c.post("/api/auth/login", json={"email": "tourist@tripmind.test", "password": "Tourist@12345"})
r = c.post("/api/guide-locations", json={"name": "Guindy", "city": "Chennai", "spots": ["Guindy National Park"]})
show("tourist admin adds guide location", r.status_code, r.get_json())

# 13. guide: set pricing + availability at authorized location
c.post("/api/auth/logout")
c.post("/api/auth/login", json={"email": "guide@tripmind.test", "password": "Guide@12345"})
r = c.post("/api/guide/pricing", json={"pricePerHour": 600, "pricePerDay": 3500})
show("guide pricing", r.status_code, r.get_json())
r = c.post("/api/guide/availability", json={"date": "2026-09-21", "from": "09:00", "to": "17:00",
                                             "locations": ["Marina Beach"]})
show("guide availability", r.status_code, r.get_json())
# unauthorized location should fail
r = c.post("/api/guide/availability", json={"date": "2026-09-22", "from": "09:00", "to": "12:00",
                                             "locations": ["DangerZone"]})
show("guide availability bad location (expect 400)", r.status_code, r.get_json())

# 14. logout & auth me
c.post("/api/auth/logout")
r = c.get("/api/auth/me")
print("[me after logout] -> user:", r.get_json().get("user"))

print("\nSMOKE TEST DONE")