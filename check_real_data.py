
import pandas as pd
from pathlib import Path

file_path = Path("data/real_solar_training_data.csv")

df = pd.read_csv(file_path)

print("\nDATASET SHAPE:")
print(df.shape)

print("\nCOLUMN NAMES:")
print(df.columns.tolist())

print("\nMISSING VALUES:")
print(df.isnull().sum())

print("\nGENERATION STATISTICS:")
print(df["ac_power_kw"].describe())

print("\nIRRADIATION STATISTICS:")
print(df["irradiation"].describe())

print("\nZERO GENERATION ROWS:")
print((df["ac_power_kw"] == 0).sum())

print("\nPOSITIVE GENERATION ROWS:")
print((df["ac_power_kw"] > 0).sum())

print("\nDUPLICATE TIMESTAMPS:")
print(df["DATE_TIME"].duplicated().sum())

print("\nSAMPLE DAYTIME RECORDS:")
print(
    df[df["irradiation"] > 0][
        ["DATE_TIME", "irradiation", "ambient_temperature_c",
         "module_temperature_c", "ac_power_kw"]
    ].head(10)
)
