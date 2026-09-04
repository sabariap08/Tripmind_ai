import random
from datetime import datetime, timedelta


AIRLINES = [
    {"name": "Emirates", "code": "EK", "rating": 4.8},
    {"name": "Singapore Airlines", "code": "SQ", "rating": 4.9},
    {"name": "Qatar Airways", "code": "QR", "rating": 4.7},
    {"name": "IndiGo", "code": "6E", "rating": 4.2},
    {"name": "Air India", "code": "AI", "rating": 4.0},
    {"name": "Lufthansa", "code": "LH", "rating": 4.6},
    {"name": "British Airways", "code": "BA", "rating": 4.5},
    {"name": "Thai Airways", "code": "TG", "rating": 4.4},
]

INTERNATIONAL_PRICES = {
    "new york": 45000, "london": 38000, "dubai": 22000,
    "singapore": 25000, "tokyo": 52000, "paris": 42000,
    "bangkok": 18000, "sydney": 55000,
}

DOMESTIC_PRICES = {
    "mumbai": 5000, "delhi": 4500, "bangalore": 4000,
    "chennai": 3500, "kolkata": 5500, "hyderabad": 3800,
    "goa": 4200, "jaipur": 4800,
}

STYLE_MULTIPLIERS = {"BUDGET": 0.7, "BALANCED": 1.0, "PREMIUM": 1.5}
CLASS_MAP = {"BUDGET": "Economy", "BALANCED": "Premium Economy", "PREMIUM": "Business"}


def search_flights(origin, destination, date, travel_style="BALANCED", count=5):
    dest_lower = destination.lower()
    base_price = INTERNATIONAL_PRICES.get(dest_lower)
    if base_price is None:
        base_price = 30000
    domestic_dests = list(DOMESTIC_PRICES.keys())
    is_domestic = any(d in dest_lower for d in domestic_dests)
    if is_domestic:
        base_price = DOMESTIC_PRICES.get(dest_lower, 5000)

    multiplier = STYLE_MULTIPLIERS.get(travel_style, 1.0)
    flight_class = CLASS_MAP.get(travel_style, "Economy")

    flights = []
    for i in range(count):
        airline = random.choice(AIRLINES)
        duration_h = random.randint(2, 4) if is_domestic else random.randint(8, 18)
        duration_m = random.randint(0, 59)
        price = int(base_price * multiplier * random.uniform(0.85, 1.15))
        dep_hour = random.randint(5, 23)
        dep_min = random.choice([0, 15, 30, 45])
        dep_time = datetime.combine(date, datetime.min.time().replace(hour=dep_hour, minute=dep_min))
        arr_time = dep_time + timedelta(hours=duration_h, minutes=duration_m)

        flights.append({
            "id": f"flight-{i+1}",
            "airline": airline["name"],
            "flightNumber": f"{airline['code']}-{random.randint(100, 9999)}",
            "departureAirport": origin[:3].upper(),
            "arrivalAirport": destination[:3].upper(),
            "departureTime": dep_time.isoformat(),
            "arrivalTime": arr_time.isoformat(),
            "duration": f"{duration_h}h {duration_m}m",
            "durationMinutes": duration_h * 60 + duration_m,
            "price": price,
            "currency": "INR",
            "travelClass": flight_class,
            "stops": 0 if duration_h < 6 else random.choice([0, 1]),
            "rating": airline["rating"],
        })

    flights.sort(key=lambda x: x["price"])
    return flights
