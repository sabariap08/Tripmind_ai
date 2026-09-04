import random


CITY_ACTIVITIES = {
    "new york": [
        {"title": "Statue of Liberty Tour", "category": "Sightseeing", "basePrice": 2500, "duration": "3 hours"},
        {"title": "Central Park Walk", "category": "Nature", "basePrice": 0, "duration": "2 hours"},
        {"title": "Times Square Exploration", "category": "Entertainment", "basePrice": 500, "duration": "2 hours"},
        {"title": "Broadway Show", "category": "Entertainment", "basePrice": 8000, "duration": "3 hours"},
        {"title": "Metropolitan Museum", "category": "Museum", "basePrice": 1500, "duration": "3 hours"},
    ],
    "london": [
        {"title": "Tower of London", "category": "Sightseeing", "basePrice": 3000, "duration": "3 hours"},
        {"title": "British Museum", "category": "Museum", "basePrice": 0, "duration": "2 hours"},
        {"title": "Thames River Cruise", "category": "Sightseeing", "basePrice": 2000, "duration": "1.5 hours"},
    ],
    "dubai": [
        {"title": "Burj Khalifa Visit", "category": "Sightseeing", "basePrice": 4000, "duration": "2 hours"},
        {"title": "Desert Safari", "category": "Adventure", "basePrice": 3500, "duration": "5 hours"},
        {"title": "Dubai Mall Shopping", "category": "Shopping", "basePrice": 1000, "duration": "3 hours"},
    ],
}

DEFAULT_ACTIVITIES = [
    {"title": "City Tour", "category": "Sightseeing", "basePrice": 1500, "duration": "4 hours"},
    {"title": "Local Museum Visit", "category": "Museum", "basePrice": 500, "duration": "2 hours"},
    {"title": "Nature Park Walk", "category": "Nature", "basePrice": 300, "duration": "2 hours"},
    {"title": "Street Food Tour", "category": "Food", "basePrice": 1000, "duration": "3 hours"},
]

FOOD_OPTIONS = [
    {"name": "Green Garden", "cuisine": "Vegetarian", "pricePerPerson": 500, "rating": 4.2, "dietary": ["vegetarian", "vegan"]},
    {"name": "Spice Garden", "cuisine": "Indian", "pricePerPerson": 700, "rating": 4.4, "dietary": ["vegetarian", "non-veg"]},
    {"name": "Ocean Basket", "cuisine": "Seafood", "pricePerPerson": 1200, "rating": 4.1, "dietary": ["non-veg"]},
    {"name": "Pasta Palace", "cuisine": "Italian", "pricePerPerson": 900, "rating": 4.3, "dietary": ["vegetarian", "non-veg"]},
    {"name": "Dragon Wok", "cuisine": "Chinese", "pricePerPerson": 800, "rating": 4.0, "dietary": ["vegetarian", "non-veg"]},
]


def search_activities(destination, count=4):
    dest_lower = destination.lower()
    activities = CITY_ACTIVITIES.get(dest_lower, DEFAULT_ACTIVITIES)
    result = []
    for i, act in enumerate(activities[:count]):
        result.append({
            "id": f"activity-{i+1}",
            "title": act["title"],
            "category": act["category"],
            "price": int(act["basePrice"] * random.uniform(0.9, 1.1)),
            "currency": "INR",
            "duration": act["duration"],
            "rating": round(random.uniform(3.8, 4.8), 1),
            "location": destination,
        })
    return result


def search_food(destination, food_preference=None, count=2):
    foods = []
    for i, opt in enumerate(FOOD_OPTIONS[:count]):
        if food_preference and "vegetarian" in food_preference.lower():
            if "vegetarian" not in opt["dietary"]:
                continue
        foods.append({
            "id": f"food-{i+1}",
            "name": opt["name"],
            "cuisine": opt["cuisine"],
            "pricePerPerson": int(opt["pricePerPerson"] * random.uniform(0.9, 1.1)),
            "currency": "INR",
            "rating": opt["rating"],
            "dietary": opt["dietary"],
        })
    if not foods:
        foods = [{
            "id": "food-1",
            "name": "Local Restaurant",
            "cuisine": "Mixed",
            "pricePerPerson": 600,
            "currency": "INR",
            "rating": 4.0,
            "dietary": ["vegetarian", "non-veg"],
        }]
    return foods
