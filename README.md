# DroughtWatch KZN

A working drought stress prediction and mapping platform for KZN cattle farms.
Flask + Jinja + vanilla JS/CSS on the frontend, PostgreSQL on the backend,
XGBoost for the machine learning.

This has been built and smoke-tested end-to-end (signup, data loading,
training, prediction, map, and the 30-day notification job all run
successfully). You still need to point it at your own PostgreSQL database
and, when ready, load your own JSON dataset in place of the bundled sample.

---

## 1. What's inside

```
drought_platform/
├── run.py                     # start here: python run.py
├── config.py                  # reads settings from environment variables
├── requirements.txt
├── schema.sql                 # reference SQL (optional -- app creates tables itself)
├── .env.example                # copy to .env and fill in your DB password
├── data/
│   └── sample_drought_data.json   # synthetic sample data so you can test before your real data arrives
├── app/
│   ├── __init__.py            # app factory, DB + login + scheduler setup
│   ├── models.py              # User, Zone, Farm, DroughtAssessment, Notification
│   ├── auth.py                 # signup / login / logout
│   ├── main.py                 # home, map, farms, data upload/train, dashboard, notifications
│   ├── scheduler_jobs.py       # the 30-day "safe to start your new month" check
│   ├── ml/
│   │   ├── formula.py          # transparent weighted drought-stress formula (fallback + proxy labels)
│   │   ├── data_loader.py      # loads your JSON into the database
│   │   ├── train_model.py      # trains + evaluates the XGBoost models, generates seaborn charts
│   │   ├── predict.py          # runs predictions, forecasts, alternative-land suggestions
│   │   └── artifacts/          # trained model files land here (empty until you train)
│   ├── templates/              # one .html file per page (Jinja)
│   └── static/
│       ├── css/style.css       # all styling, separate from the HTML
│       ├── js/main.js          # flash-message behaviour
│       ├── js/map.js           # Leaflet map logic
│       └── img/dashboard/      # seaborn chart images land here after training
```

## 2. Install PostgreSQL and create the database

**Ubuntu/Debian:**
```bash
sudo apt update
sudo apt install -y postgresql postgresql-contrib
```

**macOS (Homebrew):**
```bash
brew install postgresql
brew services start postgresql
```

**Windows:** download the installer from https://www.postgresql.org/download/windows/
and run it (keep the default port 5432).

Then create the database and a dedicated app user:

```bash
sudo -u postgres psql
```
```sql
CREATE DATABASE drought_platform;
CREATE USER drought_app WITH PASSWORD 'choose_a_strong_password';
GRANT ALL PRIVILEGES ON DATABASE drought_platform TO drought_app;
\c drought_platform
GRANT ALL ON SCHEMA public TO drought_app;
\q
```

You do **not** need to run `schema.sql` by hand -- the app creates every
table automatically the first time it starts (`db.create_all()` in
`app/__init__.py`). `schema.sql` is there as a plain-SQL reference, in case
you ever want to inspect or hand-run the schema, or move to a migration
tool later.

## 3. Configure and install

```bash
cd drought_platform
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# then edit .env and set:
#   DATABASE_URL=postgresql+psycopg2://drought_app:choose_a_strong_password@localhost:5432/drought_platform
#   SECRET_KEY=<any long random string>
```

## 4. Run it

```bash
python run.py
```

Open http://localhost:5000 -- you'll land on the login page. Click
**Sign up** to create your first account (name, surname, email, password),
then log in.

## 5. Load data and train the model

You said you'll provide your own JSON dataset later -- since then you've
sent through the real one: `data/drought_stress_dataset_12wk.json` and
`data/drought_stress_dataset_32wk.json` (6 real farms, worst/best-case
forecasts, alerts and relocation recommendations -- see section 8 below for
the full story). Upload either of those from the Data & Model page to see
the real map, scenario toggle, alerts and relocation suggestions.

`data/sample_drought_data.json` (960 synthetic weekly readings across 8 KZN
zones) is also still bundled -- it exercises the *other*, simpler upload
path (the in-app ML training/dashboard pipeline from section 6), which is
independent of the rich dataset and still useful if you want to see model
training/evaluation charts.

1. Go to **Data & Model** in the navbar.
2. Upload `data/sample_drought_data.json` (or your own file, once you have it).
3. Click **Train model on loaded data**.
4. Go to **Dashboard** to see the seaborn evaluation charts (feature
   importance, confusion matrix, risk-by-severity, rainfall vs. NDVI,
   correlation heatmap) and the metrics (MAE, RMSE, R², accuracy,
   precision, recall, F1).
