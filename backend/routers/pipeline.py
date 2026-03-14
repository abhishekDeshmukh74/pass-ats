"""API routes for inspecting pipeline runs (agent I/O)."""

from fastapi import APIRouter, HTTPException
from backend.services.db import get_pipeline_runs, get_pipeline_run

router = APIRouter()


@router.get("/pipeline-runs")
def list_pipeline_runs(limit: int = 20, skip: int = 0):
    runs = get_pipeline_runs(limit=min(limit, 100), skip=skip)
    return runs


@router.get("/pipeline-runs/{run_id}")
def get_run_detail(run_id: str):
    run = get_pipeline_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Pipeline run not found.")
    return run
