"""Bounded exploratory diagnostics. Never selects a replacement using test results."""

import json
import joblib
import numpy as np
import pandas as pd
from app.train import ROOT, FEATURES, segments
from app.prognostics import load, features, horizon_metrics
from app.alerting import grouped_alerts


def calibration_experiment():
    model = joblib.load(ROOT / "models/lineguard.joblib")
    report = json.loads((ROOT / "models/lineguard_metrics.json").read_text())
    runs = [r["run"] for r in report["manifest"] if r["role"] == "calibration"]
    frames = [pd.read_csv(ROOT / "data/SKAB/data" / name, sep=";") for name in runs]
    # Fixed small experiment: first three calibration runs fit thresholds;
    # last four evaluate. The fitted detector has seen none of these runs.
    reference = [model.scores(frame.loc[frame.anomaly == 0, FEATURES]) for frame in frames[:3]]
    thresholds = {
        "Pooled normal 99th percentile": float(np.quantile(np.concatenate(reference), 0.99)),
        "Conservative runwise 99th percentile": float(max(np.quantile(x, 0.99) for x in reference)),
    }
    results = []
    for name, threshold in thresholds.items():
        false_seconds = normal_seconds = 0.0
        hits = events = 0
        delays = []
        per_run = []
        for run, frame in zip(runs[3:], frames[3:]):
            seconds = (
                (pd.to_datetime(frame.datetime) - pd.to_datetime(frame.datetime.iloc[0]))
                .dt.total_seconds()
                .to_numpy()
            )
            weights = np.r_[np.where(np.diff(seconds) <= 1.5, np.diff(seconds), 0), 0]
            alarm = grouped_alerts(model.scores(frame[FEATURES]) / threshold, seconds)
            labels = frame.anomaly.to_numpy() != 0
            f = float(weights[alarm & ~labels].sum())
            n = float(weights[~labels].sum())
            false_seconds += f
            normal_seconds += n
            for start, end in segments(labels):
                events += 1
                matches = np.flatnonzero(alarm[start:end])
                if len(matches):
                    hits += 1
                    delays.append(float(seconds[start + matches[0]] - seconds[start]))
            per_run.append({"run": run, "false_alarm_seconds": f, "normal_seconds": n})
        results.append(
            {
                "candidate": name,
                "threshold": threshold,
                "events": events,
                "hits": hits,
                "false_alarm_seconds": false_seconds,
                "normal_seconds": normal_seconds,
                "normal_time_alarm_rate": false_seconds / max(normal_seconds, 1),
                "median_detected_delay_s": float(np.median(delays)) if delays else None,
                "per_run": per_run,
            }
        )
    return {
        "threshold_fit_runs": runs[:3],
        "development_evaluation_runs": runs[3:],
        "candidates": results,
        "decision": "Keep the existing detector and threshold. This small development comparison does not establish deployment calibration or justify a new test claim.",
        "protocol": "Two fixed threshold candidates, fitted on the first three chronological calibration runs and evaluated on the final four. Detector fitted on earlier training runs only. No test runs used. Exploratory analysis added after the original test had been inspected; requires independent replication.",
    }


def forecast_cutoffs():
    bundle = joblib.load(ROOT / "models/prognostics.joblib")
    frame = load("test_FD001.txt")
    truth = pd.read_csv(ROOT / "data/CMAPSS/FD001/RUL_FD001.txt", header=None)[0].to_numpy()
    predictions = np.clip(
        bundle["model"].predict(
            features(frame, bundle.get("feature_set", "trailing"))[bundle["feature_columns"]]
        ),
        0,
        125,
    )
    rows = []
    for fraction in [0.5, 0.75, 1.0]:
        actual = []
        pred = []
        persistent = []
        for engine, group in frame.groupby("engine_id"):
            index = max(0, int(np.ceil(len(group) * fraction)) - 1)
            selected = group.iloc[index]
            actual.append(float(truth[int(engine) - 1] + group.cycle.iloc[-1] - selected.cycle))
            p = predictions[group.index.to_numpy()[: index + 1]]
            pred.append(float(p[-1]))
            persistent.append(bool(len(p) >= 3 and np.all(p[-3:] <= 30)))
        actual = np.array(actual)
        pred = np.array(pred)
        outside = actual > 30
        rows.append(
            {
                "observed_fraction": fraction,
                "engines": len(actual),
                "mae_cycles": float(np.abs(actual - pred).mean()),
                "horizon_30": horizon_metrics(actual, pred, 30),
                "persistent_false_early_warnings": int((np.array(persistent) & outside).sum()),
                "persistent_hits": int((np.array(persistent) & ~outside).sum()),
            }
        )
    return {
        "protocol": "Retrospective diagnostic at fixed 50%, 75%, 100% of each available test trajectory, one observation per engine per cutoff. Uncapped actual RUL; causal feature windows. A persistent warning is three successive predictions at or below 30 cycles. Previously inspected test; no new model selection or independent performance claim.",
        "cutoffs": rows,
    }


if __name__ == "__main__":
    from app.artifacts import atomic_json

    atomic_json(
        ROOT / "models/research_evidence.json",
        {"calibration": calibration_experiment(), "forecast": forecast_cutoffs()},
    )
