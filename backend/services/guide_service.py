"""Guide data layer: profile, weekly locked availability calendar and pricing.

Availability is submitted per WEEK. Once a week is submitted it is locked:
the guide cannot resubmit or amend days inside that week. Bookings/re-planning
can only read availability, so a locked week is the single source of truth for
guide schedules.

Locations are plain service areas (the city declared at registration by
default) — there is no tourist-spot-authorization gate on where a guide works.
"""
import datetime
from datetime import datetime as dt
from bson.objectid import ObjectId
from services.mongodb import get_collection

STATUSES = ("ACTIVE", "BOOKED", "OFFLINE")


def _id():
    return str(ObjectId())


def _reg(registration, label):
    """Best-effort read of a registration field by fuzzy label match."""
    if not registration:
        return ""
    for key, val in registration.items():
        if label.lower() in str(key).lower():
            return str(val or "").strip()
    return ""


def _service_area(user_id):
    """The guide's city declared at registration (Base location)."""
    u = get_collection("users").find_one({"_id": user_id})
    area = _reg((u or {}).get("registration") or {}, "base location")
    if area:
        return area
    return _reg((u or {}).get("profile") or {}, "city")


def guide_profile(user_id):
    """Folded onto the users collection via profile."""

    def _(u):
        return {k: u.get(k) for k in ("name", "email")}

    u = get_collection("users").find_one({"_id": user_id})
    p = u.get("profile", {}) if u else {}
    reg = u.get("registration", {}) if u else {}
    profile = {
        "userId": user_id,
        "name": u.get("name") if u else None,
        "email": u.get("email") if u else None,
        "experience": p.get("experience") or _reg(reg, "experience") or 0,
        "description": p.get("description") or "",
        "languages": p.get("languages") or [],
        "specialty": p.get("specialty") or "",
        "city": p.get("city") or _reg(reg, "base location") or "",
        "rating": p.get("rating") or 0,
        "reviewCount": p.get("reviewCount") or 0,
        "status": p.get("status") or "ACTIVE",
        "registration": {
            "dob": _reg(reg, "date of birth") or _reg(reg, "dob"),
            "identificationType": _reg(reg, "identification type"),
            "identificationNumber": _reg(reg, "identification number"),
            "qualification": _reg(reg, "qualification"),
            "address": _reg(reg, "address"),
            "contactNumber": _reg(reg, "contact number"),
        },
    }
    availability = sorted(list(get_collection("guide_availability")
                               .find({"guideId": user_id})),
                          key=lambda d: d.get("weekStart", ""), reverse=True)
    pricing = list(get_collection("guide_pricing").find({"guideId": user_id}))
    return {"profile": profile, "availability": availability, "pricing": pricing}


def update_guide_profile(user_id, data):
    p = data.get("profile") or {}
    langs = [x for x in (p.get("languages") or []) if x]
    upd = {
        "profile.experience": int(p.get("experience") or 0),
        "profile.description": (p.get("description") or ""),
        "profile.languages": langs,
        "profile.specialty": (p.get("specialty") or ""),
        "profile.status": p.get("status") if p.get("status") in STATUSES else "ACTIVE",
    }
    get_collection("users").update_one({"_id": user_id}, {"$set": upd})
    return guide_profile(user_id)


def _parse_day(date_str):
    return dt.strptime((date_str or "").strip(), "%Y-%m-%d")


def _week_id(week_start):
    year = week_start.isocalendar()[0]
    week = week_start.isocalendar()[1]
    return "%04d-W%02d" % (year, week)


def _locked_weeks_overlap(user_id, week_start, week_end):
    return get_collection("guide_availability").find_one({
        "guideId": user_id,
        "locked": True,
        "weekStart": {"$lte": week_end},
        "weekEnd": {"$gte": week_start},
    })


