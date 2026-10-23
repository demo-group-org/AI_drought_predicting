"""
Loads the JSON dataset you provide into the database.

Expected JSON shape -- a list of reading objects:

[
  {
    "zone": "Msinga",
    "district": "uMzinyathi",
    "latitude": -28.75,
    "longitude": 30.42,
    "date": "2024-01-15",
    "rainfall_mm": 12.4,
    "temperature_c": 31.2,
    "soil_moisture": 0.18,
    "ndvi": 0.31,
    "water_availability": 0.40,
    "historical_drought": 1,
    "risk_score": 78.5,          // optional -- if you have a ground-truth label
    "severity_level": "High"     // optional -- Low / Moderate / High
  },
  ...
]

Only "zone", "latitude", "longitude" and "date" are required. Every other
field is optional -- missing values are stored as NULL and handled by the
training pipeline. If "risk_score" / "severity_level" are omitted, the
training script derives a proxy label from the weighted formula in
ml/formula.py so the pipeline still works before you have real ground truth.
"""
import json
from datetime import datetime

from app import db
from app.models import Zone, DroughtAssessment, ForecastReading, DroughtAlert, RelocationRecommendation

# Approximate coordinates for towns that appear as relocation targets but
# aren't themselves one of the dataset's monitored farms, plus Msinga (not
# in the current dataset at all, but requested on the map regardless).
KNOWN_TOWN_COORDS = {
    "Dundee": (-28.1657, 30.2325, "KwaZulu-Natal"),
    "Ermelo": (-26.5330, 29.9891, "Mpumalanga"),
    "Underberg": (-29.7833, 29.5000, "KwaZulu-Natal"),
    "Kokstad": (-30.5460, 29.4270, "KwaZulu-Natal"),
    "Middelburg (Mpumalanga)": (-25.7750, 29.4640, "Mpumalanga"),
    "Msinga": (-28.7500, 30.4200, "KwaZulu-Natal"),
}


def _parse_date(value):
    if isinstance(value, str):
        return datetime.strptime(value, "%Y-%m-%d").date()
    return value


def load_json_file(filepath):
    with open(filepath, "r", encoding="utf-8") as f:
        records = json.load(f)
    return load_records(records)


def load_records(records):
    """
    Upserts Zones and inserts DroughtAssessment rows from a list of dicts
    (see module docstring for shape). Returns a summary dict.
    """
    zones_created, zones_updated, readings_created = 0, 0, 0

    for rec in records:
        zone_name = rec["zone"].strip()
        zone = Zone.query.filter_by(name=zone_name).first()

        if zone is None:
            zone = Zone(
                name=zone_name,
                district=rec.get("district"),
                latitude=rec["latitude"],
                longitude=rec["longitude"],
            )
            db.session.add(zone)
            db.session.flush()  # get zone.id before we use it below
            zones_created += 1
        else:
            zones_updated += 1

        # Keep the zone's "latest known" fields in sync with the newest reading.
        zone.district = rec.get("district", zone.district)
        zone.rainfall_mm = rec.get("rainfall_mm", zone.rainfall_mm)
        zone.temperature_c = rec.get("temperature_c", zone.temperature_c)
        zone.soil_moisture = rec.get("soil_moisture", zone.soil_moisture)
        zone.ndvi = rec.get("ndvi", zone.ndvi)
        zone.water_availability = rec.get("water_availability", zone.water_availability)
        if "historical_drought" in rec:
            # store as a running frequency across loaded readings
            prior = zone.historical_drought_freq or 0.0
            zone.historical_drought_freq = (prior + float(rec["historical_drought"])) / 2

        reading = DroughtAssessment(
            zone_id=zone.id,
            reading_date=_parse_date(rec["date"]),
            rainfall_mm=rec.get("rainfall_mm"),
            temperature_c=rec.get("temperature_c"),
            soil_moisture=rec.get("soil_moisture"),
            ndvi=rec.get("ndvi"),
            water_availability=rec.get("water_availability"),
            historical_drought=rec.get("historical_drought"),
            risk_score=rec.get("risk_score"),
            severity_level=rec.get("severity_level"),
        )
        db.session.add(reading)
        readings_created += 1

    db.session.commit()
    return {
        "zones_created": zones_created,
        "zones_updated": zones_updated,
        "readings_created": readings_created,
    }


def is_rich_dataset(filepath):
    """True if this file is the worst/best-case forecast dataset format
    ({"metadata": ..., "farms": [...]}) rather than the flat reading list."""
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
    return isinstance(data, dict) and "farms" in data


def _get_or_create_zone(name, latitude, longitude, province=None, district=None,
                         is_relocation_target=False, source_farm_code=None,
                         herd_size=None, primary_water_source=None):
    zone = Zone.query.filter_by(name=name).first()
    if zone is None:
        zone = Zone(name=name, latitude=latitude, longitude=longitude)
        db.session.add(zone)
        db.session.flush()
    if province:
        zone.province = province
    if district:
        zone.district = district
    if is_relocation_target:
        zone.is_relocation_target = True
    if source_farm_code:
        zone.source_farm_code = source_farm_code
    if herd_size is not None:
        zone.herd_size = herd_size
    if primary_water_source:
        zone.primary_water_source = primary_water_source
    return zone


