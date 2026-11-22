"""SolarWise Flask application and JSON API."""

from __future__ import annotations

import json
import sqlite3
import csv
import calendar
import os
import tempfile
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterator

import joblib
import numpy as np
from flask import Flask, jsonify, render_template, request

from train_model import (
    DATASET_PATH as MODEL_DATASET_PATH,
    FEATURES,
    MODEL_PATH,
    estimate_physical_yield,
    train_model,
)


ROOT = Path(__file__).resolve().parent
HISTORICAL_DATASET_PATH = ROOT / "data" / "real_solar_training_data.csv"
DEFAULT_INPUTS = {
    "sunlight_intensity": 760.0,
    "temperature": 27.0,
    "panel_capacity": 6.5,
    "cloud_coverage": 18.0,
}
LIMITS = {
    "sunlight_intensity": (0, 1200),
    "temperature": (-20, 60),
    "panel_capacity": (0.5, 50),
    "cloud_coverage": (0, 100),
}
APPLIANCES = [
    {"name": "Washing machine", "kw": 0.8, "duration": 1.5, "icon": "wash"},
    {"name": "Dishwasher", "kw": 1.2, "duration": 1.4, "icon": "dish"},
    {"name": "EV charging", "kw": 3.0, "duration": 2.0, "icon": "car"},
    {"name": "Water heater", "kw": 2.0, "duration": 1.0, "icon": "heat"},
]
INSIGHT_TYPES = {"health", "cleaning", "savings", "weather_risk"}
CURRENCY_SYMBOLS = {"INR": "₹", "USD": "$", "EUR": "€", "GBP": "£"}
GRID_CO2_KG_PER_KWH = 0.42

app = Flask(__name__)
app.config["DATABASE"] = str(
    Path(tempfile.gettempdir()) / "solarwise.db"
    if os.getenv("VERCEL")
    else ROOT / "instance" / "solarwise.db"
)
app.config["HISTORICAL_DATASET"] = str(HISTORICAL_DATASET_PATH)
app.config["JSON_SORT_KEYS"] = False

_bundle: dict[str, Any] | None = None


def get_model_bundle() -> dict[str, Any]:
    """Load a persisted model, training it once if this is a fresh checkout."""
    global _bundle
    if _bundle is None:
        if not MODEL_PATH.exists():
            train_model()
        _bundle = joblib.load(MODEL_PATH)
    return _bundle


def get_db() -> sqlite3.Connection:
    Path(app.config["DATABASE"]).parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(app.config["DATABASE"])
    connection.row_factory = sqlite3.Row
    return connection


@contextmanager
def db_connection() -> Iterator[sqlite3.Connection]:
    connection = get_db()
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def init_db() -> None:
    with db_connection() as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS forecasts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                sunlight_intensity REAL NOT NULL,
                temperature REAL NOT NULL,
                panel_capacity REAL NOT NULL,
                cloud_coverage REAL NOT NULL,
                generation_kwh REAL NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS insight_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                record_type TEXT NOT NULL,
                created_at TEXT NOT NULL,
                payload_json TEXT NOT NULL
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_insight_records_type_id "
            "ON insight_records(record_type, id DESC)"
        )


def parse_inputs(payload: dict[str, Any]) -> dict[str, float]:
    inputs: dict[str, float] = {}
    for key, (minimum, maximum) in LIMITS.items():
        value = payload.get(key, DEFAULT_INPUTS[key])
        if isinstance(value, bool):
            raise ValueError(f"{key} must be a number.")
        try:
            number = float(value)
        except (TypeError, ValueError) as error:
            raise ValueError(f"{key} must be a number.") from error
        if not np.isfinite(number) or not minimum <= number <= maximum:
            raise ValueError(f"{key} must be between {minimum:g} and {maximum:g}.")
        inputs[key] = number
    return inputs


def load_historical_records() -> list[dict[str, Any]]:
    """Load the project's joined, timestamped generation and weather observations."""
    dataset_path = Path(app.config["HISTORICAL_DATASET"])
    try:
        file_stat = dataset_path.stat()
    except OSError as error:
        raise FileNotFoundError(
            "The historical solar dataset could not be opened."
        ) from error
    return _read_historical_records(
        str(dataset_path), file_stat.st_mtime_ns, file_stat.st_size
    )


@lru_cache(maxsize=4)
def _read_historical_records(
    dataset_path_string: str, _modified_ns: int, _file_size: int
) -> list[dict[str, Any]]:
    dataset_path = Path(dataset_path_string)
    try:
        with dataset_path.open(newline="", encoding="utf-8-sig") as file:
            reader = csv.DictReader(file)
            required_columns = {
                "DATE_TIME",
                "ac_power_kw",
                "energy_kwh_15min",
                "ambient_temperature_c",
                "module_temperature_c",
                "irradiation",
            }
            if not reader.fieldnames or not required_columns.issubset(reader.fieldnames):
                raise ValueError(
                    "The historical dataset is missing required generation or weather columns."
                )
            records = []
            for line_number, row in enumerate(reader, start=2):
                try:
                    timestamp = datetime.strptime(
                        row["DATE_TIME"], "%Y-%m-%d %H:%M:%S"
                    )
                    values = {
                        key: float(row[column])
                        for key, column in (
                            ("ac_power_kw", "ac_power_kw"),
                            ("energy_kwh_15min", "energy_kwh_15min"),
                            ("ambient_temperature_c", "ambient_temperature_c"),
                            ("module_temperature_c", "module_temperature_c"),
                            ("irradiation", "irradiation"),
                        )
                    }
                except (TypeError, ValueError) as error:
                    raise ValueError(
                        f"The historical dataset contains an invalid record on row {line_number}."
                    ) from error
                if not all(np.isfinite(value) for value in values.values()):
                    raise ValueError(
                        f"The historical dataset contains a non-finite value on row {line_number}."
                    )
                if values["ac_power_kw"] < 0 or values["energy_kwh_15min"] < 0:
                    raise ValueError(
                        f"The historical dataset contains negative generation on row {line_number}."
                    )
                records.append(
                    {
                        "timestamp": timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                        "date": timestamp.date().isoformat(),
                        **values,
                    }
                )
    except OSError as error:
        raise FileNotFoundError(
            "The historical solar dataset could not be opened."
        ) from error
    if not records:
        raise ValueError("The historical solar dataset contains no observations.")
    records.sort(key=lambda record: record["timestamp"])
    if len({record["timestamp"] for record in records}) != len(records):
        raise ValueError("The historical solar dataset contains duplicate timestamps.")
    return records


