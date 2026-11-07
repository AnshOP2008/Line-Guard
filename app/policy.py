"""Maintenance-policy simulation: turns out-of-fold RUL forecasts into cost and downtime impact."""

import json
import numpy as np
from sklearn.base import clone
from app.artifacts import atomic_json
from app.prognostics import CAP, candidates, features, interval, load
from app.train import ROOT

OOF_PATH = ROOT / "models/policy_oof.json"
PROTOCOL = (
    "Every engine of NASA C-MAPSS FD001 training data (100 run-to-failure trajectories) is replayed "
    "cycle by cycle. Forecasts are out-of-fold: the same five engine-grouped folds as the prognostics "
    "cross-validation are used, and each engine is predicted only by a model fitted on the other four "
    "folds. Policies are simulated on those forecasts. A predictive policy triggers maintenance at the "
    "first cycle its signal (point forecast, or the 90% interval lower bound) is at or below the "
    "threshold; maintenance happens after the lead time, and if the engine has already failed by then "
    "the event is an unplanned failure. Engines are split by cross-validation fold: 60 tuning engines (folds 0-2) and 40 evaluation "
    "engines (folds 3-4). Both the fixed interval and the LineGuard threshold (unless given explicitly) "
    "are tuned on the tuning engines only, with identical treatment (exhaustive search minimising "
    "cost per 1000 operating cycles), and every policy is reported on the evaluation engines, which "
    "tuning never saw. The fixed interval is tuned over true failure cycles, so it is a strong "
    "scheduled-maintenance competitor. Costs are user-supplied "
    "assumptions, not measured plant data. Simulated dataset."
)
_cache = {}


def build():
    df = load("train_FD001.txt")
    metrics = json.loads((ROOT / "models/prognostics_metrics.json").read_text())
    import joblib

    bands = joblib.load(ROOT / "models/prognostics.joblib")["interval_bands"]
    kind, model = candidates()[metrics["selected_model"]]
    X = features(df, kind)
    life = df.groupby("engine_id").cycle.max()
    y = (df.engine_id.map(life) - df.cycle).clip(upper=CAP)
    engines = []
    for k, held in enumerate(metrics["cv_folds"]):
        fit = ~df.engine_id.isin(held)
        m = clone(model).fit(X[fit], y[fit])
        for e in held:
            g = df[df.engine_id == e].sort_values("cycle")
            pred = np.clip(m.predict(X.loc[g.index]), 0, CAP)
            low, _ = interval(pred, bands)
            engines.append(
                {
                    "engine_id": int(e),
                    "fold": k,
                    "failure_cycle": int(life[e]),
                    "pred": [round(float(v), 1) for v in pred],
                    "low": [round(float(v), 1) for v in low],
                }
            )
    engines.sort(key=lambda r: r["engine_id"])
    atomic_json(OOF_PATH, {"protocol": PROTOCOL, "engines": engines})
    _cache.clear()
    return engines


def load_oof():
    if "oof" not in _cache:
        _cache["oof"] = json.loads(OOF_PATH.read_text())
    return _cache["oof"]


def _result(name, failures, preventive, used, wasted, total_life, cost_p, cost_f):
    n = failures + preventive
    cost = preventive * cost_p + failures * cost_f
    return {
        "policy": name,
        "failures": int(failures),
        "preventive": int(preventive),
        "failure_rate": failures / n if n else 0.0,
        "mean_wasted_cycles": (sum(wasted) / preventive) if preventive else 0.0,
        "life_utilisation": sum(used) / total_life if total_life else 0.0,
        "total_cost": float(cost),
        "cost_per_1000_cycles": float(cost / sum(used) * 1000) if sum(used) else 0.0,
    }


def _run(oof, name, maint_cycle, cost_p, cost_f):
    """maint_cycle(engine) -> cycle at which maintenance happens, or None (never)."""
    failures, preventive, used, wasted, total = 0, 0, [], [], 0
    per_engine = []
    for e in oof["engines"]:
        fc = e["failure_cycle"]
        total += fc
        c = maint_cycle(e)
        if c is None or c >= fc:
            failures += 1
            used.append(fc)
            per_engine.append(_row(e, fc, "failure"))
        else:
            preventive += 1
            used.append(c)
            wasted.append(fc - c)
            per_engine.append(_row(e, c, "preventive"))
    out = _result(name, failures, preventive, used, wasted, total, cost_p, cost_f)
    out["per_engine"] = per_engine
    return out


def _row(e, action_cycle, outcome):
    return {
        "engine_id": e["engine_id"],
        "failure_cycle": e["failure_cycle"],
        "action_cycle": int(action_cycle),
        "outcome": outcome,
    }


def simulate(oof, threshold, cost_preventive=1.0, cost_failure=10.0, lead=0, use_lower_bound=False):
    key = "low" if use_lower_bound else "pred"

    def when(e):
        for i, v in enumerate(e[key]):
            if v <= threshold:
                return i + 1 + lead  # cycles are 1-indexed
        return None

    name = (
        f"Predictive (threshold {threshold:g}, {'lower bound' if use_lower_bound else 'forecast'})"
    )
    return _run(oof, name, when, cost_preventive, cost_failure)


