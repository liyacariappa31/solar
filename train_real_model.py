
"""Train and compare ML models using real solar data."""

from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from sklearn.ensemble import RandomForestRegressor, GradientBoostingRegressor
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.pipeline import Pipeline
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler


# Project paths
ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
MODEL_DIR = ROOT / "models"

TRAIN_FILE = DATA_DIR / "solar_ml_train.csv"
TEST_FILE = DATA_DIR / "solar_ml_test.csv"

MODEL_DIR.mkdir(exist_ok=True)

BEST_MODEL_FILE = MODEL_DIR / "solar_real_model.joblib"
RESULTS_FILE = DATA_DIR / "model_comparison.csv"


# Input features and prediction target
FEATURES = [
    "irradiation",
    "ambient_temperature_c",
    "module_temperature_c",
    "hour_sin",
    "hour_cos"
]

TARGET = "ac_power_kw"


def main():

    print("\nLoading training and testing datasets...")

    train = pd.read_csv(TRAIN_FILE)
    test = pd.read_csv(TEST_FILE)

    X_train = train[FEATURES]
    y_train = train[TARGET]

    X_test = test[FEATURES]
    y_test = test[TARGET]

    print("Training records:", len(train))
    print("Testing records:", len(test))

    # Define models
    models = {
        "Linear Regression": Pipeline([
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
            ("model", LinearRegression())
        ]),

        "Random Forest": Pipeline([
            ("imputer", SimpleImputer(strategy="median")),
            ("model", RandomForestRegressor(
                n_estimators=200,
                max_depth=12,
                min_samples_leaf=2,
                random_state=42,
                n_jobs=-1
            ))
        ]),

        "Gradient Boosting": Pipeline([
            ("imputer", SimpleImputer(strategy="median")),
            ("model", GradientBoostingRegressor(
                n_estimators=150,
                learning_rate=0.05,
                max_depth=3,
                random_state=42
            ))
        ])
    }

    results = []
    trained_models = {}

    print("\nTraining and evaluating models...")

    for name, model in models.items():

        print(f"\nTraining {name}...")

        model.fit(X_train, y_train)

        predictions = model.predict(X_test)

        mae = mean_absolute_error(y_test, predictions)

        rmse = np.sqrt(
            mean_squared_error(y_test, predictions)
        )

        r2 = r2_score(y_test, predictions)

        results.append({
            "Model": name,
            "MAE_kW": mae,
            "RMSE_kW": rmse,
            "R2_Score": r2
        })

        trained_models[name] = model

        print("MAE:", round(mae, 4))
        print("RMSE:", round(rmse, 4))
        print("R2 Score:", round(r2, 4))

    # Compare models
    results_df = pd.DataFrame(results)

    results_df = results_df.sort_values(
        by="MAE_kW",
        ascending=True
    ).reset_index(drop=True)

    results_df.to_csv(RESULTS_FILE, index=False)

    # Select the model with lowest MAE
    best_name = results_df.iloc[0]["Model"]
    best_model = trained_models[best_name]

    # Save model and metadata
    model_package = {
        "model": best_model,
        "features": FEATURES,
        "target": TARGET,
        "model_name": best_name,
        "target_unit": "kW"
    }

    joblib.dump(model_package, BEST_MODEL_FILE)

    # Display results
    print("\nMODEL COMPARISON")
    print("----------------")
    print(results_df.to_string(index=False))

    print("\nBEST MODEL:", best_name)
    print("Saved model:", BEST_MODEL_FILE)
    print("Comparison saved:", RESULTS_FILE)

    # Example predictions
    example_predictions = best_model.predict(X_test.head(10))

    comparison = pd.DataFrame({
        "Actual_kW": y_test.head(10).values,
        "Predicted_kW": example_predictions
    })

    print("\nSAMPLE PREDICTIONS")
    print("-----------------")
    print(comparison.round(3).to_string(index=False))

    print("\nReal-world model training completed!")


if __name__ == "__main__":
    main()
