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
| Optimization | Custom multi-criteria scoring engine |

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
│   ├── css/style.css        # Global styles
│   ├── js/
│   │   ├── api.js           # API helper
│   │   ├── utils.js         # Utility functions
│   │   └── chat.js          # AI chat widget
│   └── pages/
│       ├── dashboard.html   # Trip dashboard
│       ├── planner.html     # Trip planner
│       └── trip.html        # Trip detail + 5 tabs
├── backend/
│   ├── app.py               # Flask app entry
│   ├── config.py            # Configuration
│   ├── requirements.txt     # Python dependencies
│   ├── routes/
│   │   ├── trips.py         # Trip API routes
│   │   └── ai.py            # AI chat route
│   └── services/
│       ├── mongodb.py       # MongoDB connection
│       ├── groq_service.py  # Groq API integration
│       ├── travel_orchestrator.py  # Plan generation
│       ├── travel_optimizer.py     # Multi-criteria optimizer
│       ├── mock_flight_service.py  # Flight search
│       ├── mock_hotel_service.py   # Hotel search
│       ├── mock_transport_service.py  # Transport search
│       ├── mock_activity_service.py   # Activities & food
│       └── ai_chat.py       # Chat logic
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
```

### Run the Application

```bash
cd backend
python app.py
```

Open `http://localhost:5000` in your browser.

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

## Demo Flow

1. Open `http://localhost:5000`
2. Click **"Plan My Trip"** or **"Try Demo Trip"**
3. Describe your trip or fill in the form
4. AI generates 3 plans (Budget/Balanced/Premium)
5. Compare plans, view timeline, check cost breakdown
6. Click **"Approve & Book"** for simulated booking
7. Click **"Simulate Delay"** to test AI replanning
8. Use the floating chat assistant for questions

## Deployment (Render)

1. Push to GitHub
2. Create a new Web Service on Render
3. Build Command: `cd backend && pip install -r requirements.txt`
4. Start Command: `cd backend && python app.py`
5. Set environment variables in Render dashboard
6. Deploy

---

Built for the AI College Conclave. Educational prototype - no real bookings are made.
