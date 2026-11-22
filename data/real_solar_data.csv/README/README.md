# Curated Solar Weather and PV AC Power Output Dataset for Explainable Solar Power Forecasting

## Purpose

This repository-style dataset package documents the preparation of `Solar_Weather_Data_Processed.csv`, a model-ready dataset used for machine learning-based solar power forecasting with explainability and uncertainty estimation.

The dataset should be described as a **curated and processed benchmark dataset**, not as a single raw field-measured dataset collected from one site. It was prepared by combining a photovoltaic generation dataset and a solar-weather dataset originally obtained from Kaggle.

## Source files

| Source file | Rows | Columns | Role in final dataset |
|---|---:|---:|---|
| `Plant_1_Generation_Data.csv` | 68778 | 7 | Source of PV AC power output (`AC_POWER`) |
| `SolarPrediction.csv` | 32686 | 11 | Source of weather/solar-radiation variables |
| `Solar_Weather_Data_Processed.csv` | 2777 | 12 | Final processed dataset used for ML modeling |

## Kaggle source links provided by the authors

1. `https://www.kaggle.com/code/pythonafroz/solar-power-generation-forecast/input`
2. `https://www.kaggle.com/code/volkanarslan97/solar-prediction/input`

If the original Kaggle dataset pages are available separately from the notebook input pages, cite the dataset pages as primary data sources and keep the notebook input pages as provenance links.

## Final processed dataset summary

| Item | Value |
|---|---|
| Final file name | `Solar_Weather_Data_Processed.csv` |
| Number of samples | 2777 hourly records |
| Number of columns | 12 |
| Date range | 2016-09-01 10:00:00 to 2016-12-26 02:00:00 |
| Missing values in final CSV | 0 |
| Duplicate rows in final CSV | 0 |
| Target variable | `AC Output` |

## Final columns

`Timestamp`, `GHI`, `Temperature`, `Relative Humidity`, `Wind Speed`, `Wind Direction`, `Hour`, `Day`, `Month`, `SZ Angle`, `SA Angle`, and `AC Output`.

Some columns in the existing CSV contain trailing spaces. For analysis code, it is recommended to strip whitespace from column names using:

```python
df.columns = df.columns.str.strip()
```

## Processing overview

The preprocessing pipeline performs the following operations:

1. Load the solar-weather file `SolarPrediction.csv`.
2. Convert `UNIXTime` into a timestamp.
3. Keep numeric weather variables and resample them to hourly means.
4. Rename variables into model-ready feature names.
5. Convert temperature from degrees Fahrenheit to degrees Celsius.
6. Convert wind speed from miles per hour to meters per second.
7. Extract `Hour`, `Day`, and `Month` from the timestamp.
8. Load `Plant_1_Generation_Data.csv`.
9. Convert `DATE_TIME` into datetime format.
10. Resample `AC_POWER` to hourly mean values.
11. Integrate the PV AC output profile with the hourly weather feature table.
12. Calculate solar zenith and solar azimuth angles from timestamp and location assumptions.
13. Remove missing rows and export the final model-ready CSV.

## Important provenance note

The source PV generation and solar-weather files are from different Kaggle sources and have different native time ranges. Therefore, the final file should be presented as a curated benchmark dataset prepared for forecasting experiments. In the manuscript, avoid claiming that all variables were collected simultaneously from the same physical PV plant unless that can be independently verified from the original source documentation.

A safe manuscript description is:

> The final dataset was prepared by integrating publicly available PV generation and solar-weather datasets obtained from Kaggle. The processed dataset was deposited in Mendeley Data to support reproducibility of the model training, evaluation, explainability, and uncertainty-estimation experiments.

## Recommended citation after Mendeley publication

Replace the DOI placeholder after publication:

Alif, S. A. Z. (2026). Curated Solar Weather and PV AC Power Output Dataset for Explainable Solar Power Forecasting. Mendeley Data, V1. DOI: `10.17632/kpx4yd6z3.1`

## File integrity hashes

SHA-256 hashes from the local files used to prepare this package:

| File | SHA-256 |
|---|---|
| `Plant_1_Generation_Data.csv` | `882f75f1c295946633617646cc92343ddb6fb821a2546c82f7e5cc737a13624e` |
| `SolarPrediction.csv` | `d6033248e8292e2feae20ebb7b26232542886998097161bbcc5fbb103c9a32ef` |
| `Solar_Weather_Data_Processed.csv` | `89321b3c0daa47ef8ee5ff90218c2b5f72899fb8323a374bfac839c83ac0eeb5` |
