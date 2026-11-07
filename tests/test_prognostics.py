import numpy as np
import pandas as pd
from fastapi.testclient import TestClient
from app.main import app
from app.prognostics import load, features

client = TestClient(app)


def test_groups_and_official_endpoint_metrics():
    r = client.get("/api/prognostics").json()
    folds = [set(f) for f in r["cv_folds"]]
    assert len(folds) == 5 and set().union(*folds) == set(range(1, 101))
    assert sum(len(f) for f in folds) == 100  # every engine held out exactly once
    assert 0 < r["interval"]["test_coverage"] <= 1
    assert len(r["engine_predictions"]) == 100
    assert r["test"][r["selected_model"]]["mae"] < r["test"]["Age-only baseline"]["mae"]
    for h in r["horizons"]:
        assert h["tp"] + h["fp"] + h["fn"] + h["tn"] == 100
    engine = client.get("/api/prognostics/engine/1").json()
    assert np.isclose(engine["predicted_rul"], r["engine_predictions"][0]["predicted_rul"])
    assert engine["actual_rul"] == r["engine_predictions"][0]["actual_rul"]
    assert engine["points"][0]["actual_rul"] == engine["actual_rul"] + engine["observed_cycles"] - 1
    assert client.get("/api/prognostics/engine/101").status_code == 404


def test_features_never_use_future_cycles_or_other_engines():
    df = load("test_FD001.txt")
    one = df[df.engine_id == 1]
    full = features(one)
    prefix = features(one.head(20))
    pd.testing.assert_frame_equal(full.iloc[:20], prefix)
    mixed = features(df[df.engine_id.isin([1, 2])])
    pd.testing.assert_frame_equal(full, mixed.loc[one.index])
    assert not any(c in full.columns for c in ["engine_id", "rul", "actual_rul"])


def test_separate_engine_upload_ignores_truth_and_rejects_bad_cycles():
    df = load("test_FD001.txt").query("engine_id == 1")
    df["actual_rul"] = 999
    response = client.post(
        "/api/prognostics/upload", files={"file": ("engine.csv", df.to_csv(index=False).encode())}
    )
    assert response.status_code == 200
    r = response.json()
    assert r["actual_rul"] is None and all(p["actual_rul"] is None for p in r["points"])
    assert "actual_rul" in r["ignored_columns"]
    assert (
        client.post(
            "/api/prognostics/upload", files={"file": ("bad.csv", b"Current,cycle\n2,1")}
        ).status_code
        == 422
    )
    invalid = df.copy()
    invalid.loc[invalid.index[1], "cycle"] = 1
    assert (
        client.post(
            "/api/prognostics/upload",
            files={"file": ("bad.csv", invalid.to_csv(index=False).encode())},
        ).status_code
        == 422
    )
    lines = df.to_csv(index=False).splitlines()
    lines[1] += ",unexpected"
    assert (
        client.post(
            "/api/prognostics/upload", files={"file": ("bad.csv", "\n".join(lines).encode())}
        ).status_code
        == 422
    )
    invalid = df.drop(df.index[3])
    assert (
        client.post(
            "/api/prognostics/upload",
            files={"file": ("bad.csv", invalid.to_csv(index=False).encode())},
        ).status_code
        == 422
    )
