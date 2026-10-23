import os
import json

from flask import (
    Blueprint, render_template, redirect, url_for, request,
    flash, jsonify, current_app,
)
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename

from app import db
from app.models import (
    Zone, Farm, Notification, DroughtAssessment, User,
    ForecastReading, DroughtAlert, RelocationRecommendation, HelpAlert, Message, AutomationAudit,
)
from app.ml import data_loader
from app.ml.predict import predict_for_zone, suggest_alternative_zones, model_is_trained
from app.ml.train_model import train_and_evaluate
from app.advisor import summarize_zone_for_farmer, format_iot_actions_for_zone
from app.utils import match_zone_to_location
from app.weather import fetch_daily_forecast
from app.chatbot import answer_question

main_bp = Blueprint("main", __name__)

_forecast_cache = {}  # zone_id -> (fetched_at datetime, forecast list)
_FORECAST_CACHE_MINUTES = 30


@main_bp.route("/")
@login_required
def home():
    farms = Farm.query.filter_by(owner_id=current_user.id).all()
    unread_count = (
        Notification.query.join(Farm)
        .filter(Farm.owner_id == current_user.id, Notification.is_read.is_(False))
        .count()
    )
    zone_count = Zone.query.count()
    high_risk_count = Zone.query.filter(
        (Zone.severity_level == "High") | (Zone.current_severity_band == "critical")
    ).count()

    # Build an "AI advisor" summary for each of the farmer's farms, so the
    # home page opens with a real recommendation rather than an empty shell.
    farm_summaries = []
    for farm in farms:
        summary = summarize_zone_for_farmer(current_app, farm.zone)
        farm_summaries.append({"farm": farm, "summary": summary})

    return render_template(
        "home.html", farms=farms, farm_summaries=farm_summaries,
        unread_count=unread_count, zone_count=zone_count, high_risk_count=high_risk_count,
    )


@main_bp.route("/map")
@login_required
def map_view():
    return render_template("map.html")


@main_bp.route("/api/zones")
@login_required
def api_zones():
    zones = Zone.query.all()
    return jsonify([
        {
            "id": z.id,
            "name": z.name,
            "district": z.district,
            "province": z.province,
            "latitude": z.latitude,
            "longitude": z.longitude,
            "risk_score": z.risk_score,
            "severity_level": z.severity_level or "Unknown",
            "current_severity_band": z.current_severity_band,
            "is_relocation_target": bool(z.is_relocation_target),
            "ndvi": z.ndvi,
            "water_availability": z.water_availability,
            "weather": {
                "temp_c": z.current_temp_c,
                "main": z.current_weather_main,
                "description": z.current_weather_description,
                "icon": z.current_weather_icon,
                "updated_at": z.weather_updated_at.isoformat() if z.weather_updated_at else None,
            } if z.current_temp_c is not None else None,
        }
        for z in zones
    ])


@main_bp.route("/api/zones/<int:zone_id>")
@login_required
def api_zone_detail(zone_id):
    zone = Zone.query.get_or_404(zone_id)
    scenario = request.args.get("scenario", "worst_case")
    if scenario not in ("worst_case", "best_case"):
        scenario = "worst_case"

    readings = (
        ForecastReading.query
        .filter_by(zone_id=zone.id, scenario=scenario)
        .order_by(ForecastReading.week_index)
        .all()
    )

    if readings:
        series = [
            {
                "week_start": r.week_start.isoformat(),
                "week_index": r.week_index,
                "drought_stress_index": r.drought_stress_index,
                "grazing_capacity_pct": r.grazing_capacity_pct,
                "feed_days_remaining": r.feed_days_remaining,
                "water_point_level_pct": r.water_point_level_pct,
                "estimated_financial_impact_zar": r.estimated_financial_impact_zar,
                "estimated_livestock_at_risk": r.estimated_livestock_at_risk,
            }
            for r in readings
        ]
        alerts = [
            {
                "severity": a.severity,
                "week_start": a.week_start.isoformat() if a.week_start else None,
                "drought_stress_index": a.drought_stress_index,
                "lead_time_days": a.lead_time_days,
                "message": a.message_to_farmer,
                "recommended_actions": json.loads(a.recommended_actions or "[]"),
            }
            for a in DroughtAlert.query.filter_by(zone_id=zone.id).all()
        ]
        relocations = [
            {
                "city": r.recommended_city,
                "province": r.province,
                "distance_km": r.distance_km,
                "reason": r.reason,
                "projected_grazing_capacity_pct": r.projected_grazing_capacity_pct,
                "estimated_relocation_cost_zar": r.estimated_relocation_cost_zar,
            }
            for r in RelocationRecommendation.query.filter_by(zone_id=zone.id).all()
        ]
        return jsonify({
            "source": "rich_dataset",
            "zone": zone.name,
            "province": zone.province,
            "herd_size": zone.herd_size,
            "primary_water_source": zone.primary_water_source,
            "is_relocation_target": bool(zone.is_relocation_target),
            "scenario": scenario,
            "severity_level": zone.severity_level or "Unknown",
            "weather": {
                "temp_c": zone.current_temp_c,
                "main": zone.current_weather_main,
                "description": zone.current_weather_description,
                "icon": zone.current_weather_icon,
            } if zone.current_temp_c is not None else None,
            "current": {
                "severity_band": zone.current_severity_band,
                "drought_stress_index": zone.current_dsi,
                "estimated_livestock_at_risk_now": zone.estimated_livestock_at_risk_now,
                "water_point_level_pct_now": zone.water_point_level_pct_now,
                "feed_days_remaining_now": zone.feed_days_remaining_now,
                "projected_financial_impact_zar": zone.projected_financial_impact_zar,
                "trend": zone.trend,
            },
            "forecast_horizon_weeks": zone.forecast_horizon_weeks,
            "series": series,
            "alerts": alerts,
            "relocation_recommendations": relocations,
        })

    # No rich forecast loaded for this zone yet -- fall back to the
    # formula/ML prediction path from the simple dataset format.
    result = predict_for_zone(current_app, zone)
    result["suggestions"] = suggest_alternative_zones(zone) if result["severity_level"] == "High" else []
    result["source"] = result.get("source", "formula_fallback")
    return jsonify(result)


