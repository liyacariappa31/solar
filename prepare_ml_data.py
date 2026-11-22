
"""Prepare chronological train and test datasets for SolarWise."""

from pathlib import Path

import pandas as pd
import numpy as np


# Project paths
ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"

INPUT_FILE = DATA_DIR / "real_solar_training_data.csv"

TRAIN_FILE = DATA_DIR / "solar_ml_train.csv"
TEST_FILE = DATA_DIR / "solar_ml_test.csv"


def prepare_ml_data():

    print("\nLoading cleaned real-world dataset...")

    df = pd.read_csv(INPUT_FILE)
    df["DATE_TIME"] = pd.to_datetime(df["DATE_TIME"])

    # Sort chronologically
    df = df.sort_values("DATE_TIME").reset_index(drop=True)

    # Select prediction features
    # Do not include AC_POWER, DC_POWER, daily yield,
    # total yield, or calculated energy as input features.
    df["hour_sin"] = np.sin(
        2 * np.pi * df["hour"] / 24
    )

    df["hour_cos"] = np.cos(
        2 * np.pi * df["hour"] / 24
    )

    feature_columns = [
        "irradiation",
        "ambient_temperature_c",
        "module_temperature_c",
        "hour_sin",
        "hour_cos"
    ]

    target_column = "ac_power_kw"

    # Keep only required columns
    ml_data = df[
        ["DATE_TIME"] + feature_columns + [target_column]
    ].copy()

    # Handle missing or infinite values
    ml_data = ml_data.replace(
        [np.inf, -np.inf],
        np.nan
    )

    ml_data = ml_data.dropna()

    # Chronological 80/20 split
    split_index = int(len(ml_data) * 0.80)

    train_data = ml_data.iloc[:split_index].copy()
    test_data = ml_data.iloc[split_index:].copy()

    # Save datasets
    train_data.to_csv(TRAIN_FILE, index=False)
    test_data.to_csv(TEST_FILE, index=False)

    print("\nML DATA PREPARATION COMPLETE")
    print("----------------------------")

    print("Total records:", len(ml_data))
    print("Training records:", len(train_data))
    print("Testing records:", len(test_data))

    print("\nTraining date range:")
    print(train_data["DATE_TIME"].min())
    print("to", train_data["DATE_TIME"].max())

    print("\nTesting date range:")
    print(test_data["DATE_TIME"].min())
    print("to", test_data["DATE_TIME"].max())

    print("\nInput features:")
    for feature in feature_columns:
        print("-", feature)

    print("\nPrediction target:", target_column)

    print("\nTraining dataset saved:", TRAIN_FILE)
    print("Testing dataset saved:", TEST_FILE)

    print("\nTraining data preview:")
    print(train_data.head())

    print("\nTesting data preview:")
    print(test_data.head())


if __name__ == "__main__":
    prepare_ml_data()
