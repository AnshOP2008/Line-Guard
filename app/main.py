"""LineGuard local API. All inference is on-device; SQLite stores human feedback."""

import io, json, sqlite3, math, csv, os, hashlib
from datetime import datetime, timezone
from contextlib import contextmanager
import numpy as np
import pandas as pd
import joblib
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from app.train import ROOT, FEATURES, NAMES, UNITS, sensor_flags
from app.prognostics import (
    load as load_engines,
    features as engine_features,
    interval as engine_interval,
    COLUMNS as ENGINE_COLUMNS,
)

app = FastAPI(
    title="LineGuard", description="Cross-sensor early anomaly detection research prototype"
)
from app.artifacts import build_version

BUILD_VERSION = build_version()
model = joblib.load(ROOT / "models/lineguard.joblib")
report = json.loads((ROOT / "models/lineguard_metrics.json").read_text())
forecast_bundle = joblib.load(ROOT / "models/prognostics.joblib")
forecast_report = json.loads((ROOT / "models/prognostics_metrics.json").read_text())
engine_test = load_engines("test_FD001.txt")
DB = ROOT / os.environ.get("LINEGUARD_DB", "data/feedback.sqlite3")


@contextmanager
def connect():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    con.execute(
        "CREATE TABLE IF NOT EXISTS feedback (id INTEGER PRIMARY KEY, source TEXT, sample INTEGER, verdict TEXT, note TEXT, created TEXT)"
    )
    try:
        con.commit()
        yield con
    finally:
        con.close()


with connect() as c:
    pass


def trace(df, source, kind="recorded", description="", limit=1200, warnings=None):
    df = df.reset_index(drop=True).iloc[:limit]
    X = df[FEATURES]
    scores = model.scores(X)
    evidence, expected = model.explain(X)
    flags = sensor_flags(X, model.scaler.scale_)
    times = (
        pd.to_datetime(df["datetime"], errors="coerce", format="ISO8601")
        if "datetime" in df
        else None
    )
    breaks = [0]
    if times is not None and times.notna().all():
        breaks.extend(np.flatnonzero(times.diff().dt.total_seconds().to_numpy() > 1.5).tolist())
    breaks.append(len(df))
    grouped = np.zeros(len(df), dtype=bool)
    for start, end in zip(breaks, breaks[1:]):
        grouped[start:end] = grouped_alerts(scores[start:end] / model.threshold)
        flags[start:end] = sensor_flags(X.iloc[start:end], model.scaler.scale_)
    warnings = list(warnings or [])
    if len(breaks) > 2:
        warnings.append("Sampling gaps reset temporal diagnostics")
        if len(breaks) - 2 > len(df) * 0.1:
            warnings.append("Unsupported cadence: more than 10% of intervals exceed 1.5 seconds")
    if kind == "uploaded" and (times is None or times.isna().any()):
        warnings.append("Sampling cadence unavailable")
    points = []
    for i in range(len(df)):
        strengths = evidence[i]
        top = np.argsort(strengths)[::-1][:3]
        suspect = flags[i]["sensor_suspect"]
        alarm = bool(scores[i] > model.threshold)
        diagnosis = (
            "Check sensor integrity"
            if suspect
            else ("Relationship change · investigate machine" if alarm else "No anomaly detected")
        )
        points.append(
            {
                "index": i,
                "time": str(df.iloc[i].get("datetime", i)),
                "values": [float(v) for v in X.iloc[i]],
                "expected": [float(v) for v in expected[i]],
                "score": float(scores[i]),
                "ratio": float(scores[i] / model.threshold),
                "alarm": alarm,
                "grouped_alert": bool(grouped[i]),
                "label": int(df.iloc[i].get("anomaly", 0)) if kind == "recorded" else None,
                "drivers": [
                    {
                        "sensor": FEATURES[j],
                        "name": NAMES[j],
                        "strength": float(strengths[j]),
                        "actual": float(X.iloc[i, j]),
                        "expected": float(expected[i, j]),
                        "unit": UNITS[j],
                    }
                    for j in top
                ],
                "diagnosis": diagnosis,
                "sensor_flags": flags[i],
            }
        )
    return register_inference(
        {
            "source": source,
            "kind": kind,
            "description": description,
            "threshold": model.threshold,
            "features": FEATURES,
            "names": NAMES,
            "units": UNITS,
            "points": points,
            "total_rows": len(df),
        },
        "pump",
        report["model_version"],
        warnings,
    )


def test_runs():
    return [r for r in report["manifest"] if r["role"] == "test"]


