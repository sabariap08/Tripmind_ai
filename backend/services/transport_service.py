"""Transport Admin data layer.

Covers the platform transport types (BUS / TRAIN / FLIGHT / CAB / AUTO; see
``config.TRANSPORT_TYPES``). Service name always comes from the transport
admin's profile — it is never asked for repeatedly on every vehicle.
"""
from datetime import datetime
from bson.objectid import ObjectId
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError
from config import TRANSPORT_TYPES
from services.mongodb import get_collection
from services import auth
from services import duplicate

BUS_SEAT_TYPES = ("SLEEPER", "SEATER")
DAY_RE = tuple(range(0, 30))

_NUMBER_FIELD = {
    "BUS": "busNumber",
    "TRAIN": "trainNumber",
    "FLIGHT": "flightNumber",
    "CAB": "vehicleNumber",
    "AUTO": "vehicleNumber",
}


def _serial_key(ttype, data):
    value = data.get(_NUMBER_FIELD.get(ttype, ""))
    return duplicate.normalize_serial(value) if value else ""


def _id():
    return str(ObjectId())


def _ok_user(user, target_owner_id):
    from services.auth import is_admin
    return is_admin(user) or user["id"] == target_owner_id


def service_name_for(owner_id):
    users = get_collection("users")
    u = users.find_one({"_id": owner_id})
    if u and u.get("profile", {}).get("serviceName"):
        return u["profile"]["serviceName"]
    return (u or {}).get("name", "Unnamed Service")


def set_service_profile(owner_id, data):
    """Transport admin company profile (service name lives here)."""
    upd = {"profile.serviceName": (data.get("serviceName") or "").strip(),
           "profile.cover": data.get("cover") or "",
           "profile.contact": data.get("contact") or "",
           "profile.description": data.get("description") or ""}
    get_collection("users").update_one({"_id": owner_id}, {"$set": upd})
    return get_collection("users").find_one({"_id": owner_id})["profile"]


def validate_transport(ttype, data):
    """Type-specific validation; returns (error|None)."""
    if ttype == "BUS":
        seats = data
        sleeper = int(seats.get("sleeperSeats") or 0)
        seater = int(seats.get("seaterSeats") or 0)
        total = int(seats.get("totalSeats") or 0)
        if sleeper + seater != total:
            return "Sleeper Seats + Seater Seats must equal Total Seats. ({} + {} != {})".format(
                sleeper, seater, total)
        if total <= 0:
            return "Total Seats must be greater than zero."
        if not data.get("busNumber") or not data.get("boardingPoint") or not data.get("droppingPoint"):
            return "Bus number and boarding/dropping points are required."
    elif ttype == "TRAIN":
        if not data.get("trainNumber") or not data.get("trainName"):
            return "Train number and name are required."
        if not data.get("boardingStation") or not data.get("destinationStation"):
            return "Boarding and destination stations are required."
        coaches = data.get("coaches") or []
        if not coaches:
            return "Add at least one coach type."
        for c in coaches:
            try:
                if int(c.get("coachCount") or 0) <= 0 or int(c.get("capacityPerCoach") or 0) <= 0:
                    return "Coach count and capacity must be greater than zero."
            except (TypeError, ValueError):
                return "Invalid coach capacity values."
    elif ttype == "FLIGHT":
        if not data.get("flightNumber") or not data.get("departureAirport") or not data.get("arrivalAirport"):
            return "Flight number and airports are required."
        if not data.get("classes") or not data["classes"]:
            return "Add at least one cabin class."
    elif ttype in ("CAB", "AUTO"):
        if not data.get("vehicleNumber"):
            return "Vehicle number is required."
        if not data.get("serviceArea"):
            return "Service area is required."
        fare = data.get("fare") or {}
        price_per_km = float(fare.get("pricePerKm") or fare.get("perKm") or 0)
        if price_per_km <= 0:
            return "CAB and AUTO must have a positive fare per km."
    elif ttype not in TRANSPORT_TYPES:
        return "Unknown transport type."
    return None


def stop_list(stops):
    out = []
    for s in stops or []:
        name = (s.get("name") or "").strip()
        if not name:
            continue
        out.append({
            "name": name,
            "day": int(s.get("day") or 0),
            "time": s.get("time") or "00:00",
        })
    return out


