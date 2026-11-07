# Data attribution and reproduction

## SKAB primary dataset

- Official source: https://github.com/waico/SKAB
- Pinned revision: `b2c0d46c2971dcbfe71e26087b6d231998bb91c2`
- Credit: Iurii Katser and Vyacheslav Kozitsin, Skoltech Anomaly Benchmark (SKAB), 2020. Upstream README contains the requested BibTeX citation.
- Upstream license: GNU GPL v3, retained at `data/SKAB/LICENSE` and project root `LICENSE`.
- Eight measured signals from a real water-circulation testbed. Repository CSV headers are preserved, including `Volume Flow RateRMS`.
- All 35 source CSVs are bundled unmodified. SHA-256 hashes and chronological split roles are written by training to `models/lineguard_metrics.json`.
- Replay scenarios that alter samples are labelled simulated. Uploaded streams carry no assumed ground truth; provided labels are ignored.

Rebuild primary model with `python -m app.train` in the project environment. No download is needed after setup.

## AI4I 2020 optional benchmark

- Official source: https://archive.ics.uci.edu/dataset/601/ai4i
- Citation: AI4I 2020 Predictive Maintenance Dataset [Dataset]. (2020). UCI Machine Learning Repository. https://doi.org/10.24432/C5HS5C
- License: Creative Commons Attribution 4.0 International, https://creativecommons.org/licenses/by/4.0/
- Source file: `data/ai4i2020.csv`, unmodified. Public synthetic data; not real-world failure outcomes.
- Reproduce with `python -m app.ai4i_optional`. Output is `models/model.joblib` and `models/metrics.json`; independent from the LineGuard model.
- Six inputs: product type, air/process temperature, rotation, torque and wear. UID, Product ID, Machine failure and all five failure-mode labels are excluded from features. Target is Machine failure.
- Fixed seed 42; stratified 60/20/20 train/validation/test. Logistic and gradient-boosted models compared by validation PR-AUC. Threshold selected using validation-only assumed cost: $15,000 per missed failure and $500 per inspection. Test metrics are then computed once.
- Costs are assumptions. Snapshot rows do not establish advance warning or a prediction horizon. No synthetic AI4I relationship is transferred into the real SKAB pump model.

Both datasets are provided for transparent reproducibility and attributed separately. The local feedback database is user-generated and is not part of either dataset.

## NASA C-MAPSS FD001 prognostics dataset

- Official primary source: [NASA PCoE repository, section 6](https://www.nasa.gov/intelligent-systems-division/discovery-and-systems-health/pcoe/pcoe-data-set-repository/).
- That NASA page directly links the archive downloaded here: `https://phm-datasets.s3.amazonaws.com/NASA/6.+Turbofan+Engine+Degradation+Simulation+Data+Set.zip`.
- The archive contains `CMAPSSData.zip`; the included FD001 files are extracted from that nested original archive. Original readme and paper retained alongside source data.
- Citation requested by NASA: A. Saxena and K. Goebel (2008), “Turbofan Engine Degradation Simulation Data Set”, NASA Prognostics Data Repository, NASA Ames Research Center, Moffett Field, CA. Original paper: A. Saxena, K. Goebel, D. Simon, N. Eklund, “Damage Propagation Modeling for Aircraft Engine Run-to-Failure Simulation”, PHM08.
- FD001:100 training and 100 test trajectories; one simulated sea-level operating condition and one HPC degradation mode. Training runs reach simulated failure; official test runs stop earlier. `RUL_FD001.txt` supplies cycles remaining after each test engine's last observation.
- These are **simulator-generated engine trajectories**, not real factory pumps or real flight telemetry. No transfer or sensor fusion with SKAB is asserted.
- Files `train_FD001.txt`, `test_FD001.txt`, `RUL_FD001.txt` have SHA-256 hashes in `models/prognostics_metrics.json`. All engine split IDs, validation cutoffs, feature names and final endpoint predictions are stored there too.
- NASA repository requests acknowledgement and states users employ data at their own risk. No explicit CC0 license is asserted. The project's GPL code license does not override upstream data terms.
- Reproduce with `python -m app.prognostics`. No download after initial setup; data is bundled. Forecast code and evaluation are independent of both SKAB and optional AI4I.

## NASA C-MAPSS FD002–FD004 (generalisation benchmark only)

Extracted from the same NASA-linked archive (`CMAPSSData.zip`) into `data/CMAPSS/FD002…FD004`; SHA-256 hashes are in `data/CMAPSS/PROVENANCE.json`. FD002 and FD004 have six simulated operating conditions; FD003 and FD004 have two fault modes. They are used only by `app/benchmark.py`, which reruns the predeclared FD001 recipe (with per-regime sensor normalisation for multi-condition subsets) and evaluates each official test set once. The app's interactive forecast lab remains FD001.
