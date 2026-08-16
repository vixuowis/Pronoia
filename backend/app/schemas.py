"""Pydantic schemas: REST request/response + SSE event shapes (design.md §7/§8)."""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    case_id: Optional[str] = None
    message: str = Field(..., min_length=1)
    # auto  → 单个 router Agent（主理人 + 工具循环）
    # agent → 直接调单个指定 Agent（agent 字段必填；如缺省则降级为 router）
    # team  → Planner 拆解 + 多专家串行 + 复核 + 提炼
    mode: Literal["auto", "agent", "team"] = "auto"
    # mode="agent" 时指定具体 agent_id（predictor / market_analyst / event_scout 等）
    agent: Optional[str] = None
    # mode="team" 时限制可调度的专家 Agent id 列表（前端可让用户去选）。
    # 缺省=全部；deep_researcher 是硬规则，不会被过滤掉。
    team_members: Optional[list[str]] = None


class CreateCaseRequest(BaseModel):
    title: Optional[str] = None


class SkillInfo(BaseModel):
    name: str
    description: str
    parameters: dict[str, Any]


class AgentInfo(BaseModel):
    id: str
    name: str
    avatar_color: str
    description: str
    persona: str
    skills: list[str]


# ---------------------------------------------------------------- SSE ------
# Every SSE frame is `data: {json}\n\n`. Event types (design.md §7):
#   meta / thinking / token / tool_call / tool_result / artifact /
#   agent_step / case_title / done / error

def sse(event: dict[str, Any]) -> str:
    """Serialize one SSE frame."""
    import json

    return f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"


# ======================================================== Backtest (P0) ======


class CreateBacktestRunRequest(BaseModel):
    """POST /api/bt/runs — 创建新回测 run 请求。"""
    name: str = Field(..., min_length=1, max_length=120, description="显示名")
    runner: Literal["baseline", "team_prompt", "team_full"] = Field(
        ..., description="回测 runner 类型"
    )
    dataset_id: Optional[str] = Field(None, description="bt_datasets.id；若传则 events/labels 从 dataset 取")
    events_path: Optional[str] = Field(None, description="数据集 JSONL 路径，相对路径以 Pronoia 项目根目录为基准，或填绝对路径；与 dataset_id 二选一")
    labels_path: Optional[str] = Field(None, description="labels JSONL 路径（可选，不传则不做 oracle 对照）")
    prompt_variant: str = Field("v0", description="system prompt / agent 编排 变体标识（用于 A/B 对照，例：v0 / optimized-team / ab-1）")
    model_version: Optional[str] = Field(None, description="指定 LLM 模型版本")
    concurrency: int = Field(4, ge=1, le=10, description="并发数，范围 1~10，默认 4；越大越快但 LLM / Rate Limit 压力越高")
    config: dict[str, Any] = Field(default_factory=dict, description="任意额外参数 JSON")


class BacktestRunResponse(BaseModel):
    """回测 Run 详情响应。"""
    id: str
    name: str
    status: str  # pending/running/done/failed
    runner: str
    prompt_variant: Optional[str]
    model_version: Optional[str]
    events_path: str
    labels_path: Optional[str]
    out_path: str
    ckpt_dir: Optional[str]
    concurrency: int
    total_events: int
    done_events: int
    acc_t3_strict: Optional[float]
    acc_t3_strict_lo: Optional[float]
    acc_t3_non_neutral: Optional[float]
    config: Optional[dict[str, Any]]
    created_at: str
    updated_at: str
    started_at: Optional[str]
    finished_at: Optional[str]
    error_msg: Optional[str]


class ListBacktestRunsResponse(BaseModel):
    total: int
    items: list[BacktestRunResponse]


class BacktestPredictionItem(BaseModel):
    id: str
    run_id: str
    event_id: str
    symbol: Optional[str]
    market: Optional[str]
    event_type_l2: Optional[str]
    pred_direction: str
    confidence: Optional[float]
    abstain: bool
    rationale: Optional[str]
    oracle_label_t3: Optional[str]
    oracle_car_t3: Optional[float]
    is_correct_t3: Optional[bool]
    trajectory_ckpt: Optional[str]
    created_at: str


class ListPredictionsResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[BacktestPredictionItem]


class EventCatalogItem(BaseModel):
    """事件目录项：events JSONL 全量条目 + 执行状态 + 已完成的 prediction。

    用于 Detail 页面一开始就展示所有待处理事件（pending/processing/done），
    而不是等每条 prediction 写入 DB 后才显示。
    """
    event_id: str
    symbol: Optional[str] = None
    market: Optional[str] = None
    event_type_l2: Optional[str] = None
    title: Optional[str] = None
    event_time: Optional[str] = None
    source_url: Optional[str] = None
    event_text: Optional[str] = Field(None, description="事件正文摘要（catalog 列表截断约 300 字，完整正文走 detail 接口）")
    # pending: 未开始；processing: 执行中（ckpt 已出现但 DB prediction 未写）；done: 已完成
    status: Literal["pending", "processing", "done"] = "pending"
    prediction: Optional[BacktestPredictionItem] = None


class ListEventCatalogResponse(BaseModel):
    total: int
    items: list[EventCatalogItem]


class BacktestMetricsSnapshot(BaseModel):
    id: int
    run_id: str
    done_count: int
    acc_t3_strict: Optional[float]
    acc_t3_strict_lo: Optional[float]
    acc_t3_non_neutral: Optional[float]
    neutral_ratio: Optional[float]
    created_at: str


class BacktestMetricsSnapshotList(BaseModel):
    items: list[BacktestMetricsSnapshot]


class ActionResponse(BaseModel):
    """简单操作返回。"""
    ok: bool
    message: Optional[str] = None
    run_id: Optional[str] = None


# ---------------------------------------------------------------------------
# UI 辅助接口：prompt 变体 & 事件计数
# ---------------------------------------------------------------------------


class PromptVariantItem(BaseModel):
    """前端 prompt_variant 下拉选项 + 预览。"""
    id: str = Field(..., description="后端 prompt_variant 实际取值（提交 runs 时用这个）")
    label: str = Field(..., description="前端显示名")
    description: str = Field(..., description="一句话描述该变体的差异点")
    market_hint: str = Field(..., description="适用市场说明")
    prompt_text: str = Field(..., description="具体的 system prompt 或 team_full 任务指令全文")


class EventsCountResponse(BaseModel):
    """events.jsonl 事件计数 + 校验结果。"""
    path: str = Field(..., description="解析后的绝对路径")
    valid: bool = Field(..., description="文件存在且通过 load_events 校验")
    count: int = Field(..., description="事件数量；无效时为 0")
    message: Optional[str] = Field(None, description="校验失败时的错误信息")


class BTDatasetResponse(BaseModel):
    """bt_datasets 表的可选项：用于前端 Data list 下拉框。"""
    id: str = Field(..., description="dataset_id，创建 run 时传给 dataset_id")
    name: str = Field(..., description="显示名，例：CN A股半年报 10例")
    path: str = Field(..., description="events JSONL 绝对路径")
    labels_path: Optional[str] = Field(None, description="labels JSONL 绝对路径（可能为空）")
    total_events: int = Field(0, description="事件总数")
    by_market: dict[str, int] = Field(default_factory=dict, description="按 market 统计：{CN:10}")
    by_type: dict[str, int] = Field(default_factory=dict, description="按 event_type_l2 统计")
    by_symbol: dict[str, int] = Field(default_factory=dict, description="按 symbol 统计")
    date_range: Optional[dict] = Field(None, description="事件时间范围：{min, max}")
    created_at: Optional[str] = Field(None, description="首次入库时间")


