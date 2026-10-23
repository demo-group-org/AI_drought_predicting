"""
Live current-weather lookup for a zone's coordinates, via OpenWeatherMap.
Adapted from the user's own weather.py: same API, but looked up by the
zone's stored lat/lon directly (no city-name geocoding needed, since every
zone already has coordinates) and wrapped so a failed/slow API call never
takes down the app.
"""
import os
import requests

OPENWEATHER_CURRENT_URL = "https://api.openweathermap.org/data/2.5/weather"
OPENWEATHER_FORECAST_URL = "https://api.openweathermap.org/data/2.5/forecast"


def _get_api_key(api_key=None):
    """Reads OPENWEATHER_API_KEY from .env; also accepts the older API_KEY name."""
    return api_key or os.environ.get("OPENWEATHER_API_KEY") or os.environ.get("API_KEY")


def fetch_current_weather(lat, lon, api_key=None, timeout=6):
    """
    Returns {"temp_c": .., "main": .., "description": .., "icon": ..} for
    the given coordinates, or None if the API key is missing or the
    request fails for any reason (network, bad key, rate limit, etc).
    """
    api_key = _get_api_key(api_key)
    if not api_key:
        return None

    try:
        response = requests.get(
            OPENWEATHER_CURRENT_URL,
            params={"lat": lat, "lon": lon, "appid": api_key, "units": "metric"},
            timeout=timeout,
        )
        response.raise_for_status()
        data = response.json()
        weather = (data.get("weather") or [{}])[0]
        return {
            "temp_c": data.get("main", {}).get("temp"),
            "main": weather.get("main"),
            "description": weather.get("description"),
            "icon": weather.get("icon"),
        }
    except (requests.RequestException, ValueError, KeyError, IndexError):
        return None


def fetch_daily_forecast(lat, lon, api_key=None, days=5, timeout=6):
    """
    Returns a list of up to `days` dicts:
    {"date": "2026-10-03", "temp_min": .., "temp_max": .., "icon": "..",
     "description": ".."} -- a daily summary built from OpenWeatherMap's
    free 5-day/3-hour-step forecast endpoint (one API call covers the
    whole window; no per-day calls needed). Returns [] on any failure so
    the calendar UI can show "forecast unavailable" instead of crashing.
    """
    api_key = _get_api_key(api_key)
    if not api_key:
        return []

    try:
        response = requests.get(
            OPENWEATHER_FORECAST_URL,
            params={"lat": lat, "lon": lon, "appid": api_key, "units": "metric"},
            timeout=timeout,
        )
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError):
        return []

    by_day = {}
    for entry in data.get("list", []):
        date_str = entry.get("dt_txt", "")[:10]
        if not date_str:
            continue
        weather = (entry.get("weather") or [{}])[0]
        temp = entry.get("main", {}).get("temp")
        bucket = by_day.setdefault(date_str, {"temps": [], "icons": [], "descriptions": []})
        if temp is not None:
            bucket["temps"].append(temp)
        if weather.get("icon"):
            bucket["icons"].append(weather["icon"])
        if weather.get("description"):
            bucket["descriptions"].append(weather["description"])

    daily = []
    for date_str in sorted(by_day.keys())[:days]:
        bucket = by_day[date_str]
        if not bucket["temps"]:
            continue
        # Use the most common icon/description of the day (usually midday conditions dominate).
        icon = max(set(bucket["icons"]), key=bucket["icons"].count) if bucket["icons"] else None
        description = max(set(bucket["descriptions"]), key=bucket["descriptions"].count) if bucket["descriptions"] else ""
        daily.append({
            "date": date_str,
            "temp_min": round(min(bucket["temps"]), 1),
            "temp_max": round(max(bucket["temps"]), 1),
            "icon": icon,
            "description": description,
        })
    return daily