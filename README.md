# TripMind AI

**One Journey. One AI. Zero Travel Hassle.**

An AI-powered travel orchestration platform that plans, optimizes, books, and adapts your entire journey from doorstep to destination.

---

## Technology Stack

| Layer | Technology |
|-------|-----------|
| Frontend | HTML5, CSS3, Vanilla JavaScript |
| Backend | Python, Flask |
| Database | MongoDB Atlas |
| AI | Groq API (llama-3.3-70b-versatile) |
| ML | Pure-Python online models (no external libs) |
| Optimization | ML-enhanced multi-criteria scoring engine |

## Architecture

```
Frontend (HTML/CSS/JS)
        |
        | REST API / Fetch
        v
Python Flask Backend
        |
        v
MongoDB Atlas
```

## Project Structure

```
tripmind-ai/
├── frontend/
│   ├── index.html           # Landing page
│   ├── login.html           # Sign in (all roles)
│   ├── register.html        # Public account creation
│   ├── portal.html          # Role-aware portal dashboard (ADMIN/TRANSPORT/TOURIST/GUIDE/USER)
│   ├── css/style.css        # Global styles
│   ├── js/
│   │   ├── api.js           # API helper
│   │   ├── utils.js         # Utility functions
│   │   ├── chat.js          # AI chat widget
│   │   └── portal.js        # Portal controller (role panels, dynamic transport forms)
│   └── pages/
│       ├── dashboard.html   # Trip dashboard
│       ├── planner.html     # Trip planner
│       ├── trip.html        # Trip detail + 5 tabs
│       └── mindmap.html     # Route journey mind map (KPR → Coimbatore → Chennai)
├── backend/
│   ├── app.py               # Flask app entry (registers all blueprints)
│   ├── config.py            # Configuration (roles, SECRET_KEY, GOOGLE_MAPS_API_KEY, DEV_MODE)
│   ├── requirements.txt     # Python dependencies
│   ├── routes/
│   │   ├── trips.py         # Trip API routes (multi-user)
│   │   ├── ai.py            # AI chat route
│   │   ├── mindmap.py       # Route mind-map flow endpoint
│   │   ├── auth.py          # Register / login / logout / me / profile
│   │   ├── transport.py     # Transport service profile + register/search/approve
│   │   ├── tourist.py       # Tourist spots + authorize guide locations
│   │   ├── guides.py        # Guide profile / availability / pricing
│   │   ├── bookings.py      # Bookings (transport seats / spots / guides)
│   │   ├── ratings.py       # User ratings for bookings (feeds ML feedback loop)
│   │   ├── ml.py            # ML recommendation / prediction / train endpoints
│   │   ├── analytics.py     # Provider dashboards (real DB aggregates per role)
│   │   └── admin.py         # Admin analytics + account & content approval
│   └── services/
│       ├── mongodb.py       # MongoDB connection
│       ├── auth.py          # RBAC: sessions, hashed passwords, role decorators
│       ├── groq_service.py  # Groq API integration
│       ├── travel_orchestrator.py  # Plan generation (DB catalogue preferred, mock fallback)
│       ├── travel_optimizer.py     # Multi-criteria optimizer (ML budget split)
│       ├── trip_optimizer.py       # DB-backed planner (real transports/spots/guides + ML timings)
│       ├── mock_flight_service.py  # Flight search (fallback)
│       ├── mock_hotel_service.py   # Hotel search (fallback)
│       ├── mock_transport_service.py  # Transport search (fallback)
│       ├── mock_activity_service.py   # Activities & food (fallback)
│       ├── transport_service.py  # Bus/Train/Flight/Cab/Auto data + validation
│       ├── tourist_service.py    # Tourist spot data + guide-location authorization
│       ├── guide_service.py      # Guide profile/availability/pricing, browsing
│       ├── booking_service.py    # Bookings with capacity/overbooking checks
│       ├── ratings_service.py    # Ratings data layer + per-service stats
│       ├── ai_chat.py       # Chat logic
│       ├── route_mindmap.py # KPR → Coimbatore → Chennai journey flow data
│       └── ml/              # Pure-Python Machine Learning
│           ├── registry.py      # Model registry + versioning (/ml/models)
│           ├── definitions.py   # 17 labelled model specs + P1-P3 priorities
│           ├── reco.py          # Hybrid recommenders (spots/hotels/transports/guides)
│           ├── content.py       # Content-based similarity (spots/hotels/tours)
│           ├── cluster.py       # K-Means (spots + user segments)
│           ├── collab.py        # SGD matrix-factorization collaborative filtering
│           ├── demand.py        # Week/season booking-demand forecast
│           ├── anomaly.py       # Pure-python isolation-score anomaly detection
│           ├── visiting_time.py # Optimal visiting-time windows
│           ├── inference.py     # Labelled inference envelope ({model,status,version,result})
│           ├── train.py         # train_all() -> metrics + registry version bumps
│           ├── features.py      # Trip/Event -> numeric features
│           ├── cost_model.py    # Linear regression cost prediction
│           ├── timing_model.py  # Learned per-item durations
│           ├── delay_model.py   # Delay frequency classifier
│           ├── trainer.py       # Recompute model params
│           ├── database.py      # Persist ml_state to MongoDB
│           └── injector.py      # Integrate ML into routes/orchestrator
├── scripts/
│   ├── seed_ml_data.py     # Seed synthetic historical data
│   ├── seed_dev.py         # Seed test accounts + sample transport/spots/guides
│   └── clean_dev.py        # Clear test bookings/trips, keep seeded catalogue
├── .env                     # Environment variables (gitignored)
├── .env.example             # Environment template
├── .gitignore
└── README.md
```

