import json
from config import AI_PROVIDER, AI_API_KEY, AI_MODEL


def call_ai(prompt, system_prompt=""):
    if AI_PROVIDER == "groq" and AI_API_KEY:
        try:
            import groq
            client = groq.Groq(api_key=AI_API_KEY)
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})
            response = client.chat.completions.create(
                model=AI_MODEL,
                messages=messages,
                temperature=0.7,
                max_tokens=1024
            )
            return response.choices[0].message.content
        except Exception as e:
            return _mock_ai_response(prompt)
    return _mock_ai_response(prompt)


def is_ai_available():
    return AI_PROVIDER == "groq" and bool(AI_API_KEY)


def _mock_ai_response(prompt):
    prompt_lower = prompt.lower()
    if "parse" in prompt_lower or "trip request" in prompt_lower or "travel" in prompt_lower:
        return json.dumps({
            "type": "trip_parsed",
            "message": "I've parsed your travel request and found the following details."
        })
    if "replan" in prompt_lower:
        return json.dumps({
            "type": "replan",
            "message": "I've generated an alternative itinerary to accommodate the delay."
        })
    if "explain" in prompt_lower or "recommendation" in prompt_lower:
        return json.dumps({
            "type": "recommendation",
            "message": "Based on your preferences and budget, I recommend this plan."
        })
    return json.dumps({
        "type": "chat",
        "message": "I'm your AI travel assistant. How can I help you plan your trip?"
    })
