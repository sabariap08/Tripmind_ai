"""Date-based, AI-assisted pre-trip checklist with persistence.

Behaviour
---------
* A checklist is generated per booking, persisted in ``checklists``, and
  regenerated on demand. Every item carries a ``dueOffsetDays`` so the UI can
  group items into 7 days / 1 day / travel day / on trip.
* The AI is asked for a strict JSON array. If no LLM backend is available, or
  the reply cannot be parsed, a curated deterministic template is used instead -
  the traveller is never left with an empty checklist and we never fake an "AI"
  result. ``source`` records which path produced the list.
* Regeneration preserves the traveller's tick marks: items are matched on their
  normalised text so completed work is not thrown away.
* Privacy: only the non-identifying party summary from
  ``passenger_service.to_ai_context`` is sent to the model. Names, ages in
  years, health free text, contact details and ID proof never appear in the
  prompt.
"""
import json
import re
from datetime import datetime, timedelta, date

from config import ROLES
from services.mongodb import get_collection
from services import passenger_service
from services.ai_service import call_ai

CATEGORIES = ("BOOKING", "DOCUMENTS", "PACKING", "MONEY", "HEALTH",
              "TRANSPORT", "LOCAL", "SAFETY", "OTHER")

# dueOffsetDays semantics: days BEFORE the travel date.
OFFSET_7 = 7
OFFSET_1 = 1
OFFSET_0 = 0            # travel day
OFFSET_POSITIVE = 1     # during the trip (rendered separately)

SOURCE_AI = "AI"
SOURCE_TEMPLATE = "TEMPLATE"

_SYSTEM_PROMPT = (
    "You create short, practical pre-trip packing and preparation checklists "
    "for travellers in Tamil Nadu, India. Reply with ONLY a JSON array. "
    "Each element must be an object with exactly the keys "
    '"text" (string, max 90 chars), "category" (one of BOOKING, DOCUMENTS, '
    'PACKING, MONEY, HEALTH, TRANSPORT, LOCAL, SAFETY, OTHER) and '
    '"dueOffsetDays" (integer: 7 for a week before, 1 the day before, '
    '0 on the travel day, or 1 for on-trip items). Produce between 8 and 16 '
    "items. Be specific to the destination and transport mode. "
    "Never invent visa or permit requirements. No markdown, no commentary."
)


def _now():
    return datetime.utcnow().isoformat()


def _parse_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _norm(text):
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


# ---------------------------------------------------------------------------
# Deterministic fallback
# ---------------------------------------------------------------------------
def template_items(context):
    """Curated baseline. Used when the LLM is unavailable or unparseable, and as
    the seed set that AI output is merged into so the traveller is never
    missing a core item (ID proofs, cancellations, emergency numbers)."""
    mode = (context.get("transportType") or "").upper()
    city = context.get("city") or "your destination"
    items = [
        ("Confirm your booking reference and save it offline", "BOOKING", OFFSET_7),
        ("Check the cancellation and reschedule policy", "BOOKING", OFFSET_7),
        ("Carry a government photo ID for every traveller", "DOCUMENTS", OFFSET_7),
        ("Download offline copies of tickets and hotel booking", "DOCUMENTS", OFFSET_1),
        ("Pack medicines and a basic first-aid kit", "HEALTH", OFFSET_7),
        ("Keep an emergency contact number saved on your phone", "SAFETY", OFFSET_7),
        ("Charge your phone and pack a power bank", "PACKING", OFFSET_1),
        ("Carry some cash for small vendors and emergencies", "MONEY", OFFSET_1),
        ("Check the weather forecast for %s" % city, "PACKING", OFFSET_1),
        ("Note the local emergency numbers for the area", "SAFETY", OFFSET_1),
    ]
    if mode in ("BUS", "CAB", "AUTO", "TRAIN", "FLIGHT"):
        items += [
            ("Arrive at the boarding point 30 minutes early", "TRANSPORT", OFFSET_0),
            ("Keep your ticket and ID ready at the boarding gate", "TRANSPORT", OFFSET_0),
        ]
    if mode == "TRAIN":
        items.append(("Note your coach and berth/seat number", "TRANSPORT", OFFSET_1))
    if mode in ("BUS", "CAB", "AUTO", "FLIGHT"):
        items.append(("Save the driver's or operator's contact number", "TRANSPORT", OFFSET_1))
    if context.get("hasHotel"):
        items.append(("Carry your hotel booking confirmation and ID", "BOOKING", OFFSET_1))
    if context.get("hasRestaurant"):
        items.append(("Confirm your restaurant reservation time", "BOOKING", OFFSET_1))
    if context.get("hasMobilityNeed"):
        items.append(("Confirm step-free access at your accommodation", "SAFETY", OFFSET_7))
    if context.get("hasDietaryNeed"):
        items.append(("Share dietary requirements with the restaurant", "HEALTH", OFFSET_1))
    return [{"text": t, "category": c, "dueOffsetDays": o} for t, c, o in items if t]


