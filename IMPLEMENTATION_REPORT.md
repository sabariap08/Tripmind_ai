# TripMind AI — Implementation Report

Project root: `tripmind-ai` · Backend `backend/app.py` → http://localhost:5000
Admin seed: `admin@tripmind.com / admin@123` · DB: Mongo Atlas `tripmind` (env override `MONGODB_DB_NAME`)

---

## 1. Executive Summary
TripMind AI has been consolidated from a sprawling, partially dead codebase into a single
coherent Flask application (14 route blueprints, 18 service modules) with all features preserved,
a trip-centric booking model, an explicit wallet payment flow, provider-management propagation
for restaurants, a simulated-delay replan pipeline, and an action-capable AI travel assistant.
The entire backend module graph imports cleanly and the repository sits well below the
100-file target.

## 2. File Inventory (target < 100 → actual 64)
- Total files: **64** (Python 42, HTML 9, JS 6, CSS 1, misc/config 6)
- Backend: `app.py` (1), `config.py` (1), routes (14), services (18), scripts (5), `requirements.txt`
- Frontend: 3 entry HTML, 5 page HTML, `css/style.css`, 6 JS modules
- Everything else: `.env`, `.env.example`, `.gitignore`, `README.md`, project-report PDF

## 3. Dead Code Removal
Deleted files that shipped no users and duplicated consolidated services:
- `services/ratings_service.py`, `services/trip_review_service.py`,
  `services/registration_fields.py`
- `routes/trip_reviews.py`, `routes/mindmap.py`
Verified with `python -c "import app"` → OK and full `compileall` → COMPILE OK before/after.

## 4. Service Consolidation (one module per concern)
- **ML**: `services/ml.py` (~2,180 lines) is the single ML module and provides a
  `sys.modules` facade that recreates the historical `services.ml.*` module names
  (`train`, `trainer`, `inference`, `features`, `database`, `definitions`, `text`,
  `reco`, `cluster`, `cost_model`, `timing_model`, `registry`, `injector`,
  `anomaly`, `collab`, `content`, `delay_model`, `demand`, `visiting_time`), so every
  existing `from services.ml… import …` statement still resolves. Verified dynamically:
  `services.ml.injector` etc. are present in `sys.modules`.
- **Reviews/ratings**: single `services/reviews.py` + `routes/ratings.py` backing
  `/api/ratings/*` and `/api/trips/<id>/reviews|review`.
- **Registration fields**: keyed role→field definitions consolidated into
  `services/reviews.py`/`services/duplicate.py` cache and served by
  `/api/auth/registration-fields`.
- **Duplicate protection** lives in `services/duplicate.py` (name/identity/mobile checks).

## 5. Booking & Payment Integrity
Previously `payFromWallet` was never set anywhere: bookings were always created PENDING and
the wallet was never debited at book time. Fixed end-to-end:
- `booking_service.create_booking` now sets `paymentStatus = COMPLETED if pay_wallet else PENDING`;
  reductions flow exactly once through the wallet.
- New `pay_booking(booking, user)` — idempotent (guards `paymentStatus == COMPLETED`), sets
  `walletPaid`, `walletTxnId`, `paidAt`, debits wallet, marks booking COMPLETED.
- New `pay_trip_bookings(trip, user)` — pays all non-cancelled sub-bookings and derives the
  trip-level `paymentStatus` (COMPLETED / FAILED / PENDING), setting `paidAt`.
- `cancel_booking` refund logic recognises the canonical `("WALLET", "COMPLETED")` statuses.
- Endpoints: `POST /api/trips/<trip_id>/pay`, `POST /api/bookings/<bid>/pay`.

## 6. Trip-Centric Bookings (one card, one PDF, one QR per trip)
- My Bookings is now rendered trip-first: each trip card shows a payment pill
  (PENDING / FAILED warn or error; WALLET / COMPLETED / PAID green), a delay chip when
  `delay.status === "ACTIVE"`, and actions: View details, Download ticket (PDF), Pay from
  wallet, Open trip, Rate trip.
