"""Reproducible, normal-only SKAB anomaly benchmark. No anomaly labels enter fitting."""

from pathlib import Path
import json, hashlib
import numpy as np
import pandas as pd
from sklearn.ensemble import ExtraTreesRegressor
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import precision_score, recall_score, average_precision_score

ROOT = Path(__file__).resolve().parents[1]
FEATURES = [
    "Accelerometer1RMS",
    "Accelerometer2RMS",
    "Current",
    "Pressure",
    "Temperature",
    "Thermocouple",
    "Voltage",
    "Volume Flow RateRMS",
]
UNITS = ["g", "g", "A", "bar", "°C", "°C", "V", "L/min"]
NAMES = [
    "Vibration · drive",
    "Vibration · pump",
    "Motor current",
    "Loop pressure",
    "Motor temperature",
    "Fluid temperature",
    "Motor voltage",
    "Flow rate",
]


class RelationshipModel:
    def fit(self, X):
        self.scaler = StandardScaler().fit(X)
        z = self.scaler.transform(X)
        self.models = []
        for j in range(8):
            m = ExtraTreesRegressor(
                n_estimators=64, max_depth=10, min_samples_leaf=8, n_jobs=1, random_state=42 + j
            ).fit(np.delete(z, j, 1), z[:, j])
            self.models.append(m)
        r = self.residuals(X)
        self.residual_scale = np.maximum(np.quantile(abs(r), 0.8, axis=0), 0.12)
        self.pca = PCA(n_components=4, random_state=42).fit(z)
        return self

    def residuals(self, X):
        z = self.scaler.transform(X)
        predicted = np.column_stack(
            [m.predict(np.delete(z, j, 1)) for j, m in enumerate(self.models)]
        )
        return z - predicted

    def scores(self, X, method="Cross-sensor residual"):
        z = self.scaler.transform(X)
        if method == "Cross-sensor residual":
            return np.mean(
                np.sort(abs(self.residuals(X)) / self.residual_scale, axis=1)[:, -3:], axis=1
            )
        if method == "PCA reconstruction":
            return np.mean((z - self.pca.inverse_transform(self.pca.transform(z))) ** 2, axis=1)
        return np.max(abs(pd.DataFrame(z).rolling(5, min_periods=1).mean().to_numpy()), axis=1)

    def explain(self, X):
        z = self.scaler.transform(X)
        residual = self.residuals(X)
        expected = (z - residual) * self.scaler.scale_ + self.scaler.mean_
        return abs(residual) / self.residual_scale, expected


def segments(a):
    a = np.asarray(a, dtype=bool)
    d = np.diff(np.r_[False, a, False].astype(int))
    return list(zip(np.where(d == 1)[0], np.where(d == -1)[0]))


def evaluate(y, alarm, times):
    truth = segments(y)
    detected = segments(alarm)
    hit = sum(any(alarm[s:e]) for s, e in truth)
    true_alerts = sum(any(y[s:e]) for s, e in detected)
    delay = []
    for s, e in truth:
        found = np.where(alarm[s:e])[0]
        if len(found):
            delay.append(float((times.iloc[s + found[0]] - times.iloc[s]).total_seconds()))
    return {
        "point_precision": float(precision_score(y, alarm, zero_division=0)),
        "point_recall": float(recall_score(y, alarm, zero_division=0)),
        "events": len(truth),
        "detected_events": hit,
        "alarm_events": len(detected),
        "true_alarm_events": true_alerts,
        "delays_s": delay,
        "normal_points": int((y == 0).sum()),
        "false_positive_points": int(((y == 0) & alarm).sum()),
    }


