"""
Prediction layer used by the web app for zones that DON'T have a rich,
dataset-provided drought stress index (i.e. legacy/simple-format zones, or
a brand new zone with no data loaded yet). Always uses the transparent
formula in formula.py -- the trained ML model (train_model.py) is used for
the Dashboard's evaluation charts/metrics, not for per-zone inference here,
since its feature set depends on whichever data source it was trained on
and isn't guaranteed to match a single fixed schema.
"""
import os
import json
import math

from app import db
from app.models import Zone
from app.ml.formula import compute_risk_score, severity_from_score

_cache = {"checked": False, "trained": False}


def model_is_trained(app):
    """Whether train_model.py has produced artifacts -- used only to show
    status on the Data & Model page, not for per-zone inference."""
    if not _cache["checked"]:
        model_dir = app.config["ML_MODEL_DIR"]
        _cache["trained"] = os.path.exists(os.path.join(model_dir, "risk_regressor.joblib"))
        _cache["checked"] = True
    return _cache["trained"]


def predict_for_zone(app, zone: Zone, persist=True):
    """
    Returns a dict with risk_score, severity_level, grazing_stress_score,
    water_stress_score and a simple 30/60/90-day forecast, and (optionally)
    saves those values onto the Zone row. Formula-based -- see
    app/ml/formula.py for the transparent weighting.
    """
    risk_score, grazing_stress, water_stress = compute_risk_score(
        rainfall_mm=zone.rainfall_mm, temperature_c=zone.temperature_c,
        soil_moisture=zone.soil_moisture, ndvi=zone.ndvi,
        water_availability=zone.water_availability,
        historical_drought=zone.historical_drought_freq,
    )
    severity_level = severity_from_score(
        risk_score, app.config["RISK_LOW_MAX"], app.config["RISK_MODERATE_MAX"]
    )

    forecast = _simple_forecast(risk_score, zone.historical_drought_freq or 0)

    if persist:
        zone.risk_score = round(risk_score, 1)
        zone.severity_level = severity_level
        zone.grazing_stress_score = grazing_stress
        zone.water_stress_score = water_stress
        zone.forecast_json = json.dumps(forecast)
        db.session.commit()

    return {
        "zone": zone.name,
        "risk_score": round(risk_score, 1),
        "severity_level": severity_level,
        "grazing_stress_score": grazing_stress,
        "water_stress_score": water_stress,
        "forecast": forecast,
        "source": "formula_fallback",
    }


def _simple_forecast(current_score, historical_drought_freq):
    """
    Lightweight persistence-plus-history forecast for the 30/60/90-day
    horizons: the further out, the more the score drifts toward this
    zone's historical drought frequency. This is intentionally simple --
    a clearly-labelled placeholder to refine once enough historical,
    dated readings exist to train a proper time-series model.
    """
    drift_target = 40 + (historical_drought_freq * 60)  # zones with more drought history drift higher
    return {
        "30": round(current_score * 0.85 + drift_target * 0.15, 1),
        "60": round(current_score * 0.65 + drift_target * 0.35, 1),
        "90": round(current_score * 0.45 + drift_target * 0.55, 1),
    }


def suggest_alternative_zones(current_zone: Zone, limit=3, max_distance_km=250):
    """
    Recommends other zones with meaningfully lower drought risk than the
    farmer's current zone -- used to advise against farming in a
    high-risk area and point toward safer land instead.

    Distance-aware: prefers the nearest lower-risk zones within
    max_distance_km, since relocating a herd a short distance is realistic
    and relocating it across provinces usually isn't. Only reaches beyond
    that radius if nothing closer qualifies, so a farmer is never pointed
    somewhere impractically far "unless it genuinely has to be" -- i.e.
    there's no closer safe option at all.
    """
    candidates = Zone.query.filter(Zone.id != current_zone.id, Zone.risk_score.isnot(None)).all()

    scored = []
    for c in candidates:
        if current_zone.risk_score is not None and c.risk_score >= current_zone.risk_score:
            continue
        distance_km = _haversine_km(current_zone.latitude, current_zone.longitude, c.latitude, c.longitude)
        scored.append((c, distance_km))

    if not scored:
        return []

    nearby = [s for s in scored if s[1] <= max_distance_km]
    pool = nearby if nearby else scored  # only reach further afield if nothing nearby qualifies
    pool.sort(key=lambda s: s[1])  # nearest first

    return [
        {
            "zone": c.name,
            "district": c.district,
            "latitude": c.latitude,
            "longitude": c.longitude,
            "risk_score": c.risk_score,
            "severity_level": c.severity_level,
            "distance_km": round(distance_km, 1),
        }
        for c, distance_km in pool[:limit]
    ]


def _haversine_km(lat1, lon1, lat2, lon2):
    """Great-circle distance in km between two lat/lon points."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
