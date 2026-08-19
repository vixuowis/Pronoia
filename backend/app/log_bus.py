"""全局日志广播器：pub/sub + ring buffer + 线程安全 publish。

- publish(msg): 同步函数，print 到 stdout + 广播给所有 subscriber（可被非 async 代码调用）
- subscribe(): async generator，先回放 ring buffer 历史再流式推送，10s 心跳保活
- ring buffer 保留最近 1000 条，新连接先一次性收到历史
- 线程安全：subscriber 是 asyncio.Queue，publish 通过 loop.call_soon_threadsafe 投递
"""
from __future__ import annotations

import asyncio
import threading
from collections import deque
from typing import Optional, Set, Tuple

_BUFFER_SIZE = 1000
_HEARTBEAT_SEC = 10.0
_QUEUE_MAXSIZE = 1000  # 每个 subscriber 的队列上限，慢消费者丢消息

_lock = threading.Lock()
_buffer: "deque[str]" = deque(maxlen=_BUFFER_SIZE)
# 每个 subscriber: (queue, 所属 event loop)
_subscribers: Set[Tuple[asyncio.Queue, asyncio.AbstractEventLoop]] = set()


def _safe_put(q: asyncio.Queue, msg: str) -> None:
    """在 subscriber 的 event loop 里执行 put_nowait；队列满则丢弃（慢消费者）。"""
    try:
        q.put_nowait(msg)
    except asyncio.QueueFull:
        pass


def publish(msg: str) -> None:
    """同步发布一条日志：print 到 stdout + 写入 ring buffer + 广播给所有 subscriber。

    线程安全：可被 sync/async 代码、任意线程调用。subscriber 是 asyncio.Queue，
    通过其所属 loop 的 call_soon_threadsafe 投递，避免跨线程直接操作 queue。
    """
    print(msg, flush=True)
    with _lock:
        _buffer.append(msg)
        subs = list(_subscribers)
    for q, loop in subs:
        try:
            loop.call_soon_threadsafe(_safe_put, q, msg)
        except RuntimeError:
            # subscriber 的 loop 已关闭，忽略（会在 subscribe 的 finally 里清理）
            pass


async def subscribe():
    """订阅日志流。先一次性回放 ring buffer 历史，再流式推送新日志。

    10s 无新消息则 yield None 作为心跳（SSE 端点据此发送 keepalive）。
    客户端断开（CancelledError）时 finally 清理 subscriber，避免泄漏。
    """
    loop = asyncio.get_running_loop()
    q: asyncio.Queue = asyncio.Queue(maxsize=_QUEUE_MAXSIZE)
    # 原子地快照历史 + 注册 subscriber：避免 gap 与重复
    # - 注册前发布的消息已在历史快照里（yield 历史）
    # - 注册后发布的消息进队列（yield 队列）
    with _lock:
        history = list(_buffer)
        _subscribers.add((q, loop))
    try:
        for msg in history:
            yield msg
        while True:
            try:
                msg: Optional[str] = await asyncio.wait_for(q.get(), timeout=_HEARTBEAT_SEC)
                yield msg
            except asyncio.TimeoutError:
                # 10s 心跳保活，防 proxy 超时
                yield None
    finally:
        with _lock:
            _subscribers.discard((q, loop))
