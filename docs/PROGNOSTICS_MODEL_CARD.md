# Engine RUL model card (NASA C-MAPSS FD001)

## Task
Predict how many operating cycles a turbofan engine has left before failure, from the sensor history observed so far. Data: NASA C-MAPSS FD001, a **simulated** run-to-failure benchmark (one operating condition, one fault mode: HPC degradation). Provenance and hashes: [DATA.md](DATA.md).

## Features (v2, "drift" set), all causal
For 14 informative sensors (2, 3, 4, 7, 8, 9, 11, 12, 13, 14, 15, 17, 20, 21) plus the observed cycle:

| Feature | Why |
|---|---|
| `_ewm`: exponentially smoothed reading (α = 0.1) | removes sensor noise |
| `_drift`: smoothed reading minus the engine's **own early-life baseline** (mean of its first 15 cycles) | removes engine-to-engine manufacturing offsets. This feature produced the biggest gain. |
| `_mean10/_mean30`: trailing means | local level |
| `_slope10/_slope30`: least-squares trend over 10 and 30 cycles | degradation speed |

Every value uses only current and earlier cycles. `tests/test_prognostics.py` checks that features computed on a 20-cycle prefix exactly equal the first 20 rows computed on the full trajectory, so no future values leak in. It also checks that rolling windows never mix engines. Engine IDs, lifetimes and RUL labels are never inputs.

## Protocol
1. **Selection.** Run 5-fold **engine-grouped** cross-validation over the 100 official training engines. Each held-out engine is truncated at 5 fixed-seed random cycles to mimic the test set, giving 500 evaluation points. Candidates are predefined: gradient boosting or extra trees on drift features, and gradient boosting on the v1 trailing-window features. The lowest CV MAE (uncapped truth) wins.
2. **Uncertainty.** Fit a split-conformal 90% interval on the selected model's out-of-fold residuals. It is Mondrian by predicted-RUL band (0–40, 40–80, 80–125), so the interval narrows as failure approaches.
3. **Final model.** Refit on all 100 training engines. Training targets are capped at 125 cycles (standard piecewise-linear RUL).
4. **Test.** Evaluate **once** on the official 100 truncated test engines with NASA's supplied final RUL. The test set chose nothing.

## Results

| | CV MAE (500 pts) | Test MAE | Test RMSE | RMSE (truth capped at 125) | NASA PHM score ↓ |
|---|---:|---:|---:|---:|---:|
| Age-only baseline | 43.99 | 28.32 | 37.78 | 37.00 | 25,970 |
| GB · trailing-window features (v1) | 24.18 | — | — | — | — |
| Extra trees · drift features | 19.24 | — | — | — | — |
| **GB · drift features (selected)** | **17.71** | **9.28** | **12.66** | **11.31** | **209** |

Unselected candidates are not run on the test set. The earlier v1 model, chosen under the previous protocol, scored test MAE 12.44 and RMSE 16.84.

- **90% conformal interval:** measured test coverage is 97%. Width is about ±6 cycles when predicted RUL is under 40, and wider for healthy engines, whose true life above the 125 cap is inherently unknowable from early data.
- **Engines within 40 cycles of failure (n = 28):** MAE 2.5 cycles.
- **30-cycle maintenance horizon:** catches 23 of 25 engines that fail within the horizon, with 1 false alarm among 75 healthy engines (precision 95.8%, recall 92.0%).
- **Largest single error:** 30.8 cycles. 60 of 100 engines are within ±10 cycles.

CV error is higher than test error because CV includes many early truncation points, where true RUL is far above the cap. The test set's censoring is different.

## Uploads
Separate schema (`engine_id, cycle, setting_1..3, sensor_1..21`): one engine, at least 20 ascending consecutive cycles. Uploaded files get predictions and intervals but **never** an invented ground truth.

## Limitations
FD001 is simulated, with a single operating condition and a single fault mode. Cycles are not hours. The 125-cycle target cap limits long-range estimates. Interval coverage is empirical on this benchmark, not a guarantee for new equipment. Real-asset validation is required before operational use.