def load_rich_dataset(filepath):
    """
    Loads the worst-case/best-case weekly forecast dataset (the format with
    top-level "metadata" and "farms" keys) into Zone, ForecastReading,
    DroughtAlert and RelocationRecommendation. Re-running this with an
    updated file is safe -- existing zones/readings are updated in place
    rather than duplicated.
    """
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    horizon_weeks = data.get("metadata", {}).get("forecast_horizon_weeks")
    band_to_severity = {"normal": "Low", "watch": "Low", "warning": "Moderate", "critical": "High"}

    farms_loaded, weeks_loaded, alerts_loaded, relocations_loaded = 0, 0, 0, 0

    for farm in data.get("farms", []):
        zone = _get_or_create_zone(
            name=farm.get("area") or farm["name"],
            latitude=farm["lat"], longitude=farm["lon"],
            province=farm.get("province"), district=farm.get("province"),
            source_farm_code=farm.get("farm_id"),
            herd_size=farm.get("herd_size"),
            primary_water_source=farm.get("primary_water_source"),
        )
        zone.forecast_horizon_weeks = horizon_weeks
        farms_loaded += 1

        dm = farm.get("dashboard_metrics", {})
        zone.current_severity_band = dm.get("current_severity_band")
        zone.current_dsi = dm.get("current_drought_stress_index")
        zone.estimated_livestock_at_risk_now = dm.get("estimated_livestock_at_risk_now")
        zone.water_point_level_pct_now = dm.get("water_point_level_pct_now")
        zone.feed_days_remaining_now = dm.get("feed_days_remaining_now")
        for key, val in dm.items():
            if key.startswith("projected_financial_impact_zar"):
                zone.projected_financial_impact_zar = val
            if key.startswith("trend"):
                zone.trend = val
        zone.severity_level = band_to_severity.get((zone.current_severity_band or "").lower(), zone.severity_level)
        zone.risk_score = zone.current_dsi

        for scenario, weeks in farm.get("scenarios", {}).items():
            for idx, wk in enumerate(weeks):
                wk_date = _parse_date(wk["week_start"])
                reading = ForecastReading.query.filter_by(
                    zone_id=zone.id, scenario=scenario, week_start=wk_date
                ).first()
                if reading is None:
                    reading = ForecastReading(zone_id=zone.id, scenario=scenario,
                                               week_start=wk_date, week_index=idx)
                    db.session.add(reading)
                reading.week_index = idx
                reading.ndvi = wk.get("ndvi")
                reading.soil_moisture_pct = wk.get("soil_moisture_pct")
                reading.rainfall_mm = wk.get("rainfall_mm")
                reading.rainfall_deficit_pct = wk.get("rainfall_deficit_pct")
                reading.temp_anomaly_c = wk.get("temp_anomaly_c")
                reading.drought_stress_index = wk.get("drought_stress_index")
                reading.water_point_level_pct = wk.get("water_point_level_pct")
                reading.grazing_capacity_pct = wk.get("grazing_capacity_pct")
                reading.feed_days_remaining = wk.get("feed_days_remaining")
                reading.estimated_livestock_at_risk = wk.get("estimated_livestock_at_risk")
                reading.estimated_financial_impact_zar = wk.get("estimated_financial_impact_zar")
                weeks_loaded += 1

        # Re-loading replaces this zone's alerts/relocation recs rather than
        # accumulating duplicates across repeated uploads of the same/updated file.
        DroughtAlert.query.filter_by(zone_id=zone.id).delete()
        RelocationRecommendation.query.filter_by(zone_id=zone.id).delete()

        for a in farm.get("alerts", []):
            db.session.add(DroughtAlert(
                zone_id=zone.id,
                source_alert_id=a.get("alert_id"),
                week_start=_parse_date(a["week_start"]) if a.get("week_start") else None,
                severity=a.get("severity"),
                drought_stress_index=a.get("drought_stress_index"),
                lead_time_days=a.get("lead_time_days"),
                message_to_farmer=a.get("message_to_farmer"),
                recommended_actions=json.dumps(a.get("recommended_actions", [])),
            ))
            alerts_loaded += 1

        for r in farm.get("relocation_recommendations", []):
            db.session.add(RelocationRecommendation(
                zone_id=zone.id,
                recommended_city=r.get("recommended_city"),
                province=r.get("province"),
                distance_km=r.get("distance_km"),
                reason=r.get("reason"),
                projected_grazing_capacity_pct=r.get("projected_grazing_capacity_pct"),
                estimated_relocation_cost_zar=r.get("estimated_relocation_cost_zar"),
            ))
            relocations_loaded += 1

            coords = KNOWN_TOWN_COORDS.get(r.get("recommended_city"))
            if coords:
                lat, lon, default_province = coords
                target_zone = _get_or_create_zone(
                    name=r["recommended_city"], latitude=lat, longitude=lon,
                    province=r.get("province") or default_province,
                    is_relocation_target=True,
                )
                if target_zone.current_dsi is None:
                    target_zone.current_dsi = max(0.0, 100 - (r.get("projected_grazing_capacity_pct") or 80))
                    target_zone.severity_level = "Low"
                    target_zone.current_severity_band = "normal"
                    target_zone.risk_score = target_zone.current_dsi

    # Always keep Msinga visible on the map, even before it has its own data.
    if not Zone.query.filter_by(name="Msinga").first():
        lat, lon, province = KNOWN_TOWN_COORDS["Msinga"]
        db.session.add(Zone(name="Msinga", latitude=lat, longitude=lon,
                             province=province, district="uMzinyathi"))

    db.session.commit()
    return {
        "format": "rich_dataset",
        "farms_loaded": farms_loaded,
        "forecast_weeks_loaded": weeks_loaded,
        "alerts_loaded": alerts_loaded,
        "relocation_recommendations_loaded": relocations_loaded,
    }
