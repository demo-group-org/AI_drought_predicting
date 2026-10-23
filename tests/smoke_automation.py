import sys
import types

stub_train = types.ModuleType('app.ml.train_model')
stub_train.train_and_evaluate = lambda app: {'status': 'ok', 'data_source': 'stub', 'rows_used': 0}
sys.modules['app.ml.train_model'] = stub_train

from flask import Flask
from app import db
from app.main import main_bp
from app.models import Zone, Farm, User, Notification, AutomationAudit

app = Flask(__name__)
app.config.update(
    TESTING=True,
    SQLALCHEMY_DATABASE_URI='sqlite:///:memory:',
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    SECRET_KEY='test-secret',
    AUTOMATION_API_KEY='super-secret-key',
)
db.init_app(app)
app.register_blueprint(main_bp)

with app.app_context():
    db.create_all()
    zone = Zone(name='Test Zone', district='Test District', latitude=-25.0, longitude=30.0, current_severity_band='critical')
    db.session.add(zone)
    db.session.flush()
    user = User(name='Test', surname='Farmer', email='farmer@example.com', location='Test Zone')
    user.set_password('pw')
    db.session.add(user)
    db.session.flush()
    farm = Farm(owner_id=user.id, zone_id=zone.id, name='Critical Farm')
    db.session.add(farm)
    db.session.commit()

    client = app.test_client()
    response = client.post(
        '/api/automations',
        json={
            'zone_id': zone.id,
            'severity': 'critical',
            'trigger_name': 'drought_critical',
            'actions': [
                {'device': 'water_valve', 'action': 'throttle', 'value': 35},
                {'device': 'solar_pump', 'action': 'start', 'value': 'emergency'},
            ],
        },
        headers={'X-API-Key': 'super-secret-key'},
    )

    print('status_code=' + str(response.status_code))
    print('json=' + str(response.get_json()))
    print('audit_count=' + str(AutomationAudit.query.count()))
    print('notification_count=' + str(Notification.query.filter_by(level='danger').count()))