def read_run(name):
    if name not in [r["run"] for r in test_runs()]:
        raise HTTPException(404, "Unknown held-out run.")
    return pd.read_csv(ROOT / "data/SKAB/data" / name, sep=";")


@app.get("/api/health")
def health():
    return {
        "status": "ready",
        "application": "LineGuard",
        "local_only": True,
        "model": "Cross-sensor residual",
        "build_version": BUILD_VERSION,
        "pump_version": report["model_version"],
        "engine_version": forecast_report["model_version"],
    }


@app.get("/api/metrics")
def metrics():
    return report


@app.get("/api/runs")
def runs():
    return test_runs()


@app.get("/api/scenario/{name}")
def scenario(name: str):
    if name == "recorded":
        run = "valve2/1.csv"
        return trace(
            read_run(run),
            run,
            "recorded",
            "Recorded SKAB valve2/1 demonstration run; all seven held-out runs remain available for inspection. Amber is anomaly ground truth, not a forecast horizon.",
        )
    from app.train import segments

    candidates = []
    for run in test_runs():
        frame = read_run(run["run"])
        for start, end in segments(frame.anomaly.to_numpy() == 0):
            candidates.append((end - start, run["run"], frame.iloc[start:end]))
    _, source, normal = max(candidates, key=lambda item: item[0])
    normal = normal.iloc[:420].copy().reset_index(drop=True)
    normal["anomaly"] = 0
    if name == "normal":
        return trace(
            normal,
            "Normal segment / " + source,
            "recorded",
            "One contiguous labelled-normal segment. No concatenation across experiments.",
        )
    if name not in ["flatline", "spike", "drift", "coherent"]:
        raise HTTPException(404, "Unknown scenario.")
    start = 150
    end = 300
    j = 2
    if name == "flatline":
        normal.iloc[start:end, normal.columns.get_loc(FEATURES[j])] = normal.iloc[start][
            FEATURES[j]
        ]
    if name == "spike":
        normal.iloc[start:end:10, normal.columns.get_loc(FEATURES[j])] += model.scaler.scale_[j] * 8
    if name == "drift":
        normal.iloc[start:end, normal.columns.get_loc(FEATURES[j])] += np.linspace(
            0, model.scaler.scale_[j] * 8, end - start
        )
    if name == "coherent":
        # Explicit what-if: not an observed machine failure and not used in benchmark metrics.
        for c, factor in [("Current", 1.25), ("Volume Flow RateRMS", 0.7), ("Pressure", 1.2)]:
            normal.loc[start : end - 1, c] *= factor
    result = trace(
        normal,
        f"Simulated {name} scenario",
        "simulated",
        f"Synthetic {name} change injected at samples {start}–{end-1} into held-out normal data. Not a real fault diagnosis or benchmark event.",
    )
    result["injection"] = {
        "start": start,
        "end": end,
        "sensor": "Current" if name != "coherent" else "Current / flow / pressure",
    }
    return result


@app.get("/api/run")
def run(name: str):
    return trace(
        read_run(name),
        name,
        "recorded",
        "Untouched chronological test run from the SKAB pump testbed.",
    )


@app.post("/api/upload")
async def upload(file: UploadFile = File(...)):
    data = await file.read(2_000_001)
    if len(data) > 2_000_000:
        raise HTTPException(413, "CSV must be under 2 MB.")
    try:
        raw = data.decode("utf-8-sig")
        delimiter = ";" if ";" in raw.splitlines()[0] else ","
        reader = csv.DictReader(io.StringIO(raw), delimiter=delimiter)
        headers = reader.fieldnames or []
        if len(headers) != len(set(headers)):
            raise ValueError("Duplicate column names are not allowed.")
        missing = [f for f in FEATURES if f not in headers]
        if missing:
            raise ValueError("Missing columns: " + ", ".join(missing))
        rows = []
        for line, row in enumerate(reader, 2):
            if line > 1201:
                raise ValueError("Use at most 1,200 samples per replay.")
            if None in row:
                raise ValueError(f"Row {line}: unexpected extra CSV fields.")
            clean = {}
            for f in FEATURES:
                try:
                    v = float(row[f])
                except (ValueError, TypeError):
                    raise ValueError(f"Row {line}: {f} must be numeric.")
                if not math.isfinite(v) or abs(v) > 1e7:
                    raise ValueError(f"Row {line}: {f} must be finite and within ±10 million.")
                clean[f] = v
            clean["datetime"] = row.get("datetime", str(line - 2))
            rows.append(clean)
        if len(rows) < 20:
            raise ValueError("Upload at least 20 samples for temporal diagnostics.")
        df = pd.DataFrame(rows)
        if "datetime" in headers:
            parsed = pd.to_datetime(df.datetime, errors="coerce")
            if (
                parsed.isna().any()
                or not parsed.is_monotonic_increasing
                or parsed.duplicated().any()
            ):
                raise ValueError("datetime must contain unique, ascending valid timestamps.")
            intervals = parsed.diff().dropna().dt.total_seconds()
            if (intervals < 0.9).any():
                raise ValueError(
                    "Pump samples must be at least 0.9 seconds apart. Verify sampling cadence."
                )
    except (ValueError, UnicodeDecodeError, csv.Error, IndexError) as e:
        raise HTTPException(422, str(e))
    result = trace(
        df,
        "Uploaded sensor stream",
        "uploaded",
        "User-provided data. Labels and extra columns are ignored; no ground truth or performance claims.",
        warnings=domain_warnings(df, "training_ranges"),
    )
    result["ignored_columns"] = [h for h in headers if h not in FEATURES + ["datetime"]]
    return result


