import json
from concurrent.futures import ThreadPoolExecutor
import pandas as pd
from fastapi.testclient import TestClient
import app.main as main
import pytest
from app.alerting import grouped_alerts
from app.evidence import pump_assessment
from app import artifacts

client = TestClient(main.app)


def test_gap_resets_persistence():
    assert grouped_alerts([2, 2, 2, 2, 2, 2], [0, 1, 2, 10, 11, 12]).tolist() == [
        False,
        False,
        True,
        False,
        False,
        True,
    ]
    point = {"sensor_flags": {"sensor_suspect": True}, "grouped_alert": True}
    assert pump_assessment(point, ["Pressure"])["status"] == "Verify data"
    assert (
        pump_assessment(point, ["Sampling gaps reset temporal diagnostics"])["status"]
        == "Sensor check"
    )


def test_server_snapshot_identity_and_lifecycle(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB", tmp_path / "tasks.sqlite3")
    assert client.post("/api/tasks", json={"inference_id": "a" * 64, "index": 0}).status_code == 404
    result = client.get("/api/scenario/flatline").json()
    pair = next(
        (i, i + 1)
        for i in range(170, 290)
        if result["points"][i]["finding_id"] == result["points"][i + 1]["finding_id"]
        and result["points"][i]["finding_id"].startswith("event")
    )
    reference = {
        "inference_id": result["inference_id"],
        "index": pair[0],
        "notes": "<b>operator</b>",
    }
    task = client.post("/api/tasks", json=reference).json()
    assert task["verified"] and task["schema_version"] == 2
    assert task["sensor_evidence"] == result["points"][pair[0]]
    assert client.post("/api/tasks", json={**reference, "index": pair[1]}).status_code == 409
    assert client.post("/api/tasks", json={**reference, "index": 9999}).status_code == 422
    assert client.patch(f"/api/tasks/{task['id']}", json={"status": "cancelled"}).status_code == 422
    assert (
        client.patch(
            f"/api/tasks/{task['id']}",
            json={"status": "cancelled", "outcome": "Duplicate inspection elsewhere"},
        ).status_code
        == 200
    )
    report = client.get(f"/api/tasks/{task['id']}/report").text
    assert (
        "cancelled" in report
        and "&lt;b&gt;operator&lt;/b&gt;" in report
        and result["model_version"] in report
    )
    assert client.post("/api/tasks", json=reference).status_code == 201


def test_uploads_do_not_collide_and_cadence_is_reported(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB", tmp_path / "tasks.sqlite3")
    frame = pd.read_csv(main.ROOT / "data/sample_stream.csv")

    def upload(data):
        return client.post(
            "/api/upload", files={"file": ("same.csv", data.to_csv(index=False).encode())}
        )

    first = upload(frame).json()
    frame.loc[:, main.FEATURES[0]] += 0.001
    second = upload(frame).json()
    assert first["asset_id"] != second["asset_id"]
    assert "Sampling gaps reset temporal diagnostics" in first["domain_warnings"]
    frame["datetime"] = pd.date_range("2026-01-01", periods=len(frame), freq="100ms")
    assert upload(frame).status_code == 422
    no_time = upload(frame.drop(columns="datetime")).json()
    assert "Sampling cadence unavailable" in no_time["domain_warnings"]
    assert no_time["points"][-1]["assessment"]["status"] == "Verify data"


def test_concurrent_duplicate_is_one_task(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB", tmp_path / "tasks.sqlite3")
    engine = client.get("/api/prognostics/engine/24").json()
    reference = {"inference_id": engine["inference_id"], "index": 10}
    client.get("/api/tasks")
    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(
            pool.map(lambda _: client.post("/api/tasks", json=reference).status_code, range(2))
        )
    assert sorted(statuses) == [201, 409]


def test_artifact_integrity_and_atomic_failure(tmp_path, monkeypatch):
    (tmp_path / "models").mkdir()
    monkeypatch.setattr(artifacts, "ROOT", tmp_path)
    monkeypatch.setattr(artifacts, "FILES", ["model.json"])
    artifacts.atomic_json(tmp_path / "models/model.json", {"value": 1})
    artifacts.atomic_json(
        tmp_path / "models/manifest.json",
        {
            "schema": 1,
            "sha256": artifacts.fingerprints(),
            "sources": artifacts.source_fingerprints(),
        },
    )
    assert artifacts.verify()
    (tmp_path / "models/model.json").write_text("changed")
    assert not artifacts.verify()
    target = tmp_path / "models/preserve.json"
    artifacts.atomic_json(target, {"good": True})
    try:
        artifacts.atomic_json(target, {"bad": float("nan")})
    except ValueError:
        pass
    assert json.loads(target.read_text()) == {"good": True}
    assert not list((tmp_path / "models").glob("*.tmp"))


def test_launcher_rejects_foreign_port_and_stale_build(monkeypatch):
    from app import launch

    monkeypatch.setattr(launch, "port_in_use", lambda: True)
    monkeypatch.setattr(launch, "lineguard_ready", lambda: False)
    with pytest.raises(SystemExit, match="another service"):
        launch.main()
    monkeypatch.setattr(launch, "lineguard_ready", lambda: True)
    import io

    monkeypatch.setattr(
        launch.urllib.request,
        "urlopen",
        lambda *args, **kwargs: io.BytesIO(b'{"build_version":"old"}'),
    )
    with pytest.raises(SystemExit, match="older LineGuard"):
        launch.main()


def test_launcher_rejects_incomplete_artifacts(monkeypatch):
    from app import launch

    monkeypatch.setattr(launch, "port_in_use", lambda: False)
    monkeypatch.setattr(launch, "verify", lambda: False)
    with pytest.raises(SystemExit, match="manifest"):
        launch.main()
