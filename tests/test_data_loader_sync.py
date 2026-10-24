import json
import os
import tempfile
import unittest

from flask import Flask

from app import db
from app.ml import data_loader
from app.models import Zone


class DataLoaderSyncTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True,
            SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
            SQLALCHEMY_TRACK_MODIFICATIONS=False,
            SECRET_KEY="test-secret",
        )
        db.init_app(self.app)

        with self.app.app_context():
            db.create_all()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def test_load_rich_dataset_keeps_district_in_sync_with_json(self):
        payload = {
            "metadata": {"forecast_horizon_weeks": 4},
            "farms": [
                {
                    "farm_id": "F101",
                    "name": "Demo Farm",
                    "area": "Maphumulo, KwaZulu-Natal",
                    "province": "KwaZulu-Natal",
                    "district": "uMzinyathi",
                    "lat": -28.7,
                    "lon": 30.4,
                    "herd_size": 50,
                    "primary_water_source": "Borehole",
                    "dashboard_metrics": {
                        "current_severity_band": "warning",
                        "current_drought_stress_index": 52.3,
                        "estimated_livestock_at_risk_now": 12,
                        "water_point_level_pct_now": 41.2,
                        "feed_days_remaining_now": 20.5,
                        "trend": "worsening",
                    },
                    "scenarios": {
                        "worst_case": [
                            {
                                "week_start": "2026-10-01",
                                "ndvi": 0.3,
                                "soil_moisture_pct": 25,
                                "rainfall_mm": 1,
                                "rainfall_deficit_pct": 34,
                                "temp_anomaly_c": 1.2,
                                "drought_stress_index": 55,
                                "water_point_level_pct": 41,
                                "grazing_capacity_pct": 52,
                                "feed_days_remaining": 20,
                                "estimated_livestock_at_risk": 12,
                                "estimated_financial_impact_zar": 200000,
                            }
                        ]
                    },
                    "alerts": [],
                    "relocation_recommendations": [],
                }
            ],
        }

        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
            json.dump(payload, fh)
            temp_path = fh.name

        try:
            with self.app.app_context():
                result = data_loader.load_rich_dataset(temp_path)
                zone = Zone.query.filter_by(name="Maphumulo, KwaZulu-Natal").first()
                self.assertIsNotNone(zone)
                self.assertEqual(zone.province, "KwaZulu-Natal")
                self.assertEqual(zone.district, "uMzinyathi")
                self.assertGreater(result["farms_loaded"], 0)
        finally:
            os.unlink(temp_path)


if __name__ == "__main__":
    unittest.main()