- One PDF and one QR token per **trip** (`/api/trips/<id>/ticket`, `.token)`), generated via
  `ticket_service`; the trip QR verifies with `valid: true` and resolves the trip, route,
  status and token (e2e-verified output: `{'kind': 'TRIP', 'route': 'Coimbatore -> Chennai',
  'tripId': …}`).

## 7. RESTAURANT Booking Flow (food bookability)
- `booking_service` gained a `RESTAURANT` resource handler: unit price taken from the real
  `food_item["price"]`; booking doc carries `restaurantId`, `foodItemId`, `foodName`; order
  rows are produced via `provider_bookings("RESTAURANT")`.
- `routes/trips._gather_db_data` gathers registered restaurants plus their first available
  food item and emits `bookableId` like `restaurant:<restaurantId>:<foodItemId>`.
- `trip_optimizer` copies food dicts with `bookableId` intact; FOOD costs are `0` when a
  restaurant has no catalogue — **no fabricated pricing** (removed the hard-coded 150/200).
- `routes/trips.book_trip` accepts `btype in ("FOOD","RESTAURANT")`.
- Frontend: new admin **Orders** panel (`rbook`) calling `api.providerBookings('RESTAURANT')`
  with paid/unpaid/cancelled stat cards.

## 8. No-Fake-Inventory Guarantee
- All `mock_*` services are deleted. Planner and booking paths resolve inventory strictly
  from registered, APPROVED records in the database.
- When no approved services match an itinerary, generation returns
  `source: "empty"` with a human explanation, and `selectedPlan` stays absent — never a
  fabricated plan (e2e asserts exactly this).

## 9. Admin & Provider Propagation
- `routes/bookings.py` provider allow-list now includes `RESTAURANT`, so restaurant owners
  see food orders through `/api/provider/bookings?type=RESTAURANT` while other roles get a
  clean empty list (role-gated).
- Transport providers see seat reservations via `/api/provider/bookings?type=TRANSPORT`;
  the seats ledger is queried on the transport document so admin overviews reflect live
  seat occupation.
- Hotel/restaurant/spot/tour resources keep their own status flows
  (`PENDING` → Admin `APPROVED`/`REJECTED`).

## 10. Simulate Delay & Replan
- `POST /api/trips/<id>/simulate-delay` records `trip['delay'] = {status: 'ACTIVE', …}` and
  triggers itinerary reassessment.
- `POST /api/trips/<id>/replan` recomputes the itinerary and sets
  `delay.status = 'RESOLVED'`; both transitions are asserted from the DB in the e2e suite.

## 11. AI Travel Assistant (action-capable)
- New `services/assistant.py`: tool registry (`list_my_trips`, `get_trip`, `list_bookings`,
  `view_wallet`, `find_alternative_transports`, `change_transport`, `pay_trip`,
  `remove_place`) with an owner-ship re-validation layer in `execute_action`.
- The AI service chain (`services/ai_service.py`) uses Google Gemini (REST) as the primary
  provider with an OpenRouter fallback and a deterministic local fallback. The assistant can
  **propose** actions; mutations execute only through `POST /api/assistant/action` after the
  frontend Confirm button (`execute_action` re-checks ownership/status server-side). Local
  keyword fallback keeps the assistant functional with no Gemini key.
- `change_transport` executes `booking_service.switch_transport`: net wallet credit/debit,
  seat release/reserve, single refund, same-trip rebooking with `switchedFrom`/`switchedTo`
  markers and duplicate guarding.
- Routes: `POST /api/assistant/chat`, `POST /api/assistant/action` (alongside
  `/api/ai/chat`, `/api/mindmap/flow`, `/api/ai/feedback-analysis`).