def run_to_failure(oof, cost_preventive=1.0, cost_failure=10.0):
    return _run(oof, "Run to failure", lambda e: None, cost_preventive, cost_failure)


def fixed_interval(oof, interval, cost_preventive=1.0, cost_failure=10.0):
    return _run(
        oof,
        f"Fixed interval ({interval} cycles)",
        lambda e: interval,
        cost_preventive,
        cost_failure,
    )


def best_fixed_interval(oof, cost_preventive=1.0, cost_failure=10.0):
    runs = [fixed_interval(oof, i, cost_preventive, cost_failure) for i in range(100, 401)]
    return min(runs, key=lambda r: r["cost_per_1000_cycles"])


def best_threshold(oof, cost_preventive=1.0, cost_failure=10.0, lead=0, use_lower_bound=False):
    runs = [
        simulate(oof, t, cost_preventive, cost_failure, lead, use_lower_bound) for t in range(0, 61)
    ]
    return min(runs, key=lambda r: r["cost_per_1000_cycles"])


def _pct(base, new):
    return 100.0 * (base - new) / base if base else 0.0


TUNING_FOLDS = (0, 1, 2)
EVALUATION_FOLDS = (3, 4)


def split(oof):
    tune = {"engines": [e for e in oof["engines"] if e["fold"] in TUNING_FOLDS]}
    evaluate = {"engines": [e for e in oof["engines"] if e["fold"] in EVALUATION_FOLDS]}
    return tune, evaluate


def compare(cost_preventive=1.0, cost_failure=10.0, lead=0, threshold=None, use_lower_bound=False):
    if not (cost_preventive > 0 and cost_failure > 0):
        raise ValueError("costs must be positive")
    if not (0.5 <= cost_failure / cost_preventive <= 1000):
        raise ValueError("failure/preventive cost ratio must be between 0.5 and 1000")
    if not (0 <= lead <= 50):
        raise ValueError("lead must be between 0 and 50 cycles")
    if threshold is not None and not (0 <= threshold <= CAP):
        raise ValueError(f"threshold must be between 0 and {CAP}")
    full = load_oof()
    tune, ev = split(full)
    tuned_interval = int(
        best_fixed_interval(tune, cost_preventive, cost_failure)["policy"].split("(")[1].split()[0]
    )
    if threshold is None:
        tuned = best_threshold(tune, cost_preventive, cost_failure, lead, use_lower_bound)
        used_threshold = int(tuned["policy"].split("threshold ")[1].split(",")[0])
    else:
        used_threshold = threshold
    rtf = run_to_failure(ev, cost_preventive, cost_failure)
    fixed = fixed_interval(ev, tuned_interval, cost_preventive, cost_failure)
    pred = simulate(ev, used_threshold, cost_preventive, cost_failure, lead, use_lower_bound)
    pred["policy"] = "LineGuard predictive"
    pred["threshold"] = used_threshold
    pred["signal"] = "interval lower bound" if use_lower_bound else "point forecast"
    pred["threshold_chosen"] = "given" if threshold is not None else "tuned on tuning engines"
    fixed["policy"] = "Best fixed interval"
    fixed["interval"] = tuned_interval
    rtf.pop("per_engine")
    return {
        "assumptions": {
            "cost_preventive": cost_preventive,
            "cost_failure": cost_failure,
            "lead": lead,
            "use_lower_bound": use_lower_bound,
        },
        "tuning_engines": len(tune["engines"]),
        "evaluation_engines": len(ev["engines"]),
        "tuned_threshold": used_threshold,
        "tuned_interval": tuned_interval,
        "policies": [rtf, fixed, pred],
        "savings_vs_fixed_pct": _pct(fixed["cost_per_1000_cycles"], pred["cost_per_1000_cycles"]),
        "savings_vs_run_to_failure_pct": _pct(
            rtf["cost_per_1000_cycles"], pred["cost_per_1000_cycles"]
        ),
        "failures_avoided_vs_fixed": fixed["failures"] - pred["failures"],
        "protocol": full["protocol"],
    }


def summary(r):
    a = r["assumptions"]
    print(
        f"cost 1:{a['cost_failure'] / a['cost_preventive']:g} lead {a['lead']} lb={a['use_lower_bound']}"
    )
    for p in r["policies"]:
        print(
            f"  {p['policy']:<22} fail {p['failures']:>3} prev {p['preventive']:>3} "
            f"waste {p['mean_wasted_cycles']:6.1f} util {p['life_utilisation']:.3f} "
            f"cost/1000 {p['cost_per_1000_cycles']:.2f}"
            + (f" thr {p['threshold']}" if "threshold" in p else "")
            + (f" int {p['interval']}" if "interval" in p else "")
        )
    print(
        f"  savings vs fixed {r['savings_vs_fixed_pct']:.1f}%, vs RTF "
        f"{r['savings_vs_run_to_failure_pct']:.1f}%, failures avoided {r['failures_avoided_vs_fixed']}"
    )


if __name__ == "__main__":
    build()
    summary(compare(1, 10, 0))
