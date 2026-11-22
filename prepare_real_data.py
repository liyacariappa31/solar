
"""Prepare matched real-world solar generation and weather data."""

from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"

GENERATION_FILE = (
    DATA_DIR / "real_solar_data.csv"
    / "Original Kaggle Source Files"
    / "Plant_1_Generation_Data.csv"
)

WEATHER_FILE = DATA_DIR / "Plant_1_Weather_Sensor_Data.csv"
OUTPUT_FILE = DATA_DIR / "real_solar_training_data.csv"


def prepare_dataset():

    print("\nLoading original datasets...")

    generation = pd.read_csv(GENERATION_FILE)
    weather = pd.read_csv(WEATHER_FILE)

    generation["DATE_TIME"] = pd.to_datetime(
        generation["DATE_TIME"],
        format="%d-%m-%Y %H:%M",
        errors="coerce"
    )

    weather["DATE_TIME"] = pd.to_datetime(
        weather["DATE_TIME"],
        format="%Y-%m-%d %H:%M:%S",
        errors="coerce"
    )

    generation = generation.dropna(subset=["DATE_TIME"])
    weather = weather.dropna(subset=["DATE_TIME"])

    # AC_POWER and DC_POWER are already in kW.
    # Aggregate the readings from all inverters.
    generation_agg = (
        generation.groupby("DATE_TIME", as_index=False)
        .agg(
            ac_power_kw=("AC_POWER", "sum"),
            dc_power_kw=("DC_POWER", "sum"),
            daily_yield=("DAILY_YIELD", "sum"),
            total_yield=("TOTAL_YIELD", "sum")
        )
    )

    # Aggregate weather readings if duplicate timestamps exist.
    weather_clean = (
        weather.groupby("DATE_TIME", as_index=False)
        .agg(
            ambient_temperature_c=("AMBIENT_TEMPERATURE", "mean"),
            module_temperature_c=("MODULE_TEMPERATURE", "mean"),
            irradiation=("IRRADIATION", "mean")
        )
    )

    # Match generation and weather timestamps.
    merged = pd.merge(
        generation_agg,
        weather_clean,
        on="DATE_TIME",
        how="inner"
    )

    merged = (
        merged.sort_values("DATE_TIME")
        .reset_index(drop=True)
    )

    # AC power is kW.
    # Energy = Power x Time (0.25 hours).
    merged["energy_kwh_15min"] = (
        merged["ac_power_kw"] * 0.25
    )

    # Time features
    merged["hour"] = merged["DATE_TIME"].dt.hour
    merged["day"] = merged["DATE_TIME"].dt.day
    merged["month"] = merged["DATE_TIME"].dt.month

    # Quality checks
    print("\nDATASET PREPARATION RESULTS")
    print("----------------------------")
    print("Merged rows:", len(merged))
    print("Duplicate timestamps:", merged["DATE_TIME"].duplicated().sum())

    print("\nMissing values:")
    print(merged.isnull().sum())

    print("\nAC power statistics (kW):")
    print(merged["ac_power_kw"].describe())

    daily_energy = (
        merged.groupby(merged["DATE_TIME"].dt.date)
        ["energy_kwh_15min"]
        .sum()
    )

    print("\nDaily energy statistics (kWh):")
    print(daily_energy.describe())

    merged.to_csv(OUTPUT_FILE, index=False)

    print("\nCorrected dataset saved:")
    print(OUTPUT_FILE)

    print("\nFirst five rows:")
    print(merged.head())

    print("\nDataset preparation completed!")


if __name__ == "__main__":
    prepare_dataset()