# ---------------------------------------------------------------------------
# AI generation
# ---------------------------------------------------------------------------
def _build_prompt(context):
    lines = [
        "Create a pre-trip checklist for this journey.",
        "",
        "Destination: %s" % (context.get("city") or "Tamil Nadu, India"),
        "Travel date: %s" % (context.get("travelDate") or "not specified"),
        "Transport mode: %s" % (context.get("transportType") or "not specified"),
        "Party: %s" % _party_sentence(context.get("party") or {}),
        "Accommodation booked: %s" % ("yes" if context.get("hasHotel") else "no"),
        "Restaurant reservation: %s" % ("yes" if context.get("hasRestaurant") else "no"),
    ]
    lines.append("")
    lines.append("Return only the JSON array.")
    return "\n".join(lines)


def _party_sentence(party):
    if not party or not party.get("count"):
        return "1 traveller"
    count = party["count"]
    base = "%d traveller%s" % (count, "" if count == 1 else "s")
    bands = party.get("ageBands") or []
    friendly = [b for b in bands if b in ("CHILD", "INFANT", "SENIOR", "TEEN")]
    if friendly:
        base += " (party includes %s)" % ", ".join(b.lower() for b in friendly)
    if party.get("requirements"):
        base += ". Requirements: %s" % ", ".join(party["requirements"])
    return base


def _parse_ai_items(raw):
    if not raw:
        return []
    text = raw.strip()
    # Strip markdown fences if the model added them.
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S)
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end == -1 or end <= start:
        return []
    try:
        parsed = json.loads(text[start:end + 1])
    except (ValueError, TypeError):
        return []
    if not isinstance(parsed, list):
        return []
    items = []
    for entry in parsed[:24]:
        if not isinstance(entry, dict):
            continue
        label = (entry.get("text") or "").strip()
        if not label or len(label) > 140:
            continue
        category = (entry.get("category") or "OTHER").strip().upper()
        if category not in CATEGORIES:
            category = "OTHER"
        try:
            offset = int(entry.get("dueOffsetDays", OFFSET_1))
        except (TypeError, ValueError):
            offset = OFFSET_1
        offset = max(0, min(offset, 30))
        items.append({"text": label, "category": category, "dueOffsetDays": offset})
    return items


def _dedupe(items):
    seen = set()
    out = []
    for item in items:
        key = _norm(item["text"])
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _merge_with_core(ai_items, template):
    """Keep the AI's specificity but guarantee the core items exist."""
    merged = _dedupe(list(ai_items) + list(template))
    return merged


# ---------------------------------------------------------------------------
# Context assembly (privacy-preserving)
# ---------------------------------------------------------------------------
def build_context(owner_id, booking, passenger_ids=None):
    travel_date = booking.get("date") or booking.get("travelDate") or ""
    traveller_count = booking.get("travellers") or booking.get("seats") or 1
    try:
        traveller_count = max(1, int(traveller_count))
    except (TypeError, ValueError):
        traveller_count = 1

    # Party context comes from the booking's stored snapshot when present, so
    # re-generating a checklist months later cannot pull in newer health data.
    snapshot = booking.get("party") or {}
    if not snapshot and passenger_ids:
        docs, err = passenger_service.resolve_booking_party(
            owner_id, passenger_ids, traveller_count)
        if not err and docs:
            snapshot = passenger_service.to_public_party_view(docs)
    requirements = snapshot.get("requirements") or []

    return {
        "city": booking.get("city") or booking.get("destination")
                or booking.get("to") or booking.get("destinationCity") or "",
        "travelDate": travel_date,
        "transportType": booking.get("type") or booking.get("transportType") or "",
        "party": snapshot,
        "hasHotel": bool(booking.get("hotelId") or booking.get("hasHotel")),
        "hasRestaurant": bool(booking.get("restaurantId") or booking.get("hasRestaurant")),
        "hasMobilityNeed": "mobility_assistance" in requirements,
        "hasDietaryNeed": any(r for r in requirements
                              if r in ("vegetarian", "vegan", "halal", "jain",
                                       "kosher", "other")),
    }


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------
def _checklist_id(owner_id, booking_id):
    return "chk-%s-%s" % (owner_id, booking_id)


