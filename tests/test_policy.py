import json
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app import policy
from app.policy_api import router
from app.prognostics import CAP
from app.train import ROOT


@pytest.fixture(scope="module")
def oof():
    return json.loads((ROOT / "models/policy_oof.json").read_text())


def test_each_engine_once_full_trajectory(oof):
    ids = [e["engine_id"] for e in oof["engines"]]
    assert sorted(ids) == list(range(1, 101))
    for e in oof["engines"]:
        assert len(e["pred"]) == len(e["low"]) == e["failure_cycle"]
        assert 0 <= min(e["pred"]) and max(e["pred"]) <= CAP


def test_no_trigger_equals_run_to_failure(oof):
    assert policy.simulate(oof, -1)["failures"] == 100
    a, b = policy.simulate(oof, -1), policy.run_to_failure(oof)
    for k in ["failures", "preventive", "total_cost", "cost_per_1000_cycles", "life_utilisation"]:
        assert a[k] == b[k]


def test_predictive_beats_run_to_failure(oof):
    rtf = policy.run_to_failure(oof)
    best = policy.best_threshold(oof)
    assert best["cost_per_1000_cycles"] < rtf["cost_per_1000_cycles"]


def test_oof_is_out_of_fold(oof):
    metrics = json.loads((ROOT / "models/prognostics_metrics.json").read_text())
    folds = metrics["cv_folds"]
    assert sorted(e["engine_id"] for e in oof["engines"]) == list(range(1, 101))
    for e in oof["engines"]:
        assert e["engine_id"] in folds[e["fold"]]


def test_compare_uses_disjoint_tuning_and_evaluation(oof):
    r = policy.compare(1, 10, 0)
    assert (r["tuning_engines"], r["evaluation_engines"]) == (60, 40)
    assert len(r["policies"][2]["per_engine"]) == 40
    assert all(e["engine_id"] in oof_ids(oof, (3, 4)) for e in r["policies"][2]["per_engine"])


def oof_ids(oof, folds):
    return {e["engine_id"] for e in oof["engines"] if e["fold"] in folds}


def test_api_router():
    app = FastAPI()
    app.include_router(router)
    c = TestClient(app)
    r = c.get("/api/policy", params={"cost_failure": 10, "lead": 5})
    assert r.status_code == 200
    body = r.json()
    assert len(body["policies"]) == 3 and "protocol" in body
    assert c.get("/api/policy", params={"lead": 99}).status_code == 422
    assert c.get("/api/policy", params={"cost_preventive": 0}).status_code == 422
    assert c.get("/api/policy", params={"threshold": 500}).status_code == 422
