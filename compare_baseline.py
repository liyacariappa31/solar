
"""Compare SolarWise ML models against an irradiation-only baseline."""

from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score


# Project paths
ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
MODEL_DIR = ROOT / "models"

TRAIN_FILE = DATA_DIR / "solar_ml_train.csv"
TEST_FILE = DATA_DIR / "solar_ml_test.csv"

MODEL_FILE = MODEL_DIR / "solar_real_model.joblib"
RESULT_FILE = DATA_DIR / "baseline_comparison.csv"


def calculate_metrics(name, actual, predicted):

    mae = mean_absolute_error(actual, predicted)

    rmse = np.sqrt(
        mean_squared_error(actual, predicted)
    )

    r2 = r2_score(actual, predicted)

    return {
        "Model": name,
        "MAE_kW": mae,
        "RMSE_kW": rmse,
        "R2_Score": r2
    }


def main():

    print("\nLoading solar datasets...")

    train = pd.read_csv(TRAIN_FILE)
    test = pd.read_csv(TEST_FILE)

    package = joblib.load(MODEL_FILE)

    # Actual values
    y_train = train["ac_power_kw"]
    y_test = test["ac_power_kw"]

    results = []

    # 1. Irradiation-only baseline
    print("\nTraining irradiation-only baseline...")

    baseline = LinearRegression()

    baseline.fit(
        train[["irradiation"]],
        y_train
    )

    baseline_predictions = baseline.predict(
        test[["irradiation"]]
    )

    results.append(
        calculate_metrics(
            "Irradiation-only Baseline",
            y_test,
            baseline_predictions
        )
    )

    # 2. Random Forest model
    print("Evaluating Random Forest...")

    best_model = package["model"]

    rf_predictions = best_model.predict(
        test[package["features"]]
    )

    results.append(
        calculate_metrics(
            "Random Forest",
            y_test,
            rf_predictions
        )
    )

    # 3. Gradient Boosting model
    # Load the training implementation's models again
    # using the same settings as the original comparison.
    from sklearn.ensemble import GradientBoostingRegressor
    from sklearn.impute import SimpleImputer
    from sklearn.pipeline import Pipeline

    print("Training Gradient Boosting for comparison...")

    features = package["features"]

    gb_model = Pipeline([
        ("imputer", SimpleImputer(strategy="median")),
        ("model", GradientBoostingRegressor(
            n_estimators=150,
            learning_rate=0.05,
            max_depth=3,
            random_state=42
        ))
    ])

    gb_model.fit(
        train[features],
        y_train
    )

    gb_predictions = gb_model.predict(
        test[features]
    )

    results.append(
        calculate_metrics(
            "Gradient Boosting",
            y_test,
            gb_predictions
        )
    )

    # Compare results
    results_df = pd.DataFrame(results)

    results_df = results_df.sort_values(
        "MAE_kW"
    ).reset_index(drop=True)

    results_df.to_csv(
        RESULT_FILE,
        index=False
    )

    print("\nBASELINE VS ML MODEL COMPARISON")
    print("--------------------------------")
    print(results_df.to_string(index=False))

    print("\nRESULTS INTERPRETATION")

    baseline_mae = results_df.loc[
        results_df["Model"] == "Irradiation-only Baseline",
        "MAE_kW"
    ].iloc[0]

    rf_mae = results_df.loc[
        results_df["Model"] == "Random Forest",
        "MAE_kW"
    ].iloc[0]

    if rf_mae < baseline_mae:
        improvement = (
            (baseline_mae - rf_mae) / baseline_mae
        ) * 100

        print(
            f"Random Forest reduces MAE by "
            f"{improvement:.2f}% compared with the baseline."
        )
    else:
        print(
            "Random Forest does not outperform "
            "the irradiation-only baseline on MAE."
        )

    print("\nComparison saved to:")
    print(RESULT_FILE)

    print("\nBaseline comparison completed!")


if __name__ == "__main__":
    main()