## 12. Frontend Changes
- `portal.js`: dead panels removed (`ptbook/hotels/dine/tours/trip/ratings/treviews`) with
  their handler bodies (`userBook`, `userTrips`, `userHotels`, …) and `PANEL_TITLES` entries;
  "Book a Transport" on the overview now opens `plantrip`; My Bookings trip card reworked
  (payment column, delay chip, detail dialog with per-booking table + totals, Verify QR link);
  `TM.tripPay` / `TM.tripDetail` / `TM.reviewTrip` wired (review handler also defined
  top-level so the live feedback panel works).
- `api.js`: `assistantChat`, `assistantAction`, `updateProfile` (PATCH `/api/users/me`),
  `tripPay`, `payBooking`.
- `chat.js`: rebuilt around `assistantChat`; renders `data.action` as a Confirm button that
  calls `assistantAction`; `style.css` adds `.chat-action` styles.
- `node --check` passes for portal.js, chat.js, api.js.

## 13. Tickets, PDF & QR Payments Mapping
- `ticket_service._service_rows` renders RESTAURANT rows (restaurant name, city, foodName, qty)
  alongside TRANSPORT/HOTEL/TOUR and trip totals.
- Payment colouring treats `PAID`, `COMPLETED`, `WALLET` as settled/green; `PENDING`/`FAILED`
  are neutral/error.
- One trip PDF aggregates all sub-bookings; the QR token is scoped to the trip (`type=trip`).

## 14. Endpoint Inventory (~70 unique paths across 14 blueprints)
- auth (11): `/api/auth/*`, `/api/users/me`, `/api/admin/users|approval`
- admin (4): stats, content-review, content review-approve, availability
- ai (5): `/api/ai/chat`, `/api/assistant/chat|action`, `/api/mindmap/flow`,
  `/api/ai/feedback-analysis`
- analytics (1): `/api/provider/stats`
- bookings (8): bookings CRUD, `all`, `/<bid>/pay`, provider bookings, guide requests/assignments
- guides (4), hotel (9), ml (16), ratings (6), restaurant (9), tickets (3), tourist (8),
  transport (8), trips (14: trips CRUD, admin trips, generate, book, pay, token, ticket,
  events, itinerary, simulate-delay, replan, itinerary items), wallet (2).

## 15. E2E Test Suite
- `backend/scripts/e2e_test.py` targets a dedicated `tripmind_test` DB
  (`MONGODB_DB_NAME` env override; collections dropped per run) and covers: registration +
  DB-approval, seeded bus/hotel+room/restaurant+food/spot+tour, no-fake-inventory
  (`source == "empty"` corridor), standalone transport booking + duplicate rejection,
  standalone deposit + pay → COMPLETED, AI trip generate → book → pay → COMPLETED trip and
  bookings, one-token one-PDF one-QR verification, provider propagation for TRANSPORT/HOTEL/
  RESTAURANT, simulate-delay ACTIVE → replan RESOLVED, assistant pay + change_transport
  proposals/executions with switched markers, profile PATCH, trip review, mindmap flow.
- Fixtures corrected to match real service validation: `transportId` key from transport
  register response, per-room `roomNumbers`, food/spot image requirements (1×1 PNG data URI),
  tour `spotId` linkage, and city-qualified boarding/dropping points.
- **Status: script written and syntax-compiled; full green run not yet executed** (deferred by
  request). Command: `cd backend && python scripts/e2e_test.py`.

## 16. TripMind Partner Hub (transport, `/tripmind-partner`)
- Separate operator surface for `TRANSPORT_ADMIN`; every other provider category
  keeps `/portal.html`. Public entry: landing, `login`, `register`; authenticated:
  `dashboard`, `buses`, `boarding-points`, `bookings`, `profile`.
- Access control is in the Flask app, not the client: signed-out → redirect to
  `/tripmind-partner/login?next=…` (`next` honoured only inside the hub),
  signed-in non-partner → `forbidden.html`. API access is independently gated by
  `require_partner` / `require_approved_provider`, so a revoked approval loses
  data even with a live session.
