"""Per-prediction RUL explanation by sensor-group substitution (model-agnostic).

For each sensor, every feature derived from it is replaced by the healthy-reference value
(median over training rows whose raw RUL >= 125) and the model is re-queried. The change in
prediction is that sensor's contribution.
"""

import hashlib
import json
import numpy as np
from app.train import ROOT
from app.prognostics import SENSORS, CAP, load, features

CAVEAT = "Counterfactual sensitivity of the model, not a physical root-cause diagnosis."
REFERENCE_PATH = ROOT / "models/explain_reference.json"

SENSOR_INFO = {
    "sensor_2": ("T24", "Total temperature at LPC outlet", "degR", "LPC"),
    "sensor_3": ("T30", "Total temperature at HPC outlet", "degR", "HPC"),
    "sensor_4": ("T50", "Total temperature at LPT outlet", "degR", "LPT"),
    "sensor_7": ("P30", "Total pressure at HPC outlet", "psia", "HPC"),
    "sensor_8": ("Nf", "Physical fan speed", "rpm", "Fan"),
    "sensor_9": ("Nc", "Physical core speed", "rpm", "Fan"),
    "sensor_11": ("Ps30", "Static pressure at HPC outlet", "psia", "HPC"),
    "sensor_12": ("phi", "Ratio of fuel flow to Ps30", "pps/psi", "Combustor"),
    "sensor_13": ("NRf", "Corrected fan speed", "rpm", "Fan"),
    "sensor_14": ("NRc", "Corrected core speed", "rpm", "HPC"),
    "sensor_15": ("BPR", "Bypass ratio", "-", "Fan"),
    "sensor_17": ("htBleed", "Bleed enthalpy", "-", "HPC"),
    "sensor_20": ("W31", "HPT coolant bleed", "lbm/s", "HPT"),
    "sensor_21": ("W32", "LPT coolant bleed", "lbm/s", "LPT"),
}
# Subsystem corrections: core speed (Nc) is a core/HPC shaft quantity.
SENSOR_INFO["sensor_9"] = ("Nc", "Physical core speed", "rpm", "HPC")

_cache = {}


def sensor_columns(sensor, columns):
    """Columns derived from one sensor. Exact prefix `sensor_` + `_` so sensor_2 != sensor_20."""
    prefix = sensor + "_"
    return [c for c in columns if c.startswith(prefix)]


def build(path=REFERENCE_PATH):
    """Compute the healthy reference from FD001 training features and save it."""
    from app.artifacts import atomic_json

    df = load("train_FD001.txt")
    life = df.groupby("engine_id").cycle.max()
    raw = df.engine_id.map(life) - df.cycle
    feats = features(df, bundle()["feature_set"])
    healthy = feats[(raw >= CAP).to_numpy()]
    ref = {c: float(healthy[c].median()) for c in bundle()["feature_columns"]}
    atomic_json(path, {"rows": int(len(healthy)), "rule": "raw RUL >= 125", "reference": ref})
    return ref


def bundle():
    if "bundle" not in _cache:
        import joblib

        _cache["bundle"] = joblib.load(ROOT / "models/prognostics.joblib")
    return _cache["bundle"]


def fingerprint():
    if "fp" not in _cache:
        h = hashlib.sha256((ROOT / "models/prognostics.joblib").read_bytes()).hexdigest()[:12]
        _cache["fp"] = "FD001 / " + h
    return _cache["fp"]


def reference():
    if "ref" not in _cache:
        ref = None
        try:
            ref = json.loads(REFERENCE_PATH.read_text())["reference"]
        except (OSError, ValueError, KeyError):
            pass
        if ref is None or set(ref) != set(bundle()["feature_columns"]):
            try:
                ref = build()
            except OSError:
                ref = None
            if ref is None:
                ref = build_in_memory()
        _cache["ref"] = ref
    return _cache["ref"]


def build_in_memory():
    df = load("train_FD001.txt")
    life = df.groupby("engine_id").cycle.max()
    raw = df.engine_id.map(life) - df.cycle
    feats = features(df, bundle()["feature_set"])
    healthy = feats[(raw >= CAP).to_numpy()]
    return {c: float(healthy[c].median()) for c in bundle()["feature_columns"]}


def _predict(model, row):
    return float(np.clip(model.predict(row), 0, CAP)[0])


def explain_row(model, feature_row, feature_columns, ref=None):
    ref = reference() if ref is None else ref
    row = feature_row[feature_columns].reset_index(drop=True)
    base = _predict(model, row)
    out = []
    for s in SENSORS:
        cols = sensor_columns(s, feature_columns)
        cf = row.copy()
        for c in cols:
            cf[c] = ref[c]
        symbol, name, unit, subsystem = SENSOR_INFO[s]
        out.append(
            {
                "sensor": s,
                "symbol": symbol,
                "name": name,
                "unit": unit,
                "subsystem": subsystem,
                "contribution_cycles": base - _predict(model, cf),
                "drift": float(row[s + "_drift"].iloc[0]) if s + "_drift" in row else None,
                "trend": float(row[s + "_slope30"].iloc[0]) if s + "_slope30" in row else None,
            }
        )
    healthy_row = row.copy()
    for c in feature_columns:
        if c.split("_")[0] == "sensor":
            healthy_row[c] = ref[c]
    out.sort(key=lambda d: d["contribution_cycles"])
    return {
        "base_prediction": base,
        "all_healthy_prediction": _predict(model, healthy_row),
        "drivers": out,
        "caveat": CAVEAT,
        "method": "Sensor-group substitution with FD001 healthy reference (raw RUL >= 125)",
    }


def explain_engine_at(df_engine, cycle=None):
    b = bundle()
    df = df_engine.sort_values("cycle").reset_index(drop=True)
    feats = features(df, b["feature_set"])[b["feature_columns"]]
    if cycle is None:
        i = len(df) - 1
    else:
        hit = np.flatnonzero(df.cycle.to_numpy() == cycle)
        if not len(hit):
            raise ValueError("cycle not observed")
        i = int(hit[0])
    res = explain_row(b["model"], feats.iloc[[i]], b["feature_columns"])
    res["cycle"] = int(df.cycle.iloc[i])
    res["engine_id"] = int(df.engine_id.iloc[0])
    res["model_version"] = fingerprint()
    return res


def explain_engine(df_engine):
    return explain_engine_at(df_engine, None)
