import json, math
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.insights_api import router
from app.explain import sensor_columns, SENSOR_INFO
from app.train import ROOT

app = FastAPI()
app.include_router(router)
client = TestClient(app)
METRICS = json.loads((ROOT / "models/prognostics_metrics.json").read_text())


def test_prefix_logic_does_not_cross_sensors():
    cols = ["sensor_2_ewm", "sensor_20_ewm", "sensor_21_drift", "sensor_2_drift", "cycle"]
    assert sensor_columns("sensor_2", cols) == ["sensor_2_ewm", "sensor_2_drift"]
    assert sensor_columns("sensor_20", cols) == ["sensor_20_ewm"]
    assert sensor_columns("sensor_21", cols) == ["sensor_21_drift"]


def test_explanation_engine_24_matches_app_prediction():
    r = client.get("/api/insights/engine/24/explain")
    assert r.status_code == 200
    body = r.json()
    assert len(body["drivers"]) == 14 == len(SENSOR_INFO)
    assert all(math.isfinite(d["contribution_cycles"]) for d in body["drivers"])
    expected = METRICS["engine_predictions"][23]["predicted_rul"]
    assert abs(body["base_prediction"] - expected) < 1e-6
    assert "not a physical root-cause" in body["caveat"]


def test_substitution_only_changes_target_sensor():
    from app import explain
    from app.prognostics import load, features

    b = explain.bundle()
    df = load("test_FD001.txt").query("engine_id == 24")
    row = features(df, b["feature_set"])[b["feature_columns"]].iloc[[-1]].reset_index(drop=True)
    ref = explain.reference()
    cf = row.copy()
    for c in sensor_columns("sensor_2", b["feature_columns"]):
        cf[c] = ref[c]
    changed = [c for c in row.columns if row[c].iloc[0] != cf[c].iloc[0]]
    assert changed and all(c.startswith("sensor_2_") for c in changed)


def test_explain_bad_inputs():
    assert client.get("/api/insights/engine/0/explain").status_code == 404
    assert client.get("/api/insights/engine/24/explain?cycle=9999").status_code == 404
