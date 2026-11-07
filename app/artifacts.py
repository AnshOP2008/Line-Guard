"""Local artifact integrity and atomic individual-file replacement."""

import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
FILES = [
    "lineguard.joblib",
    "lineguard_metrics.json",
    "prognostics.joblib",
    "prognostics_metrics.json",
    "operations_evidence.json",
    "research_evidence.json",
    "policy_oof.json",
    "explain_reference.json",
]


def atomic_json(path, value):
    path = Path(path)
    fd, temporary = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, allow_nan=False)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def atomic_joblib(path, value):
    import joblib

    path = Path(path)
    fd, temporary = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    os.close(fd)
    try:
        joblib.dump(value, temporary)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def file_fingerprint(path):
    content = path.read_bytes()
    if path.suffix in {".py", ".json", ".csv", ".txt"}:
        content = content.replace(b"\r\n", b"\n")
    return hashlib.sha256(content).hexdigest()


def fingerprints():
    return {
        name: file_fingerprint(ROOT / "models" / name) for name in FILES
    }


def source_fingerprints():
    paths = [
        ROOT / "app" / name
        for name in [
            "train.py",
            "prognostics.py",
            "alerting.py",
            "research.py",
            "policy.py",
            "explain.py",
        ]
    ]
    paths += sorted((ROOT / "data/SKAB/data").rglob("*.csv"))
    paths += sorted((ROOT / "data/CMAPSS/FD001").glob("*.txt"))
    return {
        path.relative_to(ROOT).as_posix(): file_fingerprint(path)
        for path in paths
        if path.is_file()
    }


def build_version():
    paths = sorted((ROOT / "app").glob("*.py")) + sorted((ROOT / "app/static").glob("*"))
    content = b"".join(path.read_bytes() for path in paths if path.is_file())
    content += (
        (ROOT / "models/manifest.json").read_bytes()
        if (ROOT / "models/manifest.json").exists()
        else b""
    )
    return hashlib.sha256(content).hexdigest()[:16]


def verify():
    try:
        manifest = json.loads((ROOT / "models/manifest.json").read_text())
        return (
            manifest["schema"] == 1
            and manifest["sha256"] == fingerprints()
            and manifest.get("sources") == source_fingerprints()
        )
    except (OSError, ValueError, KeyError):
        return False


if __name__ == "__main__":
    if "--write" in sys.argv:
        atomic_json(
            ROOT / "models/manifest.json",
            {"schema": 1, "sha256": fingerprints(), "sources": source_fingerprints()},
        )
    elif not verify():
        raise SystemExit("Model artifact set is incomplete or changed. Run launch.ps1 -Rebuild.")
