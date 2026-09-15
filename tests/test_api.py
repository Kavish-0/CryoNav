"""
FastAPI Backend Endpoint Contract Tests.
Tests all public API routes to guarantee contract compliance for the frontend.
"""
import unittest
import sys
from pathlib import Path

# Ensure repo root is on sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from fastapi.testclient import TestClient
from src.api.main import app


class TestCryoNavAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Using context manager to trigger FastAPI startup event
        cls.client_context = TestClient(app)
        cls.client = cls.client_context.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client_context.__exit__(None, None, None)

    def test_get_config(self):
        res = self.client.get("/config")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("region", data)
        self.assertIn("stations", data)
        self.assertIn("origins", data)
        self.assertIn("ship", data)
        self.assertIn("routing_weights", data)
        self.assertIn("bharati", data["stations"])
        self.assertIn("maitri", data["stations"])
        self.assertIn("cape_town", data["origins"])

    def test_get_demo_dates(self):
        res = self.client.get("/demo-dates")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("demo_dates", data)
        self.assertIsInstance(data["demo_dates"], list)
        self.assertTrue(len(data["demo_dates"]) > 0)

    def test_get_grid(self):
        res = self.client.get("/grid")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("shape", data)
        self.assertIn("lat", data)
        self.assertIn("lon", data)
        self.assertIn("land_mask", data)
        self.assertEqual(data["cell_size_km"], 25)
        self.assertEqual(len(data["shape"]), 2)

    def test_get_forecast(self):
        # Test forecast retrieval
        res = self.client.get("/forecast?date=2023-01-13&lead=7")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("sic", data)
        self.assertIn("source", data)
        self.assertIn("stats", data)
        self.assertEqual(data["stats"]["lead_day"], 7)
        self.assertIn("mean_sic", data["stats"])
        self.assertIn("ice_area_km2", data["stats"])

    def test_get_observed(self):
        res = self.client.get("/observed?date=2023-01-20")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("sic", data)
        self.assertIn("stats", data)
        self.assertIn("ice_extent_km2", data["stats"])

    def test_get_bergs(self):
        res = self.client.get("/bergs?date=2023-01-13&horizon=7&limit=4")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("bergs", data)
        self.assertIn("source", data)
        self.assertIn("n_ensemble", data)
        self.assertIsInstance(data["bergs"], list)
        if data["bergs"]:
            first = data["bergs"][0]
            self.assertIn("berg_id", first)
            self.assertIn("mean_track", first)
            self.assertIn("ensemble", first)

    def test_post_route(self):
        payload = {
            "origin": "cape_town",
            "destination": "bharati",
            "depart_date": "2023-01-13",
            "w_time": 1.0,
            "w_fuel": 0.5,
            "w_risk": 2.0,
            "berg_limit": 4,
        }
        res = self.client.post("/route", json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("routes", data)
        self.assertIn("comparison", data)
        self.assertIn("origin", data)
        self.assertIn("destination", data)

        # Check alternative profiles exist in routes
        routes = data["routes"]
        expected_profiles = ["great_circle", "min_ice", "min_time", "balanced", "persistence_route"]
        for profile in expected_profiles:
            self.assertIn(profile, routes)
            self.assertIn("success", routes[profile])
            if routes[profile]["success"]:
                self.assertIn("path_latlon", routes[profile])
                self.assertIn("distance_nm", routes[profile])
                self.assertIn("time_h", routes[profile])

    def test_get_metrics(self):
        res = self.client.get("/metrics")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("status", data)
        # "baselines" is only populated once results/backtest_summary.csv exists,
        # which a fresh clone does not have (results/ is gitignored).
        if "baselines" in data:
            self.assertIsInstance(data["baselines"], list)


if __name__ == "__main__":
    unittest.main()
