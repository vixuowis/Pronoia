"""Pronoia backend entry: FastAPI app (CORS, routes, static SPA mount)."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import config, db
from .routes import cases, chat, logic, meta

app = FastAPI(title="Pronoia", version="3.8.3", docs_url="/api/docs")

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


@app.on_event("startup")
def _startup() -> None:
    db.init_db()


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
