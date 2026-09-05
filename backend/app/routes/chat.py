"""POST /api/chat — SSE 对话流 (design.md §6.2/§7)."""
from __future__ import annotations

import asyncio
from typing import AsyncIterator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from .. import config, db
from ..agents.roster import AGENTS, get_agent, system_prompt
from ..agents.team import run_team
from ..llm import complete_text, run_agent
from ..schemas import ChatRequest, sse

router = APIRouter(prefix="/api", tags=["chat"])


def _history_for_llm(case_id: str) -> list[dict]:
    """该 case 最近 CONTEXT_MESSAGES 条消息 → LLM 上下文（user/assistant 纯文本）。"""
    msgs = db.list_messages(case_id, limit=config.CONTEXT_MESSAGES)
    out = []
    for m in msgs:
        if m["role"] in ("user", "assistant") and (m.get("content") or "").strip():
            out.append({"role": m["role"], "content": m["content"]})
    return out


async def _gen_title(question: str) -> str:
    import re

    fallback = re.sub(r"\s+", "", question or "")[:15] or "未命名研究"
    try:
        title = await complete_text(
            "你是标题生成器。用不超过15个字的中文概括用户的研究问题，只输出标题本身，不要标点收尾。",
            question[:300],
            max_tokens=800,  # reasoning 模型会消耗部分预算在思考上，给足余量
        )
        title = (title or "").strip().strip("「」\"'。 \n")
        return title[:20] or fallback
    except Exception:  # noqa: BLE001
        return fallback


async def _chat_stream(req: ChatRequest) -> AsyncIterator[str]:
    case_id = req.case_id
    case = db.get_case(case_id) if case_id else None
    if case is None:
        case = db.create_case()
    case_id = case["id"]

    # 1) 落库 user message；上下文取最近 12 条（含本条）
    is_first = db.count_messages(case_id, role="user") == 0
    db.add_message(case_id, role="user", content=req.message)
    history = _history_for_llm(case_id)

    message_id = db.new_id()
    state = {"content": "", "tool_trace": [], "rounds": 0}

    async def artifact_store(kind: str, title: str, payload):
        return await asyncio.to_thread(
            db.add_artifact, case_id, message_id, kind, title, payload
        )

    yield sse({"type": "meta", "case_id": case_id, "mode": req.mode, "agent": req.agent,
               "team_members": req.team_members})
    try:
        if req.mode == "team":
            # team 模式：history 传给 synthesize；问题原文作为规划输入
            hist_for_team = history[:-1] if history else []  # 排除当前 user 消息
            async for ev in run_team(req.message, hist_for_team, state, artifact_store,
                                     team_members=req.team_members):
                yield sse(ev)
        else:
            # mode == "agent" | "auto"：单 Agent 工具循环
            # 优先级：req.agent → "router"（向后兼容）
            agent_id = (req.agent or "").strip() or "router"
            agent_def = get_agent(agent_id)
            if agent_def is None:
                valid = ", ".join(sorted(AGENTS.keys()))
                yield sse({"type": "error",
                           "message": f"未知 Agent「{agent_id}」。可用: {valid}"})
                return
            messages = [{"role": "system", "content": system_prompt(agent_id)}] + history
            async for ev in run_agent(agent_id, messages, agent_def=agent_def,
                                      state=state, artifact_store=artifact_store,
                                      max_rounds=config.AUTO_MAX_ROUNDS):
                yield sse(ev)

        # 2) 落库 assistant message（content + tool_trace JSON）
        # agent 模式下记录实际调用的 agent_id
        record_agent = req.agent if req.mode == "agent" and req.agent else "router"
        db.add_message(case_id, role="assistant", agent=record_agent,
                       content=state["content"], tool_trace=state["tool_trace"] or None,
                       message_id=message_id)

        # 3) 首条消息 → 生成 case 标题
        if is_first:
            title = await _gen_title(req.message)
            await asyncio.to_thread(db.update_case_title, case_id, title)
            yield sse({"type": "case_title", "title": title})

        yield sse({"type": "done", "case_id": case_id, "message_id": message_id})
    except asyncio.CancelledError:
        # 前端断开 / 用户主动停止：尽力保存已产出内容，然后让 ASGI 正常收尾
        # 不 yield error（连接已断，前端收不到），只落库 + 日志
        try:
            if state["content"] or state["tool_trace"]:
                err_agent = req.agent if req.mode == "agent" and req.agent else "router"
                db.add_message(case_id, role="assistant", agent=err_agent,
                               content=state["content"],
                               tool_trace=state["tool_trace"] or None,
                               message_id=message_id)
        except Exception:  # noqa: BLE001
            pass
        print(f"CHAT case={case_id} cancelled by client (rounds={state.get('rounds', 0)}, "
              f"content_len={len(state.get('content', ''))})", flush=True)
        raise
    except Exception as e:  # noqa: BLE001
        # 尽力保留已产出内容
        try:
            if state["content"] or state["tool_trace"]:
                err_agent = req.agent if req.mode == "agent" and req.agent else "router"
                db.add_message(case_id, role="assistant", agent=err_agent,
                               content=state["content"],
                               tool_trace=state["tool_trace"] or None,
                               message_id=message_id)
        except Exception:  # noqa: BLE001
            pass
        yield sse({"type": "error", "message": f"{type(e).__name__}: {e}"})


@router.post("/chat")
async def chat(req: ChatRequest):
    return StreamingResponse(
        _chat_stream(req),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