## Setup Instructions

### Prerequisites

- Python 3.10+
- MongoDB Atlas account (free tier)

### Installation

```bash
# Clone and enter the project
cd tripmind-ai

# Create virtual environment
python -m venv venv

# Activate virtual environment
# Windows:
venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate

# Install dependencies
cd backend
pip install -r requirements.txt

# Go back to root
cd ..

# Set up environment variables
# Copy .env.example to .env and fill in your values
```

### Environment Variables

Create a `.env` file in the project root:

```env
MONGODB_URI="mongodb+srv://your-connection-string"

AI_PROVIDER="groq"
AI_API_KEY="your_groq_api_key"
AI_MODEL="llama-3.3-70b-versatile"

APP_URL="http://localhost:5000"

ML_ENABLED="true"

# Auth / role-based access
SECRET_KEY="change-me-in-production"

# Multi-user platform
DEV_MODE="true"                  # dev-only shortcuts (demo credential shortcut, no prod gating)

# Google Maps (optional — add your key to enable pickers, never commit it)
GOOGLE_MAPS_API_KEY=""
```

### Run the Application

```bash
cd backend
python app.py
```

Open `http://localhost:5000` in your browser.

## Multi-User Platform

TripMind AI is a role-based travel management, booking and optimization platform.
Access is enforced in the backend (`services/auth.py` + Flask session cookies,
hashed with `werkzeug`), never just in the UI.

### Roles & RBAC

| Role | Capabilities |
|------|-------------|
| **ADMIN** | Analytics dashboard, approve/reject transports & spots, view all bookings |
| **TRANSPORT_ADMIN** | Company profile (service name auto-applied to all vehicles), register Bus / Train / Flight / Cab / Auto |
| **TOURIST_SPOT_ADMIN** | Publish tourist spots with recommended time slots & maps coords, authorize guide locations |
| **GUIDE** | Profile, pricing (₹/hr, ₹/day), availability calendar — only at tourist-admin-authorized locations |
| **USER** | Plan AI trips, search transports, book seats/guides, browse catalogue |

### Test accounts (Dev only)

`python backend/scripts/seed_dev.py` (idempotent) creates:

| Email | Password | Role |
|-------|----------|------|
| `admin@tripmind.com` | `admin@123` | ADMIN (main dev Admin) |
| `admin@tripmind.test` | `Admin@12345` | ADMIN |
| `transport@tripmind.test` | `Transport@12345` | TRANSPORT_ADMIN (Kovai Express Coaches) |
| `tourist@tripmind.test` | `Tourist@12345` | TOURIST_SPOT_ADMIN |
| `hotel@tripmind.test` | `Hotel@12345` | HOTEL_ADMIN |
| `guide@tripmind.test` | `Guide@12345` | GUIDE |
| `user@tripmind.test` | `User@12345` | USER |

Pending provider accounts (all use `Password@12345`): `pendingtransport@`,
`pendingtourist@`, `pendinghotel@`, `pendingguide@tripmind.test`. They start
`PENDING` so the Admin approval flow can be tested end-to-end.

Seed also loads sample catalogue data: KPR→Chennai night bus (seat validation
`Sleeper+Seater=Total`), Kovai Express train with SL/CC coaches, a CJB→MAA
flight, cab & auto, 4 Chennai tourist spots, and authorized guide locations
(Mylapore, Marina Beach, Egmore).

### Transport registration rules

