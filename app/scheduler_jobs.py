"""
Runs once a day. For every farm where MONTH_CYCLE_DAYS (default 30) have
passed since the last check, it looks at that farm's zone risk and
creates a Notification:
  - if the zone is Low risk        -> "safe to start your new month" message
  - if the zone is Moderate/High   -> a caution message with the current risk

The farm's cycle then resets from today, so this repeats every ~30 days
for as long as the farm exists.

A second job refreshes live current weather for every zone from
OpenWeatherMap every 30 minutes (paced gently to stay within the free-tier
rate limit), so the map/dashboard/home page show real, current conditions
rather than only the forecast dataset.
"""
from datetime import date, timedelta, datetime
import time


def register_jobs(app, scheduler):
    def check_monthly_cycles():
        with app.app_context():
            from app import db
            from app.models import Farm, Notification

            cycle_days = app.config["MONTH_CYCLE_DAYS"]
            cutoff = date.today() - timedelta(days=cycle_days)

            due_farms = Farm.query.filter(Farm.last_cycle_check <= cutoff).all()
            for farm in due_farms:
                zone = farm.zone
                if zone is None or zone.severity_level is None:
                    continue

                if zone.severity_level == "Low":
                    message = (
                        f"{cycle_days} days have passed for {farm.name}. "
                        f"Nothing suspicious is showing for {zone.name} -- "
                        f"you can safely start your new farming month."
                    )
                    level = "info"
                else:
                    message = (
                        f"{cycle_days} days have passed for {farm.name}. "
                        f"{zone.name} is currently at {zone.severity_level} drought risk "
                        f"(score {zone.risk_score}) -- review grazing and water plans before "
                        f"starting the new month."
                    )
                    level = "warning" if zone.severity_level == "Moderate" else "danger"

                db.session.add(Notification(farm_id=farm.id, message=message, level=level))
                farm.last_cycle_check = date.today()

            if due_farms:
                db.session.commit()

    def refresh_weather():
        with app.app_context():
            from app import db
            from app.models import Zone
            from app.weather import fetch_current_weather

            zones = Zone.query.all()
            for zone in zones:
                result = fetch_current_weather(zone.latitude, zone.longitude)
                if result:
                    zone.current_temp_c = result["temp_c"]
                    zone.current_weather_main = result["main"]
                    zone.current_weather_description = result["description"]
                    zone.current_weather_icon = result["icon"]
                    zone.weather_updated_at = datetime.utcnow()
                    db.session.commit()
                # Gentle pacing between calls -- well within OpenWeatherMap's
                # free-tier rate limit even for dozens of zones.
                time.sleep(1)

    scheduler.add_job(
        check_monthly_cycles, "interval", days=1,
        id="monthly_cycle_check", replace_existing=True,
    )
    scheduler.add_job(
        refresh_weather, "interval", minutes=30,
        id="weather_refresh", replace_existing=True,
        next_run_time=datetime.now(),  # run once immediately, then every 30 min
    )
