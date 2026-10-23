from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_user, logout_user, login_required, current_user

from app import db
from app.models import User, Farm, Zone
from app.utils import match_zone_to_location

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/signup", methods=["GET", "POST"])
def signup():
    if current_user.is_authenticated:
        return redirect(url_for("main.home"))

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        surname = request.form.get("surname", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")
        location = request.form.get("location", "").strip()
        farm_name = request.form.get("farm_name", "").strip()
        herd_size = request.form.get("herd_size", "").strip()

        if not all([name, surname, email, password]):
            flash("Please fill in every field.", "warning")
            return render_template("signup.html")

        if password != confirm_password:
            flash("Passwords do not match.", "warning")
            return render_template("signup.html")

        if User.query.filter_by(email=email).first():
            flash("An account with that email already exists. Please log in.", "warning")
            return redirect(url_for("auth.login"))

        user = User(name=name, surname=surname, email=email, location=location or None)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()

        # This platform is for farmers, so their first farm is created right
        # here at signup -- no separate "register as a farmer" step needed.
        # If we can match their location to a known zone, the farm is
        # created immediately; otherwise they can add it from My Farms once
        # they've seen which zones exist.
        farm_created = False
        if farm_name:
            zones = Zone.query.all()
            zone_id = match_zone_to_location(location, zones)
            if zone_id:
                db.session.add(Farm(
                    owner_id=user.id, zone_id=zone_id, name=farm_name,
                    herd_size=int(herd_size) if herd_size.isdigit() else 0,
                ))
                db.session.commit()
                farm_created = True

        login_user(user)
        if farm_created:
            flash(f"Welcome, {user.name} -- your account and {farm_name} are ready.", "success")
        else:
            flash(f"Welcome, {user.name} -- your account is ready.", "success")
        return redirect(url_for("main.home"))

    return render_template("signup.html")


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.home"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        user = User.query.filter_by(email=email).first()
        if user is None or not user.check_password(password):
            flash("Incorrect email or password.", "danger")
            return render_template("login.html")

        login_user(user)
        next_page = request.args.get("next")
        return redirect(next_page or url_for("main.home"))

    return render_template("login.html")


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("auth.login"))
