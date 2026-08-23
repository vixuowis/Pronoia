from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Optional


Market = Literal["CN", "US", "HK"]
Direction = Literal["up", "down"]
Label = Literal["up", "down", "neutral"]
# Oracle horizons used for scoring. Numeric horizons (t*) map 1-to-1 to label_t* / car_t*.
# Composite horizons (avg_* / consensus66) map to label_avg_* / label_consensus66.
Horizon = Literal[
    "t1", "t3", "t5", "t7", "t15", "t30", "t60",
    "avg_short", "avg_mid", "avg_long", "avg_all", "consensus66",
]

ALL_HORIZONS: tuple[Horizon, ...] = (
    "t1", "t3", "t5", "t7", "t15", "t30", "t60",
    "avg_short", "avg_mid", "avg_long", "avg_all", "consensus66",
)


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
    # 多窗口判别：ret_t3..ret_t60 / car_t3..car_t60 → {direction, confidence, ...}
    horizons: Optional[dict[str, Any]] = None

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
            horizons=(d.get("horizons") or None),
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
            "horizons": self.horizons,
        }


@dataclass(frozen=True)
class EventLabel:
    event_id: str
    label_t1: Label
    label_t3: Label
    label_t5: Label
    label_t7: Label = ""
    label_t15: Label = ""
    label_t30: Label = ""
    label_t60: Label = ""
    label_avg_short: Label = ""
    label_avg_mid: Label = ""
    label_avg_long: Label = ""
    label_avg_all: Label = ""
    label_consensus66: Label = ""
    car_t1: float = 0.0
    car_t3: float = 0.0
    car_t5: float = 0.0
    car_t7: Optional[float] = None
    car_t15: Optional[float] = None
    car_t30: Optional[float] = None
    car_t60: Optional[float] = None
    car_avg_short: Optional[float] = None
    car_avg_mid: Optional[float] = None
    car_avg_long: Optional[float] = None
    car_avg_all: Optional[float] = None
    market: Optional[Market] = None
    event_type_l2: Optional[str] = None
    car_t1_pvalue: Optional[float] = None
    car_t3_pvalue: Optional[float] = None
    car_t5_pvalue: Optional[float] = None
    car_t7_pvalue: Optional[float] = None
    car_t15_pvalue: Optional[float] = None
    car_t30_pvalue: Optional[float] = None
    car_t60_pvalue: Optional[float] = None
    # Consistency / horizon-metadata signals
    n_horizons_valid: Optional[int] = None
    n_horizons_signed: Optional[int] = None
    consensus_net: Optional[float] = None
    consensus_maj_frac: Optional[float] = None
    # Meta: which oracle horizon was used as the primary direction label (avg_all / t3 / etc.)
    primary_oracle_horizon: Optional[str] = None

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
        def _label(key):
            return str(d.get(key) or "")
        def _car(key):
            v = d.get(key)
            if v is None or v == "":
                return None
            try:
                return float(v)
            except (TypeError, ValueError):
                return None
        def _opt_int(key):
            v = d.get(key)
            if v is None or v == "":
                return None
            try:
                return int(v)
            except (TypeError, ValueError):
                return None
        return EventLabel(
            event_id=str(d.get("event_id") or d.get("id") or ""),
            # numeric horizon labels (backward-compat: t1/t3/t5 always present)
            label_t1=_label("label_t1"),
            label_t3=_label("label_t3"),
            label_t5=_label("label_t5"),
            # extended numeric horizons
            label_t7=_label("label_t7"),
            label_t15=_label("label_t15"),
            label_t30=_label("label_t30"),
            label_t60=_label("label_t60"),
            # avgCAR horizons
            label_avg_short=_label("label_avg_short"),
            label_avg_mid=_label("label_avg_mid"),
            label_avg_long=_label("label_avg_long"),
            label_avg_all=_label("label_avg_all"),
            # strict consensus horizon
            label_consensus66=_label("label_consensus66"),
            # backward-compat: base 3 cars
            car_t1=float(d.get("car_t1") or 0.0),
            car_t3=float(d.get("car_t3") or 0.0),
            car_t5=float(d.get("car_t5") or 0.0),
            # extended cars (nullable: None = no data)
            car_t7=_car("car_t7"),
            car_t15=_car("car_t15"),
            car_t30=_car("car_t30"),
            car_t60=_car("car_t60"),
            car_avg_short=_car("car_avg_short"),
            car_avg_mid=_car("car_avg_mid"),
            car_avg_long=_car("car_avg_long"),
            car_avg_all=_car("car_avg_all"),
            market=(str(market).upper() if market is not None else None),  # type: ignore[arg-type]
            event_type_l2=(str(d.get("event_type_l2")).strip() or None) if d.get("event_type_l2") is not None else None,
            car_t1_pvalue=_safe_float("car_t1_pvalue"),
            car_t3_pvalue=_safe_float("car_t3_pvalue"),
            car_t5_pvalue=_safe_float("car_t5_pvalue"),
            car_t7_pvalue=_safe_float("car_t7_pvalue"),
            car_t15_pvalue=_safe_float("car_t15_pvalue"),
            car_t30_pvalue=_safe_float("car_t30_pvalue"),
            car_t60_pvalue=_safe_float("car_t60_pvalue"),
            n_horizons_valid=_opt_int("n_horizons_valid"),
            n_horizons_signed=_opt_int("n_horizons_signed"),
            consensus_net=_safe_float("consensus_net"),
            consensus_maj_frac=_safe_float("consensus_maj_frac"),
            primary_oracle_horizon=str(d.get("primary_oracle_horizon") or "") or None,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "label_t1": self.label_t1,
            "label_t3": self.label_t3,
            "label_t5": self.label_t5,
            "label_t7": self.label_t7,
            "label_t15": self.label_t15,
            "label_t30": self.label_t30,
            "label_t60": self.label_t60,
            "label_avg_short": self.label_avg_short,
            "label_avg_mid": self.label_avg_mid,
            "label_avg_long": self.label_avg_long,
            "label_avg_all": self.label_avg_all,
            "label_consensus66": self.label_consensus66,
            "car_t1": self.car_t1,
            "car_t3": self.car_t3,
            "car_t5": self.car_t5,
            "car_t7": self.car_t7,
            "car_t15": self.car_t15,
            "car_t30": self.car_t30,
            "car_t60": self.car_t60,
            "car_avg_short": self.car_avg_short,
            "car_avg_mid": self.car_avg_mid,
            "car_avg_long": self.car_avg_long,
            "car_avg_all": self.car_avg_all,
            "market": self.market,
            "event_type_l2": self.event_type_l2,
            "car_t1_pvalue": self.car_t1_pvalue,
            "car_t3_pvalue": self.car_t3_pvalue,
            "car_t5_pvalue": self.car_t5_pvalue,
            "car_t7_pvalue": self.car_t7_pvalue,
            "car_t15_pvalue": self.car_t15_pvalue,
            "car_t30_pvalue": self.car_t30_pvalue,
            "car_t60_pvalue": self.car_t60_pvalue,
            "n_horizons_valid": self.n_horizons_valid,
            "n_horizons_signed": self.n_horizons_signed,
            "consensus_net": self.consensus_net,
            "consensus_maj_frac": self.consensus_maj_frac,
            "primary_oracle_horizon": self.primary_oracle_horizon,
        }
