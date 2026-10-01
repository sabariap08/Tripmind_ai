# TripMind AI — Audit & Fix Backlog

**Status legend:** `[x]` verified done (suite passes) · `[~]` in progress · `[ ]` not started · `[!]` blocked

**Verification suites** (run from `backend/`, all currently exit 0):

| Script | What it proves |
|---|---|
| `scripts/check_asset_refs.py` | 346 file refs + 43 route refs resolve against disk and `url_map` |
| `scripts/check_css_vars.py` | 1739 CSS custom-property refs are defined |
| `scripts/ascii_harden.py --check` | Frontend sources are pure ASCII |
| `scripts/test_replanner.py` | 16/16 replan engine |
| `scripts/test_replan_e2e.py` | 16/16 two-phase replan over real HTTP |
| `scripts/test_place_images.py` | 22/22 photo provenance guards |
| `scripts/test_ai_chat_confirm.py` | 21/21 no-mutation-without-confirmation |
| `scripts/test_assistant_transport.py` | live assistant proposes + confirms a natural-language transport change and re-flows the plan |

---

## 1. Encoding & infrastructure

- [x] 586 non-ASCII chars hardened to escapes across 44 files
- [x] Encoded mojibake repaired (`dashboard.html`, `bookings.js`)
- [x] Server-side `charset=utf-8` via `_force_utf8`
- [x] `repairEncoding()` at the fetch boundary
- [x] `SECRET_KEY` resolution: env → `backend/.secret_key` → generated; refuses to boot when `DEV_MODE=false`
- [x] `sw.js` — added `/pages/journey.html` + `/js/portal.js`, bumped `CACHE_VERSION` v6 → v8

## 2. Trip page (`frontend/pages/trip.html`)

- [x] Rail `top`/`z-index` — was parked under the nav (z-index 900)
- [x] Double scroll offset removed (`scroll-padding-top` + `scroll-margin-top` both counting)
- [x] `initRailSpy()` idempotent via `railTeardown` disposer array
- [x] `secEvents` rail link added (section existed but was unreachable by nav)
- [x] `askConfirm` — **both** `yes` and `no` were bound to **both** buttons, so every click ran confirm *and* cancel; also leaked listeners on non-button exits
- [x] `renderEvents` hides the rail link instead of `remove()`ing it (2nd run could never relabel)
- [x] Transport / Stay / Activities breakdown section added
- [x] Replan Trip UI — drives the two-phase endpoint, shows real cost delta

## 3. Correctness defects found by audit

- [x] `geo_match` "match nothing" sentinel was **inverted** — `{"__no_such_field__": {"$exists": False}}` matches *every* document, so `city=".*"` returned all 7 spots
- [x] `place_images` negative cache unreachable + duplicate `if cached:`
- [x] `place_images` false positives (Mumbai bridge for "Marina Gateway", Singapore for "Marina Deck") — added geographic corroboration + foreign-proper-noun rules
- [x] ML recommender read `doc["image"]`, a key no writer ever sets → image `null` for every spot
- [x] IRCTC policy — narrower TRAIN rule must beat blanket `is_admin`
- [x] `/api/ai/chat` **mutated the itinerary with no confirmation** while the page promised otherwise
- [x] Live assistant ignored natural phrasing ("I don't want the train, I want a bus after 2 PM") and its `change_transport` only swapped the booking record — never the plan. It now proposes the change and re-flows the itinerary; a booked trip is flagged `change_pending` instead of being reported as changed.
- [x] `dest_only` transports shown without any indication they don't board at the origin
- [x] `/generate` returned **200** on AI failure — indistinguishable from a genuine empty result
- [x] Ratings had a read-then-write duplicate check only — no DB-level guarantee

## 4. Frontend robustness

