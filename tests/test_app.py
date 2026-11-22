import tempfile
import unittest
import json
from pathlib import Path

import numpy as np

import app as solar_app


class SolarWiseApiTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        solar_app.app.config.update(TESTING=True, DATABASE=str(Path(self.temp_dir.name) / "test.db"))
        solar_app.init_db()
        self.client = solar_app.app.test_client()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_prediction_returns_model_estimate_and_saves_history(self):
        response = self.client.post(
            "/api/predict",
            json={
                "sunlight_intensity": 760,
                "temperature": 27,
                "panel_capacity": 6.5,
                "cloud_coverage": 18,
            },
        )
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertGreater(body["generation_kwh"], 0)
        self.assertEqual(len(body["hourly"]), 9)
        self.assertTrue(body["advice"])
        self.assertTrue(body["scheduler"])
        self.assertEqual(body["weather_impact"][0]["generation_kwh"], body["generation_kwh"])
        self.assertEqual(body["weather_impact"][0]["change_kwh"], 0)
        self.assertEqual(len(self.client.get("/api/history").get_json()["forecasts"]), 1)

    def test_batched_predictions_match_random_forest_means_and_confidence(self):
        inputs_batch = [
            solar_app.DEFAULT_INPUTS,
            {**solar_app.DEFAULT_INPUTS, "cloud_coverage": 0.0},
            {**solar_app.DEFAULT_INPUTS, "temperature": 25.0},
        ]
        results = solar_app.predict_yields(inputs_batch)
        bundle = solar_app.get_model_bundle()
        values = np.array(
            [[inputs[key] for key in solar_app.FEATURES] for inputs in inputs_batch],
            dtype=float,
        )
        tree_predictions = np.array(
            [tree.predict(values) for tree in bundle["model"].estimators_]
        )
        for index, inputs in enumerate(inputs_batch):
            ceiling = solar_app.estimate_physical_yield(
                inputs["sunlight_intensity"],
                inputs["temperature"],
                inputs["panel_capacity"],
                inputs["cloud_coverage"],
            ) * 1.12
            expected_generation = round(
                min(ceiling, max(0.0, float(bundle["model"].predict(values)[index]))),
                2,
            )
            expected_confidence = round(float(np.std(tree_predictions[:, index])), 2)
            self.assertEqual(results[index], (expected_generation, expected_confidence))

    def test_what_if_prediction_does_not_change_saved_history(self):
        response = self.client.post("/api/predict", json={**solar_app.DEFAULT_INPUTS, "save_history": False})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get("/api/history").get_json()["forecasts"], [])

    def test_zero_sunlight_cannot_predict_solar_generation(self):
        response = self.client.post(
            "/api/predict",
            json={**solar_app.DEFAULT_INPUTS, "sunlight_intensity": 0, "save_history": False},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["generation_kwh"], 0)

    def test_out_of_range_input_is_rejected(self):
        response = self.client.post(
            "/api/predict",
            json={**solar_app.DEFAULT_INPUTS, "cloud_coverage": 101},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("cloud_coverage", response.get_json()["error"])

    def test_history_limit_is_validated(self):
        response = self.client.get("/api/history?limit=500")
        self.assertEqual(response.status_code, 400)

    def test_historical_simulation_uses_ordered_source_records_without_filling_gaps(self):
        dates_response = self.client.get("/api/simulation/dates")
        self.assertEqual(dates_response.status_code, 200)
        dates = dates_response.get_json()["dates"]
        self.assertEqual([item["date"] for item in dates], sorted(item["date"] for item in dates))

        day_response = self.client.get("/api/simulation/day?date=2020-05-15")
        self.assertEqual(day_response.status_code, 200)
        day = day_response.get_json()
        timestamps = [record["timestamp"] for record in day["records"]]
        self.assertEqual(timestamps, sorted(timestamps))
        observed_hours = sorted({timestamp[11:13] for timestamp in timestamps})
        self.assertEqual([hour["hour"][:2] for hour in day["hourly"]], observed_hours)
        self.assertNotIn("cloud_coverage", day["records"][0])
        self.assertNotIn("panel_capacity", day["records"][0])

    def test_historical_weather_values_are_read_from_the_matching_timestamp(self):
        response = self.client.get("/api/simulation/day?date=2020-06-02")
        self.assertEqual(response.status_code, 200)
        records = response.get_json()["records"]
        record = records[2]
        self.assertEqual(record["timestamp"], "2020-06-02 00:30:00")
        self.assertAlmostEqual(record["ambient_temperature_c"], 22.564072666666664)
        self.assertAlmostEqual(record["module_temperature_c"], 20.113968933333336)
        self.assertEqual(record["irradiation"], 0.0)
        self.assertEqual(record["ac_power_kw"], 0.0)

    def test_historical_day_reports_full_day_peak_from_source_records(self):
        response = self.client.get("/api/simulation/day?date=2020-06-02")
        self.assertEqual(response.status_code, 200)
        day = response.get_json()
        peak = max(day["records"], key=lambda record: record["ac_power_kw"])
        self.assertEqual(day["peak_timestamp"], peak["timestamp"])
        self.assertEqual(day["peak_ac_power_kw"], round(peak["ac_power_kw"], 2))
        self.assertEqual(len(day["hourly"]), 24)
        self.assertTrue(all("generation_kwh" in point for point in day["hourly"]))

    def test_historical_day_reports_approximate_plant_capacity_from_source_peak(self):
        response = self.client.get("/api/simulation/day?date=2020-06-02")
        self.assertEqual(response.status_code, 200)
        day = response.get_json()
        source_peak = max(
            record["ac_power_kw"] for record in solar_app.load_historical_records()
        )
        self.assertEqual(day["estimated_plant_capacity_kwp"], round(source_peak * 1.1, 2))

    def test_scheduler_snapshots_match_each_historical_record(self):
        response = self.client.get(
            "/api/simulation/day?date=2020-05-15&include_scheduler=1"
        )
        self.assertEqual(response.status_code, 200)
        day = response.get_json()
        snapshots = day["scheduler_snapshots"]
        self.assertEqual(len(snapshots), len(day["records"]))
        self.assertEqual(
            [snapshot["timestamp"] for snapshot in snapshots],
            [record["timestamp"] for record in day["records"]],
        )
        self.assertTrue(
            all(item["start"] == "Unavailable" for item in snapshots[0]["scheduler"])
        )

    def test_scheduler_does_not_recommend_zero_output_windows(self):
        schedule = solar_app.build_scheduler(
            [{"hour": "00:00", "generation_kwh": 0.0, "complete": True}],
            "2020-05-15",
        )
        self.assertTrue(all(item["start"] == "Unavailable" for item in schedule))

    def test_historical_scheduler_windows_change_with_observed_solar_profile(self):
        response = self.client.get(
            "/api/simulation/day?date=2020-05-15&include_scheduler=1"
        )
        day = response.get_json()
        snapshots = {
            snapshot["timestamp"]: snapshot["scheduler"]
            for snapshot in day["scheduler_snapshots"]
        }
        morning = snapshots["2020-05-15 08:00:00"][0]
        afternoon = snapshots["2020-05-15 14:00:00"][0]
        self.assertNotEqual(morning["start"], afternoon["start"])
        self.assertIn("Aggregate", afternoon["status"])

    def test_historical_simulation_rejects_invalid_and_unavailable_dates(self):
        invalid = self.client.get("/api/simulation/day?date=2020-5-15")
        unavailable = self.client.get("/api/simulation/day?date=2019-01-01")
        invalid_scheduler = self.client.get(
            "/api/simulation/scheduler?date=2020-05-15&through=2020-05-15%2000%3A30"
        )
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(unavailable.status_code, 404)
        self.assertEqual(invalid_scheduler.status_code, 400)

    def test_appliance_windows_only_use_observations_reached_in_playback(self):
        response = self.client.get(
            "/api/simulation/scheduler?date=2020-05-15&through=2020-05-15%2000%3A00%3A00"
        )
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body["through"], "2020-05-15 00:00:00")
        self.assertTrue(body["scheduler"])
        self.assertTrue(
            all(item["start"] == "Unavailable" for item in body["scheduler"])
        )

    def test_dataset_information_reports_source_coverage_and_model(self):
        response = self.client.get("/api/simulation/dataset-info")
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        history = body["historical_dataset"]
        self.assertEqual(history["record_count"], 3157)
        self.assertEqual(history["start_timestamp"], "2020-05-15 00:00:00")
        self.assertEqual(history["end_timestamp"], "2020-06-17 23:45:00")
        self.assertEqual(history["nominal_sampling_interval_minutes"], 15)
        self.assertGreater(history["non_nominal_gap_count"], 0)
        self.assertIn("not interpolated", history["energy_basis"])
        self.assertIn("not a residential meter", history["scope_note"])
        self.assertEqual(body["model"]["algorithm"], "RandomForestRegressor")
        self.assertEqual(body["model"]["version"], "1.0.0")
        self.assertEqual(body["model"]["training_record_count"], 1800)

    def test_monthly_report_uses_historical_energy_and_labels_estimates(self):
        response = self.client.get(
            "/api/simulation/monthly-report?rate=2.5&currency=USD"
        )
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body["currency"], "USD")
        self.assertEqual([month["month"] for month in body["months"]], ["2020-05", "2020-06"])
        may = body["months"][0]
        self.assertTrue(may["partial_month"])
        self.assertEqual(may["first_date"], "2020-05-15")
        self.assertAlmostEqual(
            may["estimated_savings"], may["generation_kwh"] * 2.5, delta=0.01
        )
        self.assertAlmostEqual(
            may["estimated_co2_avoided_kg"],
            may["generation_kwh"] * solar_app.GRID_CO2_KG_PER_KWH,
            delta=0.01,
        )
        self.assertIn("not a residential 6.5 kWp system", body["disclaimer"])

    def test_monthly_report_rejects_invalid_tariff(self):
        response = self.client.get("/api/simulation/monthly-report?rate=0")
        self.assertEqual(response.status_code, 400)

    def test_health_comparison_marks_manual_values_unverified(self):
        response = self.client.post(
            "/api/insights/health",
            json={
                **solar_app.DEFAULT_INPUTS,
                "reading_mode": "manual",
                "reported_generation_kwh": 0.1,
            },
        )
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertFalse(body["verified"])
        self.assertEqual(body["reading_mode"], "manual")
        self.assertLess(body["health_score"], 100)
        self.assertEqual(body["deviation_direction"], "below")
        self.assertEqual(body["expected_generation_kwh"], body["predicted_generation_kwh"])
        self.assertEqual(body["actual_generation_kwh"], body["comparison_generation_kwh"])
        self.assertTrue(body["possible_causes"])
        self.assertTrue(body["recommended_actions"])
        self.assertIn("not connected", body["disclaimer"])
        self.assertTrue(body["notification_required"])
        self.assertTrue(body["notification_message"])

    def test_health_demo_is_labeled_as_simulated(self):
        response = self.client.post(
            "/api/insights/health",
            json={**solar_app.DEFAULT_INPUTS, "reading_mode": "demo"},
        )
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body["reading_mode"], "demo")
        self.assertIn("Seven-day sample", body["reading_label"])
        self.assertFalse(body["verified"])
        self.assertEqual(body["consecutive_underperformance_days"], 7)
        self.assertTrue(body["panel_review_recommended"])
        self.assertIn("week", body["notification_message"].lower())
        self.assertIn("huge", body["notification_message"].lower())
        self.assertIn("replace", body["notification_message"].lower())
        self.assertEqual(body["demo_week"]["average_actual_kwh"], 2.74)
        self.assertEqual(body["demo_week"]["latest_actual_kwh"], 2.6)

    def test_three_consecutive_underperformance_days_trigger_panel_review(self):
        with solar_app.db_connection() as connection:
            for date_key in ("2026-11-20", "2026-11-21", "2026-11-22"):
                payload = {
                    "reading_mode": "manual",
                    "underperformance_detected": True,
                }
                connection.execute(
                    """
                    INSERT INTO insight_records (record_type, created_at, payload_json)
                    VALUES ('health', ?, ?)
                    """,
                    (f"{date_key}T12:00:00+00:00", json.dumps(payload)),
                )
        self.assertEqual(
            solar_app.consecutive_underperformance_days(),
            3,
        )

    def test_health_comparison_reports_direction_and_zero_deviation(self):
        prediction, _ = solar_app.predict_yield(solar_app.DEFAULT_INPUTS)
        response = self.client.post(
            "/api/insights/health",
            json={
                **solar_app.DEFAULT_INPUTS,
                "reading_mode": "manual",
                "reported_generation_kwh": prediction,
            },
        )
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body["deviation_direction"], "matches")
        self.assertEqual(body["signed_deviation_percent"], 0)
        self.assertEqual(body["deviation_percent"], 0)

    def test_cleaning_and_savings_estimates_are_persisted(self):
        cleaning = self.client.post(
            "/api/insights/cleaning",
            json={
                **solar_app.DEFAULT_INPUTS,
                "soiling_percent": 10,
                "days_since_cleaning": 100,
            },
        )
        self.assertEqual(cleaning.status_code, 200)
        self.assertGreater(cleaning.get_json()["estimated_recovery_kwh"], 0)

        savings = self.client.post(
            "/api/insights/savings",
            json={
                **solar_app.DEFAULT_INPUTS,
                "electricity_rate": 8.5,
                "currency": "INR",
            },
        )
        self.assertEqual(savings.status_code, 200)
        body = savings.get_json()
        self.assertEqual(body["currency_symbol"], "₹")
        self.assertAlmostEqual(body["yearly_savings"], body["daily_savings"] * 365)
        records = self.client.get("/api/insights/history").get_json()["records"]
        self.assertEqual([record["type"] for record in records], ["savings", "cleaning"])

    def test_weather_risk_scenario_and_invalid_types(self):
        response = self.client.post(
            "/api/insights/weather-risk",
            json={
                **solar_app.DEFAULT_INPUTS,
                "cloud_coverage": 63,
                "temperature": 40,
                "rain_scenario": "heavy",
            },
        )
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertIn(body["risk_level"], {"low", "moderate", "high"})
        self.assertIn("conditions entered", body["disclaimer"])
        self.assertTrue(any("High cloud warning" in alert for alert in body["alerts"]))
        self.assertTrue(any("Extreme-heat warning" in alert for alert in body["alerts"]))
        self.assertTrue(any("Heavy-rain scenario" in alert for alert in body["alerts"]))

        dashboard = self.client.get("/")
        insights = self.client.get("/insights")
        self.assertNotIn(b">Weather</span>", dashboard.data)
        self.assertNotIn(b">Weather</span>", insights.data)
        self.assertIn(b"scenario input", insights.data)

        invalid_rain = self.client.post(
            "/api/insights/weather-risk",
            json={**solar_app.DEFAULT_INPUTS, "rain_scenario": ["heavy"]},
        )
        invalid_currency = self.client.post(
            "/api/insights/savings",
            json={**solar_app.DEFAULT_INPUTS, "electricity_rate": 8, "currency": []},
        )
        self.assertEqual(invalid_rain.status_code, 400)
        self.assertEqual(invalid_currency.status_code, 400)

    def test_dashboard_sections_have_individual_pages(self):
        pages = {
            "/prediction": "Solar prediction",
            "/weather": "Weather impact",
            "/insights": "Solar health &amp; insights",
            "/simulator": "Solar simulator",
            "/advisor": "Efficiency advisor",
            "/scheduler": "Smart scheduler",
            "/history": "Forecast history",
        }
        for path, heading in pages.items():
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertIn(heading.encode(), response.data)

    def test_prediction_and_history_explain_their_data_sources(self):
        prediction = self.client.get("/prediction")
        history = self.client.get("/history")
        self.assertNotIn(b"What each input changes", prediction.data)
        self.assertIn(b"Load 7-day sample", prediction.data)
        self.assertIn(b"Monthly Solar Report", history.data)
        self.assertIn(b"DATASET &amp; MODEL", history.data)


if __name__ == "__main__":
    unittest.main()