def set_availability(user_id, data):
    """Weekly, lock-once availability.

    Payload options:
      {weekStart: "YYYY-MM-DD" (Monday), days: [
          {date: "YYYY-MM-DD", from, to, slots: [{from, to}], locations: [...]}]}
      {date: "YYYY-MM-DD", from, to, locations: [...]}   # legacy single-day

    A week is locked the moment it is submitted; the guide cannot amend it.
    """
    base_city = _service_area(user_id)
    epochs = {}

    def collection_(locations):
        locations = [x for x in (locations or []) if x]
        if not locations and base_city:
            locations = [base_city]
        if not locations:
            return None, "Select at least one location or your city as the service area."
        return locations, None

    def _slots_for(day_data):
        slots = []
        for s in day_data.get("slots") or []:
            if s.get("from") and s.get("to"):
                slots.append({"from": s.get("from"), "to": s.get("to")})
        if day_data.get("from") and day_data.get("to"):
            slots.append({"from": day_data["from"], "to": day_data["to"]})
        return slots

    # --- Normalize submitted days -------------------------------------------------
    if data.get("weekStart"):
        week_start = _parse_day(data["weekStart"])
        for d in data.get("days") or []:
            day_date = (d.get("date") or "").strip()
            if not day_date:
                continue
            locs, lerr = collection_(d.get("locations") or [])
            if lerr:
                return None, lerr
            slots = _slots_for(d)
            if not slots:
                continue
            epochs[day_date] = {"date": day_date,
                                "slots": slots,
                                "locations": locs}
        if not epochs:
            return None, "Add at least one day with a time slot for the week."
        # Only accept days that belong to that calendar week.
        week_end = week_start + datetime.timedelta(days=6)
        valid_days = [(week_start + datetime.timedelta(days=i)).strftime("%Y-%m-%d")
                      for i in range(7)]
        out_of_week = [d for d in epochs if d not in valid_days]
        if out_of_week:
            return None, "Days outside the selected week: " + ", ".join(out_of_week)
        week_end_str = week_end.strftime("%Y-%m-%d")
        week_id = _week_id(week_start)
        locked = _locked_weeks_overlap(
            user_id, week_start.strftime("%Y-%m-%d"), week_end_str)
        if locked:
            return None, ("This week (from %s) is already locked. Weekly "
                          "availability cannot be amended after submission."
                          % (locked.get("weekStart") or ""))
        locs = sorted({x for d in epochs.values() for x in d["locations"]})
        doc = {
            "_id": _id(),
            "guideId": user_id,
            "weekId": week_id,
            "weekStart": week_start.strftime("%Y-%m-%d"),
            "weekEnd": week_end_str,
            "days": [epochs[d] for d in valid_days if d in epochs],
            "locations": locs,
            "locked": True,
            "lockedAt": datetime.datetime.utcnow().isoformat(),
            "createdAt": datetime.datetime.utcnow().isoformat(),
        }
        get_collection("guide_availability").insert_one(doc)
        return doc, None

    # --- Legacy single-day submission (locked per week too) ------------------------
    date = (data.get("date") or "").strip()
    if not date:
        return None, "Provide weekStart with days, or a single date."
    d = _parse_day(date)
    week_start = d - datetime.timedelta(days=d.weekday())
    locked = _locked_weeks_overlap(user_id,
                                   week_start.strftime("%Y-%m-%d"),
                                   (week_start + datetime.timedelta(days=6)).strftime("%Y-%m-%d"))
    if locked:
        return None, ("The week containing %s is already locked. Weekly "
                      "availability cannot be amended after submission." % date)
    ok, err = collection_(data.get("locations") or [])
    if not ok:
        return None, err
    slots = _slots_for(data)
    if not slots:
        return None, "Add at least one time slot."
    week_end = week_start + datetime.timedelta(days=6)
    doc = {
        "_id": _id(),
        "guideId": user_id,
        "weekId": _week_id(week_start),
        "weekStart": week_start.strftime("%Y-%m-%d"),
        "weekEnd": week_end.strftime("%Y-%m-%d"),
        "days": [{"date": date, "slots": slots, "locations": ok}],
        "locations": sorted(ok),
        "locked": True,
        "lockedAt": datetime.datetime.utcnow().isoformat(),
        "createdAt": datetime.datetime.utcnow().isoformat(),
    }
    get_collection("guide_availability").insert_one(doc)
    # Sync assigned locations onto the guide profile so date-less browsing works.
    existing = set(get_collection("users").find_one({"_id": user_id}).get("profile", {}).get("locations") or [])
    merged = existing.union(doc["locations"])
    get_collection("users").update_one(
        {"_id": user_id}, {"$set": {"profile.locations": sorted(merged)}})
    return doc, None


def set_pricing(user_id, data):
    pc = (data.get("pricePerHour") or 0)
    pd = (data.get("pricePerDay") or 0)
    doc = {
        "_id": _id(),
        "guideId": user_id,
        "pricePerHour": float(pc),
        "pricePerDay": float(pd),
        "details": (data.get("details") or ""),
        "updatedAt": datetime.datetime.utcnow().isoformat(),
    }
    old = get_collection("guide_pricing").find_one({"guideId": user_id})
    if old:
        doc["_id"] = old["_id"]
        get_collection("guide_pricing").replace_one({"_id": old["_id"]}, doc)
    else:
        get_collection("guide_pricing").insert_one(doc)
    return doc, None


def availability_for_date(guide_id, date):
    av = get_collection("guide_availability").find_one(
        {"guideId": guide_id, "days.date": date, "locked": True})
    if not av:
        return None
    day = next((d for d in av.get("days", []) if d.get("date") == date), None)
    return day or None


def browse_guides(location=None, date=None):
    q = {"role": "GUIDE"}
    users = get_collection("users")
    guides = list(users.find(q))
    out = []
    for g in guides:
        prof = g.get("profile", {}) or {}
        service_city = _service_area(str(g["_id"]))
        eligible = ([service_city] if service_city else []) + (prof.get("locations") or [])
        if date:
            day = availability_for_date(str(g["_id"]), date)
            if not day or not day.get("slots"):
                continue
            eligible = eligible + (day.get("locations") or [])
            if location and not _loc_ok(location, eligible):
                continue
        elif location:
            if not (_loc_ok(location, eligible) or _loc_ok(location, [service_city])):
                continue
        price = get_collection("guide_pricing").find_one({"guideId": str(g["_id"])})
        rec = {
            "userId": str(g["_id"]),
            "name": g.get("name"),
            "profile": prof,
            "serviceArea": service_city,
        }
        rec["pricing"] = {"pricePerHour": price["pricePerHour"], "pricePerDay": price["pricePerDay"]} if price else {}
        out.append(rec)
    return out


def _loc_ok(requested, assigned):
    rl = (requested or "").lower().strip()
    for name in assigned:
        nl = (name or "").lower().strip()
        if nl and (nl == rl or rl in nl or nl in rl):
            return True
    return False