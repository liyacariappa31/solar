
"""Exploratory Data Analysis for real solar data."""

from pathlib import Path

import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns


ROOT = Path(__file__).resolve().parent
DATA_FILE = ROOT / "data" / "real_solar_training_data.csv"
OUTPUT_DIR = ROOT / "data" / "eda_plots"

OUTPUT_DIR.mkdir(exist_ok=True)

# Load dataset
df = pd.read_csv(DATA_FILE)
df["DATE_TIME"] = pd.to_datetime(df["DATE_TIME"])

# Calculate daily energy
daily = (
    df.groupby(df["DATE_TIME"].dt.date)["energy_kwh_15min"]
    .sum()
)

sns.set_theme(style="whitegrid")


# 1. Generation distribution
plt.figure(figsize=(9, 5))
sns.histplot(df["ac_power_kw"], bins=40, kde=True)
plt.title("Solar Power Generation Distribution")
plt.xlabel("AC Power (kW)")
plt.ylabel("Frequency")
plt.tight_layout()
plt.savefig(OUTPUT_DIR / "generation_distribution.png")
plt.close()


# 2. Irradiation vs generation
plt.figure(figsize=(9, 5))
sns.scatterplot(
    data=df,
    x="irradiation",
    y="ac_power_kw",
    alpha=0.5
)
plt.title("Irradiation vs Solar Power Generation")
plt.xlabel("Irradiation")
plt.ylabel("AC Power (kW)")
plt.tight_layout()
plt.savefig(OUTPUT_DIR / "irradiation_vs_generation.png")
plt.close()


# 3. Temperature vs generation
plt.figure(figsize=(9, 5))
sns.scatterplot(
    data=df,
    x="module_temperature_c",
    y="ac_power_kw",
    alpha=0.5
)
plt.title("Module Temperature vs Solar Power Generation")
plt.xlabel("Module Temperature (°C)")
plt.ylabel("AC Power (kW)")
plt.tight_layout()
plt.savefig(OUTPUT_DIR / "temperature_vs_generation.png")
plt.close()


# 4. Daily energy generation
plt.figure(figsize=(12, 5))
daily.plot(kind="line", marker="o")
plt.title("Daily Solar Energy Generation")
plt.xlabel("Date")
plt.ylabel("Energy Generation (kWh)")
plt.xticks(rotation=45)
plt.tight_layout()
plt.savefig(OUTPUT_DIR / "daily_generation.png")
plt.close()


# 5. Correlation heatmap
numeric_columns = [
    "ac_power_kw",
    "dc_power_kw",
    "ambient_temperature_c",
    "module_temperature_c",
    "irradiation",
    "energy_kwh_15min"
]

plt.figure(figsize=(10, 7))
sns.heatmap(
    df[numeric_columns].corr(),
    annot=True,
    cmap="coolwarm",
    fmt=".2f"
)
plt.title("Solar Dataset Correlation Heatmap")
plt.tight_layout()
plt.savefig(OUTPUT_DIR / "correlation_heatmap.png")
plt.close()


print("\nEDA completed successfully!")
print("Dataset rows:", len(df))
print("Daily energy records:", len(daily))
print("EDA graphs saved in:", OUTPUT_DIR)

print("\nDaily generation statistics:")
print(daily.describe())
