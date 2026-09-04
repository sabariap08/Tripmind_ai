from datetime import datetime
from services.mongodb import get_collection


def handle_ai_chat(trip_id, message):
    msg_lower = message.lower()
    trip = None
    if trip_id:
        trip = get_collection("trips").find_one({"_id": trip_id})

    if any(w in msg_lower for w in ["reduce", "cheaper", "save", "budget"]):
        response = "I can help you reduce costs! Consider switching to budget-friendly flights and hotels. Would you like me to generate a budget-optimized plan?"
        suggestions = ["Generate budget plan", "Show cheaper hotels", "Reduce activity costs"]
    elif any(w in msg_lower for w in ["hotel", "stay", "accommodation"]):
        response = "Looking at hotel options for your trip. Your current selection is a great balance of comfort and value. Want to explore alternatives?"
        suggestions = ["Upgrade hotel", "Downgrade to budget", "Show hotel details"]
    elif any(w in msg_lower for w in ["vegetarian", "food", "restaurant", "diet"]):
        response = "I'll note your vegetarian preference! All restaurant recommendations will be filtered for vegetarian options."
        suggestions = ["Show veg restaurants", "Update food preference", "Add dietary restrictions"]
    elif any(w in msg_lower for w in ["delay", "what if", "reschedule"]):
        response = "If there's a flight delay, I can automatically replan your itinerary. Use the 'Simulate Delay' feature on your trip page to see how it works."
        suggestions = ["Simulate 3hr delay", "Simulate 5hr delay", "View replan options"]
    elif any(w in msg_lower for w in ["comfort", "upgrade", "premium"]):
        response = "Want to upgrade to a more comfortable experience? I can suggest premium flights, 5-star hotels, and exclusive activities."
        suggestions = ["Upgrade to premium", "Show premium options", "Compare plans"]
    elif any(w in msg_lower for w in ["budget", "cost", "spending", "price"]):
        if trip:
            est = trip.get("totalEstimatedCost", 0)
            budget = trip.get("budget", 0)
            response = f"Your trip budget is ₹{budget:,} and estimated cost is ₹{est:,}. {'You have ₹' + str(int(budget - est)) + ' remaining.' if budget > est else 'You are slightly over budget.'}"
        else:
            response = "Please select a trip first to see budget details."
        suggestions = ["View cost breakdown", "Optimize costs", "Switch to budget plan"]
    else:
        response = "I'm your AI travel assistant! I can help with trip planning, cost optimization, delay replanning, and food preferences. What would you like to know?"
        suggestions = ["Plan a trip", "Check budget", "Simulate delay", "Food preferences"]

    return {
        "response": response,
        "suggestions": suggestions,
        "timestamp": datetime.utcnow().isoformat(),
    }
