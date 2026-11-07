"""NASA FD001 remaining-useful-life benchmark. Engine groups stay separate."""

import hashlib, json
import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.ensemble import ExtraTreesRegressor, HistGradientBoostingRegressor
from sklearn.metrics import (
    mean_absolute_error,
    mean_squared_error,
    precision_score,
    recall_score,
    confusion_matrix,
)
from app.train import ROOT

DATA = ROOT / "data/CMAPSS/FD001"
COLUMNS = (
    ["engine_id", "cycle"]
    + [f"setting_{i}" for i in range(1, 4)]
    + [f"sensor_{i}" for i in range(1, 22)]
)
SENSORS = [f"sensor_{i}" for i in [2, 3, 4, 7, 8, 9, 11, 12, 13, 14, 15, 17, 20, 21]]
CAP = 125


def load(name):
    return pd.read_csv(DATA / name, sep=r"\s+", header=None, names=COLUMNS)


TREND_WINDOWS = (10, 30)
BASELINE_CYCLES = 15
EWM_ALPHA = 0.1


def trailing_features(df):
    """v1 features: current reading plus trailing 20-cycle mean, std and change."""
    frames = []
    for _, g in df.groupby("engine_id", sort=False):
        g = g.sort_values("cycle")
        z = g[SENSORS].copy()
        z["cycle"] = g.cycle
        for s in SENSORS:
            roll = g[s].rolling(20, min_periods=1)
            z[s + "_mean20"] = roll.mean()
            z[s + "_std20"] = roll.std(ddof=0).fillna(0)
            z[s + "_change20"] = g[s] - g[s].shift(19).fillna(g[s].iloc[0])
        frames.append(z)
    return pd.concat(frames).sort_index()


def drift_features(df):
    """Degradation-drift features. Every value uses only the current and earlier cycles.

    * ``_ewm``: exponentially smoothed reading (noise suppression).
    * ``_drift``: smoothed reading minus this engine's own early-life baseline
      (mean of its first 15 observed cycles; an expanding mean before that).
      This removes engine-to-engine manufacturing offsets, which dominate raw readings.
    * ``_mean{w}`` / ``_slope{w}``: trailing mean and least-squares slope over 10 and 30 cycles.
    """
    frames = []
    for _, g in df.groupby("engine_id", sort=False):
        g = g.sort_values("cycle")
        z = pd.DataFrame(index=g.index)
        z["cycle"] = g.cycle
        t = pd.Series(np.arange(len(g)), index=g.index, dtype=float)
        early = np.arange(len(g)) < BASELINE_CYCLES
        for s in SENSORS:
            x = g[s]
            smooth = x.ewm(alpha=EWM_ALPHA, adjust=True).mean()
            baseline = x.expanding().mean().where(early, x.iloc[:BASELINE_CYCLES].mean())
            z[s + "_ewm"] = smooth
            z[s + "_drift"] = smooth - baseline
            for w in TREND_WINDOWS:
                mean = x.rolling(w, min_periods=2).mean()
                cov = (x * t).rolling(w, min_periods=2).mean() - mean * t.rolling(
                    w, min_periods=2
                ).mean()
                var = t.rolling(w, min_periods=2).var(ddof=0)
                z[f"{s}_mean{w}"] = mean
                z[f"{s}_slope{w}"] = (cov / var).fillna(0)
        frames.append(z)
    return pd.concat(frames).sort_index()


FEATURE_SETS = {"trailing": trailing_features, "drift": drift_features}


def features(df, kind="drift"):
    return FEATURE_SETS[kind](df)


def nasa_score(y, p):
    """PHM08 asymmetric score: late predictions (overestimating life) cost more. Lower is better."""
    d = np.asarray(p, dtype=float) - np.asarray(y, dtype=float)
    return float(np.sum(np.where(d < 0, np.exp(-d / 13) - 1, np.exp(d / 10) - 1)))


def errors(y, p):
    y = np.asarray(y, dtype=float)
    return {
        "mae": float(mean_absolute_error(y, p)),
        "rmse": float(np.sqrt(mean_squared_error(y, p))),
        "rmse_capped_truth": float(np.sqrt(mean_squared_error(np.minimum(y, CAP), p))),
        "nasa_score": nasa_score(y, p),
    }


