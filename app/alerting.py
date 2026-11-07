"""Causal alert policy and retrospective evidence for LineGuard."""

import json
import joblib
import numpy as np
import pandas as pd

from app.train import FEATURES, ROOT, segments
from app.prognostics import SENSORS, load


def grouped_alerts(ratios, seconds=None):
    """Require three high samples to enter and five low samples to clear."""
    active = False
    streak = 0
    alerts = []
    for index, ratio in enumerate(ratios):
        if seconds is not None and index and seconds[index] - seconds[index - 1] > 1.5:
            active, streak = False, 0
        qualifies = ratio < 0.85 if active else ratio > 1
        streak = streak + 1 if qualifies else 0
        if streak == (5 if active else 3):
            active = not active
            streak = 0
        alerts.append(active)
    return np.asarray(alerts, dtype=bool)


def compare():
    model = joblib.load(ROOT / "models/lineguard.joblib")
    report = json.loads((ROOT / "models/lineguard_metrics.json").read_text())
    totals = {
        name: {"events": 0, "hits": 0, "alerts": 0, "false_events": 0, "delay": []}
        for name in ("Raw", "Grouped")
    }
    duration = 0.0
    normal_count = 0
    driver_counts = np.zeros(len(FEATURES), dtype=int)
    reference = {feature: [float("inf"), float("-inf")] for feature in FEATURES}
    runs = []
    event_details = []
    for metrics in totals.values():
        metrics.update(false_alarm_seconds=0.0, alert_seconds=0.0, normal_seconds=0.0)
    for run in report["manifest"]:
        frame = pd.read_csv(ROOT / "data/SKAB/data" / run["run"], sep=";")
        labels = frame.get("anomaly", pd.Series(0, index=frame.index)).to_numpy() != 0
        if run["role"] == "train":
            normal = frame.loc[~labels, FEATURES]
            for feature in FEATURES:
                low, high = reference[feature]
                reference[feature] = [
                    min(low, float(normal[feature].min())),
                    max(high, float(normal[feature].max())),
                ]
        ratios = model.scores(frame[FEATURES]) / model.threshold
        normal = ratios[~labels]
        runs.append(
            {
                "run": run["run"],
                "role": run["role"],
                "median_normal_ratio": float(np.median(normal)),
                "normal_raw_alert_rate": float(np.mean(normal > 1)),
            }
        )
        if run["role"] != "test":
            continue
        seconds = (
            (pd.to_datetime(frame.datetime) - pd.to_datetime(frame.datetime.iloc[0]))
            .dt.total_seconds()
            .to_numpy()
        )
        # Left-sample occupancy, excluding missing telemetry and the final unknown interval.
        weights = np.r_[np.where(np.diff(seconds) <= 1.5, np.diff(seconds), 0), 0]
        duration += weights.sum()
        evidence, _ = model.explain(frame[FEATURES])
        false_points = (~labels) & (ratios > 1)
        normal_count += int(false_points.sum())
        driver_counts += np.bincount(evidence[false_points].argmax(axis=1), minlength=len(FEATURES))
        truth = segments(labels)
        paired = {}
        for name, alarms in (("Raw", ratios > 1), ("Grouped", grouped_alerts(ratios, seconds))):
            metrics = totals[name]
            windows = segments(alarms)
            metrics["events"] += len(truth)
            metrics["alerts"] += len(windows)
            metrics["false_events"] += sum(not labels[start:end].any() for start, end in windows)
            metrics["false_alarm_seconds"] += float(weights[alarms & ~labels].sum())
            metrics["alert_seconds"] += float(weights[alarms].sum())
            metrics["normal_seconds"] += float(weights[~labels].sum())
            paired[name] = []
            for start, end in truth:
                first = np.flatnonzero(alarms[start:end])
                if first.size:
                    metrics["hits"] += 1
                    metrics["delay"].append(float(seconds[start + first[0]] - seconds[start]))
                paired[name].append(
                    float(seconds[start + first[0]] - seconds[start]) if first.size else None
                )
        for index, (start, end) in enumerate(truth):
            event_details.append(
                {
                    "run": run["run"],
                    "start_sample": int(start),
                    "end_sample": int(end),
                    "raw_delay_s": paired["Raw"][index],
                    "grouped_delay_s": paired["Grouped"][index],
                }
            )
    hours = duration / 3600
    for metrics in totals.values():
        delays = metrics.pop("delay")
        metrics["median_delay_seconds"] = float(np.median(delays)) if delays else None
        metrics["false_events_per_observed_hour"] = metrics["false_events"] / hours
        metrics["false_alarm_fraction_of_normal_time"] = metrics["false_alarm_seconds"] / max(
            1, metrics["normal_seconds"]
        )
        metrics["alert_occupancy"] = metrics["alert_seconds"] / duration
        metrics["missed_events"] = metrics["events"] - metrics["hits"]
    common = [
        event
        for event in event_details
        if event["raw_delay_s"] is not None and event["grouped_delay_s"] is not None
    ]
    engine_train = load("train_FD001.txt")
    engine_ranges = {
        name: [float(engine_train[name].min()), float(engine_train[name].max())]
        for name in SENSORS + ["setting_1", "setting_2", "setting_3"]
    }
    return {
        "engine_training_ranges": engine_ranges,
        "observed_hours": hours,
        "policies": totals,
        "run_drift": runs,
        "normal_alert_driver_counts": dict(zip(FEATURES, driver_counts.tolist())),
        "normal_alert_points": normal_count,
        "training_ranges": reference,
        "events": event_details,
        "common_event_delays": {
            "count": len(common),
            "excluded": len(event_details) - len(common),
            "raw_median_s": (
                float(np.median([e["raw_delay_s"] for e in common])) if common else None
            ),
            "grouped_median_s": (
                float(np.median([e["grouped_delay_s"] for e in common])) if common else None
            ),
        },
        "protocol": "Fixed illustrative rule: three successive scores above threshold open an alert. Five below 0.85 times threshold clear it. Gaps above 1.5 seconds reset state; unobserved intervals are excluded from time-based metrics. Exploratory comparison on previously inspected runs. No threshold refit.",
    }


if __name__ == "__main__":
    from app.artifacts import atomic_json

    atomic_json(ROOT / "models/operations_evidence.json", compare())