def _build(ttype, data, owner_id):
    svc = service_name_for(owner_id)
    base = {
        "_id": _id(),
        "ownerId": owner_id,
        "type": ttype,
        "status": "PENDING",
        "serviceName": svc,
        "images": data.get("images") or [],
        "documents": data.get("documents") or [],
        "bookedSeats": 0,
        "createdAt": datetime.utcnow().isoformat(),
        "updatedAt": datetime.utcnow().isoformat(),
        "rejectionReason": None,
    }
    if ttype == "BUS":
        base.update({
            "busNumber": data.get("busNumber"),
            "boardingPoint": data.get("boardingPoint"),
            "boardingDay": int(data.get("boardingDay") or 0),
            "boardingTime": data.get("boardingTime"),
            "droppingPoint": data.get("droppingPoint"),
            "droppingDay": int(data.get("droppingDay") or 0),
            "droppingTime": data.get("droppingTime"),
            "stops": stop_list(data.get("stops")),
            "seatTypes": [s for s in data.get("seatTypes") or [] if s in BUS_SEAT_TYPES],
            "totalSeats": int(data.get("totalSeats") or 0),
            "sleeperSeats": int(data.get("sleeperSeats") or 0),
            "seaterSeats": int(data.get("seaterSeats") or 0),
            "singleSeat": bool(data.get("singleSeat")),
            "doubleSeat": bool(data.get("doubleSeat")),
            "layout": data.get("layout"),  # optional seat-layout representation
            "fare": data.get("fare"),
        })
    elif ttype == "TRAIN":
        coaches = []
        for c in data.get("coaches") or []:
            cc = int(c.get("coachCount") or 0)
            cap = int(c.get("capacityPerCoach") or 0)
            coaches.append({
                "code": c.get("code", "SL"),
                "label": c.get("label", c.get("code", "")),
                "coachCount": cc,
                "capacityPerCoach": cap,
                "totalCapacity": cc * cap,
                "price": c.get("price"),
            })
        base.update({
            "trainNumber": data.get("trainNumber"),
            "trainName": data.get("trainName"),
            "boardingStation": data.get("boardingStation"),
            "destinationStation": data.get("destinationStation"),
            "totalCoaches": int(data.get("totalCoaches") or len(coaches)),
            "coaches": coaches,
            "stations": _station_list(data.get("stations")),
            "recurring": data.get("recurring") or [],
            "daysOfWeek": data.get("daysOfWeek") or [],
        })
    elif ttype == "FLIGHT":
        classes = []
        for cl in data.get("classes") or []:
            classes.append({
                "name": cl.get("name"),
                "seats": int(cl.get("seats") or 0),
                "price": cl.get("price"),
            })
        base.update({
            "flightNumber": data.get("flightNumber"),
            "airline": svc,
            "departureAirport": data.get("departureAirport"),
            "arrivalAirport": data.get("arrivalAirport"),
            "boardingDay": int(data.get("boardingDay") or 0),
            "boardingTime": data.get("boardingTime"),
            "arrivalDay": int(data.get("arrivalDay") or 0),
            "arrivalTime": data.get("arrivalTime"),
            "layoverAirport": data.get("layoverAirport"),
            "totalSeats": int(data.get("totalSeats") or 0),
            "classes": classes,
            "baggage": {"cabin": data.get("cabinBaggage"), "checkin": data.get("checkinBaggage")},
        })
    elif ttype in ("CAB", "AUTO"):
        fare = data.get("fare") or {}
        base_fare = float(fare.get("baseFare") or 0)
        price_per_km = float(fare.get("pricePerKm") or fare.get("perKm") or 0)
        minimum_fare = float(fare.get("minimum") or 0) or base_fare
        base.update({
            "vehicleNumber": data.get("vehicleNumber"),
            "vehicleType": data.get("vehicleType") or ttype,
            "seatingCapacity": int(data.get("seatingCapacity") or 0),
            "ac": bool(data.get("ac")),
            "driver": data.get("driver") or {},
            "serviceArea": data.get("serviceArea"),
            "baseLocation": data.get("baseLocation"),
            "availableTimings": data.get("availableTimings") or {},
            "fare": {
                "baseFare": base_fare,
                "pricePerKm": price_per_km,
                "minimum": minimum_fare,
            },
        })
    base["numberKey"] = _serial_key(ttype, data)
    return base


def _station_list(stations):
    out = []
    for s in stations or []:
        name = (s.get("name") or "").strip()
        if not name:
            continue
        out.append({
            "name": name,
            "day": int(s.get("day") or 0),
            "arrivalTime": s.get("arrivalTime") or "",
            "departureTime": s.get("departureTime") or "",
        })
    return out


def create_transport(ttype, data, owner_id):
    err = validate_transport(ttype, data)
    if err:
        return None, err
    key = _serial_key(ttype, data)
    if key and duplicate.transport_number_taken(_NUMBER_FIELD.get(ttype, ""), data.get(_NUMBER_FIELD.get(ttype, ""))):
        return None, ("A %s with this number (%s) is already registered."
                      % (ttype, data.get(_NUMBER_FIELD.get(ttype, ""))))
    doc = _build(ttype, data, owner_id)
    # Pending until Admin approves; resources created by Admin auto-approve.
    doc["status"] = auth.resource_status(owner_id)
    try:
        get_collection("transports").insert_one(doc)
    except DuplicateKeyError:
        return None, ("A %s with this number (%s) is already registered."
                      % (ttype, data.get(_NUMBER_FIELD.get(ttype, ""))))
    return doc, None


