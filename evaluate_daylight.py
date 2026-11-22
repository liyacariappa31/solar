
"""Evaluate SolarWise model performance during daylight hours."""

from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import seaborn as sns

from sklearn.metrics import (
    mean_absolute_error,
    mean_squared_error,
    r2_score
)


# Project paths
ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
MODEL_DIR = ROOT / "models"

TEST_FILE = DATA_DIR / "solar_ml_test.csv"
MODEL_FILE = MODEL_DIR / "solar_real_model.joblib"

OUTPUT_DIR = DATA_DIR / "daylight_evaluation"
OUTPUT_DIR.mkdir(exist_ok=True)


def main():

    print("\nLoading test dataset and trained model...")

    test = pd.read_csv(TEST_FILE)

    package = joblib.load(MODEL_FILE)

    model = package["model"]
    features = package["features"]
    target = package["target"]

    # Keep records with positive irradiation
    daylight = test[test["irradiation"] > 0].copy()

    if daylight.empty:
        print("No daylight records found.")
        return

    X_test = daylight[features]
    y_test = daylight[target]

    # Generate predictions
    predictions = model.predict(X_test)

    # Calculate metrics
    mae = mean_absolute_error(y_test, predictions)

    rmse = np.sqrt(
        mean_squared_error(y_test, predictions)
    )

    r2 = r2_score(y_test, predictions)

    print("\nDAYLIGHT MODEL EVALUATION")
    print("-------------------------")

    print("Model:", package["model_name"])
    print("Total test records:", len(test))
    print("Daylight records:", len(daylight))
    print("Excluded records:", len(test) - len(daylight))

    print("\nMAE:", round(mae, 4), "kW")
    print("RMSE:", round(rmse, 4), "kW")
    print("R2 Score:", round(r2, 4))

    # Save daylight predictions
    results = pd.DataFrame({
        "DATE_TIME": daylight["DATE_TIME"],
        "Irradiation": daylight["irradiation"],
        "Actual_kW": y_test.values,
        "Predicted_kW": predictions,
        "Error_kW": y_test.values - predictions
    })

    results.to_csv(
        OUTPUT_DIR / "daylight_predictions.csv",
        index=False
    )

    sns.set_theme(style="whitegrid")

    # 1. Actual vs predicted
    plt.figure(figsize=(8, 6))

    plt.scatter(
        y_test,
        predictions,
        alpha=0.6
    )

    minimum = min(y_test.min(), predictions.min())
    maximum = max(y_test.max(), predictions.max())

    plt.plot(
        [minimum, maximum],
        [minimum, maximum],
        linestyle="--"
    )

    plt.xlabel("Actual Power (kW)")
    plt.ylabel("Predicted Power (kW)")
    plt.title("Daylight: Actual vs Predicted Power")

    plt.tight_layout()

    plt.savefig(
        OUTPUT_DIR / "daylight_actual_vs_predicted.png",
        dpi=150
    )

    plt.close()

    # 2. Prediction error distribution
    errors = y_test.values - predictions

    plt.figure(figsize=(8, 5))

    sns.histplot(
        errors,
        bins=30,
        kde=True
    )

    plt.axvline(0, linestyle="--")

    plt.xlabel("Prediction Error (kW)")
    plt.ylabel("Frequency")
    plt.title("Daylight Prediction Error Distribution")

    plt.tight_layout()

    plt.savefig(
        OUTPUT_DIR / "daylight_error_distribution.png",
        dpi=150
    )

    plt.close()

    # 3. Actual vs predicted over time
    plt.figure(figsize=(12, 5))

    plt.plot(
        range(len(y_test)),
        y_test.values,
        label="Actual",
        linewidth=1.5
    )

    plt.plot(
        range(len(predictions)),
        predictions,
        label="Predicted",
        linewidth=1.5
    )

    plt.xlabel("Daylight Test Record")
    plt.ylabel("Power (kW)")
    plt.title("Daylight Actual vs Predicted Power")
    plt.legend()

    plt.tight_layout()

    plt.savefig(
        OUTPUT_DIR / "daylight_prediction_over_time.png",
        dpi=150
    )

    plt.close()

    print("\nDaylight evaluation files saved in:")
    print(OUTPUT_DIR)

    print("\nDaylight evaluation completed successfully!")


if __name__ == "__main__":
    main()