5. Go to **Map** -- every zone now shows as a coloured marker (green =
   Low, amber = Moderate, red/clay = High). Click one to see its current
   risk, grazing/water stress sub-scores, a 30/60/90-day forecast, and --
   if it's High risk -- a list of lower-risk zones suggested instead.
6. Go to **My Farms** to register a farm against a zone.

### Your own JSON format

When your real dataset is ready, it needs to be a JSON array of reading
objects, one per zone per date:

```json
[
  {
    "zone": "Msinga",
    "district": "uMzinyathi",
    "latitude": -28.75,
    "longitude": 30.42,
    "date": "2024-01-15",
    "rainfall_mm": 12.4,
    "temperature_c": 31.2,
    "soil_moisture": 0.18,
    "ndvi": 0.31,
    "water_availability": 0.40,
    "historical_drought": 1,
    "risk_score": 78.5,
    "severity_level": "High"
  }
]
```

Only `zone`, `latitude`, `longitude` and `date` are required -- everything
else is optional. If `risk_score` / `severity_level` are missing, the
training script derives a proxy label from the transparent formula in
`app/ml/formula.py`, so the pipeline works even before you have
ground-truth labels; feed in real labels later and retrain to improve
accuracy. Uploading a new file adds to what's already loaded (it doesn't
erase previous readings), so you can load your dataset in batches.

## 6. How the pieces you asked for work

- **Signup/login**: `app/auth.py` + `templates/signup.html` /
  `login.html`, using Flask-Login and hashed passwords (Werkzeug).
- **Navbar with Map and other pages**: `templates/base.html`.
- **AI model + metrics**: `app/ml/train_model.py` trains an XGBoost
  regressor (risk score 0-100) and an XGBoost classifier (Low/Moderate/
  High), evaluated with MAE/RMSE/R² and accuracy/precision/recall/F1 on
  a held-out test split, saved to `app/ml/artifacts/metrics.json`.
- **Dashboards with seaborn**: generated in `train_model.py`
  (`_generate_charts`), saved as static PNGs, shown on the Dashboard page
  -- no external service, nothing that requires JavaScript charting
  libraries.
- **Map with severity colours and icons (not emojis)**: `static/js/map.js`
  + Leaflet, coloured circle markers, Font Awesome icons throughout the
  UI.
- **"Don't farm here, try this instead"**: `predict.py ->
  suggest_alternative_zones()`, shown in the map's side panel whenever a
  zone is High risk.
- **30-day calendar update**: `app/scheduler_jobs.py` runs once a day in
  the background (APScheduler) and checks every farm's
  `last_cycle_check`. Once 30 days have passed, it creates a Notification
  -- "nothing suspicious, you may start your new farming month" if the
  zone is Low risk, or a caution message if it isn't -- and resets the
  30-day counter. Notifications show under **Notifications** in the
  navbar, with an unread badge.

## 7. Running it with Docker (recommended for team members)

If you'd rather not install PostgreSQL locally at all, use Docker instead --
one command starts Postgres *and* the app together, already wired up
correctly.

**Prerequisite:** Docker Desktop installed and running
(https://www.docker.com/products/docker-desktop/).

```bash
docker compose up --build
```

That's it. Compose starts a Postgres container (with the `drought_app`
user/database already created for you), waits for it to be healthy, then
starts the Flask app pointed at it. Open http://localhost:5000 -- tables
are created automatically on first run, same as running it locally.

To stop everything:
```bash
docker compose down
```

To stop everything **and delete the database** (start completely fresh):
```bash
docker compose down -v
```

Since `docker-compose.yml` mounts your project folder into the container
(`volumes: - .:/app`), any code changes you make locally take effect
immediately -- just refresh the browser (Flask's debug reloader picks up
`.py` changes; for template/static changes a browser refresh is enough).

Each teammate just needs Docker installed and `docker compose up --build`
run once from the project root -- no per-machine Postgres install,
password setup, or `pg_hba.conf` editing required.

## 8. What's new: real KZN+national dataset, community, and the drought/no-drought story

Building on section 6 above, this update adds:

- **No more logging in twice.** Signing up now logs you straight in (see
  `app/auth.py`) and takes you to the home page -- you don't create an
  account and then have to separately log in with the same details.