- **Dynamic per-type forms** (Bus/Train/Flight/Cab/Auto) — fields change by type.
- **Bus:** `Sleeper Seats + Seater Seats == Total Seats` enforced on both client
  and server, day numbers (`Day 0`…) + 24-hour times, intermediate stops.
- **Train:** coach configuration with configurable codes/counts/capacity/price;
  capacity = Σ(coachCount × capacityPerCoach).
- **Service name always comes from the transport admin's profile** — never
  re-entered on each vehicle.

### Guide authorization

Guides can only be assigned locations added by a tourist spot admin
(`guide_locations` collection). Setting availability for an unauthorized
location is rejected server-side.

## Machine Learning

The app ships a **pure-Python ML layer (17 models, no scikit-learn/numpy)** that
drives all recommendations and predictions while staying lightweight. Model
parameters persist to MongoDB (`ml_state`, `ml_models` registry, `ml_training_samples`).

### Models & priorities

Priorities (P1 = core, P3 = advanced): the registry + a trained-state label
(`ACTIVE` / `INITIAL` / `COLD_START`) are returned on `/api/ml/status` and every
inference, so the frontend never claims "ML" without the data to back it.

| Model | What it does | How it learns |
|-------|-------------|---------------|
| **Cost prediction** (`cost_model.py`) | Predicted total cost + smart budget split | Linear regression (normal equations) over historical trip costs |
| **Timing / duration** (`timing_model.py`) | Realistic durations per item type | Averages of actual itinerary start→end durations |
| **Delay prediction** (`delay_model.py`) | Delay probability + severity + buffer | Frequency counting over travel events + simulated delays |
| **Tourist-spot recommender** (`reco.py`) | Hybrid popularity/content/rating ranking | Book counts, rating stats, text similarity |
| **Hotel recommender** (`reco.py`) | Availability + rating + content ranking | Live availability (`total−booked−blocked>0`), ratings, similarity |
| **Transport recommender** (`reco.py`) | Corridor-aware transport ranking | Type preference + ratings + fare normalization |
| **Guide recommender** (`reco.py`) | Skill/interests matching + availability | Profile similarity + availability gating |
| **Content-based similar items** (`content.py`) | Similar spots/hotels/tours | Tag/description text similarity |
| **Spot clustering** (`cluster.py`) | K-Means spot groups | Book-driven popularity + category features |
| **User segmentation** (`cluster.py`) | Travel-style segments | Preference/book histograms |
| **Collaborative filtering** (`collab.py`) | Matrix factorization affinity + similar users | SGD over user↔service interactions (ratings/bookings) |
| **Demand forecast** (`demand.py`) | Week/season booking demand | Weekly/seasonal aggregates + trend |
| **Anomaly detection** (`anomaly.py`) | Outlier bookings/behaviour | Pure-python isolation score |
| **Visiting-time windows** (`visiting_time.py`) | Best time to visit each spot | Opening hours + crowd patterns |
| **Personalized trip ranking** (`inference.py`) | Rank generated plans for the user | Cost fit + optimization score + travel time |

### Ratings feedback loop

Users rate bookings they actually made (`/api/ratings`). Ratings persist both
`serviceType` and `serviceId`, so they automatically feed `reco._rating_stats`
and collaborative filtering — the ML models improve as real users rate.

### Learning lifecycle
- **Seed:** `python scripts/seed_ml_data.py` loads ~200 realistic synthetic trips.
- **Train:** `POST /api/admin/ml/train` (Admin) or
  `python -c "from services.ml.train import train_all; train_all()"` recomputes
  all models and bumps registry versions (`MAE/RMSE/R²` for cost, silhouette for
  clustering).
- **Reinforce:** as users generate/book trips and submit ratings, `injector.py`
  records new samples; re-training incorporates them.
- **Toggle:** set `ML_ENABLED="false"` to fall back to deterministic behaviour.

