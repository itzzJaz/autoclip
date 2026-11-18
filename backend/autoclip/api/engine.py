"""Engine lifecycle endpoints — what the Start / Stop control calls."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException

from ..engine import EngineBusy, EngineError, EngineStatus, engine
from .schemas import EngineOut, EngineStopIn

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/engine", tags=["engine"])


def _out(status: EngineStatus) -> EngineOut:
    return EngineOut(
        state=status.state,
        error=status.error,
        model=status.model,
        model_loaded=status.model_loaded,
        started_at=status.started_at,
        active_job_id=status.active_job_id,
        queued=status.queued,
        ffmpeg_version=status.ffmpeg_version,
        ready=status.ready,
    )


def _http_error(exc: EngineError) -> HTTPException:
    status_code = 409 if isinstance(exc, EngineBusy) else 500
    return HTTPException(
        status_code=status_code,
        detail={"message": str(exc), "hint": exc.hint},
    )


@router.get("", response_model=EngineOut)
async def engine_status() -> EngineOut:
    return _out(engine.status())


@router.post("/start", response_model=EngineOut)
async def engine_start() -> EngineOut:
    """Load the configured model and allow the worker to run.

    The load happens in a worker thread: model construction is blocking, and the
    health check already reports the transition as ``starting`` while it runs.
    """
    try:
        return _out(await asyncio.to_thread(engine.start, preload=True))
    except EngineError as exc:
        raise _http_error(exc) from exc


@router.post("/stop", response_model=EngineOut)
async def engine_stop(payload: EngineStopIn | None = None) -> EngineOut:
    force = payload.force if payload is not None else False
    try:
        return _out(await asyncio.to_thread(engine.stop, force=force))
    except EngineError as exc:
        raise _http_error(exc) from exc