- **Location at signup.** The signup form now asks for your nearest
  town/area (e.g. "Msinga", "Vryheid", "Dundee"). When you later register a
  farm, its Zone dropdown is pre-selected based on that location
  (`_match_zone_to_location` in `app/main.py`).
- **Community page.** A new **Community** nav item lists other farmers on
  the platform (with a mailto contact link) and lets you post a help alert
  ("need feed", "need a water tanker", etc.). Anyone else with a farm in
  the same zone gets it as a Notification immediately; everyone sees it on
  the Community wall regardless, and you can mark your own alert resolved.
  Models: `HelpAlert` in `app/models.py`, routes in `app/main.py`.
- **The real dataset is wired in.** `data/drought_stress_dataset_12wk.json`
  and `data/drought_stress_dataset_32wk.json` are the two files you
  provided -- 6 real farms across KZN, Western Cape, Eastern Cape, Northern
  Cape, Limpopo and Free State, each with a worst-case *and* best-case
  weekly forecast (drought stress index, NDVI, soil moisture, rainfall,
  water-point level, grazing capacity, feed-days remaining, and a running
  ZAR financial-impact estimate), auto-triggered alerts with lead time, and
  ranked relocation recommendations. Upload either file from the **Data &
  Model** page -- the app auto-detects this richer format
  (`data_loader.is_rich_dataset` / `load_rich_dataset`) versus the older
  flat-reading format, so the same upload button handles both.
- **The map is specific to real places now**, including Msinga, Dundee and
  Vryheid as you asked: every farm's `area` (e.g. "Dlomodlomo, Vryheid")
  becomes its own zone; every relocation-target city that recurs across the
  dataset (Dundee, Ermelo, Underberg, Kokstad, Middelburg) is added as its
  own zone too, marked with a flag icon instead of a risk-coloured dot;
  and Msinga is always seeded onto the map even though it isn't in this
  particular dataset yet, ready for when you have data for it.
- **Worst-case vs. best-case, side by side.** The map now has a scenario
  toggle above it -- "Worst case (drought)" / "Best case (no drought)".
  Switching it re-fetches `/api/zones/<id>?scenario=worst_case|best_case`
  and redraws that zone's forecast panel: a mini bar chart of the drought
  stress index across the whole horizon, the first/final-week numbers,
  grazing capacity, and feed-days remaining. This is the literal answer to
  "how does the system react when drought happens, versus when it
  doesn't" -- same zone, same week numbers, two different trajectories.
- **Alerts and relocation recommendations are real, not just formula
  fallbacks**, when a zone has been loaded from the rich dataset: the
  zone's detail panel shows the dataset's actual auto-triggered alert
  (severity, lead time in days, farmer-facing message, recommended
  actions) and its ranked relocation suggestions (city, distance, projected
  grazing capacity, estimated cost) pulled straight from
  `DroughtAlert` / `RelocationRecommendation` in the database. Zones that
  only have the older simple format still fall back to the in-app
  formula/ML prediction path from section 6 -- nothing there was removed.

### Re-loading the dataset later

Uploading the same or an updated file again is safe -- zones, forecast
weeks, alerts and relocation recommendations are matched and updated in
place rather than duplicated (tested by loading the 12-week file, then the
32-week file, on top of it: same 12 zones, forecast rows extended from 12
weeks to 32, alerts/relocation rows replaced rather than doubled).

## 10b. What's new: no Data & Model in the navbar, live dashboard charts, the real fix for "weather not available"

- **The actual cause of "weather not available" / "could not load forecast"**: almost
  certainly your `.env` is missing `OPENWEATHER_API_KEY` -- it was never in
  `.env.example` until this update, so a `.env` created before now won't have it. Open
  your `.env` and add:
  ```
  OPENWEATHER_API_KEY=your_real_key_here
  ```
  then restart `python run.py`. Give it 30-60 seconds after startup (12 zones, paced
  1 second apart) before checking the map/dashboard/home page again. Both the weather
  chip and the forecast calendar now say exactly this in their own "not available"
  message, so it's self-diagnosing from here on.
- **"Data & Model" removed from the navbar entirely**, since farmers never need to
  interact with it -- the model trains itself automatically (see section 10 below). The
  page still exists at `/data` if you want to check status yourself, it's just not
  advertised in the UI anymore.