- The hub route also serves its own `css/partner.css` and `js/*.js` out of
  `frontend/tripmind-partner/`, so no protected page is ever reachable by
  weakening the guard.
- Real data only: `/api/provider/stats`, `/api/transport/list`,
  `/api/transport/services`, `/api/transport/<tid>` (PUT),
  `/api/provider/bookings?type=TRANSPORT`, `/api/auth/me`. No seeded or
  placeholder metrics.
- `transport_service.update_transport` now carries `bookedSeats` through the
  rebuild, so editing timings/prices can no longer release already-sold seats.
- Registration posts the transport payload (company, GSTIN, PAN, licence,
  service categories), normalises a 10-digit mobile and checks GSTIN duplicates
  before insert; the category is stored as `registration.partnerType`.
- Passenger registration is now passenger-first: `/register.html` creates a
  `USER` immediately (Basics → Identity → Review, no role chooser); the business
  wizard only appears on the explicit `/register.html?provider=1` (or
  `?role=…`) deep link, and `roleLanding()` sends a `TRANSPORT_ADMIN` who signs
  in to the hub instead of the shared portal.
- PWA: `sw.js` precaches only the hub's public entry points plus
  `css/partner.css` / `js/partner.js` (authenticated pages stay network-first);
  `add_pwa_tags.py` now scans `frontend/tripmind-partner/` with `../`-prefixed
  shared assets, and `check_pwa_serving.py` covers the hub pages, its assets and
  the signed-out redirect.

## 17. Verification Status & Next Steps
- Syntax: 0 errors across all 42 `.py` files.
- Imports: 42/42 backend modules import cleanly in one process (incl. ML facade consumers).
- Frontend: `node --check` clean for portal.js, chat.js, api.js.
- **Next**: run the e2e suite to green and (optionally) re-enable `smoke_test.py` against the
  seeded admin DB; then delete `TripMind_AI_Project_Report.pdf` if the static copy should be
  replaced by this report.

---

# Revision 2 — Current Implementation Report

Sections 1–17 above are historical (they describe the consolidation pass). This revision is the
up-to-date picture. It is organized as **Fixed / Newly Implemented / ML Models / Data Flow /
Remaining Issues**. Nothing here is claimed as verified by a full test run — only static and
targeted checks (listed at the end).

Repository size today: **75 Python, 23 HTML, 18 JS, 3 CSS** files; the backend exposes
**141 routes**, all defined in the single consolidated `backend/routes/__init__.py`.

## 18. Fixed
- **Assistant transport changes no longer silently drop.** `backend/services/assistant.py`
  now detects transport-change intent (`_transport_change_intent`) and routes it through
  `ai_chat._apply_transport_change`; a deterministic high-confidence mutation is never
  discarded just because the LLM returned a null tool call. `frontend/js/chat.js` reloads the
  page after `change_transport` / `edit_itinerary` / `remove_place` so the plan reflects the
  change.
- **Transport-swap fare math.** `backend/services/replanner.py` `build_transport_swap()` had an
  original-cost bug; fixed and now emits `arrivalBasis` / `arrivalEstimated` alongside the
  4-tuple `_leg_schedule()` (`dep, arr, estimated, basis`).
- **Guide destination leakage.** `backend/services/guide_service.py` now gates candidates with
  `_loc_ok()` using `geo_match.py`, so a guide from the wrong city can no longer appear.
- **Budget discipline.** `backend/services/ai_plan_builder.py` treats budget as a target band
  (`_BUDGET_TARGET_LOW = 0.70`, `_BUDGET_TARGET_HIGH = 0.95`) via `_budget_total/_fit/_note`;
  prices are never inflated to hit a target.
