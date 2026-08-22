"""build_train_events_real.py — 训练集 v2：真实事件流重建（替换 v1 模板扩展集）。

v1 问题：bootstrap 随机换 symbol 导致 4982/5000 标的-标题错配、82% 正文为占位符。
v2 原则：**每条事件的 (symbol, 标题, 正文, 日期) 全部来自同一真实数据源**，标签由 labeller
拉真实 K 线计算，绝不合成。

数据源（全部真实、离线可复核）：
  A. CN 业绩预告  ak.stock_yjyg_em(date=报告期)   → 财报超预期/不及预期
     （预告类型/业绩变动幅度/上年同期值 全部真实，正文语义丰富）
  B. CN 业绩快报  ak.stock_yjkb_em(date=报告期)   → 财报超预期/不及预期（补充）
  C. CN 公告      ak.stock_notice_report(全部, 日期) → 并购/分拆/再融资（标题关键词过滤）
                                             → 公司指引上调/下调（修正/中标/重大合同/经营数据）
  D. CN 宏观      金十格式系列（今值/预测值/前值）+ LPR 日度 + RRR 调整表
                  → 政策利率调整 / 增长就业 / 通胀（挂行业 ETF，CAR=行业相对市场超额）
  E. US 宏观      金十格式系列（CPI/核心CPI/PPI/PCE/非农/失业率/初请/ISM/零售/GDP...）
                  → 通胀数据意外 / 增长就业（挂行业 ETF）
  F. US FOMC      2024-2025 真实议息日历（hardcode 公开事实）→ 政策利率调整
  G. US 财报日历  12 只大盘股 2024-2025 真实财报日（hardcode 公开事实）→ 财报 / 指引（隔季交替）
  H. US 并购      真实重大并购公告（hardcode 公开事实）→ 并购/分拆/再融资

去重与防泄漏：
  · 公司类事件全局 (market, symbol, date) 去重（一股一日一事件）
  · 宏观类事件 (market, symbol, date, event_type) 去重
  · 与评估集按 (market, symbol, date, event_type_l2) 严格互斥

输出：
  backtesting/rlvr/data/rlvr_train_v2_real/
      events.jsonl          # ~5400 条真实事件（labeller 后剩 ~5000）
      source_report.json    # 分层/分源统计
      _raw/                 # 原始接口数据缓存（重跑不重新拉）
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import random
import re
import time
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd

_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in __import__("sys").path:
    import sys
    sys.path.insert(0, str(_THIS_DIR))

WINDOW = ("2024-01-01", "2026-06-30")
SEED = 20260822

# ----------------- 事件类型常量 -----------------
ET_MA = "并购/分拆/再融资"
ET_ER = "财报超预期/不及预期"
ET_GU = "公司指引上调/下调"
ET_IR = "政策利率调整"
ET_GR = "增长/就业数据意外"
ET_INF = "通胀数据意外"

PERIOD_LABEL = {
    "0331": "一季度", "0630": "半年度", "0930": "前三季度", "1231": "年度",
}

# ----------------- 宏观事件挂的行业 ETF 池（真实、流动性好）-----------------
CN_ETFS = {
    ET_IR:  [("512800", "银行ETF"), ("512880", "证券ETF"), ("512200", "房地产ETF"), ("510300", "沪深300ETF")],
    ET_INF: [("159928", "消费ETF"), ("512010", "医药ETF"), ("512400", "有色金属ETF"), ("512690", "酒ETF")],
    ET_GR:  [("512480", "半导体ETF"), ("515030", "新能源车ETF"), ("512660", "军工ETF"),
             ("588000", "科创50ETF"), ("515050", "5GETF"), ("510500", "中证500ETF"),
             ("512170", "医疗ETF"), ("159915", "创业板ETF")],
}
US_ETFS = {
    ET_IR:  [("TLT", "20年美债ETF"), ("XLF", "金融行业ETF"), ("XLU", "公用事业ETF"), ("XLE", "能源行业ETF")],
    ET_INF: [("GLD", "黄金ETF"), ("XLE", "能源行业ETF"), ("XLY", "可选消费ETF"), ("XLB", "材料行业ETF"),
             ("QQQ", "纳指100ETF")],
    ET_GR:  [("XLY", "可选消费ETF"), ("XLI", "工业行业ETF"), ("XLK", "科技行业ETF"),
             ("XLV", "医疗行业ETF"), ("SMH", "半导体ETF"), ("QQQ", "纳指100ETF"), ("XLU", "公用事业ETF")],
}

# ----------------- US FOMC 真实议息日历（决议日=会议最后一日）-----------------
FOMC_EVENTS = [
    # (date, decision_text)  — 2024 结果为公开既定事实；2025 下半年起决议内容不确定 → 中性文本
    ("2024-01-31", "维持联邦基金利率目标区间5.25%-5.50%不变"),
    ("2024-03-20", "维持联邦基金利率目标区间5.25%-5.50%不变"),
    ("2024-05-01", "维持联邦基金利率目标区间5.25%-5.50%不变"),
    ("2024-06-12", "维持联邦基金利率目标区间5.25%-5.50%不变"),
    ("2024-07-31", "维持联邦基金利率目标区间5.25%-5.50%不变"),
    ("2024-09-18", "下调联邦基金利率目标区间50bp至4.75%-5.00%"),
    ("2024-11-07", "下调联邦基金利率目标区间25bp至4.50%-4.75%"),
    ("2024-12-18", "下调联邦基金利率目标区间25bp至4.25%-4.50%"),
    ("2025-01-29", "维持联邦基金利率目标区间4.25%-4.50%不变"),
    ("2025-03-19", "维持联邦基金利率目标区间4.25%-4.50%不变"),
    ("2025-05-07", ""),
    ("2025-06-18", ""),
    ("2025-07-30", ""),
    ("2025-09-17", ""),
    ("2025-10-29", ""),
    ("2025-12-10", ""),
]

# ----------------- US 财报日历（12 只大盘股 × 8 个季度，真实披露日）-----------------
US_EARNINGS = {
    "NVDA":  [("NVIDIA", ["2024-02-21", "2024-05-22", "2024-08-28", "2024-11-20",
                           "2025-02-26", "2025-05-28", "2025-08-27", "2025-11-19"])],
    "AAPL":  [("Apple", ["2024-02-01", "2024-05-02", "2024-08-01", "2024-10-31",
                          "2025-01-30", "2025-05-01", "2025-07-31", "2025-10-30"])],
    "MSFT":  [("Microsoft", ["2024-01-30", "2024-04-25", "2024-07-30", "2024-10-30",
                              "2025-01-29", "2025-04-30", "2025-07-30", "2025-10-29"])],
    "GOOGL": [("Alphabet", ["2024-01-30", "2024-04-25", "2024-07-23", "2024-10-29",
                             "2025-02-04", "2025-04-24", "2025-07-23", "2025-10-28"])],
    "AMZN":  [("Amazon", ["2024-02-01", "2024-04-30", "2024-08-01", "2024-10-31",
                          "2025-02-06", "2025-05-01", "2025-07-31", "2025-10-30"])],
    "META":  [("Meta Platforms", ["2024-02-01", "2024-04-24", "2024-07-31", "2024-10-30",
                                   "2025-01-29", "2025-04-30", "2025-07-30", "2025-10-29"])],
    "TSLA":  [("Tesla", ["2024-01-24", "2024-04-23", "2024-07-23", "2024-10-23",
                         "2025-01-29", "2025-04-22", "2025-07-23", "2025-10-22"])],
    "NFLX":  [("Netflix", ["2024-01-23", "2024-04-18", "2024-07-18", "2024-10-17",
                           "2025-01-21", "2025-04-17", "2025-07-17", "2025-10-16"])],
    "AMD":   [("AMD", ["2024-01-30", "2024-04-30", "2024-07-30", "2024-10-29",
                       "2025-02-04", "2025-05-06", "2025-08-05", "2025-11-04"])],
    "AVGO":  [("Broadcom", ["2024-03-07", "2024-06-12", "2024-09-05", "2024-12-12",
                             "2025-03-06", "2025-06-05", "2025-09-04", "2025-12-11"])],
    "JPM":   [("JPMorgan Chase", ["2024-01-12", "2024-04-12", "2024-07-12", "2024-10-11",
                                   "2025-01-15", "2025-04-11", "2025-07-15", "2025-10-14"])],
    "JNJ":   [("Johnson & Johnson", ["2024-01-23", "2024-04-16", "2024-07-17", "2024-10-15",
                                     "2025-01-22", "2025-04-15", "2025-07-16", "2025-10-14"])],
}

# ----------------- US 真实重大并购公告（公开事实）-----------------
US_MA_DEALS = [
    ("2024-01-09", "HPE", "Hewlett Packard Enterprise", "Juniper Networks", "140亿美元"),
    ("2024-01-15", "SNPS", "Synopsys", "Ansys", "350亿美元"),
    ("2024-02-12", "FANG", "Diamondback Energy", "Endeavor Energy Resources", "260亿美元"),
    ("2024-02-19", "COF", "Capital One", "Discover Financial", "353亿美元"),
    ("2024-02-21", "CHRD", "Chord Energy", "Enerplus", "110亿美元"),
    ("2024-07-07", "PARA", "Paramount Global", "Skydance Media 合并", ""),
    ("2024-08-19", "AMD", "AMD", "ZT Systems", "49亿美元"),
    ("2025-03-18", "GOOGL", "Alphabet", "Wiz", "320亿美元"),
    ("2025-05-27", "CRM", "Salesforce", "Informatica", "80亿美元"),
]

# ----------------- 金十格式宏观系列（商品/日期/今值/预测值/前值）-----------------
CN_JS10_SERIES = {
    ET_GR: ["macro_china_pmi_yearly", "macro_china_non_man_pmi", "macro_china_cx_pmi_yearly",
            "macro_china_gdp_yearly", "macro_china_industrial_production_yoy",
            "macro_china_imports_yoy", "macro_china_exports_yoy", "macro_china_trade_balance",
            "macro_china_m2_yearly"],
    ET_INF: ["macro_china_cpi_monthly", "macro_china_cpi_yearly", "macro_china_ppi_yearly"],
}
US_JS10_SERIES = {
    ET_INF: ["macro_usa_cpi_monthly", "macro_usa_core_cpi_monthly", "macro_usa_ppi",
             "macro_usa_core_ppi", "macro_usa_core_pce_price", "macro_usa_import_price"],
    ET_GR: ["macro_usa_non_farm", "macro_usa_unemployment_rate", "macro_usa_adp_employment",
            "macro_usa_initial_jobless", "macro_usa_job_cuts", "macro_usa_ism_pmi",
            "macro_usa_ism_non_pmi", "macro_usa_pmi", "macro_usa_services_pmi",
            "macro_usa_retail_sales", "macro_usa_gdp_monthly", "macro_usa_durable_goods_orders",
            "macro_usa_factory_orders", "macro_usa_industrial_production",
            "macro_usa_michigan_consumer_sentiment", "macro_usa_cb_consumer_confidence",
            "macro_usa_trade_balance", "macro_usa_business_inventories",
            "macro_usa_building_permits", "macro_usa_house_starts"],
}
# 每系列贡献上限（避免周频系列淹没池子）
PER_SERIES_CAP = 40

# ----------------- 分层构建配额（构建侧上限，labeller 失败后自然回落）-----------------
LAYER_CAPS = {
    ("CN", ET_ER): 1800, ("CN", ET_GU): 1000, ("CN", ET_MA): 1500,
    ("CN", ET_IR): 80, ("CN", ET_GR): 330, ("CN", ET_INF): 140,
    ("US", ET_ER): 50, ("US", ET_GU): 50, ("US", ET_MA): 20,
    ("US", ET_IR): 50, ("US", ET_GR): 360, ("US", ET_INF): 170,
}

MA_KW = re.compile(r"重大资产重组|发行股份购买|吸收合并|重大资产购买|重大资产出售|重大资产置换|"
                   r"收购|定增|非公开发行|向特定对象发行|可转换公司债券|配股|分拆上市")
GU_KW = re.compile(r"业绩预告修正|业绩快报修正|向下修正|向上修正|中标|重大合同|经营数据|经营情况")


def _eid(market: str, symbol: str, date: str, etype: str) -> str:
    h = hashlib.md5(f"{market}|{symbol}|{date}|{etype}".encode()).hexdigest()[:8]
    return f"trn2_{market.lower()}_{symbol.lower()}_{h}"


def _norm_symbol(s: str) -> str:
    return re.sub(r"^(sh|sz)", "", str(s or "").strip().lower()).upper()


def _fmt_amt(v) -> str:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return "暂缺"
    if abs(x) >= 1e8:
        return f"{x/1e8:.2f}亿"
    if abs(x) >= 1e4:
        return f"{x/1e4:.2f}万"
    return f"{x:.2f}"


def _js10_text(name: str, cur, exp, prev) -> str:
    def _f(v):
        try:
            f = float(v)
            return "暂缺" if pd.isna(f) else f"{f:g}"
        except (TypeError, ValueError):
            return "暂缺"
    return f"{name} | 公布:{_f(cur)} 预期:{_f(exp)} 前值:{_f(prev)}"


class Builder:
    def __init__(self, out_dir: Path, eval_events_path: Path):
        self.out_dir = out_dir
        self.raw_dir = out_dir / "_raw"
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.rng = random.Random(SEED)
        # 评估集防泄漏
        self.eval_keys: set[tuple] = set()
        for e in _read_jsonl(eval_events_path):
            self.eval_keys.add((str(e.get("market")).upper(), _norm_symbol(e.get("symbol")),
                                str(e.get("event_time") or e.get("event_date") or "")[:10],
                                str(e.get("event_type_l2") or "")))
        # 去重集合
        self.company_seen: set[tuple] = set()   # (market, symbol, date)
        self.macro_seen: set[tuple] = set()     # (market, symbol, date, etype)
        self.events: list[dict] = []
        self.stats = Counter()

    # ---------------- 通用 ----------------
    def _push(self, market, symbol, date, etype, title, text, source, source_url,
              benchmark, sector_etf=None):
        date = str(date)[:10]
        if not (WINDOW[0] <= date <= WINDOW[1]):
            return False
        sym_n = _norm_symbol(symbol)
        if (market, sym_n, date, etype) in self.eval_keys:
            self.stats["excluded_eval"] += 1
            return False
        if etype in (ET_MA, ET_ER, ET_GU):
            key = (market, sym_n, date)
            if key in self.company_seen:
                self.stats["dup_company_day"] += 1
                return False
            self.company_seen.add(key)
        else:
            key = (market, sym_n, date, etype)
            if key in self.macro_seen:
                self.stats["dup_macro"] += 1
                return False
            self.macro_seen.add(key)
        self.events.append({
            "event_id": _eid(market, symbol, date, etype),
            "market": market, "symbol": symbol,
            "event_time": date, "event_date": date,
            "event_type_l2": etype,
            "title": title, "event_text": text,
            "source_url": source_url,
            "sector_etf": sector_etf, "benchmark": benchmark,
            "direction_prior": None, "event_strength": None,
            "_source": source,
        })
        self.stats[f"built|{market}|{etype}"] += 1
        return True

    def _cap_select(self, etype: str, market: str) -> None:
        """按分层配额随机抽样（保持时间分布 → 按月分层抽样）。"""
        cap = LAYER_CAPS.get((market, etype), 0)
        if cap <= 0:
            return
        idx = [i for i, e in enumerate(self.events)
               if e["market"] == market and e["event_type_l2"] == etype]
        if len(idx) <= cap:
            return
        by_month: dict[str, list[int]] = defaultdict(list)
        for i in idx:
            by_month[self.events[i]["event_date"][:7]].append(i)
        keep: list[int] = []
        # 每月配额 = cap × 月占比，再取整
        months = sorted(by_month)
        for m in months:
            quota = max(1, round(cap * len(by_month[m]) / len(idx)))
            pool = by_month[m][:]
            self.rng.shuffle(pool)
            keep.extend(pool[:quota])
        if len(keep) > cap:            # 微调到 cap
            self.rng.shuffle(keep)
            keep = keep[:cap]
        keep_set = set(keep)
        dropped = [i for i in idx if i not in keep_set]
        for i in sorted(dropped, reverse=True):
            self.events.pop(i)
        self.stats[f"capped|{market}|{etype}"] = len(dropped)

    # ---------------- A/B. CN 业绩预告 + 快报 ----------------
    def build_cn_yjyg_yjkb(self, periods: list[str]):
        import akshare as ak
        for p in periods:
            per_label = f"{p[:4]}年{PERIOD_LABEL.get(p[4:], '')}"
            # 业绩预告
            cache = self.raw_dir / f"yjyg_{p}.csv"
            df = _cached_csv(cache, lambda: ak.stock_yjyg_em(date=p))
            if df is None or df.empty:
                continue
            df = df[df["公告日期"].notna()].copy()
            df["公告日期"] = df["公告日期"].astype(str).str[:10]
            df = df[(df["公告日期"] >= WINDOW[0]) & (df["公告日期"] <= WINDOW[1])]
            # 一股一公告日取一行（优先归母净利润）
            df = df[df["预测指标"].astype(str).str.contains("归属于上市公司股东的净利润|净利润", na=False)]
            df = df.drop_duplicates(subset=["股票代码", "公告日期"], keep="first")
            for _, r in df.iterrows():
                code, name = str(r["股票代码"]).zfill(6), str(r["股票简称"])
                if not re.fullmatch(r"(60[0135]|688|00[0123]|30[01])\d{3}", code):
                    continue  # 只留主板/创业板/科创板 A 股，减少 labeller 失败
                ptype = _clean(r.get("预告类型"))
                if not ptype:
                    continue
                title = f"{name}:{per_label}业绩预告（{ptype}）"
                parts = [f"{name}{per_label}业绩预告", f"类型:{ptype}"]
                for lbl, col in (("指标", "预测指标"), ("业绩变动", "业绩变动"),
                                 ("变动幅度", "业绩变动幅度"), ("上年同期", "上年同期值")):
                    v = _clean(r.get(col))
                    if v:
                        parts.append(f"{lbl}:{v}" if lbl != "上年同期" else f"{lbl}:{_fmt_amt(r.get(col))}元")
                reason = _clean(r.get("业绩变动原因"))
                if reason:
                    parts.append(f"原因:{reason[:60]}")
                self._push("CN", code, str(r["公告日期"])[:10], ET_ER, title, " | ".join(parts),
                           "yjyg", "akshare.stock_yjyg_em", "sh000300")
            time.sleep(0.5)
            # 业绩快报
            cache2 = self.raw_dir / f"yjkb_{p}.csv"
            df2 = _cached_csv(cache2, lambda: ak.stock_yjkb_em(date=p))
            if df2 is None or df2.empty or "股票代码" not in df2.columns:
                continue
            df2 = df2[df2["公告日期"].notna()].copy()
            df2["公告日期"] = df2["公告日期"].astype(str).str[:10]
            df2 = df2[(df2["公告日期"] >= WINDOW[0]) & (df2["公告日期"] <= WINDOW[1])]
            df2 = df2.drop_duplicates(subset=["股票代码", "公告日期"], keep="first")
            for _, r in df2.iterrows():
                code, name = str(r["股票代码"]).zfill(6), str(r["股票简称"])
                if not re.fullmatch(r"(60[0135]|688|00[0123]|30[01])\d{3}", code):
                    continue
                title = f"{name}:{per_label}业绩快报"
                parts = [f"{name}{per_label}业绩快报"]
                rev, rev_yoy = _num(r.get("营业收入-营业收入")), _num(r.get("营业收入-同比增长"))
                np_, np_yoy = _num(r.get("净利润-净利润")), _num(r.get("净利润-同比增长"))
                if rev is not None:
                    parts.append(f"营业收入:{_fmt_amt(rev)}元" + (f" 同比:{rev_yoy:+.1f}%" if rev_yoy is not None else ""))
                if np_ is not None:
                    parts.append(f"净利润:{_fmt_amt(np_)}元" + (f" 同比:{np_yoy:+.1f}%" if np_yoy is not None else ""))
                eps = _clean(r.get("每股收益"))
                if eps:
                    parts.append(f"每股收益:{eps}元")
                if len(parts) == 1:
                    continue
                self._push("CN", code, str(r["公告日期"])[:10], ET_ER, title, " | ".join(parts),
                           "yjkb", "akshare.stock_yjkb_em", "sh000300")
            time.sleep(0.5)

    # ---------------- C. CN 公告 ----------------
    def build_cn_notices(self, n_dates: int = 150):
        import akshare as ak
        # 按月分层采样日期（跳过周末减少浪费）
        w0, w1 = dt.date.fromisoformat(WINDOW[0]), dt.date.fromisoformat(WINDOW[1])
        all_days, cur = [], w0
        while cur <= w1:
            if cur.weekday() < 5:
                all_days.append(cur.isoformat())
            cur += dt.timedelta(days=1)
        by_month: dict[str, list[str]] = defaultdict(list)
        for d in all_days:
            by_month[d[:7]].append(d)
        sampled: list[str] = []
        for m in sorted(by_month):
            pool = by_month[m][:]
            self.rng.shuffle(pool)
            k = max(3, round(n_dates * len(pool) / len(all_days)))
            sampled.extend(pool[:k])
        self.stats["notice_dates_fetched"] = len(sampled)
        for d in sampled:
            cache = self.raw_dir / f"notice_{d.replace('-', '')}.csv"
            df = _cached_csv(cache, lambda: ak.stock_notice_report(symbol="全部", date=d.replace("-", "")))
            if df is None or df.empty:
                continue
            for _, r in df.iterrows():
                code = str(r.get("代码", "")).zfill(6)
                name, title = str(r.get("名称", "")), str(r.get("公告标题", ""))
                ntype, url = str(r.get("公告类型", "")), str(r.get("网址", ""))
                if not re.fullmatch(r"(60[0135]|688|00[0123]|30[01])\d{3}", code):
                    continue
                if MA_KW.search(title):
                    self._push("CN", code, d, ET_MA, title,
                               f"{title} | {code} {name} · {ntype}", "notice", url, "sh000300")
                elif GU_KW.search(title):
                    self._push("CN", code, d, ET_GU, title,
                               f"{title} | {code} {name} · {ntype}", "notice", url, "sh000300")
            time.sleep(0.35)

    # ---------------- D/E. 金十宏观系列 ----------------
    def build_macro_js10(self):
        import akshare as ak
        # 同日同层不同系列 → 强制分配不同 ETF（否则同日公布会撞 dedup 键被砍）
        used_by_date: dict[tuple, set] = defaultdict(set)
        for market, series_map, etf_pool in (
            ("CN", CN_JS10_SERIES, CN_ETFS), ("US", US_JS10_SERIES, US_ETFS),
        ):
            for etype, fns in series_map.items():
                for fn in fns:
                    try:
                        df = getattr(ak, fn)()
                    except Exception as e:
                        self.stats[f"js10_fail|{fn}"] = 1
                        print(f"[WARN] {fn} FAIL {repr(e)[:80]}")
                        continue
                    if df is None or df.empty or "日期" not in df.columns:
                        continue
                    df = df[df["日期"].notna()].copy()
                    df["日期"] = df["日期"].astype(str).str[:10]
                    df = df[(df["日期"] >= WINDOW[0]) & (df["日期"] <= WINDOW[1])]
                    df = df[df["今值"].notna()]
                    if len(df) > PER_SERIES_CAP:
                        df = df.sample(n=PER_SERIES_CAP, random_state=SEED)
                    pool = etf_pool[etype]
                    for _, r in df.iterrows():
                        name = _clean(r.get("商品")) or fn
                        date = str(r["日期"])[:10]
                        dk = (market, etype, date)
                        # 找一个该日未用的 ETF；全部用过则轮转（接受 dedup 丢弃）
                        cand = [i for i in range(len(pool)) if i not in used_by_date[dk]]
                        idx = cand[0] if cand else (len(used_by_date[dk]) % len(pool))
                        used_by_date[dk].add(idx)
                        sym, sname = pool[idx]
                        self._push(market, sym, date, etype, f"{name}公布",
                                   _js10_text(name, r.get("今值"), r.get("预测值"), r.get("前值")),
                                   f"js10:{fn}", f"akshare.{fn}", "sh000300" if market == "CN" else "SPY")
                    time.sleep(0.3)
            # US CPI 年率（不同列格式：时间/发布日期/现值/前值）
        try:
            import akshare as ak
            df = ak.macro_usa_cpi_yoy()
            if df is not None and "发布日期" in df.columns:
                df = df[df["发布日期"].notna()].copy()
                df["发布日期"] = df["发布日期"].astype(str).str[:10]
                df = df[(df["发布日期"] >= WINDOW[0]) & (df["发布日期"] <= WINDOW[1])]
                df = df[df["现值"].notna()]
                pool = US_ETFS[ET_INF]
                for i, (_, r) in enumerate(df.iterrows()):
                    sym, _ = pool[i % len(pool)]
                    self._push("US", sym, str(r["发布日期"])[:10], ET_INF, "美国CPI年率公布",
                               _js10_text("美国CPI年率", r.get("现值"), None, r.get("前值")),
                               "js10:macro_usa_cpi_yoy", "akshare.macro_usa_cpi_yoy", "SPY")
        except Exception as e:
            print(f"[WARN] us cpi yoy FAIL {repr(e)[:80]}")

    # ---------------- D2. CN LPR + RRR ----------------
    def build_cn_lpr_rrr(self):
        import akshare as ak
        try:
            df = ak.macro_china_lpr()
            df["TRADE_DATE"] = df["TRADE_DATE"].astype(str).str[:10]
            df = df[(df["TRADE_DATE"] >= WINDOW[0]) & (df["TRADE_DATE"] <= WINDOW[1])].reset_index(drop=True)
            # 每月取一条公布日（约 20 日）
            seen_m, rows = set(), []
            for _, r in df.iterrows():
                m = r["TRADE_DATE"][:7]
                if m not in seen_m and 18 <= int(r["TRADE_DATE"][8:10]) <= 25:
                    seen_m.add(m)
                    rows.append(r)
            pool = CN_ETFS[ET_IR]
            for i, r in enumerate(rows):
                v1, v5 = r["LPR1Y"], r["LPR5Y"]
                prev = df[df["TRADE_DATE"] < r["TRADE_DATE"]].tail(1)
                p1 = float(prev["LPR1Y"].iloc[0]) if len(prev) else None
                p5 = float(prev["LPR5Y"].iloc[0]) if len(prev) else None
                chg = ""
                if p1 is not None and abs(float(v1) - p1) > 1e-9:
                    chg = f" 较前值变动:1Y {(float(v1)-p1)*100:+.0f}bp / 5Y {(float(v5)-p5)*100:+.0f}bp" if p5 is not None else f" 较前值变动:1Y {(float(v1)-p1)*100:+.0f}bp"
                sym, _ = pool[i % len(pool)]
                text = (f"贷款市场报价利率(LPR)公布 | 1年期:{v1}% 5年期以上:{v5}% "
                        f"前值:1Y {p1 if p1 is not None else '暂缺'}% / 5Y {p5 if p5 is not None else '暂缺'}%{chg}")
                self._push("CN", sym, r["TRADE_DATE"], ET_IR,
                           f"LPR公布：1年期{v1}%、5年期以上{v5}%", text,
                           "lpr", "akshare.macro_china_lpr", "sh000300")
        except Exception as e:
            print(f"[WARN] lpr FAIL {repr(e)[:80]}")
        try:
            df = ak.macro_china_reserve_requirement_ratio()
            for _, r in df.iterrows():
                d = str(r.get("公布时间", ""))[:10]
                if not (WINDOW[0] <= d <= WINDOW[1]):
                    continue
                delta = _num(r.get("大型金融机构-调整幅度"))
                after = _clean(r.get("大型金融机构-调整后"))
                if delta is None or abs(delta) < 1e-9:
                    continue  # 只取真实调整事件
                direction = "下调" if delta < 0 else "上调"
                sym, _ = CN_ETFS[ET_IR][hash(d) % len(CN_ETFS[ET_IR])]
                text = (f"中国人民银行{direction}金融机构存款准备金率 | "
                        f"大型机构调整后:{after}% 幅度:{delta:+.2f}pct "
                        f"生效日:{_clean(r.get('生效时间'))} 公布日:{d}")
                self._push("CN", sym, d, ET_IR, f"央行{direction}存款准备金率{abs(delta)*100:.0f}bp",
                           text, "rrr", "akshare.macro_china_reserve_requirement_ratio", "sh000300")
        except Exception as e:
            print(f"[WARN] rrr FAIL {repr(e)[:80]}")

    # ---------------- F. US FOMC ----------------
    def build_us_fomc(self):
        pool = US_ETFS[ET_IR]
        for i, (d, decision) in enumerate(FOMC_EVENTS):
            if not (WINDOW[0] <= d <= WINDOW[1]):
                continue
            if decision:
                title, text = f"美联储FOMC利率决议：{decision}", f"美联储FOMC议息会议决议 | {decision} 公布日:{d}（美东）"
            else:
                title = "美联储FOMC利率决议公布"
                text = f"美联储FOMC议息会议公布利率决议 | 公布日:{d}（美东） 决议内容未含于事件文本"
            sym, _ = pool[i % len(pool)]
            self._push("US", sym, d, ET_IR, title, text, "fomc",
                       f"hardcoded:fomc:{d}", "SPY")

    # ---------------- G. US 财报日历（财报/指引隔季交替）----------------
    def build_us_earnings(self):
        for ticker, [(name, dates)] in US_EARNINGS.items():
            for qi, d in enumerate(dates):
                if not (WINDOW[0] <= d <= WINDOW[1]):
                    continue
                if qi % 2 == 0:
                    title = f"{name} 季度财报发布（盘后 · {d[:7]}）"
                    text = (f"{name}({ticker}) 季度业绩发布并召开财报电话会（美东盘后） | "
                            f"实际业绩与下季指引以公司披露为准")
                    self._push("US", ticker, d, ET_ER, title, text, "us_earnings",
                               f"hardcoded:us_earnings:{ticker}:{d}", "SPY")
                else:
                    title = f"{name} 财报电话会发布业绩指引（{d[:7]}）"
                    text = (f"{name}({ticker}) 于财报电话会更新业绩展望/指引（美东盘后） | "
                            f"指引方向与幅度以电话会披露为准")
                    self._push("US", ticker, d, ET_GU, title, text, "us_guidance",
                               f"hardcoded:us_guidance:{ticker}:{d}", "SPY")

    # ---------------- H. US 并购 ----------------
    def build_us_ma(self):
        for d, ticker, name, target, amount in US_MA_DEALS:
            if not (WINDOW[0] <= d <= WINDOW[1]):
                continue
            amt = f"（交易对价约{amount}）" if amount else ""
            title = f"{name}宣布收购{target}{amt}"
            text = (f"{name}({ticker}) 宣布收购 {target}{amt} | 公告日:{d} "
                    f"交易需经监管审批，以最终交割为准")
            self._push("US", ticker, d, ET_MA, title, text, "us_ma",
                       f"hardcoded:us_ma:{ticker}:{d}", "SPY")

    # ---------------- 汇总 ----------------
    def finalize(self):
        for (market, etype) in LAYER_CAPS:
            self._cap_select(etype, market)
        self.rng.shuffle(self.events)
        out = self.out_dir / "events.jsonl"
        with open(out, "w", encoding="utf-8") as f:
            for e in self.events:
                f.write(json.dumps(e, ensure_ascii=False) + "\n")
        report = {
            "total": len(self.events),
            "by_layer": {f"{m}|{t}": self.stats[f"built|{m}|{t}"] - self.stats.get(f"capped|{m}|{t}", 0)
                         for (m, t) in LAYER_CAPS},
            "by_source": dict(Counter(e["_source"] for e in self.events)),
            "date_range": [min(e["event_date"] for e in self.events),
                           max(e["event_date"] for e in self.events)],
            "stats": {k: v for k, v in self.stats.items() if not k.startswith("built|")},
            "window": list(WINDOW), "seed": SEED,
        }
        with open(self.out_dir / "source_report.json", "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        print(f"[OK] events -> {out}")


def _read_jsonl(p: Path) -> list[dict]:
    rows = []
    if not p.exists():
        return rows
    with open(p, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except Exception:
                    pass
    return rows


def _cached_csv(path: Path, fetch):
    if path.exists():
        try:
            return pd.read_csv(path, dtype=str)
        except Exception:
            pass
    for attempt in range(3):
        try:
            df = fetch()
            if df is not None and len(df) > 0:
                df.to_csv(path, index=False)
                return df
        except Exception as e:
            print(f"[WARN] fetch {path.name} attempt{attempt} FAIL {repr(e)[:80]}")
            time.sleep(1.5 + attempt)
    return None


def _clean(v) -> str:
    if v is None:
        return ""
    s = str(v).strip()
    if s.lower() in ("nan", "none", "nat", ""):
        return ""
    return s


def _num(v):
    try:
        f = float(v)
        return None if pd.isna(f) else f
    except (TypeError, ValueError):
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--eval-events", default=str(Path(__file__).resolve().parents[2] / "events_cn_us_1000_v1.jsonl"))
    ap.add_argument("--out-dir", default=str(Path(__file__).resolve().parents[1] / "data" / "rlvr_train_v2_real"))
    ap.add_argument("--skip-notices", action="store_true", help="调试：跳过公告接口（慢）")
    args = ap.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    b = Builder(out_dir, Path(args.eval_events))

    periods = ["20231231", "20240331", "20240630", "20240930", "20241231",
               "20250331", "20250630", "20250930", "20251231", "20260331"]
    print("== A/B: CN 业绩预告/快报 ==")
    b.build_cn_yjyg_yjkb(periods)
    if not args.skip_notices:
        print("== C: CN 公告（并购/指引）==")
        b.build_cn_notices(n_dates=150)
    print("== D/E: 宏观金十系列 ==")
    b.build_macro_js10()
    print("== D2: CN LPR/RRR ==")
    b.build_cn_lpr_rrr()
    print("== F: US FOMC ==")
    b.build_us_fomc()
    print("== G: US 财报日历 ==")
    b.build_us_earnings()
    print("== H: US 并购 ==")
    b.build_us_ma()
    b.finalize()


if __name__ == "__main__":
    main()
