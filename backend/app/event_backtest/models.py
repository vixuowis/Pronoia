from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Optional


Market = Literal["CN", "US", "HK"]
Direction = Literal["up", "down"]
Label = Literal["up", "down", "neutral"]


def event_template() -> dict[str, Any]:
    return {
        "event_id": "evt_cn_rate_0001",
        "market": "CN",
        "symbol": "600000",
        "event_time": "2025-01-10T09:00:00+08:00",
        "event_type_l2": "政策利率调整",
        "title": "LPR 下调",
        "event_text": "央行宣布 LPR 下调 10bp，市场预期银行与地产链风险偏好改善。",
        "source_url": "https://example.com/official-announcement",
        "sector_etf": "银行ETF",
        "benchmark": "sh000300",
        "direction_prior": "up",
        "event_strength": 2,
    }


@dataclass(frozen=True)
class EventRecord:
    event_id: str
    market: Market
    symbol: str
    event_time: str
    event_type_l2: str
    title: str
    event_text: str
    source_url: str
    sector_etf: Optional[str] = None
    benchmark: Optional[str] = None
    direction_prior: Optional[str] = None
    event_strength: Optional[int] = None

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "EventRecord":
        return EventRecord(
            event_id=str(d.get("event_id") or d.get("id") or ""),
            market=str(d.get("market") or "").upper(),  # type: ignore[arg-type]
            symbol=str(d.get("symbol") or ""),
            event_time=str(d.get("event_time") or ""),
            event_type_l2=str(d.get("event_type_l2") or d.get("event_type") or ""),
            title=str(d.get("title") or ""),
            event_text=str(d.get("event_text") or d.get("text") or ""),
            source_url=str(d.get("source_url") or d.get("url") or ""),
            sector_etf=(str(d.get("sector_etf")).strip() or None) if d.get("sector_etf") is not None else None,
            benchmark=(str(d.get("benchmark")).strip() or None) if d.get("benchmark") is not None else None,
            direction_prior=(str(d.get("direction_prior")).strip() or None) if d.get("direction_prior") is not None else None,
            event_strength=int(d["event_strength"]) if d.get("event_strength") is not None else None,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "market": self.market,
            "symbol": self.symbol,
            "event_time": self.event_time,
            "event_type_l2": self.event_type_l2,
            "title": self.title,
            "event_text": self.event_text,
            "source_url": self.source_url,
            "sector_etf": self.sector_etf,
            "benchmark": self.benchmark,
            "direction_prior": self.direction_prior,
            "event_strength": self.event_strength,
        }


@dataclass(frozen=True)
class TeamPrediction:
    event_id: str
    pred_direction: Direction
    run_id: str
    model_version: str = ""
    confidence: Optional[float] = None
    rationale: Optional[str] = None
    abstain: bool = False

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "TeamPrediction":
        return TeamPrediction(
            event_id=str(d.get("event_id") or d.get("id") or ""),
            pred_direction=str(d.get("pred_direction") or d.get("direction") or ""),
            run_id=str(d.get("run_id") or ""),
            model_version=str(d.get("model_version") or ""),
            confidence=float(d["confidence"]) if d.get("confidence") is not None else None,
            rationale=(str(d.get("rationale")).strip() or None) if d.get("rationale") is not None else None,
            abstain=bool(d.get("abstain") is True),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "pred_direction": self.pred_direction,
            "run_id": self.run_id,
            "model_version": self.model_version,
            "confidence": self.confidence,
            "rationale": self.rationale,
            "abstain": self.abstain,
        }


@dataclass(frozen=True)
class EventLabel:
    event_id: str
    label_t1: Label
    label_t3: Label
    label_t5: Label
    car_t1: float
    car_t3: float
    car_t5: float
    market: Optional[Market] = None
    event_type_l2: Optional[str] = None
    car_t1_pvalue: Optional[float] = None
    car_t3_pvalue: Optional[float] = None
    car_t5_pvalue: Optional[float] = None

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "EventLabel":
        market = d.get("market")
        def _safe_float(key):
            v = d.get(key)
            if v is None or v == "":
                return None
            try:
                return float(v)
            except (TypeError, ValueError):
                return None
        return EventLabel(
            event_id=str(d.get("event_id") or d.get("id") or ""),
            label_t1=str(d.get("label_t1") or ""),
            label_t3=str(d.get("label_t3") or ""),
            label_t5=str(d.get("label_t5") or ""),
            car_t1=float(d.get("car_t1") or 0.0),
            car_t3=float(d.get("car_t3") or 0.0),
            car_t5=float(d.get("car_t5") or 0.0),
            market=(str(market).upper() if market is not None else None),  # type: ignore[arg-type]
            event_type_l2=(str(d.get("event_type_l2")).strip() or None) if d.get("event_type_l2") is not None else None,
            car_t1_pvalue=_safe_float("car_t1_pvalue"),
            car_t3_pvalue=_safe_float("car_t3_pvalue"),
            car_t5_pvalue=_safe_float("car_t5_pvalue"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "label_t1": self.label_t1,
            "label_t3": self.label_t3,
            "label_t5": self.label_t5,
            "car_t1": self.car_t1,
            "car_t3": self.car_t3,
            "car_t5": self.car_t5,
            "market": self.market,
            "event_type_l2": self.event_type_l2,
            "car_t1_pvalue": self.car_t1_pvalue,
            "car_t3_pvalue": self.car_t3_pvalue,
            "car_t5_pvalue": self.car_t5_pvalue,
        }