def due_date_for(travel_date, offset):
    travel = _parse_date(travel_date)
    if travel is None:
        return None
    return (travel - timedelta(days=int(offset or 0))).isoformat()


def _decorate(item, travel_date, index):
    """Add the stable id and due date an item needs to be tickable in the UI."""
    enriched = dict(item)
    enriched["id"] = "item-%d" % index
    enriched.setdefault("done", False)
    enriched.setdefault("doneAt", None)
    enriched["dueDate"] = due_date_for(travel_date, item.get("dueOffsetDays", 0))
    return enriched


def get_checklist(owner_id, booking_id):
    doc = get_collection("checklists").find_one(
        {"_id": _checklist_id(owner_id, booking_id), "ownerId": owner_id})
    if not doc:
        return None
    doc["id"] = str(doc["_id"])
    doc["daysUntil"] = _days_until(doc.get("travelDate"))
    return doc


def _days_until(travel_date):
    travel = _parse_date(travel_date)
    if travel is None:
        return None
    return (travel - date.today()).days


def list_checklists(owner_id):
    rows = list(get_collection("checklists").find({"ownerId": owner_id})
                .sort("travelDate", 1))
    for row in rows:
        row["id"] = str(row["_id"])
        row["daysUntil"] = _days_until(row.get("travelDate"))
    return rows


def _preserve_progress(previous_items, new_items):
    """Carry tick marks across a regeneration.

    Matching is on normalised text, so a reworded AI item still inherits its
    tick. Items the traveller had already completed that the new list does not
    mention at all are appended rather than dropped - regenerating must never
    silently discard work the traveller already did, nor a custom item they
    typed in.
    """
    done_map = {}
    completed = []
    for item in previous_items or []:
        key = _norm(item.get("text"))
        if not key:
            continue
        done_map[key] = (bool(item.get("done")), item.get("doneAt"))
        if item.get("done"):
            completed.append(item)

    for item in new_items:
        key = _norm(item.get("text"))
        if key in done_map:
            was_done, done_at = done_map[key]
            item["done"] = was_done
            item["doneAt"] = done_at
        else:
            item.setdefault("done", False)
            item.setdefault("doneAt", None)

    present = {_norm(i.get("text")) for i in new_items}
    for item in completed:
        if _norm(item.get("text")) not in present:
            carried = dict(item)
            carried.setdefault("done", True)
            carried.setdefault("doneAt", None)
            new_items.append(carried)
    return new_items


