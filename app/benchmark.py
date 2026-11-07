"""Generalisation check: the FD001 recipe on all four NASA C-MAPSS subsets.

The FD001 configuration (drift features + gradient boosting, same hyperparameters) is
predeclared and reused unchanged; nothing is tuned per subset. FD002 and FD004 run under
six operating conditions, so sensors are first z-scored per operating regime. Regimes
are KMeans clusters of the three operating settings fitted on training data only.
Each subset's official test set is evaluated once.
"""

import json

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.ensemble import HistGradientBoostingRegressor

from app.prognostics import CAP, COLUMNS, SENSORS, drift_features, errors
from app.train import ROOT

SUBSETS = {
    "FD001": {"conditions": 1, "fault_modes": 1},
    "FD002": {"conditions": 6, "fault_modes": 1},
    "FD003": {"conditions": 1, "fault_modes": 2},
    "FD004": {"conditions": 6, "fault_modes": 2},
}
SETTINGS = ["setting_1", "setting_2", "setting_3"]


def read(subset, kind):
    path = ROOT / "data/CMAPSS" / subset / f"{kind}_{subset}.txt"
    if kind == "RUL":
        return pd.read_csv(path, header=None)[0].to_numpy()
    return pd.read_csv(path, sep=r"\s+", header=None, names=COLUMNS)


class RegimeNormalizer:
    """Per-operating-regime z-scoring of sensors, fitted on training rows only."""

    def __init__(self, regimes):
        self.regimes = regimes

    def fit(self, df):
        self.kmeans = KMeans(self.regimes, n_init=10, random_state=42).fit(df[SETTINGS].round(2))
        label = self.kmeans.labels_
        self.mean = df[SENSORS].groupby(label).mean()
        self.std = df[SENSORS].groupby(label).std().replace(0, 1).fillna(1)
        return self

    def transform(self, df):
        out = df.copy()
        label = self.kmeans.predict(df[SETTINGS].round(2))
        out[SENSORS] = (df[SENSORS].to_numpy() - self.mean.loc[label].to_numpy()) / self.std.loc[
            label
        ].to_numpy()
        return out


def model():
    return HistGradientBoostingRegressor(
        max_iter=260, max_leaf_nodes=15, l2_regularization=5, learning_rate=0.06, random_state=42
    )


def evaluate(subset, normalize):
    train, test, truth = read(subset, "train"), read(subset, "test"), read(subset, "RUL")
    if normalize:
        norm = RegimeNormalizer(SUBSETS[subset]["conditions"]).fit(train)
        train, test = norm.transform(train), norm.transform(test)
    life = train.groupby("engine_id").cycle.max()
    y = (train.engine_id.map(life) - train.cycle).clip(upper=CAP)
    m = model().fit(drift_features(train), y)
    final = test.groupby("engine_id").tail(1).index
    p = np.clip(m.predict(drift_features(test).loc[final]), 0, CAP)
    return {
        **errors(truth, p),
        "train_engines": int(train.engine_id.nunique()),
        "test_engines": int(len(final)),
    }


def run():
    results = {}
    for subset, info in SUBSETS.items():
        multi = info["conditions"] > 1
        row = {**info, "regime_normalised": multi, "result": evaluate(subset, multi)}
        if multi:
            row["ablation_without_regime_normalisation"] = evaluate(subset, False)
        results[subset] = row
        print(subset, json.dumps(row["result"]), flush=True)
    return {
        "protocol": __doc__.strip(),
        "subsets": results,
        "literature_rmse": {
            "note": "Published RMSE values as collected in arXiv:2511.19124, Table I. Protocols "
            "differ between papers (test-truth capping, windowing), so treat as context, not a "
            "leaderboard.",
            "source": "https://arxiv.org/abs/2511.19124",
            "rows": {
                "Bi-LSTM": [17.60, 29.67, 17.62, 31.84],
                "CNN-LSTM-Attention": [15.98, 14.45, 13.91, 16.64],
                "CAELSTM": [14.44, None, 13.40, None],
                "ABGRU": [12.83, None, 13.23, None],
                "Transformer": [11.36, None, 11.28, None],
                "TCNN-Transformer": [None, 15.2, None, 17.3],
            },
        },
    }


if __name__ == "__main__":
    from app.artifacts import atomic_json

    atomic_json(ROOT / "models/benchmark_cmapss.json", run())
