#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Pronoia 前向事件收集 (Step 1)
针对 T-1 / 3 / 7 / 14 / 30 / 60 六个事件观测窗口，从真实数据源收集
"分布要广" 的事件（市场 × 事件类型 × 时间窗），写入 events_forward.jsonl。
"""
from __future__ import annotations
import os, re, sys, json, time, hashlib, datetime as dt, warnings, argparse
from pathlib import Path
warnings.filterwarnings("ignore")
import akshare as ak

# ---- 不走沙箱代理，用远程机直连 ----
for k in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "all_proxy"):
    os.environ.pop(k, None)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]

TODAY = dt.date.today()  # 2026-09-04
WINDOW_DAYS = {"T-1": 1, "T-3": 3, "T-7": 7, "T-14": 14, "T-30": 30, "T-60": 60}

# ---------------- 分类 (对齐 collector._match_cn_type / _match_us_type) ----------------
NEG_TITLE = re.compile(r"(进展公告|进展情况|法律意见书|回购股份进展|注销回购|减少注册资本|担保|"
                       r"提示性公告|更正|补充公告|取消|登记|办理|确认|提示|说明|"
                       r"股东大会|董事会决议|监事会决议|召开|网络投票|委托|授权|"
                       r"投资者关系活动|投资者交流|调研活动|解读会|电话交流会|分析师会议|"
                       r"纪要|关系活动记录表|问答|接待|交流纪要|现场参观|路演)")

def match_cn_type(title: str, snippet: str = "") -> str | None:
    t = f"{title} {snippet}"
    # 业绩预告 / 快报 / 定期报告 —— 离散、驱动价格
    if re.search(r"(业绩预告|业绩快报|年度业绩|半年度业绩|前三季度业绩|"
                  r"半年报|半年度报告|年度报告|一季报|一季度报告|三季度报告|中报|年报|季度报告)", t):
        return "财报超预期/不及预期"
    # 重组 / 收购 / 分拆 / 再融资
    if re.search(r"(重大资产重组|重组报告书|收购报告书|吸收合并|分拆|"
                  r"定增|非公开发行|配股|可转债预案|发行股份购买资产)", t):
        return "并购/分拆/再融资"
    # 指引
    if re.search(r"(盈利预测|业绩指引|业绩展望|经营目标|年度目标|"
                  r"上调.*?(预期|预测|指引)|下调.*?(预期|预测|指引))", t):
        return "公司指引上调/下调"
    # 退而求其次：标题含明显业绩方向词的预告归入财报
    if re.search(r"(预增|预减|扭亏|续盈|续亏|首亏|增亏)", t) and re.search(r"(预告|业绩)", t):
        return "财报超预期/不及预期"
    return None


# 财报事件质量分：预告带方向 > 快报 > 定期报告全文
def cn_financial_quality(title: str) -> int:
    t = title
    if re.search(r"(预增|预减|扭亏|续盈|续亏|首亏|增亏|续亏)", t) and re.search(r"(业绩预告|预告)", t):
        return 5  # 业绩预告带方向 —— 最优
    if re.search(r"业绩预告", t):
        return 4
    if re.search(r"业绩快报", t):
        return 3
    if re.search(r"(半年报|半年度报告|年度报告|一季报|三季度报告|中报|年报)", t):
        return 2  # 定期报告全文 —— 兜底
    return 1


# 并购事件质量分：主报告 > 摘要/预案 > 子文件(会计师/财务顾问/评估/法律)
def cn_ma_quality(title: str) -> int:
    t = title
    if re.search(r"(重大资产重组报告书|收购报告书|发行股份购买资产.*?报告书|重组报告书)", t) and not re.search(r"(上会稿|申报稿|注册稿)", t):
        return 5  # 正式报告书
    if re.search(r"(重大资产重组报告书|收购报告书|发行股份购买资产.*?报告书|重组报告书)", t):
        return 4  # 上会/申报/注册稿
    if re.search(r"(预案|摘要|新增股份变动|配股.*?上市公告|可转债募集|发行公告)", t):
        return 3
    # 子文件：会计师/财务顾问/评估/法律/核查/补充/回复 —— 低优先
    if re.search(r"(会计师|审计|财务顾问|评估报告|估值报告|法律意见|律师|核查|回复|意见函|补充|更正)", t):
        return 1
    return 2


def match_us_type(filing_type: str, title: str) -> str | None:
    text = f"{filing_type} {title}".lower()
    if re.search(r"(merger|acquisition|acquire|spin[- ]?off|divestiture|business combination)", text):
        return "并购/分拆/再融资"
    if filing_type in {"10-k", "10-q", "10-k/a", "10-q/a", "20-f"} or re.search(
        r"(earnings|financial results|quarterly results|annual results|results for the quarter)", text):
        return "财报超预期/不及预期"
    if re.search(r"(guidance|outlook|forecast|reaffirms|raises guidance|lowers guidance)", text):
        return "公司指引上调/下调"
    return None


def slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return s[:32] or "event"

def digest(*parts: str) -> str:
    return hashlib.md5("||".join(str(x or "") for x in parts).encode()).hexdigest()[:10]


def cn_benchmark(symbol: str) -> str:
    return "sh000300"


# ---------------- CN 公告收集 ----------------
CN_KEYWORDS = ["业绩预告", "业绩快报", "重大资产重组", "重组报告书", "收购报告书",
               "吸收合并", "定增", "非公开发行", "配股", "可转债", "盈利预测", "业绩指引"]


def collect_cn_for_date(d: dt.date, window_label: str, per_cell_target: int) -> list[dict]:
    d8 = d.strftime("%Y%m%d")
    out: list[dict] = []
    try:
        df = ak.stock_notice_report(symbol="全部", date=d8)
    except Exception as e:
        print(f"[CN {d8}] fetch err: {repr(e)[:120]}", flush=True)
        return out
    if df is None or len(df) == 0:
        print(f"[CN {d8}] no announcements (非交易日?)", flush=True)
        return out

    # 按 (类型) 桶收集，保证类型多样性
    buckets: dict[str, list[dict]] = {}
    for _, r in df.iterrows():
        title = str(r.get("公告标题") or "").strip()
        etype_raw = str(r.get("公告类型") or "").strip()
        code = str(r.get("代码") or "").strip()
        name = str(r.get("名称") or "").strip()
        url = str(r.get("网址") or "").strip()
        pub = r.get("公告日期")
        if not title or not code or len(code) != 6 or not code.isdigit():
            continue
        if NEG_TITLE.search(title):
            continue  # 过滤进展/程序性公告
        etype = match_cn_type(title, etype_raw)
        if not etype:
            continue
        qscore = cn_financial_quality(title) if etype == "财报超预期/不及预期" else cn_ma_quality(title)
        # 财报事件最低门槛：至少是定期报告全文(q>=2)或预告/快报(q>=3)
        if etype == "财报超预期/不及预期" and qscore < 2:
            continue
        event_time = pub.isoformat() if hasattr(pub, "isoformat") else d.isoformat()
        event_text = f"{title} | {code} {name} · {etype_raw}"
        eid = f"fwd_cn_{slug(code)}_{slug(etype)}_{digest(code, event_time, title)}"
        rec = {
            "event_id": eid,
            "market": "CN",
            "symbol": code,
            "event_time": event_time,
            "event_date": event_time[:10],
            "event_type_l2": etype,
            "title": title[:120],
            "event_text": event_text[:400],
            "source_url": url,
            "sector_etf": None,
            "benchmark": cn_benchmark(code),
            "direction_prior": None,
            "event_strength": None,
            "_source": "akshare.stock_notice_report",
            "_window": window_label,
            "_name": name,
            "_qscore": qscore,
        }
        buckets.setdefault(etype, []).append(rec)

    for etype, lst in buckets.items():
        # 按质量分降序（主报告/预告带方向 优先，子文件/全文 次之）
        lst.sort(key=lambda r: r.get("_qscore", 0), reverse=True)
        # 按 symbol 去重：每家公司只留 1 条（取质量最高的主文件，避免同一交易多份子文件充数）
        seen_sym = set(); dedup = []
        for r in lst:
            if r["symbol"] in seen_sym:
                continue
            seen_sym.add(r["symbol"])
            dedup.append(r)
        out.extend(dedup[:per_cell_target])
    print(f"[CN {d8} {window_label}] raw={len(df)}  kept={len(out)}  types={ {k: len(v) for k,v in buckets.items()} }", flush=True)
    return out


# ---------------- US SEC 收集 (EDGAR 官方 API，可靠无限流) ----------------
US_TICKERS = ["NVDA", "AAPL", "TSLA", "META", "AMD", "JPM", "MSFT", "AMZN", "GOOGL", "NFLX", "INTC", "BABA"]
EDGAR_UA = "Pronoia-Research admin@example.com"
_TICKER_CIK: dict | None = None


def _load_ticker_cik() -> dict:
    global _TICKER_CIK
    if _TICKER_CIK is not None:
        return _TICKER_CIK
    import urllib.request
    try:
        req = urllib.request.Request("https://www.sec.gov/files/company_tickers.json",
                                     headers={"User-Agent": EDGAR_UA})
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = json.load(r)
        _TICKER_CIK = {v["ticker"]: v["cik_str"] for v in raw.values()}
        print(f"[US] ticker->CIK 映射 {len(_TICKER_CIK)} 条", flush=True)
    except Exception as e:
        print(f"[US] company_tickers fetch err: {repr(e)[:120]}", flush=True)
        _TICKER_CIK = {}
    return _TICKER_CIK


def _edgar_classify(form: str, items: str) -> str | None:
    """EDGAR form/items → Pronoia 类型。"""
    form = (form or "").strip()
    items = (items or "").strip()
    # 财报：10-K/10-Q 定期报告；8-K 含 2.02(经营业绩) / 9.01(财务报表)
    if form in {"10-K", "10-Q", "10-K/A", "10-Q/A", "20-F", "40-F"}:
        return "财报超预期/不及预期"
    if form == "8-K" and ("2.02" in items or "9.01" in items):
        return "财报超预期/不及预期"
    # 并购：425(企业合并)、S-4、DEFM14A、8-K 含 2.01(收购完成)/1.01(实质性协议)
    if form in {"425", "S-4", "S-4/A", "DEFM14A", "PREM14A", "424B3", "424B5"}:
        return "并购/分拆/再融资"
    if form == "8-K" and ("2.01" in items or "1.01" in items or "1.02" in items):
        return "并购/分拆/再融资"
    return None


def collect_us_sec(per_cell_target: int) -> list[dict]:
    out: list[dict] = []
    import urllib.request
    tc = _load_ticker_cik()
    if not tc:
        return out
    buckets: dict[str, list[dict]] = {}
    n_tk = 0
    for sym in US_TICKERS:
        cik = tc.get(sym)
        if not cik:
            continue
        url = f"https://data.sec.gov/submissions/CIK{str(cik).zfill(10)}.json"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": EDGAR_UA})
            with urllib.request.urlopen(req, timeout=20) as r:
                d = json.load(r)
        except Exception as e:
            print(f"[US {sym}] submissions err: {repr(e)[:100]}", flush=True)
            continue
        rec_name = (d.get("name") or sym)[:40]
        recent = (d.get("filings") or {}).get("recent") or {}
        forms = recent.get("form") or []
        dates = recent.get("filingDate") or []
        items_arr = recent.get("items") or []
        docs = recent.get("primaryDocument") or []
        accs = recent.get("accessionNumber") or []
        if not forms:
            continue
        for i, form in enumerate(forms):
            try:
                fdate = (dates[i] if i < len(dates) else "")[:10]
                if not fdate:
                    continue
                age = (TODAY - dt.date.fromisoformat(fdate)).days
                if age > 60 or age < 0:
                    continue
                items = items_arr[i] if i < len(items_arr) else ""
                etype = _edgar_classify(form, items)
                if not etype:
                    continue
                doc = docs[i] if i < len(docs) else ""
                acc = accs[i] if i < len(accs) else ""
                acc_nodash = acc.replace("-", "")
                title = f"{rec_name} {form}"
                if items:
                    title += f" items:{items}"
                ev_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nodash}/{doc}" if doc else url
                benchmark = "QQQ" if re.search(r"(nvda|amd|intc|msft|meta|aapl|googl|amzn|nflx|technology|ai|gpu|semiconductor|software|cloud)",
                                                sym.lower()) else "SPY"
                eid = f"fwd_us_{slug(sym)}_{slug(etype)}_{digest(sym, fdate, title)}"
                rec = {
                    "event_id": eid, "market": "US", "symbol": sym,
                    "event_time": fdate, "event_date": fdate,
                    "event_type_l2": etype, "title": title[:120],
                    "event_text": f"EDGAR {form} | {rec_name} | items:{items}"[:400],
                    "source_url": ev_url, "sector_etf": None,
                    "benchmark": benchmark, "direction_prior": None,
                    "event_strength": None, "_source": "sec.edgar.submissions",
                    "_name": rec_name, "_age_days": age,
                }
                buckets.setdefault(etype, []).append(rec)
                n_tk += 1
            except Exception:
                continue
        time.sleep(0.5)  # EDGAR 礼貌限速
    for etype, lst in buckets.items():
        seen = set(); dedup = []
        for r in lst:
            k = (r["symbol"], r["title"][:40], r["event_date"])
            if k in seen: continue
            seen.add(k); dedup.append(r)
        out.extend(dedup[:per_cell_target])
    print(f"[US] candidates={n_tk}  kept={len(out)}  types={ {k: len(v) for k,v in buckets.items()} }", flush=True)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(_PROJECT_ROOT / "pronoia_run" / "forward_test" / "events_forward.jsonl"))
    ap.add_argument("--per-cell", type=int, default=4, help="每 (窗口×类型) 最多保留多少条")
    ap.add_argument("--skip-us", action="store_true")
    args = ap.parse_args()

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    all_events: list[dict] = []

    print(f"=== Pronoia 前向事件收集  today={TODAY} ===", flush=True)
    for wlabel, nday in WINDOW_DAYS.items():
        d = TODAY - dt.timedelta(days=nday)
        evs = collect_cn_for_date(d, wlabel, args.per_cell)
        # 标注窗口
        for e in evs:
            e["_window"] = wlabel
            e["_age_days"] = nday
        all_events.extend(evs)
        time.sleep(1.0)

    if not args.skip_us:
        us_evs = collect_us_sec(per_cell_target=3)
        # US 事件按 age 归入最近窗口标签
        for e in us_evs:
            age = e.get("_age_days", 999)
            e["_window"] = _nearest_window(age)
        all_events.extend(us_evs)

    # 全局去重 (event_id)
    seen = set(); final = []
    for e in all_events:
        if e["event_id"] in seen:
            continue
        seen.add(e["event_id"])
        final.append(e)

    with open(args.out, "w", encoding="utf-8") as f:
        for e in final:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")

    # ---- 汇总 ----
    import collections
    by_win = collections.Counter(e["_window"] for e in final)
    by_type = collections.Counter(e["event_type_l2"] for e in final)
    by_mkt = collections.Counter(e["market"] for e in final)
    by_wt = collections.Counter((e["_window"], e["event_type_l2"]) for e in final)
    print(f"\n=== 汇总: 共 {len(final)} 条事件 → {args.out} ===", flush=True)
    print(f"窗口分布: {dict(by_win)}", flush=True)
    print(f"类型分布: {dict(by_type)}", flush=True)
    print(f"市场分布: {dict(by_mkt)}", flush=True)
    print("窗口×类型:", flush=True)
    for k, v in sorted(by_wt.items()):
        print(f"  {k[0]:5s} {k[1]:22s} : {v}", flush=True)
    print("\n样本(前 15):", flush=True)
    for e in final[:15]:
        print(f"  [{e['_window']}] {e['market']} {e['symbol']} {e['event_date']} | {e['event_type_l2']} | {e['title'][:50]}", flush=True)
    print("DONE_COLLECT", flush=True)


def _nearest_window(age: int) -> str:
    best = "T-60"; best_diff = 999
    for wl, nd in WINDOW_DAYS.items():
        diff = abs(age - nd)
        if diff < best_diff:
            best_diff = diff; best = wl
    return best


if __name__ == "__main__":
    main()