@main_bp.route("/api/farms/<int:farm_id>/advisor")
@login_required
def api_farm_advisor(farm_id):
    """Powers the home page's worst-case/best-case advisor toggle: current
    status + plain-language message, plus what the end of the chosen
    scenario's forecast horizon looks like for this farm's zone."""
    farm = Farm.query.get_or_404(farm_id)
    if farm.owner_id != current_user.id:
        return jsonify({"error": "not your farm"}), 403

    scenario = request.args.get("scenario", "worst_case")
    if scenario not in ("worst_case", "best_case"):
        scenario = "worst_case"

    zone = farm.zone
    summary = summarize_zone_for_farmer(current_app, zone)
    summary["zone_name"] = zone.name
    summary["farm_name"] = farm.name
    summary["weather"] = {
        "temp_c": zone.current_temp_c,
        "main": zone.current_weather_main,
        "description": zone.current_weather_descriptiodn,
        "icon": zone.current_weather_icon,
    } if zone.current_temp_c is not None else None

    readings = (
        ForecastReading.query.filter_by(zone_id=zone.id, scenario=scenario)
        .order_by(ForecastReading.week_index)
        .all()
    )
    summary["projection"] = None
    if readings:
        last = readings[-1]
        summary["projection"] = {
            "scenario": scenario,
            "weeks": len(readings),
            "final_drought_stress_index": last.drought_stress_index,
            "final_grazing_capacity_pct": last.grazing_capacity_pct,
            "final_feed_days_remaining": last.feed_days_remaining,
            "final_financial_impact_zar": last.estimated_financial_impact_zar,
        }
    return jsonify(summary)


@main_bp.route("/farms", methods=["GET", "POST"])
@login_required
def farms():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        zone_id = request.form.get("zone_id")
        herd_size = request.form.get("herd_size", 0)
        latitude = request.form.get("latitude") or None
        longitude = request.form.get("longitude") or None

        if not name or not zone_id:
            flash("Please give the farm a name and select its zone.", "warning")
        else:
            farm = Farm(
                owner_id=current_user.id, zone_id=int(zone_id), name=name,
                herd_size=int(herd_size or 0),
                latitude=float(latitude) if latitude else None,
                longitude=float(longitude) if longitude else None,
            )
            db.session.add(farm)
            db.session.commit()
            flash(f"{name} was registered.", "success")
        return redirect(url_for("main.farms"))

    zones = Zone.query.order_by(Zone.name).all()
    my_farms = Farm.query.filter_by(owner_id=current_user.id).all()
    suggested_zone_id = match_zone_to_location(current_user.location, zones)
    return render_template("farms.html", zones=zones, farms=my_farms, suggested_zone_id=suggested_zone_id)


@main_bp.route("/notifications")
@login_required
def notifications():
    items = (
        Notification.query.join(Farm)
        .filter(Farm.owner_id == current_user.id)
        .order_by(Notification.created_at.desc())
        .all()
    )
    for n in items:
        n.is_read = True
    db.session.commit()
    return render_template("notifications.html", notifications=items)


