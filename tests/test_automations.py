import unittest

from flask import Flask

from app import db
from app.advisor import format_iot_actions_for_zone
from app.main import main_bp
from app.models import AutomationAudit, Farm, Notification, User, Zone


class AutomationEndpointTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            TESTING=True,
            SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
            SQLALCHEMY_TRACK_MODIFICATIONS=False,
            SECRET_KEY="test-secret",
            AUTOMATION_API_KEY="super-secret-key",
        )
        db.init_app(self.app)
        self.app.register_blueprint(main_bp)

        with self.app.app_context():
            db.create_all()
            self.zone = Zone(
                name="Test Zone",
                district="Test District",
                latitude=-25.0,
                longitude=30.0,
                current_severity_band="critical",
            )
            db.session.add(self.zone)
            db.session.flush()

            self.user = User(
                name="Test",
                surname="Farmer",
                email="farmer@example.com",
                location="Test Zone",
            )
            self.user.set_password("pw")
            db.session.add(self.user)
            db.session.flush()

            self.farm = Farm(owner_id=self.user.id, zone_id=self.zone.id, name="Critical Farm")
            db.session.add(self.farm)
            db.session.commit()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def test_format_iot_actions_for_zone_returns_structured_actions(self):
        actions = format_iot_actions_for_zone(self.zone, ["Open emergency pump", "Throttle valve"])
        self.assertTrue(actions)
        self.assertEqual(actions[0]["severity"], "critical")
        self.assertIn("device", actions[0])
        self.assertIn("action", actions[0])

    def test_automations_endpoint_requires_api_key_and_logs_event(self):
        client = self.app.test_client()

        response = client.post(
            "/api/automations",
            json={
                "zone_id": self.zone.id,
                "severity": "critical",
                "trigger_name": "drought_critical",
                "actions": [
                    {"device": "water_valve", "action": "throttle", "value": 35},
                    {"device": "solar_pump", "action": "start", "value": "emergency"},
                ],
            },
            headers={"X-API-Key": "super-secret-key"},
        )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["status"], "accepted")
        self.assertEqual(payload["notification_count"], 1)

        with self.app.app_context():
            self.assertEqual(AutomationAudit.query.count(), 1)
            self.assertEqual(Notification.query.filter_by(level="danger").count(), 1)

    def test_automations_endpoint_rejects_invalid_key(self):
        client = self.app.test_client()
        response = client.post(
            "/api/automations",
            json={"zone_id": self.zone.id, "severity": "critical"},
            headers={"X-API-Key": "wrong-key"},
        )
        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