### Runtime response
On `/api/trips/:id/generate`, the response now includes an `ml` object:
```json
{
  "costPrediction": { "predictedCost": 172500, "budgetSplit": [...], "confidence": 0.95 },
  "delayPrediction": { "probability": 0.33, "severity": "MEDIUM", "suggestedBufferMinutes": 261 }
}
```
The cost prediction tunes sub-budget allocation and the timing model tunes itinerary scheduling automatically.

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/trips` | GET | List all trips |
| `/api/trips` | POST | Create a new trip |
| `/api/trips/:id` | GET | Get trip details |
| `/api/trips/:id/generate` | POST | Generate AI itinerary |
| `/api/trips/:id/itinerary` | GET | Get trip itineraries |
| `/api/trips/:id/book` | POST | Simulate booking |
| `/api/trips/:id/simulate-delay` | POST | Simulate flight delay |
| `/api/trips/:id/replan` | POST | AI replanning |
| `/api/trips/:id/events` | GET | Get travel events |
| `/api/ai/chat` | POST | AI chat assistant |
| `/api/mindmap/flow` | GET | KPR → Coimbatore → Chennai connected journey flow |
| `/api/auth/register` | POST | Public user registration (USER role) |
| `/api/auth/login` | POST | Login (sets session cookie) |
| `/api/auth/logout` | POST | Logout |
| `/api/auth/me` | GET | Current user |
| `/api/users/me` | GET/PATCH | Own profile |
| `/api/transport/services` | GET/POST | Transport admin service profile |
| `/api/transport/register` | POST | Register Bus/Train/Flight/Cab/Auto |
| `/api/transport/list` | GET | List transports (owner-scoped) |
| `/api/transport/:id` | GET/PUT | Transport detail / update |
| `/api/transport/:id/status` | POST | Approve / reject (ADMIN) |
| `/api/transport/search` | GET | Approved transports for a corridor |
| `/api/spots` | GET/POST | Tourist spots catalogue / publish |
| `/api/spots/:id` | GET/PUT | Spot detail / update |
| `/api/spots/:id/status` | POST | Approve / reject (ADMIN) |
| `/api/guide-locations` | GET/POST | Authorized guide-location list / add |
| `/api/guide/profile` | GET/PUT | Guide profile |
| `/api/guide/pricing` | POST | Guide pricing |
| `/api/guide/availability` | POST | Guide availability (authorized locations only) |
| `/api/guides` | GET | Browse guides (by location / date) |
| `/api/bookings` | GET/POST | My bookings / create booking |
| `/api/bookings/all` | GET | All bookings (ADMIN) |
| `/api/bookings/:id` | DELETE | Cancel booking |
| `/api/admin/stats` | GET | Platform analytics (ADMIN) |
| `/api/admin/users/:id/approval` | POST | Approve/reject/suspend a provider account (ADMIN) |
| `/api/admin/content-review` | GET | Provider-created resources awaiting approval (ADMIN) |
| `/api/admin/content/:kind/:id/review` | POST | Approve / reject a pending resource (ADMIN) |
| `/api/ratings/eligible` | GET | Bookings the logged-in user can still rate |
| `/api/ratings` | GET/POST | My ratings / submit a rating (1–5, comment ≤500) |
| `/api/ratings/service` | GET | Aggregate rating stats for a service (catalogue cards) |
| `/api/provider/stats` | GET | Role-scoped provider dashboard numbers (real DB aggregates) |
| `/api/ml/status` | GET | ML registry: models, versions, trained-at |
| `/api/ml/recommend/spots` | GET | ML-ranked tourist spots (cold-start → popularity labelled) |
| `/api/ml/recommend/hotels` | GET | ML-ranked, availability-gated hotels |
| `/api/ml/recommend/transports` | GET | Corridor-aware transport ranking |
| `/api/ml/recommend/guides` | GET | Guide matching + availability gating |
| `/api/ml/similar` | GET | Content-based similar spots/hotels/tours |
| `/api/ml/predict/cost` | GET | Predicted cost + budget split |
| `/api/ml/predict/time` | GET | Learned per-type durations |
| `/api/ml/clusters` | GET | Tourist-spot clusters |
| `/api/ml/segments` | GET | User segments |
| `/api/ml/affinity` | GET | Collaborative affinity / similar users |
| `/api/ml/demand` | GET | Booking-demand forecast |
| `/api/ml/anomalies` | GET | Outlier detection (ADMIN) |
| `/api/ml/visit-times` | GET | Best visiting-time windows for a spot |
| `/api/ml/trip-rank` | POST | Personalized ranking of generated plans |
| `/api/admin/ml/train` | POST | Re-train all ML models (ADMIN) |

## DB-Driven Planning

Planner (`/pages/planner.html`) is a two-step structured flow:
1. **Trip details** — origin/destination, dates, travelers, **budget with an
   "Unlimited" option** (`budgetUnlimited`, stored as budget `0`), travel style,
   and a **service preference** (Hotels / Transport / Activities / Guide).
2. **Prioritize tourist spots** — the ML recommender ranks approved spots
   (cold-start → ranked by popularity, labelled so users know). The user clicks
   spots in **priority order** (up to 4) — or "I Have No Choice" — and the
   optimizer places prioritized spots first, then fills the rest.

When a trip is generated, the planner queries live catalogue data
(`transports`, `tourist_spots`, `guides`, `hotels`) for the corridor and builds
the itinerary from real entities (`services/trip_optimizer.py`). ML remains the
decision engine — learned budget splits allocate spend, learned durations
schedule legs, and every activity carries a `bookableId`
(`spot:<id>` / `transport:<id>` / `hotel:<id>` / `guide:<id>`) so the plan is
bookable. Unlimited budgets treat spend as unconstrained (premium eligible).
If a corridor has no catalogue data, classic demo generators are the documented
fallback (`"source": "mock"`).

```json
{ "source": "db", "transport": { "type": "TRAIN", "trainNumber": "12675", ... },
  "budgetUnlimited": true, "prioritizedSpotIds": ["...", "..."] }