@app.get("/api/sample")
def sample():
    return FileResponse(
        ROOT / "data/sample_stream.csv", filename="lineguard_sample.csv", media_type="text/csv"
    )


class Feedback(BaseModel):
    source: str = Field(min_length=1, max_length=120)
    sample: int = Field(ge=0, le=10000000)
    verdict: str
    note: str = Field(default="", max_length=1000)


@app.get("/api/feedback")
def feedback():
    with connect() as c:
        return [dict(r) for r in c.execute("SELECT * FROM feedback ORDER BY id DESC")]


@app.post("/api/feedback", status_code=201)
def save_feedback(item: Feedback):
    if item.verdict not in ["Real fault", "False alarm", "Sensor issue", "Needs investigation"]:
        raise HTTPException(422, "Invalid feedback verdict.")
    with connect() as c:
        cur = c.execute(
            "INSERT INTO feedback(source,sample,verdict,note,created) VALUES(?,?,?,?,?)",
            (
                item.source,
                item.sample,
                item.verdict,
                item.note,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        c.commit()
        return {"id": cur.lastrowid, **item.model_dump()}


@app.get("/api/prognostics")
def prognostics():
    return forecast_report


def engine_trace(df, actual_final=None, source="Official NASA FD001 test", warnings=None):
    df = df.sort_values("cycle").reset_index(drop=True)
    inputs = engine_features(df, forecast_bundle.get("feature_set", "trailing"))
    predicted = np.clip(
        forecast_bundle["model"].predict(inputs[forecast_bundle["feature_columns"]]), 0, 125
    )
    low, high = engine_interval(predicted, forecast_bundle["interval_bands"])
    last = int(df.cycle.iloc[-1])
    channels = ["sensor_2", "sensor_3", "sensor_4", "sensor_7", "sensor_11", "sensor_15"]
    return register_inference(
        {
            "source": source,
            "engine_id": int(df.engine_id.iloc[0]),
            "observed_cycles": last,
            "predicted_rul": float(predicted[-1]),
            "interval_low": float(low[-1]),
            "interval_high": float(high[-1]),
            "interval_coverage": forecast_report["interval"]["target_coverage"],
            "actual_rul": actual_final,
            "channels": channels,
            "points": [
                {
                    "cycle": int(row.cycle),
                    "predicted_rul": float(predicted[i]),
                    "interval_low": float(low[i]),
                    "interval_high": float(high[i]),
                    "actual_rul": (
                        None if actual_final is None else int(actual_final + last - row.cycle)
                    ),
                    "sensors": [float(row[c]) for c in channels],
                    "inputs": {c: float(row[c]) for c in ENGINE_COLUMNS},
                }
                for i, (_, row) in enumerate(df.iterrows())
            ],
        },
        "engine",
        forecast_report["model_version"],
        warnings,
    )


@app.get("/api/prognostics/engine/{engine_id}")
def forecast_engine(engine_id: int):
    if not 1 <= engine_id <= 100:
        raise HTTPException(404, "Choose an official test engine from 1 to 100.")
    actual = forecast_report["engine_predictions"][engine_id - 1]["actual_rul"]
    return engine_trace(engine_test[engine_test.engine_id == engine_id], actual)


@app.get("/api/prognostics/sample")
def engine_sample():
    from fastapi.responses import Response

    content = engine_test[engine_test.engine_id == 1].to_csv(index=False)
    return Response(
        content,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=lineguard_engine_sample.csv"},
    )


@app.post("/api/prognostics/upload")
async def upload_engine(file: UploadFile = File(...)):
    data = await file.read(2_000_001)
    if len(data) > 2_000_000:
        raise HTTPException(413, "Engine CSV must be under 2 MB.")
    try:
        reader = csv.DictReader(io.StringIO(data.decode("utf-8-sig")))
        headers = reader.fieldnames or []
        if len(headers) != len(set(headers)):
            raise ValueError("Duplicate column names are not allowed.")
        missing = [c for c in ENGINE_COLUMNS if c not in headers]
        if missing:
            raise ValueError("Missing engine columns: " + ", ".join(missing))
        rows = []
        for line, row in enumerate(reader, 2):
            if line > 2001:
                raise ValueError("Use at most 2,000 cycles for one engine.")
            if None in row:
                raise ValueError(f"Row {line}: unexpected extra CSV fields.")
            clean = {}
            for c in ENGINE_COLUMNS:
                try:
                    v = float(row[c])
                except (ValueError, TypeError):
                    raise ValueError(f"Row {line}: {c} must be numeric.")
                if not math.isfinite(v) or abs(v) > 1e7:
                    raise ValueError(f"Row {line}: {c} must be finite and within ±10 million.")
                if c in ["engine_id", "cycle"] and (not v.is_integer() or v < 1):
                    raise ValueError(f"Row {line}: {c} must be a positive integer.")
                clean[c] = v
            rows.append(clean)
        df = pd.DataFrame(rows)
        if len(df) < 20:
            raise ValueError("At least 20 observed cycles are required.")
        if df.engine_id.nunique() != 1:
            raise ValueError("Upload exactly one engine trajectory at a time.")
        if not df.cycle.is_monotonic_increasing or df.cycle.duplicated().any():
            raise ValueError("Cycles must be unique and ascending.")
        if not (df.cycle.diff().dropna() == 1).all():
            raise ValueError(
                "Observed cycles must be consecutive; missing-cycle imputation is not supported."
            )
    except (ValueError, UnicodeDecodeError, csv.Error) as e:
        raise HTTPException(422, str(e))
    result = engine_trace(
        df,
        None,
        "Uploaded FD001-compatible engine telemetry",
        warnings=domain_warnings(df, "engine_training_ranges"),
    )
    result["ignored_columns"] = [c for c in headers if c not in ENGINE_COLUMNS]
    result["domain_warnings"] = domain_warnings(df, "engine_training_ranges")
    return result


from app.alerting import grouped_alerts
from app.evidence import register_inference
from app.maintenance import router as maintenance_router

operations_path = ROOT / "models/operations_evidence.json"
report["model_version"] = (
    "SKAB / " + hashlib.sha256((ROOT / "models/lineguard.joblib").read_bytes()).hexdigest()[:12]
)
forecast_report["model_version"] = (
    "FD001 / " + hashlib.sha256((ROOT / "models/prognostics.joblib").read_bytes()).hexdigest()[:12]
)


def domain_warnings(frame, key):
    if not operations_path.is_file():
        return ["Training reference unavailable"]
    ranges = json.loads(operations_path.read_text(encoding="utf-8")).get(key, {})
    return [
        name
        for name, (low, high) in ranges.items()
        if ((frame[name] < low) | (frame[name] > high)).mean() >= 0.1
    ]


@app.get("/api/operations/evidence")
def operations_evidence():
    if not operations_path.is_file():
        raise HTTPException(503, "Run python -m app.alerting to generate the comparison.")
    return json.loads(operations_path.read_text(encoding="utf-8"))


@app.get("/api/research/evidence")
def research_evidence():
    path = ROOT / "models/research_evidence.json"
    if not path.is_file():
        raise HTTPException(503, "Research diagnostics unavailable. Rebuild the local artifacts.")
    return json.loads(path.read_text(encoding="utf-8"))


@app.get("/api/benchmark")
def benchmark():
    path = ROOT / "models/benchmark_cmapss.json"
    if not path.is_file():
        raise HTTPException(503, "Run python -m app.benchmark to generate the comparison.")
    return json.loads(path.read_text(encoding="utf-8"))


app.include_router(maintenance_router)
from app.insights_api import router as insights_router  # noqa: E402
from app.policy_api import router as policy_router  # noqa: E402

app.include_router(insights_router)
app.include_router(policy_router)

app.mount("/static", StaticFiles(directory=ROOT / "app/static"), name="static")


@app.get("/")
def index():
    # Version every static URL with the build hash so browsers never mix old scripts with new HTML.
    from fastapi.responses import HTMLResponse

    html = (ROOT / "app/static/index.html").read_text(encoding="utf-8")
    for name in ["style.css", "app.js", "operations.js", "insights.js"]:
        html = html.replace(f"/static/{name}", f"/static/{name}?v={BUILD_VERSION}")
    return HTMLResponse(html, headers={"Cache-Control": "no-cache"})
