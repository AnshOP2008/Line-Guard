import json

from app.train import ROOT


def test_benchmark_covers_all_subsets_with_predeclared_recipe():
    r = json.loads((ROOT / "models/benchmark_cmapss.json").read_text())
    assert set(r["subsets"]) == {"FD001", "FD002", "FD003", "FD004"}
    fd001 = json.loads((ROOT / "models/prognostics_metrics.json").read_text())
    # FD001 row must reproduce the shipped app model's official test result exactly.
    assert (
        abs(r["subsets"]["FD001"]["result"]["mae"] - fd001["test"][fd001["selected_model"]]["mae"])
        < 1e-9
    )
    for name in ["FD002", "FD004"]:
        row = r["subsets"][name]
        assert row["regime_normalised"]
        assert (
            row["result"]["rmse_capped_truth"]
            < row["ablation_without_regime_normalisation"]["rmse_capped_truth"]
        )
