"""Seed synthetic historical data for ML models.

Generates realistic past trips, itineraries, and delay events so the ML
models have sensible baselines from day one. Run this once before training:

    python scripts/seed_ml_data.py

This only adds data under the `ml_seed_*` collections / flags so it can be
distinguished from real usage.
"""
import sys
import os
import random
import json
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.mongodb import get_db
from services.ml import cost_model, timing_model, delay_model

ORIGINS = ["Coimbatore", "Chennai", "Mumbai", "Delhi", "Bangalore", "Kolkata", "Hyderabad", "Goa"]
DOMESTIC = ["Mumbai", "Delhi", "Bangalore", "Chennai", "Goa", "Jaipur", "Kolkata"]
INTERNATIONAL = ["New York", "London", "Dubai", "Singapore", "Tokyo", "Paris", "Bangkok", "Sydney"]
STYLES = ["BUDGET", "BALANCED", "PREMIUM"]

# Realistic base prices (roughly matching mock services)
INTL_BASE = {"New York": 45000, "London": 38000, "Dubai": 22000, "Singapore": 25000,
             "Tokyo": 52000, "Paris": 42000, "Bangkok": 18000, "Sydney": 55000}
DOM_BASE = {"Mumbai": 5000, "Delhi": 4500, "Bangalore": 4000, "Chennai": 3500,
            "Kolkata": 5500, "Hyderabad": 3800, "Goa": 4200, "Jaipur": 4800}

STYLE_MULT = {"BUDGET": 0.7, "BALANCED": 1.0, "PREMIUM": 1.5}

AIRLINES_LONG = ["Emirates", "Singapore Airlines", "Qatar Airways", "Air India", "Lufthansa", "British Airways"]
AIRLINES_DOM = ["IndiGo", "Air India", "GoAir", "SpiceJet"]


def make_trip(i):
    origin = random.choice(ORIGINS)
    if random.random() < 0.5:
        dest = random.choice(INTERNATIONAL)
    else:
        dest = random.choice(DOMESTIC)
    if dest == origin:
        dest = random.choice(INTERNATIONAL)

    travelers = random.randint(1, 4)
    days = random.randint(2, 10)
    style = random.choice(STYLES)

    start = datetime.utcnow() - timedelta(days=random.randint(20, 400))
    end = start + timedelta(days=days - 1)

    dest_key = dest.lower()
    base_price = INTL_BASE.get(dest.capitalize()) or DOM_BASE.get(dest.capitalize(), 5000)
    if dest.lower() in [d.lower() for d in INTERNATIONAL]:
        base_price = INTL_BASE.get(dest.capitalize(), 30000)
    else:
        base_price = DOM_BASE.get(dest.capitalize(), 5000)

    flight_cost = int(base_price * STYLE_MULT[style] * random.uniform(0.85, 1.15))
    hotel_per_night = int((3000 if style == "BUDGET" else 5000 if style == "BALANCED" else 9000) * random.uniform(0.9, 1.1))
    hotel_cost = hotel_per_night * days
    food_per_day = 1000 if style == "BUDGET" else 1500 if style == "BALANCED" else 2500
    food_cost = food_per_day * days
    activity_cost = random.randint(1500, 6000)
    transport_cost = random.randint(1000, 4000)

    total_cost = flight_cost + hotel_cost + food_cost + activity_cost + transport_cost
    budget = int(total_cost * random.uniform(1.1, 1.6))

    return {
        "_id": f"seed-trip-{i}",
        "userId": "ml-seed",
        "origin": origin,
        "destination": dest,
        "startDate": start.isoformat(),
        "endDate": end.isoformat(),
        "travelers": travelers,
        "budget": budget,
        "currency": "INR",
        "travelStyle": style,
        "status": random.choice(["PLANNED", "BOOKED"]),
        "totalEstimatedCost": total_cost,
        "createdAt": start.isoformat(),
        "updatedAt": start.isoformat(),
        "itineraries": [],
        "bookings": [],
        "events": [],
        "recommendations": [],
    }


def make_events(trip):
    events = []
    if random.random() < 0.25:
        minutes = random.choice([60, 120, 180, 240, 300, 360, 480])
        severity = "LOW" if minutes < 120 else ("MEDIUM" if minutes < 300 else "HIGH")
        events.append({
            "_id": f"seed-event-{trip['_id']}",
            "tripId": trip["_id"],
            "type": "FLIGHT_DELAY",
            "title": f"Flight Delay - {minutes} minutes",
            "description": f"Historical delay of {minutes} minutes",
            "severity": severity,
            "occurredAt": trip["startDate"],
            "resolvedAt": None,
        })
    return events