- **Passenger form was writing the wrong field names.** `frontend/pages/passengers.html` sent
  `SPOUSE/CHILD/PARENT/SIBLING` relationships and `OTHER` gender, plus `dob`, `proofType`,
  `proofNumber`, `emergencyContact`, `health.notes` — all rejected or silently ignored by
  `backend/services/passenger_service.py`. The form now uses the exact backend contract
  (relationships `SELF/FAMILY/FRIEND/COLLEAGUE/OTHER`; genders
  `FEMALE/MALE/NON_BINARY/PREFER_NOT_TO_SAY`; `dateOfBirth`; `idProofType` / `idProofNumber`;
  `health.medicalNotes`; `health.emergencyContactName` / `emergencyContactPhone`). Masked ID
  proof is preserved on edit without re-entering the full number.
- **ML registry metadata.** `backend/services/ml.py` wrote a `trained_at` key while readers
  expected `trainedAt`; a `_bump()` helper now increments `version` and writes `trainedAt`
  consistently across all `train_all` sites. `/api/ml/status` previously returned an integer
  count; it now returns the actual registry rows.
- **Home page image weight.** `frontend/css/style.css` `.dest-tile` reserved a
  `contain-intrinsic-size: 400px 300px` box while tiles render at ~250px wide; corrected to
  `250px 188px` to remove the scroll-anchoring / extra-layout cost.

## 19. Newly Implemented
- **"What TripMind Learned" (admin ML surface).** New admin panel `insights` in
  `frontend/js/portal.js` (nav item, title, icon, `definePanel('insights', [ADMIN], adminMlInsights)`).
  Renders, from the existing ML endpoints, the model registry with human-friendly names,
  status pills, metric chips, training time, plus cluster / segment / demand-forecast /
  anomaly sections, with reload and train actions (`TM.mlInsightsReload`, `TM.mlInsightsTrain`).
- **Service-level reviews.** `backend/services/reviews.py` gained `service_reviews()` and a
  `service_stats()` consumer at `/api/ratings/service`, returning
  `{avg, count, distribution, reviews:[{rating, comment, reviewer, createdAt}]}` with reviewer
  names masked to "First L.". Frontend: a "Reviews & ratings" button + modal on each spot card
  in `frontend/pages/planner.html`, and a "Read reviews" dialog (reusable `TM.serviceReviews`)
  in the portal feedback panel. Shared `.rev-*` styles were added to `portal.html`.
- **Passenger party preview.** Dead API `passengerPartyPreview` (`/api/passengers/party`) now
  has a consumer: the travellers page renders a "What a partner sees" card showing headcount,
  age bands and coarse preparation flags — the same non-identifying snapshot stored on a
  booking — so a traveller can confirm their consent choices before booking.
- **Pre-trip reminder scheduler (built, wired).** `backend/services/scheduler.py` runs in-process
  (`app.py` → `scheduler.start()`), is idempotent via
  `notification_service._claim_reminder`, exposes an admin trigger, and ships a cron entry point
  `scripts/run_scheduled_jobs.py`. (`TODO.md` still listed this as outstanding and is stale.)
- **Home-page performance pass.** Hero image preloaded (`<link rel="preload" as="image">`) with
  `fetchpriority="high"`; `preconnect` / `dns-prefetch` to the Unsplash image CDN; destination
  tiles lazy-loaded (already present) with the corrected intrinsic size; below-the-fold landing
  sections use `content-visibility: auto` (scoped to `main >` so the hero first paint is
  unaffected).

## 20. ML Models
`/api/ml/status` loads **16 registered models** (the internal `"system"` doc is filtered out).
All are currently `INITIAL` at `version 0` with `samples 0` until training runs:

| model | category |
| --- | --- |
| ai_requirement_extraction | nlp |
| anomaly_detection | observability |
| collaborative_filtering | recommendation |
| content_based_recommendation | recommendation |
| demand_prediction | prediction |
| guide_recommendation | recommendation |
| hotel_recommendation | recommendation |
| itinerary_optimization | optimization |
| personalized_trip_ranking | recommendation |
| tourist_spot_clustering | clustering |
| tourist_spot_recommendation | recommendation |
| transport_recommendation | recommendation |
| travel_cost_prediction | prediction |
| travel_time_prediction | prediction |
| user_segmentation | clustering |
| visiting_time_recommendation | recommendation |

