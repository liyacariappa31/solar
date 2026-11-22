
"""Evaluate the trained real-world SolarWise model."""

from pathlib import Path

import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
import seaborn as sns
import joblib
import numpy as np
import pandas as pd

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

PLOT_DIR = DATA_DIR / "model_evaluation"
PLOT_DIR.mkdir(exist_ok=True)


def main():

    print("\nLoading test data and trained model...")

    test = pd.read_csv(TEST_FILE)

    # Load saved model package
    package = joblib.load(MODEL_FILE)

    model = package["model"]
    features = package["features"]
    target = package["target"]

    X_test = test[features]
    y_test = test[target]

    # Generate predictions
    predictions = model.predict(X_test)

    # Calculate evaluation metrics
    mae = mean_absolute_error(y_test, predictions)

    rmse = np.sqrt(
        mean_squared_error(y_test, predictions)
    )

    r2 = r2_score(y_test, predictions)

    print("\nMODEL EVALUATION RESULTS")
    print("-----------------------")
    print("Model:", package["model_name"])
    print("MAE:", round(mae, 4), "kW")
    print("RMSE:", round(rmse, 4), "kW")
    print("R2 Score:", round(r2, 4))

    # Save actual vs predicted values
    results = pd.DataFrame({
        "DATE_TIME": test["DATE_TIME"],
        "Actual_kW": y_test,
        "Predicted_kW": predictions,
        "Error_kW": y_test - predictions
    })

    results.to_csv(
        DATA_DIR / "real_model_predictions.csv",
        index=False
    )

    sns.set_theme(style="whitegrid")

    # 1. Actual vs predicted graph
    plt.figure(figsize=(8, 6))

    plt.scatter(
        y_test,
        predictions,
        alpha=0.5
    )

    min_value = min(y_test.min(), predictions.min())
    max_value = max(y_test.max(), predictions.max())

    plt.plot(
        [min_value, max_value],
        [min_value, max_value],
        linestyle="--"
    )

    plt.xlabel("Actual Power (kW)")
    plt.ylabel("Predicted Power (kW)")
    plt.title("Actual vs Predicted Solar Power")

    plt.tight_layout()
    plt.savefig(PLOT_DIR / "actual_vs_predicted.png", dpi=150)
    plt.close()

    # 2. Prediction error distribution
    errors = y_test - predictions

    plt.figure(figsize=(8, 5))

    sns.histplot(
        errors,
        bins=30,
        kde=True
    )

    plt.axvline(0, linestyle="--")

    plt.xlabel("Prediction Error (kW)")
    plt.ylabel("Frequency")
    plt.title("Solar Power Prediction Error Distribution")

    plt.tight_layout()
    plt.savefig(
        PLOT_DIR / "prediction_error_distribution.png",
        dpi=150
    )
    plt.close()

    # 3. Actual and predicted power over time
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

    plt.xlabel("Test Record")
    plt.ylabel("Power (kW)")
    plt.title("Actual vs Predicted Power Over Time")
    plt.legend()

    plt.tight_layout()
    plt.savefig(
        PLOT_DIR / "prediction_over_time.png",
        dpi=150
    )
    plt.close()

    # 4. Feature importance
    fitted_model = model.named_steps["model"]

    if hasattr(fitted_model, "feature_importances_"):

        importance = pd.DataFrame({
            "Feature": features,
            "Importance": fitted_model.feature_importances_
        }).sort_values(
            by="Importance",
            ascending=False
        )

        print("\nFEATURE IMPORTANCE")
        print("------------------")
        print(importance.to_string(index=False))

        plt.figure(figsize=(8, 5))

        sns.barplot(
            data=importance,
            x="Importance",
            y="Feature"
        )

        plt.title("Solar Model Feature Importance")
        plt.tight_layout()

        plt.savefig(
            PLOT_DIR / "feature_importance.png",
            dpi=150
        )
        plt.close()

    print("\nEvaluation graphs saved in:")
    print(PLOT_DIR)

    print("\nPrediction results saved in:")
    print(DATA_DIR / "real_model_predictions.csv")

    print("\nModel evaluation completed successfully!")


if __name__ == "__main__":
    main()