INTERVAL_BINS = (0, 40, 80, CAP + 1)
COVERAGE = 0.9


def fit_intervals(pred, truth):
    """Split-conformal, Mondrian by predicted-RUL band, from out-of-fold engine residuals."""
    pred, residual = np.asarray(pred), np.asarray(truth) - np.asarray(pred)
    bands = []
    for lo, hi in zip(INTERVAL_BINS, INTERVAL_BINS[1:]):
        r = np.sort(residual[(pred >= lo) & (pred < hi)])
        n = len(r)
        k_lo = max(int(np.floor((n + 1) * (1 - COVERAGE) / 2)) - 1, 0)
        k_hi = min(int(np.ceil((n + 1) * (1 + COVERAGE) / 2)) - 1, n - 1)
        bands.append(
            {"min_pred": lo, "max_pred": hi, "n": n, "low": float(r[k_lo]), "high": float(r[k_hi])}
        )
    return bands


def interval(pred, bands):
    pred = np.atleast_1d(np.asarray(pred, dtype=float))
    low, high = np.empty_like(pred), np.empty_like(pred)
    for b in bands:
        m = (pred >= b["min_pred"]) & (pred < b["max_pred"])
        low[m], high[m] = pred[m] + b["low"], pred[m] + b["high"]
    return np.maximum(low, 0), high


def horizon_metrics(y, p, h):
    truth = np.asarray(y) <= h
    alarm = np.asarray(p) <= h
    tn, fp, fn, tp = confusion_matrix(truth, alarm, labels=[False, True]).ravel()
    return {
        "horizon": h,
        "precision": float(precision_score(truth, alarm, zero_division=0)),
        "recall": float(recall_score(truth, alarm, zero_division=0)),
        "false_positive_rate": float(fp / max(tn + fp, 1)),
        "tp": int(tp),
        "fp": int(fp),
        "fn": int(fn),
        "tn": int(tn),
        "alerts": int(alarm.sum()),
    }


def candidates():
    hgb = dict(
        max_iter=260, max_leaf_nodes=15, l2_regularization=5, learning_rate=0.06, random_state=42
    )
    et = dict(
        n_estimators=200,
        max_depth=14,
        min_samples_leaf=3,
        max_features=0.5,
        n_jobs=-1,
        random_state=42,
    )
    return {
        "Gradient boosting · drift features": ("drift", HistGradientBoostingRegressor(**hgb)),
        "Extra trees · drift features": ("drift", ExtraTreesRegressor(**et)),
        "Gradient boosting · trailing-window features (v1)": (
            "trailing",
            HistGradientBoostingRegressor(**hgb),
        ),
    }


