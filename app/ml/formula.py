"""
Transparent, explainable drought-stress formula. Used in two ways:

1. As a proxy label to train/bootstrap the ML model when a reading has no
   ground-truth risk_score / severity_level of its own.
2. As a fallback score for a zone that the trained model has never seen
   (e.g. brand new zone with only a handful of readings).

All sub-scores are normalised 0-100, where 100 = healthy / low stress.
"""


def _normalise(value, low, high, invert=False):
    if value is None:
        return 50.0  # neutral midpoint when a field is missing
    value = max(low, min(high, value))
    score = (value - low) / (high - low) * 100
    return 100 - score if invert else score


def compute_risk_score(rainfall_mm=None, temperature_c=None, soil_moisture=None,
                        ndvi=None, water_availability=None, historical_drought=None):
    """
    Returns (risk_score 0-100, grazing_stress_score 0-100, water_stress_score 0-100)
    where a HIGHER risk_score means MORE drought stress.
    """
    rainfall_health = _normalise(rainfall_mm, 0, 120)               # more rain = healthier
    ndvi_health = _normalise(ndvi, 0.0, 0.8)                        # higher NDVI = healthier
    soil_health = _normalise(soil_moisture, 0.0, 0.5)               # higher moisture = healthier
    water_health = _normalise(water_availability, 0.0, 1.0)         # higher availability = healthier
    heat_penalty = _normalise(temperature_c, 20, 40)                # higher temp = more stress (not inverted)

    health_score = (
        0.30 * rainfall_health +
        0.25 * ndvi_health +
        0.20 * soil_health +
        0.15 * water_health +
        0.10 * (100 - heat_penalty)
    )

    drought_history_penalty = (historical_drought or 0) * 10  # nudge risk up if this period was a known drought
    risk_score = max(0.0, min(100.0, (100 - health_score) + drought_history_penalty))

    grazing_stress_score = max(0.0, min(100.0, 100 - (0.6 * ndvi_health + 0.4 * rainfall_health)))
    water_stress_score = max(0.0, min(100.0, 100 - (0.7 * water_health + 0.3 * soil_health)))

    return round(risk_score, 1), round(grazing_stress_score, 1), round(water_stress_score, 1)


def severity_from_score(risk_score, low_max=33, moderate_max=66):
    if risk_score <= low_max:
        return "Low"
    if risk_score <= moderate_max:
        return "Moderate"
    return "High"
