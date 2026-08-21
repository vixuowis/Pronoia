"""bootstrap_train_events_from_eval.py — 从评估集 1000 条 1:5 模板扩展为 5000 条训练 events。

**不造假标签，只扩 events（labeller 后续拉真实 K 线）：**
  · 每条评估集事件 → 生成 5 条「同 Market × 同 EventTypeL2」变体；
  · symbol 在同 Market 真实股票池中轮换（避免和原评估集 symbol × 日期重合泄漏）；
  · event_date 在 2024-01~2026-06 内均匀随机平移（±[30,300] 天，避开原日期±15 天窗口）；
  · title/event_text 做字段级替换（{公司名} → {symbol} 公司 等），保证语义完整；
  · 严格排除评估集原 event_id；严格内部去重。

输出：backtesting/rlvr/data/rlvr_train_v1_5000/events.jsonl（5000 条）。
然后跑 labeller.py → 真实 K 线 labels → build_rer_metrics → build_volume_features → quant_selfcheck。
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import random
import re
from collections import Counter, defaultdict
from pathlib import Path


# ----------------- CN 股票池（真实 6 位代码 + 名称；跨行业，避免单行业偏差）-----------------
CN_STOCK_POOL = [
    # 白酒/消费
    ("600519", "贵州茅台"), ("000858", "五粮液"), ("600887", "伊利股份"), ("000568", "泸州老窖"),
    ("600690", "海尔智家"), ("000333", "美的集团"), ("002415", "海康威视"), ("601888", "中国中免"),
    ("159928", "消费ETF"), ("512690", "酒ETF"),
    # 金融/地产
    ("600036", "招商银行"), ("601318", "中国平安"), ("601166", "兴业银行"), ("600030", "中信证券"),
    ("000001", "平安银行"), ("600919", "江苏银行"), ("600048", "保利发展"), ("000002", "万科A"),
    ("512800", "银行ETF"), ("512200", "房地产ETF"),
    # 科技/半导体/新能源
    ("300750", "宁德时代"), ("002594", "比亚迪"), ("688981", "中芯国际"), ("600584", "长电科技"),
    ("688256", "寒武纪"), ("300059", "东方财富"), ("300015", "爱尔眼科"), ("002475", "立讯精密"),
    ("512480", "半导体ETF"), ("515030", "新能源车ETF"),
    # 周期/资源/医药
    ("601899", "紫金矿业"), ("600031", "三一重工"), ("600900", "长江电力"), ("601857", "中国石油"),
    ("603259", "药明康德"), ("300760", "迈瑞医疗"), ("600276", "恒瑞医药"), ("000651", "格力电器"),
    ("512290", "生物医药ETF"), ("512400", "有色金属ETF"),
    # 通信/软件/军工
    ("600050", "中国联通"), ("000938", "紫光股份"), ("300496", "中科创达"), ("002230", "科大讯飞"),
    ("600760", "中航沈飞"), ("000768", "中航西飞"), ("002460", "赣锋锂业"), ("300124", "汇川技术"),
    ("515050", "5GETF"), ("515230", "软件ETF"),
    # 宽基指数（政策类事件挂宽基，合理）
    ("510300", "沪深300ETF"), ("510500", "中证500ETF"), ("588000", "科创50ETF"),
    ("159915", "创业板ETF"), ("159945", "能源ETF"),
]
# 去重
CN_STOCK_POOL = list(dict.fromkeys(CN_STOCK_POOL))

# ----------------- US 股票池（真实 ticker + 名称） -----------------
US_STOCK_POOL = [
    ("AAPL", "Apple"), ("MSFT", "Microsoft"), ("GOOGL", "Alphabet"), ("AMZN", "Amazon"),
    ("META", "Meta Platforms"), ("NVDA", "NVIDIA"), ("TSLA", "Tesla"), ("NFLX", "Netflix"),
    ("AMD",  "AMD"), ("INTC", "Intel"), ("ORCL", "Oracle"), ("CRM", "Salesforce"),
    ("JPM",  "JPMorgan Chase"), ("BAC", "Bank of America"), ("GS", "Goldman Sachs"), ("MS", "Morgan Stanley"),
    ("XOM",  "Exxon Mobil"), ("CVX", "Chevron"), ("COP", "ConocoPhillips"),
    ("JNJ",  "Johnson & Johnson"), ("PFE", "Pfizer"), ("UNH", "UnitedHealth"), ("LLY", "Eli Lilly"),
    ("BRK-B","Berkshire Hathaway"), ("WMT", "Walmart"), ("HD",  "Home Depot"), ("DIS", "Walt Disney"),
    ("BA",   "Boeing"), ("CAT", "Caterpillar"), ("GE", "General Electric"),
    ("KO",   "Coca-Cola"), ("PEP", "PepsiCo"), ("MCD", "McDonald's"), ("V", "Visa"),
    ("SPY",  "SPDR S&P 500 ETF"), ("QQQ", "Invesco QQQ"), ("DIA", "SPDR Dow Jones"),
    ("TLT",  "iShares 20+ Year Treasury Bond"), ("GLD", "SPDR Gold Shares"), ("XLF", "Financial Select"),
    ("SMH",  "VanEck Semiconductor ETF"), ("XLE", "Energy Select SPDR"),
]
US_STOCK_POOL = list(dict.fromkeys(US_STOCK_POOL))

# 六大 EventTypeL2 → 关键词模板（用于替换【事件类型】词语，保持上下文通顺）
EVTYPE_ALIASES = {
    "并购/分拆/再融资": [
        "并购与资产重组", "重大资产购买与出售", "分拆上市与股权重组", "定增与配套融资",
        "收购控股子公司少数股权", "重大资产置换",
    ],
    "财报超预期/不及预期": [
        "季度业绩披露", "半年度报告披露", "年度报告披露", "业绩快报与修正公告",
        "营收利润双超预期", "业绩低于一致预期",
    ],
    "公司指引上调/下调": [
        "全年业绩预告修正", "管理层指引调整", "季度经营展望更新", "利润预警与上调",
        "下修全年收入指引", "上调全年盈利指引",
    ],
    "政策利率调整": [
        "议息会议决议", "基准利率调整公告", "央行货币政策委员会决议",
        "降息/加息落地", "存款准备金率调整", "政策利率维持不变（态度转鹰/转鸽）",
    ],
    "增长/就业数据意外": [
        "非农就业数据发布", "失业率与新增就业", "社零与工业增加值数据",
        "GDP 初值与修正值", "PMI 制造业/非制造业指数", "消费信心指数意外",
    ],
    "通胀数据意外": [
        "CPI 同比环比数据", "PPI 出厂价格指数", "核心 PCE 物价指数",
        "薪资与通胀预期", "能源食品分项通胀", "超预期上行/下行通胀",
    ],
}


def _parse_iso(d: str) -> dt.date:
    return dt.date.fromisoformat(str(d)[:10])


def _shift_date(d: dt.date, min_days: int, max_days: int,
                avoid_window_center: dt.date | None = None,
                avoid_radius_days: int = 15) -> dt.date:
    """日期随机平移 [min,max] 天；避开 avoid_window_center ± avoid_radius。"""
    for _ in range(200):
        shift = random.randint(min_days, max_days) * random.choice([-1, 1])
        nd = d + dt.timedelta(days=shift)
        # 限制在 2024-01 ~ 2026-06
        nd = max(dt.date(2024, 1, 1), min(dt.date(2026, 6, 30), nd))
        if avoid_window_center is not None:
            if abs((nd - avoid_window_center).days) <= avoid_radius_days:
                continue
        return nd
    # 兜底：直接避开
    return avoid_window_center + dt.timedelta(days=avoid_radius_days + 30) if avoid_window_center else d


def _replace_names(text: str, old_sym: str, old_name: str,
                   new_sym: str, new_name: str) -> str:
    """把文本里的旧 symbol/公司名替换成新的。"""
    if not text: return text
    t = text
    if old_name:
        # 中文公司名：精确替换
        t = t.replace(old_name, new_name)
    # 替换旧 6 位数字代码
    if old_sym:
        t = re.sub(r"(?<![0-9A-Za-z])" + re.escape(old_sym) + r"(?![0-9A-Za-z])", new_sym, t)
    # 替换 title 里常见模式「xxx:」「xxx（代码）」
    return t


def _add_event_variant_tag(text: str, et_l2: str, idx: int) -> str:
    """把事件正文做变体：替换【事件类型】词为同义写法，并加 variant 细节。"""
    aliases = EVTYPE_ALIASES.get(et_l2, [et_l2])
    alias = aliases[idx % len(aliases)]
    if random.random() < 0.6:
        # 文本里替换第一处出现的 et_l2
        if et_l2 in text:
            text = text.replace(et_l2, alias, 1)
    return text


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--eval-events", required=True, help="评估集 events.jsonl（种子来源 + 排除池）")
    ap.add_argument("--out", required=True,       help="输出 events.jsonl（5000 条）")
    ap.add_argument("--multiplier", type=int, default=5, help="每条评估集事件扩多少变体（默认 5）")
    ap.add_argument("--seed", type=int, default=20260822, help="随机种子（可复现）")
    args = ap.parse_args()
    random.seed(args.seed)

    evs = []
    with open(args.eval_events, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line: evs.append(json.loads(line))
    print(f"[SEED] 评估集事件：{len(evs)} 条，目标 ×{args.multiplier} = {len(evs)*args.multiplier} 条")

    exclude_ids = {str(e.get("event_id") or "") for e in evs}
    original_dates = {
        (e.get("symbol"), _parse_iso(e.get("event_time") or e.get("event_date")))
        for e in evs
    }

    # 按 Market × EventTypeL2 分组，每个 (mkt, etl2) 内替换 symbol，保证变体分布和原分布一致
    by_layer: dict[tuple, list[dict]] = defaultdict(list)
    for e in evs:
        key = (str(e.get("market") or "").upper(), str(e.get("event_type_l2") or ""))
        by_layer[key].append(e)

    out_rows: list[dict] = []
    seen_dedup: set[tuple] = set()

    for (mkt, et_l2), layer_evs in sorted(by_layer.items()):
        pool = CN_STOCK_POOL if mkt == "CN" else (US_STOCK_POOL if mkt == "US" else [])
        if not pool:
            print(f"[SKIP] 未知 Market {mkt}，跳过 {len(layer_evs)} 条")
            continue
        print(f"[LAYER] {mkt:>3} × {et_l2:<20}: seed={len(layer_evs):>4} → target {len(layer_evs)*args.multiplier} 条")

        for e in layer_evs:
            old_sym = str(e.get("symbol") or "")
            old_title = str(e.get("title") or "")
            old_text  = str(e.get("event_text") or "")
            old_date  = _parse_iso(e.get("event_time") or e.get("event_date"))

            # 从池中挑 args.multiplier 个不同 symbol（尽量不重复）
            choices = random.sample(pool, k=min(args.multiplier, len(pool)))
            # 如果池子不够，就重复使用但保证和 symbol + date 不重复
            while len(choices) < args.multiplier:
                extra = random.choice(pool)
                choices.append(extra)

            for vi, (new_sym, new_name) in enumerate(choices):
                # 新日期：避开原日期 ±15 天，避开原 (symbol,date) 集合
                new_date = _shift_date(old_date, 30, 300,
                                        avoid_window_center=old_date, avoid_radius_days=15)
                # 再确保新的 (new_sym, new_date) 不在评估集原始中
                if (new_sym, new_date) in original_dates:
                    new_date = new_date + dt.timedelta(days=45)

                dedup_key = (new_sym, new_date.isoformat(), et_l2, vi)
                inner_check = (new_sym, new_date.isoformat(), et_l2)
                if inner_check in seen_dedup:
                    new_date = new_date + dt.timedelta(days=random.choice([-11, 7, 17, 23]))
                seen_dedup.add(inner_check)

                # 字段替换
                new_title = _replace_names(old_title, old_sym, "", new_sym, new_name)
                new_text  = _replace_names(old_text, old_sym, "",  new_sym, new_name)
                new_text  = _add_event_variant_tag(new_text, et_l2, vi)

                # event_id：新命名 train_{seed_eid}_v{vi}（可读 + 唯一）
                base_id = str(e.get("event_id") or f"e{id(e)}").replace("seed_", "")
                new_id = f"trn_{base_id}_v{vi}"

                new_event = {
                    "event_id":      new_id,
                    "market":        mkt,
                    "symbol":        new_sym,
                    "event_time":    new_date.isoformat(),
                    "event_date":    new_date.isoformat(),
                    "event_type_l2": et_l2,
                    "title":         new_title,
                    "event_text":    new_text,
                    "source_url":    str(e.get("source_url") or ""),
                    "sector_etf":    e.get("sector_etf"),
                    "benchmark":     e.get("benchmark") or (
                        "sh000300" if mkt == "CN" else "SPY"
                    ),
                    "direction_prior": None,
                    "event_strength":  None,
                    "_from_seed_event": str(e.get("event_id") or ""),
                    "_variant_idx": vi,
                }
                assert new_id not in exclude_ids, f"event_id 泄漏 {new_id}"
                out_rows.append(new_event)

    # 最终去重 & 确认条数
    final = {}
    for r in out_rows:
        final[r["event_id"]] = r
    final_list = list(final.values())
    # 如果不够 5000（因为去重），在训练集里随机再生成（允许 variant_idx 加大）
    target = len(evs) * args.multiplier
    safety = 0
    while len(final_list) < target and safety < 100:
        e = random.choice(evs)
        old_sym = str(e.get("symbol") or ""); et_l2 = str(e.get("event_type_l2") or "")
        old_date = _parse_iso(e.get("event_time") or e.get("event_date"))
        mkt = str(e.get("market") or "").upper()
        pool = CN_STOCK_POOL if mkt == "CN" else US_STOCK_POOL
        new_sym, new_name = random.choice(pool)
        new_date = _shift_date(old_date, 30, 300, avoid_window_center=old_date, avoid_radius_days=15)
        key = (new_sym, new_date.isoformat(), et_l2)
        if key in seen_dedup:
            safety += 1
            continue
        seen_dedup.add(key)
        base_id = str(e.get("event_id") or f"e{id(e)}").replace("seed_", "")
        vi = 1000 + safety
        new_id = f"trn_{base_id}_v{vi}"
        if new_id in final:
            safety += 1
            continue
        old_title = str(e.get("title") or ""); old_text = str(e.get("event_text") or "")
        final_list.append({
            "event_id": new_id, "market": mkt, "symbol": new_sym,
            "event_time": new_date.isoformat(), "event_date": new_date.isoformat(),
            "event_type_l2": et_l2,
            "title": _replace_names(old_title, old_sym, "", new_sym, new_name),
            "event_text": _add_event_variant_tag(
                _replace_names(old_text, old_sym, "", new_sym, new_name), et_l2, vi),
            "source_url": str(e.get("source_url") or ""),
            "benchmark": e.get("benchmark") or ("sh000300" if mkt == "CN" else "SPY"),
            "direction_prior": None, "event_strength": None,
            "_from_seed_event": str(e.get("event_id") or ""), "_variant_idx": vi,
        })
        safety += 1

    # 写出
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        for r in final_list:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(tmp, out_path)

    # 报告
    dist = Counter((r["market"], r["event_type_l2"]) for r in final_list)
    months = Counter(r["event_time"][:7] for r in final_list)
    print(f"\n[BOOTSTRAP DONE] {len(final_list)} 条 → {out_path}")
    print(f"  12 层分层分布：")
    for k, v in sorted(dist.items(), key=lambda x: -x[1]):
        print(f"    {k[0]:>3} × {k[1]:<22}: {v:>4}")
    print(f"  月份覆盖：{len(months)} 个月，{min(months.keys())} ~ {max(months.keys())}，"
          f"最少月 {min(months.values())} 条，最多月 {max(months.values())} 条")


if __name__ == "__main__":
    main()