- **Dashboard charts are now live, not static images.** The two new charts at the top
  (drought stress index by zone, and live temperature vs. drought stress) are rendered
  with Chart.js directly from `/api/zones`, which already includes each zone's live
  weather -- so the temperature-vs-DSI chart visibly changes as the weather refresh job
  updates the database. They redraw every 60 seconds automatically (`dashboard.js`), no
  page refresh needed. The old seaborn PNG charts (confusion matrix, feature importance,
  etc.) are still there, but moved into a collapsed "Model evaluation snapshot" section
  with an explanation of why *those specific* charts are a point-in-time snapshot rather
  than live -- that's what a confusion matrix inherently is (performance on one held-out
  test split from one training run), not something that updates continuously the way
  zone status does.
- **On satellite data**: I haven't wired in a live satellite feed (e.g. Digital Earth
  Africa NDVI, Sentinel Hub) -- that needs its own API registration/key, which hasn't
  been provided, so I'm not fabricating that integration. The forecast dataset's own
  NDVI values are already used (in `ForecastReading` and the ML training features); a
  live satellite feed would be a real next step if you get access to one, and would slot
  into the same `app/weather.py`-style pattern (a fetch function + a scheduled refresh
  job + new `Zone` columns).

## 10. What's new: live weather, 5-day calendar, a chatbot, real-time chat, auto-trained ML

- **Fixed two install/runtime issues from testing on Windows:**
  - `ModuleNotFoundError: No module named 'requests'` -- just means `pip install -r requirements.txt`
    needs re-running after pulling this update (it adds `requests`, `Flask-SocketIO`,
    `python-socketio`, `simple-websocket`).
  - The real-time chat's WebSocket upgrade was failing with a 500 -- fixed by adding
    `simple-websocket` to `requirements.txt`, which is what lets Flask-SocketIO's
    threading mode handle real WebSocket connections on the plain Werkzeug dev server.
- **Home page no longer has farm-registration UI.** That's exclusively on My Farms now;
  Home is just the AI advisor, live weather, the 5-day forecast calendar, and the chatbot.
- **Live weather per zone**, via your OpenWeatherMap key (`app/weather.py`, adapted from
  the script you sent). A background job (`app/scheduler_jobs.py`) refreshes every zone's
  current conditions every 30 minutes -- paced with a 1-second gap between calls to stay
  well inside the free-tier rate limit -- and stores the result on the `Zone` row, so pages
  read it from the database rather than calling the weather API on every request. Shown on
  the map panel, the dashboard's zone cards, and each home-page advisor card.
- **5-day forecast calendar per farm**, under "This week in \<zone\>" on the home page --
  pulls OpenWeatherMap's free 5-day/3-hour forecast once and summarises it into daily
  cards (day name, icon, high/low). Fetched live on request and cached server-side for 30
  minutes per zone (`/api/farms/<id>/forecast` in `app/main.py`), so repeated page loads
  don't hammer the API or need the key exposed to the browser.
- **A chatbot that reads your real data, no upload, no external LLM call.**
  `app/chatbot.py` is a small keyword-matching assistant -- ask it about weather, risk,
  feed/water days, or whether to relocate, and it answers from your farm's zone,
  live weather, forecast readings, alerts and relocation recommendations already in the
  database. This is deliberately NOT a generative AI integration (no API key was provided
  for one) -- if you want a true LLM-backed version later, `answer_question()` is the one
  function to swap out.
- **Real-time chat replaces email.** Community's "Contact" button now opens an in-app chat
  (`/community/chat/<user_id>`) over Socket.IO (`app/sockets.py`), not a `mailto:` link.
  One room per pair of farmers, messages persist to the database (`Message` model) so
  history survives a refresh. **This requires `run.py` to start the app via
  `socketio.run(app, ...)` instead of `app.run(...)` -- already done for you.**
- **The ML model trains itself automatically on your real data -- no upload needed.**
  `train_model.py` now builds its training set from `forecast_readings` (the real 12/32-week
  dataset, already auto-seeded) rather than requiring the old flat-reading upload. It still
  prefers the simple uploaded format if you ever load 20+ rows of that instead. Training now
  runs once automatically at startup (`_auto_train_model` in `app/__init__.py`), so the
  Dashboard's charts and the Data & Model page's metrics are populated the moment the app
  starts -- confirmed in testing with the real dataset: 384 rows used, ~96% severity accuracy.
