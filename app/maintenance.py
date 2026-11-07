"""Persistent local maintenance findings and printable evidence."""

import json
from datetime import datetime, timezone
from html import escape
from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field, FiniteFloat

router = APIRouter(prefix="/api/tasks")


class Finding(BaseModel):
    asset: str = Field(min_length=1, max_length=120)
    observation: str = Field(min_length=1, max_length=160)
    source: str = Field(min_length=1, max_length=160)
    reason: str = Field(min_length=1, max_length=300)
    model_version: str = Field(min_length=1, max_length=140)
    priority: Literal["Routine", "Inspect soon"]
    reading: str = Field(min_length=1, max_length=300)
    series: list[FiniteFloat] = Field(min_length=1, max_length=100)
    notes: str = Field(default="", max_length=2000)


class EvidenceReference(BaseModel):
    inference_id: str = Field(min_length=64, max_length=64)
    index: int = Field(ge=0)
    horizon: int = Field(default=30, ge=5, le=125)
    notes: str = Field(default="", max_length=2000)


class Progress(BaseModel):
    status: Literal["acknowledged", "completed", "cancelled"]
    outcome: str = Field(default="", max_length=2000)


def connect():
    from app.main import connect as database

    return database()


def prepare(connection):
    connection.execute("""
        CREATE TABLE IF NOT EXISTS maintenance_task (
            id INTEGER PRIMARY KEY,
            finding_key TEXT NOT NULL,
            snapshot TEXT NOT NULL,
            status TEXT NOT NULL,
            outcome TEXT NOT NULL DEFAULT '',
            created TEXT NOT NULL,
            updated TEXT NOT NULL
        )
    """)
    old_index = connection.execute(
        "SELECT sql FROM sqlite_master WHERE name='one_active_finding'"
    ).fetchone()
    if old_index and "cancelled" not in old_index["sql"]:
        connection.execute("DROP INDEX one_active_finding")
    connection.execute("""
        CREATE TABLE IF NOT EXISTS task_history (
            id INTEGER PRIMARY KEY, task_id INTEGER NOT NULL,
            status TEXT NOT NULL, outcome TEXT NOT NULL, created TEXT NOT NULL
        )
    """)
    connection.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS one_active_finding
        ON maintenance_task(finding_key) WHERE status NOT IN ('completed', 'cancelled')
    """)


def unpack(row):
    return {
        **json.loads(row["snapshot"]),
        **{field: row[field] for field in ("id", "status", "created", "updated", "outcome")},
    }


@router.get("")
def list_tasks():
    with connect() as connection:
        prepare(connection)
        return [
            unpack(row)
            for row in connection.execute("SELECT * FROM maintenance_task ORDER BY id DESC")
        ]


@router.post("", status_code=201)
def create_task(finding: EvidenceReference | Finding):
    now = datetime.now(timezone.utc).isoformat()
    if isinstance(finding, EvidenceReference):
        from app.evidence import snapshot

        payload = snapshot(finding)
        key = json.dumps([payload["asset_id"], payload["finding_id"]])
    else:
        payload = {**finding.model_dump(), "schema_version": 1, "verified": False}
        key = json.dumps([finding.asset, finding.source, finding.observation])
    with connect() as connection:
        prepare(connection)
        cursor = connection.execute(
            """
            INSERT OR IGNORE INTO maintenance_task
            (finding_key, snapshot, status, created, updated) VALUES (?, ?, 'open', ?, ?)
        """,
            (key, json.dumps(payload, allow_nan=False), now, now),
        )
        if not cursor.rowcount:
            raise HTTPException(409, "An active task already exists for this observation.")
        row = connection.execute(
            "SELECT * FROM maintenance_task WHERE id = ?", (cursor.lastrowid,)
        ).fetchone()
        connection.execute(
            "INSERT INTO task_history(task_id,status,outcome,created) VALUES (?,?,?,?)",
            (row["id"], row["status"], row["outcome"], row["updated"]),
        )
        connection.commit()
        return unpack(row)


@router.patch("/{task_id}")
def progress_task(task_id: int, progress: Progress):
    if progress.status in ("completed", "cancelled") and not progress.outcome.strip():
        raise HTTPException(422, "Enter the inspection outcome or cancellation reason.")
    previous = {"acknowledged": "open", "completed": "acknowledged", "cancelled": "open"}[
        progress.status
    ]
    with connect() as connection:
        prepare(connection)
        cursor = connection.execute(
            """
            UPDATE maintenance_task SET status = ?, outcome = ?, updated = ?
            WHERE id = ? AND (status = ? OR (? = 'cancelled' AND status = 'acknowledged'))
        """,
            (
                progress.status,
                progress.outcome.strip(),
                datetime.now(timezone.utc).isoformat(),
                task_id,
                previous,
                progress.status,
            ),
        )
        row = connection.execute(
            "SELECT * FROM maintenance_task WHERE id = ?", (task_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(404, "Task not found.")
        if not cursor.rowcount:
            raise HTTPException(409, "Refresh the task before changing its status.")
        connection.execute(
            "INSERT INTO task_history(task_id,status,outcome,created) VALUES (?,?,?,?)",
            (row["id"], row["status"], row["outcome"], row["updated"]),
        )
        connection.commit()
        return unpack(row)


@router.get("/{task_id}/report", response_class=HTMLResponse)
def report(task_id: int):
    with connect() as connection:
        prepare(connection)
        row = connection.execute(
            "SELECT * FROM maintenance_task WHERE id = ?", (task_id,)
        ).fetchone()
        history = list(
            connection.execute(
                "SELECT status,outcome,created FROM task_history WHERE task_id=? ORDER BY id",
                (task_id,),
            )
        )
    if row is None:
        raise HTTPException(404, "Task not found.")
    task = unpack(row)
    values = task["series"]
    low, high = min(values), max(values)
    points = " ".join(
        f"{10 + 580 * index / max(1, len(values) - 1):.2f},"
        f"{100 - 90 * (value - low) / (high - low or 1):.2f}"
        for index, value in enumerate(values)
    )
    fields = (
        ("Observation", "observation"),
        ("Data source", "source"),
        ("Assessment", "reading"),
        ("Recommended investigation", "reason"),
        ("Model version", "model_version"),
        ("Priority", "priority"),
        ("Status", "status"),
        ("Recorded at", "created"),
        ("Notes", "notes"),
        ("Inspection outcome", "outcome"),
    )
    extra = (
        "<h2>Provenance and quality</h2><p>"
        + escape(
            f"Schema {task.get('schema_version', 1)} · Server verified {task.get('verified', False)} · "
            f"Policy {task.get('policy_version', 'Legacy')} · "
            f"Warnings {', '.join(task.get('quality_warnings', [])) or 'None recorded'}"
        )
        + "</p>"
    )
    extra += (
        "<p>Inference evidence digest "
        + escape(task.get("inference_id", "Legacy snapshot"))
        + "</p>"
    )
    extra += (
        "<h2>Task history</h2><ul>"
        + "".join(
            f"<li>{escape(item['created'])} · {escape(item['status'])} · {escape(item['outcome'])}</li>"
            for item in history
        )
        + "</ul>"
    )
    positions = task.get("positions", [])
    extra += (
        "<p>Observation extent "
        + escape(f"{positions[0]} to {positions[-1]}" if positions else "Legacy sample order")
        + "</p>"
    )
    extra += (
        "<details><summary>Structured sensor evidence</summary><pre>"
        + escape(
            json.dumps(
                {
                    "current": task.get("sensor_evidence", {}),
                    "causal_input_window": task.get("input_window", []),
                },
                indent=2,
            )
        )
        + "</pre></details>"
    )
    details = "".join(
        f"<dt>{label}</dt><dd>{escape(task[key] or 'None recorded')}</dd>" for label, key in fields
    )
    return HTMLResponse(
        f"""<!doctype html><html lang="en"><meta charset="utf-8">
