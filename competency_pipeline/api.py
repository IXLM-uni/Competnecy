# -*- coding: utf-8 -*-
"""
FastAPI backend для Competency Pipeline с SSE streaming.

Endpoints:
    POST /api/pipeline/run   — запуск pipeline, SSE stream
    GET  /api/artifacts       — список артефактов
    GET  /api/artifacts/{name} — содержимое артефакта
"""

import asyncio
import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

logger = logging.getLogger(__name__)

app = FastAPI(title="Competency Pipeline API", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

ARTIFACTS_DIR = Path(__file__).resolve().parent.parent / "artifacts"


class PipelineRequest(BaseModel):
    role: str
    semesters: int = 4
    skip_telegram: bool = False
    skip_reddit: bool = True


@app.post("/api/pipeline/run")
async def run_pipeline(req: PipelineRequest):
    """Запуск pipeline со streaming SSE events."""

    queue: asyncio.Queue = asyncio.Queue()

    async def _run_in_background():
        """Запускает pipeline и кладёт events в queue."""
        from .llm_helpers import set_sse_queue, emit_sse
        from .pipeline_v2 import PipelineV2

        set_sse_queue(queue)

        try:
            pipeline = PipelineV2(
                role=req.role,
                artifacts_dir=str(ARTIFACTS_DIR),
                semesters=req.semesters,
            )
            await pipeline.run()
        except Exception as exc:
            logger.error("Pipeline ОШИБКА: %s", exc)
            await emit_sse("error", {"message": str(exc)})
            await emit_sse("done", {"success": False, "error": str(exc)})
        finally:
            set_sse_queue(None)
            # Sentinel: сигнал завершения SSE stream
            await queue.put(None)

    async def _event_generator():
        """Читает events из queue и отдаёт как SSE."""
        task = asyncio.create_task(_run_in_background())

        try:
            while True:
                event = await queue.get()
                if event is None:
                    break  # Pipeline завершён

                event_type = event.get("event", "message")
                data = json.dumps(event.get("data", {}), ensure_ascii=False)
                yield {"event": event_type, "data": data}
        except asyncio.CancelledError:
            task.cancel()
            raise

    return EventSourceResponse(_event_generator())


@app.get("/api/artifacts")
async def list_artifacts():
    """Список артефактов в директории."""
    if not ARTIFACTS_DIR.exists():
        return JSONResponse({"artifacts": []})

    artifacts = []
    for f in sorted(ARTIFACTS_DIR.glob("*.md")):
        artifacts.append({
            "name": f.name,
            "size": f.stat().st_size,
            "modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
        })

    return JSONResponse({"artifacts": artifacts})


@app.get("/api/artifacts/{name}")
async def get_artifact(name: str):
    """Содержимое конкретного артефакта."""
    path = ARTIFACTS_DIR / name
    if not path.exists() or not path.suffix == ".md":
        return JSONResponse({"error": "Not found"}, status_code=404)

    content = path.read_text(encoding="utf-8")
    return JSONResponse({"name": name, "content": content})


@app.get("/api/health")
async def health():
    return {"status": "ok", "artifacts_dir": str(ARTIFACTS_DIR)}
