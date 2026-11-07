"""Insight endpoints: per-prediction RUL explanation."""

from typing import Optional
from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/api/insights", tags=["insights"])


@router.get("/engine/{engine_id}/explain")
def explain_engine(engine_id: int, cycle: Optional[int] = Query(default=None, ge=1)):
    if not 1 <= engine_id <= 100:
        raise HTTPException(404, "Choose an official test engine from 1 to 100.")
    from app import explain
    from app.prognostics import load

    df = load("test_FD001.txt")
    df = df[df.engine_id == engine_id]
    if cycle is not None and cycle not in set(df.cycle):
        raise HTTPException(404, f"Cycle {cycle} was not observed for engine {engine_id}.")
    return explain.explain_engine_at(df, cycle)