- [x] `passengers.html` — `TM.api.*` was undefined (TypeError on load, whole page dead)
- [x] `passengers.html` — empty `data-tm-drawer-open` made the burger a no-op
- [x] `portal.js` — `window.TM = {...}` wiped `TM.esc`/`toast`/`button`/`drawer`; now merges
- [x] Partner hub `maps.js` 404 (×2) — Google Maps never initialised on boarding-points and buses
- [x] `theme.css` — 6 undefined custom properties (`--tm-bg`, `--tm-surface`, `--tm-bg-soft`, `--tm-r-1/2`, `--tm-warn`)
- [x] `.tm-alert` was used by `register.html` + `register.js` but **defined nowhere** — signup errors rendered as unstyled text
- [x] `api.js` errors now surface the server's `message` and a `retryable` flag; `chat.js` shows a real retry affordance

## 5. New checkers (root-cause guards, not one-off fixes)

- [x] `check_asset_refs.py` — route-aware, so extensionless links are checked against `url_map` not the filesystem
- [x] `check_css_vars.py` — undefined `var()` silently invalidates the whole declaration
- [x] `audit_rating_duplicates.py` — read-only by default, `--dedupe` opt-in

---

## Remaining — verification only

No implementation work outstanding. Every item below is "written, not watched working."

- [ ] **Run one real Coimbatore → Chennai generation end to end** — the highest-risk gap. Trip generation through Ollama has not been exercised since the provider/meal/duration changes. Read back the actual plan: provider on every item, meal times matching the schedule, train duration, total against budget.
- [ ] **Click through the trip page in a browser** — blank-page fix, RE-PLAN two-phase, Confirm & Book, Providers section, VIEW modal. All written and compiling; none seen rendering.
- [!] **MongoDB mojibake repair** — `backend/scripts/fix_encoded_mojibake.py` is written but has never been run against the database. Needs an explicit go-ahead.
- [ ] **Cost model quality** — R² 0.3181 over 159 samples. Five features, and the label falls back to `budget * 0.9` when no itinerary cost exists, so the targets are partly circular. Do not quote this number as model accuracy until the labels are fixed.

## Completed since the last audit

- [x] **Scheduler for `due_checklists_for_today`** — `services/scheduler.py` started from `app.py:234`; admin endpoint at `routes/__init__.py:3209`; cron entry `scripts/run_scheduled_jobs.py`. Idempotent via `notification_service._claim_reminder`, so a restart cannot double-send.
- [x] **Budget utilisation / breakdown** — `_BUDGET_TARGET_LOW/HIGH`, `_budget_fit`, `_budget_note` in `ai_plan_builder.py`; plans rank against the real budget and state plainly in `budgetFitDetail.note` when a route cannot absorb it. No invented costs.
- [x] **"What TripMind learned" surface** — `/api/ml/status`, admin `insights` panel, `TM.mlInsightsReload` / `mlInsightsTrain`.
- [x] **Service-level reviews** — `services/reviews.py`, `/api/ratings/service`, `api.serviceRating`, planner spot-card reviews modal, traveller feedback buttons.
- [x] **Home-page performance pass** — hero preload/preconnect, `contain-intrinsic-size` on `.dest-tile`, below-the-fold `content-visibility`.
- [x] **Final report** — "Revision 2" appended to `IMPLEMENTATION_REPORT.md`.
- [x] **Passenger Details nav** — `dashboard.html`, `planner.html`, `index.html` (visitor-hidden, revealed on auth).
- [x] **"For Travel Partners" logo** — `sw.js` no longer serves `/index.html` for a failed partner navigation; CSS `tm-splash-bail` retires the splash with no JS.
- [x] **ML auto-retrain** — `scheduler.ml_retrain_job` registered in `JOBS`. Gated on `ML_AUTOTRAIN_ENABLED` (off by default: retraining rewrites model parameters). Two guards: `ML_AUTOTRAIN_MIN_SAMPLES` (50) so an empty tick does not republish identical parameters under a new version, and `ML_AUTOTRAIN_MIN_INTERVAL_SECONDS` (6h). Sample count is read from the sample collections, never from model state — otherwise a prior retrain satisfies its own trigger.

