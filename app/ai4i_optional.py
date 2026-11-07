from pathlib import Path
import json, hashlib
import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.pipeline import make_pipeline
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import (
    average_precision_score,
    precision_score,
    recall_score,
    confusion_matrix,
    precision_recall_curve,
)

ROOT = Path(__file__).resolve().parents[1]
FEATURES = [
    "Type",
    "Air temperature [K]",
    "Process temperature [K]",
    "Rotational speed [rpm]",
    "Torque [Nm]",
    "Tool wear [min]",
]
NUMERIC = FEATURES[1:]
BOUNDS = [(250, 350), (250, 400), (200, 4000), (0, 150), (0, 300)]


def metrics(y, p, t):
    pred = p >= t
    return {
        "pr_auc": float(average_precision_score(y, p)),
        "precision": float(precision_score(y, pred, zero_division=0)),
        "recall": float(recall_score(y, pred, zero_division=0)),
        "confusion": confusion_matrix(y, pred, labels=[0, 1]).tolist(),
        "alerts": int(pred.sum()),
    }


def cost_curve(y, p):
    return [
        dict(threshold=round(float(t), 3), **metrics(y, p, t)) for t in np.linspace(0.01, 0.99, 99)
    ]


def train():
    df = pd.read_csv(ROOT / "data/ai4i2020.csv")
    X = df[FEATURES]
    y = df["Machine failure"]
    train_idx, rest = train_test_split(
        np.arange(len(df)), test_size=0.4, stratify=y, random_state=42
    )
    val_idx, test_idx = train_test_split(
        rest, test_size=0.5, stratify=y.iloc[rest], random_state=42
    )
    prep = ColumnTransformer(
        [
            ("type", OneHotEncoder(sparse_output=False, handle_unknown="ignore"), ["Type"]),
            ("sensors", StandardScaler(), NUMERIC),
        ]
    )
    candidates = {
        "Logistic baseline": make_pipeline(
            prep, LogisticRegression(max_iter=1000, class_weight="balanced", random_state=42)
        ),
        "Gradient boosted trees": make_pipeline(
            prep,
            HistGradientBoostingClassifier(
                max_iter=220,
                max_leaf_nodes=15,
                l2_regularization=2,
                learning_rate=0.07,
                random_state=42,
            ),
        ),
    }
    models = {}
    results = {}
    for name, model in candidates.items():
        model.fit(X.iloc[train_idx], y.iloc[train_idx])
        pv = model.predict_proba(X.iloc[val_idx])[:, 1]
        models[name] = model
        results[name] = {"validation_pr_auc": float(average_precision_score(y.iloc[val_idx], pv))}
    winner = max(results, key=lambda n: results[n]["validation_pr_auc"])
    model = models[winner]
    pv = model.predict_proba(X.iloc[val_idx])[:, 1]
    curve = cost_curve(y.iloc[val_idx], pv)
    threshold = min(curve, key=lambda r: r["confusion"][1][0] * 15000 + r["alerts"] * 500)[
        "threshold"
    ]
    for name, m in models.items():
        results[name]["test"] = metrics(
            y.iloc[test_idx], m.predict_proba(X.iloc[test_idx])[:, 1], threshold
        )
    ptest = model.predict_proba(X.iloc[test_idx])[:, 1]
    precision, recall, th = precision_recall_curve(y.iloc[test_idx], ptest)
    report = {
        "selected_model": winner,
        "threshold": threshold,
        "seed": 42,
        "splits": {"train": len(train_idx), "validation": len(val_idx), "test": len(test_idx)},
        "failures": {
            k: int(y.iloc[v].sum())
            for k, v in [("train", train_idx), ("validation", val_idx), ("test", test_idx)]
        },
        "models": results,
        "validation_curve": curve,
        "test_curve": cost_curve(y.iloc[test_idx], ptest),
        "pr_curve": [
            {"recall": float(r), "precision": float(p)}
            for r, p in zip(
                recall[:: max(1, len(recall) // 120)], precision[:: max(1, len(precision) // 120)]
            )
        ],
        "medians": {c: float(X.iloc[train_idx][c].median()) for c in NUMERIC},
        "sha256": hashlib.sha256((ROOT / "data/ai4i2020.csv").read_bytes()).hexdigest(),
    }
    (ROOT / "models").mkdir(exist_ok=True)
    joblib.dump(model, ROOT / "models/model.joblib")
    (ROOT / "models/metrics.json").write_text(json.dumps(report, indent=2))
    print(json.dumps({"selected": winner, "threshold": threshold, "results": results}, indent=2))


if __name__ == "__main__":
    train()
