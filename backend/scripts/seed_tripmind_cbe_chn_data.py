"""Seed the TripMind AI Coimbatore <-> Chennai corridor development database.

Creates the full active-corridor catalogue used by the DB-backed planner:

  Accounts: system Main Admin, 1 Railway / IRCTC admin, 6 transport admins,
            hotel admins, restaurant admins, travel spot admins and guides
            (password is exactly "password" for every seeded account).

  Trains:   20 x IR trains on the Coimbatore Junction <-> Chennai Egmore axis
            (10 each direction) owned by the Railway admin, with coach classes
            and per-class pricing.
  Buses:    30 x inter-city buses (Coimbatore <-> Chennai, both directions).
  Flights:  10 x Coimbatore (CJB) <-> Chennai (MAA) flights across 2 airlines.
  Cabs:     30 x cabs/autos based in Coimbatore and Chennai with km fares.
  Lounges:  Railway lounges at Egmore / Chennai Central / Coimbatore Junction.
  Hotels:   Corridor hotels (Chennai, Coimbatore, Ooty) with room inventory.
  Restaurants: corridor restaurants + food items.
  Spots:    Tourist spots (Chennai, Coimbatore, Ooty, Mahabalipuram) + tours.
  Guides:   Guide profiles, pricing, and locked weekly availability.

IDEMPOTENT: every write is an upsert keyed on a stable natural key (email,
transport numberKey, owner+name, restaurantId+name, spotId+tour name,
guideId+weekStart, ownerId+name for lounges). Re-running only syncs data to
the definitions below; it never wipes record-level data it does not own.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash
from bson.objectid import ObjectId
from services.mongodb import get_collection, ensure_unique_indexes
from services.auth import new_user_id
from services import duplicate
from config import ROLES

from scripts.seed_dev import seed_admin

PASSWORD = "password"

# Verified at seed-build time: every Unsplash image id used below (or carried
# over from the original seed_data.IMG) previously returned HTTP 200. Images are
# hotlinked from the Unsplash CDN (Unsplash License, free to use).
IMG = {
    "india_gate": "photo-1524492412937-b28074a5d7da",
    "taj": "photo-1564507592333-c60657eea523",
    "hawa_mahal": "photo-1599661046289-e31897846e41",
    "houseboat": "photo-1602216056096-3b40cc0c9944",
    "goa_beach": "photo-1512343879784-a960bf40e7f2",
    "varanasi": "photo-1561361513-2d000a50f0dc",
    "himalaya": "photo-1626621341517-bbf3d9990a23",
    "andaman": "photo-1544550581-5f7ceaf7f992",
    "rajasthan_fort": "photo-1477587458883-47145ed94245",
    "beach1": "photo-1507525428034-b723cf961d3e",
    "beach2": "photo-1519046904884-53103b34b206",
    "resort_pool": "photo-1566073771259-6a8506099945",
    "room1": "photo-1582719478250-c89cae4dc85b",
    "room2": "photo-1618773928121-c32242e63f39",
    "lake": "photo-1501785888041-af3ef285b470",
    "cafe1": "photo-1554118811-1e0d58224f24",
    "dosa": "photo-1630383249896-424e482df921",
    "bus1": "photo-1544620347-c4fd4a3d5957",
    "bus2": "photo-1570125909232-eb263c188f7e",
    "flight1": "photo-1436491865332-7a61a109cc05",
    "auto1": "photo-1502877338535-766e1452684a",
    "car1": "photo-1549317661-bd32c8ce0db2",
    "rail1": "photo-1474487548417-781cb71495f3",
    "airport1": "photo-1556388158-158ea5ccacbd",
    "food1": "photo-1567620905732-2d1ec7ab7445",
    "restaurant1": "photo-1414235077428-338989a2e8c0",
    "restaurant2": "photo-1517248135467-4c7edcad34c4",
    "restaurant3": "photo-1552566626-52f8b828add9",
    "food2": "photo-1546069901-ba9599a7e63c",
    "food3": "photo-1565299624946-b28f40a0ae38",
    "food4": "photo-1504674900247-0877df9cc836",
    "food5": "photo-1540189549336-e6e99c3679fe",
    "veg": "photo-1512621776951-a57141f2eefd",
    "coffee1": "photo-1495474472287-4d71bcdd2085",
    "breakfast1": "photo-1493770348161-369560ae357d",
    "breakfast2": "photo-1484723091739-30a097e8f929",
    "dessert1": "photo-1565958011703-44f9829ba187",
    "apartment1": "photo-1560448204-e02f11c3d0e2",
    "room3": "photo-1554995207-c18c203602cb",
    "room4": "photo-1566665797739-1674de7a421a",
    "room5": "photo-1590490360182-c33d57733427",
    "car2": "photo-1533473359331-0135ef1b58bf",
    "car3": "photo-1485291571150-772bcfc10da5",
    "bar1": "photo-1514362545857-3bc16c4c7d1b",
    "mountain_night": "photo-1519681393784-d120267933ba",
    "lake_mtn": "photo-1500534314209-a25ddb2bd429",
    "nature1": "photo-1506744038136-46273834b3fb",
    "street_india": "photo-1522199755839-a2bacb67c546",
    "travel1": "photo-1516426122078-c23e76319801",
    "india_street2": "photo-1471874276752-65e2d717604a",
}

_IMG_USED = set()


def img_url(key):
    _IMG_USED.add(key)
    return "https://images.unsplash.com/%s?auto=format&fit=crop&w=700&q=70" % IMG[key]


def _id():
    return str(ObjectId())


def _now():
    return datetime.utcnow().isoformat()


def _created():
    return datetime.utcnow().isoformat()


def _mobile(i):
    return "%d%08d" % (9, 30000000 + i)


def _gst(i):
    return "33AAAAA%04dZ%02dN%02d" % (i + 1, (i + 1) % 30, (i + 1) % 10)


def _identity(i):
    return "%012d" % (740000000000 + i)


def _state_for(city):
    return "Tamil Nadu"


# ---------------------------------------------------------------------------
# Account table (single source of truth for credentials + PDF generator)
# ---------------------------------------------------------------------------
ACCOUNTS = [
    # -- Passenger (traveller / USER role) --
    {"role": "USER", "name": "TripMind Traveller", "company": "Passenger",
     "email": "user@tripmind.com", "city": "Chennai", "companyId": "usr"},
    # -- Railway / IRCTC Admin --
    {"role": "RAILWAY_ADMIN", "name": "T. Narayanan", "company": "Southern Railway — Coimbatore Division",
     "email": "railway.southern@tripmind.demo", "city": "Coimbatore", "companyId": "ir"},
    # -- Transport Admins --
    {"role": "TRANSPORT_ADMIN", "name": "S. Ramesh", "company": "SRL Travels",
     "email": "transport.srl@tripmind.demo", "city": "Coimbatore", "companyId": "srl"},
    {"role": "TRANSPORT_ADMIN", "name": "K. Murugan", "company": "KMS Transport",
     "email": "transport.kms@tripmind.demo", "city": "Chennai", "companyId": "kms"},
    {"role": "TRANSPORT_ADMIN", "name": "M. Varun", "company": "Blue Horizon Aviation",
     "email": "transport.bluehorizon@tripmind.demo", "city": "Chennai", "companyId": "bha"},
    {"role": "TRANSPORT_ADMIN", "name": "P. Nandini", "company": "Kongu Kaveri Air",
     "email": "transport.kongukaveri@tripmind.demo", "city": "Coimbatore", "companyId": "kka"},
    {"role": "TRANSPORT_ADMIN", "name": "G. Thirunavukkarasu", "company": "GTG Tours & Travels",
     "email": "transport.gtg@tripmind.demo", "city": "Coimbatore", "companyId": "gtg"},
    {"role": "TRANSPORT_ADMIN", "name": "S. Aneesh", "company": "Vembanad Cabs",
     "email": "transport.vembanad@tripmind.demo", "city": "Chennai", "companyId": "vcb"},
    # -- Hotel Admins --
    {"role": "HOTEL_ADMIN", "name": "R. Priya", "company": "Grand Chennai Residency",
     "email": "hotel.grandchennai@tripmind.demo", "city": "Chennai", "companyId": "gcr"},
    {"role": "HOTEL_ADMIN", "name": "V. Deepa", "company": "Marina Gateway",
     "email": "hotel.marinagateway@tripmind.demo", "city": "Chennai", "companyId": "mgw"},
    {"role": "HOTEL_ADMIN", "name": "P. Karthik", "company": "Hotel Residency",
     "email": "hotel.residency@tripmind.demo", "city": "Coimbatore", "companyId": "hre"},
    {"role": "HOTEL_ADMIN", "name": "A. Lakshmi", "company": "Kovai Palm Court",
     "email": "hotel.kovaipalm@tripmind.demo", "city": "Coimbatore", "companyId": "kpc"},
    {"role": "HOTEL_ADMIN", "name": "N. Suresh", "company": "Ooty Lake View Stay",
     "email": "hotel.ootylakeview@tripmind.demo", "city": "Ooty", "companyId": "olv"},
    # -- Restaurant Admins --
    {"role": "RESTAURANT_ADMIN", "name": "K. Radhakrishnan", "company": "Annapoorna South Indian Kitchen",
     "email": "restaurant.annapoorna@tripmind.demo", "city": "Coimbatore", "companyId": "ann"},
    {"role": "RESTAURANT_ADMIN", "name": "V. Imran", "company": "Chennai Spice Junction",
     "email": "restaurant.chennaispice@tripmind.demo", "city": "Chennai", "companyId": "csj"},
    {"role": "RESTAURANT_ADMIN", "name": "J. Wilson", "company": "Marina Deck",
     "email": "restaurant.marinadeck@tripmind.demo", "city": "Chennai", "companyId": "mdk"},
    {"role": "RESTAURANT_ADMIN", "name": "L. Meenakshi", "company": "Kovai Botani Cafe",
     "email": "restaurant.kovaibotani@tripmind.demo", "city": "Coimbatore", "companyId": "kbc"},
    # -- Travel Spot Admins --
    {"role": "TOURIST_SPOT_ADMIN", "name": "D. Bhavani", "company": "Heritage Tamil Nadu",
     "email": "spot.heritagetn@tripmind.demo", "city": "Chennai", "companyId": "htn"},
    {"role": "TOURIST_SPOT_ADMIN", "name": "S. Kannan", "company": "Shoreline Monuments",
     "email": "spot.shoreline@tripmind.demo", "city": "Mahabalipuram", "companyId": "sln"},
    {"role": "TOURIST_SPOT_ADMIN", "name": "R. Joseph", "company": "Nilgiris Tourism",
     "email": "spot.nilgiris@tripmind.demo", "city": "Ooty", "companyId": "ngs"},
    {"role": "TOURIST_SPOT_ADMIN", "name": "B. Kavitha", "company": "Kongu Scenic Tours",
     "email": "spot.konguscenic@tripmind.demo", "city": "Coimbatore", "companyId": "ksc"},
    # -- Guides --
    {"role": "GUIDE", "name": "Arun Prakash", "company": "Arun Prakash — Chennai Heritage",
     "email": "guide.arun@tripmind.demo", "city": "Chennai", "companyId": "gar"},
    {"role": "GUIDE", "name": "Ravi Shankar", "company": "Ravi Shankar — Kovai Trails",
     "email": "guide.ravi@tripmind.demo", "city": "Coimbatore", "companyId": "gra"},
    {"role": "GUIDE", "name": "Meera Krishnan", "company": "Meera Krishnan — Mahabalipuram History",
     "email": "guide.meera@tripmind.demo", "city": "Mahabalipuram", "companyId": "gme"},
    {"role": "GUIDE", "name": "Bhuvana Suresh", "company": "Bhuvana Suresh — Ooty Nature",
     "email": "guide.bhuvana@tripmind.demo", "city": "Ooty", "companyId": "gbh"},
]

_ROLE_LABEL = {
    "USER": "Passenger",
    "RAILWAY_ADMIN": "Railway Admin",
    "TRANSPORT_ADMIN": "Transport Admin",
    "HOTEL_ADMIN": "Hotel Admin",
    "RESTAURANT_ADMIN": "Restaurant Admin",
    "TOURIST_SPOT_ADMIN": "Travel Spot Admin",
    "GUIDE": "Guide",
}


def _registration_fields(role, a, i):
    base = {"city": a["city"], "ownerName": a["name"]}
    reg = {"registration": {}}
    if role in ("RAILWAY_ADMIN", "TRANSPORT_ADMIN"):
        net = a["city"] + " - Chennai corridor" if role == "RAILWAY_ADMIN" else a["city"] + " district"
        reg["registration"] = {
            "companyName": a["company"],
            "serviceArea": net,
            "companyCity": a["city"],
            "companyAddress": "Road no. %d, %s" % (i, a["city"]),
            "companyPhone": _mobile(i),
            "driverCount": str(2 + i % 8),
            "description": ("Operates trains and lounges on the Coimbatore-Chennai rail corridor."
                            if role == "RAILWAY_ADMIN"
                            else "Registered inter-city and local transport provider."),
        }
    elif role == "HOTEL_ADMIN":
        reg["registration"] = {
            "hotelName": a["company"],
            "ownerName": a["name"],
            "contactNumber": _mobile(i),
            "address": "Hotel street %d, %s" % (i, a["city"]),
            "registrationInfo": "Registered hospitality operator.",
        }
    elif role == "RESTAURANT_ADMIN":
        reg["registration"] = {
            "restaurantName": a["company"],
            "ownerName": a["name"],
            "contactNumber": _mobile(i),
            "address": "Food street %d, %s" % (i, a["city"]),
            "businessRegInfo": "FSSAI registered establishment.",
        }
    elif role == "TOURIST_SPOT_ADMIN":
        reg["registration"] = {
            "organisationName": a["company"],
            "organisationCity": a["city"],
            "adminName": a["name"],
            "contactNumber": _mobile(i),
            "idType": "AADHAAR",
            "idNumber": _identity(i),
            "govtApproval": "State tourism board approved operator.",
            "locationAddress": "Tourist office %d, %s" % (i, a["city"]),
            "city": a["city"],
            "district": a["city"],
            "state": _state_for(a["city"]),
            "optimalTimes": "06:00-09:00, 09:00-12:00, 12:00-15:00, 15:00-18:00, 18:00-21:00",
            "entryFee": "0",
            "workingDays": "Mon,Tue,Wed,Thu,Fri,Sat,Sun",
        }
    elif role == "GUIDE":
        reg["registration"] = {
            "dob": "1985-%02d-%02d" % (1 + i % 12, 1 + i % 27),
            "contactNumber": _mobile(i),
            "address": "Guide lane %d, %s" % (i, a["city"]),
            "idType": "AADHAAR",
            "idNumber": _identity(i),
            "qualification": "Certified regional tour guide",
            "experience": str(3 + i % 12),
            "languages": "Tamil, English",
            "base location": a["city"],
        }
    return reg


def _profile(role, a, i):
    p = {"scope": ""}
    if role in ("RAILWAY_ADMIN", "TRANSPORT_ADMIN"):
        p["serviceName"] = a["company"]
        p["contact"] = a["company"] + ", " + a["city"]
        p["description"] = "Registered %s serving the Coimbatore-Chennai corridor." % (
            "railway operator" if role == "RAILWAY_ADMIN" else "transport provider")
    if role == "GUIDE":
        specialty = a["company"].split("—")[1].strip()
        p.update({
            "specialty": specialty,
            "languages": ["Tamil", "English"],
            "experience": 3 + i % 12,
            "city": a["city"],
            "rating": round(4.0 + (i % 5) * 0.2, 1),
            "reviewCount": 8 + i,
            "status": "ACTIVE",
            "locations": [a["city"]],
        })
    return p


def seed_users():
    users = get_collection("users")
    seeded = {}
    for i, a in enumerate(ACCOUNTS):
        email = a["email"].strip().lower()
        existing = users.find_one({"email": email})
        profile = _profile(a["role"], a, i)
        reg = _registration_fields(a["role"], a, i).get("registration", {})
        mobile = _mobile(i)
        gst = _gst(i)
        identity_type = "AADHAAR"
        identity_number = _identity(i)

        doc = {
            "name": a["name"],
            "email": email,
            "passwordHash": generate_password_hash(PASSWORD),
            "role": a["role"],
            "status": "ACTIVE",
            "approved": True,
            "approvalStatus": "APPROVED",
            "approvalReason": "",
            "approvedAt": _now(),
            "approvedBy": "SEED",
            "profile": profile,
            "registration": reg,
            "documents": [],
            "images": [],
            "updatedAt": _now(),
        }
        if existing:
            updates = {k: v for k, v in doc.items() if k != "_id"}
            updates["createdAt"] = existing.get("createdAt") or _now()
            users.update_one({"_id": existing["_id"]}, {"$set": updates})
            uid = str(existing["_id"])
        else:
            if not duplicate.mobile_taken(mobile):
                doc["mobile"] = mobile
            if not duplicate.gst_taken(gst):
                doc["gst"] = gst
            if not duplicate.identity_taken(identity_type, identity_number):
                doc["identityType"] = identity_type
                doc["identityNumber"] = identity_number
            uid = new_user_id()
            doc["_id"] = uid
            doc["createdAt"] = _now()
            try:
                users.insert_one(doc)
            except Exception as e:
                print("  !! failed to insert %s: %s" % (email, e))
                for k in ("mobile", "gst", "identityType", "identityNumber"):
                    doc.pop(k, None)
                users.insert_one(doc)
        seeded[email] = uid
    return seeded


# ---------------------------------------------------------------------------
# Transports
# ---------------------------------------------------------------------------

def _upsert_transport(doc):
    coll = get_collection("transports")
    key = doc.get("numberKey") or doc.get("busNumber") or doc.get("trainNumber") \
        or doc.get("flightNumber") or doc.get("vehicleNumber")
    existing = coll.find_one({"numberKey": key}) if key else None
    doc["createdAt"] = doc.get("createdAt") or _now()
    doc["updatedAt"] = _now()
    if existing:
        coll.update_one({"_id": existing["_id"]}, {"$set": doc})
        return str(existing["_id"])
    doc["_id"] = _id()
    coll.insert_one(doc)
    return doc["_id"]


def _coaches(rows):
    out = []
    for code, label, count, cap, price in rows:
        out.append({
            "code": code, "label": label, "coachCount": count,
            "capacityPerCoach": cap, "totalCapacity": count * cap, "price": price,
        })
    return out


def _train_spec(owner, train_number, train_name, fm, to, dep_from, dep_day,
                dep_time, arr_day, arr_time, stations, coaches):
    return {
        "ownerId": owner, "type": "TRAIN", "status": "APPROVED",
        "serviceName": "Southern Railway",
        "images": [img_url("rail1")],
        "trainNumber": train_number, "trainName": train_name,
        "boardingStation": fm, "destinationStation": to,
        "boardingDay": dep_day, "boardingTime": dep_time,
        "droppingDay": arr_day, "droppingTime": arr_time,
        "stations": stations,
        "coaches": coaches,
        "totalCoaches": sum(c["coachCount"] for c in coaches),
        "daysOfWeek": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
        "recurring": [],
        "bookedSeats": 0, "documents": [], "rejectionReason": None,
    }


def seed_trains(uid):
    ir = uid["railway.southern@tripmind.demo"]
    cbe, maa = "Coimbatore Junction", "Chennai Egmore"
    units = []
    def add(spec):
        spec["numberKey"] = spec["trainNumber"]
        units.append(_upsert_transport(spec))

    add(_train_spec(ir, "12674", "Cheran Express", cbe, maa, cbe, 0, "20:15",
                    1, "05:10", [
                        {"name": "Tiruppur", "day": 0, "arrivalTime": "21:05", "departureTime": "21:07"},
                        {"name": "Erode", "day": 0, "arrivalTime": "22:10", "departureTime": "22:15"},
                        {"name": "Salem", "day": 0, "arrivalTime": "23:30", "departureTime": "23:35"},
                        {"name": "Chennai Egmore", "day": 1, "arrivalTime": "05:10", "departureTime": ""},
                    ], _coaches([("SL", "Sleeper", 6, 72, 370), ("3A", "3 Tier AC", 4, 64, 780),
                                 ("2A", "2 Tier AC", 2, 46, 1100)])))
    add(_train_spec(ir, "12673", "Cheran Express", maa, cbe, maa, 0, "20:30",
                    1, "05:30", [
                        {"name": "Villupuram", "day": 0, "arrivalTime": "22:40", "departureTime": "22:45"},
                        {"name": "Salem", "day": 1, "arrivalTime": "02:10", "departureTime": "02:15"},
                        {"name": "Erode", "day": 1, "arrivalTime": "03:20", "departureTime": "03:25"},
                        {"name": "Coimbatore Junction", "day": 1, "arrivalTime": "05:30", "departureTime": ""},
                    ], _coaches([("SL", "Sleeper", 7, 72, 370), ("3A", "3 Tier AC", 4, 64, 780),
                                 ("2A", "2 Tier AC", 2, 46, 1100)])))
    add(_train_spec(ir, "22650", "Kaveri SF Express", cbe, maa, cbe, 0, "07:30",
                    0, "13:25", [
                        {"name": "Erode", "day": 0, "arrivalTime": "08:40", "departureTime": "08:45"},
                        {"name": "Salem", "day": 0, "arrivalTime": "09:50", "departureTime": "09:55"},
                        {"name": "Villupuram", "day": 0, "arrivalTime": "12:05", "departureTime": "12:10"},
                        {"name": "Chennai Egmore", "day": 0, "arrivalTime": "13:25", "departureTime": ""},
                    ], _coaches([("SL", "Sleeper", 5, 72, 335), ("3A", "3 Tier AC", 3, 64, 720),
                                 ("2A", "2 Tier AC", 2, 46, 1020)])))
    add(_train_spec(ir, "22649", "Kaveri SF Express", maa, cbe, maa, 0, "14:30",
                    0, "20:20", [
                        {"name": "Villupuram", "day": 0, "arrivalTime": "15:40", "departureTime": "15:45"},
                        {"name": "Salem", "day": 0, "arrivalTime": "18:00", "departureTime": "18:05"},
                        {"name": "Erode", "day": 0, "arrivalTime": "19:00", "departureTime": "19:05"},
                        {"name": "Coimbatore Junction", "day": 0, "arrivalTime": "20:20", "departureTime": ""},
                    ], _coaches([("SL", "Sleeper", 5, 72, 335), ("3A", "3 Tier AC", 3, 64, 720),
                                 ("2A", "2 Tier AC", 2, 46, 1020)])))
    add(_train_spec(ir, "22673", "Kovai SF Express", cbe, maa, cbe, 0, "22:10",
                    1, "06:45", [
                        {"name": "Tiruppur", "day": 0, "arrivalTime": "22:55", "departureTime": "22:57"},
                        {"name": "Erode", "day": 1, "arrivalTime": "00:05", "departureTime": "00:10"},
                        {"name": "Salem", "day": 1, "arrivalTime": "01:20", "departureTime": "01:25"},
                        {"name": "Katpadi", "day": 1, "arrivalTime": "03:55", "departureTime": "04:00"},
                        {"name": "Chennai Egmore", "day": 1, "arrivalTime": "06:45", "departureTime": ""},
                    ], _coaches([("SL", "Sleeper", 6, 72, 385), ("3A", "3 Tier AC", 4, 64, 800),
                                 ("2A", "2 Tier AC", 2, 46, 1130)])))
    add(_train_spec(ir, "22674", "Kovai SF Express", maa, cbe, maa, 0, "22:30",
                    1, "07:15", [
                        {"name": "Katpadi", "day": 1, "arrivalTime": "00:50", "departureTime": "00:55"},
                        {"name": "Salem", "day": 1, "arrivalTime": "03:20", "departureTime": "03:25"},
                        {"name": "Erode", "day": 1, "arrivalTime": "04:30", "departureTime": "04:35"},
                        {"name": "Tiruppur", "day": 1, "arrivalTime": "05:30", "departureTime": "05:32"},
                        {"name": "Coimbatore Junction", "day": 1, "arrivalTime": "07:15", "departureTime": ""},
                    ], _coaches([("SL", "Sleeper", 6, 72, 385), ("3A", "3 Tier AC", 4, 64, 800),
                                 ("2A", "2 Tier AC", 2, 46, 1130)])))
    add(_train_spec(ir, "16650", "Parasuram SF Express", cbe, maa, cbe, 0, "06:30",
                    0, "13:40", [
                        {"name": "Tiruppur", "day": 0, "arrivalTime": "07:15", "departureTime": "07:17"},
                        {"name": "Erode", "day": 0, "arrivalTime": "08:20", "departureTime": "08:25"},
                        {"name": "Salem", "day": 0, "arrivalTime": "09:35", "departureTime": "09:40"},
                        {"name": "Katpadi", "day": 0, "arrivalTime": "12:20", "departureTime": "12:25"},
                        {"name": "Chennai Egmore", "day": 0, "arrivalTime": "13:40", "departureTime": ""},
                    ], _coaches([("SL", "Sleeper", 4, 72, 315), ("3A", "3 Tier AC", 3, 64, 685),
                                 ("CC", "Chair Car", 4, 78, 590)])))
    add(_train_spec(ir, "16649", "Parasuram SF Express", maa, cbe, maa, 0, "08:00",
                    0, "15:10", [
                        {"name": "Katpadi", "day": 0, "arrivalTime": "09:20", "departureTime": "09:25"},
                        {"name": "Salem", "day": 0, "arrivalTime": "11:45", "departureTime": "11:50"},
                        {"name": "Tiruppur", "day": 0, "arrivalTime": "14:05", "departureTime": "14:07"},
                        {"name": "Coimbatore Junction", "day": 0, "arrivalTime": "15:10", "departureTime": ""},
                    ], _coaches([("SL", "Sleeper", 4, 72, 315), ("3A", "3 Tier AC", 3, 64, 685),
                                 ("CC", "Chair Car", 4, 78, 590)])))
    add(_train_spec(ir, "22678", "Pandian SF Express (CBE)", cbe, maa, cbe, 0, "23:40",
                    1, "08:00", [
                        {"name": "Erode", "day": 1, "arrivalTime": "01:05", "departureTime": "01:10"},
                        {"name": "Salem", "day": 1, "arrivalTime": "02:15", "departureTime": "02:20"},
                        {"name": "Katpadi", "day": 1, "arrivalTime": "04:50", "departureTime": "04:55"},
                        {"name": "Chennai Egmore", "day": 1, "arrivalTime": "08:00", "departureTime": ""},
                    ], _coaches([("SL", "Sleeper", 5, 72, 375), ("3A", "3 Tier AC", 4, 64, 795),
                                 ("2A", "2 Tier AC", 2, 46, 1120)])))
    add(_train_spec(ir, "22677", "Pandian SF Express (CBE)", maa, cbe, maa, 0, "23:10",
                    1, "07:30", [
                        {"name": "Katpadi", "day": 1, "arrivalTime": "01:40", "departureTime": "01:45"},
                        {"name": "Salem", "day": 1, "arrivalTime": "04:10", "departureTime": "04:15"},
                        {"name": "Coimbatore Junction", "day": 1, "arrivalTime": "07:30", "departureTime": ""},
                    ], _coaches([("SL", "Sleeper", 5, 72, 375), ("3A", "3 Tier AC", 4, 64, 795),
                                 ("2A", "2 Tier AC", 2, 46, 1120)])))
    # Additional CBE -> EMU pairs (day services)
    add(_train_spec(ir, "22639", "Yercaud SF Express", cbe, maa, cbe, 0, "16:35",
                    0, "23:05", [
                        {"name": "Tiruppur", "day": 0, "arrivalTime": "17:15", "departureTime": "17:17"},
                        {"name": "Erode", "day": 0, "arrivalTime": "18:20", "departureTime": "18:25"},
                        {"name": "Salem", "day": 0, "arrivalTime": "19:40", "departureTime": "19:45"},
                        {"name": "Villupuram", "day": 0, "arrivalTime": "21:45", "departureTime": "21:50"},
                        {"name": "Chennai Egmore", "day": 0, "arrivalTime": "23:05", "departureTime": ""},
                    ], _coaches([("SL", "Sleeper", 6, 72, 365), ("3A", "3 Tier AC", 3, 64, 775),
                                 ("2A", "2 Tier AC", 1, 46, 1090)])))
    add(_train_spec(ir, "22640", "Yercaud SF Express", maa, cbe, maa, 0, "07:35",
                    0, "14:00", [
                        {"name": "Villupuram", "day": 0, "arrivalTime": "09:00", "departureTime": "09:05"},
                        {"name": "Salem", "day": 0, "arrivalTime": "11:00", "departureTime": "11:05"},
                        {"name": "Erode", "day": 0, "arrivalTime": "12:10", "departureTime": "12:15"},
                        {"name": "Tiruppur", "day": 0, "arrivalTime": "13:10", "departureTime": "13:12"},
                        {"name": "Coimbatore Junction", "day": 0, "arrivalTime": "14:00", "departureTime": ""},
                    ], _coaches([("SL", "Sleeper", 6, 72, 365), ("3A", "3 Tier AC", 3, 64, 775),
                                 ("2A", "2 Tier AC", 1, 46, 1090)])))
    add(_train_spec(ir, "16693", "Kongu SF Express", cbe, maa, cbe, 0, "06:45",
                    0, "13:10", [
                        {"name": "Erode", "day": 0, "arrivalTime": "08:00", "departureTime": "08:05"},
                        {"name": "Salem", "day": 0, "arrivalTime": "09:15", "departureTime": "09:20"},
                        {"name": "Katpadi", "day": 0, "arrivalTime": "11:50", "departureTime": "11:55"},
                        {"name": "Chennai Egmore", "day": 0, "arrivalTime": "13:10", "departureTime": ""},
                    ], _coaches([("SL", "Sleeper", 5, 72, 345), ("3A", "3 Tier AC", 3, 64, 745),
                                 ("CC", "Chair Car", 2, 78, 565)])))
    add(_train_spec(ir, "16694", "Kongu SF Express", maa, cbe, maa, 0, "08:05",
                    0, "14:30", [
                        {"name": "Katpadi", "day": 0, "arrivalTime": "09:25", "departureTime": "09:30"},
                        {"name": "Salem", "day": 0, "arrivalTime": "11:55", "departureTime": "12:00"},
                        {"name": "Erode", "day": 0, "arrivalTime": "13:05", "departureTime": "13:10"},
                        {"name": "Coimbatore Junction", "day": 0, "arrivalTime": "14:30", "departureTime": ""},
                    ], _coaches([("SL", "Sleeper", 5, 72, 345), ("3A", "3 Tier AC", 3, 64, 745),
                                 ("CC", "Chair Car", 2, 78, 565)])))
    add(_train_spec(ir, "16341", "Kovai Express", cbe, maa, cbe, 0, "09:15",
                    0, "15:35", [
                        {"name": "Tiruppur", "day": 0, "arrivalTime": "09:55", "departureTime": "09:57"},
                        {"name": "Erode", "day": 0, "arrivalTime": "11:00", "departureTime": "11:05"},
                        {"name": "Salem", "day": 0, "arrivalTime": "12:15", "departureTime": "12:20"},
                        {"name": "Katpadi", "day": 0, "arrivalTime": "14:05", "departureTime": "14:10"},
                        {"name": "Chennai Egmore", "day": 0, "arrivalTime": "15:35", "departureTime": ""},
                    ], _coaches([("SL", "Sleeper", 6, 72, 355), ("3A", "3 Tier AC", 4, 64, 765),
                                 ("2A", "2 Tier AC", 2, 46, 1085)])))
    add(_train_spec(ir, "16342", "Kovai Express", maa, cbe, maa, 0, "10:20",
                    0, "16:40", [
                        {"name": "Katpadi", "day": 0, "arrivalTime": "11:40", "departureTime": "11:45"},
                        {"name": "Salem", "day": 0, "arrivalTime": "13:30", "departureTime": "13:35"},
                        {"name": "Erode", "day": 0, "arrivalTime": "14:45", "departureTime": "14:50"},
                        {"name": "Tiruppur", "day": 0, "arrivalTime": "15:40", "departureTime": "15:42"},
                        {"name": "Coimbatore Junction", "day": 0, "arrivalTime": "16:40", "departureTime": ""},
                    ], _coaches([("SL", "Sleeper", 6, 72, 355), ("3A", "3 Tier AC", 4, 64, 765),
                                 ("2A", "2 Tier AC", 2, 46, 1085)])))
    add(_train_spec(ir, "12669", "Udayan Express", cbe, maa, cbe, 0, "11:00",
                    0, "17:20", [
                        {"name": "Erode", "day": 0, "arrivalTime": "12:15", "departureTime": "12:20"},
                        {"name": "Salem", "day": 0, "arrivalTime": "13:30", "departureTime": "13:35"},
                        {"name": "Villupuram", "day": 0, "arrivalTime": "15:40", "departureTime": "15:45"},
                        {"name": "Chennai Egmore", "day": 0, "arrivalTime": "17:20", "departureTime": ""},
                    ], _coaches([("SL", "Sleeper", 5, 72, 340), ("3A", "3 Tier AC", 3, 64, 740),
                                 ("CC", "Chair Car", 3, 78, 560)])))
    add(_train_spec(ir, "12670", "Udayan Express", maa, cbe, maa, 0, "12:10",
                    0, "18:30", [
                        {"name": "Villupuram", "day": 0, "arrivalTime": "13:40", "departureTime": "13:45"},
                        {"name": "Salem", "day": 0, "arrivalTime": "15:50", "departureTime": "15:55"},
                        {"name": "Erode", "day": 0, "arrivalTime": "17:05", "departureTime": "17:10"},
                        {"name": "Coimbatore Junction", "day": 0, "arrivalTime": "18:30", "departureTime": ""},
                    ], _coaches([("SL", "Sleeper", 5, 72, 340), ("3A", "3 Tier AC", 3, 64, 740),
                                 ("CC", "Chair Car", 3, 78, 560)])))
    add(_train_spec(ir, "16157", "Chendur Express", cbe, maa, cbe, 0, "16:30",
                    0, "23:15", [
                        {"name": "Tiruppur", "day": 0, "arrivalTime": "17:10", "departureTime": "17:12"},
                        {"name": "Erode", "day": 0, "arrivalTime": "18:15", "departureTime": "18:20"},
                        {"name": "Salem", "day": 0, "arrivalTime": "19:35", "departureTime": "19:40"},
                        {"name": "Villupuram", "day": 0, "arrivalTime": "21:40", "departureTime": "21:45"},
                        {"name": "Chennai Egmore", "day": 0, "arrivalTime": "23:15", "departureTime": ""},
                    ], _coaches([("SL", "Sleeper", 6, 72, 355), ("3A", "3 Tier AC", 4, 64, 765),
                                 ("2A", "2 Tier AC", 2, 46, 1085)])))
    add(_train_spec(ir, "16158", "Chendur Express", maa, cbe, maa, 0, "05:15",
                    0, "11:45", [
                        {"name": "Villupuram", "day": 0, "arrivalTime": "06:45", "departureTime": "06:50"},
                        {"name": "Salem", "day": 0, "arrivalTime": "08:50", "departureTime": "08:55"},
                        {"name": "Erode", "day": 0, "arrivalTime": "10:00", "departureTime": "10:05"},
                        {"name": "Tiruppur", "day": 0, "arrivalTime": "10:50", "departureTime": "10:52"},
                        {"name": "Coimbatore Junction", "day": 0, "arrivalTime": "11:45", "departureTime": ""},
                    ], _coaches([("SL", "Sleeper", 6, 72, 355), ("3A", "3 Tier AC", 4, 64, 765),
                                 ("2A", "2 Tier AC", 2, 46, 1085)])))
    return units


def seed_buses(uid):
    srl = uid["transport.srl@tripmind.demo"]
    kms = uid["transport.kms@tripmind.demo"]
    gtg = uid["transport.gtg@tripmind.demo"]
    units = []
    def b(owner, svc, num, fm, fday, ftime, to, tday, ttime, stops, stypes,
          total, slp, seater, fare, img=None):
        doc = {
            "ownerId": owner, "type": "BUS", "status": "APPROVED", "serviceName": svc,
            "images": ([img_url("bus1"), img_url("street_india")] if slp
                       else [img_url("bus2"), img_url("goa_beach")]),
            "busNumber": num, "boardingPoint": fm, "boardingDay": fday,
            "boardingTime": ftime, "droppingPoint": to, "droppingDay": tday,
            "droppingTime": ttime, "stops": stops,
            "seatTypes": stypes, "totalSeats": total, "sleeperSeats": slp,
            "seaterSeats": seater, "singleSeat": True, "doubleSeat": True,
            "layout": None, "fare": fare, "bookedSeats": 0,
            "documents": [], "rejectionReason": None,
        }
        doc["numberKey"] = num
        units.append(_upsert_transport(doc))

    # 15 x Coimbatore -> Chennai
    b(srl, "SRL Travels", "TN-38 AB 1001", "Coimbatore", 0, "20:45", "Chennai", 1, "05:30",
      [{"name": "Erode", "day": 0, "time": "22:40"}, {"name": "Salem", "day": 1, "time": "00:20"},
       {"name": "Vellore", "day": 1, "time": "03:00"}], ["SLEEPER", "SEATER"], 40, 24, 16,
      {"sleeper": 899, "seater": 699})
    b(srl, "SRL Travels", "TN-38 AB 1002", "Coimbatore", 0, "21:30", "Chennai", 1, "06:15",
      [{"name": "Tiruppur", "day": 0, "time": "22:15"}, {"name": "Salem", "day": 1, "time": "00:10"},
       {"name": "Vellore", "day": 1, "time": "03:20"}], ["SLEEPER"], 33, 33, 0, {"sleeper": 929})
    b(srl, "SRL Travels", "TN-38 AB 1003", "Coimbatore", 0, "22:15", "Chennai", 1, "07:00",
      [{"name": "Erode", "day": 0, "time": "23:50"}, {"name": "Katpadi", "day": 1, "time": "03:40"}],
      ["SLEEPER", "SEATER"], 40, 20, 20, {"sleeper": 899, "seater": 699})
    b(srl, "SRL Travels", "TN-38 AB 1004", "Coimbatore", 0, "07:00", "Chennai", 0, "15:00",
      [{"name": "Tiruppur", "day": 0, "time": "07:50"}, {"name": "Salem", "day": 0, "time": "10:00"}],
      ["SEATER"], 48, 0, 48, {"seater": 499})
    b(srl, "SRL Travels", "TN-38 AB 1005", "Coimbatore", 0, "09:30", "Chennai", 0, "17:30",
      [{"name": "Erode", "day": 0, "time": "11:00"}, {"name": "Vellore", "day": 0, "time": "15:00"}],
      ["SEATER"], 48, 0, 48, {"seater": 529})
    b(kms, "KMS Transport", "TN-39 DX 2001", "Coimbatore", 0, "20:00", "Chennai", 1, "04:45",
      [{"name": "Tiruppur", "day": 0, "time": "20:50"}, {"name": "Erode", "day": 0, "time": "22:00"},
       {"name": "Salem", "day": 0, "time": "23:30"}, {"name": "Katpadi", "day": 1, "time": "02:30"}],
      ["SLEEPER", "SEATER"], 44, 26, 18, {"sleeper": 849, "seater": 649})
    b(kms, "KMS Transport", "TN-39 DX 2002", "Coimbatore", 0, "21:00", "Chennai", 1, "05:45",
      [{"name": "Erode", "day": 0, "time": "22:30"}, {"name": "Salem", "day": 1, "time": "00:10"}],
      ["SLEEPER"], 30, 30, 0, {"sleeper": 879})
    b(kms, "KMS Transport", "TN-39 DX 2003", "Coimbatore", 0, "23:00", "Chennai", 1, "07:30",
      [{"name": "Erode", "day": 1, "time": "00:30"}, {"name": "Katpadi", "day": 1, "time": "04:00"}],
      ["SLEEPER", "SEATER"], 40, 22, 18, {"sleeper": 879, "seater": 679})
    b(kms, "KMS Transport", "TN-39 DX 2004", "Coimbatore", 0, "08:00", "Chennai", 0, "16:00",
      [{"name": "Tiruppur", "day": 0, "time": "08:50"}, {"name": "Salem", "day": 0, "time": "11:00"}],
      ["SEATER"], 50, 0, 50, {"seater": 479})
    b(kms, "KMS Transport", "TN-39 DX 2005", "Coimbatore", 0, "14:00", "Chennai", 0, "22:00",
      [{"name": "Erode", "day": 0, "time": "15:10"}, {"name": "Vellore", "day": 0, "time": "19:20"}],
      ["SEATER"], 48, 0, 48, {"seater": 449})
    b(gtg, "GTG Tours & Travels", "TN-43 GT 3001", "Coimbatore", 0, "20:30", "Chennai", 1, "05:15",
      [{"name": "Erode", "day": 0, "time": "22:10"}, {"name": "Salem", "day": 1, "time": "00:00"},
       {"name": "Vellore", "day": 1, "time": "02:45"}], ["SLEEPER", "SEATER"], 40, 24, 16,
      {"sleeper": 869, "seater": 669})
    b(gtg, "GTG Tours & Travels", "TN-43 GT 3002", "Coimbatore", 0, "22:45", "Chennai", 1, "07:15",
      [{"name": "Tiruppur", "day": 0, "time": "23:30"}, {"name": "Salem", "day": 1, "time": "01:20"},
       {"name": "Katpadi", "day": 1, "time": "04:10"}], ["SLEEPER"], 32, 32, 0, {"sleeper": 909})
    b(gtg, "GTG Tours & Travels", "TN-43 GT 3003", "Coimbatore", 0, "10:30", "Chennai", 0, "18:30",
      [{"name": "Erode", "day": 0, "time": "12:00"}, {"name": "Salem", "day": 0, "time": "13:40"}],
      ["SEATER"], 45, 0, 45, {"seater": 499})
    b(kms, "KMS Transport", "TN-39 DX 2030", "Coimbatore", 0, "19:00", "Chennai", 1, "03:45",
      [{"name": "Erode", "day": 0, "time": "20:20"}, {"name": "Salem", "day": 0, "time": "22:00"},
       {"name": "Krishnagiri", "day": 1, "time": "00:30"}], ["SLEEPER", "SEATER"], 40, 20, 20,
      {"sleeper": 829, "seater": 629})
    b(srl, "SRL Travels", "TN-38 AB 1006", "Coimbatore", 0, "18:30", "Chennai", 1, "03:15",
      [{"name": "Tiruppur", "day": 0, "time": "19:20"}, {"name": "Salem", "day": 0, "time": "21:30"}],
      ["SLEEPER", "SEATER"], 40, 22, 18, {"sleeper": 829, "seater": 629})

    # 15 x Chennai -> Coimbatore
    b(srl, "SRL Travels", "TN-38 AB 1101", "Chennai", 0, "20:45", "Coimbatore", 1, "05:30",
      [{"name": "Vellore", "day": 0, "time": "22:30"}, {"name": "Salem", "day": 1, "time": "01:20"},
       {"name": "Erode", "day": 1, "time": "02:40"}], ["SLEEPER", "SEATER"], 40, 24, 16,
      {"sleeper": 899, "seater": 699})
    b(srl, "SRL Travels", "TN-38 AB 1102", "Chennai", 0, "21:30", "Coimbatore", 1, "06:15",
      [{"name": "Vellore", "day": 0, "time": "23:10"}, {"name": "Salem", "day": 1, "time": "01:50"},
       {"name": "Tiruppur", "day": 1, "time": "04:40"}], ["SLEEPER"], 33, 33, 0, {"sleeper": 929})
    b(srl, "SRL Travels", "TN-38 AB 1103", "Chennai", 0, "22:15", "Coimbatore", 1, "07:00",
      [{"name": "Katpadi", "day": 0, "time": "23:40"}, {"name": "Salem", "day": 1, "time": "02:20"}],
      ["SLEEPER", "SEATER"], 40, 20, 20, {"sleeper": 899, "seater": 699})
    b(srl, "SRL Travels", "TN-38 AB 1104", "Chennai", 0, "06:00", "Coimbatore", 0, "14:00",
      [{"name": "Vellore", "day": 0, "time": "07:50"}, {"name": "Salem", "day": 0, "time": "10:30"}],
      ["SEATER"], 48, 0, 48, {"seater": 499})
    b(srl, "SRL Travels", "TN-38 AB 1105", "Chennai", 0, "16:00", "Coimbatore", 1, "00:00",
      [{"name": "Vellore", "day": 0, "time": "17:30"}, {"name": "Erode", "day": 0, "time": "21:30"}],
      ["SEATER"], 48, 0, 48, {"seater": 479})
    b(kms, "KMS Transport", "TN-39 DX 2101", "Chennai", 0, "20:00", "Coimbatore", 1, "04:45",
      [{"name": "Vellore", "day": 0, "time": "21:30"}, {"name": "Salem", "day": 1, "time": "00:10"},
       {"name": "Erode", "day": 1, "time": "01:30"}], ["SLEEPER", "SEATER"], 44, 26, 18,
      {"sleeper": 849, "seater": 649})
    b(kms, "KMS Transport", "TN-39 DX 2102", "Chennai", 0, "23:00", "Coimbatore", 1, "07:30",
      [{"name": "Katpadi", "day": 1, "time": "00:40"}, {"name": "Salem", "day": 1, "time": "03:10"},
       {"name": "Tiruppur", "day": 1, "time": "05:40"}], ["SLEEPER", "SEATER"], 40, 22, 18,
      {"sleeper": 879, "seater": 679})
    b(kms, "KMS Transport", "TN-39 DX 2103", "Chennai", 0, "08:00", "Coimbatore", 0, "16:00",
      [{"name": "Vellore", "day": 0, "time": "09:30"}, {"name": "Salem", "day": 0, "time": "12:00"}],
      ["SEATER"], 50, 0, 50, {"seater": 479})
    b(kms, "KMS Transport", "TN-39 DX 2104", "Chennai", 0, "12:00", "Coimbatore", 0, "20:00",
      [{"name": "Vellore", "day": 0, "time": "13:30"}, {"name": "Erode", "day": 0, "time": "17:30"}],
      ["SEATER"], 48, 0, 48, {"seater": 449})
    b(gtg, "GTG Tours & Travels", "TN-43 GT 3101", "Chennai", 0, "20:30", "Coimbatore", 1, "05:15",
      [{"name": "Vellore", "day": 0, "time": "22:00"}, {"name": "Salem", "day": 1, "time": "00:40"},
       {"name": "Tiruppur", "day": 1, "time": "03:40"}], ["SLEEPER", "SEATER"], 40, 24, 16,
      {"sleeper": 869, "seater": 669})
    b(gtg, "GTG Tours & Travels", "TN-43 GT 3102", "Chennai", 0, "22:45", "Coimbatore", 1, "07:15",
      [{"name": "Katpadi", "day": 1, "time": "00:20"}, {"name": "Salem", "day": 1, "time": "03:00"}],
      ["SLEEPER"], 32, 32, 0, {"sleeper": 909})
    b(gtg, "GTG Tours & Travels", "TN-43 GT 3103", "Chennai", 0, "10:30", "Coimbatore", 0, "18:30",
      [{"name": "Vellore", "day": 0, "time": "12:10"}, {"name": "Salem", "day": 0, "time": "14:40"}],
      ["SEATER"], 45, 0, 45, {"seater": 499})
    b(kms, "KMS Transport", "TN-39 DX 2130", "Chennai", 0, "19:00", "Coimbatore", 1, "03:45",
      [{"name": "Vellore", "day": 0, "time": "20:30"}, {"name": "Salem", "day": 1, "time": "23:10"}],
      ["SLEEPER", "SEATER"], 40, 20, 20, {"sleeper": 829, "seater": 629})
    b(srl, "SRL Travels", "TN-38 AB 1106", "Chennai", 0, "18:30", "Coimbatore", 1, "03:15",
      [{"name": "Vellore", "day": 0, "time": "20:00"}, {"name": "Salem", "day": 1, "time": "22:40"},
       {"name": "Erode", "day": 1, "time": "00:00"}], ["SLEEPER", "SEATER"], 40, 22, 18,
      {"sleeper": 829, "seater": 629})
    b(gtg, "GTG Tours & Travels", "TN-43 GT 3104", "Chennai", 0, "11:30", "Coimbatore", 0, "19:30",
      [{"name": "Vellore", "day": 0, "time": "13:10"}, {"name": "Salem", "day": 0, "time": "15:40"},
       {"name": "Erode", "day": 0, "time": "16:50"}, {"name": "Tiruppur", "day": 0, "time": "17:45"}],
      ["SEATER"], 48, 0, 48, {"seater": 479})
    return units


def seed_flights(uid):
    bha = uid["transport.bluehorizon@tripmind.demo"]
    kka = uid["transport.kongukaveri@tripmind.demo"]
    units = []
    def f(owner, svc, num, dep, arr, dday, dtime, aday, atime, ec, biz):
        doc = {
            "ownerId": owner, "type": "FLIGHT", "status": "APPROVED", "serviceName": svc,
            "images": [img_url("flight1"), img_url("airport1")],
            "flightNumber": num, "airline": svc,
            "departureAirport": dep, "arrivalAirport": arr,
            "boardingDay": dday, "boardingTime": dtime,
            "arrivalDay": aday, "arrivalTime": atime,
            "layoverAirport": "", "totalSeats": ec + biz,
            "classes": [{"name": "Economy", "seats": ec, "price": 1480},
                        {"name": "Business", "seats": biz, "price": 4800}],
            "baggage": {"cabin": "7 kg", "checkin": "15 kg"},
            "bookedSeats": 0, "documents": [], "rejectionReason": None,
        }
        doc["numberKey"] = num
        units.append(_upsert_transport(doc))

    f(bha, "Blue Horizon Aviation", "6E-2041", "Coimbatore (CJB)", "Chennai (MAA)", 0, "06:00", 0, "07:10", 90, 12)
    f(bha, "Blue Horizon Aviation", "6E-2043", "Coimbatore (CJB)", "Chennai (MAA)", 0, "08:30", 0, "09:40", 90, 12)
    f(bha, "Blue Horizon Aviation", "6E-2045", "Coimbatore (CJB)", "Chennai (MAA)", 0, "13:15", 0, "14:25", 90, 12)
    f(bha, "Blue Horizon Aviation", "6E-2047", "Coimbatore (CJB)", "Chennai (MAA)", 0, "17:45", 0, "18:55", 90, 12)
    f(bha, "Blue Horizon Aviation", "6E-2049", "Coimbatore (CJB)", "Chennai (MAA)", 0, "20:15", 0, "21:25", 90, 12)
    f(kka, "Kongu Kaveri Air", "KK-1101", "Coimbatore (CJB)", "Chennai (MAA)", 0, "09:00", 0, "10:10", 88, 10)
    f(bha, "Blue Horizon Aviation", "6E-2042", "Chennai (MAA)", "Coimbatore (CJB)", 0, "06:15", 0, "07:25", 90, 12)
    f(bha, "Blue Horizon Aviation", "6E-2044", "Chennai (MAA)", "Coimbatore (CJB)", 0, "11:00", 0, "12:10", 90, 12)
    f(kka, "Kongu Kaveri Air", "KK-1102", "Chennai (MAA)", "Coimbatore (CJB)", 0, "18:30", 0, "19:40", 88, 10)
    f(kka, "Kongu Kaveri Air", "KK-1104", "Chennai (MAA)", "Coimbatore (CJB)", 0, "21:00", 0, "22:10", 96, 10)
    return units


def seed_cabs(uid):
    srl = uid["transport.srl@tripmind.demo"]
    kms = uid["transport.kms@tripmind.demo"]
    gtg = uid["transport.gtg@tripmind.demo"]
    vcb = uid["transport.vembanad@tripmind.demo"]
    units = []
    i = [0]
    def c(owner, svc, num, vtype, seats, ac, city, area, driver, base, km, min_f):
        i[0] += 1
        doc = {
            "ownerId": owner, "type": "CAB", "status": "APPROVED", "serviceName": svc,
            "images": [img_url("car1")],
            "vehicleNumber": num, "vehicleType": vtype, "seatingCapacity": seats,
            "ac": ac, "driver": {"name": driver, "contact": _mobile(40 + i[0])},
            "serviceArea": area, "baseLocation": base,
            "availableTimings": {"from": "06:00", "to": "22:00"},
            "fare": {"baseFare": base, "pricePerKm": km, "minimum": min_f},
            "bookedSeats": 0, "documents": [], "rejectionReason": None,
        }
        doc["numberKey"] = num
        units.append(_upsert_transport(doc))

    # Coimbatore-based
    c(srl, "SRL Travels", "TN-38 CA 5001", "Sedan", 4, True, "Coimbatore",
      "Coimbatore", "D. Prakash", "Gandhipuram, Coimbatore", 50, 320)
    c(srl, "SRL Travels", "TN-38 CA 5002", "SUV", 6, True, "Coimbatore",
      "Coimbatore", "E. Rajan", "RS Puram, Coimbatore", 70, 420)
    c(srl, "SRL Travels", "TN-38 CA 5003", "Hatchback", 4, True, "Coimbatore",
      "Coimbatore", "F. Suresh", "Saibaba Colony, Coimbatore", 40, 250)
    c(srl, "SRL Travels", "TN-38 CA 5004", "Sedan", 4, False, "Coimbatore",
      "Coimbatore", "G. Manoj", "Peelamedu, Coimbatore", 35, 230)
    c(srl, "SRL Travels", "TN-38 CA 5005", "SUV", 7, True, "Coimbatore",
      "Coimbatore", "H. Ravi", "Avvai Street, Coimbatore", 80, 480)
    c(kms, "KMS Transport", "TN-39 DX 6001", "Sedan", 4, True, "Coimbatore",
      "Coimbatore", "I. Selvam", "Ramanathapuram, Coimbatore", 50, 300)
    c(kms, "KMS Transport", "TN-39 DX 6002", "Hatchback", 4, True, "Coimbatore",
      "Coimbatore", "J. Kumar", "Koundampalayam, Coimbatore", 40, 240)
    c(kms, "KMS Transport", "TN-39 DX 6003", "AUTO", 3, False, "Coimbatore",
      "Coimbatore", "K. Murugesan", "Ukkadam, Coimbatore", 15, 40)
    c(gtg, "GTG Tours & Travels", "TN-43 GT 7001", "SUV", 6, True, "Coimbatore",
      "Coimbatore", "L. Karthik", "Rathinapuri, Coimbatore", 70, 400)
    c(gtg, "GTG Tours & Travels", "TN-43 GT 7002", "Sedan", 4, True, "Coimbatore",
      "Coimbatore", "M. Anbu", "Poomarket, Coimbatore", 50, 320)
    c(gtg, "GTG Tours & Travels", "TN-43 GT 7003", "Hatchback", 4, False, "Coimbatore",
      "Coimbatore", "N. Vignesh", "Sundarapuram, Coimbatore", 35, 220)
    c(gtg, "GTG Tours & Travels", "TN-43 GT 7004", "AUTO", 3, False, "Coimbatore",
      "Coimbatore", "O. Senthil", "Lakshmi Mills, Coimbatore", 15, 40)
    c(vcb, "Vembanad Cabs", "TN-43 VA 8001", "Sedan", 4, True, "Coimbatore",
      "Coimbatore", "P. Vimal", "Race Course, Coimbatore", 55, 340)
    c(vcb, "Vembanad Cabs", "TN-43 VA 8002", "SUV", 6, True, "Coimbatore",
      "Coimbatore", "Q. Ashwin", "Gandhipuram, Coimbatore", 75, 440)
    c(vcb, "Vembanad Cabs", "TN-43 VA 8003", "Hatchback", 4, True, "Coimbatore",
      "Coimbatore", "R. Dinesh", "Podanur, Coimbatore", 40, 250)

    # Chennai-based
    c(srl, "SRL Travels", "TN-38 CA 5101", "Sedan", 4, True, "Chennai",
      "Chennai", "T. Saravanan", "T. Nagar, Chennai", 50, 320)
    c(srl, "SRL Travels", "TN-38 CA 5102", "SUV", 6, True, "Chennai",
      "Chennai", "U. Logesh", "Adyar, Chennai", 70, 420)
    c(srl, "SRL Travels", "TN-38 CA 5103", "Hatchback", 4, False, "Chennai",
      "Chennai", "V. Pradeep", "Anna Nagar, Chennai", 35, 230)
    c(kms, "KMS Transport", "TN-39 DX 6101", "Sedan", 4, True, "Chennai",
      "Chennai", "W. Balaji", "Egmore, Chennai", 50, 300)
    c(kms, "KMS Transport", "TN-39 DX 6102", "Hatchback", 4, True, "Chennai",
      "Chennai", "X. Deepak", "Mylapore, Chennai", 40, 240)
    c(kms, "KMS Transport", "TN-39 DX 6103", "AUTO", 3, False, "Chennai",
      "Chennai", "Y. Moorthy", "Guindy, Chennai", 15, 40)
    c(kms, "KMS Transport", "TN-39 DX 6104", "SUV", 6, True, "Chennai",
      "Chennai", "Z. Praveen", "Velachery, Chennai", 70, 400)
    c(gtg, "GTG Tours & Travels", "TN-43 GT 7101", "Sedan", 4, True, "Chennai",
      "Chennai", "A. Vinoth", "Nungambakkam, Chennai", 50, 320)
    c(gtg, "GTG Tours & Travels", "TN-43 GT 7102", "Hatchback", 4, True, "Chennai",
      "Chennai", "B. Ganesh", "Tambaram, Chennai", 40, 240)
    c(vcb, "Vembanad Cabs", "TN-43 VA 8101", "Sedan", 4, True, "Chennai",
      "Chennai", "C. Rahul", "Chetpet, Chennai", 55, 340)
    c(vcb, "Vembanad Cabs", "TN-43 VA 8102", "SUV", 6, True, "Chennai",
      "Chennai", "D. Jagan", "Kotturpuram, Chennai", 75, 440)
    c(vcb, "Vembanad Cabs", "TN-43 VA 8103", "Hatchback", 4, False, "Chennai",
      "Chennai", "E. Hari", "Chromepet, Chennai", 35, 220)
    c(srl, "SRL Travels", "TN-38 CA 5104", "Sedan", 4, True, "Chennai",
      "Chennai", "F. Aravind", "OMR, Chennai", 60, 380)
    c(srl, "SRL Travels", "TN-38 CA 5105", "SUV", 7, True, "Chennai",
      "Chennai", "G. Murugan", "Porur, Chennai", 80, 460)
    c(vcb, "Vembanad Cabs", "TN-43 VA 8104", "Hatchback", 4, True, "Chennai",
      "Chennai", "H. Sathish", "Besant Nagar, Chennai", 40, 250)
    return units


# ---------------------------------------------------------------------------
# Lounges
# ---------------------------------------------------------------------------

def _upsert_lounge(doc):
    coll = get_collection("lounges")
    existing = coll.find_one({"ownerId": doc["ownerId"], "name": doc["name"]})
    doc["createdAt"] = doc.get("createdAt") or _now()
    doc["updatedAt"] = _now()
    if existing:
        coll.update_one({"_id": existing["_id"]}, {"$set": doc})
        return str(existing["_id"])
    doc["_id"] = new_user_id()
    coll.insert_one(doc)
    return doc["_id"]


def seed_lounges(uid):
    ir = uid["railway.southern@tripmind.demo"]
    def l(name, station, city, terminal, desc, price, cap, hours, amenities):
        return _upsert_lounge({
            "ownerId": ir, "name": name, "railwayStation": station, "city": city,
            "terminal": terminal, "description": desc,
            "images": [img_url("airport1"), img_url("resort_pool")],
            "amenities": amenities, "pricePerPerson": float(price),
            "maxCapacity": cap, "hours": hours, "status": "APPROVED", "bookings": 0,
        })
    out = []
    out.append(l("Cheran Executive Lounge", "Chennai Egmore", "Chennai",
                 "Main Terminus", "Air-conditioned waiting lounge with recliners, snack bar and showers at Egmore.",
                 349, 120, "06:00 - 23:00",
                 ["AC Lounge", "Recliners", "Snack Bar", "Showers", "Wi-Fi", "Charging Points"]))
    out.append(l("Chennai Central Starlight Lounge", "Chennai Central", "Chennai",
                 "Platform 1", "Premier lounge near Platform 1 with buffet and sleep pods for long layovers.",
                 449, 90, "00:00 - 23:59",
                 ["AC Lounge", "Sleep Pods", "Buffet", "Showers", "Wi-Fi", "TV"]))
    out.append(l("Kovai Vantage Lounge", "Coimbatore Junction", "Coimbatore",
                 "Platform 2/3", "Modern lounge at Coimbatore Junction with workstations and refreshments.",
                 299, 100, "06:00 - 22:00",
                 ["AC Lounge", "Workstations", "Snack Bar", "Wi-Fi", "Charging Points"]))
    out.append(l("Tiruppur Express Lounge", "Tiruppur", "Tiruppur",
                 "Main Building", "Compact lounge for express train passengers passing through Tiruppur.",
                 199, 60, "07:00 - 21:00",
                 ["AC Lounge", "Seating", "Water & Snacks", "Wi-Fi"]))
    return out


# ---------------------------------------------------------------------------
# Hotels
# ---------------------------------------------------------------------------

def _room(rid, name, total, price, bed, beds, occ, ac, numbers, extra=None):
    r = {
        "id": rid, "name": name, "category": (extra.get("category", "Standard") if extra else "Standard"),
        "totalRooms": total, "bookedRooms": 0, "blockedRooms": 0,
        "pricePerNight": round(price, 2), "ac": ac, "bedType": bed,
        "numberOfBeds": beds, "maxOccupancy": occ,
        "amenities": ["Wi-Fi", "AC", "TV", "Breakfast", "Room Service", "Parking", "24/7 Front Desk"],
        "images": [img_url("room1") if total % 3 == 0 else img_url("room2")],
        "roomNumbers": numbers,
    }
    if extra:
        r.update(extra)
    return r


def _room_numbers(prefix, n):
    return ["%s%03d" % (prefix, i) for i in range(1, n + 1)]


def _upsert_hotel(doc):
    coll = get_collection("hotels")
    existing = coll.find_one({"ownerId": doc["ownerId"], "name": doc["name"]})
    doc["createdAt"] = doc.get("createdAt") or _now()
    doc["updatedAt"] = _now()
    if existing:
        coll.update_one({"_id": existing["_id"]}, {"$set": doc})
        return str(existing["_id"])
    doc["_id"] = new_user_id()
    coll.insert_one(doc)
    return doc["_id"]


def seed_hotels(uid):
    def h(owner, name, city, category, stars, address, lat, lng, total, room_types, contact, images):
        return _upsert_hotel({
            "ownerId": owner, "name": name, "description": "%s — %s property serving %s travellers."
            % (name, category, city),
            "address": address, "city": city, "state": _state_for(city), "country": "India",
            "lat": lat, "lng": lng,
            "contactNumber": contact, "email": None,
            "checkInTime": "12:00", "checkOutTime": "11:00",
            "amenities": ["Wi-Fi", "Parking", "Restaurant", "Room Service", "AC", "TV", "Breakfast", "24/7 Front Desk"],
            "category": category, "starRating": stars,
            "images": images, "documents": [],
            "totalRooms": total, "roomTypes": room_types,
            "status": "APPROVED",
        })

    hotels = []
    gcr = uid["hotel.grandchennai@tripmind.demo"]
    mgw = uid["hotel.marinagateway@tripmind.demo"]
    hre = uid["hotel.residency@tripmind.demo"]
    kpc = uid["hotel.kovaipalm@tripmind.demo"]
    olv = uid["hotel.ootylakeview@tripmind.demo"]

    hotels.append(h(gcr, "Grand Chennai Residency", "Chennai", "Luxury", 4,
                    "No. 12, Cathedral Road, Chennai 600086", 13.0358, 80.2385, 21, [
                        _room("gcr-rt-1", "Deluxe King", 10, 4200, "King Bed", 1, 2, True,
                              _room_numbers("GCR", 10), {"category": "Luxury"}),
                        _room("gcr-rt-2", "Executive Suite", 4, 7200, "King Bed", 2, 3, True,
                              _room_numbers("GCR", 4), {"category": "Suite"}),
                        _room("gcr-rt-3", "Standard Double", 7, 2600, "Double Bed", 1, 2, True,
                              _room_numbers("GCR", 7)),
                    ], "98420 10021", [img_url("room2"), img_url("resort_pool")]))
    hotels.append(h(mgw, "Marina Gateway", "Chennai", "Mid-Range", 3,
                    "No. 27, Beach Road, Triplicane, Chennai 600005", 13.0629, 80.2772, 15, [
                        _room("mgw-rt-1", "City View", 8, 2100, "Double Bed", 1, 2, True,
                              _room_numbers("MGW", 8)),
                        _room("mgw-rt-2", "Sea View", 4, 2900, "King Bed", 1, 2, True,
                              _room_numbers("MGW", 4), {"category": "Deluxe"}),
                        _room("mgw-rt-3", "Family", 3, 3100, "King Bed", 2, 4, True,
                              _room_numbers("MGW", 3), {"category": "Suite"}),
                    ], "98420 10022", [img_url("room4"), img_url("beach1")]))
    hotels.append(h(hre, "Hotel Residency", "Coimbatore", "Budget", 2,
                    "Avinashi Road, Coimbatore 641004", 11.0266, 76.9951, 10, [
                        _room("hre-rt-1", "Standard", 6, 1200, "Double Bed", 1, 2, True,
                              _room_numbers("HRE", 6)),
                        _room("hre-rt-2", "Dormitory", 4, 700, "Multiple Beds", 6, 1, True,
                              _room_numbers("HRE", 4), {"category": "Budget"}),
                    ], "98420 10023", [img_url("room3"), img_url("breakfast2")]))
    hotels.append(h(kpc, "Kovai Palm Court", "Coimbatore", "Mid-Range", 3,
                    "No. 44, NSR Road, Saibaba Colony, Coimbatore 641011", 11.0195, 76.9530, 18, [
                        _room("kpc-rt-1", "Business Room", 10, 2300, "King Bed", 1, 2, True,
                              _room_numbers("KPC", 10)),
                        _room("kpc-rt-2", "Executive Suite", 4, 3600, "King Bed", 2, 3, True,
                              _room_numbers("KPC", 4), {"category": "Suite"}),
                        _room("kpc-rt-3", "Twin Garden", 4, 1800, "Twin Bed", 2, 2, True,
                              _room_numbers("KPC", 4)),
                    ], "98420 10024", [img_url("room1"), img_url("resort_pool")]))
    hotels.append(h(olv, "Ooty Lake View Stay", "Ooty", "Mid-Range", 3,
                    "Lake Road, Ooty 643001", 11.4065, 76.6924, 11, [
                        _room("olv-rt-1", "Valley Room", 8, 2900, "King Bed", 1, 2, False,
                              _room_numbers("OLV", 8), {"category": "Mountain View",
                                                           "amenities": ["Wi-Fi", "TV", "Breakfast", "Fireplace", "Parking"]}),
                        _room("olv-rt-2", "Cottage Wooden", 3, 3500, "King Bed", 1, 2, False,
                              _room_numbers("OLV", 3), {"category": "Cottage",
                                                           "amenities": ["Wi-Fi", "TV", "Breakfast", "Fireplace", "Parking"]}),
                    ], "98420 10025", [img_url("lake_mtn"), img_url("mountain_night")]))
    return hotels


# ---------------------------------------------------------------------------
# Restaurants + food items
# ---------------------------------------------------------------------------

def _upsert_restaurant(doc):
    coll = get_collection("restaurants")
    existing = coll.find_one({"ownerId": doc["ownerId"], "name": doc["name"]})
    doc["createdAt"] = doc.get("createdAt") or _now()
    doc["updatedAt"] = _now()
    if existing:
        coll.update_one({"_id": existing["_id"]}, {"$set": doc})
        return str(existing["_id"])
    doc["_id"] = new_user_id()
    coll.insert_one(doc)
    return doc["_id"]


def _upsert_food(rid, item):
    coll = get_collection("food_items")
    item = dict(item)
    existing = coll.find_one({"restaurantId": rid, "name": item["name"]})
    item["createdAt"] = item.get("createdAt") or _now()
    if existing:
        coll.update_one({"_id": existing["_id"]}, {"$set": item})
        return str(existing["_id"])
    item["_id"] = str(ObjectId())
    coll.insert_one(item)
    return item["_id"]


def seed_restaurants(uid):
    ann = uid["restaurant.annapoorna@tripmind.demo"]
    csj = uid["restaurant.chennaispice@tripmind.demo"]
    mdk = uid["restaurant.marinadeck@tripmind.demo"]
    kbc = uid["restaurant.kovaibotani@tripmind.demo"]

    def r(owner, name, rtype, city, address, lat, lng, cuisines, images):
        return _upsert_restaurant({
            "ownerId": owner, "name": name, "restaurantType": rtype, "city": city,
            "address": address, "lat": lat, "lng": lng,
            "contactNumber": _mobile(60), "email": None,
            "description": "%s — rated dining in %s." % (name, city),
            "operatingDays": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
            "openingHours": ["07:00-11:00", "12:30-15:30", "19:00-22:30"],
            "cuisines": cuisines, "images": images, "status": "APPROVED",
        })

    def f(rid, name, price, cat, img_key, prep=10, desc=""):
        _upsert_food(rid, {
            "restaurantId": rid, "name": name, "price": round(float(price), 2),
            "prepTimeMinutes": prep, "category": cat, "description": desc,
            "available": True, "image": img_url(img_key),
        })

    ann_id = r(ann, "Annapoorna South Indian Kitchen", "Casual Dining", "Coimbatore",
               "110 Cross-Cut Road, Coimbatore 641012", 11.0173, 76.9718,
               ["South Indian", "Tamil Nadu"], [img_url("restaurant2"), img_url("food1")])
    csj_id = r(csj, "Chennai Spice Junction", "Multi-Cuisine", "Chennai",
               "T. Nagar 3rd Avenue, Chennai 600017", 13.0419, 80.2347,
               ["Multi-Cuisine", "Biryani"], [img_url("restaurant3"), img_url("food3")])
    mdk_id = r(mdk, "Marina Deck", "Fine Dining", "Chennai",
               "Marina Beach Promenade, Chennai 600005", 13.0500, 80.2824,
               ["Seafood", "Coastal"], [img_url("restaurant1"), img_url("beach2")])
    kbc_id = r(kbc, "Kovai Botani Cafe", "Cafe", "Coimbatore",
               "Botanical Garden Road, Peelamedu, Coimbatore 641004", 11.0282, 76.9773,
               ["Cafe", "Continental"], [img_url("cafe1"), img_url("mountain_night")])

    f(ann_id, "Idli (2 pcs)", 35, "VEG", "breakfast1", 10)
    f(ann_id, "Medu Vada (2 pcs)", 25, "VEG", "breakfast2", 8)
    f(ann_id, "Ven Pongal", 55, "VEG", "food3", 10)
    f(ann_id, "Masala Dosa", 65, "VEG", "dosa", 12)
    f(ann_id, "Poori Masala (2 pcs)", 45, "VEG", "food5", 10)
    f(ann_id, "South Indian Meals", 130, "VEG", "food4", 5)
    f(ann_id, "Chapati (2 pcs)", 40, "VEG", "food1", 10)
    f(ann_id, "Kerala Parotta", 50, "VEG", "veg", 10)
    f(ann_id, "Curd Rice", 60, "VEG", "food2", 5)

    f(csj_id, "Filter Coffee", 30, "BEVERAGE", "coffee1", 5)
    f(csj_id, "Chicken Biryani", 210, "NON_VEG", "food3", 20)
    f(csj_id, "Vegetable Biryani", 160, "VEG", "dosa", 20)
    f(csj_id, "Chettinad Chicken", 240, "NON_VEG", "food5", 25)
    f(csj_id, "Egg Parotta", 55, "NON_VEG", "food1", 12)
    f(csj_id, "Mutton Chukka", 280, "NON_VEG", "food4", 25)

    f(mdk_id, "Fish Curry Meals", 260, "NON_VEG", "food4", 20)
    f(mdk_id, "Prawn Fry", 320, "NON_VEG", "food5", 25)
    f(mdk_id, "Curd Rice", 90, "VEG", "food2", 5)
    f(mdk_id, "Sea Food Thali", 340, "NON_VEG", "food3", 25)
    f(mdk_id, "Nethili Fry", 190, "NON_VEG", "food1", 15)

    f(kbc_id, "Vegetable Soup", 80, "VEG", "food2", 15)
    f(kbc_id, "Veg Noodles", 140, "VEG", "food5", 18)
    f(kbc_id, "Hot Chocolate", 120, "BEVERAGE", "coffee1", 10)
    f(kbc_id, "Roast Chicken", 260, "NON_VEG", "food1", 25)
    f(kbc_id, "Mixed Veg Curry", 150, "VEG", "veg", 20)
    f(kbc_id, "Quinoa Bowl", 180, "VEG", "veg", 15)
    return [ann_id, csj_id, mdk_id, kbc_id]


# ---------------------------------------------------------------------------
# Tourist spots, tours, guide locations
# ---------------------------------------------------------------------------

def _slots(raw):
    return [{"from": f, "to": t, "note": "Open window"} for f, t in raw]


def _upsert_spot(doc):
    coll = get_collection("tourist_spots")
    existing = coll.find_one({"ownerId": doc["ownerId"], "name": doc["name"]})
    doc["createdAt"] = doc.get("createdAt") or _now()
    doc["updatedAt"] = _now()
    if existing:
        coll.update_one({"_id": existing["_id"]}, {"$set": doc})
        return str(existing["_id"])
    doc["_id"] = _id()
    coll.insert_one(doc)
    return doc["_id"]


def _upsert_tour(doc):
    coll = get_collection("tours")
    existing = coll.find_one({"spotId": doc["spotId"], "name": doc["name"]})
    doc["createdAt"] = doc.get("createdAt") or _now()
    doc["updatedAt"] = _now()
    if existing:
        coll.update_one({"_id": existing["_id"]}, {"$set": doc})
        return str(existing["_id"])
    doc["_id"] = _id()
    coll.insert_one(doc)
    return doc["_id"]


def _upsert_guide_location(doc):
    coll = get_collection("guide_locations")
    existing = coll.find_one({"name": doc["name"]})
    doc["createdAt"] = doc.get("createdAt") or _now()
    if existing:
        coll.update_one({"_id": existing["_id"]}, {"$set": doc})
        return str(existing["_id"])
    doc["_id"] = _id()
    coll.insert_one(doc)
    return doc["_id"]


def seed_spots(uid):
    htn = uid["spot.heritagetn@tripmind.demo"]
    sln = uid["spot.shoreline@tripmind.demo"]
    ngs = uid["spot.nilgiris@tripmind.demo"]
    ksc = uid["spot.konguscenic@tripmind.demo"]

    spots = {}
    tours_out = []

    spots["marina"] = _upsert_spot({
        "ownerId": htn, "name": "Marina Beach", "city": "Chennai", "category": "BEACH",
        "location": {"name": "Marina Beach, Chennai", "address": "Marina Beach Road, Chennai 600005",
                     "lat": 13.0500, "lng": 80.2824, "city": "Chennai",
                     "district": "Chennai", "state": "Tamil Nadu", "country": "India"},
        "description": "One of the world's longest urban beaches on the Bay of Bengal, with the historic Anna and MGR memorials at its northern end.",
        "entryFee": 0.0, "openingTime": "05:00", "closingTime": "21:00",
        "recommendedTimes": _slots([("05:00", "08:00"), ("08:00", "11:00"), ("11:00", "14:00"),
                                    ("16:00", "18:00"), ("18:00", "21:00")]),
        "optimalTimes": _slots([("05:00", "08:00"), ("08:00", "11:00"), ("11:00", "14:00"),
                                ("16:00", "18:00"), ("18:00", "21:00")]),
        "workingDays": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
        "popularity": 92, "visitingTravelers": 1200,
        "images": [img_url("beach1"), img_url("beach2"), img_url("goa_beach"),
                   img_url("india_gate"), img_url("street_india")],
        "status": "APPROVED",
    })
    spots["fortstgeorge"] = _upsert_spot({
        "ownerId": htn, "name": "Fort St. George", "city": "Chennai", "category": "HERITAGE",
        "location": {"name": "Fort St. George, Chennai", "address": "Rajaji Salai, Chennai 600009",
                     "lat": 13.0800, "lng": 80.2869, "city": "Chennai",
                     "district": "Chennai", "state": "Tamil Nadu", "country": "India"},
        "description": "The 17th-century British East India Company fort that gave Chennai its name, now housing the oldest Anglican church in India.",
        "entryFee": 20.0, "openingTime": "09:00", "closingTime": "17:00",
        "recommendedTimes": _slots([("09:00", "12:00"), ("12:00", "15:00"), ("15:00", "17:00")]),
        "optimalTimes": _slots([("09:00", "12:00"), ("12:00", "15:00"), ("15:00", "17:00")]),
        "workingDays": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"],
        "popularity": 88, "visitingTravelers": 600,
        "images": [img_url("rajasthan_fort"), img_url("taj"), img_url("hawa_mahal"),
                   img_url("street_india"), img_url("india_street2")],
        "status": "APPROVED",
    })
    spots["kapaleeshwarar"] = _upsert_spot({
        "ownerId": htn, "name": "Kapaleeshwarar Temple", "city": "Chennai", "category": "HERITAGE",
        "location": {"name": "Kapaleeshwarar Temple, Mylapore", "address": "Mylapore, Chennai 600004",
                     "lat": 13.0337, "lng": 80.2699, "city": "Chennai",
                     "district": "Chennai", "state": "Tamil Nadu", "country": "India"},
        "description": "A 7th-century Dravidian temple carved in the Pallava style, Hebbar of gopurams and the mythical peacock-and-river origin story.",
        "entryFee": 0.0, "openingTime": "05:00", "closingTime": "21:00",
        "recommendedTimes": _slots([("05:00", "08:00"), ("09:00", "12:00"), ("16:00", "18:00"),
                                    ("18:00", "21:00")]),
        "optimalTimes": _slots([("05:00", "08:00"), ("09:00", "12:00"), ("16:00", "18:00"),
                                ("18:00", "21:00")]),
        "workingDays": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
        "popularity": 90, "visitingTravelers": 800,
        "images": [img_url("taj"), img_url("india_gate"), img_url("street_india"),
                   img_url("hawa_mahal"), img_url("india_street2")],
        "status": "APPROVED",
    })
    spots["mamallapuram"] = _upsert_spot({
        "ownerId": sln, "name": "Mahabalipuram (Shore Temple)", "city": "Mahabalipuram",
        "category": "HERITAGE",
        "location": {"name": "Shore Temple, Mahabalipuram", "address": "Baluchetti Street, Mahabalipuram 603104",
                     "lat": 12.6165, "lng": 80.1993, "city": "Mahabalipuram",
                     "district": "Chengalpattu", "state": "Tamil Nadu", "country": "India"},
        "description": "UNESCO World Heritage rock-cut temples and monolithic rathas carved from granite facing the Bay of Bengal.",
        "entryFee": 40.0, "openingTime": "06:00", "closingTime": "18:00",
        "recommendedTimes": _slots([("06:00", "09:00"), ("09:00", "12:00"), ("12:00", "15:00"),
                                    ("15:00", "18:00"), ("18:00", "21:00")]),
        "optimalTimes": _slots([("06:00", "09:00"), ("09:00", "12:00"), ("12:00", "15:00"),
                                ("15:00", "18:00"), ("18:00", "21:00")]),
        "workingDays": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
        "popularity": 95, "visitingTravelers": 900,
        "images": [img_url("taj"), img_url("hawa_mahal"), img_url("beach2"),
                   img_url("houseboat"), img_url("india_gate")],
        "status": "APPROVED",
    })
    spots["palladam_ghat"] = _upsert_spot({
        "ownerId": ksc, "name": "Marudhamalai Murugan Temple", "city": "Coimbatore",
        "category": "HERITAGE",
        "location": {"name": "Marudhamalai Temple, Coimbatore", "address": "Marudhamalai Hill Road, Coimbatore 641046",
                     "lat": 11.0344, "lng": 76.7141, "city": "Coimbatore",
                     "district": "Coimbatore", "state": "Tamil Nadu", "country": "India"},
        "description": "Temple of Lord Murugan on a scenic hill, a beloved spiritual stop with panoramic views over western Tamil Nadu.",
        "entryFee": 0.0, "openingTime": "05:00", "closingTime": "21:00",
        "recommendedTimes": _slots([("05:00", "08:00"), ("09:00", "12:00"), ("16:00", "18:00"),
                                    ("18:00", "21:00")]),
        "optimalTimes": _slots([("05:00", "08:00"), ("09:00", "12:00"), ("16:00", "18:00"),
                                ("18:00", "21:00")]),
        "workingDays": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
        "popularity": 85, "visitingTravelers": 700,
        "images": [img_url("hawa_mahal"), img_url("mountain_night"), img_url("nature1"),
                   img_url("india_gate"), img_url("street_india")],
        "status": "APPROVED",
    })
    spots["kovai_kondattam"] = _upsert_spot({
        "ownerId": ksc, "name": "Kovai Kondattam Amusement Park", "city": "Coimbatore",
        "category": "FUN",
        "location": {"name": "Kovai Kondattam, Coimbatore", "address": "Sundarapuram, Coimbatore 641024",
                     "lat": 10.9534, "lng": 76.9098, "city": "Coimbatore",
                     "district": "Coimbatore", "state": "Tamil Nadu", "country": "India"},
        "description": "Water and dry amusement park near Sundarapuram — rides, wave pool and slides for families.",
        "entryFee": 400.0, "openingTime": "09:00", "closingTime": "18:00",
        "recommendedTimes": _slots([("09:00", "12:00"), ("12:00", "15:00"), ("15:00", "18:00")]),
        "optimalTimes": _slots([("09:00", "12:00"), ("12:00", "15:00"), ("15:00", "18:00")]),
        "workingDays": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
        "popularity": 82, "visitingTravelers": 1100,
        "images": [img_url("beach1"), img_url("goa_beach"), img_url("resort_pool"),
                   img_url("nature1"), img_url("street_india")],
        "status": "APPROVED",
    })
    spots["ooty"] = _upsert_spot({
        "ownerId": ngs, "name": "Ooty Lake", "city": "Ooty", "category": "NATURE",
        "location": {"name": "Ooty Lake, Ooty", "address": "Lake Road, Ooty 643001",
                     "lat": 11.4065, "lng": 76.6924, "city": "Ooty",
                     "district": "The Nilgiris", "state": "Tamil Nadu", "country": "India"},
        "description": "Boating lake and gardens surrounded by eucalyptus and pine hills in the Nilgiri Blue Mountains.",
        "entryFee": 20.0, "openingTime": "09:00", "closingTime": "18:00",
        "recommendedTimes": _slots([("09:00", "12:00"), ("12:00", "15:00"), ("15:00", "18:00")]),
        "optimalTimes": _slots([("09:00", "12:00"), ("12:00", "15:00"), ("15:00", "18:00")]),
        "workingDays": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
        "popularity": 88, "visitingTravelers": 700,
        "images": [img_url("lake"), img_url("lake_mtn"), img_url("mountain_night"),
                   img_url("himalaya"), img_url("nature1")],
        "status": "APPROVED",
    })

    tours_out.append(_upsert_tour({
        "spotId": spots["marina"], "ownerId": htn,
        "name": "Dawn Beach & Memorial Walk", "description": "Guided sunrise walk along the promenade visiting the Kamarajar Statue, Anna Memorial and MGR Memorial.",
        "duration": 1.5, "cost": 150, "maxParticipants": 20, "bookedParticipants": 0,
        "availableTimes": _slots([("05:30", "07:00"), ("07:00", "08:30")]),
        "includedServices": ["Guide narration"], "guideRequired": False, "status": "APPROVED",
    }))
    tours_out.append(_upsert_tour({
        "spotId": spots["fortstgeorge"], "ownerId": htn,
        "name": "Fort & Heritage Quarter Walk", "description": "Explore the ramparts, museum and St. Mary's Church with a heritage storyteller.",
        "duration": 2.0, "cost": 250, "maxParticipants": 15, "bookedParticipants": 0,
        "availableTimes": _slots([("09:00", "11:00"), ("14:00", "16:00")]),
        "includedServices": ["Guide narration"], "guideRequired": True, "status": "APPROVED",
    }))
    tours_out.append(_upsert_tour({
        "spotId": spots["kapaleeshwarar"], "ownerId": htn,
        "name": "Temple Rituals & Legends Tour", "description": "Morning darshan walk through the temple explaining the Pallava legends and rituals.",
        "duration": 2.0, "cost": 200, "maxParticipants": 15, "bookedParticipants": 0,
        "availableTimes": _slots([("05:30", "07:30"), ("09:00", "11:00")]),
        "includedServices": ["Guide narration"], "guideRequired": True, "status": "APPROVED",
    }))
    tours_out.append(_upsert_tour({
        "spotId": spots["mamallapuram"], "ownerId": sln,
        "name": "Shore Temple Heritage Trail", "description": "In-depth guided trail of the Shore Temple, Five Rathas and Arjuna's Penance with a certified historian.",
        "duration": 3.0, "cost": 500, "maxParticipants": 12, "bookedParticipants": 0,
        "availableTimes": _slots([("07:00", "10:00"), ("15:00", "18:00")]),
        "includedServices": ["Certified guide", "Entry tickets"], "guideRequired": True, "status": "APPROVED",
    }))
    tours_out.append(_upsert_tour({
        "spotId": spots["palladam_ghat"], "ownerId": ksc,
        "name": "Marudhamalai Sunrise Trek", "description": "Early morning climb and darshan at the hilltop Murugan temple with valley viewpoints.",
        "duration": 3.0, "cost": 300, "maxParticipants": 12, "bookedParticipants": 0,
        "availableTimes": _slots([("05:00", "08:00"), ("08:00", "11:00")]),
        "includedServices": ["Guide narration"], "guideRequired": True, "status": "APPROVED",
    }))
    tours_out.append(_upsert_tour({
        "spotId": spots["kovai_kondattam"], "ownerId": ksc,
        "name": "Water Park Half-Day Pass", "description": "Half-day access to slides and wave pool with family locker included.",
        "duration": 4.0, "cost": 450, "maxParticipants": 40, "bookedParticipants": 0,
        "availableTimes": _slots([("09:00", "12:00"), ("11:00", "15:00"), ("14:00", "18:00")]),
        "includedServices": ["Entry tickets", "Locker"], "guideRequired": False, "status": "APPROVED",
    }))
    tours_out.append(_upsert_tour({
        "spotId": spots["ooty"], "ownerId": ngs,
        "name": "Lake Boating & Gardens Walk", "description": "Row-boat ride on Ooty Lake followed by a walk through the Government Botanical Gardens.",
        "duration": 2.5, "cost": 350, "maxParticipants": 10, "bookedParticipants": 0,
        "availableTimes": _slots([("09:00", "11:30"), ("14:00", "16:30")]),
        "includedServices": ["Boat ride", "Entry tickets"], "guideRequired": False, "status": "APPROVED",
    }))

    _upsert_guide_location({"name": "Chennai", "city": "Chennai",
                            "spots": [spots["marina"], spots["fortstgeorge"], spots["kapaleeshwarar"]],
                            "approved": True, "createdBy": htn})
    _upsert_guide_location({"name": "Mahabalipuram", "city": "Mahabalipuram",
                            "spots": [spots["mamallapuram"]], "approved": True, "createdBy": sln})
    _upsert_guide_location({"name": "Ooty", "city": "Ooty",
                            "spots": [spots["ooty"]], "approved": True, "createdBy": ngs})
    _upsert_guide_location({"name": "Coimbatore", "city": "Coimbatore",
                            "spots": [spots["palladam_ghat"], spots["kovai_kondattam"]],
                            "approved": True, "createdBy": ksc})

    return spots, tours_out


# ---------------------------------------------------------------------------
# Guides: pricing + locked weekly availability
# ---------------------------------------------------------------------------

def seed_guides(uid):
    gids = {
        "arun": uid["guide.arun@tripmind.demo"],
        "ravi": uid["guide.ravi@tripmind.demo"],
        "meera": uid["guide.meera@tripmind.demo"],
        "bhuvana": uid["guide.bhuvana@tripmind.demo"],
    }
    cities = {
        "arun": "Chennai", "ravi": "Coimbatore",
        "meera": "Mahabalipuram", "bhuvana": "Ooty",
    }
    pricing = [
        ("arun", 800, 4500, "Chennai Heritage — Fort St. George, Kapaleeshwarar, Marina, San Thome"),
        ("ravi", 700, 4000, "Kovai Trails — Marudhamalai, Perur, Kovai Kondattam, Siruvani"),
        ("meera", 750, 4200, "Mahabalipuram History — Shore Temple, Five Rathas, sculpting streets"),
        ("bhuvana", 650, 3800, "Ooty Nature — Botanical Gardens, Doddabetta, tea estates"),
    ]
    avails = 0
    for key, hourly, daily, details in pricing:
        gid = gids[key]
        old = get_collection("guide_pricing").find_one({"guideId": gid})
        doc = {"guideId": gid, "pricePerHour": float(hourly), "pricePerDay": float(daily),
               "details": details, "updatedAt": _now()}
        if old:
            doc["_id"] = old["_id"]
            get_collection("guide_pricing").replace_one({"_id": old["_id"]}, doc)
        else:
            doc["_id"] = _id()
            get_collection("guide_pricing").insert_one(doc)

        today = datetime.utcnow().date()
        week_start = today - timedelta(days=today.weekday())
        for w in range(6):
            ws = week_start + timedelta(weeks=w)
            we = ws + timedelta(days=6)
            week_id = "%04d-W%02d" % (ws.isocalendar()[0], ws.isocalendar()[1])
            coll = get_collection("guide_availability")
            if coll.find_one({"guideId": gid, "weekStart": ws.isoformat()}):
                continue
            days = []
            for d in range(7):
                day = ws + timedelta(days=d)
                days.append({
                    "date": day.isoformat(),
                    "slots": [{"from": "09:00", "to": "13:00"}, {"from": "14:00", "to": "18:00"}],
                    "locations": [cities[key]],
                })
            coll.insert_one({
                "_id": _id(), "guideId": gid, "weekId": week_id,
                "weekStart": ws.isoformat(), "weekEnd": we.isoformat(),
                "days": days, "locations": [cities[key]],
                "locked": True, "lockedAt": _now(), "createdAt": _now(),
            })
            avails += 1
    return gids, avails


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def seed_all(verbose=True):
    if verbose:
        print("=" * 70)
        print("TripMind AI — Coimbatore <-> Chennai corridor seed")
        print("=" * 70)
    ensure_unique_indexes()  # idempotent
    seed_admin()
    uid = seed_users()
    if verbose:
        print("\n[users] %d corridor accounts + Main Admin synced (password='password')" % len(ACCOUNTS))
    seed_trains(uid)
    seed_buses(uid)
    seed_flights(uid)
    seed_cabs(uid)
    seed_lounges(uid)
    seed_hotels(uid)
    seed_restaurants(uid)
    seed_spots(uid)
    _, avail = seed_guides(uid)
    if verbose:
        print("[trains] 20 IR trains on Coimbatore Junction <-> Chennai Egmore")
        print("[buses]  30 inter-city buses (Coimbatore <-> Chennai)")
        print("[flights] 10 flights (Coimbatore CJB <-> Chennai MAA)")
        print("[cabs]   30 cabs/autos (Coimbatore + Chennai)")
        print("[lounges]  4 railway lounges (Egmore, Chennai Central, Coimbatore Jn, Tiruppur)")
        print("[guides] %d guide pricing profiles + %d locked weeks of availability" % (4, avail))
        print("[images] %d distinct verified Unsplash image ids used" % len(_IMG_USED))
    return summarize()


def summarize():
    db = get_collection("users").database
    users = get_collection("users")
    def count(coll, q=None):
        return db[coll].count_documents(q or {})
    by_role = {}
    for rlabel, rid in ((_ROLE_LABEL[k], k) for k in _ROLE_LABEL):
        by_role[rlabel] = users.count_documents({"role": rid})
    summary = {
        "railway_admins": by_role.get("Railway Admin", 0),
        "transport_admins": by_role.get("Transport Admin", 0),
        "hotel_admins": by_role.get("Hotel Admin", 0),
        "restaurant_admins": by_role.get("Restaurant Admin", 0),
        "travel_spot_admins": by_role.get("Travel Spot Admin", 0),
        "guides": by_role.get("Guide", 0),
        "system_admins": users.count_documents({"role": "ADMIN"}),
        "passengers": by_role.get("Passenger", 0),
        "transports": count("transports"),
        "transports_approved": count("transports", {"status": "APPROVED"}),
        "trains": count("transports", {"type": "TRAIN"}),
        "buses": count("transports", {"type": "BUS"}),
        "flights": count("transports", {"type": "FLIGHT"}),
        "cabs": count("transports", {"type": {"$in": ["CAB", "AUTO"]}}),
        "lounges": count("lounges"),
        "hotels": count("hotels"),
        "hotels_approved": count("hotels", {"status": "APPROVED"}),
        "restaurants": count("restaurants"),
        "food_items": count("food_items", {"available": True}),
        "tourist_spots": count("tourist_spots"),
        "tours": count("tours"),
        "guide_locations": count("guide_locations"),
        "guide_pricing": count("guide_pricing"),
        "guide_availability_weeks": count("guide_availability"),
    }
    return summary


def print_summary(summary):
    print("\n" + "=" * 70)
    print("SEED VERIFICATION — database summary (db=%s)" % get_collection("users").database.name)
    print("=" * 70)
    lines = [
        ("System Admin accounts", summary["system_admins"]),
        ("Passenger (USER) accounts", summary["passengers"]),
        ("Railway Admin accounts", summary["railway_admins"]),
        ("Transport Admin accounts", summary["transport_admins"]),
        ("Hotel Admin accounts", summary["hotel_admins"]),
        ("Restaurant Admin accounts", summary["restaurant_admins"]),
        ("Travel Spot Admin accounts", summary["travel_spot_admins"]),
        ("Guide accounts", summary["guides"]),
        ("Transports (approved)", "%d (%d)" % (summary["transports"], summary["transports_approved"])),
        ("  Trains", summary["trains"]),
        ("  Buses", summary["buses"]),
        ("  Flights", summary["flights"]),
        ("  Cabs/Autos", summary["cabs"]),
        ("Lounges", summary["lounges"]),
        ("Hotels (approved)", "%d (%d)" % (summary["hotels"], summary["hotels_approved"])),
        ("Restaurants", summary["restaurants"]),
        ("Food items available", summary["food_items"]),
        ("Tourist spots", summary["tourist_spots"]),
        ("Tours", summary["tours"]),
        ("Guide locations", summary["guide_locations"]),
        ("Guide pricing profiles", summary["guide_pricing"]),
        ("Guide availability weeks", summary["guide_availability_weeks"]),
    ]
    for k, v in lines:
        print("  %-34s %s" % (k, v))
    print("=" * 70)


if __name__ == "__main__":
    s = seed_all()
    print_summary(s)