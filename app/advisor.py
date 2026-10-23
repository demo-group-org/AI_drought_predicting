"""
Builds the farmer-facing "advisor" summary shown on the home page: is this
zone currently in a drought risk period, what's the plain-language
recommendation, and what would the system automatically tell the farmer if
conditions worsen. Uses the real dataset's own alert message when one has
been loaded for this zone; otherwise falls back to the formula/ML path so
every zone -- rich dataset or simple/legacy -- gets a sensible summary.
"""
import json

SEVERITY_BAND_TO_LEVEL = {"normal": "Low", "watch": "Low", "warning": "Moderate", "critical": "High"}


def format_iot_actions_for_zone(zone, actions=None):
    """Normalize recommended drought actions into the device-oriented format
    used by edge gateways / Lambda automation payloads. This keeps the human-
    readable advisory text intact while exposing the exact commands that can be
    sent outward to valves, pumps, and other sensors."""
    normalized = []
    candidate_actions = actions or []
    severity = (zone.current_severity_band or "normal").lower() if zone else "unknown"

    def map_action(raw_action):
        if isinstance(raw_action, dict):
            device = raw_action.get("device") or raw_action.get("type") or raw_action.get("name") or "iot_device"
            command = raw_action.get("action") or raw_action.get("command") or raw_action.get("operation") or "execute"
            value = raw_action.get("value")
            target = raw_action.get("target") or raw_action.get("location") or (zone.name if zone else None)
            return {
                "zone_id": zone.id if zone else None,
                "zone_name": zone.name if zone else None,
                "severity": severity,
                "device": str(device),
                "action": str(command),
                "value": value,
                "target": target,
            }

        label = str(raw_action or "").strip()
        if not label:
            return None

        lower = label.lower()
        if "valve" in lower or "water" in lower:
            device = "water_valve"
        elif "pump" in lower or "solar" in lower:
            device = "solar_pump"
        elif "feed" in lower or "grazing" in lower:
            device = "feed_station"
        else:
            device = "iot_device"

        if "throttle" in lower or "reduce" in lower:
            action = "throttle"
        elif "start" in lower or "run" in lower:
            action = "start"
        elif "stop" in lower or "halt" in lower:
            action = "stop"
        elif "open" in lower:
            action = "open"
        elif "close" in lower:
            action = "close"
        else:
            action = "execute"

        value = None
        for keyword in ("30%", "40%", "50%", "60%", "70%", "80%", "90%", "100%"):
            if keyword in label:
                value = keyword
                break
        if value is None and any(token.isdigit() for token in label.split()):
            value = [token for token in label.split() if token.isdigit()][0]

        return {
            "zone_id": zone.id if zone else None,
            "zone_name": zone.name if zone else None,
            "severity": severity,
            "device": device,
            "action": action,
            "value": value,
            "target": zone.name if zone else None,
        }

    for item in candidate_actions:
        entry = map_action(item)
        if entry:
            normalized.append(entry)

    if not normalized and zone and severity == "critical":
        normalized = [
            {
                "zone_id": zone.id,
                "zone_name": zone.name,
                "severity": "critical",
                "device": "water_valve",
                "action": "throttle",
                "value": "30%",
                "target": zone.name,
            },
            {
                "zone_id": zone.id,
                "zone_name": zone.name,
                "severity": "critical",
                "device": "solar_pump",
                "action": "start",
                "value": "emergency",
                "target": zone.name,
            },
        ]

    return normalized


def summarize_zone_for_farmer(app, zone):
    from app.models import DroughtAlert
    from app.ml.predict import predict_for_zone

    has_rich_data = zone.current_dsi is not None

    if has_rich_data:
        band = (zone.current_severity_band or "normal").lower()
        severity_level = SEVERITY_BAND_TO_LEVEL.get(band, "Low")
        in_drought = band in ("warning", "critical")

        alert = (
            DroughtAlert.query.filter_by(zone_id=zone.id)
            .order_by(DroughtAlert.week_start.asc().nullslast())
            .first()
        )
        if alert:
            message = alert.message_to_farmer
            actions = json.loads(alert.recommended_actions or "[]")
            lead_time_days = alert.lead_time_days
        else:
            message = (
                f"{zone.name} is currently stable (drought stress index "
                f"{zone.current_dsi:.0f}/100, trend {zone.trend or 'steady'}). "
                f"No action needed right now -- keep an eye on water points and grazing condition."
            )
            actions = ["Continue routine monitoring", "Check water-point levels weekly"]
            lead_time_days = None

        iot_actions = format_iot_actions_for_zone(zone, actions)
        return {
            "has_data": True,
            "severity_level": severity_level,
            "severity_band": band,
            "in_drought": in_drought,
            "drought_stress_index": zone.current_dsi,
            "feed_days_remaining": zone.feed_days_remaining_now,
            "water_point_level_pct": zone.water_point_level_pct_now,
            "livestock_at_risk": zone.estimated_livestock_at_risk_now,
            "financial_impact_zar": zone.projected_financial_impact_zar,
            "trend": zone.trend,
            "message": message,
            "recommended_actions": actions,
            "iot_actions": iot_actions,
            "lead_time_days": lead_time_days,
        }

    # Legacy/simple-format zone (or a zone with no data loaded at all yet)
    result = predict_for_zone(app, zone)
    severity_level = result["severity_level"]
    in_drought = severity_level == "High"
    if severity_level == "High":
        message = (
            f"{zone.name} is at High drought risk (score {result['risk_score']}/100). "
            f"Grazing and water stress are both elevated -- this is not a good time to "
            f"bring in more livestock, and it's worth reviewing your herd-reduction options."
        )
    elif severity_level == "Moderate":
        message = (
            f"{zone.name} is at Moderate drought risk (score {result['risk_score']}/100). "
            f"Worth increasing how often you check water points and grazing condition."
        )
    else:
        message = (
            f"{zone.name} is at Low drought risk (score {result['risk_score']}/100). "
            f"Conditions look stable -- routine monitoring is enough for now."
        )

    actions = ["Continue routine monitoring"]
    if in_drought:
        actions = [
            "Throttle water valves by 30%",
            "Start emergency solar pump cycle",
            "Reduce grazing pressure and check feed stores",
        ]

    return {
        "has_data": zone.risk_score is not None,
        "severity_level": severity_level,
        "severity_band": severity_level.lower(),
        "in_drought": in_drought,
        "drought_stress_index": result["risk_score"],
        "feed_days_remaining": None,
        "water_point_level_pct": None,
        "livestock_at_risk": None,
        "financial_impact_zar": None,
        "trend": None,
        "message": message,
        "recommended_actions": actions,
        "iot_actions": format_iot_actions_for_zone(zone, actions),
        "lead_time_days": None,
    }
