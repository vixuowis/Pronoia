"""Admin 路由：后端日志实时推送（SSE）。

GET /api/admin/live-log
  - 订阅 log_bus.subscribe()，返回 text/event-stream
  - 每条日志：data: {"ts": "...", "msg": "..."}\n\n
  - 10s 心跳（: heartbeat 注释）防 proxy 超时
  - 客户端断开时 CancelledError 触发 subscribe 的 finally 清理 subscriber
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

from fastapi import APIRouter
from starlette.responses import StreamingResponse

from ..log_bus import subscribe

router = APIRouter(prefix="/api/admin", tags=["admin"])


async def _event_stream():
    try:
        async for msg in subscribe():
            if msg is None:
                # 10s 心跳保活：SSE 注释行，不会被前端 EventSource 当作事件
                yield ": heartbeat\n\n"
            else:
                ts = datetime.now(timezone.utc).isoformat()
                payload = json.dumps({"ts": ts, "msg": msg}, ensure_ascii=False)
                yield f"data: {payload}\n\n"
    except asyncio.CancelledError:
        # 客户端断开：交由 subscribe 的 finally 清理 subscriber
        raise


@router.get("/live-log")
async def live_log():
    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # 关闭 nginx 缓冲，保证实时推送
            "Connection": "keep-alive",
        },
    )