def generate_checklist(owner_id, booking, passenger_ids=None, regenerate=False):
    """Create or refresh the checklist for one booking.

    Returns ``(document, error)``."""
    booking_id = str(booking.get("_id") or booking.get("id") or booking.get("reference") or "")
    if not booking_id:
        return None, "This booking has no identifier, so a checklist cannot be created."

    existing = get_collection("checklists").find_one(
        {"_id": _checklist_id(owner_id, booking_id), "ownerId": owner_id})
    if existing and not regenerate:
        existing["id"] = str(existing["_id"])
        existing["daysUntil"] = _days_until(existing.get("travelDate"))
        return existing, None

    context = build_context(owner_id, booking, passenger_ids)
    template = template_items(context)

    ai_items = []
    source = SOURCE_TEMPLATE
    model_note = ""
    try:
        raw = call_ai(_build_prompt(context), _SYSTEM_PROMPT,
                      max_tokens=1200, temperature=0.4)
        ai_items = _parse_ai_items(raw)
        if ai_items:
            source = SOURCE_AI
        else:
            model_note = "The AI reply could not be parsed; a curated checklist was used."
    except Exception as exc:  # pragma: no cover - network dependent
        model_note = "AI checklist generation failed (%s); a curated checklist was used." % exc

    items = _merge_with_core(ai_items, template) if ai_items else template
    items = _preserve_progress(existing.get("items") if existing else None, items)

    travel_date = context["travelDate"]
    doc = {
        "_id": _checklist_id(owner_id, booking_id),
        "ownerId": owner_id,
        "bookingId": booking_id,
        "bookingReference": booking.get("reference") or "",
        "title": "Pre-trip checklist for %s" % (context["city"] or "your trip"),
        "travelDate": travel_date,
        "context": {
            "city": context["city"],
            "transportType": context["transportType"],
            "partySize": (context["party"] or {}).get("count", 1),
        },
        "source": source,
        "modelNote": model_note,
        "items": [_decorate(item, travel_date, i) for i, item in enumerate(items)],
        "generatedAt": _now(),
        "updatedAt": _now(),
    }
    if existing:
        doc["createdAt"] = existing.get("createdAt") or _now()
    else:
        doc["createdAt"] = _now()
    get_collection("checklists").replace_one(
        {"_id": doc["_id"], "ownerId": owner_id}, doc, upsert=True)
    doc["id"] = doc["_id"]
    doc["daysUntil"] = _days_until(travel_date)
    return doc, None


def set_item_state(owner_id, checklist_id, item_id, done):
    doc = get_collection("checklists").find_one(
        {"_id": str(checklist_id), "ownerId": owner_id})
    if not doc:
        return None, "Checklist not found."
    found = False
    for item in doc.get("items", []):
        if str(item.get("id")) == str(item_id):
            item["done"] = bool(done)
            item["doneAt"] = _now() if done else None
            found = True
            break
    if not found:
        return None, "Checklist item not found."
    doc["updatedAt"] = _now()
    get_collection("checklists").replace_one({"_id": doc["_id"]}, doc)
    doc["id"] = str(doc["_id"])
    doc["daysUntil"] = _days_until(doc.get("travelDate"))
    return doc, None


def add_custom_item(owner_id, checklist_id, text, category="OTHER", due_offset=1):
    label = (text or "").strip()
    if not label:
        return None, "Checklist item text is required."
    if len(label) > 140:
        return None, "Checklist item text must be under 140 characters."
    category = (category or "OTHER").strip().upper()
    if category not in CATEGORIES:
        category = "OTHER"
    try:
        offset = max(0, min(int(due_offset), 30))
    except (TypeError, ValueError):
        offset = 1
    doc = get_collection("checklists").find_one(
        {"_id": str(checklist_id), "ownerId": owner_id})
    if not doc:
        return None, "Checklist not found."
    doc.setdefault("items", []).append({
        "id": "custom-%d" % len(doc.get("items", [])),
        "text": label,
        "category": category,
        "dueOffsetDays": offset,
        "dueDate": due_date_for(doc.get("travelDate"), offset),
        "done": False,
        "doneAt": None,
        "custom": True,
    })
    doc["updatedAt"] = _now()
    get_collection("checklists").replace_one({"_id": doc["_id"]}, doc)
    doc["id"] = str(doc["_id"])
    doc["daysUntil"] = _days_until(doc.get("travelDate"))
    return doc, None


def remove_item(owner_id, checklist_id, item_id):
    doc = get_collection("checklists").find_one(
        {"_id": str(checklist_id), "ownerId": owner_id})
    if not doc:
        return None, "Checklist not found."
    before = len(doc.get("items", []))
    doc["items"] = [i for i in doc.get("items", []) if str(i.get("id")) != str(item_id)]
    if len(doc["items"]) == before:
        return None, "Checklist item not found."
    doc["updatedAt"] = _now()
    get_collection("checklists").replace_one({"_id": doc["_id"]}, doc)
    doc["id"] = str(doc["_id"])
    doc["daysUntil"] = _days_until(doc.get("travelDate"))
    return doc, None


def progress(doc):
    items = (doc or {}).get("items") or []
    total = len(items)
    done = sum(1 for i in items if i.get("done"))
    return {
        "total": total,
        "done": done,
        "percent": int(round(done * 100.0 / total)) if total else 0,
        "daysUntil": _days_until((doc or {}).get("travelDate")),
    }
