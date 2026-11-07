from fastapi.testclient import TestClient

import app.main as main
from app.alerting import grouped_alerts

client = TestClient(main.app)


def test_task_snapshot_and_duplicate_protection(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB", tmp_path / "tasks.sqlite3")
    finding = {
        "asset": "Pump P–01",
        "source": "recorded replay",
        "observation": "sample 200",
        "model_version": "v1",
        "reading": "1.2 times threshold",
        "priority": "Inspect soon",
        "reason": "Review pressure and current",
        "series": [1, 1.1, 1.2],
        "notes": "<script>literal notes</script>",
    }
    saved = client.post("/api/tasks", json=finding)
    assert saved.status_code == 201
    task_id = saved.json()["id"]
    assert client.post("/api/tasks", json={**finding, "reading": "2"}).status_code == 409
    assert (
        client.patch(
            f"/api/tasks/{task_id}", json={"status": "completed", "outcome": "Checked"}
        ).status_code
        == 409
    )
    assert client.patch(f"/api/tasks/{task_id}", json={"status": "acknowledged"}).status_code == 200
    completed = client.patch(
        f"/api/tasks/{task_id}", json={"status": "completed", "outcome": "Checked"}
    )
    assert completed.json()["series"] == finding["series"]
    assert completed.json()["reading"] == finding["reading"]
    report = client.get(f"/api/tasks/{task_id}/report")
    assert "attachment" in report.headers["content-disposition"]
    assert "&lt;script&gt;literal notes&lt;/script&gt;" in report.text
    assert client.post("/api/tasks", json=finding).status_code == 201


def test_grouped_alert_is_causal_and_clears_after_five_low_samples():
    readings = [1.1, 1.2, 1.2, 0.8, 0.8, 0.9, 0.8, 0.8, 0.8, 0.8, 0.8]
    assert grouped_alerts(readings).tolist() == [False, False] + [True] * 8 + [False]
    assert grouped_alerts(readings[:5]).tolist() == [False, False, True, True, True]
