"""FEVER backend configuration: env loading & tunables."""
from __future__ import annotations

import os
from pathlib import Path

# akshare 部分接口用 tqdm 打进度条，污染服务日志，全局禁用
os.environ.setdefault("TQDM_DISABLE", "1")

from dotenv import load_dotenv

# backend/app/config.py -> app -> backend -> FEVER project root
_BACKEND_DIR = Path(__file__).resolve().parents[1]
_PROJECT_ROOT = _BACKEND_DIR.parent

# Project-root .env first (shared, contains the real ARK_API_KEY),
# then backend-local .env may override.
load_dotenv(_PROJECT_ROOT / ".env", override=False)
load_dotenv(_BACKEND_DIR / ".env", override=True)

ARK_API_URL: str = os.getenv("ARK_API_URL", "https://ark.cn-beijing.volces.com/api/coding/v3")
ARK_API_KEY: str = os.getenv("ARK_API_KEY", "")
ARK_MODEL: str = os.getenv("ARK_MODEL", "deepseek-v4-flash")

DB_PATH: str = os.getenv("FEVER_DB_PATH", str(_BACKEND_DIR / "fever.db"))

# Long-running actor simulation is isolated behind an asynchronous gateway.
SIMULATION_GATEWAY_URL: str = os.getenv(
    "FEVER_SIMULATION_GATEWAY_URL", "http://127.0.0.1:5010"
).rstrip("/")
SIMULATION_GATEWAY_TIMEOUT: float = float(
    os.getenv("FEVER_SIMULATION_GATEWAY_TIMEOUT", "15")
)

# Skill execution guardrails (design.md §2/§4)
SKILL_TIMEOUT: float = float(os.getenv("FEVER_SKILL_TIMEOUT", "60"))  # seconds per skill call
TOOL_RESULT_MAX_CHARS: int = int(os.getenv("FEVER_TOOL_RESULT_MAX_CHARS", "4000"))

# Agent loop guardrails (design.md §6)
AUTO_MAX_ROUNDS: int = int(os.getenv("FEVER_AUTO_MAX_ROUNDS", "8"))
TEAM_MAX_ROUNDS: int = int(os.getenv("FEVER_TEAM_MAX_ROUNDS", "5"))
CONTEXT_MESSAGES: int = int(os.getenv("FEVER_CONTEXT_MESSAGES", "12"))

# LLM request timeout (per streaming round)
LLM_TIMEOUT: float = float(os.getenv("FEVER_LLM_TIMEOUT", "180"))

FRONTEND_DIST = _PROJECT_ROOT / "frontend" / "dist"