```

## Approvals & Ratings

**Provider & content approval (backend-enforced):**
- New provider registrations start `PENDING` and cannot log into provider
  features until an Admin approves them (`/api/admin/users/:id/approval`).
- Transport / hotel / spot / tour resources created by a provider default to
  `PENDING` and only become visible/bookable in public catalogues after an
  Admin approves them via the **Content Review** tab (or
  `/api/admin/content/:kind/:id/review`). Resources created by an Admin
  auto-approve. `auth.resource_status()` and `require_approved_provider` guard
  every service layer, so approval can never be bypassed in the UI.
- Editing an approved resource keeps its status and rejection reason.

**Ratings loop:** a USER rates a booking they actually made (and wasn't
cancelled). Each booking can be rated once; ratings feed the ML recommender and
collaborative filtering, and drive the rating shown on catalogue cards.

## Route Journey Mind Map

Open **Route Map** in the navigation (or `/pages/mindmap.html`) for a single, connected
travel pathway:

```
KPR → Coimbatore (Two-Wheeler / Car / Bus / Auto / Cab)
   → Transit Point (Railway Station / Central Bus Stand / Airport CJB)
   → Bus / Train / Flight (with all classes)
   → Chennai Arrival (MAA / MAS / MS / Kilambakkam)
   → Local Transport (Metro / Bus / Auto / Cab / Walk / Cycle)
   → [ Hotel (by category)   |   Tourist Spot Directly ]
   → Marina · Kapaleeshwarar · Fort St. George · San Thome · VGP
     · DakshinaChitra · Mahabalipuram · Guindy National Park
   → Next Spot (chain several)  →  Return / Continue Journey
```

- Every stage is connected; selecting an option highlights the full journey path
  in the sticky summary bar (e.g. KPR → Bus → Coimbatore → Train → Chennai Central
  → Metro → Hotel → Cab → Marina Beach).
- Transport methods, distances, durations and reach information are shown for each
  tourist spot and hotel from each arrival point.
- Asking the AI chat for the "travel flow / route / journey" returns only the
  flow content (mind-map output rule).
- The map is served from `GET /api/mindmap/flow` (backend) so the page stays
  dynamic and consistent with the rest of the app.

## Demo Flow

Trip planning is **login-first**: dashboard, planner, trip details and the
portal require an authenticated (non-demo) user and redirect to `/login.html`
when logged out. After login you land in the role-aware portal.

1. Open `http://localhost:5000`, click **Sign In** and use a test account
   (`user@tripmind.test` / `User@12345`) or a quick-sign-in button.
2. From the **Portal**, book transport / guides / hotels / tours, or open
   **My Statistics** to see live per-role numbers.
3. Click **Plan My Trip** → fill trip details (try the **Unlimited** budget and a
   **service preference**) → click ML-ranked spots in priority order → generate.
4. Compare plans, view timeline, cost breakdown, then **Approve & Book**.
5. Rate a completed booking under **Rate Bookings** — ratings update catalogue
   cards and feed the ML feedback loop.
6. Sign in as `transport@` / `tourist@` / `hotel@` / `guide@` / `admin@` to
   register resources (which start `PENDING`), publish spots, set guide slots,
   and approve accounts/content via the Admin portal.
7. **Provider dashboards** show real database aggregates (fleet/approvals/
   revenue/occupancy/assignments) — nothing mocked.

## Deployment (Render)

1. Push to GitHub
2. Create a new Web Service on Render
3. Build Command: `cd backend && pip install -r requirements.txt`
4. Start Command: `cd backend && python app.py`
5. Set environment variables in Render dashboard
6. Deploy

---

Built for the AI College Conclave. Educational prototype - no real bookings are made.
