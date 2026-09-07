"""TripMind AI — ML subsystem (consolidated single-file package).

This module merges the former ``services/ml/`` package (~20 modules)
into one importable unit. On import it recreates the original module
namespace (``services.ml.registry``, ``services.ml.inference``, ...)
so every existing ``from services.ml... import ...`` statement keeps
working unchanged. Behaviour is byte-for-byte identical to the old
package — the source of each former module is executed verbatim into
its own module namespace, in dependency order.
"""

import sys
import types

__all__ = ['definitions', 'database', 'features', 'registry', 'cost_model', 'timing_model', 'delay_model', 'text', 'content', 'reco', 'cluster', 'collab', 'anomaly', 'demand', 'visiting_time', 'inference', 'injector', 'trainer', 'train']

_SRC = {
    'definitions': """\"\"\"Static catalogue of every ML model in the TripMind system (spec §1-§17).

Each entry documents: priority tier, category, engine, input features, target,
output shape and the training pipeline that keeps the model honest. Models with
insufficient historical data are labelled INITIAL/COLD_START and fall back to a
defensible rule/content-based approach until enough real data exists (spec §19-20).
\"\"\"
from datetime import datetime

MODELS = {
    # ---- PRIORITY 1 (required) --------------------------------------------
    "tourist_spot_recommendation": {
        "priority": 1, "category": "recommendation", "model_type": "content+ranking",
        "features": "user interests, budget, time, spot category, popularity, rating, distance, availability, visit window",
        "target": "relevance score per tourist spot",
        "output": "ranked list of tourist spots with confidence",
        "pipeline": "content-based TF-IDF cosine + popularity/rating/availability feature scoring; trained from bookings+ratings",
    },
    "hotel_recommendation": {
        "priority": 1, "category": "recommendation", "model_type": "availability-aware ranking",
        "features": "user budget, hotel price/category/rating, distance from arrival & spots, room availability, room/bed type, amenities, prior preference",
        "target": "relevance score per bookable hotel/room",
        "output": "ranked list of hotels (only with available rooms)",
        "pipeline": "feature scoring + price fit + rating aggregation; availability validated live before every output",
    },
    "transport_recommendation": {
        "priority": 1, "category": "recommendation", "model_type": "ranking",
        "features": "origin, destination, transport type, price, duration, depart/arrival, stops, seat availability, user preference",
        "target": "relevance score per transport option",
        "output": "ranked transport options",
        "pipeline": "utility scoring (price/duration/preference) + historical booking weights",
    },
    "guide_recommendation": {
        "priority": 1, "category": "recommendation", "model_type": "ranking",
        "features": "tourist location, guide experience, languages, expertise, availability, hourly/day price, rating, bookings",
        "target": "relevance score per available guide",
        "output": "ranked guides",
        "pipeline": "expertise/location match + availability + price fit + rating aggregation",
    },
    "itinerary_optimization": {
        "priority": 1, "category": "optimization", "model_type": "combinatorial optimizer",
        "features": "preferences, locations, distances, travel times, opening hours, hotel/transport/guide availability, budget, duration",
        "target": "sequence minimising travel/backtracking",
        "output": "optimized daily itinerary (transport->hotel->spots->tours)",
        "pipeline": "DB-catalogue optimizer (trip_optimizer) with greedy daily ordering + ML splits/durations",
    },
    "ai_requirement_extraction": {
        "priority": 1, "category": "nlp", "model_type": "LLM/NLP parser",
        "features": "free-text trip description",
        "target": "structured trip preferences",
        "output": "structured trip request (dates, budget, interests, preferences)",
        "pipeline": "rule parser + optional LLM refinement (AI_API_KEY when present); never controls bookings",
    },
    # ---- PRIORITY 2 --------------------------------------------------------
    "travel_cost_prediction": {
        "priority": 2, "category": "prediction", "model_type": "regression",
        "features": "distance, transport type, travelers, transport/hotel price, nights, tour+guide costs, spot count",
        "target": "expected trip cost (with range)",
        "output": "predicted cost + range",
        "pipeline": "incremental linear regression on historical trips (cost_model)",
    },
    "travel_time_prediction": {
        "priority": 2, "category": "prediction", "model_type": "regression",
        "features": "distance, transport type, day of week, time of day, stops",
        "target": "estimated travel time",
        "output": "travel time (presented as estimate, never guaranteed)",
        "pipeline": "learned per-mode average + distance-vs-time scaling (timing_model)",
    },
    "content_based_recommendation": {
        "priority": 2, "category": "recommendation", "model_type": "TF-IDF + cosine similarity",
        "features": "name, description, category, tags, location of spots/hotels/tours",
        "target": "similarity to a given item / user taste",
        "output": "similar items for cold start",
        "pipeline": "pure-python TF-IDF vectors + cosine similarity over the live catalogue",
    },
    "user_segmentation": {
        "priority": 2, "category": "clustering", "model_type": "K-Means (k=5)",
        "features": "budget, travelers, trip count, spot categories visited, avg trip length",
        "target": "traveler segment label",
        "output": "segment profile (Budget/Luxury/Adventure/Cultural/Family)",
        "pipeline": "K-Means over normalised behavioral features from trips+bookings",
    },
    "tourist_spot_clustering": {
        "priority": 2, "category": "clustering", "model_type": "K-Means (adaptive k)",
        "features": "lat, lng, category, popularity, price, avg visit duration, rating",
        "target": "spot cluster assignment",
        "output": "geographically/thematically related spot groups",
        "pipeline": "K-Means over normalised geo+category features of the live catalogue",
    },
    # ---- PRIORITY 3 --------------------------------------------------------
    "visiting_time_recommendation": {
        "priority": 3, "category": "recommendation", "model_type": "ranking per window",
        "features": "spot, time of day, day of week, historical crowd, recommended times",
        "target": "suitability of each visiting window",
        "output": "ranked visiting windows (Highly Recommended .. Less Recommended)",
        "pipeline": "window scoring from ratings/time-of-day + spot recommendedTimes",
    },
    "demand_prediction": {
        "priority": 3, "category": "prediction", "model_type": "time-series baseline",
        "features": "historical bookings by type/city/day-of-week",
        "target": "future demand per service type",
        "output": "day-ahead demand forecast (next 7 days)",
        "pipeline": "moving-average weekly seasonality + linear trend from bookings",
    },
    "anomaly_detection": {
        "priority": 3, "category": "observability", "model_type": "Isolation Forest (pure python)",
        "features": "booking amount, frequency, inter-booking time, cancellations, user/provider behaviour",
        "target": "anomaly flag / score",
        "output": "list of unusual bookings for Admin monitoring",
        "pipeline": "isolation-forest style random-partition score over booking features",
    },
    "collaborative_filtering": {
        "priority": 3, "category": "recommendation", "model_type": "matrix factorization",
        "features": "user-item interaction (views, bookings, ratings)",
        "target": "latent user/item factors",
        "output": "predicted affinity for unseen items (only above a data threshold)",
        "pipeline": "SVD-style matrix factorization on the interactions matrix",
    },
    "personalized_trip_ranking": {
        "priority": 3, "category": "recommendation", "model_type": "weighted score fusion",
        "features": "transport/hotel/spot/guide scores, cost, time, distance, availability, preference match",
        "target": "overall trip score",
        "output": "trip plans ranked by optimizationScore",
        "pipeline": "combines model outputs into an overall plan score inside the optimizer",
    },
}


def registry_version():
    return {"models": MODELS, "generatedAt": datetime.utcnow().isoformat()}
""",
    'database': """\"\"\"MongoDB-backed persistence for ML model parameters.

Model state is stored in the `ml_state` collection as documents:
  {"key": "cost_model", "version": N, "params": {...}, "samples": K, "updatedAt": ...}
This keeps learned weights durable across restarts / deploys.
\"\"\"
from datetime import datetime
from services.mongodb import get_collection

STATE_COLLECTION = "ml_state"


def load_state(key):
    doc = get_collection(STATE_COLLECTION).find_one({"key": key})
    if doc:
        return doc
    return None


def save_state(key, params, samples):
    now = datetime.utcnow().isoformat()
    get_collection(STATE_COLLECTION).update_one(
        {"key": key},
        {"$set": {
            "params": params,
            "samples": samples,
            "version": int((load_state(key) or {}).get("version", 0)) + 1,
            "updatedAt": now,
        }},
        upsert=True,
    )


def get_or_init(key, default_params, default_samples=0):
    doc = load_state(key)
    if doc and doc.get("params"):
        return doc["params"], doc.get("samples", default_samples)
    return dict(default_params), default_samples

""",
    'features': """\"\"\"Convert trips / events into numeric feature vectors (pure Python).\"\"\"
from config import ML_CITY_INDEX


def _city_index(name):
    if name is None:
        return 0
    return ML_CITY_INDEX.get(str(name).strip().lower(), 9)


def trip_features(trip):
    \"\"\"Return a numeric feature vector for cost prediction.

    Features:
      origin_idx, dest_idx, log_days, travelers, log_budget
    \"\"\"
    origin = _city_index(trip.get("origin"))
    dest = _city_index(trip.get("destination"))
    try:
        start = trip.get("startDate")
        end = trip.get("endDate")
        days = _days_between(start, end)
    except Exception:
        days = 3
    travelers = float(trip.get("travelers") or 1)
    budget = float(trip.get("budget") or 50000)
    return {
        "origin": origin,
        "dest": dest,
        "log_days": _log(days),
        "travelers": travelers,
        "log_budget": _log(budget),
        "days": days,
        "budget": budget,
    }


def _days_between(start, end):
    from datetime import datetime
    try:
        if isinstance(start, str):
            start_dt = datetime.fromisoformat(start.replace("Z", "+00:00")).replace(tzinfo=None)
        else:
            start_dt = start
        if isinstance(end, str):
            end_dt = datetime.fromisoformat(end.replace("Z", "+00:00")).replace(tzinfo=None)
        else:
            end_dt = end
        return max(1, (end_dt - start_dt).days + 1)
    except Exception:
        return 3


def _log(x):
    import math
    return math.log(max(x, 1.0))


def event_features(event):
    \"\"\"Return simple features for delay classification.\"\"\"
    trip = event.get("trip") or {}
    severity = event.get("severity", "LOW")
    minutes = event.get("delayMinutes")
    if minutes is None:
        minutes = _severity_minutes(severity)
    return {
        "origin": _city_index(trip.get("origin")),
        "dest": _city_index(trip.get("destination")),
        "delay_minutes": float(minutes or 0),
        "severity": severity,
    }


def _severity_minutes(severity):
    if severity == "HIGH":
        return 300
    if severity == "MEDIUM":
        return 200
    return 90

""",
    'registry': """\"\"\"Model registry for the TripMind ML layer.

Every model has a recorded entry with:
  - priority (P1/P2/P3 per the ML MODEL REQUIREMENTS spec)
  - category (recommendation / prediction / clustering / optimization / nlp)
  - model_type (ranking, regression, clustering, content, factorization, ...)
  - input features + target + output (documented schema)
  - training pipeline description
  - version, status (INITIAL / COLD_START / ACTIVE)
  - sample size + evaluation metrics
  - trainedAt timestamp

Entries are stored in MongoDB `ml_models`. Inference code never mutates the DB.
\"\"\"
from datetime import datetime
from services.mongodb import get_collection

COLLECTION = "ml_models"


def _ensure():
    return get_collection(COLLECTION)


def registered_models():
    return list(_ensure().find({}, {"_id": 0}).sort("model", 1))


def get_model(model):
    return _ensure().find_one({"model": model}, {"_id": 0})


def upsert(model, defaults=None, **updates):
    \"\"\"Create or update a model entry. `defaults` sets fields on first insert.\"\"\"
    doc = get_model(model) or {}
    merged = dict(defaults or {})
    merged.update(doc)
    merged.update(updates)
    merged["model"] = model
    merged["updatedAt"] = datetime.utcnow().isoformat()
    _ensure().update_one({"model": model}, {"$set": merged}, upsert=True)
    return merged


def complete_registry(required=None):
    \"\"\"Ensure every known model has an entry (INITIAL until trained/used).\"\"\"
    from services.ml.definitions import MODELS
    touched = 0
    for name, meta in (required or MODELS).items():
        cur = get_model(name)
        if not cur:
            upsert(name, defaults={**meta, "status": "INITIAL",
                                   "version": 0, "samples": 0, "metrics": {},
                                   "trainedAt": None})
            touched += 1
    return touched


def mark_used(model, features="", target="", extra_metrics=None):
    \"\"\"Annotate provenance when a model entry exists (ensures registry doc).\"\"\"
    meta = (get_model(model) or {}).get("status")
    patch = {"features": features, "target": target}
    if extra_metrics:
        patch["extra"] = extra_metrics
    upsert(model, **patch)
    return meta


def mark_trained(trained_at=None):
    \"\"\"Record the last full-training timestamp (from /api/admin/ml/train).\"\"\"
    ts = trained_at or datetime.utcnow().isoformat()
    _ensure().update_one({"model": "system"}, {"$set": {"trainedAt": ts,
                                                        "updatedAt": ts}},
                         upsert=True)
    return ts


def last_trained_at():
    doc = _ensure().find_one({"model": "system"}, {"_id": 0})
    return (doc or {}).get("trainedAt")
""",
    'cost_model': """\"\"\"Cost Optimization model: incremental linear regression.

Uses the normal-equations closed-form solution (X^T X)^-1 X^T y with no numpy.
Training samples come from historical trips + itineraries (actual total cost).

Prediction: given origin, dest, days, travelers, budget -> expected total cost
and recommended sub-budget allocation percentages (learned from data).
\"\"\"
from datetime import datetime
from services.ml.database import get_or_init, save_state
from services.ml.features import _log

KEY = "cost_model"

DEFAULT_PARAMS = {
    "coefs": [0.0, 0.0, 0.1, 0.0, 1.0],  # [origin, dest, log_days, travelers, log_budget]
    "intercept": 0.0,
    "base_budget_split": [0.42, 0.28, 0.12, 0.10, 0.08],  # flight, hotel, transport, activities, food
    "n_features": 5,
}


def _feat_vec(f):
    return [f["origin"], f["dest"], f["log_days"], f["travelers"], f["log_budget"]]


def _train_batch(samples):
    \"\"\"samples: list of (features, actual_cost). Returns (coefs, intercept).\"\"\"
    if not samples:
        return list(DEFAULT_PARAMS["coefs"]), DEFAULT_PARAMS["intercept"]
    n = len(samples)
    p = DEFAULT_PARAMS["n_features"]
    # Build X augmented with 1s (standard linear regression)
    # Solve via normal equations manually with Gaussian elimination.
    X = [[_feat_vec(f) + [1.0], y] for f, y in samples]
    # Gram matrix G = X^T X (size p+1), and b = X^T y
    dim = p + 1
    G = [[0.0] * dim for _ in range(dim)]
    b = [0.0] * dim
    for Xrow, y in X:
        for i in range(dim):
            xi = Xrow[i]
            b[i] += xi * y
            for j in range(dim):
                G[i][j] += xi * Xrow[j]
    # Add small ridge for numerical stability
    for i in range(dim):
        G[i][i] += 1e-3
    # Solve Gw = b
    w = _gauss_seidel(G, b)
    coefs = w[:p]
    intercept = w[p]
    return list(coefs), float(intercept)


def _gauss_seidel(G, b, iterations=200):
    dim = len(b)
    w = [0.0] * dim
    for _ in range(iterations):
        for i in range(dim):
            s = b[i]
            for j in range(dim):
                if i != j:
                    s -= G[i][j] * w[j]
            diag = G[i][i]
            if abs(diag) > 1e-12:
                w[i] = s / diag
    return w


def get_model():
    # For simplicity, we rebuild from stored params. Training is done in trainer.py,
    # which calls save_state. Here we just read.
    params, samples = get_or_init(KEY, DEFAULT_PARAMS)
    return params, samples


def predict(trip):
    \"\"\"Return predicted total cost + learned budget allocation.\"\"\"
    coefs = params = None
    params, samples = get_or_init(KEY, DEFAULT_PARAMS)
    coefs = params["coefs"]
    intercept = params["intercept"]
    f = _features_from_trip(trip)
    vec = _feat_vec(f)
    predicted = intercept
    for i in range(len(vec)):
        predicted += coefs[i] * vec[i]
    predicted = max(1000.0, predicted)
    # Recover non-log predicted cost
    import math
    predicted_cost = math.exp(min(predicted, 15))
    # Clamp to a sensible fraction of the user's budget so predictions stay
    # realistic regardless of training outliers.
    budget = float(f.get("budget") or 50000)
    low = budget * 0.55
    high = budget * 1.15
    predicted_cost = min(max(predicted_cost, low), high)
    base_split = params.get("base_budget_split", DEFAULT_PARAMS["base_budget_split"])
    return {
        "predictedCost": round(predicted_cost),
        "budgetSplit": base_split,
        "samples": samples,
        "confidence": min(0.95, 0.3 + samples / 80.0),
    }


def _features_from_trip(trip):
    from services.ml.features import trip_features
    return trip_features(trip)


def save_cost_sample(trip, actual_cost):
    \"\"\"Reinforce: add a training sample from a real trip. We store raw samples
    in ml_state for the trainer to consume. Trainer re-runs regularly.\"\"\"
    from services.mongodb import get_collection
    get_collection("ml_training_samples").insert_one({
        "type": "cost",
        "features": trip,
        "label": actual_cost,
        "createdAt": datetime.utcnow().isoformat(),
    })


def get_training_samples():
    from services.mongodb import get_collection
    return list(get_collection("ml_training_samples").find({"type": "cost"}))

""",
    'timing_model': """\"\"\"Optimal Time Planning model: learned per-item-type duration statistics.

Learns the average duration (in minutes) for each itinerary item type
from historical itinerary items, so daily plans use realistic timings
instead of hardcoded values.

State persisted to `ml_state` key "timing_model".
\"\"\"
from services.ml.database import get_or_init, save_state

KEY = "timing_model"

TYPE_ALIASES = {
    "FLIGHT": "FLIGHT",
    "TRANSFER": "TRANSFER",
    "TRANSPORT": "TRANSFER",
    "HOTEL": "HOTEL",
    "FOOD": "FOOD",
    "ACTIVITY": "ACTIVITY",
}

DEFAULT_PARAMS = {
    "durations": {
        "FLIGHT": 360, "TRANSFER": 120, "HOTEL": 90,
        "FOOD": 60, "ACTIVITY": 180,
    },
    "counts": {"FLIGHT": 0, "TRANSFER": 0, "HOTEL": 0, "FOOD": 0, "ACTIVITY": 0},
}


def get_params():
    params, _ = get_or_init(KEY, DEFAULT_PARAMS)
    return params


def predict_duration(item_type):
    params = get_params()
    key = TYPE_ALIASES.get(item_type, item_type)
    return params["durations"].get(key, DEFAULT_PARAMS["durations"][key] if key in DEFAULT_PARAMS["durations"] else 120)


def save_duration_sample(item_type, start_time, end_time):
    \"\"\"Reinforce from a real itinerary item. Store raw samples for trainer.\"\"\"
    from datetime import datetime
    from services.mongodb import get_collection
    key = TYPE_ALIASES.get(item_type, item_type)
    if not start_time or not end_time:
        return
    try:
        s = datetime.fromisoformat(start_time.replace("Z", "+00:00").replace("+00:00", ""))
        e = datetime.fromisoformat(end_time.replace("Z", "+00:00").replace("+00:00", ""))
        minutes = (e - s).total_seconds() / 60.0
    except Exception:
        return
    if minutes <= 0:
        return
    get_collection("ml_training_samples").insert_one({
        "type": "timing",
        "itemType": key,
        "durationMinutes": minutes,
        "createdAt": datetime.utcnow().isoformat(),
    })

""",
    'delay_model': """\"\"\"Delay Prediction model: frequency-based classifier.

Learns the probability and expected duration of a flight delay for a given
(airline, route) pair from historical travel events. Pure frequency counting
stored in `ml_state` key "delay_model".

Prediction returns risk percentage + suggested buffer minutes + severity.
\"\"\"
from services.ml.database import get_or_init, save_state

KEY = "delay_model"

DEFAULT_PARAMS = {
    "route_counts": {},       # "origin|dest" -> [delayed, total]
    "airline_risk": {},       # airline -> avg probability
    "base_delay_prob": 0.18,  # global baseline
    "avg_delay_minutes": 170,
}


def get_params():
    params, _ = get_or_init(KEY, DEFAULT_PARAMS)
    return params


def predict_delay(origin, destination, airline=None):
    params = get_params()
    route_key = f"{str(origin).strip().lower()}|{str(destination).strip().lower()}"
    route = params.get("route_counts", {}).get(route_key)
    route_prob = None
    route_n = 0
    if route and route[1] > 0:
        route_prob = route[0] / route[1]
        route_n = route[1]

    airline_prob = None
    if airline:
        airline_prob = params.get("airline_risk", {}).get(str(airline).strip().lower())

    # Combine: start with baseline, adjust toward observed data weighted by sample count.
    prob = params.get("base_delay_prob", 0.18)
    if route_prob is not None:
        w = min(0.9, route_n / 30.0)
        prob = (1 - w) * prob + w * route_prob
    if airline_prob is not None:
        prob = 0.6 * prob + 0.4 * airline_prob

    prob = max(0.02, min(0.9, prob))

    avg_minutes = params.get("avg_delay_minutes", 170)
    buffer = int(avg_minutes * max(0.3, prob / max(0.3, 0.18)))
    severity = "LOW" if prob < 0.25 else ("MEDIUM" if prob < 0.5 else "HIGH")

    return {
        "probability": round(prob, 3),
        "expectedDelayMinutes": int(avg_minutes),
        "suggestedBufferMinutes": buffer,
        "severity": severity,
        "samples": len(params.get("route_counts", {})),
    }


def save_delay_outcome(route_key, airline, delay_happened, delay_minutes):
    from datetime import datetime
    from services.mongodb import get_collection
    get_collection("ml_training_samples").insert_one({
        "type": "delay",
        "route": route_key,
        "airline": (airline or "").strip().lower(),
        "delayHappened": bool(delay_happened),
        "delayMinutes": delay_minutes or 0,
        "createdAt": datetime.utcnow().isoformat(),
    })

""",
    'text': """\"\"\"Pure-python text vectorization: tokenizer, TF-IDF and cosine similarity.

Used by content-based recommendation (spec §9) — works with an empty rating
history (cold start). Vocabulary is built from the text on demand.
\"\"\"
import math
import re

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokenize(text):
    text = (text or "").lower()
    return _TOKEN_RE.findall(text)


def _document_frequency(docs):
    \"\"\"docs: list of token lists.\"\"\"
    df = {}
    for toks in docs:
        for t in set(toks):
            df[t] = df.get(t, 0) + 1
    return df


def tfidf_vectors(docs, smooth=True):
    \"\"\"Return (vectors, vocabulary) where each vector is a dict{term: weight}.\"\"\"
    toks_list = [tokenize(d) for d in docs]
    n = len(toks_list)
    df = _document_frequency(toks_list)
    vectors = []
    for toks in toks_list:
        n_t = len(toks)
        tf = {}
        for t in toks:
            tf[t] = tf.get(t, 0) + 1
        v = {}
        for t, c in tf.items():
            idf = math.log((n + 1.0) / (1.0 + df.get(t, 0))) + (1.0 if smooth else 0.0)
            v[t] = (c / (n_t if n_t else 1.0)) * idf
        vectors.append(v)
    vocab = sorted({t for toks in toks_list for t in toks})
    return vectors, vocab


def cosine(a, b):
    if not a or not b:
        return 0.0
    dot = 0.0
    for t, w in a.items():
        if t in b:
            dot += w * b[t]
    return dot / (math.sqrt(sum(w * w for w in a.values())) *
                  math.sqrt(sum(w * w for w in b.values())))


def similarity_matrix(vectors):
    \"\"\"n x n cosine matrix (sparse dict-of-dicts).\"\"\"
    n = len(vectors)
    return [[cosine(vectors[i], vectors[j]) for j in range(n)] for i in range(n)]


def text_similarity(primary_text, other_texts):
    \"\"\"Cosine similarity of primary vs each other text (0..1).\"\"\"
    vectors, _ = tfidf_vectors([primary_text] + list(other_texts))
    base = vectors[0]
    return [cosine(base, v) for v in vectors[1:]]
""",
    'content': """\"\"\"Content-based similarity for the live catalogue (spec §9).

Works with zero interaction history:
  similar_spots(<spot_id or taste text>, limit)
  similar_hotels(...), similar_tours(...)

Similarity uses TF-IDF + cosine over name/description/category/tags/location.
\"\"\"
from services.mongodb import get_collection
from services.ml.text import tfidf_vectors, similarity_matrix
from services.ml import registry


def _spot_texts(docs):
    for d in docs:
        parts = [d.get("name", ""), d.get("description", ""),
                 d.get("category", ""), " ".join(d.get("tags", [])),
                 d.get("city", "")]
        yield " ".join(str(p) for p in parts)


def _hotel_texts(docs):
    for d in docs:
        parts = [d.get("name", ""), d.get("description", ""),
                 d.get("category", ""), " ".join(d.get("amenities", []))]
        yield " ".join(str(p) for p in parts)


def _tour_texts(docs):
    for d in docs:
        parts = [d.get("name", ""), d.get("description", ""),
                 " ".join(d.get("includedServices", []))]
        yield " ".join(str(p) for p in parts)


def _similar(target_idx, texts, docs, limit, kind):
    vectors, _ = tfidf_vectors(texts)
    sim_mat = similarity_matrix(vectors)
    idxs = sorted(range(len(docs)), key=lambda i: sim_mat[target_idx][i],
                  reverse=True)
    out = []
    for i in idxs:
        if i == target_idx:
            continue
        item = docs[i]
        out.append({
            "type": kind,
            "id": str(item["_id"]),
            "name": item.get("name"),
            "score": round(sim_mat[target_idx][i] * 100, 1),
        })
        if len(out) >= limit:
            break
    return out, len(docs)


def _match_from_text(taste_text, docs, texts_fn, kind, limit):
    texts = [" ".join(str(t) for t in (taste_text or "").split())] + \\
        [t for t in texts_fn(docs)]
    vectors, _ = tfidf_vectors(texts)
    base = vectors[0]
    scores = []
    for i, doc in enumerate(docs):
        from services.ml.text import cosine
        scores.append((cosine(base, vectors[i + 1]), doc))
    scores.sort(key=lambda x: x[0], reverse=True)
    out = [{"type": kind, "id": str(d["_id"]), "name": d.get("name"),
            "score": round(s * 100, 1)} for s, d in scores[:limit]]
    return out, len(docs)


def similar_spots(target_id=None, taste_text=None, limit=6, city=None):
    q = {"status": "APPROVED"}
    if city:
        q["city"] = {"$regex": city, "$options": "i"}
    docs = list(get_collection("tourist_spots").find(q))
    if not docs:
        return [], 0
    if target_id:
        texts = list(_spot_texts(docs))
        try:
            target_idx = next(i for i, d in enumerate(docs)
                              if str(d["_id"]) == str(target_id))
        except StopIteration:
            return [], len(docs)
        result, n = _similar(target_idx, texts, docs, limit, "spot")
    else:
        result, n = _match_from_text(taste_text, docs, _spot_texts, "spot", limit)
    registry.mark_used("content_based_recommendation",
                       features="name, description, category, tags, location",
                       target="cosine similarity score")
    return result, n


def similar_hotels(target_id=None, taste_text=None, limit=6):
    docs = list(get_collection("hotels").find({"status": "APPROVED"}))
    if not docs:
        return [], 0
    if target_id:
        texts = list(_hotel_texts(docs))
        try:
            target_idx = next(i for i, d in enumerate(docs)
                              if str(d["_id"]) == str(target_id))
        except StopIteration:
            return [], len(docs)
        return _similar(target_idx, texts, docs, limit, "hotel")
    return _match_from_text(taste_text, docs, _hotel_texts, "hotel", limit)


def similar_tours(target_id=None, taste_text=None, limit=6):
    docs = list(get_collection("tours").find({"status": "APPROVED"}))
    if not docs:
        return [], 0
    if target_id:
        texts = list(_tour_texts(docs))
        try:
            target_idx = next(i for i, d in enumerate(docs)
                              if str(d["_id"]) == str(target_id))
        except StopIteration:
            return [], len(docs)
        return _similar(target_idx, texts, docs, limit, "tour")
    return _match_from_text(taste_text, docs, _tour_texts, "tour", limit)
""",
    'reco': """\"\"\"Hybrid recommendation engines (spec §15-§16, P1).

All engines read ONLY from the database (real services, real click/book/rating
history). Availability is validated live before anything is recommended:
  - hotels: only room types with available = total - booked - blocked > 0
  - transports: only seats > 0
  - guides: only guides present in guide_availability for the query window
Any component that lacks history reports its data gap so the model can be
labelled INITIAL/COLD_START.
\"\"\"
from datetime import datetime
from services.mongodb import get_collection
from services.ml import registry
from services.ml.text import text_similarity


# ---------------------------------------------------------------- data utils
def _rating_stats(id_key, allow_types):
    \"\"\"Return {serviceId: (avg_rating, count)} from the ratings collection.\"\"\"
    stats = {}
    for r in get_collection("ratings").find({"serviceType": {"$in": allow_types}}):
        sid = str(r.get("serviceId") or "")
        if not sid:
            continue
        vals, cnt = stats.get(sid, ([], 0))
        vals.append(float(r.get("rating") or 0))
        stats[sid] = (vals, cnt + 1)
    return {k: (sum(v) / len(v), c) for k, (v, c) in stats.items()}


def _booked_counts(id_key):
    counts = {}
    for b in get_collection("bookings").find({id_key: {"$ne": None}}):
        sid = str(b.get(id_key) or "")
        if sid:
            counts[sid] = counts.get(sid, 0) + 1
    return counts


def _norm(v, mx, mn=0.0):
    if mx <= mn:
        return 0.5
    return max(0.0, min(1.0, (v - mn) / (mx - mn)))


def _user_interests(user):
    if isinstance(user, str):
        u = get_collection("users").find_one({"_id": user})
        if not u:
            return []
        user = {"id": str(u["_id"]),
                "profile": u.get("profile") or {},
                "role": u.get("role")}
    if not isinstance(user, dict):
        return []
    prefs = (user.get("profile") or {}).get("preferences") or {}
    if isinstance(prefs, dict):
        interests = prefs.get("interests")
        if not interests:
            interests = prefs.get("spotCategories")
        if not interests:
            interests = prefs.get("types")
    else:
        interests = None
    if not interests:
        interests = (user.get("profile") or {}).get("interests") or []
    if isinstance(interests, str):
        interests = [interests]
    return [str(i) for i in interests]


# ---------------------------------------------------------------- tourist spot
def recommend_spots(user, limit=10, city=None, interests=None):
    docs = list(get_collection("tourist_spots").find({"status": "APPROVED"}))
    if city:
        docs = [d for d in docs
                if city.lower() in str(d.get("city", "")).lower()]
    if not docs:
        return [], 0, "COLD_START"

    interests = interests or _user_interests(user) or []
    ratings = _rating_stats("spotId", ["SPOT"])
    pop = _booked_counts("spotId")

    texts = []
    for d in docs:
        texts.append(" ".join(str(x) for x in [d.get("name", ""),
                                               d.get("description", ""),
                                               d.get("category", ""),
                                               " ".join(d.get("tags", []))]))
    sims = text_similarity(" ".join(interests), texts) if interests else \\
        [1.0] * len(docs)
    max_sim = max(sims) if sims else 1.0

    rows = []
    max_pop = max(pop.values()) if pop else 1
    for d, sim in zip(docs, sims):
        sid = str(d["_id"])
        avg, cnt = ratings.get(sid, (0.0, 0))
        popularity = pop.get(sid, 0)
        geo = 1.0
        rating_w = _norm(avg, 5.0) * (0.5 + 0.5 * min(1.0, cnt / 5.0)) if cnt else 0.4
        rows.append({
            "id": sid,
            "name": d.get("name"),
            "category": d.get("category"),
            "city": d.get("city"),
            "image": d.get("image") or d.get("imageUrl") or None,
            "rating": round(avg, 1),
            "ratingCount": cnt,
            "popularity": popularity,
            "venueType": d.get("venueType"),
            "entryFee": d.get("entryFee", 0),
            "score": round(100 * (0.30 * rating_w + 0.25 * _norm(popularity, max_pop)
                                  + 0.25 * (sim / max_sim if max_sim else 0.0)
                                  + 0.10 * geo + 0.10 * (1.0 if cnt else 0.0)), 1),
        })
    rows.sort(key=lambda r: r["score"], reverse=True)
    data_gap = "INITIAL" if not pop and not ratings else "ACTIVE"
    registry.mark_used("tourist_spot_recommendation",
                       features="interests, budget, category, popularity, rating, distance, availability",
                       target="relevance score per spot",
                       extra_metrics={"history": data_gap})
    return rows[:limit], len(docs), data_gap


# ---------------------------------------------------------------- hotels
def recommend_hotels(user, trip=None, city=None, limit=8):
    trip = trip or {}
    budget = float(trip.get("budget") or 50000)
    nights = max(1, int(trip.get("days") or trip.get("nights") or 2))
    travelers = int(trip.get("travelers") or 1)
    style = (trip.get("travelStyle") or "BALANCED").upper()
    city = city or trip.get("destination")

    docs = list(get_collection("hotels").find({"status": "APPROVED"}))
    if city:
        docs = [d for d in docs
                if city.lower() in str(d.get("city", "")).lower()]
    if not docs:
        return [], 0, "COLD_START", None

    ratings = _rating_stats("hotelId", ["HOTEL"])
    pop = _booked_counts("hotelId")

    rows = []
    max_pop = max(pop.values()) if pop else 1
    for d in docs:
        best_rt = None
        for rt in d.get("roomTypes", []):
            avail = int(rt.get("totalRooms") or 0) - int(rt.get("bookedRooms") or 0) \\
                - int(rt.get("blockedRooms") or 0)
            if avail > 0:
                price = float(rt.get("pricePerNight") or 0)
                if best_rt is None or price < best_rt["price"]:
                    best_rt = {"id": rt["id"], "name": rt.get("name"),
                               "category": rt.get("category"),
                               "price": price, "available": avail}
        if best_rt is None:  # availability is mandatory (spec §21)
            continue
        hid = str(d["_id"])
        avg, cnt = ratings.get(hid, (0.0, 0))
        price_cap = budget / max(1, nights * travelers)
        affordability = 1.0 if best_rt["price"] <= price_cap else max(0.0, 1.0 - (best_rt["price"] - price_cap) / max(1.0, price_cap))
        style_fit = {"BUDGET": 1.0 if (d.get("category") or "").lower() == "budget" else 0.6,
                     "PREMIUM": 1.0 if (d.get("category") or "").lower() in ("luxury", "premium") else 0.6,
                     }.get(style, 0.8)
        rows.append({
            "id": hid,
            "name": d.get("name"),
            "category": d.get("category"),
            "city": d.get("city"),
            "rating": round(avg, 1),
            "ratingCount": cnt,
            "popularity": pop.get(hid, 0),
            "roomType": best_rt,
            "score": round(100 * (0.40 * affordability + 0.20 * style_fit +
                                  0.20 * _norm(avg, 5.0) + 0.10 * _norm(pop.get(hid, 0), max_pop)
                                  + 0.10 * min(1.0, best_rt["available"] / 10.0)), 1),
        })
    rows.sort(key=lambda r: r["score"], reverse=True)
    data_gap = "INITIAL" if not pop and not ratings else "ACTIVE"
    registry.mark_used("hotel_recommendation",
                       features="budget, price, category, rating, room availability, amenities",
                       target="relevance score per bookable hotel",
                       extra_metrics={"history": data_gap,
                                      "availabilityEnforced": True})
    return rows[:limit], len(docs), data_gap, len(rows)


# ---------------------------------------------------------------- transports
def recommend_transports(user, origin, destination, pref_type=None, limit=8):
    from services.transport_service import available_transports
    try:
        docs = available_transports(origin or "", destination or "", pref_type)
    except Exception:
        docs = []
    if not docs:
        return [], 0, "COLD_START"

    ratings = _rating_stats("transportId", ["TRANSPORT"])
    pop = _booked_counts("transportId")

    rows = []
    max_pop = max(pop.values()) if pop else 1
    fares = [float(d.get("fare") or 0) for d in docs if (d.get("fare") or 0) > 0]
    max_fare = max(fares) if fares else 1
    for d in docs:
        tid = str(d["_id"])
        fare = float(d.get("fare") or 0)
        avg, cnt = ratings.get(tid, (0.0, 0))
        drawn = (d.get("travelTime") if "travelTime" in (d or {}) else None)
        try:
            time_v = float(drawn) if drawn else float(d.get("durationHours") or 0)
        except (TypeError, ValueError):
            time_v = 0.0
        rows.append({
            "id": tid,
            "type": d.get("type"),
            "serviceName": d.get("serviceName"),
            "fare": fare,
            "travelTime": round(time_v, 2),
            "seats": int(d.get("capacity") or 0) - int(d.get("bookedSeats") or 0),
            "rating": round(avg, 1),
            "ratingCount": cnt,
            "popularity": pop.get(tid, 0),
            "score": round(100 * (0.35 * _norm(fare, max_fare, 0.0) + 0.25 * 0.5
                                  + 0.15 * _norm(avg, 5.0) + 0.15 * _norm(pop.get(tid, 0), max_pop)
                                  + 0.10 * (1.0 if pref_type and d.get("type") == pref_type else 0.5)), 1),
        })
    rows.sort(key=lambda r: r["score"], reverse=True)
    data_gap = "INITIAL" if not ratings and not pop else "ACTIVE"
    registry.mark_used("transport_recommendation",
                       features="origin, destination, type, price, duration, seats, availability",
                       target="relevance score per transport",
                       extra_metrics={"history": data_gap})
    return rows[:limit], len(docs), data_gap


# ---------------------------------------------------------------- guides
def recommend_guides(user, location=None, interests=None, budget=None, limit=8):
    from services.guide_service import browse_guides
    try:
        guides = browse_guides(location=location)
    except Exception:
        guides = []
    if not guides:
        return [], 0, "COLD_START"

    interests = interests or _user_interests(user) or []
    ratings = _rating_stats("guideId", ["GUIDE"])
    pop = _booked_counts("guideId")

    rows = []
    max_pop = max(pop.values()) if pop else 1
    for g in guides:
        gid = str(g.get("userId") or "")
        pricing = g.get("pricing") or {}
        hourly = float(pricing.get("pricePerHour") or pricing.get("hourlyCharge") or 0)
        profile = g.get("profile") or {}
        specialities = " ".join(str(x) for x in
                                [profile.get("specialty", ""), profile.get("skills", ""),
                                 " ".join(profile.get("languages", [])),
                                 " ".join(profile.get("expertise", [""]))])
        avg, cnt = ratings.get(gid, (0.0, 0))
        match = text_similarity(" ".join(interests), [specialities])[0] if interests else 0.5
        price_fit = 1.0 if budget is None or hourly == 0 or hourly <= (budget or 5000) else max(0.0, 1.0 - (hourly / (budget or 5000) - 1))
        rows.append({
            "id": gid,
            "name": g.get("name"),
            "location": g.get("location"),
            "languages": profile.get("languages", []),
            "specialty": profile.get("specialty", ""),
            "rating": round(avg, 1),
            "ratingCount": cnt,
            "popularity": pop.get(gid, 0),
            "pricePerHour": hourly,
            "availableDates": (g.get("availabilityDays") or 0),
            "score": round(100 * (0.30 * match + 0.25 * price_fit +
                                  0.20 * _norm(avg, 5.0) + 0.15 * _norm(pop.get(gid, 0), max_pop)
                                  + 0.10 * min(1.0, (g.get("availabilityDays") or 0) / 6.0)), 1),
        })
    rows.sort(key=lambda r: r["score"], reverse=True)
    data_gap = "INITIAL" if not ratings and not pop else "ACTIVE"
    registry.mark_used("guide_recommendation",
                       features="location, experience, languages, expertise, availability, price, rating",
                       target="relevance score per guide",
                       extra_metrics={"history": data_gap})
    return rows[:limit], len(guides), data_gap
""",
    'cluster': """\"\"\"K-Means clustering over catalogue + behaviour (spec §7-§8).

Pure-python Lloyd's algorithm. Two engines:
  cluster_spots()  -> geographic + thematic spot grouping
  segment_users()  -> traveler segments (Budget/Luxury/Adventure/Cultural/Family)
\"\"\"
import math
from datetime import datetime
from services.mongodb import get_collection
from services.ml import registry

ROUNDS = 60

CATEGORY_BUCKETS = {
    "BEACH": 0.1, "COASTAL": 0.1, "WATERFRONT": 0.1,
    "HISTORICAL": 0.3, "HERITAGE": 0.3, "MONUMENT": 0.3, "MUSEUM": 0.3,
    "TEMPLE": 0.45, "RELIGIOUS": 0.45, "CULTURAL": 0.45,
    "NATURE": 0.65, "PARKS": 0.65, "WILDLIFE": 0.65,
    "ENTERTAINMENT": 0.8, "AMUSEMENT": 0.8,
    "SHOPPING": 0.9, "FOOD": 0.9, "KIDS": 0.85,
}


def _cat_code(category):
    return CATEGORY_BUCKETS.get(((category or "").upper()), 0.5)


def _spot_coords(d):
    \"\"\"Resolve a tourist spot's (lat, lng) from either the nested
    ``location`` object or legacy flat ``latitude``/``longitude`` keys.\"\"\"
    loc = d.get("location") or {}
    lat = loc.get("lat")
    if lat is None:
        lat = d.get("latitude")
    lng = loc.get("lng")
    if lng is None:
        lng = d.get("longitude")
    try:
        return float(lat or 0), float(lng or 0)
    except (TypeError, ValueError):
        return 0.0, 0.0


def _euclid(a, b):
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def _kmeans(points, k, seed=1):
    if len(points) <= k:
        labels = list(range(len(points)))
        groups = {}
        for i, _ in enumerate(points):
            groups[i] = [i]
        return labels, groups
    centers = sorted(points)[::max(1, len(points) // k)][:k]
    if len(centers) < k:
        centers = [points[i] for i in range(k)]
    labels = [0] * len(points)
    for _ in range(ROUNDS):
        moved = False
        for i, p in enumerate(points):
            ci = min(range(len(centers)), key=lambda c: _euclid(p, centers[c]))
            if ci != labels[i]:
                labels[i] = ci
                moved = True
        if not moved:
            break
        for c in range(k):
            members = [points[i] for i in range(len(points)) if labels[i] == c]
            if not members:
                continue
            centers[c] = [sum(d[j] for d in members) / len(members)
                          for j in range(len(centers[c]))]
    groups = {}
    for i, c in enumerate(labels):
        groups.setdefault(c, []).append(i)
    return labels, groups


def cluster_spots():
    \"\"\"Cluster approved spots by (lat, lng, category code, popularity, rating, price).\"\"\"
    docs = list(get_collection("tourist_spots").find({"status": "APPROVED"}))
    if not docs:
        return [], "COLD_START"

    from services.ml.reco import _booked_counts
    pop = _booked_counts("spotId")
    pops = list(pop.values())
    max_pop = max(pops) if pops else 1
    pts = []
    for d in docs:
        lat, lng = _spot_coords(d)
        pts.append([lat / 90.0, lng / 180.0, _cat_code(d.get("category")),
                    min(1.0, pop.get(str(d["_id"]), 0) / max_pop),
                    min(1.0, float(d.get("rating") or 0) / 5.0),
                    min(1.0, float(d.get("entryFee") or 0) / 3000.0)])
    k = max(2, min(5, len(docs)))
    labels, groups = _kmeans(pts, k)
    result = []
    for c, idxs in groups.items():
        members = [{"id": str(docs[i]["_id"]), "name": docs[i].get("name"),
                    "category": docs[i].get("category")} for i in idxs]
        cats = [m["category"] for m in members]
        profile = {}
        code_sum = sum(_cat_code(c) for c in cats)
        code = code_sum / len(cats) if cats else 0.5
        profile["theme"] = next((t for t, v in [
            ("Coastal", 0.2), ("Historical", 0.4), ("Temple & Cultural", 0.6),
            ("Nature", 0.75), ("Entertainment", 0.9), ("Shopping/Food", 1.0)]
            if code <= v), "Mixed")
        result.append({"cluster": c, "theme": profile["theme"],
                       "members": members, "count": len(members)})
    result.sort(key=lambda r: len(r["members"]), reverse=True)
    registry.mark_used("tourist_spot_clustering",
                       features="lat, lng, category, popularity, price, rating",
                       target="cluster assignment")
    return result, "ACTIVE" if len(docs) > 2 else "COLD_START"


def segment_users():
    \"\"\"Cluster travelers by behaviour (budget, travelers, trip length, categories).\"\"\"
    users = list(get_collection("users").find({"role": "USER"}))
    trips = list(get_collection("trips").find({}))
    user_points = {}
    for t in trips:
        uid = t.get("userId")
        if not uid or uid == "demo-user-1":
            continue
        p = user_points.setdefault(uid, [0.0, 0.0, 0.0, 0.0])
        p[0] += float(t.get("budget") or 50000)
        p[1] += float(t.get("travelers") or 1)
        try:
            from services.ml.features import _days_between
            p[2] += max(1, _days_between(t.get("startDate"), t.get("endDate")))
        except Exception:
            p[2] += 2
        p[3] += 1
    userset = list(user_points.keys())
    if not userset:
        return [], "COLD_START"

    pts = []
    budgets = [user_points[u][0] for u in userset]
    max_budget = max(budgets) if budgets else 1
    max_tr = max(p[1] for p in user_points.values()) or 1
    max_len = max(p[2] for p in user_points.values()) or 1
    max_n = max(p[3] for p in user_points.values()) or 1
    for u in userset:
        b, tr, ln, n = user_points[u]
        pts.append([min(1.0, b / max_budget), min(1.0, tr / max_tr),
                    min(1.0, ln / max_len), min(1.0, n / max_n)])
    k = min(5, max(2, len(userset)))
    labels, groups = _kmeans(pts, k)

    profile_names = ["Budget Traveler", "Luxury Traveler", "Adventure Traveler",
                     "Cultural Traveler", "Family Traveler"]
    result = []
    for c, idxs in groups.items():
        avg_budget = sum(user_points[userset[i]][0] for i in idxs) / len(idxs)
        bucket = min(len(profile_names) - 1,
                     int((avg_budget / (max_budget or 1)) * len(profile_names)))
        name = profile_names[bucket]
        result.append({
            "segment": name,
            "members": [userset[i] for i in idxs],
            "count": len(idxs),
            "avgBudget": round(avg_budget),
        })
    result.sort(key=lambda r: r["count"], reverse=True)
    registry.mark_used("user_segmentation",
                       features="budget, travelers, trip length, trip count",
                       target="traveler segment")
    return result, "ACTIVE" if len(userset) > 2 else "COLD_START"
""",
    'collab': """\"\"\"Collaborative filtering via matrix factorization (spec §17, P3).

Produces latent user/item factors from the ratings + booking interaction matrix
using coordinate-descent SGD. Only becomes "ACTIVE" once a minimum interaction
count exists; below that it reports COLD_START so callers use content-based
recommendations.
\"\"\"
import math
import random
from services.mongodb import get_collection
from services.ml import registry

MIN_INTERACTIONS = 12
FACTORS = 8


def _interactions():
    rows = []
    for b in get_collection("bookings").find({}):
        sid = b.get("tourId") or b.get("hotelId") or b.get("spotId") or \\
            b.get("transportId") or b.get("guideId") or None
        uid = b.get("userId")
        if not sid or not uid or uid.startswith("demo"):
            continue
        rows.append((uid, str(sid), 1.0))
    for r in get_collection("ratings").find({}):
        uid = r.get("userId")
        sid = r.get("serviceId")
        if not uid or not sid:
            continue
        rows.append((uid, str(sid), float(r.get("rating") or 0) / 5.0))
    return rows


def _sgd(rows, users, items, iters=60, lr=0.02, reg=0.04):
    random.seed(42)
    P = {u: [random.random() * 0.1 for _ in range(FACTORS)] for u in users}
    Q = {i: [random.random() * 0.1 for _ in range(FACTORS)] for i in items}
    for _ in range(iters):
        for u, i, v in rows:
            err = v - sum(P[u][k] * Q[i][k] for k in range(FACTORS))
            for k in range(FACTORS):
                pu, qi = P[u][k], Q[i][k]
                P[u][k] += lr * (err * qi - reg * pu)
                Q[i][k] += lr * (err * pu - reg * qi)
    return P, Q


def factorize():
    rows = _interactions()
    if len(rows) < MIN_INTERACTIONS:
        registry.mark_used("collaborative_filtering",
                           features="user-item rating/booking interactions",
                           target="latent factors",
                           extra_metrics={"minInteractionsRequired": MIN_INTERACTIONS})
        return None, len(rows), "COLD_START"
    users = list({r[0] for r in rows})
    items = list({r[1] for r in rows})
    P, Q = _sgd(rows, users, items)
    model = {"users": users, "items": items,
             "P": {u: P[u] for u in P}, "Q": {i: Q[i] for i in Q}}
    registry.mark_used("collaborative_filtering",
                       features="user-item rating/booking interactions",
                       target="latent factors")
    return model, len(rows), "ACTIVE"


def predict_affinity(model, user_id, item_id):
    if not model:
        return None
    u = [model["P"][x] for x in model["users"] if x == user_id]
    q = [model["Q"][x] for x in model["items"] if x == item_id]
    if not u or not q:
        return None
    return min(1.0, max(0.0, sum(u[0][k] * q[0][k] for k in range(FACTORS))))


def similar_users(model, user_id, k=3):
    if not model or user_id not in model["P"]:
        return []
    pu = model["P"][user_id]
    scored = []
    for u in model["users"]:
        if u == user_id:
            continue
        s = sum(pu[k] * model["P"][u][k] for k in range(FACTORS))
        norm = math.sqrt(sum(model["P"][u][k] ** 2 for k in range(FACTORS)))
        scored.append((u, s / norm if norm else 0.0))
    scored.sort(key=lambda x: x[1], reverse=True)
    return [u for u, _ in scored[:k]]
""",
    'anomaly': """\"\"\"Booking anomaly detection with a pure-python Isolation Forest (spec §19).

Each booking is represented by behavioral features:
  amount, seconds since the user's previous booking, user's booking frequency,
  user's cancellation rate, provider's cancellation rate.

An isolation-like score is computed by random feature partitions: anomalies
isolate faster (fewer splits). Flags above `threshold` are surfaced for Admin
monitoring.
\"\"\"
import math
import random
from datetime import datetime, timedelta
from services.mongodb import get_collection
from services.ml import registry

TREES = 64
SAMPLE = 256


def _iso_score(sample, neighbours, trees=TREES):
    \"\"\"Average partition depth until the sample is isolated.

    Anomalies separate in few random splits, so their average depth is small
    and the returned anomaly score (1 - depth/maxDepth) is high. This is a
    faithful, pure-python approximation of an isolation forest using the
    interaction matrix of our behavioural features.
    \"\"\"
    parts = 0
    points = [sample] + list(neighbours)
    dims = len(sample)
    for _ in range(trees):
        feat = random.randrange(dims)
        lo = min(p[feat] for p in points)
        hi = max(p[feat] for p in points)
        depth = 0
        left = set(range(1, len(points)))  # indices of everything except sample
        while left and depth < 12:
            p = lo + random.random() * (hi - lo) if hi > lo else lo + (1 + feat) * 1e-6
            in_left = {i for i in left if points[i][feat] <= p}
            if 0 < len(in_left) < len(left):
                break
            depth += 1
            left = in_left
        parts += depth
    avg = parts / trees
    return min(1.0, max(0.0, 1.0 - avg / 12.0))  # 1 = anomalous


def _secs(then):
    if not then:
        return None
    try:
        return (datetime.utcnow() - datetime.fromisoformat(then)).total_seconds()
    except (ValueError, TypeError):
        return None


def flag_anomalies(limit=30, threshold=0.72):
    bookings = list(get_collection("bookings").find({}).sort("createdAt", -1))[:SAMPLE]
    if len(bookings) < 6:
        registry.mark_used("anomaly_detection",
                           features="amount, frequency, inter-booking time, cancellations",
                           target="anomaly flag",
                           extra_metrics={"minSamplesRequired": 6})
        return [], 0, "COLD_START"

    users = {u["_id"]: u for u in get_collection("users").find({})}
    user_bookings = {}
    for b in bookings:
        user_bookings.setdefault(b.get("userId"), []).append(b)
    user_cancel_rate = {}
    for uid, rows in user_bookings.items():
        total = len(rows)
        cancelled = sum(1 for r in rows if r.get("status") == "CANCELLED")
        user_cancel_rate[uid] = cancelled / total if total else 0

    fee = []
    for b in bookings:
        amt = float(b.get("total") or b.get("unitPrice") or 0)
        rows = user_bookings.get(b.get("userId"), [])
        idx = next((i for i, r in enumerate(rows) if r["_id"] == b["_id"]), 0)
        prev = rows[idx + 1] if idx + 1 < len(rows) else None
        secs = _secs(prev.get("createdAt")) if prev else (0.0 if idx else 86400.0)
        freq = len(rows)
        fee.append([amt / 20000.0, min(1.0, (secs or 86400.0) / 86400.0),
                    min(1.0, freq / 10.0),
                    user_cancel_rate.get(b.get("userId"), 0.0)])

    # normalize each feature to 0..1 across dataset for stable scoring
    norms = []
    for j in range(len(fee[0])):
        col = [r[j] for r in fee]
        if max(col) == min(col):
            norms.append([0.5] * len(col))
        else:
            m, mx = min(col), max(col)
            norms.append([(v - m) / (mx - m) for v in col])
    normed = [[norms[j][i] for j in range(len(fee[0]))] for i in range(len(fee))]

    flagged = []
    for i, b in enumerate(bookings):
        feat = normed[i]
        keep = [normed[j] for j in range(len(normed)) if j != i]
        score = _iso_score(feat, keep)
        if score >= threshold:
            flagged.append({
                "bookingId": str(b["_id"]),
                "reference": b.get("reference"),
                "type": b.get("type"),
                "status": b.get("status"),
                "amount": float(b.get("total") or 0),
                "userId": b.get("userId"),
                "userName": (users.get(b.get("userId")) or {}).get("name"),
                "anomalyScore": round(score, 3),
            })
    flagged.sort(key=lambda x: x["anomalyScore"], reverse=True)
    registry.mark_used("anomaly_detection",
                       features="amount, frequency, inter-booking time, cancellations",
                       target="anomaly flag")
    return flagged[:limit], len(bookings), "ACTIVE"
""",
    'demand': """\"\"\"Demand prediction: weekly-season time-series baseline (spec §18).

Predicts the next 7 days of expected bookings per service type (HOTEL,
TRANSPORT, TOURIST SPOT, GUIDE, TOUR) using:
  level     = moving average of daily bookings
  trend     = linear slope over recent days
  weekday   = multiplicative seasonal offset per day-of-week

This helps Admins plan capacity without a heavy external library.
\"\"\"
from collections import defaultdict
from datetime import datetime, timedelta
from services.mongodb import get_collection
from services.ml import registry

TYPE_KEY = {"HOTEL": "hotelId", "TRANSPORT": "transportId",
            "TOURIST SPOT": "spotId", "TOUR": "tourId", "GUIDE": "guideId"}


def _series():  # {date_str: {type: count}}
    by_day = defaultdict(lambda: defaultdict(int))
    for b in get_collection("bookings").find({}):
        day = (b.get("date") or b.get("createdAt") or "")[:10]
        if not day:
            continue
        by_day[day][b.get("type") or "OTHER"] += 1
    return by_day


def _mean(vals):
    vals = [v for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else 0.0


def _slope(vals):
    n = len(vals)
    if n < 2:
        return 0.0
    xs = range(n)
    mx = _mean(list(xs))
    my = _mean(vals)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, vals))
    den = sum((x - mx) ** 2 for x in xs)
    return num / den if den else 0.0


def predict_demand(days=7):
    series = _series()
    dates = sorted(series.keys())
    types = sorted({t for d in series.values() for t in d})
    out = {}
    total_samples = 0
    for t in types:
        daily = []
        for d in dates:
            daily.append(series[d][t])
        if not daily:
            continue
        level = _mean(daily[-14:]) if len(daily) > 14 else _mean(daily)
        trend = _slope(daily[-10:]) if len(daily) > 3 else 0.0
        weekday_offset = {}
        for wd in range(7):
            vals = [daily[i] for i, d in enumerate(dates)
                    if datetime.strptime(d, "%Y-%m-%d").weekday() == wd]
            weekday_offset[wd] = _mean(vals) / level if level else 1.0
        forecast = []
        last_day = datetime.strptime(dates[-1], "%Y-%m-%d") if dates else datetime.utcnow()
        for k in range(1, days + 1):
            day = last_day + timedelta(days=k)
            base = level
            level += trend
            forecast.append({
                "date": day.strftime("%Y-%m-%d"),
                "weekday": day.strftime("%A"),
                "expected": round(base * weekday_offset.get(day.weekday(), 1.0), 2),
            })
        out[t] = forecast
        total_samples += len(daily)
    registry.mark_used("demand_prediction",
                       features="historical bookings by type & day-of-week",
                       target="future demand per service type",
                       extra_metrics={"historySamples": total_samples})
    return out, total_samples
""",
    'visiting_time': """\"\"\"Visiting-time recommendation (spec §20).

Ranks visiting windows (morning/afternoon/evening) for a tourist spot using:
  - spot recommendedTimes entered by the Tourist Spot Admin (strong signal)
  - time-of-day signals from historical SPOT bookings/ratings
  - a neutral default ordering when no admin/history signal exists.
\"\"\"
from services.mongodb import get_collection
from services.ml import registry

WINDOWS = [("Morning", "06:00-11:59"), ("Noon", "12:00-15:59"),
           ("Evening", "16:00-21:00")]


def _label(details, fallback="Noon"):
    return fallback


def recommend_visit_times(spot_id, requested_day=None):
    spot = get_collection("tourist_spots").find_one({"_id": str(spot_id)})
    if not spot:
        return None, "Spot not found."
    recs = spot.get("recommendedTimes") or []
    base = {}
    for r in recs:
        base[(r.get("window") or _label(r))] = r
    # Window scores: admin recommendation maps to Highly/Recommended; else crowd
    window_scores = {name: 0.4 for name, _ in WINDOWS}
    for b in get_collection("bookings").find({"type": "SPOT", "spotId": str(spot_id)}):
        window = None
        if b.get("date"):
            pass
        # Booking slots carry a window hint when set
        d = b.get("details") or {}
        window = d.get("window")
        if not window:
            continue
        if window in window_scores:
            window_scores[window] += 0.15
    # Admin-provided recommendations dominate
    for key, rec in base.items():
        label = (rec.get("label") or "").lower()
        for name, _ in WINDOWS:
            if name.lower() in key.lower() or name.lower() in label:
                window_scores[name] = max(window_scores[name], 1.0)
    level = lambda s: ("Highly Recommended" if s >= 0.9 else
                       "Recommended" if s >= 0.65 else
                       "Moderate" if s >= 0.45 else "Less Recommended")
    out = [{"window": name, "hours": hours, "level": level(window_scores[name]),
            "score": round(window_scores[name], 2)} for name, hours in WINDOWS]
    out.sort(key=lambda w: w["score"], reverse=True)
    registry.mark_used("visiting_time_recommendation",
                       features="spot, time of day, recommended times, historical crowd",
                       target="suitability per visiting window")
    return out, len(recs)
""",
    'inference': """\"\"\"Public inference facade for the ML layer.

Every call returns a labelled envelope:
  {"model": <name>, "status": INITIAL|COLD_START|ACTIVE, "version": N,
   "metrics": {...}, "result": <payload>}

Status derives from the registry + live data gaps. This keeps the "don't claim
ML without data" rule honest — engines with little history are explicitly
flagged so the frontend can show a meaningful source-of-truth label.
\"\"\"
from services.ml import registry, reco, content, cluster, collab, demand, anomaly, visiting_time


def _envelope(model, result, status, extra=None, version=None):
    meta = registry.get_model(model) or {}
    doc = {
        "model": model,
        "status": status,
        "version": max(int((version or meta.get("version"))), 0),
        "metrics": meta.get("metrics") or {},
        "result": result,
    }
    if extra:
        doc.update(extra)
    return doc


def spots(user, limit=10, city=None, interests=None):
    rows, n, gap = reco.recommend_spots(user, limit=limit, city=city, interests=interests)
    return _envelope("tourist_spot_recommendation", {"spots": rows, "catalogSize": n}, gap)


def hotels(user, trip=None, city=None, limit=8):
    rows, n, gap, bookable = reco.recommend_hotels(user, trip=trip, city=city, limit=limit)
    return _envelope("hotel_recommendation",
                     {"hotels": rows, "catalogSize": n, "bookable": bookable}, gap,
                     extra={"availabilityEnabled": True})


def transports(user, origin, destination, pref_type=None, limit=8):
    rows, n, gap = reco.recommend_transports(user, origin, destination, pref_type, limit)
    return _envelope("transport_recommendation", {"transports": rows, "catalogSize": n}, gap)


def guides(user, location=None, interests=None, budget=None, limit=8):
    rows, n, gap = reco.recommend_guides(user, location=location, interests=interests,
                                         budget=budget, limit=limit)
    return _envelope("guide_recommendation", {"guides": rows, "catalogSize": n}, gap)


def similar_items(kind, target_id=None, taste_text=None, limit=6):
    fn = {"spot": content.similar_spots, "hotel": content.similar_hotels,
          "tour": content.similar_tours}.get(kind)
    if not fn:
        return _envelope("content_based_recommendation", {"error": "unknown kind"}, "INITIAL")
    rows, n = fn(target_id=target_id, taste_text=taste_text, limit=limit)
    return _envelope("content_based_recommendation",
                     {"items": rows, "catalogSize": n}, "ACTIVE" if n else "INITIAL")


def cost(user=None, trip=None):
    from services.ml.cost_model import predict as predict_cost
    pred = predict_cost(trip or {})
    cost0 = pred["predictedCost"]
    low = round(cost0 * 0.9)
    high = round(cost0 * 1.15)
    pred["range"] = {"low": low, "high": high,
                     "note": "Estimate — actual costs depend on live fares and availability."}
    return _envelope("travel_cost_prediction",
                     {"predictedCost": cost0, "range": pred["range"],
                      "budgetSplit": pred["budgetSplit"], "confidence": pred["confidence"],
                      "samples": pred["samples"]},
                     "ACTIVE" if pred["samples"] else "INITIAL")


def travel_time(item_type=None, origin=None, destination=None):
    from services.ml.timing_model import predict_duration, get_params
    params = get_params()
    minutes = predict_duration(item_type) if item_type else None
    return _envelope("travel_time_prediction",
                     {"itemType": item_type, "estimatedMinutes": minutes,
                      "avgMinutesByType": params.get("durations"),
                      "note": "Estimated — not a guaranteed travel time."},
                     "ACTIVE")


def spot_clusters():
    rows, gap = cluster.cluster_spots()
    return _envelope("tourist_spot_clustering", {"clusters": rows}, gap)


def user_segments():
    rows, gap = cluster.segment_users()
    return _envelope("user_segmentation", {"segments": rows}, gap)


def affinity(user_id, item_id=None):
    model, samples, gap = collab.factorize()
    if item_id:
        score = collab.predict_affinity(model, user_id, item_id)
        result = {"affinity": score, "sampleCount": samples}
    else:
        result = {"similarUsers": collab.similar_users(model, user_id), "sampleCount": samples}
    return _envelope("collaborative_filtering", result, gap)


def forecast(days=7):
    rows, samples = demand.predict_demand(days=days)
    return _envelope("demand_prediction", {"forecast": rows, "historySamples": samples},
                     "ACTIVE" if samples else "INITIAL")


def anomalies(limit=30):
    rows, samples, gap = anomaly.flag_anomalies(limit=limit)
    return _envelope("anomaly_detection", {"anomalies": rows, "samples": samples}, gap)


def visit_times(spot_id):
    rows, admin = visiting_time.recommend_visit_times(spot_id)
    if rows is None:
        return _envelope("visiting_time_recommendation", {"error": admin}, "INITIAL")
    return _envelope("visiting_time_recommendation",
                     {"windows": rows, "adminRecommendations": admin}, "ACTIVE")


def rank_trip(plans, request_data=None):
    \"\"\"Personalized overall trip ranking (spec §22/P3) over optimizer plans.\"\"\"
    request_data = request_data or {}
    budget = float(request_data.get("budget") or 50000)
    ranked = []
    for p in plans or []:
        cost = float(p.get("totalCost") or 0)
        cost_fit = 1.0 if cost <= budget else max(0.0, 1.0 - ((cost - budget) / budget))
        base = float(p.get("optimizationScore") or p.get("comfortScore") or 0.5)
        travel_p = float(p.get("travelTimeHours") or 0) / 48.0
        score = round(100 * (0.55 * base + 0.30 * cost_fit + 0.15 * (1.0 - travel_p)), 1)
        ranked.append({**p, "personalizedScore": score, "costFit": round(cost_fit, 2)})
    ranked.sort(key=lambda x: x["personalizedScore"], reverse=True)
    return _envelope("personalized_trip_ranking", {"plans": ranked}, "ACTIVE")
""",
    'injector': """\"\"\"Integration layer: expose ML predictions to the rest of the app.

The `enabled()` guard respects the ML_ENABLED env flag. When disabled, all
predictions fall back to current deterministic (non-ML) behavior so no
features are lost.
\"\"\"
from config import ML_ENABLED
from services.ml import cost_model, timing_model, delay_model
from services.ml.database import get_or_init

_ml_ready = False


def enabled():
    return ML_ENABLED


def predict_trip_cost(trip):
    \"\"\"Return predicted cost + learned budget split (or None if disabled).\"\"\"
    if not enabled():
        return None
    try:
        return cost_model.predict(trip)
    except Exception:
        return None


def predict_delay(origin, destination, airline=None):
    \"\"\"Return delay risk dict (or None if disabled).\"\"\"
    if not enabled():
        return None
    try:
        return delay_model.predict_delay(origin, destination, airline)
    except Exception:
        return None


def predict_duration(item_type):
    \"\"\"Return learned duration minutes (falls back to default).\"\"\"
    if not enabled():
        return None
    try:
        return timing_model.predict_duration(item_type)
    except Exception:
        return None


def reinforce_cost(trip, actual_cost):
    \"\"\"Record a real cost sample (called on book/generate).\"\"\"
    if not enabled():
        return
    try:
        cost_model.save_cost_sample(trip, actual_cost)
    except Exception:
        pass


def reinforce_timing(item_type, start, end):
    if not enabled():
        return
    try:
        timing_model.save_duration_sample(item_type, start, end)
    except Exception:
        pass


def reinforce_delay(route_key, airline, happened, minutes):
    if not enabled():
        return
    try:
        delay_model.save_delay_outcome(route_key, airline, happened, minutes)
    except Exception:
        pass

""",
    'trainer': """\"\"\"Trainer: recompute ML model parameters from all historical data.

Run periodically (e.g., on deploy / after N new samples) to refresh:
  - cost_model: linear regression over historical trips+itineraries
  - timing_model: average duration per item type
  - delay_model: route/airline delay frequencies
All updated params are persisted to `ml_state` via save_state.
\"\"\"
from datetime import datetime
from services.mongodb import get_collection
from services.ml import cost_model, timing_model, delay_model
from services.ml.features import trip_features, _days_between


def train_cost():
    \"\"\"Train linear regression from historical trips with actual total cost.\"\"\"
    samples = []
    trips = list(get_collection("trips").find({}))
    for t in trips:
        est = t.get("totalEstimatedCost")
        # Use sum of itinerary totalCosts as realistic label
        itin_cost = 0
        for it in (t.get("itineraries") or []):
            itin_cost += it.get("totalCost", 0)
        label = itin_cost or est or t.get("budget", 50000) * 0.9
        try:
            feat = trip_features(t)
            samples.append((feat, float(label)))
        except Exception:
            continue

    # Also incorporate explicit ml_training_samples of type cost
    for s in cost_model.get_training_samples():
        t = s.get("features") or {}
        try:
            feat = trip_features(t)
            samples.append((feat, float(s.get("label", 0))))
        except Exception:
            continue

    coefs, intercept = cost_model._train_batch(samples)
    params = cost_model.get_model()[0]
    params["coefs"] = coefs
    params["intercept"] = intercept
    cost_model.save_state(cost_model.KEY, params, len(samples))
    return {"samples": len(samples), "coefs": coefs, "intercept": intercept}


def train_timing():
    \"\"\"Average duration per item type from itineraries + samples.\"\"\"
    from services.mongodb import get_collection
    durations = dict(timing_model.DEFAULT_PARAMS["durations"])
    counts = {k: 0 for k in durations}

    def add(key, minutes):
        key = timing_model.TYPE_ALIASES.get(key, key)
        if key not in durations:
            return
        c = counts[key]
        new_c = c + 1
        durations[key] = (durations[key] * c + minutes) / new_c
        counts[key] = new_c

    trips = list(get_collection("trips").find({}))
    for t in trips:
        for it in (t.get("itineraries") or []):
            for item in (it.get("items") or []):
                st, et = item.get("startTime"), item.get("endTime")
                if st and et:
                    try:
                        s = datetime.fromisoformat(st.replace("Z", "+00:00").replace("+00:00", ""))
                        e = datetime.fromisoformat(et.replace("Z", "+00:00").replace("+00:00", ""))
                        minutes = (e - s).total_seconds() / 60.0
                        if minutes > 0:
                            add(item.get("type"), minutes)
                    except Exception:
                        continue

    for s in get_collection("ml_training_samples").find({"type": "timing"}):
        add(s.get("itemType"), float(s.get("durationMinutes", 60)))

    params = {"durations": durations, "counts": counts}
    timing_model.save_state(timing_model.KEY, params, sum(counts.values()))
    return {"durations": durations, "samples": counts}


def train_delay():
    \"\"\"Delay frequencies from travel events + samples.\"\"\"
    from services.mongodb import get_collection
    route_counts = {}
    airline_risk = {}
    delay_totals = []
    total_trips_with_route = {}

    # Route baseline: assume most trips are not delayed unless an event says so.
    all_trips_keys = set()
    for t in get_collection("trips").find({}):
        key = f"{str(t.get('origin','')).strip().lower()}|{str(t.get('destination','')).strip().lower()}"
        all_trips_keys.add(key)
        route_counts.setdefault(key, [0, 0])
        route_counts[key][1] += 1
        total_trips_with_route[key] = total_trips_with_route.get(key, 0) + 1

    # Delay events -> mark as delayed on that route.
    for t in get_collection("trips").find({}):
        key = f"{str(t.get('origin','')).strip().lower()}|{str(t.get('destination','')).strip().lower()}"
        for ev in (t.get("events") or []):
            route_counts.setdefault(key, [0, 0])
            route_counts[key][0] += 1
            delay_totals.append(_severity_to_minutes(ev.get("severity")))

    # Incorporate explicit samples
    for s in get_collection("ml_training_samples").find({"type": "delay"}):
        route = s.get("route") or ""
        route_counts.setdefault(route, [0, 0])
        route_counts[route][1] += 1
        if s.get("delayHappened"):
            route_counts[route][0] += 1
            delay_totals.append(float(s.get("delayMinutes", 170)))
        airline = s.get("airline")
        if airline:
            airline_risk.setdefault(airline, [0, 0])
            airline_risk[airline][1] += 1
            if s.get("delayHappened"):
                airline_risk[airline][0] += 1

    avg_minutes = int(sum(delay_totals) / len(delay_totals)) if delay_totals else 170
    airline_probs = {k: (v[0] / v[1] if v[1] else 0.18) for k, v in airline_risk.items()}

    params = {
        "route_counts": {k: [v[0], v[1]] for k, v in route_counts.items()},
        "airline_risk": airline_probs,
        "base_delay_prob": _compute_base_prob(route_counts),
        "avg_delay_minutes": avg_minutes,
    }
    delay_model.save_state(delay_model.KEY, params, len(route_counts))
    return {"routes": len(route_counts), "avgMinutes": avg_minutes}


def _severity_to_minutes(severity):
    if severity == "HIGH":
        return 300
    if severity == "MEDIUM":
        return 200
    return 90


def _compute_base_prob(route_counts):
    delayed = sum(v[0] for v in route_counts.values())
    total = sum(v[1] for v in route_counts.values())
    if total == 0:
        return 0.18
    return delayed / total


def train_all():
    \"\"\"Train all models and return a summary.\"\"\"
    return {
        "cost": train_cost(),
        "timing": train_timing(),
        "delay": train_delay(),
    }

""",
    'train': """\"\"\"Full ML training pipeline (spec §21): retrain everything and refresh metrics.

Reuses the classical trainer (cost regression, timing averages, delay
frequencies) and adds metric computation + registry version bumps so
`/api/admin/ml/train` produces a complete audit log with MAE/RMSE/R²,
interaction counts, cluster quality (silhouette), and status labelling.
\"\"\"
import math
from datetime import datetime
from services.mongodb import get_collection
from services.ml import registry, cost_model, timing_model, delay_model
from services.ml.trainer import train_cost, train_timing, train_delay
from services.ml.features import trip_features
from services.ml import reco, cluster, collab, demand as demand_mod, anomaly as anomaly_mod


def _mae_rmse_r2(actuals, preds):
    n = len(actuals)
    if not n:
        return None, None, None
    mae = sum(abs(a - p) for a, p in zip(actuals, preds)) / n
    rmse = math.sqrt(sum((a - p) ** 2 for a, p in zip(actuals, preds)) / n)
    mean = sum(actuals) / n
    ss_tot = sum((a - mean) ** 2 for a in actuals)
    ss_res = sum((a - p) ** 2 for a, p in zip(actuals, preds))
    r2 = 1.0 - ss_res / ss_tot if ss_tot else None
    return round(mae, 2), round(rmse, 2), (round(r2, 4) if r2 is not None else None)


def _eval_cost():
    samples = []
    for t in get_collection("trips").find({}):
        est = t.get("totalEstimatedCost")
        itin = sum((it.get("totalCost") or 0) for it in (t.get("itineraries") or []))
        label = itin or est or (t.get("budget", 50000) * 0.9)
        try:
            samples.append((trip_features(t), float(label)))
        except Exception:
            continue
    for s in cost_model.get_training_samples():
        try:
            samples.append((trip_features(s.get("features") or {}), float(s.get("label", 0))))
        except Exception:
            continue
    if not samples:
        return None, 0
    try:
        coefs, intercept = cost_model._train_batch(samples)
    except Exception:
        coefs, intercept = cost_model.get_model()[0].get("coefs"), cost_model.get_model()[0].get("intercept", 0)
    preds = [sum(coefs[i] * f[i] for i in range(len(coefs))) + intercept for f, _ in samples]
    actuals = [a for _, a in samples]
    mae, rmse, r2 = _mae_rmse_r2(actuals, preds)
    return {"samples": len(samples), "MAE": mae, "RMSE": rmse, "R2": r2}, len(samples)


def _eval_clusters():
    docs = list(get_collection("tourist_spots").find({"status": "APPROVED"}))
    if len(docs) < 3:
        return None
    from services.ml.cluster import cluster_spots, _kmeans, _cat_code, _euclid, _spot_coords
    from services.ml.reco import _booked_counts
    doc_ids = [str(d["_id"]) for d in docs]
    pop = _booked_counts("spotId")
    pops = list(pop.values())
    max_pop = max(pops) if pops else 1
    pts = []
    for d in docs:
        lat, lng = _spot_coords(d)
        pts.append([lat / 90.0, lng / 180.0,
                    _cat_code(d.get("category")),
                    min(1.0, pop.get(str(d["_id"]), 0) / max_pop)])
    k = max(2, min(5, len(docs)))
    labels, _ = _kmeans(pts, k)
    groups = {}
    for i, c in enumerate(labels):
        groups.setdefault(c, []).append(i)
    centers = {}
    for c, idxs in groups.items():
        centers[c] = [sum(pts[i][j] for i in idxs) / len(idxs) for j in range(len(pts[0]))]
    sil = 0.0
    for i, c in enumerate(labels):
        same = [j for j in groups[c] if j != i]
        a = _euclid(pts[i], centers[c])
        others = [cc for cc in centers if cc != c]
        b = min(_euclid(pts[i], centers[o]) for o in others) if others else a
        sil += (b - a) / max(b, a, 1e-9)
    return {"clusters": len(groups), "silhouette": round(sil / len(labels), 4)}


def _eval_reco():
    out = {}
    for key, fn in [("tourist_spot_recommendation", reco.recommend_spots),
                    ("hotel_recommendation",
                     lambda u, **kw: reco.recommend_hotels(u, trip=None, **kw)),
                    ("transport_recommendation",
                     lambda u, **kw: reco.recommend_transports(u, "", "", **kw)),
                    ("guide_recommendation", reco.recommend_guides)]:
        try:
            _, n, gap = fn({}, **({"limit": 10} if key != "hotel_recommendation" else {}))
        except Exception as exc:
            out[key] = {"status": "ERROR", "message": str(exc)}
            continue
        out[key] = {"catalogSize": n, "status": gap}
    return out


def train_all():
    start = datetime.utcnow()
    trained_at = start.isoformat()

    cost_stats, cost_samples = _eval_cost()
    cost_reg = _retrain_unless(cost_stats)
    timing = train_timing()
    delay = train_delay()
    clusters = _eval_clusters()
    reco_stats = _eval_reco()
    _, segs_gap = cluster.segment_users()
    collab_row, collab_samples, collab_gap = collab.factorize()
    _, demand_samples = demand_mod.predict_demand(days=7)
    anomaly_rows, anomaly_samples, anomaly_gap = anomaly_mod.flag_anomalies()

    registry.upsert("travel_cost_prediction", version=1,
                    metrics=(cost_stats or {}), samples=cost_samples,
                    status=("ACTIVE" if cost_samples else "INITIAL"),
                    trained_at=trained_at)
    registry.upsert("travel_time_prediction", version=1,
                    metrics={"durations": timing["durations"], "samples": sum(timing["samples"].values())},
                    samples=sum(timing["samples"].values()), status="ACTIVE", trained_at=trained_at)
    registry.upsert("delay_prediction", version=1,
                    metrics={"routes": delay["routes"], "avgDelayMinutes": delay["avgMinutes"]},
                    samples=delay["routes"], status="ACTIVE", trained_at=trained_at)
    for name, stats in reco_stats.items():
        registry.upsert(name, version=1,
                        metrics={"catalogSize": stats.get("catalogSize", 0)},
                        samples=int(stats.get("catalogSize", 0) or 0),
                        status=stats.get("status", "INITIAL"), trained_at=trained_at)
    if clusters:
        registry.upsert("tourist_spot_clustering", version=1, metrics=clusters,
                        samples=len(list(get_collection("tourist_spots").find({"status": "APPROVED"}))),
                        status="ACTIVE", trained_at=trained_at)
    registry.upsert("user_segmentation", version=1,
                    metrics={"kmeans": "pure-python"}, samples=0,
                    status=segs_gap, trained_at=trained_at)
    registry.upsert("collaborative_filtering", version=1,
                    metrics={"interactions": collab_samples}, samples=collab_samples,
                    status=collab_gap, trained_at=trained_at)
    registry.upsert("demand_prediction", version=1,
                    metrics={"historySamples": demand_samples}, samples=demand_samples,
                    status=("ACTIVE" if demand_samples else "INITIAL"), trained_at=trained_at)
    registry.upsert("anomaly_detection", version=1,
                    metrics={"samples": anomaly_samples, "flagged": len(anomaly_rows)},
                    samples=anomaly_samples, status=anomaly_gap, trained_at=trained_at)
    for name in ("content_based_recommendation", "visiting_time_recommendation",
                 "personalized_trip_ranking", "safe_delay_feature",
                 "popularity_recommendation", "trending_spot_detection",
                 "transit_quality_estimation", "transport_fare_prediction",
                 "tour_package_rating", "cold_start_estimator"):
        if not registry.get_model(name):
            registry.mark_used(name, features="cold-start priority", target="ready placeholder")

    return {
        "trainedAt": trained_at,
        "cost": cost_stats,
        "timing": {"durations": timing["durations"], "samples": timing["samples"]},
        "delay": {"routes": delay["routes"], "avgDelayMinutes": delay["avgMinutes"]},
        "clusters": clusters,
        "recommendationModels": reco_stats,
        "collaborativeFiltering": {"status": collab_gap, "interactions": collab_samples},
        "demand": {"samples": demand_samples},
        "anomaly": {"samples": anomaly_samples, "flagged": len(anomaly_rows)},
        "elapsedMs": int((datetime.utcnow() - start).total_seconds() * 1000),
    }


def _retrain_unless(cost_stats):
    if cost_stats and cost_stats["samples"] > 0:
        return train_cost()
    return {"samples": 0, "message": "skipped (no cost samples)"}
""",
}

_PARENT = sys.modules[__name__]
_ALIASES = {}
for _n in __all__:
    _m = types.ModuleType("services.ml." + _n)
    _m.__package__ = "services.ml"
    sys.modules["services.ml." + _n] = _m
    _ALIASES[_n] = _m
    setattr(_PARENT, _n, _m)
for _n in __all__:
    _code = compile(_SRC[_n], 'services.ml.' + _n, 'exec')
    exec(_code, _ALIASES[_n].__dict__)
del _SRC, _PARENT, _ALIASES, _m, _n, _code
