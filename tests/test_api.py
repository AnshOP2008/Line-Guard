from fastapi.testclient import TestClient
from app.main import app
from app.train import ROOT, FEATURES
import pandas as pd

client = TestClient(app)


def test_health_and_metrics_contract():
    assert client.get("/api/health").json()["status"] == "ready"
    r = client.get("/api/metrics").json()
    assert len(r["features"]) == 8
    assert all("anomaly" not in f and "datetime" not in f for f in r["features"])
    roles = [r["role"] for r in r["manifest"]]
    assert roles == sorted(roles, key=lambda r: ["train", "calibration", "test"].index(r))
    assert (
        roles.count("train") == 21 and roles.count("calibration") == 7 and roles.count("test") == 7
    )
    train_end = max(x["end"] for x in r["manifest"] if x["role"] == "train")
    cal_start = min(x["start"] for x in r["manifest"] if x["role"] == "calibration")
    cal_end = max(x["end"] for x in r["manifest"] if x["role"] == "calibration")
    test_start = min(x["start"] for x in r["manifest"] if x["role"] == "test")
    assert train_end < cal_start and cal_end < test_start
    assert r["methods"][r["primary"]]["events"] == 7


def test_recorded_and_simulated_are_distinct():
    recorded = client.get("/api/scenario/recorded").json()
    assert recorded["kind"] == "recorded" and len(recorded["points"]) > 20
    injected = client.get("/api/scenario/flatline").json()
    assert injected["kind"] == "simulated" and injected["injection"]["start"] == 150
    assert all(p["label"] is None for p in injected["points"])
    assert any(p["sensor_flags"]["sensor_suspect"] for p in injected["points"][160:295])
    assert len(injected["points"][200]["expected"]) == 8


def test_csv_validation_and_label_exclusion():
    source = pd.read_csv(ROOT / "data/sample_stream.csv")
    source["anomaly"] = 1
    good = client.post(
        "/api/upload", files={"file": ("test.csv", source.to_csv(index=False).encode(), "text/csv")}
    )
    assert good.status_code == 200
    assert "anomaly" in good.json()["ignored_columns"]
    assert all(p["label"] is None for p in good.json()["points"])
    bad = source.copy()
    bad.loc[0, FEATURES[0]] = float("nan")
    assert (
        client.post(
            "/api/upload", files={"file": ("bad.csv", bad.to_csv(index=False).encode())}
        ).status_code
        == 422
    )
    assert client.post("/api/upload", files={"file": ("bad.csv", b"x,y\n1,2")}).status_code == 422
    duplicate = source.copy()
    duplicate.loc[1, "datetime"] = duplicate.loc[0, "datetime"]
    assert (
        client.post(
            "/api/upload", files={"file": ("bad.csv", duplicate.to_csv(index=False).encode())}
        ).status_code
        == 422
    )


def test_feedback_persists_and_escapes_are_data(tmp_path, monkeypatch):
    import app.main as main

    monkeypatch.setattr(main, "DB", tmp_path / "feedback.sqlite3")
    result = client.post(
        "/api/feedback",
        json={
            "source": "<script>test</script>",
            "sample": 3,
            "verdict": "False alarm",
            "note": "Check current sensor",
        },
    )
    assert result.status_code == 201
    data = client.get("/api/feedback").json()
    assert data[0]["source"] == "<script>test</script>"
    assert (
        client.post(
            "/api/feedback", json={"source": "test", "sample": 0, "verdict": "bad"}
        ).status_code
        == 422
    )


def test_path_traversal_rejected():
    assert (
        client.get("/api/run", params={"name": "../../models/lineguard.joblib"}).status_code == 404
    )


def test_event_metrics_preserve_misses_and_delays():
    import numpy as np
    from app.train import evaluate

    times = pd.Series(pd.date_range("2000-01-01", periods=12, freq="s"))
    truth = np.array([0, 0, 1, 1, 1, 0, 0, 0, 1, 1, 0, 0])
    alarm = np.array([1, 0, 0, 1, 1, 0, 0, 0, 0, 0, 0, 1], dtype=bool)
    result = evaluate(truth, alarm, times)
    assert result["events"] == 2 and result["detected_events"] == 1
    assert result["alarm_events"] == 3 and result["true_alarm_events"] == 1
    assert result["delays_s"] == [1.0]
    assert result["false_positive_points"] == 2