def train():
    df = load("train_FD001.txt")
    test = load("test_FD001.txt")
    truth = pd.read_csv(DATA / "RUL_FD001.txt", header=None)[0].to_numpy()
    life = df.groupby("engine_id").cycle.max()
    raw = df.engine_id.map(life) - df.cycle
    y = raw.clip(upper=CAP)
    frames = {kind: fn(df) for kind, fn in FEATURE_SETS.items()}

    # 5-fold engine-grouped cross-validation. Each held-out engine is truncated at five
    # fixed-seed random cycles, mimicking the official test protocol (trajectories that
    # stop before failure). No engine appears in both the fit and evaluation side of a fold.
    ids = np.arange(1, 101)
    rng = np.random.default_rng(42)
    rng.shuffle(ids)
    folds = [sorted(f.tolist()) for f in np.array_split(ids, 5)]
    cut_rng = np.random.default_rng(43)
    cutoffs = {
        int(i): sorted(int(c) for c in cut_rng.integers(30, int(life[i]), size=5))
        for i in range(1, 101)
    }
    row = {(e, c): ix for ix, e, c in zip(df.index, df.engine_id, df.cycle)}

    validation, oof = {}, {}
    for name, (kind, model) in candidates().items():
        preds, actual = [], []
        for k, held in enumerate(folds):
            fit = ~df.engine_id.isin(held)
            m = clone(model).fit(frames[kind][fit], y[fit])
            idx = [row[(e, c)] for e in held for c in cutoffs[e]]
            preds.append(np.clip(m.predict(frames[kind].loc[idx]), 0, CAP))
            actual.append(raw.loc[idx].to_numpy())
        oof[name] = (np.concatenate(preds), np.concatenate(actual))
        validation[name] = errors(oof[name][1], oof[name][0])
    p_cv, t_cv = next(iter(oof.values()))
    cv_ages = np.array([c for i in range(1, 101) for c in cutoffs[i]])
    median_life = float(life.median())
    validation["Age-only baseline"] = errors(t_cv, np.clip(median_life - cv_ages, 0, CAP))

    selected = min(candidates(), key=lambda n: validation[n]["mae"])
    kind, model = candidates()[selected]
    bands = fit_intervals(*oof[selected])
    model.fit(frames[kind], y)

    FT = FEATURE_SETS[kind](test)
    final_idx = test.groupby("engine_id").tail(1).index
    p = np.clip(model.predict(FT.loc[final_idx]), 0, CAP)
    low, high = interval(p, bands)
    baseline = np.clip(median_life - test.loc[final_idx, "cycle"].to_numpy(), 0, CAP)
    test_metrics = {selected: errors(truth, p), "Age-only baseline": errors(truth, baseline)}
    covered = (truth >= low) & (truth <= high)
    result = {
        "dataset": "NASA C-MAPSS FD001",
        "simulated": True,
        "target_cap_cycles": CAP,
        "selected_model": selected,
        "feature_set": kind,
        "seed": 42,
        "cv_folds": folds,
        "cv_cutoffs": {str(k): v for k, v in cutoffs.items()},
        "cv_evaluation_points": int(len(t_cv)),
        "final_refit_engines": 100,
        "official_test_engines": 100,
        "features": list(FT.columns),
        "sensors": SENSORS,
        "validation": validation,
        "test": test_metrics,
        "interval": {
            "method": "Split conformal, Mondrian by predicted-RUL band, out-of-fold CV residuals",
            "target_coverage": COVERAGE,
            "bands": bands,
            "test_coverage": float(covered.mean()),
            "test_mean_width": float((high - low).mean()),
            "test_coverage_within_cap": float(covered[truth <= CAP].mean()),
        },
        "horizons": [horizon_metrics(truth, p, h) for h in range(5, 126)],
        "engine_predictions": [
            {
                "engine_id": int(i),
                "observed_cycles": int(c),
                "predicted_rul": float(a),
                "interval_low": float(lo),
                "interval_high": float(hi),
                "actual_rul": int(b),
                "baseline_rul": float(d),
            }
            for i, c, a, lo, hi, b, d in zip(
                test.loc[final_idx, "engine_id"],
                test.loc[final_idx, "cycle"],
                p,
                low,
                high,
                truth,
                baseline,
            )
        ],
        "files": {
            name: hashlib.sha256((DATA / name).read_bytes()).hexdigest()
            for name in ["train_FD001.txt", "test_FD001.txt", "RUL_FD001.txt"]
        },
        "protocol": (
            "Model and feature set selected by 5-fold engine-grouped cross-validation on the official "
            "training engines (five fixed-seed truncation points per held-out engine, uncapped truth, "
            "lowest MAE wins). 90% conformal intervals calibrated on the same out-of-fold residuals. "
            "Selected configuration refit on all 100 training engines, then evaluated once on the "
            "official 100 truncated test engines with supplied final-cycle RUL. Features are causal "
            "(current and earlier cycles only). Training targets capped at 125 cycles; evaluation truth "
            "uncapped unless labelled capped."
        ),
    }
    from app.artifacts import atomic_joblib, atomic_json

    atomic_joblib(
        ROOT / "models/prognostics.joblib",
        {
            "model": model,
            "feature_set": kind,
            "feature_columns": list(FT.columns),
            "interval_bands": bands,
        },
    )
    atomic_json(ROOT / "models/prognostics_metrics.json", result)
    print(
        json.dumps(
            {
                "selected": selected,
                "validation": validation,
                "test": test_metrics,
                "interval": result["interval"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    train()