def update_transport(ttype, data, owner_id):
    doc = get_collection("transports").find_one({"_id": data.get("transportId")})
    if not doc:
        return None, "Transport not found."
    if not _ok_user(owner_id, doc["ownerId"]):
        return None, "Not authorized to edit this transport."
    err = validate_transport(ttype, data)
    if err:
        return None, err
    key = _serial_key(ttype, data)
    field = _NUMBER_FIELD.get(ttype, "")
    if key and duplicate.transport_number_taken(field, data.get(field), exclude_id=doc["_id"]):
        return None, ("Another %s with this number (%s) is already registered."
                      % (ttype, data.get(field)))
    new = _build(ttype, data, doc["ownerId"])
    new["_id"] = doc["_id"]
    new["status"] = doc.get("status", "PENDING")  # keep approval state on edit
    new["createdAt"] = doc["createdAt"]
    new["updatedAt"] = datetime.utcnow().isoformat()
    if doc.get("rejectionReason"):
        new["rejectionReason"] = doc["rejectionReason"]
    try:
        get_collection("transports").replace_one({"_id": doc["_id"]}, new)
    except DuplicateKeyError:
        return None, ("Another %s with this number (%s) is already registered."
                      % (ttype, data.get(field)))
    return new, None


def get_transport(tid):
    doc = get_collection("transports").find_one({"_id": tid})
    return doc


def list_transports(owner_id=None, status=None, ttype=None, approved_only=False):
    q = {}
    if owner_id:
        q["ownerId"] = owner_id
    if status:
        q["status"] = status
    if ttype:
        q["type"] = ttype
    if approved_only:
        q["status"] = "APPROVED"
    docs = list(get_collection("transports").find(q).sort("createdAt", -1))
    for d in docs:
        d["_id"] = d["_id"]
    return docs


def set_status(tid, status, reason=None):
    upd = {"status": status, "rejectionReason": reason or None,
           "updatedAt": datetime.utcnow().isoformat()}
    get_collection("transports").update_one({"_id": tid}, {"$set": upd})
    return get_transport(tid)


def available_transports(origin, destination, ttype=None):
    """Only APPROVED transports whose corridor matches origin->destination.

    Strict corridor first (origin before destination). If a direct match is not
    found, falls back to destination-only matching so hub departures (e.g. a
    Coimbatore→Chennai train for an origin of KPR) still surface within the
    connected travel flow.
    """
    q = {"status": "APPROVED"}
    if ttype:
        q["type"] = ttype
    docs = list(get_collection("transports").find(q))
    direct, dest_only = [], []
    for d in docs:
        corridor = _corridor(d)
        if not corridor:
            continue
        if origin and destination:
            if _match(corridor, origin, destination):
                direct.append(d)
            elif _match(corridor, destination, None) and not _match(corridor, origin, None):
                dest_only.append(d)
        elif origin:
            if _match(corridor, origin, None):
                direct.append(d)
        else:
            direct.append(d)
    return direct or dest_only


def _corridor(d):
    if d["type"] == "BUS":
        pts = [d.get("boardingPoint"), d.get("droppingPoint")] + [s["name"] for s in d.get("stops", [])]
        return [p for p in pts if p]
    if d["type"] == "TRAIN":
        pts = [d.get("boardingStation"), d.get("destinationStation")] + [s["name"] for s in d.get("stations", [])]
        return [p for p in pts if p]
    if d["type"] == "FLIGHT":
        return [d.get("departureAirport"), d.get("arrivalAirport")]
    if d["type"] in ("CAB", "AUTO"):
        return [d.get("baseLocation"), d.get("serviceArea")]
    return []


def _match(corridor, origin, destination):
    oc = [x for x in corridor if origin.lower().strip() in (x or "").lower().strip()]
    if not oc:
        return False
    origin_idx = corridor.index(oc[0])
    if destination is None:
        return True
    dc = [x for x in corridor if destination.lower().strip() in (x or "").lower().strip()]
    if not dc:
        return False
    return corridor.index(dc[0]) > origin_idx


# --- Capacity helpers (used by bookings) ---
def _capacity(transport):
    """Total booking capacity per transport type."""
    if transport["type"] == "TRAIN":
        return sum(int(c.get("totalCapacity") or 0) for c in transport.get("coaches") or [])
    if transport["type"] in ("CAB", "AUTO"):
        return int(transport.get("seatingCapacity") or transport.get("totalSeats") or 1)
    return int(transport.get("totalSeats") or 0)


def book_seats(transport, seat_type, qty, transport_id=None):
    """Atomically decrement capacity (guarded $inc so concurrent bookings can
    never overbook). Returns (ok, error)."""
    total = _capacity(transport)
    if total <= 0:
        return False, "This transport has no bookable capacity configured."
    qty = max(1, int(qty or 0))
    doc = get_collection("transports").find_one_and_update(
        {"_id": transport_id or transport["_id"],
         "bookedSeats": {"$lte": total - qty}},
        {"$inc": {"bookedSeats": qty}},
        return_document=ReturnDocument.AFTER,
    )
    if not doc:
        cur = int(get_collection("transports").find_one(
            {"_id": transport_id or transport["_id"]}).get("bookedSeats") or 0)
        return False, "Only %d seats available." % max(0, total - cur)
    return True, None


def release_seats(transport_id, qty):
    t = get_collection("transports").find_one({"_id": transport_id})
    if not t:
        return
    cur = max(0, int(t.get("bookedSeats") or 0) - (int(qty) or 0))
    get_collection("transports").update_one({"_id": transport_id}, {"$set": {"bookedSeats": cur}})