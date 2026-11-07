"""Maintenance-policy simulation endpoint."""

from typing import Optional
from fastapi import APIRouter, HTTPException
from app.policy import compare

router = APIRouter(prefix="/api/policy")


@router.get("")
def policy(
    cost_preventive: float = 1.0,
    cost_failure: float = 10.0,
    lead: int = 0,
    threshold: Optional[float] = None,
    use_lower_bound: bool = False,
):
    try:
        return compare(cost_preventive, cost_failure, lead, threshold, use_lower_bound)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
