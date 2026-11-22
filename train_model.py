"""Generate a reproducible solar dataset and train the daily-yield model."""

from __future__ import annotations

import csv
import random
from pathlib import Path

import joblib
import numpy as np
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_absolute_error, r2_score


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
MODEL_DIR = ROOT / "models"
DATASET_PATH = DATA_DIR / "solar_training_data.csv"
MODEL_PATH = MODEL_DIR / "solar_yield_model.joblib"
FEATURES = [
    "sunlight_intensity",
    "temperature",
    "panel_capacity",
    "cloud_coverage",
]


def estimate_physical_yield(
    sunlight_intensity: float,
    temperature: float,
    panel_capacity: float,
    cloud_coverage: float,
) -> float:
    """Approximate daily energy using irradiance, temperature, and cloud losses."""
    irradiance_factor = max(0.0, sunlight_intensity / 1000)
    cloud_factor = max(0.22, 1 - 0.68 * cloud_coverage / 100)
    temperature_factor = max(0.72, 1 - 0.004 * max(0, temperature - 25))
    cold_bonus = min(1.06, 1 + 0.0015 * max(0, 25 - temperature))
    return panel_capacity * 5.35 * irradiance_factor * cloud_factor * temperature_factor * cold_bonus


def generate_dataset(path: Path = DATASET_PATH, rows: int = 1800) -> None:
    """Write deterministic, physically informed training examples to CSV."""
    generator = random.Random(42017)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow([*FEATURES, "daily_generation_kwh"])
        for _ in range(rows):
            sunlight = generator.uniform(0, 1200)
            temperature = generator.uniform(-20, 60)
            capacity = generator.uniform(0.5, 50)
            cloud = generator.uniform(0, 100)
            expected = estimate_physical_yield(sunlight, temperature, capacity, cloud)
            measured = max(0, expected * generator.gauss(1, 0.035))
            writer.writerow(
                [
                    round(sunlight, 1),
                    round(temperature, 1),
                    round(capacity, 2),
                    round(cloud, 1),
                    round(measured, 3),
                ]
            )


def train_model() -> dict[str, float | int | str]:
    """Train and persist the estimator, returning useful validation metrics."""
    if not DATASET_PATH.exists():
        generate_dataset()

    with DATASET_PATH.open(newline="", encoding="utf-8") as file:
        rows = list(csv.DictReader(file))
    features = np.array([[float(row[key]) for key in FEATURES] for row in rows])
    target = np.array([float(row["daily_generation_kwh"]) for row in rows])
    x_train, x_test, y_train, y_test = train_test_split(
        features, target, test_size=0.2, random_state=17
    )
    model = RandomForestRegressor(
        n_estimators=180,
        min_samples_leaf=2,
        max_features=1.0,
        random_state=17,
        n_jobs=-1,
    )
    model.fit(x_train, y_train)
    predictions = model.predict(x_test)
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    temporary_model_path = MODEL_PATH.with_name(f"{MODEL_PATH.stem}.tmp{MODEL_PATH.suffix}")
    joblib.dump({"model": model, "features": FEATURES, "version": "1.0.0"}, temporary_model_path)
    temporary_model_path.replace(MODEL_PATH)
    return {
        "dataset_rows": len(rows),
        "mae_kwh": round(float(mean_absolute_error(y_test, predictions)), 3),
        "r2": round(float(r2_score(y_test, predictions)), 4),
        "model_path": str(MODEL_PATH),
    }


if __name__ == "__main__":
    print(train_model())
