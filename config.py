import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


class Config:
    """
    All settings are read from environment variables so the same code runs
    locally (with your own Postgres) and later in production (Azure, etc.)
    without any code changes -- only the .env file / environment differs.
    """

    SECRET_KEY = os.environ.get("SECRET_KEY", "change-this-in-production")

    # Example DATABASE_URL:
    # postgresql+psycopg2://drought_app:your_password@localhost:5432/drought_platform
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL",
        "postgresql+psycopg2://drought_app:your_password@localhost:5432/drought_platform",
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Where the trained ML model + training data live
    ML_MODEL_DIR = os.path.join(BASE_DIR, "app", "ml", "artifacts")
    ML_DATA_DIR = os.path.join(BASE_DIR, "data")
    DASHBOARD_IMG_DIR = os.path.join(BASE_DIR, "app", "static", "img", "dashboard")

    # Shared secret used by AWS Lambda / edge devices to post automation events.
    AUTOMATION_API_KEY = os.environ.get("AUTOMATION_API_KEY", "change-this-automations-key")

    # Number of days after which a farm is re-checked and the farmer is
    # notified that a new farming month is safe to start (per requirement).
    MONTH_CYCLE_DAYS = 30

    # Risk score thresholds (0-100). Feed into both the ML pipeline and the map colours.
    RISK_LOW_MAX = 33
    RISK_MODERATE_MAX = 66
    # anything above RISK_MODERATE_MAX is High