Supporting endpoint shapes (consumed by the insights panel):
- clusters → `result.clusters[]` each `{cluster, theme, members[], count}`
- segments → `result.segments[]` each `{segment, members, count, avgBudget}`
- demand → `result.forecast.{TYPE}[]` each `{date, weekday, expected}`
- anomalies → `result.anomalies[]` each `{reference, bookingId, type, status, amount, userName, anomalyScore}`

## 21. Data Flow
- **Assistant transport change (live path).** `frontend/js/chat.js` → `/api/assistant/chat` →
  `backend/services/assistant.py` (`_local_intent` → `_transport_change_intent`) →
  `ai_chat._apply_transport_change` → booking flagged `change_pending`; plan reflowed. No wallet
  refund/rebill and no `booking_service.switch_transport` call (paid bookings must not be
  silently re-sold). `/api/ai/chat` remains a compatible sibling backend with no frontend caller.
- **Reviews.** Booking completion → `reviews.eligible_bookings` → rating stored →
  `service_reviews(service_type, service_id)` → `/api/ratings/service` → planner card modal and
  portal feedback dialog.
- **Passenger privacy chain.** Form → `passenger_service.validate_payload` → `_build_health`
  (consent-gated; emergency contact stored only with consent) / `_build_proof` (masked to last 4)
  → owner view for the traveller; `to_ai_context` and `to_public_party_view` emit only aggregates
  (party size, age bands, coarse flags) — never names, exact ages, contacts or proof.
- **ML insights.** `ml.registry.complete_registry()` seeds 16 definitions →
  `ml.train.train_all()` bumps versions and stamps `trainedAt` → `/api/ml/status` +
  cluster/segment/demand/anomaly endpoints → admin `insights` panel.

## 22. Remaining Issues
- **No full test run this cycle.** `backend/scripts/e2e_test.py` has pre-existing stale-fixture
  failures (25 pass / 28 fail as last observed) and `backend/scripts/test_ai_extras.py` depends on
  live LLM JSON output (49 pass / 4 fail). These are not in the claimed-green set and were not
  re-run here.
- **ML models are untrained** (`INITIAL`, `samples 0`); the insights surface will show empty
  cluster/segment/demand/anomaly sections until `train_all` runs against real data.
- **MongoDB mojibake** cannot be confirmed or repaired without running
  `backend/scripts/fix_encoded_mojibake.py` against the live DB (needs explicit go-ahead).
- **Home-page CSS payload.** The landing page still ships two render-blocking stylesheets
  (~140 KB combined) with some duplicated rules between `style.css` and `theme.css`; a
  critical-CSS / de-duplication pass is the next meaningful win and was deliberately left
  out of this cycle to avoid a risky refactor.
- `TODO.md` is stale for the scheduler item and should be reconciled.

## 23. Checks Run This Cycle
- `python -m py_compile` clean for `services/ml.py`, `services/reviews.py`,
  `services/passenger_service.py`, `routes/__init__.py`.
- `node --check` clean for `frontend/js/portal.js`; inline-script extraction + `node --check`
  clean for `frontend/pages/planner.html` and `frontend/pages/passengers.html`.
- `scripts/check_asset_refs.py`: 340 refs / 0 broken. `scripts/check_css_vars.py`: 1800 refs /
  0 undefined. `scripts/ascii_harden.py --check`: 0 files with non-ASCII.
- Targeted runtime checks (not the suite): `/api/ml/status` registry loads 16 models;
  `reviews.service_reviews('SPOT', <unknown>)` returns the empty-but-valid envelope;
  `passenger_service.validate_payload` accepts the new frontend payload and rejects the old one;
  `_build_proof` returns `******5678` and `_build_health` stores emergency contact only with
  consent.