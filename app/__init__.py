import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_socketio import SocketIO
from apscheduler.schedulers.background import BackgroundScheduler

from config import Config

db = SQLAlchemy()
login_manager = LoginManager()
login_manager.login_view = "auth.login"
login_manager.login_message = "Please log in to view that page."
login_manager.login_message_category = "warning"

# threading async_mode needs no extra server (eventlet/gevent) -- fine for
# a small number of concurrent users such as a hackathon demo or small team.
socketio = SocketIO(async_mode="threading", cors_allowed_origins="*")

scheduler = BackgroundScheduler(daemon=True)


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    os.makedirs(app.config["ML_MODEL_DIR"], exist_ok=True)
    os.makedirs(app.config["ML_DATA_DIR"], exist_ok=True)
    os.makedirs(app.config["DASHBOARD_IMG_DIR"], exist_ok=True)

    db.init_app(app)
    login_manager.init_app(app)
    socketio.init_app(app)

    from app.models import User

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    from app.auth import auth_bp
    from app.main import main_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)

    # NOTE: "as _sockets" matters here -- a bare "import app.sockets" would
    # rebind the local `app` variable above to the package, shadowing the
    # Flask instance we just built.
    from app import sockets as _sockets  # noqa: F401 -- registers the Socket.IO chat event handlers

    with app.app_context():
        db.create_all()
        _auto_seed_dataset(app)
        _auto_train_model(app)

    # Start the background jobs (30-day farm re-check, live weather refresh).
    # guard against re-adding jobs on the Flask debug reloader's second process.
    if not scheduler.running:
        from app.scheduler_jobs import register_jobs
        register_jobs(app, scheduler)
        scheduler.start()

    return app


def _auto_seed_dataset(app):
    """
    On a completely fresh database (no zones yet), automatically load the
    bundled real dataset so the map/dashboard/home page show real data the
    first time the app runs -- instead of an empty map with nothing on it.
    Safe to call every startup: it only does anything when Zone is empty.
    """
    from app.models import Zone
    if Zone.query.first() is not None:
        return

    from app.ml import data_loader
    candidates = [
        os.path.join(app.config["ML_DATA_DIR"], "drought_stress_dataset_32wk.json"),
        os.path.join(app.config["ML_DATA_DIR"], "drought_stress_dataset_12wk.json"),
    ]
    for path in candidates:
        if os.path.exists(path):
            try:
                data_loader.load_rich_dataset(path)
                app.logger.info(f"Auto-seeded drought dataset from {path}")
            except Exception as exc:  # pragma: no cover -- seeding must never crash startup
                app.logger.warning(f"Could not auto-seed dataset from {path}: {exc}")
            return


def _auto_train_model(app):
    """
    Trains the ML model automatically on whatever data is present (the
    real forecast dataset by default, once auto-seeded) so the Dashboard's
    evaluation charts are populated the first time the app runs -- no
    farmer upload or manual "Train model" click required. Re-training
    later (e.g. after uploading new data) is still available from the
    Data & Model page.
    """
    from app.ml.train_model import train_and_evaluate
    try:
        result = train_and_evaluate(app)
        if result.get("status") == "ok":
            app.logger.info(f"Auto-trained model on {result['data_source']} ({result['rows_used']} rows)")
    except Exception as exc:  # pragma: no cover -- training must never crash startup
        app.logger.warning(f"Could not auto-train model: {exc}")