def train():
    paths = list((ROOT / "data/SKAB/data").glob("*/*.csv"))
    train = []
    cal = []
    test = []
    manifest = []
    loaded = []
    for p in paths:
        df = pd.read_csv(p, sep=";")
        df["datetime"] = pd.to_datetime(df["datetime"])
        df = df.sort_values("datetime").reset_index(drop=True)
        if "anomaly" not in df:
            df["anomaly"] = 0
        loaded.append((p, df))
    loaded.sort(key=lambda item: item[1].datetime.iloc[0])
    n = len(loaded)
    a = int(n * 0.6)
    b = int(n * 0.8)
    for i, (p, df) in enumerate(loaded):
        role = "train" if i < a else "calibration" if i < b else "test"
        clean = df.loc[df.anomaly == 0, FEATURES]
        if role == "train":
            train.append(clean)
        elif role == "calibration":
            for start, end in segments(df.anomaly.to_numpy() == 0):
                cal.append(df.iloc[start:end][FEATURES])
        else:
            test.append(
                (p.relative_to(ROOT / "data/SKAB/data").as_posix(), df.reset_index(drop=True))
            )
        manifest.append(
            {
                "run": p.relative_to(ROOT / "data/SKAB/data").as_posix(),
                "role": role,
                "normal_points": len(clean),
                "total_points": len(df),
                "start": str(df.datetime.iloc[0]),
                "end": str(df.datetime.iloc[-1]),
                "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
            }
        )
    X = pd.concat(train, ignore_index=True)
    C = pd.concat(cal, ignore_index=True)
    model = RelationshipModel().fit(X)
    methods = {}
    thresholds = {}
    target = 0.01
    for method in ["Rolling z baseline", "PCA reconstruction", "Cross-sensor residual"]:
        cs = np.concatenate([model.scores(chunk, method) for chunk in cal])
        threshold = float(np.quantile(cs, 1 - target, method="higher"))
        thresholds[method] = threshold
        results = []
        scores = []
        ys = []
        for run, df in test:
            s = model.scores(df[FEATURES], method)
            y = df.anomaly.to_numpy().astype(int)
            results.append({"run": run, **evaluate(y, s > threshold, df.datetime)})
            scores.extend(s)
            ys.extend(y)
        n = sum(r["normal_points"] for r in results)
        fp = sum(r["false_positive_points"] for r in results)
        events = sum(r["events"] for r in results)
        alarms = sum(r["alarm_events"] for r in results)
        delays = [v for r in results for v in r["delays_s"]]
        methods[method] = {
            "threshold": threshold,
            "calibration_fpr": float((cs > threshold).mean()),
            "test_point_precision": float(
                precision_score(ys, np.array(scores) > threshold, zero_division=0)
            ),
            "test_point_recall": float(
                recall_score(ys, np.array(scores) > threshold, zero_division=0)
            ),
            "test_pr_auc": float(average_precision_score(ys, scores)),
            "test_normal_fpr": fp / n,
            "event_recall": sum(r["detected_events"] for r in results) / events,
            "event_precision": sum(r["true_alarm_events"] for r in results) / max(alarms, 1),
            "median_detection_delay_s": float(np.median(delays)) if delays else None,
            "events": events,
            "detected_events": sum(r["detected_events"] for r in results),
            "alarm_events": alarms,
            "per_run": results,
        }
    # Primary relationship detector is predeclared; test results are descriptive, never selection criteria.
    model.thresholds = thresholds
    model.threshold = thresholds["Cross-sensor residual"]
    base = test[0][1][FEATURES].iloc[:160].copy()
    # Use normal-only held-out segment for reproducible stress tests.
    normal = (
        pd.concat([d.loc[d.anomaly == 0, FEATURES] for _, d in test], ignore_index=True)
        .iloc[:600]
        .copy()
    )
    injections = {}
    for kind in ["spike", "drift", "flatline"]:
        xx = normal.copy()
        j = 2
        start = 200
        end = 400
        if kind == "spike":
            xx.iloc[start:end:10, j] += model.scaler.scale_[j] * 8
        if kind == "drift":
            xx.iloc[start:end, j] += np.linspace(0, model.scaler.scale_[j] * 8, end - start)
        if kind == "flatline":
            xx.iloc[start:end, j] = xx.iloc[start, j]
        score = model.scores(xx)
        evidence, _ = model.explain(xx)
        flag = sensor_flags(xx, model.scaler.scale_)
        target_idx = np.arange(start, end)
        target_idx = target_idx[::10] if kind == "spike" else target_idx
        injections[kind] = {
            "injected_sensor": FEATURES[j],
            "start": start,
            "end": end,
            "anomaly_detection_rate": float((score[target_idx] > model.threshold).mean()),
            "sensor_heuristic_rate": float(
                np.array([f["sensor_suspect"] for f in flag])[target_idx].mean()
            ),
            "top_sensor_attribution_rate": float((evidence[target_idx].argmax(axis=1) == j).mean()),
            "note": "Synthetic injection into held-out normal tail; diagnostic heuristic, not sensor-fault classifier.",
        }
    # Ablation evaluates missing sensor sensitivity by replacing it with training mean; no refit.
    ablation = []
    merged = pd.concat([d for _, d in test], ignore_index=True)
    y = merged.anomaly.to_numpy().astype(int)
    for j, c in enumerate(FEATURES):
        xx = merged[FEATURES].copy()
        xx[c] = model.scaler.mean_[j]
        s = model.scores(xx)
        ablation.append(
            {
                "sensor": c,
                "test_point_recall": float(recall_score(y, s > model.threshold, zero_division=0)),
                "test_normal_fpr": float((s[y == 0] > model.threshold).mean()),
            }
        )
    report = {
        "primary": "Cross-sensor residual",
        "seed": 42,
        "target_point_fpr": target,
        "features": FEATURES,
        "names": NAMES,
        "units": UNITS,
        "train_count": len(X),
        "calibration_count": len(C),
        "test_count": len(merged),
        "train_runs": a,
        "methods": methods,
        "manifest": manifest,
        "injections": injections,
        "ablation": ablation,
        "split_contract": "Entire runs sorted by start timestamp: earliest 60% train, next 20% calibrate, latest 20% test (21/7/7 runs). Only labelled-normal rows in train/calibration are used. No test rows or labels enter fitting or calibration. Labels filter clean data retrospectively. Same physical rig; not independent sites. Distribution shift remains a deployment risk.",
    }
    from app.artifacts import atomic_joblib, atomic_json

    atomic_joblib(ROOT / "models/lineguard.joblib", model)
    atomic_json(ROOT / "models/lineguard_metrics.json", report)
    print(
        json.dumps(
            {k: {a: b for a, b in v.items() if a != "per_run"} for k, v in methods.items()},
            indent=2,
        )
    )


def sensor_flags(X, reference_scale=None):
    arr = np.asarray(X, dtype=float)
    out = []
    delta = np.diff(arr, axis=0, prepend=arr[:1])
    spread = np.maximum(
        np.asarray(reference_scale) if reference_scale is not None else np.std(arr[:20], axis=0),
        1e-8,
    )
    for i in range(len(arr)):
        flat = []
        spikes = []
        if i >= 9:
            flat = [
                FEATURES[j] for j in [0, 1, 2, 4, 5, 6] if np.ptp(arr[i - 9 : i + 1, j]) < 1e-10
            ]
        if i > 0:
            spikes = [FEATURES[j] for j in range(8) if abs(delta[i, j]) > 6 * spread[j]]
        out.append({"sensor_suspect": bool(flat or spikes), "flatline": flat, "spike": spikes})
    return out


if __name__ == "__main__":
    from app.train import train as run_training

    run_training()
