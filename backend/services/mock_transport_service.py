import random


TRANSPORT_OPTIONS = [
    {"type": "Uber", "icon": "🚗", "basePrice": 200, "perKm": 15, "durationPerKm": 2},
    {"type": "Ola", "icon": "🚗", "basePrice": 180, "perKm": 14, "durationPerKm": 2},
    {"type": "Local Taxi", "icon": "🚕", "basePrice": 150, "perKm": 12, "durationPerKm": 3},
    {"type": "Metro", "icon": "🚇", "basePrice": 50, "perKm": 5, "durationPerKm": 1.5},
    {"type": "Bus", "icon": "🚌", "basePrice": 30, "perKm": 3, "durationPerKm": 4},
    {"type": "Private Car", "icon": "🚘", "basePrice": 500, "perKm": 20, "durationPerKm": 2},
]

TRANSFER_TYPES = {
    "BUDGET": ["Metro", "Bus", "Local Taxi"],
    "BALANCED": ["Uber", "Ola", "Local Taxi"],
    "PREMIUM": ["Private Car", "Uber"],
}


def search_transport(origin, destination, count=3):
    distance = random.randint(5, 30)
    transports = []
    for i, opt in enumerate(TRANSPORT_OPTIONS[:count]):
        price = int(opt["basePrice"] + distance * opt["perKm"])
        duration = int(distance * opt["durationPerKm"])
        transports.append({
            "id": f"transport-{i+1}",
            "type": opt["type"],
            "icon": opt["icon"],
            "price": price,
            "currency": "INR",
            "duration": f"{duration} min",
            "durationMinutes": duration,
            "distance": distance,
        })
    return transports


def search_airport_transfer(airport, hotel, travel_style="BALANCED", count=2):
    allowed = TRANSFER_TYPES.get(travel_style, TRANSFER_TYPES["BALANCED"])
    distance = random.randint(15, 45)
    transfers = []
    for i, ttype in enumerate(allowed[:count]):
        opt = next((o for o in TRANSPORT_OPTIONS if o["type"] == ttype), TRANSPORT_OPTIONS[0])
        price = int(opt["basePrice"] + distance * opt["perKm"])
        duration = int(distance * opt["durationPerKm"])
        transfers.append({
            "id": f"transfer-{i+1}",
            "type": opt["type"],
            "icon": opt["icon"],
            "price": price,
            "currency": "INR",
            "duration": f"{duration} min",
            "durationMinutes": duration,
            "distance": distance,
        })
    return transfers
