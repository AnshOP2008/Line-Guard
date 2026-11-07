"""Versioned assessments and server-owned inference evidence."""

import hashlib
import json

POLICY_VERSION = "persistence-3-clear-5-v2"


def digest(value):
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode()).hexdigest()


def pump_assessment(point, warnings):
    blocking_warnings = [
        item for item in warnings if item != "Sampling gaps reset temporal diagnostics"
    ]
    if blocking_warnings:
        return {
            "status": "Verify data",
            "priority": "Routine",
            "reason": "Verify sensor units, cadence and equipment compatibility before inspection planning.",
        }
    if point["sensor_flags"]["sensor_suspect"]:
        return {
            "status": "Sensor check",
            "priority": "Inspect soon",
            "reason": "Inspect wiring and sensor integrity before assigning a machine fault.",
        }
    if point["grouped_alert"]:
        return {
            "status": "Inspect",
            "priority": "Inspect soon",
            "reason": "A persistent relationship change needs an equipment inspection.",
        }
    return {
        "status": "Monitor",
        "priority": "Routine",
        "reason": "Continue monitoring and review raw evidence during scheduled inspection.",
    }


def register_inference(result, profile, model_version, warnings=None):
    from app.main import connect

    warnings = warnings or []
    points = result["points"]
    identity = digest(
        {
            "profile": profile,
            "source": result["source"],
            "points": points,
            "model": model_version,
            "policy": POLICY_VERSION,
            "warnings": warnings,
        }
    )
    result["inference_id"] = identity
    result["model_version"] = model_version
    result["policy_version"] = POLICY_VERSION
    result["domain_warnings"] = warnings
    result["asset_id"] = (
        f"pump:{identity[:16]}"
        if profile == "pump"
        else (
            f"upload-engine:{identity[:16]}"
            if result["actual_rul"] is None
            else f"fd001-test:{result['engine_id']}"
        )
    )
    event_start = None
    for index, point in enumerate(points):
        if profile != "pump":
            continue
        active = point["grouped_alert"] or point["sensor_flags"]["sensor_suspect"]
        if active and event_start is None:
            event_start = index
        if not active:
            event_start = None
        point["finding_id"] = f"event-{event_start}" if active else f"sample-{index}"
        point["assessment"] = pump_assessment(point, warnings)
    with connect() as connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS inference_evidence (
                id TEXT PRIMARY KEY, profile TEXT NOT NULL, payload TEXT NOT NULL
            )
        """)
        connection.execute(
            "INSERT OR IGNORE INTO inference_evidence VALUES (?, ?, ?)",
            (identity, profile, json.dumps(result, allow_nan=False)),
        )
        connection.commit()
    return result


def snapshot(reference):
    from app.main import connect
    from fastapi import HTTPException

    with connect() as connection:
        if not connection.execute(
            "SELECT name FROM sqlite_master WHERE name='inference_evidence'"
        ).fetchone():
            raise HTTPException(404, "Evidence unavailable. Reload the observation.")
        row = connection.execute(
            "SELECT profile, payload FROM inference_evidence WHERE id = ?",
            (reference.inference_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(404, "Evidence unavailable. Reload the observation.")
    evidence = json.loads(row["payload"])
    if reference.index >= len(evidence["points"]):
        raise HTTPException(422, "Observation index is outside this evidence.")
    point = evidence["points"][reference.index]
    history = evidence["points"][max(0, reference.index - 99) : reference.index + 1]
    common = {
        "schema_version": 2,
        "asset_id": evidence["asset_id"],
        "inference_id": reference.inference_id,
        "source": evidence["source"],
        "model_version": evidence["model_version"],
        "policy_version": evidence["policy_version"],
        "quality_warnings": evidence["domain_warnings"],
        "notes": reference.notes,
        "sensor_evidence": point,
        "verified": True,
        "input_window": history[-20:],
    }
    if row["profile"] == "pump":
        return {
            **common,
            "asset": "Pump P–01",
            "observation": f"Sample {point['index']} · {point['time']}",
            "finding_id": point["finding_id"],
            **point["assessment"],
            "reading": f"{point['ratio']:.2f} times threshold",
            "series": [item["ratio"] for item in history],
            "positions": [item["time"] for item in history],
            "unit": "threshold ratio",
            "threshold": evidence["threshold"],
        }
    warning = bool(evidence["domain_warnings"])
    urgent = not warning and point["predicted_rul"] <= reference.horizon
    return {
        **common,
        "asset": ("Uploaded engine " if evidence["actual_rul"] is None else "Turbofan TF–")
        + str(evidence["engine_id"]),
        "observation": f"Observed cycle {point['cycle']}",
        "finding_id": "inspection",
        "reason": (
            "Verify equipment compatibility and units."
            if warning
            else (
                "Review the engine within the planning horizon."
                if urgent
                else "Review the estimate at the next scheduled inspection."
            )
        ),
        "priority": "Inspect soon" if urgent else "Routine",
        "reading": f"{point['predicted_rul']:.1f} cycles remaining · horizon {reference.horizon} cycles",
        "series": [item["predicted_rul"] for item in history],
        "positions": [item["cycle"] for item in history],
        "unit": "operational cycles",
        "horizon": reference.horizon,
    }
