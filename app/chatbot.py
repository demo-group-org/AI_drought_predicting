"""
A small keyword-matching assistant for the home page. Deliberately NOT an
LLM integration -- it reads directly from the database (zones, forecast
readings, alerts, relocation recommendations, live weather) that's already
loaded, and composes a plain-language answer. No API key, no upload, no
external call required for this to work.
"""
from app.advisor import summarize_zone_for_farmer


def answer_question(app, user, message):
    from app.models import Farm, ForecastReading

    message = (message or "").strip()
    if not message:
        return "Ask me something like \"what's my risk\" or \"what's the weather at my farm\"."

    farms = Farm.query.filter_by(owner_id=user.id).all()
    if not farms:
        return "You haven't added a farm yet -- add one from My Farms and I'll be able to answer questions about it."

    lower = message.lower()

    # Figure out which farm/zone the question is about: look for a farm or
    # zone name mentioned, otherwise default to the farmer's first farm.
    target_farm = farms[0]
    for farm in farms:
        if farm.name.lower() in lower or farm.zone.name.lower() in lower:
            target_farm = farm
            break

    zone = target_farm.zone
    summary = summarize_zone_for_farmer(app, zone)

    greeting_words = ["hi", "hello", "hey", "howzit", "sawubona"]
    if any(lower == g or lower.startswith(g + " ") for g in greeting_words):
        return f"Hi {user.name}! Ask me about weather, drought risk, feed/water days, or whether you should relocate."

    if any(w in lower for w in ["weather", "rain", "temperature", "hot", "cold", "forecast today"]):
        if zone.current_temp_c is not None:
            return (
                f"Right now at {zone.name}: {zone.current_temp_c:.0f}\u00b0C, "
                f"{zone.current_weather_description or zone.current_weather_main or 'conditions unavailable'}."
            )
        return f"I don't have live weather for {zone.name} yet -- it refreshes automatically soon after the server starts."

    if any(w in lower for w in ["relocate", "move my herd", "move herd", "another zone", "safer place", "where should i"]):
        from app.ml.predict import suggest_alternative_zones
        from app.models import RelocationRecommendation
        recs = RelocationRecommendation.query.filter_by(zone_id=zone.id).all()
        if recs:
            lines = [f"{r.recommended_city} ({r.distance_km:.0f} km, grazing capacity {r.projected_grazing_capacity_pct:.0f}%)" for r in recs]
            return f"For {zone.name}, the ranked relocation options are: " + "; ".join(lines) + "."
        suggestions = suggest_alternative_zones(zone)
        if suggestions:
            lines = [f"{s['zone']} ({s['distance_km']} km, risk {s['risk_score']})" for s in suggestions]
            return f"Nearby lower-risk zones for {zone.name}: " + "; ".join(lines) + "."
        return f"{zone.name} doesn't currently need relocation -- risk is {summary['severity_level']}."

    if any(w in lower for w in ["worst case", "worst-case", "if drought continues", "keeps not raining"]):
        return _scenario_reply(zone, "worst_case")

    if any(w in lower for w in ["best case", "best-case", "if it rains", "rain return", "if rains return"]):
        return _scenario_reply(zone, "best_case")

    if any(w in lower for w in ["feed", "water", "days remaining", "days left"]):
        parts = []
        if summary["feed_days_remaining"] is not None:
            parts.append(f"about {summary['feed_days_remaining']:.0f} feed days remaining")
        if summary["water_point_level_pct"] is not None:
            parts.append(f"water points at {summary['water_point_level_pct']:.0f}%")
        if parts:
            return f"At {zone.name}: " + " and ".join(parts) + "."
        return f"I don't have feed/water numbers for {zone.name} yet."

    if any(w in lower for w in ["risk", "drought", "stress", "danger", "how am i", "how is my farm", "status"]):
        return summary["message"]

    # Fallback: general status, same as the advisor card's own message.
    return summary["message"]


def _scenario_reply(zone, scenario):
    from app.models import ForecastReading
    readings = (
        ForecastReading.query.filter_by(zone_id=zone.id, scenario=scenario)
        .order_by(ForecastReading.week_index.desc())
        .first()
    )
    if not readings:
        return f"I don't have a week-by-week forecast loaded for {zone.name} yet."
    label = "if the drought continues" if scenario == "worst_case" else "if good rains return"
    return (
        f"For {zone.name}, {label}: by the end of the forecast, drought stress index would reach "
        f"{readings.drought_stress_index:.0f}/100, grazing capacity {readings.grazing_capacity_pct:.0f}%, "
        f"feed days remaining {readings.feed_days_remaining:.0f}, "
        f"estimated financial impact R{readings.estimated_financial_impact_zar:,.0f}."
    )
