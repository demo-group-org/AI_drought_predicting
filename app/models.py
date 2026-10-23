from datetime import datetime, date
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

from app import db


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    surname = db.Column(db.String(80), nullable=False)
    email = db.Column(db.String(160), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    # Free-text location the farmer gave at signup (e.g. "Vryheid", "Msinga").
    # Used to pre-select their nearest zone and to show other farmers roughly
    # where each other are for the community/help-alert feature.
    location = db.Column(db.String(160))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    farms = db.relationship("Farm", backref="owner", lazy=True)
    help_alerts = db.relationship("HelpAlert", backref="requester", lazy=True)

    def set_password(self, raw_password):
        self.password_hash = generate_password_hash(raw_password)

    def check_password(self, raw_password):
        return check_password_hash(self.password_hash, raw_password)

    def __repr__(self):
        return f"<User {self.email}>"


class Zone(db.Model):
    """
    A named farming area/region on the map (e.g. Vryheid, Dundee, Msinga).
    Holds the latest drought readings, the current dashboard snapshot, and
    (if a rich dataset has been loaded) is linked to a full worst-case /
    best-case weekly forecast via ForecastReading, plus DroughtAlert and
    RelocationRecommendation rows.
    """
    __tablename__ = "zones"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), unique=True, nullable=False)
    district = db.Column(db.String(120))          # kept for the simple/legacy dataset format
    province = db.Column(db.String(120))           # used by the rich dataset format
    latitude = db.Column(db.Float, nullable=False)
    longitude = db.Column(db.Float, nullable=False)

    source_farm_code = db.Column(db.String(20))     # e.g. "F001", if this zone came from the rich dataset
    herd_size = db.Column(db.Integer)
    primary_water_source = db.Column(db.String(160))
    # True for a zone that only exists as a *destination* to relocate to
    # (e.g. Dundee, Ermelo, Underberg) rather than a monitored farm itself.
    is_relocation_target = db.Column(db.Boolean, default=False)

    # Latest known inputs (simple/legacy dataset format -- see DroughtAssessment)
    rainfall_mm = db.Column(db.Float)
    temperature_c = db.Column(db.Float)
    soil_moisture = db.Column(db.Float)
    ndvi = db.Column(db.Float)
    water_availability = db.Column(db.Float)
    historical_drought_freq = db.Column(db.Float)

    # Latest model outputs (legacy formula/ML path)
    risk_score = db.Column(db.Float)
    severity_level = db.Column(db.String(20))       # Low / Moderate / High
    grazing_stress_score = db.Column(db.Float)
    water_stress_score = db.Column(db.Float)
    forecast_json = db.Column(db.Text)

    # Current dashboard snapshot (rich dataset format -- "dashboard_metrics")
    current_severity_band = db.Column(db.String(20))     # watch / warning / critical / normal
    current_dsi = db.Column(db.Float)
    estimated_livestock_at_risk_now = db.Column(db.Integer)
    water_point_level_pct_now = db.Column(db.Float)
    feed_days_remaining_now = db.Column(db.Float)
    projected_financial_impact_zar = db.Column(db.Float)
    forecast_horizon_weeks = db.Column(db.Integer)
    trend = db.Column(db.String(20))                     # worsening / improving / stable

    # Live current weather (refreshed periodically in the background --
    # see scheduler_jobs.py -- rather than fetched per page view).
    current_temp_c = db.Column(db.Float)
    current_weather_main = db.Column(db.String(60))
    current_weather_description = db.Column(db.String(120))
    current_weather_icon = db.Column(db.String(10))
    weather_updated_at = db.Column(db.DateTime)

    last_updated = db.Column(db.DateTime, default=datetime.utcnow)

    farms = db.relationship("Farm", backref="zone", lazy=True)
    assessments = db.relationship("DroughtAssessment", backref="zone", lazy=True)
    forecast_readings = db.relationship("ForecastReading", backref="zone", lazy=True,
                                         cascade="all, delete-orphan")
    alerts = db.relationship("DroughtAlert", backref="zone", lazy=True,
                              cascade="all, delete-orphan")
    relocation_recommendations = db.relationship("RelocationRecommendation", backref="zone", lazy=True,
                                                  cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Zone {self.name}>"


class Farm(db.Model):
    __tablename__ = "farms"

    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    zone_id = db.Column(db.Integer, db.ForeignKey("zones.id"), nullable=False)

    name = db.Column(db.String(120), nullable=False)
    latitude = db.Column(db.Float)
    longitude = db.Column(db.Float)
    herd_size = db.Column(db.Integer, default=0)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_cycle_check = db.Column(db.Date, default=date.today)

    notifications = db.relationship("Notification", backref="farm", lazy=True)

    def __repr__(self):
        return f"<Farm {self.name}>"


class DroughtAssessment(db.Model):
    """One reading for a zone, in the SIMPLE/legacy JSON format (a flat list
    of {zone, date, rainfall_mm, ndvi, ...} records). Used to train/evaluate
    the in-app ML model. Not used by the rich worst/best-case dataset --
    that one populates ForecastReading instead."""
    __tablename__ = "drought_assessments"

    id = db.Column(db.Integer, primary_key=True)
    zone_id = db.Column(db.Integer, db.ForeignKey("zones.id"), nullable=False)
    reading_date = db.Column(db.Date, nullable=False)

    rainfall_mm = db.Column(db.Float)
    temperature_c = db.Column(db.Float)
    soil_moisture = db.Column(db.Float)
    ndvi = db.Column(db.Float)
    water_availability = db.Column(db.Float)
    historical_drought = db.Column(db.Integer)

    risk_score = db.Column(db.Float)
    severity_level = db.Column(db.String(20))

    def __repr__(self):
        return f"<DroughtAssessment zone={self.zone_id} date={self.reading_date}>"


class ForecastReading(db.Model):
    """One week, one scenario (worst_case / best_case), for a zone -- the
    rich dataset's weekly forecast series. Powers the map's scenario toggle
    and the worst-case/best-case story on the zone detail panel."""
    __tablename__ = "forecast_readings"

    id = db.Column(db.Integer, primary_key=True)
    zone_id = db.Column(db.Integer, db.ForeignKey("zones.id"), nullable=False)
    scenario = db.Column(db.String(20), nullable=False)   # "worst_case" or "best_case"
    week_start = db.Column(db.Date, nullable=False)
    week_index = db.Column(db.Integer, nullable=False)     # 0-based position in the horizon, for ordering/charting

    ndvi = db.Column(db.Float)
    soil_moisture_pct = db.Column(db.Float)
    rainfall_mm = db.Column(db.Float)
    rainfall_deficit_pct = db.Column(db.Float)
    temp_anomaly_c = db.Column(db.Float)
    drought_stress_index = db.Column(db.Float)
    water_point_level_pct = db.Column(db.Float)
    grazing_capacity_pct = db.Column(db.Float)
    feed_days_remaining = db.Column(db.Float)
    estimated_livestock_at_risk = db.Column(db.Integer)
    estimated_financial_impact_zar = db.Column(db.Float)

    __table_args__ = (
        db.UniqueConstraint("zone_id", "scenario", "week_start", name="uix_zone_scenario_week"),
    )

    def __repr__(self):
        return f"<ForecastReading zone={self.zone_id} {self.scenario} wk{self.week_index}>"


class DroughtAlert(db.Model):
    """An auto-triggered, dataset-sourced early-warning alert (distinct from
    the in-app Notification model, which is user-facing/farm-specific --
    this is the raw dataset alert tied to a zone/scenario)."""
    __tablename__ = "drought_alerts"

    id = db.Column(db.Integer, primary_key=True)
    zone_id = db.Column(db.Integer, db.ForeignKey("zones.id"), nullable=False)
    source_alert_id = db.Column(db.String(40))   # e.g. "F001-A02", from the dataset
    scenario = db.Column(db.String(20), default="worst_case")
    week_start = db.Column(db.Date)
    severity = db.Column(db.String(20))           # watch / warning / critical
    drought_stress_index = db.Column(db.Float)
    lead_time_days = db.Column(db.Integer)
    message_to_farmer = db.Column(db.Text)
    recommended_actions = db.Column(db.Text)      # JSON-encoded list of strings

    def __repr__(self):
        return f"<DroughtAlert zone={self.zone_id} {self.severity}>"


class RelocationRecommendation(db.Model):
    """A 'move your herd here instead' suggestion tied to a zone, taken
    straight from the dataset when available."""
    __tablename__ = "relocation_recommendations"

    id = db.Column(db.Integer, primary_key=True)
    zone_id = db.Column(db.Integer, db.ForeignKey("zones.id"), nullable=False)
    recommended_city = db.Column(db.String(120))
    province = db.Column(db.String(120))
    distance_km = db.Column(db.Float)
    reason = db.Column(db.Text)
    projected_grazing_capacity_pct = db.Column(db.Float)
    estimated_relocation_cost_zar = db.Column(db.Float)

    def __repr__(self):
        return f"<RelocationRecommendation {self.recommended_city}>"


class Notification(db.Model):
    __tablename__ = "notifications"

    id = db.Column(db.Integer, primary_key=True)
    farm_id = db.Column(db.Integer, db.ForeignKey("farms.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    message = db.Column(db.Text, nullable=False)
    level = db.Column(db.String(20), default="info")  # info / warning / danger
    is_read = db.Column(db.Boolean, default=False)

    def __repr__(self):
        return f"<Notification farm={self.farm_id} level={self.level}>"


class HelpAlert(db.Model):
    """A farmer-to-farmer help request ('I need help -- feed, water, transport')
    posted to the community. Everyone else in the same zone/province gets a
    Notification when one is posted."""
    __tablename__ = "help_alerts"

    id = db.Column(db.Integer, primary_key=True)
    requester_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    zone_id = db.Column(db.Integer, db.ForeignKey("zones.id"))
    message = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    resolved = db.Column(db.Boolean, default=False)

    zone = db.relationship("Zone")

    def __repr__(self):
        return f"<HelpAlert from={self.requester_id} resolved={self.resolved}>"


class Message(db.Model):
    """A direct message between two farmers, sent over the real-time
    community chat (Socket.IO) instead of email."""
    __tablename__ = "messages"

    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    recipient_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_read = db.Column(db.Boolean, default=False)

    sender = db.relationship("User", foreign_keys=[sender_id])
    recipient = db.relationship("User", foreign_keys=[recipient_id])

    @staticmethod
    def room_name(user_id_a, user_id_b):
        """Deterministic chat-room name for a pair of users, regardless of order."""
        a, b = sorted([int(user_id_a), int(user_id_b)])
        return f"dm-{a}-{b}"

    def __repr__(self):
        return f"<Message {self.sender_id}->{self.recipient_id}>"