def predict_yields(
    inputs_batch: list[dict[str, float]],
) -> list[tuple[float, float]]:
    if not inputs_batch:
        return []
    bundle = get_model_bundle()
    values = np.array(
        [[inputs[key] for key in FEATURES] for inputs in inputs_batch],
        dtype=float,
    )
    model = bundle["model"]
    tree_predictions = np.asarray(
        [tree.predict(values) for tree in model.estimators_],
        dtype=float,
    )
    predictions = tree_predictions.mean(axis=0)
    confidences = tree_predictions.std(axis=0)
    results = []
    for index, inputs in enumerate(inputs_batch):
        physical_ceiling = estimate_physical_yield(
            inputs["sunlight_intensity"],
            inputs["temperature"],
            inputs["panel_capacity"],
            inputs["cloud_coverage"],
        ) * 1.12
        prediction = min(physical_ceiling, max(0.0, float(predictions[index])))
        results.append((round(prediction, 2), round(float(confidences[index]), 2)))
    return results


def predict_yield(inputs: dict[str, float]) -> tuple[float, float]:
    return predict_yields([inputs])[0]


def hourly_profile(inputs: dict[str, float], daily_kwh: float) -> list[dict[str, Any]]:
    daylight_weights = [0.02, 0.06, 0.12, 0.18, 0.21, 0.19, 0.13, 0.07, 0.02]
    denominator = sum(daylight_weights)
    output = []
    for index, weight in enumerate(daylight_weights):
        hour = index + 8
        temperature_loss = max(0.78, 1 - max(0, inputs["temperature"] - 30) * 0.004)
        cloud_variability = 1 - inputs["cloud_coverage"] / 100 * 0.15 * (index % 2)
        output.append(
            {
                "hour": f"{hour:02d}:00",
                "generation_kwh": round(daily_kwh * weight / denominator * temperature_loss * cloud_variability, 2),
            }
        )
    total = sum(row["generation_kwh"] for row in output)
    if total > 0:
        scale = daily_kwh / total
        for row in output:
            row["generation_kwh"] = round(row["generation_kwh"] * scale, 2)
    return output


