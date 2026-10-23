"""
Trains the drought-risk model on whatever data is already in the database
-- no farmer upload required. It prefers the simple uploaded format
(drought_assessments) if at least 20 rows of that exist; otherwise it
trains on the real forecast dataset (forecast_readings), which is always
present once the app has auto-seeded itself. Either way it writes:
  - risk_regressor.joblib          (predicts 0-100 risk score)
  - severity_classifier.joblib     (predicts Low / Moderate / High)
  - metrics.json                   (numbers shown on the dashboard page)
  - static/img/dashboard/*.png     (seaborn charts shown on the dashboard page)

Run standalone with:  python -m app.ml.train_model
Or trigger it from the web app's "Train model" button (see app/main.py),
or automatically at startup (see app/__init__.py's _auto_seed_dataset).
"""
import os
import json

import numpy as np
import pandas as pd
import joblib
import matplotlib
matplotlib.use("Agg")  # no display available on the server
import matplotlib.pyplot as plt
import seaborn as sns
from sklearn.model_selection import train_test_split
from sklearn.metrics import (
    mean_absolute_error, mean_squared_error, r2_score,
    accuracy_score, precision_recall_fscore_support, confusion_matrix,
)
from sklearn.preprocessing import LabelEncoder
from xgboost import XGBRegressor, XGBClassifier

from app.ml.formula import compute_risk_score, severity_from_score

# Feature set for the SIMPLE uploaded format (drought_assessments).
SIMPLE_FEATURE_COLUMNS = [
    "rainfall_mm", "temperature_c", "soil_moisture",
    "ndvi", "water_availability", "historical_drought",
]

# Feature set for the REAL forecast dataset (forecast_readings) -- this is
# what trains automatically with no upload, since it's populated by
# auto-seed. Deliberately excludes grazing_capacity/feed_days/financial
# impact, which are *consequences* of the drought stress index rather than
# independent inputs -- including them would let the model "cheat".
RICH_FEATURE_COLUMNS = [
    "ndvi", "soil_moisture_pct", "rainfall_mm",
    "rainfall_deficit_pct", "temp_anomaly_c", "water_point_level_pct",
]

sns.set_theme(style="whitegrid", palette="deep")


def _build_simple_dataframe():
    from app.models import DroughtAssessment, Zone

    rows = []
    for r in DroughtAssessment.query.join(Zone).all():
        rows.append({
            "zone": r.zone.name,
            "rainfall_mm": r.rainfall_mm,
            "temperature_c": r.temperature_c,
            "soil_moisture": r.soil_moisture,
            "ndvi": r.ndvi,
            "water_availability": r.water_availability,
            "historical_drought": r.historical_drought if r.historical_drought is not None else 0,
            "risk_score": r.risk_score,
            "severity_level": r.severity_level,
        })
    df = pd.DataFrame(rows)
    if df.empty:
        return df

    # Where a reading has no ground-truth label, derive a proxy from the
    # transparent formula so training can still proceed.
    for idx, row in df.iterrows():
        if pd.isna(row["risk_score"]):
            score, _, _ = compute_risk_score(
                rainfall_mm=row["rainfall_mm"], temperature_c=row["temperature_c"],
                soil_moisture=row["soil_moisture"], ndvi=row["ndvi"],
                water_availability=row["water_availability"],
                historical_drought=row["historical_drought"],
            )
            df.at[idx, "risk_score"] = score
        if pd.isna(row["severity_level"]) or row["severity_level"] is None:
            df.at[idx, "severity_level"] = severity_from_score(df.at[idx, "risk_score"])
    return df


def _build_rich_dataframe():
    from app.models import ForecastReading, Zone

    rows = []
    for r in ForecastReading.query.join(Zone).all():
        rows.append({
            "zone": r.zone.name,
            "ndvi": r.ndvi,
            "soil_moisture_pct": r.soil_moisture_pct,
            "rainfall_mm": r.rainfall_mm,
            "rainfall_deficit_pct": r.rainfall_deficit_pct,
            "temp_anomaly_c": r.temp_anomaly_c,
            "water_point_level_pct": r.water_point_level_pct,
            "risk_score": r.drought_stress_index,
        })
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["severity_level"] = df["risk_score"].apply(lambda s: severity_from_score(s) if pd.notna(s) else None)
    return df


def train_and_evaluate(app):
    simple_df = _build_simple_dataframe()
    if len(simple_df) >= 20:
        return _train_pipeline(app, simple_df, SIMPLE_FEATURE_COLUMNS, data_source="simple_uploaded_data")

    rich_df = _build_rich_dataframe()
    if len(rich_df) >= 20:
        return _train_pipeline(app, rich_df, RICH_FEATURE_COLUMNS, data_source="real_forecast_dataset")

    return {
        "status": "not_enough_data",
        "rows_available": len(simple_df) + len(rich_df),
        "message": "Not enough data loaded yet to train on. This should not normally happen "
                   "once the app has auto-seeded its bundled dataset -- check the Data & Model "
                   "page's status, or upload a dataset manually.",
    }


