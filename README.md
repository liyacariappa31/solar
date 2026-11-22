# SolarWise — Smart Solar Energy Optimizer

SolarWise is a local-first solar dashboard that estimates daily photovoltaic yield from sunlight intensity, ambient temperature, installed panel capacity, and cloud coverage. It combines a persisted scikit-learn Random Forest model with a Flask API, a responsive HTML/CSS/JavaScript dashboard, and Chart.js visualizations.

## What it does

- Estimates daily generation in kWh and displays an hourly production curve.
- Trains and persists a Random Forest regressor from a reproducible, physically informed sample dataset. On a fresh checkout, the dataset and model are created automatically when the app first starts.
- Compares current conditions with clear-sky and cooler-panel scenarios.
- Gives condition-aware panel care and performance suggestions.
- Recommends midday windows for common flexible appliances using predicted hourly output.
- Calculates a simple solar-fit score and estimated avoided CO₂ equivalent.
- Saves submitted forecasts in a local SQLite database and charts the saved history. What-if runs are not saved.
- Adds a Solar Insights page with an unverified manual/demo generation comparison, user-estimated cleaning recovery, tariff-based gross bill offsets, and editable weather-risk scenarios.
- Stores submitted insights in the same local SQLite database and lists the recent records on the Insights page.
- Replays the timestamped observations in `data/real_solar_training_data.csv` as clearly labeled simulated-live history, advancing one source record every 30 seconds with date selection, pause, replay, and stop controls.
- Updates recorded output, day-to-date energy, weather fields, hourly chart, observed peak, performance indicator, advice, and retrospective appliance windows from the selected playback position. Scheduler snapshots are returned with the selected day instead of fetched again at every playback tick. Gaps are not interpolated, and playback stops at the last available observation.
- Provides dataset provenance and model information, an explanation of the four prediction inputs, and a monthly historical report with clearly labeled tariff and CO₂ estimates.
- Validates API input and exposes a health endpoint for the loaded model.
- Keeps the dashboard focused on a single-screen overview; prediction, weather, simulator, advisor, scheduler, and history each open on their own page.
- Provides a persistent dark/light theme toggle across the dashboard and tool pages, with larger desktop typography and a full-height dashboard layout.

The sample training data is synthetic and the physical yield formula is an educational approximation. Forecasts are planning estimates, not meter readings or guarantees. SolarWise does not connect to an inverter or a live weather service. Manual generation entries are unverified, demo readings are simulated, possible causes are not fault diagnoses, and weather/rain alerts are user-entered scenarios rather than live alerts. Savings are gross grid-offset estimates based on the entered tariff.

Historical playback is also simulated, not a live inverter or weather connection. Its source is the joined Plant 1 generation/weather dataset. The recorded generation is aggregated across the source plant's inverters and should not be read as this household's output; appliance windows compare that plant profile with reference appliance loads and do not measure household demand. The source includes ambient and module temperatures and irradiation, but not cloud coverage or a household panel capacity. Missing observations remain gaps.

The historical dataset contains 3,157 records from 2020-05-15 through 2020-06-17 with a nominal 15-minute interval; timestamp gaps are retained. The historical records and the model training data are separate: the Random Forest model uses 1,800 reproducibly generated, physically informed synthetic examples. Monthly report totals are observed Plant 1 aggregate energy for the days present in each month. Tariff values are illustrative gross-offset estimates, not residential bill savings; CO₂ estimates use an assumed factor of 0.42 kg/kWh. Partial months are not extrapolated.

## Requirements

- Python 3.10 or newer
- pip
- Internet access for the Google Fonts and Chart.js CDN assets (the app itself and API run locally)

## Run locally

Open a terminal in the project directory:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
python app.py
```

Open [http://127.0.0.1:5000](http://127.0.0.1:5000). The first launch generates `data/solar_training_data.csv`, trains the model, saves it under `models/`, and initializes the SQLite database under `instance/`. To train the model again explicitly, run:

```powershell
python train_model.py
```

Flask's development server is intended for local use. Set `debug=False` before exposing the app to a network.

The dashboard links to dedicated `/prediction`, `/weather`, `/insights`, `/simulator`, `/advisor`, `/scheduler`, and `/history` pages. Simulator inputs persist while navigating between pages in the same browser tab, and the theme choice is saved across visits.

On Vercel, the model cache and SQLite database use temporary function storage. Saved forecast and insight history is not durable across function restarts; use a persistent database for production history.

## API

- `GET /api/health` — model status and version.
- `POST /api/predict` — accepts JSON `sunlight_intensity` (0–1200 W/m²), `temperature` (-20–60 °C), `panel_capacity` (0.5–50 kWp), and `cloud_coverage` (0–100%). Optional `save_history: false` runs an unsaved simulation.
- `GET /api/history?limit=20` — recent saved forecasts (limit 1–100).
- `GET /api/simulation/dates` — dates present in the historical playback source.
- `GET /api/simulation/day?date=YYYY-MM-DD` — timestamped source observations and hourly groups for one date; add `include_scheduler=1` to include appliance-window snapshots aligned with every record.
- `GET /api/simulation/scheduler?date=YYYY-MM-DD&through=YYYY-MM-DD%20HH:MM:SS` — appliance windows calculated only from complete hourly records through the selected playback timestamp.
- `GET /api/simulation/dataset-info` — source coverage, nominal sampling interval, model version, features, and training-data provenance.
- `GET /api/simulation/monthly-report?rate=8.5&currency=INR` — monthly observed aggregate energy with illustrative gross savings and estimated CO₂ offset.
- `POST /api/insights/health` — compares a manually entered generation value or labeled simulated demo against the model estimate.
- `POST /api/insights/cleaning` — estimates possible soiling loss and recovery from user-entered soiling and cleaning age.
- `POST /api/insights/savings` — calculates daily, weekly, monthly, and yearly gross grid-offset value for an entered tariff and currency.
- `POST /api/insights/weather-risk` — estimates cloud, heat, and optional rain-scenario losses from entered conditions; this is not a live alert.
- `GET /api/insights/history?limit=20` — recent saved insight records, optionally filtered with `type=health`, `cleaning`, `savings`, or `weather_risk` (limit 1–100).

## Tests

```powershell
python -m unittest discover -s tests -v
```

The tests cover model-backed prediction, forecast and insight persistence, historical playback and scheduler snapshots, dataset provenance, monthly estimates, input validation, and disclosure labels for simulated or unverified readings.
