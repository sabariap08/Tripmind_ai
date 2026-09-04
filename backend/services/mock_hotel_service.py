import random
from datetime import datetime


HOTEL_TIERS = {
    "BUDGET": [
        {"name": "Budget Inn", "stars": 2, "multiplier": 0.5, "rating": 3.2},
        {"name": "Travelodge", "stars": 2, "multiplier": 0.6, "rating": 3.4},
    ],
    "BALANCED": [
        {"name": "Grand Plaza", "stars": 4, "multiplier": 1.0, "rating": 4.3},
        {"name": "City Center Hotel", "stars": 3, "multiplier": 0.8, "rating": 4.0},
        {"name": "Comfort Suites", "stars": 3, "multiplier": 0.9, "rating": 4.1},
    ],
    "PREMIUM": [
        {"name": "The Ritz-Carlton", "stars": 5, "multiplier": 2.0, "rating": 4.8},
        {"name": "Four Seasons", "stars": 5, "multiplier": 2.2, "rating": 4.9},
        {"name": "Mandarin Oriental", "stars": 5, "multiplier": 1.8, "rating": 4.7},
    ],
}

BASE_PRICE_PER_NIGHT = 5000

AMENITY_OPTIONS = [
    ["WiFi", "Parking"],
    ["WiFi", "Pool", "Gym"],
    ["WiFi", "Pool", "Spa", "Restaurant"],
    ["WiFi", "Pool", "Spa", "Restaurant", "Room Service", "Concierge"],
    ["WiFi", "Pool", "Spa", "Restaurant", "Room Service", "Concierge", "Airport Shuttle", "Business Center"],
]


def search_hotels(destination, check_in, check_out, travel_style="BALANCED", count=3):
    nights = max(1, (check_out - check_in).days)
    tiers = HOTEL_TIERS.get(travel_style, HOTEL_TIERS["BALANCED"])

    hotels = []
    for i, tier in enumerate(tiers):
        if i >= count:
            break
        base = BASE_PRICE_PER_NIGHT * tier["multiplier"]
        price_per_night = int(base * random.uniform(0.9, 1.1))
        total_price = price_per_night * nights
        amenities_idx = min(tier["stars"] - 2, len(AMENITY_OPTIONS) - 1)

        hotels.append({
            "id": f"hotel-{i+1}",
            "name": tier["name"],
            "stars": tier["stars"],
            "pricePerNight": price_per_night,
            "totalPrice": total_price,
            "currency": "INR",
            "rating": tier["rating"] + random.uniform(-0.1, 0.1),
            "amenities": AMENITY_OPTIONS[max(0, amenities_idx)],
            "distanceFromCenter": round(random.uniform(0.5, 8.0), 1),
            "checkIn": check_in.isoformat(),
            "checkOut": check_out.isoformat(),
            "nights": nights,
            "roomType": "Deluxe Room" if tier["stars"] >= 4 else "Standard Room",
        })

    hotels.sort(key=lambda x: x["pricePerNight"])
    return hotels