def _train_pipeline(app, df, feature_columns, data_source):
    df[feature_columns] = df[feature_columns].apply(pd.to_numeric, errors="coerce")
    df[feature_columns] = df[feature_columns].fillna(df[feature_columns].median())
    df = df.dropna(subset=["risk_score", "severity_level"])

    X = df[feature_columns]
    y_reg = df["risk_score"].astype(float)

    label_encoder = LabelEncoder()
    y_clf = label_encoder.fit_transform(df["severity_level"].astype(str))

    X_train, X_test, y_reg_train, y_reg_test, y_clf_train, y_clf_test = train_test_split(
        X, y_reg, y_clf, test_size=0.2, random_state=42
    )

    regressor = XGBRegressor(
        n_estimators=200, max_depth=4, learning_rate=0.08,
        subsample=0.9, colsample_bytree=0.9, random_state=42,
    )
    regressor.fit(X_train, y_reg_train)
    reg_pred = regressor.predict(X_test)

    mae = mean_absolute_error(y_reg_test, reg_pred)
    rmse = np.sqrt(mean_squared_error(y_reg_test, reg_pred))
    r2 = r2_score(y_reg_test, reg_pred)

    classifier = XGBClassifier(
        n_estimators=200, max_depth=4, learning_rate=0.08,
        subsample=0.9, colsample_bytree=0.9, random_state=42,
        eval_metric="mlogloss",
    )
    classifier.fit(X_train, y_clf_train)
    clf_pred = classifier.predict(X_test)

    accuracy = accuracy_score(y_clf_test, clf_pred)
    precision, recall, f1, _ = precision_recall_fscore_support(
        y_clf_test, clf_pred, average="weighted", zero_division=0
    )
    cm = confusion_matrix(y_clf_test, clf_pred)
    class_names = label_encoder.classes_.tolist()

    model_dir = app.config["ML_MODEL_DIR"]
    joblib.dump(regressor, os.path.join(model_dir, "risk_regressor.joblib"))
    joblib.dump(classifier, os.path.join(model_dir, "severity_classifier.joblib"))
    joblib.dump(label_encoder, os.path.join(model_dir, "label_encoder.joblib"))

    metrics = {
        "data_source": data_source,
        "rows_used": len(df),
        "zones_used": df["zone"].nunique(),
        "regression": {"mae": round(mae, 2), "rmse": round(rmse, 2), "r2": round(r2, 3)},
        "classification": {
            "accuracy": round(accuracy, 3),
            "precision": round(precision, 3),
            "recall": round(recall, 3),
            "f1": round(f1, 3),
            "classes": class_names,
        },
        "feature_importance": dict(zip(feature_columns, [round(float(v), 3) for v in regressor.feature_importances_])),
    }
    with open(os.path.join(model_dir, "metrics.json"), "w") as f:
        json.dump(metrics, f, indent=2)

    _generate_charts(app, df, feature_columns, cm, class_names, metrics["feature_importance"])

    metrics["status"] = "ok"
    return metrics


def _generate_charts(app, df, feature_columns, confusion_mat, class_names, feature_importance):
    img_dir = app.config["DASHBOARD_IMG_DIR"]

    plt.figure(figsize=(6, 4))
    fi = pd.Series(feature_importance).sort_values()
    sns.barplot(x=fi.values, y=fi.index, color="#8AA366")
    plt.title("What drives the drought stress index")
    plt.xlabel("Relative importance")
    plt.tight_layout()
    plt.savefig(os.path.join(img_dir, "feature_importance.png"), dpi=140)
    plt.close()

    plt.figure(figsize=(5, 4))
    sns.heatmap(confusion_mat, annot=True, fmt="d", cmap="YlOrBr",
                xticklabels=class_names, yticklabels=class_names)
    plt.title("Predicted vs. actual severity")
    plt.xlabel("Predicted")
    plt.ylabel("Actual")
    plt.tight_layout()
    plt.savefig(os.path.join(img_dir, "confusion_matrix.png"), dpi=140)
    plt.close()

    plt.figure(figsize=(6, 4))
    severity_order = [c for c in ["Low", "Moderate", "High"] if c in df["severity_level"].unique()]
    sns.boxplot(data=df, x="severity_level", y="risk_score", hue="severity_level",
                order=severity_order, hue_order=severity_order,
                palette=["#7FAF6A", "#D9A441", "#B5502F"][:len(severity_order)], legend=False)
    plt.title("Risk score spread by severity class")
    plt.tight_layout()
    plt.savefig(os.path.join(img_dir, "risk_by_severity.png"), dpi=140)
    plt.close()

    plt.figure(figsize=(6, 4))
    sns.scatterplot(data=df, x="rainfall_mm", y="ndvi", hue="severity_level",
                     palette={"Low": "#7FAF6A", "Moderate": "#D9A441", "High": "#B5502F"})
    plt.title("Rainfall vs. vegetation health")
    plt.tight_layout()
    plt.savefig(os.path.join(img_dir, "rainfall_vs_ndvi.png"), dpi=140)
    plt.close()

    plt.figure(figsize=(6, 5))
    corr = df[feature_columns + ["risk_score"]].corr()
    sns.heatmap(corr, annot=True, fmt=".2f", cmap="vlag", center=0)
    plt.title("How the inputs relate to each other and to risk")
    plt.tight_layout()
    plt.savefig(os.path.join(img_dir, "correlation_heatmap.png"), dpi=140)
    plt.close()


if __name__ == "__main__":
    from app import create_app
    flask_app = create_app()
    with flask_app.app_context():
        result = train_and_evaluate(flask_app)
        print(json.dumps(result, indent=2))