def historical_hourly_profile(
    records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    buckets: dict[int, list[dict[str, Any]]] = {}
    for record in records:
        hour = int(record["timestamp"][11:13])
        buckets.setdefault(hour, []).append(record)

    profile = []
    for hour in sorted(buckets):
        samples = buckets[hour]
        observed_minutes = {
            int(record["timestamp"][14:16]) for record in samples
        }
        profile.append(
            {
                "hour": f"{hour:02d}:00",
                "generation_kwh": round(
                    sum(record["energy_kwh_15min"] for record in samples), 2
                ),
                "average_power_kw": round(
                    sum(record["ac_power_kw"] for record in samples) / len(samples), 2
                ),
                "observation_count": len(samples),
                "complete": observed_minutes == {0, 15, 30, 45},
            }
        )
    return profile


def historical_scheduler_snapshots(
    records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Calculate a retrospective appliance schedule at each observed record."""
    snapshots = []
    for index, record in enumerate(records):
        observed_records = records[: index + 1]
        profile = historical_hourly_profile(observed_records)
        snapshots.append(
            {
                "timestamp": record["timestamp"],
                "scheduler": build_scheduler(profile, record["date"]),
            }
        )
    return snapshots


def build_advice(inputs: dict[str, float], daily_kwh: float, confidence: float) -> list[dict[str, str]]:
    tips = []
    if inputs["cloud_coverage"] >= 45:
        tips.append(
            {
                "title": "Cloud cover is the main constraint",
                "detail": f"At {inputs['cloud_coverage']:.0f}% cloud cover, shift flexible loads into the brighter midday window.",
                "tag": "WEATHER",
            }
        )
    if inputs["temperature"] > 32:
        tips.append(
            {
                "title": "Give the panels room to breathe",
                "detail": "High cell temperatures reduce output. Keep the rear ventilation gap clear and check for trapped debris.",
                "tag": "COOLING",
            }
        )
    if inputs["sunlight_intensity"] < 550:
        tips.append(
            {
                "title": "Check for avoidable shade",
                "detail": "Trim nearby branches and inspect morning and afternoon shade; small obstructions can affect an entire string.",
                "tag": "SITE CHECK",
            }
        )
    if inputs["cloud_coverage"] < 25 and inputs["temperature"] <= 32:
        tips.append(
            {
                "title": "A strong window for flexible loads",
                "detail": "Clear, moderate conditions favor direct solar use. Run high-draw appliances around solar noon.",
                "tag": "GOOD WINDOW",
            }
        )
    if confidence > max(0.4, daily_kwh * 0.16):
        tips.append(
            {
                "title": "Treat this forecast as a wider range",
                "detail": "The model is less certain on this estimate; use it as a planning guide, not a guarantee.",
                "tag": "MODEL NOTE",
            }
        )
    tips.append(
        {
            "title": "Keep the surface clean",
            "detail": "A quick check for dust, leaves, or bird residue helps maintain consistent light capture.",
            "tag": "MAINTENANCE",
        }
    )
    return tips[:4]


def build_scheduler(
    profile: list[dict[str, Any]], historical_date: str | None = None
) -> list[dict[str, Any]]:
    """Rank complete hourly windows by recorded energy and appliance demand."""
    hourly_energy: dict[int, float] = {}
    for row in profile:
        hour = int(row["hour"][:2])
        if row.get("complete", True):
            hourly_energy[hour] = float(row["generation_kwh"])

    recommendations = []
    for appliance in APPLIANCES:
        candidates = []
        for start_hour in range(24):
            end_hour = start_hour + appliance["duration"]
            overlapping_hours = range(start_hour, int(np.ceil(end_hour)))
            if any(hour not in hourly_energy for hour in overlapping_hours):
                continue
            available_energy = 0.0
            available_power = []
            for hour in overlapping_hours:
                overlap = max(
                    0.0,
                    min(end_hour, hour + 1) - max(float(start_hour), float(hour)),
                )
                if overlap:
                    energy = hourly_energy[hour] * overlap
                    available_energy += energy
                    available_power.append(hourly_energy[hour])
            required_energy = appliance["kw"] * appliance["duration"]
            supported = (
                available_energy >= required_energy
                and min(available_power, default=0.0) >= appliance["kw"]
            )
            if available_energy > 0 and any(power > 0 for power in available_power):
                candidates.append(
                    {
                        "start_hour": start_hour,
                        "end_hour": end_hour,
                        "available_energy": available_energy,
                        "required_energy": required_energy,
                        "supported": supported,
                    }
                )
        recommendation = max(
            candidates,
            key=lambda item: (
                item["supported"],
                item["available_energy"],
                -item["start_hour"],
            ),
            default=None,
        )
        if recommendation is None:
            start = end = "Unavailable"
            available_energy = 0.0
            required_energy = appliance["kw"] * appliance["duration"]
            supported = False
            coverage = 0
            status = "No complete hourly window in the available records"
        else:
            start_hour = recommendation["start_hour"]
            end_minutes = round(recommendation["end_hour"] * 60)
            end = f"{end_minutes // 60:02d}:{end_minutes % 60:02d}"
            start = f"{start_hour:02d}:00"
            if historical_date:
                start = f"{historical_date} {start}"
                end = f"{historical_date} {end}"
            available_energy = recommendation["available_energy"]
            required_energy = recommendation["required_energy"]
            supported = recommendation["supported"]
            coverage = min(100, round(available_energy / required_energy * 100)) if required_energy else 0
            if historical_date:
                status = "Aggregate output covers load" if supported else "Partial aggregate output"
            else:
                status = "Solar-ready" if supported else "Partial solar"
        recommendations.append(
            {
                **appliance,
                "start": start,
                "end": end,
                "available_energy_kwh": round(available_energy, 2),
                "required_energy_kwh": round(required_energy, 2),
                "solar_coverage": coverage,
                "status": status,
            }
        )
    return recommendations


def weather_impact(
    estimates: list[tuple[float, float]],
) -> list[dict[str, Any]]:
    labels = ["Current conditions", "Clear skies", "Cooler panels"]
    prediction = estimates[0][0]
    return [
        {
            "label": label,
            "generation_kwh": estimate,
            "change_kwh": round(estimate - prediction, 2),
        }
        for label, (estimate, _) in zip(labels, estimates, strict=True)
    ]


def save_forecast(inputs: dict[str, float], generation_kwh: float) -> None:
    created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with db_connection() as connection:
        connection.execute(
            """
            INSERT INTO forecasts (
                created_at, sunlight_intensity, temperature,
                panel_capacity, cloud_coverage, generation_kwh
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                created_at,
                inputs["sunlight_intensity"],
                inputs["temperature"],
                inputs["panel_capacity"],
                inputs["cloud_coverage"],
                generation_kwh,
            ),
        )


def parse_bounded_number(
    payload: dict[str, Any], key: str, minimum: float, maximum: float
) -> float:
    value = payload.get(key)
    if isinstance(value, bool):
        raise ValueError(f"{key} must be a number.")
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{key} must be a number.") from error
    if not np.isfinite(number) or not minimum <= number <= maximum:
        raise ValueError(f"{key} must be between {minimum:g} and {maximum:g}.")
    return number


def save_insight_record(record_type: str, payload: dict[str, Any]) -> int:
    created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with db_connection() as connection:
        cursor = connection.execute(
            """
            INSERT INTO insight_records (record_type, created_at, payload_json)
            VALUES (?, ?, ?)
            """,
            (record_type, created_at, json.dumps(payload, separators=(",", ":"))),
        )
        return int(cursor.lastrowid)


def consecutive_underperformance_days() -> int:
    """Count consecutive UTC dates with saved manual underperformance readings."""
    with db_connection() as connection:
        rows = connection.execute(
            """
            SELECT created_at, payload_json
            FROM insight_records
            WHERE record_type = 'health'
            ORDER BY id DESC
            LIMIT 100
            """
        ).fetchall()

    results_by_date: dict[str, bool] = {}
    for row in rows:
        try:
            payload = json.loads(row["payload_json"])
        except (json.JSONDecodeError, TypeError):
            continue
        if payload.get("reading_mode") != "manual":
            continue
        date_key = row["created_at"][:10]
        if date_key not in results_by_date:
            results_by_date[date_key] = bool(payload.get("underperformance_detected"))

    if not results_by_date:
        return 0

    dates = sorted(results_by_date, reverse=True)
    consecutive = 0
    expected_date = datetime.strptime(dates[0], "%Y-%m-%d").date()
    for date_key in dates:
        date_value = datetime.strptime(date_key, "%Y-%m-%d").date()
        if date_value != expected_date or not results_by_date[date_key]:
            break
        consecutive += 1
        expected_date -= timedelta(days=1)
    return consecutive


def require_json_object() -> dict[str, Any] | None:
    payload = request.get_json(silent=True)
    return payload if isinstance(payload, dict) else None


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/prediction")
def prediction_page():
    return render_template("section.html", page="prediction")


@app.get("/weather")
def weather_page():
    return render_template("section.html", page="weather")


@app.get("/simulator")
def simulator_page():
    return render_template("section.html", page="simulator")


@app.get("/advisor")
def advisor_page():
    return render_template("section.html", page="advisor")


@app.get("/scheduler")
def scheduler_page():
    return render_template("section.html", page="scheduler")


@app.get("/history")
def history_page():
    return render_template("section.html", page="history")


@app.get("/insights")
def insights_page():
    return render_template("section.html", page="insights")


@app.get("/api/health")
def health():
    bundle = get_model_bundle()
    return jsonify({"status": "ok", "model_version": bundle["version"]})


@app.post("/api/predict")
def predict():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "Send the forecast inputs as a JSON object."}), 400
    try:
        inputs = parse_inputs(payload)
    except ValueError as error:
        return jsonify({"error": str(error)}), 400

    estimates = predict_yields(
        [
            inputs,
            {**inputs, "cloud_coverage": 0.0},
            {**inputs, "temperature": min(inputs["temperature"], 25.0)},
        ]
    )
    generation, confidence = estimates[0]
    profile = hourly_profile(inputs, generation)
    peak_hour = max(profile, key=lambda row: row["generation_kwh"])["hour"]
    if payload.get("save_history", True):
        save_forecast(inputs, generation)
    return jsonify(
        {
            "inputs": inputs,
            "generation_kwh": generation,
            "confidence_range_kwh": confidence,
            "confidence_percent": max(55, min(98, round(100 - confidence / max(generation, 1) * 100))),
            "hourly": profile,
            "weather_impact": weather_impact(estimates),
            "advice": build_advice(inputs, generation, confidence),
            "scheduler": build_scheduler(profile),
            "peak_hour": peak_hour,
            "carbon_avoided_kg": round(generation * GRID_CO2_KG_PER_KWH, 1),
            "solar_fit_score": max(1, min(100, round(100 - inputs["cloud_coverage"] * 0.36 - max(0, inputs["temperature"] - 25) * 0.6))),
            "model_version": get_model_bundle()["version"],
        }
    )


