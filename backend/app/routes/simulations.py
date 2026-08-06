"""Asynchronous scenario simulation routes backed by FEVER-MiroFish gateway."""
from __future__ import annotations

import threading
from typing import Any, Literal

import requests
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .. import config, db

router = APIRouter(prefix="/api", tags=["simulations"])
TERMINAL = {"completed", "partial", "failed", "cancelled"}
_sync_lock = threading.RLock()


class StartSimulationRequest(BaseModel):
    source_graph_artifact_id: str = Field(..., min_length=1)
    question: str | None = None
    as_of: str | None = None
    horizon_days: int = Field(default=30, ge=1, le=365)
    mode: Literal["quick"] = "quick"
    max_actors: int = Field(default=6, ge=4, le=8)
    market: dict[str, Any] | None = None


def _gateway(method: str, path: str, **kwargs: Any) -> dict[str, Any]:
    try:
        response = requests.request(
            method,
            f"{config.SIMULATION_GATEWAY_URL}{path}",
            timeout=config.SIMULATION_GATEWAY_TIMEOUT,
            **kwargs,
        )
    except requests.RequestException as error:
        raise HTTPException(status_code=503, detail=f"推演网关不可用: {error}") from error
    if response.status_code >= 400:
        try:
            detail = response.json().get("detail")
        except (ValueError, AttributeError):
            detail = response.text[:300]
        raise HTTPException(status_code=502, detail=f"推演网关拒绝请求: {detail}")
    return response.json()


def _public(job: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in job.items() if key != "request_payload"}


def _sync(job: dict[str, Any]) -> dict[str, Any]:
    # Multiple tabs may poll together. Serialize the terminal write so one
    # gateway result creates exactly one FEVER artifact.
    with _sync_lock:
        job = db.get_simulation_job(job["id"]) or job
        if job["status"] in TERMINAL and (job["status"] != "completed" or job.get("artifact_id")):
            return job
        remote = _gateway("GET", f"/v1/simulations/{job['gateway_job_id']}")
        artifact_id = job.get("artifact_id")
        if remote.get("status") in {"completed", "partial"} and remote.get("result") and not artifact_id:
            request_payload = job["request_payload"]
            mode_cn = "快速" if request_payload.get("mode") == "quick" else "校准"
            artifact = db.add_artifact(
                job["case_id"], None, "simulation", f"{mode_cn}多智能体情景推演", remote["result"]
            )
            artifact_id = artifact["id"]
        return db.update_simulation_job(
            job["id"],
            status=remote.get("status", job["status"]),
            stage=remote.get("stage", job["stage"]),
            progress=float(remote.get("progress", job["progress"])),
            error=remote.get("error"),
            artifact_id=artifact_id,
            finished_at=remote.get("finished_at"),
        ) or job


@router.post("/cases/{case_id}/simulations", status_code=202)
def start_simulation(case_id: str, request: StartSimulationRequest):
    if not db.get_case(case_id):
        raise HTTPException(status_code=404, detail="case not found")
    graph = db.get_artifact(case_id, request.source_graph_artifact_id)
    if not graph or graph.get("kind") != "graph":
        raise HTTPException(status_code=404, detail="source evidence graph not found")
    payload = request.model_dump()
    payload["case_id"] = case_id
    payload["evidence_graph"] = graph["payload"]
    # Stable default is essential for idempotency: the same immutable graph
    # and parameters must compile to the same spec hash on repeated clicks.
    payload["as_of"] = request.as_of or graph["created_at"]
    remote = _gateway("POST", "/v1/simulations", json=payload)
    job = db.create_simulation_job(
        case_id,
        request.source_graph_artifact_id,
        remote,
        {key: value for key, value in payload.items() if key != "evidence_graph"},
    )
    return _public(_sync(job))


@router.get("/simulations/{job_id}")
def get_simulation(job_id: str):
    job = db.get_simulation_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="simulation job not found")
    return _public(_sync(job))


@router.post("/simulations/{job_id}/cancel")
def cancel_simulation(job_id: str):
    job = db.get_simulation_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="simulation job not found")
    remote = _gateway("POST", f"/v1/simulations/{job['gateway_job_id']}/cancel")
    updated = db.update_simulation_job(
        job_id,
        status=remote.get("status", job["status"]),
        stage=remote.get("stage", job["stage"]),
        progress=float(remote.get("progress", job["progress"])),
        error=remote.get("error"),
        finished_at=remote.get("finished_at"),
    )
    return _public(updated or job)


@router.get("/cases/{case_id}/simulations")
def list_simulations(case_id: str):
    if not db.get_case(case_id):
        raise HTTPException(status_code=404, detail="case not found")
    return [_public(job) for job in db.list_simulation_jobs(case_id)]