## Demo-fix pass (COIMBATORE → CHENNAI)

- [x] **Premium Services reach the model** — `_PREMIUM_DIRECTIVES` / `_premium_directives` inject concrete behaviour per service instead of a label the model ignored.
- [x] **Meals follow real itinerary time** — `_MEAL_WINDOWS` + `_meal_label`; a full day now gets 08:30 breakfast, 13:00 lunch, 20:00 dinner instead of three breakfasts.
- [x] **Real travel durations** — `_leg_ride_minutes` reads the operator's boarding→dropping schedule, then falls back to distance/speed. The Cheran Express reads 8h55m, not 90 minutes.
- [x] **Seed data** — `provider` on every transport/hotel/restaurant; Marina Deck Hotel added; the seeder's `railway.southern@tripmind.demo` KeyError fixed via `RAILWAY_ADMIN_KEY`.
- [x] **Destination filtering** — `list_spots(city="Chennai")` returns Marina Beach, Kapaleeshwarar Temple and Fort St. George only; no Ooty/Kovai leakage.
- [x] **Providers reach the itinerary** — `provider`, `operator`, `rating`, `images` on transport (both legs), hotel, activity/tour and food items.
- [x] **Itinerary VIEW** — `trip.html` opens a type-appropriate image plus real provider facts; nothing is invented when an item has no photo.
- [x] **Blank-page fix** — `theme.css` starts `[data-reveal]` at `opacity: 0` and cleared only on `.is-in`, while `destinations.js` added `.revealed`. Anything the observer missed stayed invisible. Both class names now clear it, and `ui.js` force-shows after 2.5s.

## Training-path bugs (found by enabling auto-retrain)

These three had been dormant because no training run had ever completed, so `/api/admin/ml/train` was failing too.

- [x] `_eval_cost` indexed `trip_features` output as a list, but it returns a dict keyed by feature name → `KeyError: 0` killed every cost evaluation. Routed through `_feat_vec`.
- [x] `recommend_transports` called `float(d.get("fare"))`, but 60 of 90 transports store fare as a class→price dict (`{"sleeper": 899, "seater": 699}`) → `TypeError` took down the recommender. Added `_numeric_fare`, which reduces a dict to its cheapest class and returns 0 rather than raising on junk.
- [x] `_eval_reco` unpacked a fixed 3-tuple, but `recommend_hotels` returns 4 → `hotel_recommendation` recorded as `ERROR` every run.

Result: 12 models at v2, 0 in ERROR (was 24 models, most at v0, two ERROR).

## Blocked / needs a decision

- [!] **No desktop browser attached** (`browser.disconnected`) — zero visual verification. Everything above is static analysis, `node --check`, the Flask test client, and direct HTTP probes.
- [!] **Local Ollama unreachable** — `OLLAMA_BASE_URL` defaults to `https://ollama.com` and needs `OLLAMA_API_KEY`. No loopback/no-auth path, so a stock local Ollama will not work.
- [!] MongoDB mojibake repair (`backend/scripts/fix_encoded_mojibake.py`) is written but has **not** been run against the database — needs an explicit go-ahead.

## Known-unverified

- The blank-page fix was diagnosed from source and a live server log (all assets 304, `/api/auth/me` 200, `/api/ml/recommend/spots` 200) but never seen in a browser. If the page is still blank after a hard refresh, that needs a real browser to chase.
- `/api/ai/chat` has **no frontend caller** — the visible assistant uses `/api/assistant/chat`. The endpoint is live and authenticated, which is why the unconfirmed mutation mattered, but its two-phase contract is currently unexercised by any UI.
- The RE-PLAN two-phase flow and Confirm & Book exist and drive their real endpoints, but have not been clicked through in a browser this session.
