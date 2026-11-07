# LineGuard pump anomaly model card

This card covers the SKAB pump detector only. The independent NASA simulated-engine failure forecast has its own [prognostics model card](PROGNOSTICS_MODEL_CARD.md), with remaining-life evaluation. No cross-equipment transfer is claimed.

## Intended use

Human-reviewed exploration of industrial pump anomalies and sensor relationships. Research prototype. Not a safety controller, remaining-life estimator, diagnosed component classifier, or validated pre-failure predictor.

## Data

SKAB v 0.9, official waico/SKAB repository, pinned commit in README. Thirty-five CSV experiments from one physical water-circulation testbed. Signals: two accelerometers (g), motor current (A), pressure (bar), motor temperature and fluid thermocouple (°C), motor voltage (V), volume flow (L/min). Source timestamps and labels are never model inputs.

Entire runs sorted by start time, first 60% train, next 20% calibration, final 20% test. Normal labels filter clean train/calibration data retrospectively. This requires knowledge of a clean reference period; an unsupervised production stream does not magically supply clean training data. The test set contains all rows, including normal rows. Exact run roles and SHA-256 hashes are stored in the metrics manifest. This is a single-rig chronological holdout, not independent-site validation.

## Model and threshold

Eight ExtraTrees regressors independently predict each standardized sensor using the other seven. Hyperparameters are fixed in code, not optimized against tests. Train residual 80 th percentiles with a 0.12 floor normalize per-sensor deviations. The score averages the three largest normalized residual magnitudes. The model uses contemporaneous relationships; it does not forecast future samples.

PCA (four components) and a trailing-five-sample standardized baseline use the same split and threshold procedure. For each model, threshold is calibration-normal 99 th percentile with the higher quantile. Strictly greater scores alert. Calibration is empirical: no claim of exchangeability, conformal coverage, future FPR guarantee or alarms-per-shift guarantee is made. Rolling windows reset at run boundaries and between separate clean calibration segments.

## Evaluation

The predeclared primary residual model detected 6/7 anomaly events; median delay among detected events 17.5 seconds; point precision 48.46%, recall 24.35%; normal point FPR 14.02%. The 1% calibration target achieved 0.989% empirically but did not transfer to the later runs. All baseline results are in README and the evidence screen.

Event recall: fraction of contiguous labelled anomaly regions overlapped by at least one alert. Event precision: fraction of contiguous alert segments overlapping any labelled region. No point-adjusted predictions. A single hit can count a long event detected, so event recall must be read alongside point recall. Raw threshold chatter creates many short alarm segments; 298 for the primary model. Detection delay excludes missed events and uses recorded timestamps, not sample count. Zero delay means the detector already alerts at onset; it does not prove advance warning. Labels describe anomalies, not time of mechanical failure.

## Sensor integrity checks

Flatline heuristic: ten identical consecutive readings in vibration/current/temperature/voltage channels. Pressure and flow are excluded because quantization can yield legitimate constant values. Spike heuristic: a one-step jump greater than six training standard deviations. Both operate causally after warmup and use train-derived scales. They can trigger without a model alarm. They do not establish root cause. No real sensor-fault labels exist here.

Synthetic current stress tests use a fixed held-out normal sequence. Spikes add eight training standard deviations every ten samples; drift ramps to that amplitude; flatline freezes one reading for 200 samples. Detection, heuristic flag and top-attribution rates are reported separately. Flatline detection is weak in the residual model but strong in the explicit heuristic; gradual drift is missed by the sensor heuristic. These results are not testbed fault performance.

Ablation replaces one entire sensor with its training mean, without refitting. It measures sensitivity to lost information, not reliable missing-data operation.

## Explanation limits

Expected reading is the corresponding regressor's prediction from other observed readings. Correlated sensors can share or mask faults. Residual magnitude is associative evidence, not causality, a calibrated failure probability or component diagnosis. Large shifts outside training support can produce arbitrary tree extrapolation.

## Operational limits

No operating-mode classifier, sensor calibration validation, missing-value imputation, online adaptation, automatic maintenance dispatch or authenticated multi-user access. CSV uploads are bounded to 2 MB and 1,200 rows; inference rejects missing/nonfinite inputs. Inference is local, bound to loopback. SQLite feedback is a human opinion record and never automatically becomes ground truth or retrains the model. Delete only the local feedback database manually if a clean demo is desired.

Before deployment: prospective fault/failure timestamps, representative operating modes, independent machines/sites, causal time splits, uncertainty/calibration monitoring, real sensor-fault evaluation, robust alarm persistence, capacity constraints, privacy/authentication and maintenance outcome studies.

## Operational alert comparison

The grouped policy is causal and preconfigured. It is an exploratory operational
layer evaluated on previously inspected runs. It does not recalibrate the detector.
See the per-run normal-score summary and raw-versus-grouped event counts in
`models/operations_evidence.json`. Unmatched alert counts are normalized by observed
test duration. Compare detection delay only with awareness that the detected event
subsets differ.

The current gap-aware policy resets after intervals above 1.5 seconds. Missing intervals are excluded from occupancy: 2.02 observed test hours remain. Raw normal-time occupancy is 13.99%; grouped is 10.70%. Grouped catches 5/7 events with 45 unmatched segments and median detected-event delay 288 seconds. On the five commonly detected events, raw median delay is 6 seconds versus grouped 288 seconds. These findings supersede earlier grouping results that did not reset across telemetry gaps. The primary raw detector and its original benchmark are unchanged.

The bounded calibration experiment in `models/research_evidence.json` uses only the seven calibration runs, split chronologically into three threshold-fit and four development-evaluation runs. Neither candidate establishes a calibration fix; neither is adopted. Previously inspected test data are not presented as an untouched new evaluation.