@main_bp.route("/data", methods=["GET"])
@login_required
def data_page():
    metrics_path = os.path.join(current_app.config["ML_MODEL_DIR"], "metrics.json")
    metrics = None
    if os.path.exists(metrics_path):
        with open(metrics_path) as f:
            metrics = json.load(f)
    reading_count = DroughtAssessment.query.count()
    forecast_reading_count = ForecastReading.query.count()
    zone_count = Zone.query.count()
    return render_template(
        "data.html", metrics=metrics, reading_count=reading_count,
        forecast_reading_count=forecast_reading_count,
        zone_count=zone_count, model_trained=model_is_trained(current_app),
    )


@main_bp.route("/data/upload", methods=["POST"])
@login_required
def data_upload():
    uploaded = request.files.get("json_file")
    if not uploaded or uploaded.filename == "":
        flash("Please choose a .json file to upload.", "warning")
        return redirect(url_for("main.data_page"))

    if not uploaded.filename.lower().endswith(".json"):
        flash("Only .json files are accepted.", "warning")
        return redirect(url_for("main.data_page"))

    filename = secure_filename(uploaded.filename)
    save_path = os.path.join(current_app.config["ML_DATA_DIR"], filename)
    uploaded.save(save_path)

    try:
        if data_loader.is_rich_dataset(save_path):
            summary = data_loader.load_rich_dataset(save_path)
            flash(
                f"Loaded {summary['farms_loaded']} farm(s), "
                f"{summary['forecast_weeks_loaded']} forecast weeks, "
                f"{summary['alerts_loaded']} alerts and "
                f"{summary['relocation_recommendations_loaded']} relocation suggestions.",
                "success",
            )
        else:
            summary = data_loader.load_json_file(save_path)
            flash(
                f"Loaded {summary['readings_created']} readings across "
                f"{summary['zones_created'] + summary['zones_updated']} zones.",
                "success",
            )
    except (KeyError, ValueError, json.JSONDecodeError) as exc:
        flash(f"Could not read that file: {exc}", "danger")

    return redirect(url_for("main.data_page"))


@main_bp.route("/data/train", methods=["POST"])
@login_required
def data_train():
    result = train_and_evaluate(current_app)
    if result.get("status") == "not_enough_data":
        flash(result["message"], "warning")
    else:
        flash("Model trained. Metrics and charts are updated below.", "success")
        # refresh every zone's prediction with the freshly trained model
        for zone in Zone.query.all():
            predict_for_zone(current_app, zone)
    return redirect(url_for("main.data_page"))


@main_bp.route("/dashboard")
@login_required
def dashboard():
    metrics_path = os.path.join(current_app.config["ML_MODEL_DIR"], "metrics.json")
    metrics = None
    if os.path.exists(metrics_path):
        with open(metrics_path) as f:
            metrics = json.load(f)
    img_dir = current_app.config["DASHBOARD_IMG_DIR"]
    chart_files = [
        "feature_importance.png", "confusion_matrix.png",
        "risk_by_severity.png", "rainfall_vs_ndvi.png", "correlation_heatmap.png",
    ]
    available_charts = [c for c in chart_files if os.path.exists(os.path.join(img_dir, c))]
    return render_template("dashboard.html", metrics=metrics, charts=available_charts)


@main_bp.route("/api/farms/<int:farm_id>/forecast")
@login_required
def api_farm_forecast(farm_id):
    """Short-term (5-day) weather calendar for a farm's zone -- 'how is
    the day going to look' at the farmer's registered location."""
    farm = Farm.query.get_or_404(farm_id)
    if farm.owner_id != current_user.id:
        return jsonify({"error": "not your farm"}), 403

    zone = farm.zone
    import datetime as _dt
    cached = _forecast_cache.get(zone.id)
    if cached and (_dt.datetime.utcnow() - cached[0]).total_seconds() < _FORECAST_CACHE_MINUTES * 60:
        return jsonify({"zone": zone.name, "days": cached[1]})

    days = fetch_daily_forecast(zone.latitude, zone.longitude)
    _forecast_cache[zone.id] = (_dt.datetime.utcnow(), days)
    return jsonify({"zone": zone.name, "days": days})


