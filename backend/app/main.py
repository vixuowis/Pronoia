"""Pronoia backend entry: FastAPI app (CORS, routes, static SPA mount)."""
from __future__ import annotations

import time
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from . import config, db
from .log_bus import publish
from .routes import admin, arena, backtest, cases, chat, logic, meta

app = FastAPI(title="Pronoia", version="3.12.1", docs_url="/api/docs")


class TimingMiddleware(BaseHTTPMiddleware):
    """记录每个请求的耗时，慢请求打标签（SLOW >3s / VSLOW >10s）。

    用途：诊断前端卡住时，从日志一眼看到哪个后端请求慢。
    """

    async def dispatch(self, request: Request, call_next):
        start = time.time()
        try:
            response = await call_next(request)
        except Exception:
            dur = time.time() - start
            path = request.url.path
            print(
                f"TIMING {request.client.host if request.client else '-'} "
                f'"{request.method} {path}" ERR - {dur:.2f}s',
                flush=True,
            )
            publish(
                f"TIMING {request.client.host if request.client else '-'} "
                f'"{request.method} {path}" ERR - {dur:.2f}s'
            )
            raise

        dur = time.time() - start
        tag = ""
        if dur > 10:
            tag = " [VSLOW]"
        elif dur > 3:
            tag = " [SLOW]"
        path = request.url.path
        # 不记 /api/health（太频繁，会刷屏）
        if path != "/api/health":
            print(
                f"TIMING {request.client.host if request.client else '-'}:{request.client.port if request.client else '-'} "
                f'"{request.method} {path}" {response.status_code} - {dur:.2f}s{tag}',
                flush=True,
            )
            publish(
                f"TIMING {request.client.host if request.client else '-'}:{request.client.port if request.client else '-'} "
                f'"{request.method} {path}" {response.status_code} - {dur:.2f}s{tag}'
            )
        return response


app.add_middleware(TimingMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(meta.router)
app.include_router(cases.router)
app.include_router(chat.router)
app.include_router(logic.router)
app.include_router(backtest.router)
app.include_router(arena.router)
app.include_router(admin.router)


@app.on_event("startup")
def _startup() -> None:
    db.init_db()
    # 自动扫描 <PROJECT_ROOT>/backtesting 目录，把 events/labels JSONL 对注册进 bt_datasets，
    # 保证「创建回测」的数据源始终来自 backtesting 目录，而不是数据库里残留的旧绝对路径。
    from .event_backtest.application import discover_backtesting_datasets

    try:
        datasets = discover_backtesting_datasets()
        print(f"[startup] Discovered {len(datasets)} backtesting dataset(s): {list(datasets.keys())}", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"[startup] discover_backtesting_datasets failed: {exc}", flush=True)


class SPAStaticFiles(StaticFiles):
    """StaticFiles with SPA fallback: unknown non-/api paths -> index.html."""

    async def get_response(self, path: str, scope):  # type: ignore[override]
        from starlette.exceptions import HTTPException as StarletteHTTPException

        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code == 404:
                index = Path(self.directory) / "index.html"
                if index.exists():
                    return FileResponse(index)
            raise


if config.FRONTEND_DIST.exists():
    app.mount("/", SPAStaticFiles(directory=str(config.FRONTEND_DIST), html=True), name="spa")