@app.get("/api/history")
def history():
    try:
        limit = int(request.args.get("limit", 20))
    except ValueError:
        return jsonify({"error": "limit must be a whole number."}), 400
    if not 1 <= limit <= 100:
        return jsonify({"error": "limit must be between 1 and 100."}), 400
    with db_connection() as connection:
        rows = connection.execute(
            """
            SELECT id, created_at, sunlight_intensity, temperature,
                   panel_capacity, cloud_coverage, generation_kwh
            FROM forecasts ORDER BY id DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return jsonify({"forecasts": [dict(row) for row in reversed(rows)]})


@app.get("/api/simulation/dates")
def historical_simulation_dates():
    try:
        records = load_historical_records()
    except (FileNotFoundError, ValueError) as error:
        return jsonify({"error": str(error)}), 503
    by_date: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        by_date.setdefault(record["date"], []).append(record)
    return jsonify(
        {
            "source": "data/real_solar_training_data.csv",
            "description": (
                "Historical Plant 1 generation and weather observations; no live "
                "inverter or weather connection."
            ),
            "dates": [
                {
                    "date": date,
                    "observation_count": len(day_records),
                    "first_timestamp": day_records[0]["timestamp"],
                    "last_timestamp": day_records[-1]["timestamp"],
                }
                for date, day_records in by_date.items()
            ],
        }
    )


@app.get("/api/simulation/dataset-info")
def historical_dataset_info():
    try:
        records = load_historical_records()
        model_bundle = get_model_bundle()
        with MODEL_DATASET_PATH.open(newline="", encoding="utf-8") as file:
            training_record_count = sum(1 for _ in csv.DictReader(file))
    except (FileNotFoundError, OSError, ValueError) as error:
        return jsonify({"error": f"Dataset or model information is unavailable: {error}"}), 503

    timestamps = [
        datetime.strptime(record["timestamp"], "%Y-%m-%d %H:%M:%S")
        for record in records
    ]
    interval_counts = Counter(
        int((current - previous).total_seconds() // 60)
        for previous, current in zip(timestamps, timestamps[1:])
    )
    nominal_interval = interval_counts.most_common(1)[0][0] if interval_counts else None
    non_nominal_gaps = sum(
        count for interval, count in interval_counts.items()
        if interval != nominal_interval
    )
    model = model_bundle["model"]
    return jsonify(
        {
            "historical_dataset": {
                "source_file": "data/real_solar_training_data.csv",
                "source_description": (
                    "Plant 1 generation observations joined with Plant 1 weather sensor observations."
                ),
                "record_count": len(records),
                "start_timestamp": records[0]["timestamp"],
                "end_timestamp": records[-1]["timestamp"],
                "nominal_sampling_interval_minutes": nominal_interval,
                "non_nominal_gap_count": non_nominal_gaps,
                "energy_basis": (
                    "Monthly totals sum the stored energy_kwh_15min values; missing "
                    "records are not interpolated."
                ),
                "scope_note": (
                    "Generation is aggregated across Plant 1 inverters. It is not a "
                    "residential meter and does not represent a 6.5 kWp household system."
                ),
            },
            "model": {
                "algorithm": type(model).__name__,
                "version": model_bundle["version"],
                "training_source": (
                    "Reproducibly generated synthetic, physically informed examples; "
                    "separate from the historical playback dataset."
                ),
                "training_record_count": training_record_count,
                "features": model_bundle.get("features", FEATURES),
            },
        }
    )


@app.get("/api/simulation/day")
def historical_simulation_day():
    requested_date = request.args.get("date", "")
    try:
        normalized_date = datetime.strptime(requested_date, "%Y-%m-%d").date().isoformat()
        if normalized_date != requested_date:
            raise ValueError
    except ValueError:
        return jsonify({"error": "date must be a valid YYYY-MM-DD date."}), 400
    try:
        records = load_historical_records()
    except (FileNotFoundError, ValueError) as error:
        return jsonify({"error": str(error)}), 503
    day_records = [record for record in records if record["date"] == normalized_date]
    if not day_records:
        return jsonify({"error": "No historical observations exist for this date."}), 404
    hourly = historical_hourly_profile(day_records)
    peak_record = max(day_records, key=lambda record: record["ac_power_kw"])
    response = {
        "date": normalized_date,
        "source": "data/real_solar_training_data.csv",
        "description": (
            "Historical Plant 1 observations. The stored AC power and interval "
            "energy values are replayed as supplied; no records are interpolated."
        ),
        "observation_count": len(day_records),
        "peak_ac_power_kw": round(peak_record["ac_power_kw"], 2),
        "estimated_plant_capacity_kwp": round(
            max(record["ac_power_kw"] for record in records) * 1.1, 2
        ),
        "peak_timestamp": peak_record["timestamp"],
        "hourly": hourly,
        "records": day_records,
    }
    if request.args.get("include_scheduler") == "1":
        response["scheduler_snapshots"] = historical_scheduler_snapshots(day_records)
    return jsonify(response)


@app.get("/api/simulation/scheduler")
def historical_simulation_scheduler():
    requested_date = request.args.get("date", "")
    requested_through = request.args.get("through", "")
    try:
        normalized_date = datetime.strptime(requested_date, "%Y-%m-%d").date().isoformat()
        timestamp = datetime.strptime(requested_through, "%Y-%m-%d %H:%M:%S")
        if normalized_date != requested_date or timestamp.strftime("%Y-%m-%d %H:%M:%S") != requested_through:
            raise ValueError
        if timestamp.date().isoformat() != normalized_date:
            raise ValueError
    except ValueError:
        return jsonify(
            {"error": "date and through must be a matching date and YYYY-MM-DD HH:MM:SS timestamp."}
        ), 400
    try:
        records = load_historical_records()
    except (FileNotFoundError, ValueError) as error:
        return jsonify({"error": str(error)}), 503
    observed_records = [
        record
        for record in records
        if record["date"] == normalized_date
        and record["timestamp"] <= requested_through
    ]
    if not observed_records:
        return jsonify({"error": "No historical observations exist through this timestamp."}), 404
    hourly = historical_hourly_profile(observed_records)
    return jsonify(
        {
            "date": normalized_date,
            "through": requested_through,
            "scheduler": build_scheduler(hourly, normalized_date),
        }
    )


@app.get("/api/simulation/monthly-report")
def historical_monthly_report():
    try:
        electricity_rate = parse_bounded_number(
            {"electricity_rate": request.args.get("rate", "8.5")},
            "electricity_rate",
            0.001,
            10000,
        )
        currency = request.args.get("currency", "INR")
        if currency not in CURRENCY_SYMBOLS:
            raise ValueError("currency must be INR, USD, EUR, or GBP.")
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    try:
        records = load_historical_records()
    except (FileNotFoundError, ValueError) as error:
        return jsonify({"error": str(error)}), 503

    months: dict[str, dict[str, Any]] = {}
    for record in records:
        timestamp = datetime.strptime(record["timestamp"], "%Y-%m-%d %H:%M:%S")
        month_key = timestamp.strftime("%Y-%m")
        month = months.setdefault(
            month_key,
            {
                "energy_kwh": 0.0,
                "record_count": 0,
                "days": set(),
                "first_date": record["date"],
                "last_date": record["date"],
            },
        )
        month["energy_kwh"] += record["energy_kwh_15min"]
        month["record_count"] += 1
        month["days"].add(record["date"])
        month["first_date"] = min(month["first_date"], record["date"])
        month["last_date"] = max(month["last_date"], record["date"])

    report_months = []
    for month_key, month in sorted(months.items()):
        year, month_number = (int(value) for value in month_key.split("-"))
        days_in_month = calendar.monthrange(year, month_number)[1]
        days_with_records = len(month["days"])
        report_months.append(
            {
                "month": month_key,
                "label": datetime(year, month_number, 1).strftime("%B %Y"),
                "generation_kwh": round(month["energy_kwh"], 2),
                "estimated_savings": round(month["energy_kwh"] * electricity_rate, 2),
                "estimated_co2_avoided_kg": round(
                    month["energy_kwh"] * GRID_CO2_KG_PER_KWH, 2
                ),
                "record_count": month["record_count"],
                "days_with_records": days_with_records,
                "days_in_month": days_in_month,
                "first_date": month["first_date"],
                "last_date": month["last_date"],
                "partial_month": (
                    month["first_date"] != f"{month_key}-01"
                    or month["last_date"] != f"{month_key}-{days_in_month:02d}"
                    or days_with_records != days_in_month
                ),
            }
        )
    return jsonify(
        {
            "source": "data/real_solar_training_data.csv",
            "currency": currency,
            "currency_symbol": CURRENCY_SYMBOLS[currency],
            "electricity_rate": electricity_rate,
            "months": report_months,
            "disclaimer": (
                "Monthly totals sum the stored energy_kwh_15min values without filling "
                "missing records. Historical energy is aggregated across Plant 1 "
                "inverters, not a residential 6.5 kWp system. Savings are illustrative "
                "gross tariff values, not household bill savings. CO₂ uses an assumed "
                f"grid-offset factor of {GRID_CO2_KG_PER_KWH:.2f} kg/kWh. Partial months are not extrapolated."
            ),
        }
    )


def demonstration_seven_day_values(predicted_kwh: float) -> dict[str, Any]:
    """Return clearly labeled fake values for project and presentation demonstrations."""
    dates = [
        "2026-11-16",
        "2026-11-17",
        "2026-11-18",
        "2026-11-19",
        "2026-11-20",
        "2026-11-21",
        "2026-11-22",
    ]
    actual_values = [3.2, 2.8, 3.0, 2.5, 2.7, 2.4, 2.6]
    daily_totals = [
        {"date": date, "generation_kwh": actual}
        for date, actual in zip(dates, actual_values, strict=True)
    ]
    average_actual = round(sum(actual_values) / len(actual_values), 2)
    return {
        "week_start": dates[0],
        "week_end": dates[-1],
        "daily_totals": daily_totals,
        "average_actual_kwh": average_actual,
        "latest_actual_kwh": actual_values[-1],
        "predicted_reference_kwh": round(predicted_kwh, 2),
        "is_fake": True,
    }


@app.post("/api/insights/health")
def solar_health():
    payload = require_json_object()
    if payload is None:
        return jsonify({"error": "Send the health check as a JSON object."}), 400
    demo_week = None
    try:
        inputs = parse_inputs(payload)
        reading_mode = payload.get("reading_mode")
        prediction, _ = predict_yield(inputs)
        if reading_mode == "manual":
            comparison_kwh = parse_bounded_number(
                payload, "reported_generation_kwh", 0, 1000
            )
            reading_label = "Manually entered reading (not verified)"
        elif reading_mode == "demo":
            demo_week = demonstration_seven_day_values(prediction)
            comparison_kwh = demo_week["latest_actual_kwh"]
            reading_label = (
                f"Seven-day sample reading · {demo_week['week_end']}"
            )
        else:
            raise ValueError("reading_mode must be manual or demo.")
    except (FileNotFoundError, ValueError) as error:
        return jsonify({"error": str(error)}), 400

    deviation_percent = (
        abs(comparison_kwh - prediction) / prediction * 100
        if prediction > 0
        else (0 if comparison_kwh == 0 else 100)
    )
    signed_deviation_percent = (
        (comparison_kwh - prediction) / prediction * 100
        if prediction > 0
        else (0 if comparison_kwh == 0 else 100)
    )
    deviation_direction = (
        "below" if signed_deviation_percent < -0.05
        else "above" if signed_deviation_percent > 0.05
        else "matches"
    )
    shortfall_kwh = max(0.0, prediction - comparison_kwh)
    shortfall_percent = (
        shortfall_kwh / prediction * 100 if prediction > 0 else 0.0
    )
    underperformance = shortfall_percent >= 15
    if reading_mode == "demo":
        underperformance = True
        shortfall_percent = round(deviation_percent, 1)
    score = max(0, round(100 - min(100, deviation_percent * 1.5)))

    possible_causes: list[str] = []
    actions: list[str] = []
    if underperformance:
        if reading_mode == "demo" and demo_week:
            actions = [
                "For seven consecutive low-reading days, inspect the affected solar panel.",
                "Ask a qualified technician to verify output, wiring, and panel condition.",
                "Replace the particular underperforming panel if the technician confirms "
                "that it is damaged or degraded.",
            ]
            status = "This week-long difference is large"
        else:
            status = "A shortfall appears in this comparison"
            if inputs["cloud_coverage"] >= 35 or inputs["sunlight_intensity"] < 500:
                possible_causes.append("Cloud cover or low sunlight may explain part of the gap.")
            possible_causes.extend(
                [
                    "Dust or residue on the panels could reduce light reaching the cells.",
                    "Nearby trees, buildings, or temporary shade could reduce output.",
                ]
            )
            if inputs["temperature"] >= 32:
                possible_causes.append("High panel temperatures may reduce conversion efficiency.")
            if shortfall_percent >= 35:
                possible_causes.append(
                    "An inverter, wiring, or connection issue is one possibility to have checked; it is not detected by this app."
                )
            actions = [
                "Compare readings across several similar, clear-sky days before drawing a conclusion.",
                "From the ground, look for visible dirt or new shading; do not climb onto the roof.",
                "If a large gap persists, ask a qualified solar technician to inspect the system.",
            ]
    elif comparison_kwh > prediction * 1.15:
        status = "The entered reading is above the model estimate"
        actions = [
            "Keep recording readings to establish a reliable comparison over time.",
            "Check that the entered time period matches the model's daily estimate.",
        ]
    else:
        status = "No unusual drop in this comparison"
        actions = [
            "Continue comparing readings from the same time period and similar weather conditions.",
        ]

    result = {
        "predicted_generation_kwh": prediction,
        "comparison_generation_kwh": round(comparison_kwh, 2),
        "expected_generation_kwh": prediction,
        "actual_generation_kwh": round(comparison_kwh, 2),
        "reading_mode": reading_mode,
        "reading_label": reading_label,
        "verified": False,
        "health_score": score,
        "deviation_percent": round(deviation_percent, 1),
        "signed_deviation_percent": round(signed_deviation_percent, 1),
        "deviation_direction": deviation_direction,
        "shortfall_kwh": round(shortfall_kwh, 2),
        "shortfall_percent": round(shortfall_percent, 1),
        "underperformance_detected": underperformance,
        "status": status,
        "possible_causes": possible_causes,
        "recommended_actions": actions,
        "disclaimer": (
            ""
            if reading_mode == "demo"
            else "SolarWise is not connected to an inverter. Manual values are unverified."
        ),
    }
    if reading_mode == "demo" and demo_week:
        result["demo_week"] = demo_week
    result["record_id"] = save_insight_record("health", result)
    consecutive_days = consecutive_underperformance_days()
    notification_required = underperformance
    panel_review_recommended = underperformance and consecutive_days >= 3
    if reading_mode == "demo" and demo_week:
        consecutive_days = 7
        panel_review_recommended = True
        notification_title = "Severe one-week underperformance"
        notification_message = (
            f"It has been a full week, and actual generation stayed low "
            f"at {demo_week['average_actual_kwh']:.2f} kWh/day versus a predicted "
            f"{demo_week['predicted_reference_kwh']:.2f} kWh/day. The difference is "
            "huge. It is better to inspect and replace the particular underperforming "
            "solar panel after qualified verification."
        )
    elif panel_review_recommended:
        notification_title = "Persistent solar underperformance"
        notification_message = (
            f"Actual generation has been at least {shortfall_percent:.1f}% below "
            f"the estimate for {consecutive_days} consecutive days. Have a qualified "
            "solar technician inspect the system and consider whether panel replacement "
            "is appropriate."
        )
    elif notification_required:
        notification_title = "Solar output shortfall"
        notification_message = (
            f"Actual generation is {shortfall_percent:.1f}% below the predicted "
            f"{prediction:.2f} kWh estimate."
        )
    else:
        notification_title = ""
        notification_message = ""

    result.update(
        {
            "notification_required": notification_required,
            "notification_title": notification_title,
            "notification_message": notification_message,
            "consecutive_underperformance_days": consecutive_days,
            "panel_review_recommended": panel_review_recommended,
        }
    )
    with db_connection() as connection:
        connection.execute(
            "UPDATE insight_records SET payload_json = ? WHERE id = ?",
            (json.dumps(result, separators=(",", ":")), result["record_id"]),
        )
    return jsonify(result)


@app.post("/api/insights/cleaning")
def cleaning_advice():
    payload = require_json_object()
    if payload is None:
        return jsonify({"error": "Send the cleaning assessment as a JSON object."}), 400
    try:
        inputs = parse_inputs(payload)
        soiling_percent = parse_bounded_number(payload, "soiling_percent", 0, 50)
        days_since_cleaning = parse_bounded_number(
            payload, "days_since_cleaning", 0, 3650
        )
        if not days_since_cleaning.is_integer():
            raise ValueError("days_since_cleaning must be a whole number.")
    except ValueError as error:
        return jsonify({"error": str(error)}), 400

    generation, _ = predict_yield(inputs)
    estimated_loss = round(generation * soiling_percent / 100, 2)
    recovery = estimated_loss
    if soiling_percent >= 10:
        recommendation = "Cleaning may be worthwhile based on your high soiling estimate."
    elif soiling_percent >= 5 or days_since_cleaning >= 90:
        recommendation = "Inspect the panels and consider cleaning if residue is visible."
    else:
        recommendation = "No urgent cleaning suggested from these inputs; clean only if buildup is visible."
    result = {
        "predicted_generation_kwh": generation,
        "soiling_percent": round(soiling_percent, 1),
        "days_since_cleaning": int(days_since_cleaning),
        "estimated_loss_kwh": estimated_loss,
        "estimated_recovery_kwh": recovery,
        "recommendation": recommendation,
        "assumption": (
            "Loss uses your reported soiling percentage; recovery assumes the estimated "
            "loss is fully restored and is not guaranteed."
        ),
        "safety_note": (
            "Follow the panel maker's instructions. Do not walk on panels or climb onto "
            "the roof; use a qualified cleaner when access is unsafe."
        ),
    }
    result["record_id"] = save_insight_record("cleaning", result)
    return jsonify(result)


@app.post("/api/insights/savings")
def solar_savings():
    payload = require_json_object()
    if payload is None:
        return jsonify({"error": "Send the savings estimate as a JSON object."}), 400
    try:
        inputs = parse_inputs(payload)
        rate = parse_bounded_number(payload, "electricity_rate", 0.001, 10000)
        currency = payload.get("currency", "INR")
        if not isinstance(currency, str) or currency not in CURRENCY_SYMBOLS:
            raise ValueError("currency must be INR, USD, EUR, or GBP.")
    except ValueError as error:
        return jsonify({"error": str(error)}), 400

    generation, _ = predict_yield(inputs)
    daily = round(generation * rate, 2)
    result = {
        "generation_kwh_per_day": generation,
        "electricity_rate": round(rate, 4),
        "currency": currency,
        "currency_symbol": CURRENCY_SYMBOLS[currency],
        "daily_savings": daily,
        "weekly_savings": round(daily * 7, 2),
        "monthly_savings": round(daily * 30, 2),
        "yearly_savings": round(daily * 365, 2),
        "yearly_generation_kwh": round(generation * 365, 2),
        "assumption": (
            "Gross potential value assumes every generated kWh offsets a grid kWh at "
            "your entered rate; it excludes export compensation, fixed charges, and taxes."
        ),
    }
    result["record_id"] = save_insight_record("savings", result)
    return jsonify(result)


@app.post("/api/insights/weather-risk")
def solar_weather_risk():
    payload = require_json_object()
    if payload is None:
        return jsonify({"error": "Send the weather scenario as a JSON object."}), 400
    try:
        inputs = parse_inputs(payload)
        rain_scenario = payload.get("rain_scenario", "none")
        if not isinstance(rain_scenario, str) or rain_scenario not in {"none", "light", "heavy"}:
            raise ValueError("rain_scenario must be none, light, or heavy.")
    except ValueError as error:
        return jsonify({"error": str(error)}), 400

    generation, clear_generation, cooler_generation = (
        estimate[0]
        for estimate in predict_yields(
            [
                inputs,
                {**inputs, "cloud_coverage": 0.0},
                {**inputs, "temperature": min(inputs["temperature"], 25.0)},
            ]
        )
    )
    cloud_loss = round(max(0.0, clear_generation - generation), 2)
    heat_loss = round(max(0.0, cooler_generation - generation), 2)
    rain_fraction = {"none": 0.0, "light": 0.02, "heavy": 0.05}[rain_scenario]
    rain_loss = round(generation * rain_fraction, 2)
    total_loss = round(min(generation, cloud_loss + heat_loss + rain_loss), 2)
    risk_percent = round(total_loss / generation * 100, 1) if generation > 0 else 0.0
    risk_level = "high" if risk_percent >= 30 else "moderate" if risk_percent >= 12 else "low"
    alerts: list[str] = []
    if inputs["cloud_coverage"] >= 60:
        alerts.append(
            f"High cloud warning: {inputs['cloud_coverage']:.0f}% cloud cover may lower solar output by about {cloud_loss:.2f} kWh/day versus clear-sky conditions."
        )
    elif inputs["cloud_coverage"] >= 20:
        alerts.append(
            f"Cloud warning: {inputs['cloud_coverage']:.0f}% cloud cover may lower solar output by about {cloud_loss:.2f} kWh/day versus clear-sky conditions."
        )
    if inputs["temperature"] >= 40:
        alerts.append(
            f"Extreme-heat warning: {inputs['temperature']:.0f} °C is above the model's 25 °C reference; estimated heat-related output difference is {heat_loss:.2f} kWh/day."
        )
    elif inputs["temperature"] >= 32:
        alerts.append(
            f"Heat warning: {inputs['temperature']:.0f} °C is above the model's 25 °C reference; estimated heat-related output difference is {heat_loss:.2f} kWh/day."
        )
    if rain_scenario == "heavy":
        alerts.append(
            f"Heavy-rain scenario: an illustrative {rain_fraction * 100:.0f}% short-term allowance adds {rain_loss:.2f} kWh/day of estimated impact; actual effects vary."
        )
    elif rain_scenario == "light":
        alerts.append(
            f"Light-rain scenario: an illustrative {rain_fraction * 100:.0f}% short-term allowance adds {rain_loss:.2f} kWh/day of estimated impact; actual effects vary."
        )
    if not alerts:
        alerts.append("No significant solar-output warning is indicated for the selected conditions.")

    result = {
        "generation_kwh": generation,
        "cloud_coverage": inputs["cloud_coverage"],
        "temperature": inputs["temperature"],
        "rain_scenario": rain_scenario,
        "estimated_cloud_loss_kwh": cloud_loss,
        "estimated_heat_loss_kwh": heat_loss,
        "estimated_rain_loss_kwh": rain_loss,
        "estimated_total_loss_kwh": total_loss,
        "estimated_loss_percent": risk_percent,
        "risk_level": risk_level,
        "alerts": alerts,
        "disclaimer": (
            "Weather warnings are estimates based on the conditions entered; rain impact "
            "is illustrative and actual effects vary."
        ),
    }
    result["record_id"] = save_insight_record("weather_risk", result)
    return jsonify(result)


@app.get("/api/insights/history")
def insights_history():
    try:
        limit = int(request.args.get("limit", 20))
    except ValueError:
        return jsonify({"error": "limit must be a whole number."}), 400
    if not 1 <= limit <= 100:
        return jsonify({"error": "limit must be between 1 and 100."}), 400
    record_type = request.args.get("type")
    if record_type is not None and record_type not in INSIGHT_TYPES:
        return jsonify({"error": "type must be health, cleaning, savings, or weather_risk."}), 400

    with db_connection() as connection:
        if record_type:
            rows = connection.execute(
                """
                SELECT id, record_type, created_at, payload_json
                FROM insight_records WHERE record_type = ?
                ORDER BY id DESC LIMIT ?
                """,
                (record_type, limit),
            ).fetchall()
        else:
            rows = connection.execute(
                """
                SELECT id, record_type, created_at, payload_json
                FROM insight_records ORDER BY id DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
    records = [
        {
            "id": row["id"],
            "type": row["record_type"],
            "created_at": row["created_at"],
            "result": json.loads(row["payload_json"]),
        }
        for row in rows
    ]
    return jsonify({"records": records})


init_db()

if __name__ == "__main__":
    app.run(debug=True)