- **Data & Model page redesigned** to lead with that automatic status (model trained: yes/no,
  live metrics) rather than an upload form -- uploading is now tucked into a collapsed
  "Add or refresh data (optional)" section for the rare case you have a newer file.
- **Relocation suggestions are now distance-aware.** The formula-based fallback
  (`suggest_alternative_zones` in `app/ml/predict.py`) now computes real haversine distance
  between zones and prefers the nearest lower-risk one within 250 km, only reaching further
  if nothing closer qualifies -- so a farmer is never pointed somewhere impractically far
  "unless it genuinely has to be". Zones with dataset-provided relocation recommendations
  (the 6 real farms) were already distance-ranked by the dataset itself and are unaffected.

### Setting up the OpenWeatherMap key

Add this to your `.env` (never commit the real key to a repo):
```
OPENWEATHER_API_KEY=your_key_here
```
Since a key was shared in this conversation's chat log, treat it as exposed -- regenerate
it on OpenWeatherMap's site before relying on it for anything beyond local testing.

## 9. What's new (previous update): data loads automatically, one-step signup, AI advisor home page

- **No more empty map/dashboard on first run.** The app now auto-seeds
  itself from `data/drought_stress_dataset_32wk.json` (falling back to the
  12-week file) the moment it starts against a fresh, empty database --
  see `_auto_seed_dataset` in `app/__init__.py`. You'll see all 12 zones
  (the 6 real farms plus Dundee/Ermelo/Underberg/Kokstad/Middelburg/Msinga)
  on the map and dashboard immediately, with no upload step required. You
  can still upload a newer file from Data & Model any time -- that always
  takes priority over what was auto-seeded.
- **One-step signup.** Since this platform is exclusively for farmers,
  signup now also asks for your farm's name and herd size (optional). If
  we can match your location to a known zone, your first farm is created
  automatically and you land straight on your home page with it already
  showing -- no separate "register as a farmer" or "register a farm" step
  needed for your first farm. My Farms is still there for adding more.
- **Home page is now an AI drought advisor.** Each farm gets its own card:
  a plain-language recommendation (using the dataset's own alert message
  when one exists for that zone), a "Drought risk period" / "No drought
  detected" banner, live stats (drought stress index, water level, feed
  days, trend), and a **"Simulate: if drought continues" / "if rains
  return"** toggle that fetches `/api/farms/<id>/advisor?scenario=...` and
  shows the projected end-of-forecast outcome (DSI, grazing capacity, feed
  days, ZAR impact) -- this is the automatic worst-case/best-case
  walkthrough you asked for, per farm, on demand.
- **Dashboard now has a live "Zones overview"** above the ML training
  charts: every zone as a colour-coded card (green/amber/red by severity,
  with a subtle pulsing glow on High-risk zones), sortable by risk or
  name, fetched client-side from `/api/zones` -- so the dashboard shows
  something useful even before you've trained the simple-format ML model.
- **Map now frames itself to the data.** Instead of opening zoomed out to
  all of South Africa, `map.js` calls `fitBounds()` on the actual loaded
  zones, so it opens already framed around Msinga/Dundee/Vryheid/etc.
- **CSS and JS are now split per page**, as requested: `home.css`/`home.js`,
  `dashboard.css`/`dashboard.js`, and `map.css` (map.js was already
  separate) each hold only that page's rules/logic. `style.css` keeps the
  shared design tokens, navbar, buttons and form styling used by every
  page -- duplicating those into every file would just mean six copies of
  the same rules to keep in sync, so they stay centralised while
  everything page-specific lives in its own file.

## 12. Known simplifications (by design, for this stage)

- The 30/60/90-day forecast is a simple, clearly-labelled
  persistence-plus-history estimate (see `_simple_forecast` in
  `predict.py`), not a trained time-series model -- there isn't enough
  dated history yet to train one properly. Once your dataset has a long
  enough run of dated readings per zone, this is the piece to upgrade
  first.
- Zones are plain latitude/longitude points, not full farm-boundary
  polygons (no PostGIS geometry columns in use yet) -- `schema.sql` keeps
  the `postgis` extension enabled so you can add polygon boundaries
  later without a database change.
- SMS/WhatsApp delivery of notifications is not wired up -- notifications
  currently appear in-app only. Adding a gateway (e.g. Africa's Talking or
  Twilio) is a small addition to `scheduler_jobs.py`.