<title>LineGuard task {task_id}</title><style>
body{{font:16px system-ui;max-width:760px;margin:3rem auto;padding:0 1rem}}
dt{{font-weight:bold;margin-top:1rem}}dd{{margin:0;white-space:pre-wrap}}
svg{{width:100%;border:1px solid #aaa}}@media print{{body{{margin:0}}}}
</style><h1>{escape(task['asset'])}</h1><p>LineGuard evidence snapshot · Task {task_id}</p>
<dl>{details}</dl>{extra}<h2>Assessment history</h2>
<svg viewBox="0 0 600 130" role="img" aria-label="Saved assessment trend">
<polyline points="{points}" fill="none" stroke="#176a59" stroke-width="2"/>
<text x="12" y="12" font-size="10">{high:.2f}</text><text x="12" y="102" font-size="10">{low:.2f}</text>
<text x="12" y="124" font-size="10">{escape(str(positions[0]) if positions else 'First sample')}</text>
<text x="588" y="124" text-anchor="end" font-size="10">{escape(str(positions[-1]) if positions else 'Last sample')}</text></svg>
<p>Saved range {low:.2f} to {high:.2f} {escape(task.get('unit','assessment units'))}. Points are spaced by observation order; exact positions are retained in the snapshot.</p>
<p>Research demonstration. Benchmark evidence supports inspection planning.
Any transfer to operational equipment requires validation for that equipment.</p></html>""",
        headers={"Content-Disposition": f'attachment; filename="lineguard-task-{task_id}.html"'},
    )