def seed():
    db = get_db()
    now = datetime.utcnow().isoformat()

    # Guard: never duplicate the seed into training if it already ran.
    existing = db["ml_seed"].find_one({"type": "seeded"})
    if existing:
        print("ML seed data already exists. Skipping (re-run train_all to retrain).")
        return False

    print(f"Generating {NUM_TRIPS} seed trips...")
    for i in range(NUM_TRIPS):
        trip = make_trip(i)
        # Build a light itinerary with items for timing model
        trip["itineraries"] = [make_itinerary(trip)]
        trip["events"] = make_events(trip)
        db["trips"].update_one(
            {"_id": trip["_id"]},
            {"$set": trip},
            upsert=True,
        )

    print("Recording ML training samples...")
    # Cost samples
    for t in db["trips"].find({"_id": {"$regex": "^seed-trip-"}}):
        itin_total = 0
        for it in t.get("itineraries", []):
            itin_total += it.get("totalCost", 0)
        label = itin_total or t.get("totalEstimatedCost", 0)
        if label:
            db["ml_training_samples"].insert_one({
                "type": "cost",
                "features": t,
                "label": label,
                "createdAt": now,
            })
        # Timing samples from items
        for it in t.get("itineraries", []):
            for item in it.get("items", []):
                if item.get("startTime") and item.get("endTime"):
                    db["ml_training_samples"].insert_one({
                        "type": "timing",
                        "itemType": item["type"],
                        "durationMinutes": item.get("durationMinutes", 60),
                        "createdAt": now,
                    })
        # Delay outcomes
        route = f"{t['origin'].strip().lower()}|{t['destination'].strip().lower()}"
        delayed = len(t.get("events", [])) > 0
        minutes = 0
        airline = None
        for ev in t.get("events", []):
            minutes = _sev_minutes(ev.get("severity"))
        # capture a plausible airline
        for it in t.get("itineraries", []):
            for item in it.get("items", []):
                if item.get("type") == "FLIGHT":
                    airline = item.get("provider")
        db["ml_training_samples"].insert_one({
            "type": "delay",
            "route": route,
            "airline": (airline or "").lower(),
            "delayHappened": delayed,
            "delayMinutes": minutes,
            "createdAt": now,
        })

    db["ml_seed"].insert_one({"type": "seeded", "createdAt": now})
    print("Seeding complete.")
    return True


def make_itinerary(trip):
    """Create a small itinerary with realistic items + durations for timing training."""
    days = max(1, (datetime.fromisoformat(trip["endDate"]) - datetime.fromisoformat(trip["startDate"])).days + 1)
    items = []
    idx = 0
    for d in range(1, days + 1):
        day_date = datetime.fromisoformat(trip["startDate"]) + timedelta(days=d - 1)
        if d == 1:
            items.append({
                "type": "TRANSFER", "title": "Home to Airport",
                "startTime": day_date.replace(hour=6, minute=0).isoformat(),
                "endTime": day_date.replace(hour=7, minute=30).isoformat(),
                "durationMinutes": 90, "cost": 500,
            })
            items.append({
                "type": "FLIGHT", "title": "Flight",
                "provider": random.choice(AIRLINES_LONG if trip["destination"].lower() in [d.lower() for d in INTERNATIONAL] else AIRLINES_DOM),
                "startTime": day_date.replace(hour=9, minute=0).isoformat(),
                "endTime": (day_date.replace(hour=9, minute=0) + timedelta(hours=6)).isoformat(),
                "durationMinutes": 360, "cost": trip["totalEstimatedCost"] * 0.4,
            })
        elif d == days:
            items.append({
                "type": "TRANSFER", "title": "Hotel to Airport",
                "startTime": day_date.replace(hour=10, minute=0).isoformat(),
                "endTime": day_date.replace(hour=11, minute=30).isoformat(),
                "durationMinutes": 90, "cost": 400,
            })
        else:
            items.append({
                "type": "FOOD", "title": "Breakfast",
                "startTime": day_date.replace(hour=8, minute=0).isoformat(),
                "endTime": day_date.replace(hour=9, minute=0).isoformat(),
                "durationMinutes": 60, "cost": 400,
            })
            items.append({
                "type": "ACTIVITY", "title": "City Tour",
                "startTime": day_date.replace(hour=10, minute=0).isoformat(),
                "endTime": day_date.replace(hour=13, minute=0).isoformat(),
                "durationMinutes": 180, "cost": 1500,
            })
        idx += 1
    return {
        "_id": f"seed-itin-{trip['_id']}",
        "tripId": trip["_id"],
        "version": 1,
        "status": "AVAILABLE",
        "totalCost": trip["totalEstimatedCost"],
        "generatedBy": "AI",
        "planType": trip["travelStyle"],
        "reasoning": [],
        "createdAt": trip["createdAt"],
        "items": items,
        "optimizationScore": 0.6,
        "comfortScore": 0.6,
        "travelTime": "6h",
    }


def _sev_minutes(sev):
    return 300 if sev == "HIGH" else 200 if sev == "MEDIUM" else 90


NUM_TRIPS = 200


if __name__ == "__main__":
    seeded = seed()
    if seeded:
        print("\nNow run the trainer:")
        print("  python -m services.ml.trainer  (or via trainer.train_all())")
