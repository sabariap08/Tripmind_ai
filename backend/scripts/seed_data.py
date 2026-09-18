"""Seed a realistic development/test database for TripMind AI.

Creates the 25 seeded resource accounts (5 x Transport Admin, Hotel Admin,
Restaurant Admin, Travel Spot Admin, Guide), keeps the system Main Admin, and
loads real, linked catalogue data for each provider:

  Transport Admins -> registered vehicles/routes with fare models
  Hotel Admins     -> hotels with room-type inventory (sum == totalRooms)
  Restaurant Admins-> restaurants + food items (breakfast & dinner)
  Travel Spot Admins-> tourist spots (>=5 images, >=5 optimal slots) + tours
  Guides           -> profile, pricing, and locked weekly availability

IDEMPOTENT: every write is an upsert keyed on a stable natural key (email,
transport numberKey, owner+name, restaurantId+name, spotId+tour name,
guideId+weekStart). Re-running this script only syncs data to the definitions
below; it never wipes other collections or removes catalogue.

Seeded login credentials: password is exactly "password" for every account.
Report them via scripts/make_credentials_pdf.py -> TripMind_AI_Test_Credentials.pdf.
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

PASSWORD = "password"

# Verified at seed-build time: every Unsplash image id below returned HTTP 200.
# Images are hotlinked from the Unsplash CDN (Unsplash License, free to use).
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


# ---------------------------------------------------------------------------
# Account table (single source of truth for credentials + PDF generator)
# ---------------------------------------------------------------------------
ACCOUNTS = [
    # -- Transport Admins --
    {"role": "TRANSPORT_ADMIN", "name": "S. Ramesh", "company": "SRL Travels",
     "email": "transport.srl@tripmind.demo", "city": "Coimbatore", "companyId": "srl"},
    {"role": "TRANSPORT_ADMIN", "name": "K. Murugan", "company": "KMS Transport",
     "email": "transport.kms@tripmind.demo", "city": "Chennai", "companyId": "kms"},
    {"role": "TRANSPORT_ADMIN", "name": "M. Varun", "company": "Blue Horizon Aviation",
     "email": "transport.bluehorizon@tripmind.demo", "city": "Chennai", "companyId": "bha"},
    {"role": "TRANSPORT_ADMIN", "name": "G. Thirunavukkarasu", "company": "GTG Tours & Travels",
     "email": "transport.gtg@tripmind.demo", "city": "Coimbatore", "companyId": "gtg"},
    {"role": "TRANSPORT_ADMIN", "name": "S. Aneesh", "company": "Vembanad Cabs",
     "email": "transport.vembanad@tripmind.demo", "city": "Alappuzha", "companyId": "vcb"},
    # -- Hotel Admins --
    {"role": "HOTEL_ADMIN", "name": "R. Priya", "company": "Grand Chennai Residency",
     "email": "hotel.grandchennai@tripmind.demo", "city": "Chennai", "companyId": "gcr"},
    {"role": "HOTEL_ADMIN", "name": "V. Deepa", "company": "Shore Temple Heritage",
     "email": "hotel.shoretemple@tripmind.demo", "city": "Mahabalipuram", "companyId": "sth"},
    {"role": "HOTEL_ADMIN", "name": "P. Karthik", "company": "Hotel Residency",
     "email": "hotel.residency@tripmind.demo", "city": "Coimbatore", "companyId": "hre"},
    {"role": "HOTEL_ADMIN", "name": "A. Lakshmi", "company": "Ooty Lake View Stay",
     "email": "hotel.ootylakeview@tripmind.demo", "city": "Ooty", "companyId": "olv"},
    {"role": "HOTEL_ADMIN", "name": "N. Suresh", "company": "Palace View Comforts",
     "email": "hotel.palaceview@tripmind.demo", "city": "Mysuru", "companyId": "pvc"},
    # -- Restaurant Admins --
    {"role": "RESTAURANT_ADMIN", "name": "K. Radhakrishnan", "company": "Annapoorna South Indian Kitchen",
     "email": "restaurant.annapoorna@tripmind.demo", "city": "Coimbatore", "companyId": "ann"},
    {"role": "RESTAURANT_ADMIN", "name": "V. Imran", "company": "Chennai Spice Junction",
     "email": "restaurant.chennaispice@tripmind.demo", "city": "Chennai", "companyId": "csj"},
    {"role": "RESTAURANT_ADMIN", "name": "J. Wilson", "company": "Marina Deck",
     "email": "restaurant.marinadeck@tripmind.demo", "city": "Chennai", "companyId": "mdk"},
    {"role": "RESTAURANT_ADMIN", "name": "R. Meena", "company": "Ooty Garden Cafe",
     "email": "restaurant.ootygarden@tripmind.demo", "city": "Ooty", "companyId": "ogc"},
    {"role": "RESTAURANT_ADMIN", "name": "F. Babu", "company": "Malabar Corner",
     "email": "restaurant.malabar@tripmind.demo", "city": "Alappuzha", "companyId": "mlb"},
    # -- Travel Spot Admins --
    {"role": "TOURIST_SPOT_ADMIN", "name": "D. Bhavani", "company": "Heritage Tamil Nadu",
     "email": "spot.heritagetn@tripmind.demo", "city": "Chennai", "companyId": "htn"},
    {"role": "TOURIST_SPOT_ADMIN", "name": "S. Kannan", "company": "Shoreline Monuments",
     "email": "spot.shoreline@tripmind.demo", "city": "Mahabalipuram", "companyId": "sln"},
    {"role": "TOURIST_SPOT_ADMIN", "name": "R. Joseph", "company": "Nilgiris Tourism",
     "email": "spot.nilgiris@tripmind.demo", "city": "Ooty", "companyId": "ngs"},
    {"role": "TOURIST_SPOT_ADMIN", "name": "P. Anitha", "company": "Mysuru Heritage Trust",
     "email": "spot.mysuruheritage@tripmind.demo", "city": "Mysuru", "companyId": "mht"},
    {"role": "TOURIST_SPOT_ADMIN", "name": "A. Leena", "company": "Kerala Backwater Club",
     "email": "spot.backwater@tripmind.demo", "city": "Alappuzha", "companyId": "kbw"},
    # -- Guides --
    {"role": "GUIDE", "name": "Arun Prakash", "company": "Arun Prakash — Chennai Heritage",
     "email": "guide.arun@tripmind.demo", "city": "Chennai", "companyId": "gar"},
    {"role": "GUIDE", "name": "Meera Krishnan", "company": "Meera Krishnan — Mahabalipuram History",
     "email": "guide.meera@tripmind.demo", "city": "Mahabalipuram", "companyId": "gme"},
    {"role": "GUIDE", "name": "Bhuvana Suresh", "company": "Bhuvana Suresh — Ooty Nature",
     "email": "guide.bhuvana@tripmind.demo", "city": "Ooty", "companyId": "gbh"},
    {"role": "GUIDE", "name": "Thomas Mathew", "company": "Thomas Mathew — Kerala Backwaters",
     "email": "guide.thomas@tripmind.demo", "city": "Alappuzha", "companyId": "gth"},
    {"role": "GUIDE", "name": "Kavya Rao", "company": "Kavya Rao — Mysuru Heritage",
     "email": "guide.kavya@tripmind.demo", "city": "Mysuru", "companyId": "gkv"},
]

_ROLE_LABEL = {
    "TRANSPORT_ADMIN": "Transport Admin",
    "HOTEL_ADMIN": "Hotel Admin",
    "RESTAURANT_ADMIN": "Restaurant Admin",
    "TOURIST_SPOT_ADMIN": "Travel Spot Admin",
    "GUIDE": "Guide",
}

def _mobile(i):
    return "%d%08d" % (9, 20000000 + i)


def _gst(i):
    return "33AAAAA%04dZ%02dN%02d" % (i, i % 30, i % 10)


def _identity(i):
    return "%012d" % (700000000000 + i)


def _registration_fields(role, a, i):
    base = {"city": a["city"], "ownerName": a["name"]}
    reg = {"registration": {}}
    if role == "TRANSPORT_ADMIN":
        reg["registration"] = {
            "companyName": a["company"],
            "companyCity": a["city"],
            "serviceArea": a["city"] + " district",
            "companyAddress": "Road no. %d, %s" % (i, a["city"]),
            "companyPhone": _mobile(i),
            "driverCount": str(2 + i % 8),
            "description": "Registered inter-city and local transport provider.",
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
            "languages": "Tamil, English" if a["city"] in ("Chennai", "Mahabalipuram", "Coimbatore", "Ooty") else "Malayalam, English",
            "base location": a["city"],
        }
    return reg


def _state_for(city):
    if city in ("Chennai", "Mahabalipuram", "Coimbatore", "Ooty"):
        return "Tamil Nadu"
    if city in ("Mysuru",):
        return "Karnataka"
    if city in ("Alappuzha",):
        return "Kerala"
    return "Tamil Nadu"


def _profile(role, a, i):
    p = {"scope": ""}
    if role == "TRANSPORT_ADMIN":
        p["serviceName"] = a["company"]
        p["contact"] = a["company"] + ", " + a["city"]
        p["description"] = "Registered transport provider serving %s and nearby corridors." % a["city"]
    if role == "GUIDE":
        specialty = a["company"].split("—")[1].strip()
        p.update({
            "specialty": specialty,
            "languages": ["Tamil", "English"] if a["city"] not in ("Alappuzha",) else ["Malayalam", "English"],
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
                # re-try without optional unique fields
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


def seed_transports(uid):
    def t(spec):
        spec["_id"] = _id()
        spec["numberKey"] = (spec.get("busNumber") or spec.get("trainNumber")
                             or spec.get("flightNumber") or spec.get("vehicleNumber"))
        out = _upsert_transport(spec)
        return out

    units = []
    srl = uid["transport.srl@tripmind.demo"]
    kms = uid["transport.kms@tripmind.demo"]
    bha = uid["transport.bluehorizon@tripmind.demo"]
    gtg = uid["transport.gtg@tripmind.demo"]
    vcb = uid["transport.vembanad@tripmind.demo"]

    # SRL Travels
    units.append(t({
        "ownerId": srl, "type": "BUS", "status": "APPROVED", "serviceName": "SRL Travels",
        "images": [img_url("bus1"), img_url("street_india")],
        "busNumber": "TN-38 AB 1234", "boardingPoint": "Coimbatore", "boardingDay": 0,
        "boardingTime": "21:30", "droppingPoint": "Chennai", "droppingDay": 1,
        "droppingTime": "05:15", "stops": [
            {"name": "Erode", "day": 0, "time": "23:10"},
            {"name": "Salem", "day": 0, "time": "01:20"},
            {"name": "Vellore", "day": 1, "time": "03:40"},
        ],
        "seatTypes": ["SLEEPER", "SEATER"], "totalSeats": 40, "sleeperSeats": 24,
        "seaterSeats": 16, "singleSeat": True, "doubleSeat": True, "layout": None,
        "fare": {"sleeper": 899, "seater": 699}, "bookedSeats": 0,
        "documents": [], "rejectionReason": None,
    }))
    units.append(t({
        "ownerId": srl, "type": "BUS", "status": "APPROVED", "serviceName": "SRL Travels",
        "images": [img_url("bus2")],
        "busNumber": "TN-37 AA 2211", "boardingPoint": "Coimbatore", "boardingDay": 0,
        "boardingTime": "20:45", "droppingPoint": "Bengaluru", "droppingDay": 0,
        "droppingTime": "04:30", "stops": [
            {"name": "Tiruppur", "day": 0, "time": "21:30"},
            {"name": "Salem", "day": 0, "time": "23:50"},
            {"name": "Krishnagiri", "day": 1, "time": "02:30"},
        ],
        "seatTypes": ["SEATER"], "totalSeats": 45, "sleeperSeats": 0, "seaterSeats": 45,
        "singleSeat": True, "doubleSeat": True, "layout": None,
        "fare": {"seater": 599}, "bookedSeats": 0,
        "documents": [], "rejectionReason": None,
    }))
    units.append(t({
        "ownerId": srl, "type": "BUS", "status": "APPROVED", "serviceName": "SRL Travels",
        "images": [img_url("bus1"), img_url("houseboat")],
        "busNumber": "TN-01 BX 9901", "boardingPoint": "Chennai", "boardingDay": 0,
        "boardingTime": "22:00", "droppingPoint": "Coimbatore", "droppingDay": 1,
        "droppingTime": "05:45", "stops": [{"name": "Vellore", "day": 0, "time": "00:10"}],
        "seatTypes": ["SLEEPER"], "totalSeats": 30, "sleeperSeats": 30, "seaterSeats": 0,
        "singleSeat": True, "doubleSeat": False, "layout": None,
        "fare": {"sleeper": 899}, "bookedSeats": 0,
        "documents": [], "rejectionReason": None,
    }))
    units.append(t({
        "ownerId": srl, "type": "CAB", "status": "APPROVED", "serviceName": "SRL Travels",
        "images": [img_url("car1")],
        "vehicleNumber": "TN-37 CA 8001", "vehicleType": "Sedan", "seatingCapacity": 4,
        "ac": True, "driver": {"name": "D. Prakash", "contact": _mobile(30)},
        "serviceArea": "Coimbatore",
        "baseLocation": "KPR Institute of Engineering and Technology, Coimbatore",
        "availableTimings": {"from": "06:00", "to": "22:00"},
        "fare": {"baseFare": 50.0, "pricePerKm": 12.0, "minimum": 100.0},
        "bookedSeats": 0, "documents": [], "rejectionReason": None,
    }))

    # KMS Transport
    units.append(t({
        "ownerId": kms, "type": "BUS", "status": "APPROVED", "serviceName": "KMS Transport",
        "images": [img_url("bus2"), img_url("goa_beach")],
        "busNumber": "TN-39 DX 5512", "boardingPoint": "Chennai", "boardingDay": 0,
        "boardingTime": "07:30", "droppingPoint": "Mahabalipuram", "droppingDay": 0,
        "droppingTime": "09:15", "stops": [{"name": "ECR Toll", "day": 0, "time": "08:15"}],
        "seatTypes": ["SEATER"], "totalSeats": 35, "sleeperSeats": 0, "seaterSeats": 35,
        "singleSeat": True, "doubleSeat": True, "layout": None,
        "fare": {"seater": 149}, "bookedSeats": 0,
        "documents": [], "rejectionReason": None,
    }))
    units.append(t({
        "ownerId": kms, "type": "AUTO", "status": "APPROVED", "serviceName": "KMS Transport",
        "images": [img_url("auto1")],
        "vehicleNumber": "TN-07 AY 3344", "vehicleType": "AUTO", "seatingCapacity": 3,
        "ac": False, "driver": {"name": "P. Selvam", "contact": _mobile(31)},
        "serviceArea": "Mahabalipuram", "baseLocation": "Chennai",
        "availableTimings": {"from": "06:00", "to": "20:00"},
        "fare": {"baseFare": 30.0, "pricePerKm": 10.0, "minimum": 50.0},
        "bookedSeats": 0, "documents": [], "rejectionReason": None,
    }))
    units.append(t({
        "ownerId": kms, "type": "TRAIN", "status": "APPROVED", "serviceName": "KMS Transport",
        "images": [img_url("rail1")],
        "trainNumber": "12674", "trainName": "Cheran Express",
        "boardingStation": "Coimbatore Junction", "destinationStation": "Chennai Egmore",
        "boardingDay": 0, "boardingTime": "20:15", "droppingDay": 1, "droppingTime": "05:10",
        "stations": [
            {"name": "Tiruppur", "day": 0, "arrivalTime": "21:05", "departureTime": "21:07"},
            {"name": "Erode", "day": 0, "arrivalTime": "22:10", "departureTime": "22:15"},
            {"name": "Salem", "day": 0, "arrivalTime": "23:30", "departureTime": "23:35"},
            {"name": "Chennai Egmore", "day": 1, "arrivalTime": "05:10", "departureTime": ""},
        ],
        "coaches": [
            {"code": "SL", "label": "Sleeper", "coachCount": 6, "capacityPerCoach": 72, "price": 370},
            {"code": "3A", "label": "3 Tier AC", "coachCount": 4, "capacityPerCoach": 64, "price": 780},
            {"code": "2A", "label": "2 Tier AC", "coachCount": 2, "capacityPerCoach": 46, "price": 1100},
        ],
        "totalCoaches": 12, "recurring": [], "daysOfWeek": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
        "bookedSeats": 0, "documents": [], "rejectionReason": None,
    }))

    # Blue Horizon Aviation
    units.append(t({
        "ownerId": bha, "type": "FLIGHT", "status": "APPROVED", "serviceName": "Blue Horizon Aviation",
        "images": [img_url("flight1")],
        "flightNumber": "6E-2041", "airline": "Blue Horizon Aviation",
        "departureAirport": "Coimbatore (CJB)", "arrivalAirport": "Chennai (MAA)",
        "boardingDay": 0, "boardingTime": "07:45", "arrivalDay": 0, "arrivalTime": "08:55",
        "layoverAirport": "", "totalSeats": 102,
        "classes": [
            {"name": "Economy", "seats": 90, "price": 1480},
            {"name": "Business", "seats": 12, "price": 4800},
        ],
        "baggage": {"cabin": "7 kg", "checkin": "15 kg"},
        "bookedSeats": 0, "documents": [], "rejectionReason": None,
    }))

    # GTG Tours (Coimbatore -> Ooty)
    units.append(t({
        "ownerId": gtg, "type": "BUS", "status": "APPROVED", "serviceName": "GTG Tours & Travels",
        "images": [img_url("bus1"), img_url("lake_mtn")],
        "busNumber": "TN-43 GT 7788", "boardingPoint": "Coimbatore", "boardingDay": 0,
        "boardingTime": "08:00", "droppingPoint": "Ooty", "droppingDay": 0,
        "droppingTime": "11:30", "stops": [{"name": "Mettupalayam", "day": 0, "time": "08:50"},
                                          {"name": "Kotagiri Ghat", "day": 0, "time": "09:50"}],
        "seatTypes": ["SEATER"], "totalSeats": 30, "sleeperSeats": 0, "seaterSeats": 30,
        "singleSeat": True, "doubleSeat": True, "layout": None,
        "fare": {"seater": 249}, "bookedSeats": 0,
        "documents": [], "rejectionReason": None,
    }))
    units.append(t({
        "ownerId": gtg, "type": "CAB", "status": "APPROVED", "serviceName": "GTG Tours & Travels",
        "images": [img_url("car2")],
        "vehicleNumber": "TN-37 GH 9009", "vehicleType": "SUV", "seatingCapacity": 6,
        "ac": True, "driver": {"name": "S. Kumar", "contact": _mobile(32)},
        "serviceArea": "Ooty", "baseLocation": "Coimbatore",
        "availableTimings": {"from": "05:00", "to": "21:00"},
        "fare": {"baseFare": 120.0, "pricePerKm": 18.0, "minimum": 250.0},
        "bookedSeats": 0, "documents": [], "rejectionReason": None,
    }))

    # Vembanad Cabs (Kochi -> Alappuzha)
    units.append(t({
        "ownerId": vcb, "type": "CAB", "status": "APPROVED", "serviceName": "Vembanad Cabs",
        "images": [img_url("car3"), img_url("houseboat")],
        "vehicleNumber": "KL-04 VC 0199", "vehicleType": "Sedan", "seatingCapacity": 4,
        "ac": True, "driver": {"name": "R. Shaji", "contact": _mobile(33)},
        "serviceArea": "Alappuzha", "baseLocation": "Kochi",
        "availableTimings": {"from": "06:00", "to": "21:00"},
        "fare": {"baseFare": 150.0, "pricePerKm": 15.0, "minimum": 300.0},
        "bookedSeats": 0, "documents": [], "rejectionReason": None,
    }))
    units.append(t({
        "ownerId": vcb, "type": "BUS", "status": "APPROVED", "serviceName": "Vembanad Cabs",
        "images": [img_url("bus2")],
        "busNumber": "KL-04 KA 1201", "boardingPoint": "Kochi", "boardingDay": 0,
        "boardingTime": "09:00", "droppingPoint": "Alappuzha", "droppingDay": 0,
        "droppingTime": "11:00", "stops": [{"name": "Cherthala", "day": 0, "time": "10:05"}],
        "seatTypes": ["SEATER"], "totalSeats": 40, "sleeperSeats": 0, "seaterSeats": 40,
        "singleSeat": True, "doubleSeat": True, "layout": None,
        "fare": {"seater": 189}, "bookedSeats": 0,
        "documents": [], "rejectionReason": None,
    }))
    return units


# ---------------------------------------------------------------------------
# Hotels
# ---------------------------------------------------------------------------

def _room(rid, name, total, price, bed, beds, occ, ac, numbers, extra=None):
    r = {
        "id": rid, "name": name, "category": extra.get("category", "Standard") if extra else "Standard",
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


def _room_id_seq(start):
    return ["R%d-%03d" % (start, i) for i in range(1, 1 + 30)][:30]


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
            "contactNumber": contact, "email": owner and None,
            "checkInTime": "12:00", "checkOutTime": "11:00",
            "amenities": ["Wi-Fi", "Parking", "Restaurant", "Room Service", "AC", "TV", "Breakfast", "24/7 Front Desk"],
            "category": category, "starRating": stars,
            "images": images, "documents": [],
            "totalRooms": total, "roomTypes": room_types,
            "status": "APPROVED",
        })

    hotels = []
    gcr = uid["hotel.grandchennai@tripmind.demo"]
    sth = uid["hotel.shoretemple@tripmind.demo"]
    hre = uid["hotel.residency@tripmind.demo"]
    olv = uid["hotel.ootylakeview@tripmind.demo"]
    pvc = uid["hotel.palaceview@tripmind.demo"]

    hotels.append(h(gcr, "Grand Chennai Residency", "Chennai", "Luxury", 4,
                    "No. 12, Cathedral Road, Chennai 600086", 13.0358, 80.2385, 21, [
                        _room("gcr-rt-1", "Deluxe King", 10, 4200, "King Bed", 1, 2, True,
                              ["GCR101", "GCR102", "GCR103", "GCR104", "GCR105",
                               "GCR106", "GCR107", "GCR108", "GCR109", "GCR110"],
                              {"category": "Luxury"}),
                        _room("gcr-rt-2", "Executive Suite", 4, 7200, "King Bed", 2, 3, True,
                              ["GCR201", "GCR202", "GCR203", "GCR204"],
                              {"category": "Suite"}),
                        _room("gcr-rt-3", "Standard Double", 7, 2600, "Double Bed", 1, 2, True,
                              ["GCR301", "GCR302", "GCR303", "GCR304", "GCR305", "GCR306", "GCR307"]),
                    ], "98420 10021", [img_url("room2"), img_url("resort_pool")]))
    hotels.append(h(sth, "Shore Temple Heritage", "Mahabalipuram", "Mid-Range", 3,
                    "East Raja Street, Mahabalipuram 603104", 12.6169, 80.1991, 12, [
                        _room("sth-rt-1", "Garden Double", 8, 1650, "Double Bed", 1, 2, True,
                              ["STH101", "STH102", "STH103", "STH104", "STH105",
                               "STH106", "STH107", "STH108"]),
                        _room("sth-rt-2", "Sea View Twin", 4, 2100, "Twin Bed", 2, 2, True,
                              ["STH201", "STH202", "STH203", "STH204"]),
                    ], "98420 10022", [img_url("room4"), img_url("beach1")]))
    hotels.append(h(hre, "Hotel Residency", "Coimbatore", "Budget", 2,
                    "Avinashi Road, Coimbatore 641004", 11.0266, 76.9951, 10, [
                        _room("hre-rt-1", "Standard", 6, 1200, "Double Bed", 1, 2, True,
                              ["HRE101", "HRE102", "HRE103", "HRE104", "HRE105", "HRE106"]),
                        _room("hre-rt-2", "Dormitory", 4, 700, "Multiple Beds", 6, 1, True,
                              ["HRE201", "HRE202", "HRE203", "HRE204"],
                              {"category": "Budget"}),
                    ], "98420 10023", [img_url("room3"), img_url("breakfast2")]))
    hotels.append(h(olv, "Ooty Lake View Stay", "Ooty", "Mid-Range", 3,
                    "Lake Road, Ooty 643001", 11.4065, 76.6924, 11, [
                        _room("olv-rt-1", "Valley Room", 8, 2900, "King Bed", 1, 2, False,
                              ["OLV101", "OLV102", "OLV103", "OLV104", "OLV105",
                               "OLV106", "OLV107", "OLV108"],
                              {"category": "Mountain View", "amenities": ["Wi-Fi", "TV", "Breakfast", "Fireplace", "Parking"]}),
                        _room("olv-rt-2", "Cottage Wooden", 3, 3500, "King Bed", 1, 2, False,
                              ["OLV201", "OLV202", "OLV203"],
                              {"category": "Cottage", "amenities": ["Wi-Fi", "TV", "Breakfast", "Fireplace", "Parking"]}),
                    ], "98420 10024", [img_url("lake_mtn"), img_url("mountain_night")]))
    hotels.append(h(pvc, "Palace View Comforts", "Mysuru", "Budget", 2,
                    "Sayyaji Rao Road, Mysuru 570001", 12.3053, 76.6545, 12, [
                        _room("pvc-rt-1", "Standard AC", 6, 1100, "Double Bed", 1, 2, True,
                              ["PVC101", "PVC102", "PVC103", "PVC104", "PVC105", "PVC106"]),
                        _room("pvc-rt-2", "Non-AC Sahana", 6, 750, "Double Bed", 1, 2, False,
                              ["PVC201", "PVC202", "PVC203", "PVC204", "PVC205", "PVC206"],
                              {"category": "Budget"}),
                    ], "98420 10025", [img_url("room5"), img_url("rajasthan_fort")]))
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
    ogc = uid["restaurant.ootygarden@tripmind.demo"]
    mlb = uid["restaurant.malabar@tripmind.demo"]

    def r(owner, name, rtype, city, address, lat, lng, cuisines, images):
        return _upsert_restaurant({
            "ownerId": owner, "name": name, "restaurantType": rtype, "city": city,
            "address": address, "lat": lat, "lng": lng,
            "contactNumber": _mobile(40), "email": None,
            "description": "%s — rated veg/contemporary dining in %s." % (name, city),
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
               ["Multi-Cuisine", "Biryani"], [img_url("restaurant3")])
    mdk_id = r(mdk, "The Marina Deck", "Fine Dining", "Chennai",
               "Marina Beach Promenade, Chennai 600005", 13.0500, 80.2824,
               ["Seafood", "Coastal"], [img_url("restaurant1"), img_url("beach2")])
    ogc_id = r(ogc, "Ooty Garden Cafe", "Cafe", "Ooty",
               "Charing Cross, Ooty 643001", 11.4136, 76.6972,
               ["Continental", "Cafe"], [img_url("cafe1"), img_url("mountain_night")])
    mlb_id = r(mlb, "Malabar Corner", "Casual Dining", "Alappuzha",
               "C.C.N.B. Road, Alappuzha 688012", 9.4983, 76.3386,
               ["Kerala", "Coastal"], [img_url("houseboat"), img_url("food2")])

    # Breakfast
    f(ann_id, "Idli (2 pcs)", 35, "VEG", "breakfast1", 10)
    f(ann_id, "Medu Vada (2 pcs)", 25, "VEG", "breakfast2", 8)
    f(ann_id, "Ven Pongal", 55, "VEG", "food3", 10)
    f(ann_id, "Masala Dosa", 65, "VEG", "dosa", 12)
    f(ann_id, "Poori Masala (2 pcs)", 45, "VEG", "food5", 10)
    # Dinner / meals
    f(ann_id, "South Indian Meals", 130, "VEG", "food4", 5)
    f(ann_id, "Chapati (2 pcs)", 40, "VEG", "food1", 10)
    f(ann_id, "Kerala Parotta", 50, "VEG", "veg", 10)
    f(ann_id, "Curd Rice", 60, "VEG", "food2", 5)

    f(csj_id, "Filter Coffee", 30, "BEVERAGE", "coffee1", 5)
    f(csj_id, "Chicken Biryani", 210, "NON_VEG", "food3", 20)
    f(csj_id, "Vegetable Biryani", 160, "VEG", "dosa", 20)
    f(csj_id, "Chettinad Chicken", 240, "NON_VEG", "food5", 25)
    f(csj_id, "Egg Parotta", 55, "NON_VEG", "food1", 12)

    f(mdk_id, "Fish Curry Meals", 260, "NON_VEG", "food4", 20)
    f(mdk_id, "Prawn Fry", 320, "NON_VEG", "food5", 25)
    f(mdk_id, "Curd Rice", 90, "VEG", "food2", 5)
    f(mdk_id, "Sea Food Thali", 340, "NON_VEG", "food3", 25)

    f(ogc_id, "Vegetable Soup", 80, "VEG", "food2", 15)
    f(ogc_id, "Veg Noodles", 140, "VEG", "food5", 18)
    f(ogc_id, "Hot Chocolate", 120, "BEVERAGE", "coffee1", 10)
    f(ogc_id, "Roast Chicken", 260, "NON_VEG", "food1", 25)
    f(ogc_id, "Mixed Veg Curry", 150, "VEG", "veg", 20)

    f(mlb_id, "Fish Curry Meal", 180, "NON_VEG", "food3", 20)
    f(mlb_id, "Appam with Stew", 150, "VEG", "food4", 15)
    f(mlb_id, "Kerala Meals", 160, "VEG", "food5", 10)
    f(mlb_id, "Puttu & Kadala", 110, "VEG", "breakfast2", 12)
    f(mlb_id, "Porotta with Beef", 190, "NON_VEG", "food1", 18)
    return [ann_id, csj_id, mdk_id, ogc_id, mlb_id]


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
    mht = uid["spot.mysuruheritage@tripmind.demo"]
    kbw = uid["spot.backwater@tripmind.demo"]

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
    spots["ooty"] = _upsert_spot({
        "ownerId": ngs, "name": "Ooty Lake", "city": "Ooty", "category": "NATURE",
        "location": {"name": "Ooty Lake, Ooty", "address": "Lake Road, Ooty 643001",
                     "lat": 11.4065, "lng": 76.6506, "city": "Ooty",
                     "district": "The Nilgiris", "state": "Tamil Nadu", "country": "India"},
        "description": "Boating lake and gardens surrounded by eucalyptus and pine hills in the Nilgiri Blue Mountains.",
        "entryFee": 20.0, "openingTime": "09:00", "closingTime": "18:00",
        "recommendedTimes": _slots([("06:00", "09:00"), ("09:00", "12:00"), ("12:00", "15:00"),
                                    ("15:00", "18:00"), ("18:00", "21:00")]),
        "optimalTimes": _slots([("06:00", "09:00"), ("09:00", "12:00"), ("12:00", "15:00"),
                                ("15:00", "18:00"), ("18:00", "21:00")]),
        "workingDays": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
        "popularity": 88, "visitingTravelers": 700,
        "images": [img_url("lake"), img_url("lake_mtn"), img_url("mountain_night"),
                   img_url("himalaya"), img_url("nature1")],
        "status": "APPROVED",
    })
    spots["mysuru"] = _upsert_spot({
        "ownerId": mht, "name": "Mysore Palace", "city": "Mysuru", "category": "HERITAGE",
        "location": {"name": "Mysore Palace", "address": "Sayyaji Rao Road, Mysuru 570001",
                     "lat": 12.3052, "lng": 76.6551, "city": "Mysuru",
                     "district": "Mysuru", "state": "Karnataka", "country": "India"},
        "description": "The resplendent residence of the Wadiyar dynasty, famed for its Indo-Saracenic architecture and 97,000 electric bulbs that light it every Sunday.",
        "entryFee": 70.0, "openingTime": "10:00", "closingTime": "17:30",
        "recommendedTimes": _slots([("06:00", "09:00"), ("09:00", "12:00"), ("12:00", "15:00"),
                                    ("15:00", "18:00"), ("18:00", "21:00")]),
        "optimalTimes": _slots([("06:00", "09:00"), ("09:00", "12:00"), ("12:00", "15:00"),
                                ("15:00", "18:00"), ("18:00", "21:00")]),
        "workingDays": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
        "popularity": 97, "visitingTravelers": 1500,
        "images": [img_url("rajasthan_fort"), img_url("taj"), img_url("hawa_mahal"),
                   img_url("bar1"), img_url("street_india")],
        "status": "APPROVED",
    })
    spots["alleppey"] = _upsert_spot({
        "ownerId": kbw, "name": "Alappuzha Backwaters", "city": "Alappuzha", "category": "NATURE",
        "location": {"name": "Alappuzha Backwaters", "address": "Alappuzha Boat Jetty, Alappuzha 688012",
                     "lat": 9.4981, "lng": 76.3388, "city": "Alappuzha",
                     "district": "Alappuzha", "state": "Kerala", "country": "India"},
        "description": "Venice of the East — a serene lattice of canals, lagoons and palm-fringed backwaters best experienced on a houseboat.",
        "entryFee": 0.0, "openingTime": "08:00", "closingTime": "18:00",
        "recommendedTimes": _slots([("06:00", "09:00"), ("09:00", "12:00"), ("12:00", "15:00"),
                                    ("15:00", "18:00"), ("18:00", "21:00")]),
        "optimalTimes": _slots([("06:00", "09:00"), ("09:00", "12:00"), ("12:00", "15:00"),
                                ("15:00", "18:00"), ("18:00", "21:00")]),
        "workingDays": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
        "popularity": 90, "visitingTravelers": 850,
        "images": [img_url("houseboat"), img_url("beach1"), img_url("nature1"),
                   img_url("lake"), img_url("goa_beach")],
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
        "spotId": spots["mamallapuram"], "ownerId": sln,
        "name": "Shore Temple Heritage Trail", "description": "In-depth guided trail of the Shore Temple, Five Rathas and Arjuna's Penance with a certified historian.",
        "duration": 3.0, "cost": 500, "maxParticipants": 12, "bookedParticipants": 0,
        "availableTimes": _slots([("07:00", "10:00"), ("15:00", "18:00")]),
        "includedServices": ["Certified guide", "Entry tickets"], "guideRequired": True, "status": "APPROVED",
    }))
    tours_out.append(_upsert_tour({
        "spotId": spots["ooty"], "ownerId": ngs,
        "name": "Lake Boating & Gardens Walk", "description": "Row-boat ride on Ooty Lake followed by a walk through the Government Botanical Gardens.",
        "duration": 2.5, "cost": 350, "maxParticipants": 10, "bookedParticipants": 0,
        "availableTimes": _slots([("09:00", "11:30"), ("14:00", "16:30")]),
        "includedServices": ["Boat ride", "Entry tickets"], "guideRequired": False, "status": "APPROVED",
    }))
    tours_out.append(_upsert_tour({
        "spotId": spots["mysuru"], "ownerId": mht,
        "name": "Royal Palace Evening Illumination", "description": "Evening tour ending with the palace light-and-sound illumination of the 97,000 bulbs.",
        "duration": 3.0, "cost": 450, "maxParticipants": 25, "bookedParticipants": 0,
        "availableTimes": _slots([("15:00", "18:00"), ("18:00", "21:00")]),
        "includedServices": ["Guide narration", "Entry tickets"], "guideRequired": True, "status": "APPROVED",
    }))
    tours_out.append(_upsert_tour({
        "spotId": spots["alleppey"], "ownerId": kbw,
        "name": "Backwater Houseboat Cruise", "description": "Half-day cruise through the Alappuzha canals with a traditional Kerala lunch on board.",
        "duration": 4.0, "cost": 900, "maxParticipants": 8, "bookedParticipants": 0,
        "availableTimes": _slots([("12:00", "16:00"), ("16:00", "20:00")]),
        "includedServices": ["Houseboat", "Veg lunch"], "guideRequired": False, "status": "APPROVED",
    }))

    # Guide locations derived from the spots (Tourist Spot Admins manage these).
    _upsert_guide_location({"name": "Chennai", "city": "Chennai",
                            "spots": [spots["marina"]], "approved": True, "createdBy": htn})
    _upsert_guide_location({"name": "Mahabalipuram", "city": "Mahabalipuram",
                            "spots": [spots["mamallapuram"]], "approved": True, "createdBy": sln})
    _upsert_guide_location({"name": "Ooty", "city": "Ooty",
                            "spots": [spots["ooty"]], "approved": True, "createdBy": ngs})
    _upsert_guide_location({"name": "Mysuru", "city": "Mysuru",
                            "spots": [spots["mysuru"]], "approved": True, "createdBy": mht})
    _upsert_guide_location({"name": "Alappuzha", "city": "Alappuzha",
                            "spots": [spots["alleppey"]], "approved": True, "createdBy": kbw})

    return spots, tours_out


# ---------------------------------------------------------------------------
# Guides: pricing + locked weekly availability
# ---------------------------------------------------------------------------

def seed_guides(uid):
    gids = {
        "arun": uid["guide.arun@tripmind.demo"],
        "meera": uid["guide.meera@tripmind.demo"],
        "bhuvana": uid["guide.bhuvana@tripmind.demo"],
        "thomas": uid["guide.thomas@tripmind.demo"],
        "kavya": uid["guide.kavya@tripmind.demo"],
    }
    cities = {
        "arun": "Chennai", "meera": "Mahabalipuram", "bhuvana": "Ooty",
        "thomas": "Alappuzha", "kavya": "Mysuru",
    }
    pricing = [
        ("arun", 800, 4500, "Chennai Heritage — Fort St. George, Kapaleeshwarar, San Thome"),
        ("meera", 700, 4000, "Mahabalipuram History — Shore Temple, Five Rathas, sculpting streets"),
        ("bhuvana", 650, 3800, "Ooty Nature — Botanical Gardens, Doddabetta, tea estates"),
        ("thomas", 750, 4200, "Kerala Backwaters — Alappuzha canals, village life, houseboats"),
        ("kavya", 700, 4000, "Mysuru Heritage — Palace, Chamundi Hill, heritage walks"),
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

        # Locked weekly availability for the coming 6 weeks.
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
        print("TripMind AI — development/test seed")
        print("=" * 70)
    ensure_unique_indexes()  # idempotent
    uid = seed_users()
    if verbose:
        print("\n[users] 25 resource accounts synced (password = 'password')")
    seed_transports(uid)
    seed_hotels(uid)
    seed_restaurants(uid)
    seed_spots(uid)
    _, avail = seed_guides(uid)
    if verbose:
        print("[guides] 5 guide pricing profiles + %d locked weeks of availability" % avail)
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
        "transport_admins": by_role.get("Transport Admin", 0),
        "hotel_admins": by_role.get("Hotel Admin", 0),
        "restaurant_admins": by_role.get("Restaurant Admin", 0),
        "travel_spot_admins": by_role.get("Travel Spot Admin", 0),
        "guides": by_role.get("Guide", 0),
        "system_admins": users.count_documents({"role": "ADMIN"}),
        "transports": count("transports"),
        "transports_approved": count("transports", {"status": "APPROVED"}),
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
        ("Transport Admin accounts", summary["transport_admins"]),
        ("Hotel Admin accounts", summary["hotel_admins"]),
        ("Restaurant Admin accounts", summary["restaurant_admins"]),
        ("Travel Spot Admin accounts", summary["travel_spot_admins"]),
        ("Guide accounts", summary["guides"]),
        ("System Admin accounts", summary["system_admins"]),
        ("Transports (approved)", "%d (%d)" % (summary["transports"], summary["transports_approved"])),
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