@main_bp.route("/api/automations", methods=["POST"])
def api_automations():
    """Webhook secured by a shared API key for AWS Lambda-triggered
    mitigation actions. It logs the event, stores normalized IoT commands,
    and pushes danger notifications to every farm in the affected zone."""
    provided_key = request.headers.get("X-API-Key")
    expected_key = current_app.config.get("AUTOMATION_API_KEY")
    if expected_key and provided_key != expected_key:
        return jsonify({"error": "unauthorized"}), 401

    payload = request.get_json(silent=True) or {}
    zone_id = payload.get("zone_id") or payload.get("zoneId")
    if zone_id is None:
        return jsonify({"error": "zone_id is required"}), 400

    zone = Zone.query.get(zone_id)
    if zone is None:
        return jsonify({"error": "zone not found"}), 404

    trigger_name = payload.get("trigger_name") or payload.get("triggerName") or "automated_mitigation"
    severity = (payload.get("severity") or "warning").lower()
    actions = payload.get("actions") or payload.get("recommended_actions") or []
    normalized_actions = format_iot_actions_for_zone(zone, actions)

    audit = AutomationAudit(
        zone_id=zone.id,
        trigger_name=trigger_name,
        severity=severity,
        actions_executed=json.dumps(normalized_actions),
        payload=json.dumps(payload),
    )
    db.session.add(audit)

    farms = Farm.query.filter_by(zone_id=zone.id).all()
    notified = 0
    for farm in farms:
        message = (
            f"Automated mitigation triggered for {zone.name}: {trigger_name}. "
            f"Emergency actions executed for {severity} severity."
        )
        db.session.add(Notification(farm_id=farm.id, message=message, level="danger"))
        notified += 1

    db.session.commit()
    return jsonify({
        "status": "accepted",
        "zone_id": zone.id,
        "zone_name": zone.name,
        "severity": severity,
        "audit_id": audit.id,
        "actions": normalized_actions,
        "notification_count": notified,
    })


@main_bp.route("/api/chat", methods=["POST"])
@login_required
def api_chat():
    """The home-page chatbot -- answers purely from data already in the
    database (zones, forecasts, weather, alerts), no upload and no
    external LLM call required."""
    message = (request.get_json(silent=True) or {}).get("message", "")
    reply = answer_question(current_app, current_user, message)
    return jsonify({"reply": reply})


@main_bp.route("/community", methods=["GET", "POST"])
@login_required
def community():
    if request.method == "POST":
        message = request.form.get("message", "").strip()
        if not message:
            flash("Please write a message before sending your alert.", "warning")
            return redirect(url_for("main.community"))

        my_farm = Farm.query.filter_by(owner_id=current_user.id).first()
        zone_id = my_farm.zone_id if my_farm else None

        help_alert = HelpAlert(requester_id=current_user.id, zone_id=zone_id, message=message)
        db.session.add(help_alert)

        # Notify every other farmer with a farm in the same zone, so this
        # reaches the people best placed to actually help.
        notified = 0
        if zone_id:
            other_farms = Farm.query.filter(Farm.zone_id == zone_id, Farm.owner_id != current_user.id).all()
            for f in other_farms:
                db.session.add(Notification(
                    farm_id=f.id,
                    message=f"{current_user.name} {current_user.surname} in your area needs help: \"{message}\"",
                    level="warning",
                ))
                notified += 1

        db.session.commit()
        if notified:
            flash(f"Your alert was posted and {notified} nearby farmer(s) were notified.", "success")
        else:
            flash("Your alert was posted to the community wall.", "success")
        return redirect(url_for("main.community"))

    other_users = User.query.filter(User.id != current_user.id).order_by(User.name).all()
    # attach each user's farm/zone (if any) for display, without a heavy join
    farms_by_owner = {f.owner_id: f for f in Farm.query.all()}
    people = [{"user": u, "farm": farms_by_owner.get(u.id)} for u in other_users]

    help_alerts = HelpAlert.query.order_by(HelpAlert.resolved.asc(), HelpAlert.created_at.desc()).all()

    return render_template("community.html", people=people, help_alerts=help_alerts)


@main_bp.route("/community/chat/<int:user_id>")
@login_required
def community_chat(user_id):
    other_user = User.query.get_or_404(user_id)
    if other_user.id == current_user.id:
        flash("You can't message yourself.", "warning")
        return redirect(url_for("main.community"))

    history = (
        Message.query.filter(
            db.or_(
                db.and_(Message.sender_id == current_user.id, Message.recipient_id == other_user.id),
                db.and_(Message.sender_id == other_user.id, Message.recipient_id == current_user.id),
            )
        )
        .order_by(Message.created_at.asc())
        .all()
    )
    # mark incoming messages as read now that they've been opened
    for m in history:
        if m.recipient_id == current_user.id and not m.is_read:
            m.is_read = True
    db.session.commit()

    return render_template("chat.html", other_user=other_user, history=history)


@main_bp.route("/community/alerts/<int:alert_id>/resolve", methods=["POST"])
@login_required
def resolve_help_alert(alert_id):
    alert = HelpAlert.query.get_or_404(alert_id)
    if alert.requester_id == current_user.id:
        alert.resolved = True
        db.session.commit()
        flash("Marked as resolved.", "success")
    else:
        flash("Only the person who posted an alert can mark it resolved.", "warning")
    return redirect(url_for("main.community"))
